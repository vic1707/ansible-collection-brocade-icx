import traceback
from typing import Any

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.connection import Connection

from ansible_collections.bofzilla.icx.plugins.module_utils.cli_client import ICX_ARGUMENT_SPEC, CliClient
from ansible_collections.bofzilla.icx.plugins.module_utils.commands.config import ConfigLine, ShowRunningConfig
from ansible_collections.bofzilla.icx.plugins.module_utils.module_common import (
	SAVE_WHEN_ARGUMENT_SPEC,
	command_strings,
	global_config_lines,
	json_diff,
	resolve_save_when,
	run_config_commands,
	validate_ip,
	validate_ip_interface,
)

DOCUMENTATION = r"""
module: management_oob
short_description: Configure out-of-band management addressing on a Brocade ICX switch
description:
  - Manages the switch management address path exposed by the global FastIron
    management IP commands.
  - This module intentionally does not configure VLAN membership, VE interfaces,
    or Ethernet port tagging. Use C(bofzilla.icx.vlans) and
    C(bofzilla.icx.interfaces) for any in-band or patch-cable transport.
options:
  mode:
    description:
      - Addressing mode for the out-of-band management path.
      - C(dhcp) enables the FastIron DHCP client.
      - C(static) configures a global management IP address and optional gateway.
    type: str
    choices: [dhcp, static]
    required: true
  ip_address:
    description:
      - Static management IPv4 address and prefix.
      - Required when C(mode=static).
      - Invalid when C(mode=dhcp).
    type: str
  default_gateway:
    description:
      - Static default gateway for the management address.
      - Invalid when C(mode=dhcp).
    type: str
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
- bofzilla.icx.management_oob:
    mode: dhcp

- bofzilla.icx.management_oob:
    mode: static
    ip_address: 192.168.1.105/24
    default_gateway: 192.168.1.1
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
management_oob:
  description: Normalized desired out-of-band management state.
  type: dict
"""


def _normalize_ip_interface(value: str) -> str:
	parts = value.split()
	if len(parts) >= 2 and parts[1] != "dynamic":
		return validate_ip_interface(f"{parts[0]}/{parts[1]}")
	return validate_ip_interface(parts[0])


def _desired(params: dict[str, Any]) -> dict[str, Any]:
	mode = params["mode"]
	if mode == "dhcp" and params.get("ip_address"):
		raise ValueError("ip_address is only valid when mode=static")
	if mode == "dhcp" and params.get("default_gateway"):
		raise ValueError("default_gateway is only valid when mode=static")
	if mode == "static" and not params.get("ip_address"):
		raise ValueError("ip_address is required when mode=static")
	return {
		"mode": mode,
		"ip_address": validate_ip_interface(params["ip_address"]) if mode == "static" else None,
		"default_gateway": validate_ip(params["default_gateway"]) if mode == "static" and params.get("default_gateway") else None,
	}


def _current(raw: str) -> dict[str, Any]:
	lines = global_config_lines(raw)
	ip_address = None
	ip_address_raw = None
	dhcp_client = "ip dhcp-client enable" in lines
	default_gateway = None
	for line in lines:
		if line.startswith("ip address "):
			ip_address_raw = line.removeprefix("ip address ")
			dhcp_client = dhcp_client or ip_address_raw.endswith(" dynamic")
			ip_address = _normalize_ip_interface(ip_address_raw.removesuffix(" dynamic").strip())
		elif line.startswith("ip default-gateway "):
			default_gateway = validate_ip(line.removeprefix("ip default-gateway "))
	return {
		"mode": "dhcp" if dhcp_client else "static",
		"dhcp_client": dhcp_client,
		"ip_address": ip_address,
		"ip_address_raw": ip_address_raw,
		"default_gateway": default_gateway,
	}


def _commands(current: dict[str, Any], desired: dict[str, Any]) -> list[ConfigLine]:
	cmds: list[ConfigLine] = []

	if desired["mode"] == "dhcp":
		if current["mode"] == "static" and current.get("ip_address_raw"):
			cmds.append(ConfigLine(f"no ip address {current['ip_address_raw']}"))
		if current.get("default_gateway"):
			cmds.append(ConfigLine(f"no ip default-gateway {current['default_gateway']}"))
		if not current["dhcp_client"]:
			cmds.append(ConfigLine("ip dhcp-client enable"))
		return cmds

	if current["dhcp_client"]:
		cmds.append(ConfigLine("no ip dhcp-client enable"))
	if current.get("ip_address") != desired["ip_address"]:
		if current["mode"] == "static" and current.get("ip_address_raw"):
			cmds.append(ConfigLine(f"no ip address {current['ip_address_raw']}"))
		cmds.append(ConfigLine(f"ip address {desired['ip_address']}"))
	if current.get("default_gateway") != desired["default_gateway"]:
		if current.get("default_gateway"):
			cmds.append(ConfigLine(f"no ip default-gateway {current['default_gateway']}"))
		if desired.get("default_gateway"):
			cmds.append(ConfigLine(f"ip default-gateway {desired['default_gateway']}"))
	return cmds


def main():
	module = AnsibleModule(
		argument_spec={
			**ICX_ARGUMENT_SPEC,
			**SAVE_WHEN_ARGUMENT_SPEC,
			"mode": {"type": "str", "choices": ["dhcp", "static"], "required": True},
			"ip_address": {"type": "str"},
			"default_gateway": {"type": "str"},
		},
		supports_check_mode=True,
	)
	try:
		client = CliClient(Connection(module._socket_path), enable_password=module.params.get("enable_password"))
		current = _current(client.run(ShowRunningConfig()))
		desired = _desired(module.params)
		cmds = _commands(current, desired)
		changed = bool(cmds)
		saved = run_config_commands(client, module, cmds, changed, resolve_save_when(module.params))
		result = {
			"changed": changed,
			"management_oob": desired,
			"command": command_strings(cmds, saved),
			"saved": saved,
		}
		if changed and getattr(module, "_diff", False):
			result["diff"] = json_diff(current, desired)
		module.exit_json(**result)
	except Exception as err:
		module.fail_json(msg=f"{type(err).__name__}: {err}", exception=traceback.format_exc())


if __name__ == "__main__":
	main()
