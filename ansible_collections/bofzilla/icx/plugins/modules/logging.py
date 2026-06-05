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
module: logging
short_description: Configure syslog settings on a Brocade ICX switch
description:
  - Manages common global syslog controls and remote logging hosts.
options:
  enabled:
    description:
      - Whether local syslog logging is enabled.
    type: bool
  hosts:
    description:
      - Canonical remote syslog hosts.
    type: list
    elements: dict
  facility:
    description:
      - Syslog facility to configure.
    type: str
  persistence:
    description:
      - Whether to persist system log messages across soft reboot.
    type: bool
  user_login:
    description:
      - Whether to log user login events.
    type: bool
  rfc5424:
    description:
      - Whether to enable RFC5424 syslog format.
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
LOGGING_CONFIG_PATTERNS = (
	"logging ",
	"no logging on",
)

EXAMPLES = r"""
- bofzilla.icx.logging:
    hosts:
      - address: 192.168.1.20
        udp_port: 1514
    user_login: true
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
logging:
  description: Normalized desired logging settings.
  type: dict
"""


def _parse(raw: str) -> dict[str, Any]:
	lines = global_config_lines(raw)
	hosts: list[dict[str, Any]] = []
	for line in lines:
		if line.startswith("logging host "):
			parts = line.split()
			host: dict[str, Any] = {"address": parts[2], "udp_port": None}
			if "udp-port" in parts:
				host["udp_port"] = int(parts[parts.index("udp-port") + 1])
			hosts.append(host)
	return {
		"enabled": "no logging on" not in lines,
		"hosts": hosts,
		"facility": next((line.removeprefix("logging facility ") for line in lines if line.startswith("logging facility ")), None),
		"persistence": "logging persistence" in lines,
		"user_login": "logging enable user-login" in lines,
		"rfc5424": "logging enable rfc5424" in lines,
	}


def _host_line(host: dict[str, Any]) -> str:
	address = validate_ip(host["address"]) if host["address"][0].isdigit() else host["address"]
	line = f"logging host {address}"
	if host.get("udp_port"):
		line += f" udp-port {host['udp_port']}"
	return line


def main():
	module = AnsibleModule(
		argument_spec={
			**ICX_ARGUMENT_SPEC,
			**SAVE_WHEN_ARGUMENT_SPEC,
			"enabled": {"type": "bool"},
			"hosts": {"type": "list", "elements": "dict", "options": {"address": {"type": "str", "required": True}, "udp_port": {"type": "int"}}},
			"facility": {"type": "str"},
			"persistence": {"type": "bool"},
			"user_login": {"type": "bool"},
			"rfc5424": {"type": "bool"},
		},
		supports_check_mode=True,
	)
	try:
		client = CliClient(Connection(module._socket_path), enable_password=module.params.get("enable_password"))
		current = _parse(running_config_matching(client, LOGGING_CONFIG_PATTERNS))
		desired = dict(current)
		for key in ("enabled", "hosts", "facility", "persistence", "user_login", "rfc5424"):
			if module.params.get(key) is not None:
				desired[key] = module.params[key]
		cmds: list[ConfigLine] = []
		if module.params.get("enabled") is not None and current["enabled"] != desired["enabled"]:
			cmds.append(ConfigLine("logging on" if desired["enabled"] else "no logging on"))
		if module.params.get("hosts") is not None and current["hosts"] != desired["hosts"]:
			for host in current["hosts"]:
				cmds.append(ConfigLine(f"no {_host_line(host)}"))
			for host in desired["hosts"]:
				cmds.append(ConfigLine(_host_line(host)))
		if module.params.get("facility") is not None and current.get("facility") != desired.get("facility"):
			if current.get("facility"):
				cmds.append(ConfigLine(f"no logging facility {current['facility']}"))
			if desired.get("facility"):
				cmds.append(ConfigLine(f"logging facility {desired['facility']}"))
		for key, line in {"persistence": "logging persistence", "user_login": "logging enable user-login", "rfc5424": "logging enable rfc5424"}.items():
			if module.params.get(key) is not None and current[key] != desired[key]:
				cmds.append(ConfigLine(line if desired[key] else f"no {line}"))
		changed = bool(cmds)
		saved = run_config_commands(client, module, cmds, changed, resolve_save_when(module.params))
		result = {"changed": changed, "logging": desired, "command": command_strings(cmds, saved), "saved": saved}
		if changed and getattr(module, "_diff", False):
			result["diff"] = json_diff(current, desired)
		module.exit_json(**result)
	except Exception as err:
		module.fail_json(msg=f"{type(err).__name__}: {err}", exception=traceback.format_exc())


if __name__ == "__main__":
	main()
