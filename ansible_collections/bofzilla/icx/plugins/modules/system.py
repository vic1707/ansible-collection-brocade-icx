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
	first_matching,
	global_config_lines,
	json_diff,
	resolve_save_when,
	run_config_commands,
	validate_ip,
)

LOGGING_LEVELS = ["alerts", "critical", "debugging", "emergencies", "errors", "informational", "notifications", "warnings"]
SYSTEM_CONFIG_PATTERNS = (
	"hostname ",
	"ip dns ",
	"logging ",
	"banner motd",
)

DOCUMENTATION = r"""
module: system
short_description: Configure basic system settings on a Brocade ICX switch
description:
  - Configures homelab-safe global system settings such as hostname, DNS,
    simple logging, and MOTD banner.
options:
  hostname:
    description:
      - System hostname to configure.
    type: str
    required: false
  dns_servers:
    description:
      - Canonical list of IPv4 DNS servers.
    type: list
    elements: str
    required: false
  dns_domains:
    description:
      - Canonical list of DNS search domains.
    type: list
    elements: str
    required: false
  logging:
    description:
      - Basic global logging settings.
    type: dict
    required: false
    suboptions:
      console:
        description:
          - Whether to display syslog messages on the console.
        type: bool
      cli_command:
        description:
          - Whether to log valid CLI commands.
        type: bool
      config_changed:
        description:
          - Whether to log startup-config changes.
        type: bool
      buffered_level:
        description:
          - Syslog buffered severity level to enable.
        type: str
      buffered_entries:
        description:
          - Number of entries retained in the local syslog buffer.
        type: int
  banner:
    description:
      - Basic MOTD banner settings.
    type: dict
    required: false
    suboptions:
      motd:
        description:
          - Message of the day banner text.
        type: str
      require_enter:
        description:
          - Whether the user must press Enter after the MOTD banner.
        type: bool
  save_when:
    description:
      - When to save running-config to startup-config.
    type: str
    choices: [changed, always, never]
    default: changed
  enable_password:
    description:
      - Password used to enter privileged EXEC mode.
    type: str
    required: false
author:
  - bofzilla
"""

EXAMPLES = r"""
- name: Configure basic system settings
  bofzilla.icx.system:
    hostname: icx-homelab
    dns_servers:
      - 1.1.1.1
      - 9.9.9.9
    dns_domains:
      - home.arpa
    logging:
      console: false
      cli_command: true
    save_when: changed
"""

RETURN = r"""
changed:
  description: Whether any configuration changed.
  type: bool
  returned: success
command:
  description: Commands sent or planned.
  type: list
  elements: str
  returned: success
saved:
  description: Whether write memory was run or planned.
  type: bool
  returned: success
system:
  description: Normalized desired system settings.
  type: dict
  returned: success
"""


def _parse_system(raw: str) -> dict[str, Any]:
	lines = global_config_lines(raw)
	hostname = None
	if line := first_matching(lines, "hostname "):
		hostname = line.removeprefix("hostname ").strip('"')
	dns_servers: list[str] = []
	if line := first_matching(lines, "ip dns server-address "):
		dns_servers = line.removeprefix("ip dns server-address ").split()
	dns_domains = [line.removeprefix("ip dns domain-list ") for line in lines if line.startswith("ip dns domain-list ")]
	logging: dict[str, Any] = {
		"console": "logging console" in lines,
		"cli_command": "logging cli-command" in lines,
		"config_changed": "logging enable config-changed" in lines,
	}
	if line := first_matching(lines, "logging buffered "):
		value = line.removeprefix("logging buffered ")
		if value.isdigit():
			logging["buffered_entries"] = int(value)
		else:
			logging["buffered_level"] = value
	banner: dict[str, Any] = {}
	if line := first_matching(lines, "banner motd "):
		value = line.removeprefix("banner motd ")
		if value == "require-enter-key":
			banner["require_enter"] = True
		elif len(value) >= 2 and value[0] == value[-1]:
			banner["motd"] = value[1:-1].strip()
	return {
		"hostname": hostname,
		"dns_servers": dns_servers,
		"dns_domains": dns_domains,
		"logging": logging,
		"banner": banner,
	}


def _desired(params: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
	desired = {
		"hostname": current["hostname"],
		"dns_servers": list(current["dns_servers"]),
		"dns_domains": list(current["dns_domains"]),
		"logging": dict(current["logging"]),
		"banner": dict(current["banner"]),
	}
	if params.get("hostname") is not None:
		desired["hostname"] = params["hostname"]
	if params.get("dns_servers") is not None:
		desired["dns_servers"] = [validate_ip(server) for server in params["dns_servers"]]
	if params.get("dns_domains") is not None:
		desired["dns_domains"] = list(dict.fromkeys(params["dns_domains"]))
	if params.get("logging"):
		desired["logging"].update({key: value for key, value in params["logging"].items() if value is not None})
	if params.get("banner"):
		desired["banner"].update({key: value for key, value in params["banner"].items() if value is not None})
	return desired


def _commands(current: dict[str, Any], desired: dict[str, Any], params: dict[str, Any]) -> list[ConfigLine]:
	cmds: list[ConfigLine] = []
	if params.get("hostname") is not None and current["hostname"] != desired["hostname"]:
		cmds.append(ConfigLine(f"hostname {desired['hostname']}"))
	if params.get("dns_servers") is not None and current["dns_servers"] != desired["dns_servers"]:
		if current["dns_servers"]:
			cmds.append(ConfigLine(f"no ip dns server-address {' '.join(current['dns_servers'])}"))
		if desired["dns_servers"]:
			cmds.append(ConfigLine(f"ip dns server-address {' '.join(desired['dns_servers'])}"))
	if params.get("dns_domains") is not None and current["dns_domains"] != desired["dns_domains"]:
		for domain in current["dns_domains"]:
			cmds.append(ConfigLine(f"no ip dns domain-list {domain}"))
		for domain in desired["dns_domains"]:
			cmds.append(ConfigLine(f"ip dns domain-list {domain}"))

	logging_param = params.get("logging") or {}
	for key, line in {
		"console": "logging console",
		"cli_command": "logging cli-command",
		"config_changed": "logging enable config-changed",
	}.items():
		if key in logging_param and logging_param[key] is not None and current["logging"].get(key) != desired["logging"].get(key):
			cmds.append(ConfigLine(line if desired["logging"][key] else f"no {line}"))
	if logging_param.get("buffered_level") is not None and current["logging"].get("buffered_level") != desired["logging"].get("buffered_level"):
		if current["logging"].get("buffered_level"):
			cmds.append(ConfigLine(f"no logging buffered {current['logging']['buffered_level']}"))
		cmds.append(ConfigLine(f"logging buffered {desired['logging']['buffered_level']}"))
	if logging_param.get("buffered_entries") is not None and current["logging"].get("buffered_entries") != desired["logging"].get("buffered_entries"):
		if current["logging"].get("buffered_entries"):
			cmds.append(ConfigLine(f"no logging buffered {current['logging']['buffered_entries']}"))
		cmds.append(ConfigLine(f"logging buffered {desired['logging']['buffered_entries']}"))

	banner_param = params.get("banner") or {}
	if banner_param.get("motd") is not None and current["banner"].get("motd") != desired["banner"].get("motd"):
		if current["banner"].get("motd"):
			cmds.append(ConfigLine(f"no banner motd ${current['banner']['motd']} $"))
		cmds.append(ConfigLine(f"banner motd $ {desired['banner']['motd']} $"))
	if banner_param.get("require_enter") is not None and current["banner"].get("require_enter", False) != desired["banner"].get("require_enter", False):
		cmds.append(ConfigLine("banner motd require-enter-key" if desired["banner"]["require_enter"] else "no banner motd require-enter-key"))
	return cmds


def main():
	module = AnsibleModule(
		argument_spec={
			**ICX_ARGUMENT_SPEC,
			**SAVE_WHEN_ARGUMENT_SPEC,
			"hostname": {"type": "str"},
			"dns_servers": {"type": "list", "elements": "str"},
			"dns_domains": {"type": "list", "elements": "str"},
			"logging": {
				"type": "dict",
				"options": {
					"console": {"type": "bool"},
					"cli_command": {"type": "bool"},
					"config_changed": {"type": "bool"},
					"buffered_level": {"type": "str", "choices": LOGGING_LEVELS},
					"buffered_entries": {"type": "int"},
				},
			},
			"banner": {
				"type": "dict",
				"options": {
					"motd": {"type": "str"},
					"require_enter": {"type": "bool"},
				},
			},
		},
		supports_check_mode=True,
	)
	try:
		client = CliClient(Connection(module._socket_path), enable_password=module.params.get("enable_password"))
		current = _parse_system(running_config_matching(client, SYSTEM_CONFIG_PATTERNS))
		desired = _desired(module.params, current)
		cmds = _commands(current, desired, module.params)
		changed = bool(cmds)
		saved = run_config_commands(client, module, cmds, changed, resolve_save_when(module.params))
		result = {
			"changed": changed,
			"system": desired,
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
