import re
import traceback
from typing import Any

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.connection import Connection

from ansible_collections.bofzilla.icx.plugins.module_utils.cli_client import ICX_ARGUMENT_SPEC, CliClient
from ansible_collections.bofzilla.icx.plugins.module_utils.commands.config import ConfigLine
from ansible_collections.bofzilla.icx.plugins.module_utils.config_state import running_config_matching
from ansible_collections.bofzilla.icx.plugins.module_utils.module_common import (
	SAVE_WHEN_ARGUMENT_SPEC,
	command_strings,
	global_config_lines,
	json_diff,
	resolve_save_when,
	run_config_commands,
	validate_ip,
)

DOCUMENTATION = r"""
module: snmp
short_description: Configure simple SNMP settings on a Brocade ICX switch
description:
  - Manages SNMP communities, trap hosts, contact, and location.
  - Advanced SNMPv3 users, groups, and views are intentionally deferred.
options:
  communities:
    description:
      - Canonical SNMP community strings and access modes.
      - The list is authoritative when provided; omitted leaves current communities untouched.
    type: list
    elements: dict
    suboptions:
      name:
        description:
          - SNMP community string.
        type: str
        required: true
      access:
        description:
          - Community access mode.
        type: str
        choices: [ro, rw]
        required: true
      acl:
        description:
          - Optional ACL suffix applied to the community command.
        type: str
  hosts:
    description:
      - Canonical SNMP trap hosts.
      - The list is authoritative when provided; omitted leaves current trap hosts untouched.
    type: list
    elements: dict
    suboptions:
      address:
        description:
          - Trap host IPv4 address or hostname.
        type: str
        required: true
      version:
        description:
          - SNMP trap version.
        type: str
        choices: [v1, v2c]
      community:
        description:
          - Community string used for this trap host.
        type: str
      port:
        description:
          - UDP trap port.
        type: int
  contact:
    description:
      - SNMP contact string.
    type: str
  location:
    description:
      - SNMP location string.
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
SNMP_CONFIG_PATTERNS = ("snmp-server ",)

EXAMPLES = r"""
- bofzilla.icx.snmp:
    communities:
      - name: "{{ vault_snmp_ro }}"
        access: ro
    contact: ops@example.com
    location: homelab
"""

RETURN = r"""
changed:
  description: Whether any configuration changed.
  type: bool
command:
  description: Commands sent or planned, with communities redacted.
  type: list
  elements: str
saved:
  description: Whether write memory was run or planned.
  type: bool
snmp:
  description: Normalized desired SNMP settings.
  type: dict
"""


def _parse(raw: str) -> dict[str, Any]:
	lines = global_config_lines(raw)
	communities: list[dict[str, Any]] = []
	hosts: list[dict[str, Any]] = []
	for line in lines:
		if line.startswith("snmp-server community "):
			parts = line.split()
			item: dict[str, Any] = {"name": parts[2], "access": parts[3]}
			if len(parts) > 4:
				item["acl"] = " ".join(parts[4:])
			communities.append(item)
		elif line.startswith("snmp-server host "):
			parts = line.split()
			host: dict[str, Any] = {"address": parts[2]}
			if "version" in parts:
				host["version"] = parts[parts.index("version") + 1]
			if "port" in parts:
				host["port"] = int(parts[parts.index("port") + 1])
			hosts.append(host)
	return {
		"communities": communities,
		"hosts": hosts,
		"contact": next((line.removeprefix("snmp-server contact ") for line in lines if line.startswith("snmp-server contact ")), None),
		"location": next((line.removeprefix("snmp-server location ") for line in lines if line.startswith("snmp-server location ")), None),
	}


def _community_line(item: dict[str, Any]) -> str:
	line = f"snmp-server community {item['name']} {item['access']}"
	if item.get("acl"):
		line += f" {item['acl']}"
	return line


def _is_redacted_secret(value: str | None) -> bool:
	return bool(value) and set(value) == {"."}


def _same_community(current: dict[str, Any], desired: dict[str, Any]) -> bool:
	if current.get("name") == desired.get("name"):
		return current.get("access") == desired.get("access") and current.get("acl") == desired.get("acl")
	if _is_redacted_secret(current.get("name")):
		return current.get("access") == desired.get("access") and current.get("acl") == desired.get("acl")
	return False


def _community_commands(current: list[dict[str, Any]], desired: list[dict[str, Any]]) -> list[ConfigLine]:
	cmds: list[ConfigLine] = []
	for item in current:
		if _is_redacted_secret(item.get("name")):
			continue
		if not any(_same_community(item, candidate) for candidate in desired):
			cmds.append(ConfigLine(f"no {_community_line(item)}"))
	for item in desired:
		if not any(_same_community(candidate, item) for candidate in current):
			cmds.append(ConfigLine(_community_line(item)))
	return cmds


def _host_line(item: dict[str, Any]) -> str:
	address = validate_ip(item["address"]) if re.match(r"^\d", item["address"]) else item["address"]
	line = f"snmp-server host {address}"
	if item.get("version"):
		line += f" version {item['version']}"
	if item.get("community"):
		line += f" {item['community']}"
	if item.get("port"):
		line += f" port {item['port']}"
	return line


def _redacted(commands: list[ConfigLine], saved: bool) -> list[str]:
	return [_redact_command(item) for item in command_strings(commands, saved)]


def _redact_command(command: str) -> str:
	command = re.sub(r"(snmp-server community) \S+", r"\1 ********", command)
	parts = command.split()
	if parts[:2] == ["snmp-server", "host"]:
		index = 3
		if len(parts) > index and parts[index] == "version":
			index += 2
		if len(parts) > index and parts[index] != "port":
			parts[index] = "********"
		return " ".join(parts)
	return command


def _redacted_state(state: dict[str, Any]) -> dict[str, Any]:
	redacted = dict(state)
	redacted["communities"] = [{**item, "name": "********"} for item in state.get("communities", [])]
	redacted["hosts"] = [{**item, "community": "********"} if item.get("community") else dict(item) for item in state.get("hosts", [])]
	return redacted


def main():
	module = AnsibleModule(
		argument_spec={
			**ICX_ARGUMENT_SPEC,
			**SAVE_WHEN_ARGUMENT_SPEC,
			"communities": {
				"type": "list",
				"elements": "dict",
				"options": {
					"name": {"type": "str", "required": True, "no_log": True},
					"access": {"type": "str", "choices": ["ro", "rw"], "required": True},
					"acl": {"type": "str"},
				},
			},
			"hosts": {
				"type": "list",
				"elements": "dict",
				"options": {
					"address": {"type": "str", "required": True},
					"version": {"type": "str", "choices": ["v1", "v2c"]},
					"community": {"type": "str", "no_log": True},
					"port": {"type": "int"},
				},
			},
			"contact": {"type": "str"},
			"location": {"type": "str"},
		},
		supports_check_mode=True,
	)
	try:
		client = CliClient(Connection(module._socket_path), enable_password=module.params.get("enable_password"))
		current = _parse(running_config_matching(client, SNMP_CONFIG_PATTERNS))
		desired = dict(current)
		for key in ("communities", "hosts", "contact", "location"):
			if module.params.get(key) is not None:
				desired[key] = module.params[key]
		cmds: list[ConfigLine] = []
		if module.params.get("communities") is not None and current["communities"] != desired["communities"]:
			cmds.extend(_community_commands(current["communities"], desired["communities"]))
		if module.params.get("hosts") is not None and current["hosts"] != desired["hosts"]:
			for item in current["hosts"]:
				cmds.append(ConfigLine(f"no {_host_line(item)}"))
			for item in desired["hosts"]:
				cmds.append(ConfigLine(_host_line(item)))
		for key, command in {"contact": "snmp-server contact", "location": "snmp-server location"}.items():
			if module.params.get(key) is not None and current.get(key) != desired.get(key):
				if current.get(key):
					cmds.append(ConfigLine(f"no {command} {current[key]}"))
				if desired.get(key):
					cmds.append(ConfigLine(f"{command} {desired[key]}"))
		changed = bool(cmds)
		saved = run_config_commands(client, module, cmds, changed, resolve_save_when(module.params))
		result = {"changed": changed, "snmp": _redacted_state(desired), "command": _redacted(cmds, saved), "saved": saved}
		if changed and getattr(module, "_diff", False):
			result["diff"] = json_diff(_redacted_state(current), _redacted_state(desired))
		module.exit_json(**result)
	except Exception as err:
		module.fail_json(msg=f"{type(err).__name__}: {err}", exception=traceback.format_exc())


if __name__ == "__main__":
	main()
