import traceback
from ipaddress import IPv4Interface
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
from ansible_collections.bofzilla.icx.plugins.module_utils.switching import parse_ve_interfaces, parse_vlans

DOCUMENTATION = r"""
module: vlans
short_description: Configure VLAN definitions on a Brocade ICX switch
description:
  - Manages VLAN existence, names, VE router-interface attachment and IPv4
    addressing, and the management-vlan flag. Port membership is intentionally
    owned by the interfaces module.
  - FastIron does not instantiate a VE until its VLAN has a tagged or untagged
    member port. On factory-reset devices, apply C(bofzilla.icx.interfaces)
    before this module when configuring C(ip_address).
options:
  vlans:
    description:
      - VLAN definitions to manage.
      - Port membership is managed by C(bofzilla.icx.interfaces), not here.
    type: list
    elements: dict
    required: true
    suboptions:
      id:
        description:
          - VLAN ID.
        type: int
        required: true
      name:
        description:
          - Optional VLAN name.
        type: str
      router_interface:
        description:
          - VE ID to attach to the VLAN with C(router-interface ve).
        type: int
      ip_address:
        description:
          - Static IPv4 address and prefix for the attached VE.
          - Requires C(router_interface).
          - The VLAN must already have a tagged or untagged member port.
        type: str
      management:
        description:
          - Whether to mark the VLAN with FastIron C(management-vlan).
          - This is in-band management VLAN behavior, not the physical OOB management port.
          - Supported by FastIron switch images only; omit it on router images.
        type: bool
        default: false
      state:
        description:
          - Whether the VLAN should exist.
        type: str
        choices: [present, absent]
        default: present
  purge:
    description:
      - Remove VLANs not listed in C(vlans).
    type: bool
    default: false
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
- bofzilla.icx.vlans:
    vlans:
      - id: 10
        name: servers
        router_interface: 10
        ip_address: 10.0.10.2/24
      - id: 99
        name: management
        management: true
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
vlans:
  description: Normalized desired VLAN definitions.
  type: list
"""


def _normalize_ip_address(value: str) -> str:
	parts = value.split()
	return str(IPv4Interface(parts[0] if len(parts) == 1 else f"{parts[0]}/{parts[1]}"))


def _desired(params: dict[str, Any], current: dict[int, dict[str, Any]], current_ve: dict[int, dict[str, Any]]) -> dict[int, dict[str, Any]]:
	desired: dict[int, dict[str, Any]] = {vlan_id: dict(vlan) for vlan_id, vlan in current.items()}
	if params.get("purge"):
		desired = {}
	for item in params["vlans"]:
		vlan_id = int(item["id"])
		state = item.get("state", "present")
		if state == "absent":
			desired.pop(vlan_id, None)
			continue
		router_interface = item.get("router_interface")
		if item.get("ip_address") and not router_interface:
			raise ValueError(f"VLAN {vlan_id}: ip_address requires router_interface")
		current_addresses = current_ve.get(router_interface, {}).get("ip_addresses", []) if router_interface else []
		desired[vlan_id] = {
			"id": vlan_id,
			"name": item.get("name"),
			"router_interface": router_interface,
			"ip_address": str(IPv4Interface(item["ip_address"])) if item.get("ip_address") else (_normalize_ip_address(current_addresses[0]) if current_addresses else None),
			"management": item.get("management", False),
			"tagged": current.get(vlan_id, {}).get("tagged", []),
			"untagged": current.get(vlan_id, {}).get("untagged", []),
			"default_gateways": current.get(vlan_id, {}).get("default_gateways", []),
		}
	return desired


def _commands(params: dict[str, Any], current: dict[int, dict[str, Any]], current_ve: dict[int, dict[str, Any]], desired: dict[int, dict[str, Any]]) -> list[ConfigLine]:
	cmds: list[ConfigLine] = []
	target_ids = set(desired)
	if params.get("purge"):
		target_ids |= set(current)
	else:
		target_ids |= {item["id"] for item in params["vlans"]}
	for vlan_id in sorted(target_ids):
		cur = current.get(vlan_id)
		des = desired.get(vlan_id)
		if des is None:
			if cur is not None:
				cmds.append(ConfigLine(f"no vlan {vlan_id}"))
			continue
		if cur is None or cur.get("name") != des.get("name"):
			cmds.append(ConfigLine(vlan_header(vlan_id, des.get("name"))))
		mode = vlan_header(vlan_id, des.get("name"))
		if cur is None or cur.get("router_interface") != des.get("router_interface"):
			if cur and cur.get("router_interface"):
				cmds.append(ConfigLine(f"no router-interface ve {cur['router_interface']}", mode))
			if des.get("router_interface"):
				cmds.append(ConfigLine(f"router-interface ve {des['router_interface']}", mode))
		if des.get("management") and not (cur or {}).get("management", False):
			cmds.append(ConfigLine("management-vlan", mode))
		elif cur and cur.get("management", False) and not des.get("management"):
			cmds.append(ConfigLine("no management-vlan", mode))
		item = next((item for item in params["vlans"] if int(item["id"]) == vlan_id), {})
		if item.get("ip_address"):
			ve_mode = f"interface ve {des['router_interface']}"
			current_addresses = current_ve.get(des["router_interface"], {}).get("ip_addresses", [])
			normalized = [_normalize_ip_address(address) for address in current_addresses]
			if des["ip_address"] in normalized:
				for raw, address in zip(current_addresses, normalized, strict=True):
					if address != des["ip_address"]:
						cmds.append(ConfigLine(f"no ip address {raw}", ve_mode))
			else:
				for raw in current_addresses:
					cmds.append(ConfigLine(f"no ip address {raw}", ve_mode))
				cmds.append(ConfigLine(f"ip address {des['ip_address']}", ve_mode))
	return cmds


def _serialize(vlans: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
	return [{key: vlan.get(key) for key in ("id", "name", "router_interface", "ip_address", "management")} for vlan in (vlans[vlan_id] for vlan_id in sorted(vlans))]


def main():
	module = AnsibleModule(
		argument_spec={
			**ICX_ARGUMENT_SPEC,
			**SAVE_WHEN_ARGUMENT_SPEC,
			"vlans": {
				"type": "list",
				"elements": "dict",
				"required": True,
				"options": {
					"id": {"type": "int", "required": True},
					"name": {"type": "str"},
					"router_interface": {"type": "int"},
					"ip_address": {"type": "str"},
					"management": {"type": "bool", "default": False},
					"state": {"type": "str", "choices": ["present", "absent"], "default": "present"},
				},
			},
			"purge": {"type": "bool", "default": False},
		},
		supports_check_mode=True,
	)
	try:
		client = CliClient(Connection(module._socket_path), enable_password=module.params.get("enable_password"))
		running_config = client.run(ShowRunningConfig())
		current = parse_vlans(running_config)
		current_ve = parse_ve_interfaces(running_config)
		desired = _desired(module.params, current, current_ve)
		cmds = _commands(module.params, current, current_ve, desired)
		changed = bool(cmds)
		saved = run_config_commands(client, module, cmds, changed, resolve_save_when(module.params))
		result: dict[str, Any] = {
			"changed": changed,
			"vlans": _serialize(desired),
			"command": command_strings(cmds, saved),
			"saved": saved,
		}
		if changed and getattr(module, "_diff", False):
			result["diff"] = json_diff(_serialize(current), _serialize(desired))
		module.exit_json(**result)
	except Exception as err:
		module.fail_json(msg=f"{type(err).__name__}: {err}", exception=traceback.format_exc())


if __name__ == "__main__":
	main()
