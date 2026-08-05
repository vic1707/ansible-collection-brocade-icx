import traceback
from typing import Any

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.connection import Connection

from ansible_collections.bofzilla.icx.plugins.module_utils.cli_client import ICX_ARGUMENT_SPEC, CliClient
from ansible_collections.bofzilla.icx.plugins.module_utils.commands.config import ConfigLine, ShowRunningConfig
from ansible_collections.bofzilla.icx.plugins.module_utils.module_common import (
	SAVE_WHEN_ARGUMENT_SPEC,
	command_strings,
	json_diff,
	resolve_save_when,
	run_config_commands,
	vlan_header,
)
from ansible_collections.bofzilla.icx.plugins.module_utils.switching import parse_interfaces

SPEED_DUPLEX_CHOICES = [
	"10-full",
	"10-half",
	"100-full",
	"100-half",
	"1000-full",
	"1000-full-master",
	"1000-full-slave",
	"10g-full",
	"10g-full-master",
	"10g-full-slave",
	"2500-full",
	"2500-full-master",
	"2500-full-slave",
	"auto",
]

DOCUMENTATION = r"""
module: interfaces
short_description: Configure Ethernet interfaces on a Brocade ICX switch
description:
  - Provides intent-based access/trunk/general port configuration over ICX
    tagged, untagged, and dual-mode commands.
options:
  interfaces:
    description:
      - Ethernet interface intents and per-port settings to manage.
      - Omitted fields are left untouched, except for VLAN membership fields
        implied by C(mode).
    type: list
    elements: dict
    required: true
    suboptions:
      name:
        description:
          - Single Ethernet port name, for example C(1/1/1) or C(1/2/1).
          - Port ranges are not accepted; provide one item per port.
        type: str
        required: true
      description:
        description:
          - Port name/comment configured with FastIron C(port-name).
        type: str
      mode:
        description:
          - VLAN membership intent for the port.
          - C(access) makes the port untagged in exactly one VLAN and removes tagged VLAN membership.
          - C(trunk) makes the port tagged-only for C(allowed_vlans), with no native/untagged VLAN.
          - C(general) makes the port tagged for C(allowed_vlans) and sets one native/untagged VLAN with ICX C(dual-mode).
        type: str
        choices: [access, trunk, general]
      access_vlan:
        description:
          - Untagged VLAN for C(mode=access). Defaults to C(1) when C(mode=access).
        type: int
      allowed_vlans:
        description:
          - Tagged VLANs for C(mode=trunk) and C(mode=general).
        type: list
        elements: int
      native_vlan:
        description:
          - Native/untagged VLAN for C(mode=general), implemented with ICX C(dual-mode).
          - Invalid with C(mode=trunk), because trunks are tagged-only in this module.
        type: int
      admin_state:
        description:
          - Administrative port state.
        type: str
        choices: [up, down]
      speed_duplex:
        description:
          - FastIron C(speed-duplex) value, or C(auto) to remove explicit speed-duplex config.
        type: str
      voice_vlan:
        description:
          - Voice VLAN ID configured with C(voice-vlan).
        type: int
      poe:
        description:
          - Power over Ethernet settings for the port.
        type: dict
        suboptions:
          enabled:
            description:
              - Whether inline power should be enabled.
            type: bool
          priority:
            description:
              - Inline power priority.
            type: int
          power_limit:
            description:
              - Inline power limit.
            type: int
          power_by_class:
            description:
              - Inline power class limit.
            type: int
          decouple_datalink:
            description:
              - Whether inline power should stay decoupled from data link state.
            type: bool
  save_when:
    description:
      - When to save running-config to startup-config.
    type: str
    choices: [changed, always, never]
    default: changed
author:
  - bofzilla
"""

EXAMPLES = r"""
- bofzilla.icx.interfaces:
    interfaces:
      - name: 1/1/1
        description: uplink
        mode: trunk
        allowed_vlans: [10, 20, 30]
      - name: 1/1/2
        mode: access
        access_vlan: 10
        poe:
          enabled: true
          priority: 2
      - name: 1/1/3
        mode: general
        native_vlan: 10
        allowed_vlans: [10, 20, 30]
"""

RETURN = r"""
changed:
  description: Whether any configuration changed.
  type: bool
command:
  description: Commands sent or planned.
  type: list
  elements: str
saved:
  description: Whether write memory was run or planned.
  type: bool
interfaces:
  description: Normalized desired interface settings.
  type: list
"""


def _desired(item: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
	_validate_item(item)
	desired = {
		"name": item["name"],
		"description": current.get("description"),
		"admin_state": current.get("admin_state", "up"),
		"speed_duplex": current.get("speed_duplex"),
		"voice_vlan": current.get("voice_vlan"),
		"mode": item.get("mode"),
		"access_vlan": current.get("untagged_vlan"),
		"native_vlan": current.get("dual_mode"),
		"allowed_vlans": current.get("tagged_vlans", []),
		"poe": dict(current.get("poe", {"enabled": None})),
	}
	for key in ("description", "admin_state", "speed_duplex", "voice_vlan"):
		if item.get(key) is not None:
			desired[key] = item[key]
	if item.get("mode") == "access":
		desired["access_vlan"] = item.get("access_vlan", 1)
		desired["allowed_vlans"] = []
		desired["native_vlan"] = None
	elif item.get("mode") in {"trunk", "general"}:
		desired["allowed_vlans"] = sorted(set(item.get("allowed_vlans") or []))
		desired["native_vlan"] = item.get("native_vlan")
		desired["access_vlan"] = None
	if item.get("poe"):
		desired["poe"].update({key: value for key, value in item["poe"].items() if value is not None})
	return desired


def _validate_item(item: dict[str, Any]) -> None:
	if " to " in item["name"]:
		raise ValueError(f"interface {item['name']}: port ranges are unsupported; provide one item per port")
	mode = item.get("mode")
	if mode == "access":
		if item.get("allowed_vlans") is not None:
			raise ValueError(f"interface {item['name']}: allowed_vlans is invalid with mode=access")
		if item.get("native_vlan") is not None:
			raise ValueError(f"interface {item['name']}: native_vlan is invalid with mode=access")
	elif mode == "trunk":
		if item.get("access_vlan") is not None:
			raise ValueError(f"interface {item['name']}: access_vlan is invalid with mode=trunk")
		if item.get("native_vlan") is not None:
			raise ValueError(f"interface {item['name']}: native_vlan is invalid with mode=trunk; use mode=general for a native VLAN")
	elif mode == "general":
		if item.get("access_vlan") is not None:
			raise ValueError(f"interface {item['name']}: access_vlan is invalid with mode=general")
		if item.get("native_vlan") is None:
			raise ValueError(f"interface {item['name']}: native_vlan is required with mode=general")
	for vlan_id in [item.get("access_vlan"), item.get("native_vlan"), *(item.get("allowed_vlans") or [])]:
		if vlan_id is not None and not 1 <= vlan_id <= 4094:
			raise ValueError(f"interface {item['name']}: VLAN ID must be between 1 and 4094: {vlan_id}")


def _current_intent(current: dict[str, Any]) -> dict[str, Any]:
	if current.get("dual_mode"):
		mode = "general"
	elif current.get("tagged_vlans"):
		mode = "trunk"
	else:
		mode = "access"
	item: dict[str, Any] = {"name": current["name"], "mode": mode}
	if mode == "access":
		item["access_vlan"] = current.get("untagged_vlan", 1)
	else:
		item["allowed_vlans"] = current.get("tagged_vlans", [])
	if mode == "general":
		item["native_vlan"] = current["dual_mode"]
	return _desired(item, current)


def _membership_commands(current: dict[str, Any], desired: dict[str, Any]) -> list[ConfigLine]:
	cmds: list[ConfigLine] = []
	name = desired["name"]
	current_tagged = set(current.get("tagged_vlans", []))
	desired_tagged = set(desired.get("allowed_vlans") or [])
	current_untagged = current.get("untagged_vlan")
	desired_untagged = desired.get("access_vlan")
	removed_nondefault = current_untagged != desired_untagged and current_untagged not in {None, 1}
	for vlan_id in sorted(current_tagged - desired_tagged):
		cmds.append(ConfigLine(f"no tagged ethernet {name}", vlan_header(vlan_id)))
	if removed_nondefault and current_untagged is not None:
		cmds.append(ConfigLine(f"no untagged ethernet {name}", vlan_header(int(current_untagged))))
	for vlan_id in sorted(desired_tagged - current_tagged):
		cmds.append(ConfigLine(f"tagged ethernet {name}", vlan_header(vlan_id)))
	if current_untagged != desired_untagged:
		if current_untagged and not removed_nondefault:
			cmds.append(ConfigLine(f"no untagged ethernet {name}", vlan_header(current_untagged)))
		if desired_untagged:
			cmds.append(ConfigLine(f"untagged ethernet {name}", vlan_header(desired_untagged)))
	if current.get("dual_mode") != desired.get("native_vlan"):
		if current.get("dual_mode"):
			cmds.append(ConfigLine(f"no dual-mode {current['dual_mode']}", f"interface ethernet {name}"))
		if desired.get("native_vlan"):
			if desired["native_vlan"] not in desired_tagged:
				cmds.append(ConfigLine(f"tagged ethernet {name}", vlan_header(desired["native_vlan"])))
			cmds.append(ConfigLine(f"dual-mode {desired['native_vlan']}", f"interface ethernet {name}"))
	return cmds


def _poe_command(poe: dict[str, Any]) -> str:
	if poe.get("enabled") is False:
		return "no inline power"
	parts = ["inline power"]
	if poe.get("decouple_datalink"):
		parts.append("decouple-datalink")
	if poe.get("power_by_class") is not None:
		parts.extend(["power-by-class", str(poe["power_by_class"])])
	if poe.get("power_limit") is not None:
		parts.extend(["power-limit", str(poe["power_limit"])])
	if poe.get("priority") is not None:
		parts.extend(["priority", str(poe["priority"])])
	return " ".join(parts)


def _commands(current: dict[str, Any], desired: dict[str, Any], item: dict[str, Any]) -> list[ConfigLine]:
	cmds = _membership_commands(current, desired)
	name = desired["name"]
	mode = f"interface ethernet {name}"
	if item.get("description") is not None and current.get("description") != desired.get("description"):
		if current.get("description"):
			cmds.append(ConfigLine(f"no port-name {current['description']}", mode))
		if desired.get("description"):
			cmds.append(ConfigLine(f"port-name {desired['description']}", mode))
	if item.get("admin_state") is not None and current.get("admin_state", "up") != desired.get("admin_state"):
		cmds.append(ConfigLine("disable" if desired["admin_state"] == "down" else "enable", mode))
	if item.get("speed_duplex") is not None and current.get("speed_duplex") != desired.get("speed_duplex"):
		cmds.append(ConfigLine("no speed-duplex" if desired["speed_duplex"] == "auto" else f"speed-duplex {desired['speed_duplex']}", mode))
	if item.get("voice_vlan") is not None and current.get("voice_vlan") != desired.get("voice_vlan"):
		if current.get("voice_vlan"):
			cmds.append(ConfigLine(f"no voice-vlan {current['voice_vlan']}", mode))
		if desired.get("voice_vlan"):
			cmds.append(ConfigLine(f"voice-vlan {desired['voice_vlan']}", mode))
	if item.get("poe") and current.get("poe", {}) != desired.get("poe", {}):
		cmds.append(ConfigLine(_poe_command(desired["poe"]), mode))
	return cmds


def main():
	module = AnsibleModule(
		argument_spec={
			**ICX_ARGUMENT_SPEC,
			**SAVE_WHEN_ARGUMENT_SPEC,
			"interfaces": {
				"type": "list",
				"elements": "dict",
				"required": True,
				"options": {
					"name": {"type": "str", "required": True},
					"description": {"type": "str"},
					"admin_state": {"type": "str", "choices": ["up", "down"]},
					"speed_duplex": {"type": "str", "choices": SPEED_DUPLEX_CHOICES},
					"voice_vlan": {"type": "int"},
					"mode": {"type": "str", "choices": ["access", "trunk", "general"]},
					"access_vlan": {"type": "int"},
					"native_vlan": {"type": "int"},
					"allowed_vlans": {"type": "list", "elements": "int"},
					"poe": {
						"type": "dict",
						"options": {
							"enabled": {"type": "bool"},
							"decouple_datalink": {"type": "bool"},
							"power_by_class": {"type": "int"},
							"power_limit": {"type": "int"},
							"priority": {"type": "int"},
						},
					},
				},
			},
		},
		supports_check_mode=True,
	)
	try:
		client = CliClient(Connection(module._socket_path), enable_password=module.params.get("enable_password"))
		current_all = parse_interfaces(client.run(ShowRunningConfig()))
		items = module.params["interfaces"]
		if len({item["name"] for item in items}) != len(items):
			raise ValueError("interface names must be unique")
		desired_items: list[dict[str, Any]] = []
		cmds: list[ConfigLine] = []
		current_items: list[dict[str, Any]] = []
		for item in items:
			current = current_all.get(item["name"], {"name": item["name"], "tagged_vlans": [], "untagged_vlan": None, "poe": {"enabled": None}})
			desired = _desired(item, current)
			current_items.append(_current_intent(current))
			desired_items.append(desired)
			cmds.extend(_commands(current, desired, item))
		changed = bool(cmds)
		saved = run_config_commands(client, module, cmds, changed, resolve_save_when(module.params))
		result: dict[str, Any] = {
			"changed": changed,
			"interfaces": desired_items,
			"command": command_strings(cmds, saved),
			"saved": saved,
		}
		if changed and getattr(module, "_diff", False):
			result["diff"] = json_diff(current_items, desired_items)
		module.exit_json(**result)
	except Exception as err:
		module.fail_json(msg=f"{type(err).__name__}: {err}", exception=traceback.format_exc())


if __name__ == "__main__":
	main()
