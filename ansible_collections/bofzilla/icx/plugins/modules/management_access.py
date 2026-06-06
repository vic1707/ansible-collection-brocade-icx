import re
import traceback
from typing import Any

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.connection import Connection

from ansible_collections.bofzilla.icx.plugins.module_utils.cli_client import ICX_ARGUMENT_SPEC, CliClient
from ansible_collections.bofzilla.icx.plugins.module_utils.commands.config import ConfigLine, ShowIpSshConfig, ShowTelnetConfig
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

DOCUMENTATION = r"""
module: management_access
short_description: Configure management access services on a Brocade ICX switch
description:
  - Manages SSH, SCP, TFTP client controls, basic web management, and telnet
    restrictions. SFTP is intentionally not exposed because FastIron 08.0.30
    documents SCP and TFTP, not SFTP.
options:
  ssh:
    description:
      - SSH server and SCP access settings.
    type: dict
  tftp:
    description:
      - TFTP client access and source-interface settings.
    type: dict
  web:
    description:
      - Basic web management HTTP and HTTPS settings.
    type: dict
  telnet:
    description:
      - Telnet server, authentication, password, timeout, and restriction settings.
    type: dict
  allow_lockout:
    description:
      - Allow changes that may lock out the current management path.
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
MANAGEMENT_ACCESS_CONFIG_PATTERNS = (
	"tftp ",
	"ip tftp ",
	"web-management",
	"web access-group",
	"enable telnet authentication",
	"telnet ",
)

EXAMPLES = r"""
- bofzilla.icx.management_access:
    ssh:
      enabled: true
      host_keys:
        - type: rsa
          modulus: 2048
      password_authentication: true
      key_authentication: true
      scp: true
      idle_time: 30
    tftp:
      enabled: false
    web:
      http: false
      https: true
"""

RETURN = r"""
changed:
  description: Whether any configuration changed.
  type: bool
command:
  description: Commands sent or planned, with secrets redacted.
  type: list
  elements: str
saved:
  description: Whether write memory was run or planned.
  type: bool
management_access:
  description: Normalized desired management access state.
  type: dict
"""


def _parse_ssh(raw: str) -> dict[str, Any]:
	state: dict[str, Any] = {"host_keys": []}
	for line in raw.splitlines():
		line = line.strip()
		if line.startswith("SSH server"):
			state["enabled"] = "Enabled" in line or "enabled" in line
		elif line.startswith("SSH port"):
			state["port"] = _last_int(line)
		elif line.startswith("Permit empty password"):
			state["permit_empty_password"] = "yes" in line.lower() or "allowed" in line.lower()
		elif line.startswith("Authentication methods"):
			value = line.split(":", 1)[1].lower()
			state["password_authentication"] = "password" in value
			state["key_authentication"] = "public-key" in value
			state["interactive_authentication"] = "interactive" in value
		elif line.startswith("Authentication retries"):
			state["authentication_retries"] = _last_int(line)
		elif line.startswith("Login timeout"):
			state["timeout"] = _last_int(line)
		elif line.startswith("Idle timeout"):
			state["idle_time"] = _last_int(line)
		elif line.startswith("Strict management VRF"):
			state["strict_management_vrf"] = "enabled" in line.lower()
		elif line.startswith("SCP"):
			state["scp"] = "enabled" in line.lower()
		elif line.startswith("SSH IPv4 access-list"):
			value = line.split(":", 1)[1].strip()
			state["access_group"] = value or None
		elif line.startswith("SSH IPv4 clients"):
			value = line.split(":", 1)[1].strip()
			state["allowed_clients"] = [] if value in {"", "All"} else value.split()
		elif "hostkey" in line.lower() and "rsa" in line.lower():
			state["host_keys"].append({"type": "rsa"})
		elif "hostkey" in line.lower() and "dsa" in line.lower():
			state["host_keys"].append({"type": "dsa"})
	return state


def _last_int(line: str) -> int:
	if match := re.search(r"(\d+)\s*$", line):
		return int(match.group(1))
	raise ValueError(f"could not parse integer value from {line!r}")


def _parse_running(raw: str) -> dict[str, Any]:
	lines = global_config_lines(raw)
	tftp: dict[str, Any] = {"enabled": "tftp disable" not in lines}
	if line := first_matching(lines, "tftp client enable vlan "):
		tftp["restricted_vlan"] = int(line.removeprefix("tftp client enable vlan "))
	if line := first_matching(lines, "ip tftp source-interface "):
		parts = line.removeprefix("ip tftp source-interface ").split(maxsplit=1)
		tftp["source_interface"] = {"type": parts[0], "name": parts[1]}
	web: dict[str, Any] = {
		"http": "web-management http" in lines,
		"https": "web-management https" in lines,
	}
	if line := first_matching(lines, "web-management enable vlan "):
		web["enabled_vlan"] = int(line.removeprefix("web-management enable vlan "))
	if line := first_matching(lines, "web access-group "):
		web["access_group"] = line.removeprefix("web access-group ")
	telnet: dict[str, Any] = {
		"authentication": "enable telnet authentication" in lines,
	}
	if line := first_matching(lines, "telnet login-retries "):
		telnet["login_retries"] = int(line.removeprefix("telnet login-retries "))
	if line := first_matching(lines, "telnet login-timeout "):
		telnet["login_timeout"] = int(line.removeprefix("telnet login-timeout "))
	if line := first_matching(lines, "telnet timeout "):
		telnet["timeout"] = int(line.removeprefix("telnet timeout "))
	if line := first_matching(lines, "telnet server enable vlan "):
		telnet["restricted_vlan"] = int(line.removeprefix("telnet server enable vlan "))
	if line := first_matching(lines, "telnet access-group "):
		telnet["access_group"] = line.removeprefix("telnet access-group ")
	return {"tftp": tftp, "web": web, "telnet": telnet}


def _parse_telnet_config(raw: str) -> dict[str, Any]:
	state: dict[str, Any] = {}
	for line in raw.splitlines():
		line = line.strip()
		if line.startswith("Telnet server"):
			state["enabled"] = "enabled" in line.split(":", 1)[1].lower()
		elif line.startswith("Idle timeout"):
			state["timeout"] = _last_int(line)
		elif line.startswith("Login timeout"):
			state["login_timeout"] = _last_int(line)
		elif line.startswith("Login retries"):
			state["login_retries"] = _last_int(line)
		elif line.startswith("Authentication"):
			state["authentication"] = "enabled" in line.split(":", 1)[1].lower()
		elif line.startswith("Telnet IPv4 access-group"):
			value = line.split(":", 1)[1].strip()
			state["access_group"] = value or None
	return state


def _desired(params: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
	desired = {
		"ssh": dict(current["ssh"]),
		"tftp": dict(current["tftp"]),
		"web": dict(current["web"]),
		"telnet": dict(current["telnet"]),
	}
	for key in ("ssh", "tftp", "web", "telnet"):
		if params.get(key):
			desired[key].update({name: value for name, value in params[key].items() if value is not None})
	if desired["ssh"].get("allowed_clients"):
		desired["ssh"]["allowed_clients"] = [validate_ip(value) for value in desired["ssh"]["allowed_clients"]]
	return desired


def _ssh_commands(params: dict[str, Any], current: dict[str, Any], desired: dict[str, Any]) -> list[ConfigLine]:
	ssh_param = params.get("ssh") or {}
	cmds: list[ConfigLine] = []
	if ssh_param.get("enabled") is not None and current.get("enabled") != desired.get("enabled"):
		if desired["enabled"]:
			for host_key in desired.get("host_keys") or [{"type": "rsa", "modulus": 2048}]:
				if not any(key.get("type") == host_key["type"] for key in current.get("host_keys", [])):
					cmd = f"crypto key generate {host_key['type']}"
					if host_key["type"] == "rsa" and host_key.get("modulus"):
						cmd += f" modulus {host_key['modulus']}"
					cmds.append(ConfigLine(cmd))
		else:
			cmds.append(ConfigLine("crypto key zeroize rsa"))
			cmds.append(ConfigLine("crypto key zeroize dsa"))
	for key, command in {
		"authentication_retries": "ip ssh authentication-retries",
		"idle_time": "ip ssh idle-time",
		"timeout": "ip ssh timeout",
		"port": "ip ssh port",
	}.items():
		if ssh_param.get(key) is not None and current.get(key) != desired.get(key):
			cmds.append(ConfigLine(f"{command} {desired[key]}"))
	for key, command in {
		"password_authentication": "ip ssh password-authentication",
		"key_authentication": "ip ssh key-authentication",
		"interactive_authentication": "ip ssh interactive-authentication",
		"permit_empty_password": "ip ssh permit-empty-password",
	}.items():
		if ssh_param.get(key) is not None and current.get(key) != desired.get(key):
			cmds.append(ConfigLine(f"{command} {'yes' if desired[key] else 'no'}"))
	for key, command in {
		"aes_only": "ip ssh encryption aes-only",
		"disable_aes_cbc": "ip ssh encryption disable-aes-cbc",
		"strict_management_vrf": "ip ssh strict-management-vrf",
	}.items():
		if ssh_param.get(key) is not None and current.get(key) != desired.get(key):
			cmds.append(ConfigLine(command if desired[key] else f"no {command}"))
	if ssh_param.get("scp") is not None and current.get("scp") != desired.get("scp"):
		cmds.append(ConfigLine(f"ip ssh scp {'enable' if desired['scp'] else 'disable'}"))
	if ssh_param.get("access_group") is not None and current.get("access_group") != desired.get("access_group"):
		if current.get("access_group"):
			cmds.append(ConfigLine(f"no ssh access-group {current['access_group']}"))
		if desired.get("access_group"):
			cmds.append(ConfigLine(f"ssh access-group {desired['access_group']}"))
	if ssh_param.get("allowed_clients") is not None and current.get("allowed_clients", []) != desired.get("allowed_clients", []):
		for address in current.get("allowed_clients", []):
			cmds.append(ConfigLine(f"no ip ssh client {address}"))
		for address in desired.get("allowed_clients", []):
			cmds.append(ConfigLine(f"ip ssh client {address}"))
	if ssh_param.get("pub_key_file"):
		pub = ssh_param["pub_key_file"]
		if pub.get("state", "present") == "absent":
			cmds.append(ConfigLine("ip ssh pub-key-file remove"))
		else:
			cmds.append(ConfigLine(f"ip ssh pub-key-file tftp {validate_ip(pub['server'])} {pub['filename']}"))
	return cmds


def _service_commands(params: dict[str, Any], current: dict[str, Any], desired: dict[str, Any]) -> list[ConfigLine]:
	cmds: list[ConfigLine] = []
	tftp = params.get("tftp") or {}
	if tftp.get("enabled") is not None and current["tftp"].get("enabled") != desired["tftp"].get("enabled"):
		cmds.append(ConfigLine("no tftp disable" if desired["tftp"]["enabled"] else "tftp disable"))
	if tftp.get("restricted_vlan") is not None and current["tftp"].get("restricted_vlan") != desired["tftp"].get("restricted_vlan"):
		if current["tftp"].get("restricted_vlan"):
			cmds.append(ConfigLine(f"no tftp client enable vlan {current['tftp']['restricted_vlan']}"))
		cmds.append(ConfigLine(f"tftp client enable vlan {desired['tftp']['restricted_vlan']}"))
	if tftp.get("source_interface") is not None and current["tftp"].get("source_interface") != desired["tftp"].get("source_interface"):
		if current["tftp"].get("source_interface"):
			old = current["tftp"]["source_interface"]
			cmds.append(ConfigLine(f"no ip tftp source-interface {old['type']} {old['name']}"))
		new = desired["tftp"]["source_interface"]
		cmds.append(ConfigLine(f"ip tftp source-interface {new['type']} {new['name']}"))

	web = params.get("web") or {}
	for key in ("http", "https"):
		if web.get(key) is not None and current["web"].get(key) != desired["web"].get(key):
			cmds.append(ConfigLine(f"web-management {key}" if desired["web"][key] else f"no web-management {key}"))
	if web.get("enabled_vlan") is not None and current["web"].get("enabled_vlan") != desired["web"].get("enabled_vlan"):
		if current["web"].get("enabled_vlan"):
			cmds.append(ConfigLine(f"no web-management enable vlan {current['web']['enabled_vlan']}"))
		cmds.append(ConfigLine(f"web-management enable vlan {desired['web']['enabled_vlan']}"))
	if web.get("access_group") is not None and current["web"].get("access_group") != desired["web"].get("access_group"):
		if current["web"].get("access_group"):
			cmds.append(ConfigLine(f"no web access-group {current['web']['access_group']}"))
		cmds.append(ConfigLine(f"web access-group {desired['web']['access_group']}"))

	telnet = params.get("telnet") or {}
	if telnet.get("enabled") is not None and current["telnet"].get("enabled") != desired["telnet"].get("enabled"):
		cmds.append(ConfigLine("telnet server" if desired["telnet"]["enabled"] else "no telnet server"))
	if telnet.get("authentication") is not None and current["telnet"].get("authentication") != desired["telnet"].get("authentication"):
		cmds.append(ConfigLine("enable telnet authentication" if desired["telnet"]["authentication"] else "no enable telnet authentication"))
	if telnet.get("password") is not None:
		cmds.append(ConfigLine(f"enable telnet password {telnet['password']}"))
	for key, command in {
		"login_retries": "telnet login-retries",
		"login_timeout": "telnet login-timeout",
		"timeout": "telnet timeout",
	}.items():
		if telnet.get(key) is not None and current["telnet"].get(key) != desired["telnet"].get(key):
			cmds.append(ConfigLine(f"{command} {desired['telnet'][key]}"))
	if telnet.get("restricted_vlan") is not None and current["telnet"].get("restricted_vlan") != desired["telnet"].get("restricted_vlan"):
		if current["telnet"].get("restricted_vlan"):
			cmds.append(ConfigLine(f"no telnet server enable vlan {current['telnet']['restricted_vlan']}"))
		cmds.append(ConfigLine(f"telnet server enable vlan {desired['telnet']['restricted_vlan']}"))
	if telnet.get("access_group") is not None and current["telnet"].get("access_group") != desired["telnet"].get("access_group"):
		if current["telnet"].get("access_group"):
			cmds.append(ConfigLine(f"no telnet access-group {current['telnet']['access_group']}"))
		cmds.append(ConfigLine(f"telnet access-group {desired['telnet']['access_group']}"))
	return cmds


def _validate(params: dict[str, Any], desired: dict[str, Any]) -> None:
	ssh = desired.get("ssh", {})
	if not params.get("allow_lockout"):
		if params.get("ssh", {}).get("enabled") is False:
			raise ValueError("disabling SSH requires allow_lockout=true")
		if params.get("telnet", {}).get("enabled") is False:
			raise ValueError("disabling Telnet requires allow_lockout=true")
		if ssh.get("password_authentication") is False and ssh.get("key_authentication") is False:
			raise ValueError("disabling both SSH password and key authentication requires allow_lockout=true")
		if ssh.get("permit_empty_password") is True:
			raise ValueError("permit_empty_password=true requires allow_lockout=true")


def _redacted(commands: list[ConfigLine], saved: bool) -> list[str]:
	items = command_strings(commands, saved)
	return [re.sub(r"(enable telnet password) .+", r"\1 ********", item) for item in items]


def main():
	module = AnsibleModule(
		argument_spec={
			**ICX_ARGUMENT_SPEC,
			**SAVE_WHEN_ARGUMENT_SPEC,
			"allow_lockout": {"type": "bool", "default": False},
			"ssh": {
				"type": "dict",
				"options": {
					"enabled": {"type": "bool"},
					"host_keys": {
						"type": "list",
						"elements": "dict",
						"options": {
							"type": {"type": "str", "choices": ["rsa", "dsa"], "required": True},
							"modulus": {"type": "int"},
						},
					},
					"authentication_retries": {"type": "int"},
					"idle_time": {"type": "int"},
					"timeout": {"type": "int"},
					"port": {"type": "int"},
					"password_authentication": {"type": "bool"},
					"key_authentication": {"type": "bool"},
					"interactive_authentication": {"type": "bool"},
					"permit_empty_password": {"type": "bool"},
					"aes_only": {"type": "bool"},
					"disable_aes_cbc": {"type": "bool"},
					"scp": {"type": "bool"},
					"strict_management_vrf": {"type": "bool"},
					"access_group": {"type": "str"},
					"allowed_clients": {"type": "list", "elements": "str"},
					"pub_key_file": {
						"type": "dict",
						"options": {
							"server": {"type": "str"},
							"filename": {"type": "str"},
							"state": {"type": "str", "choices": ["present", "absent"], "default": "present"},
						},
					},
				},
			},
			"tftp": {
				"type": "dict",
				"options": {
					"enabled": {"type": "bool"},
					"restricted_vlan": {"type": "int"},
					"source_interface": {
						"type": "dict",
						"options": {
							"type": {"type": "str", "choices": ["ethernet", "loopback", "management", "ve"], "required": True},
							"name": {"type": "str", "required": True},
						},
					},
				},
			},
			"web": {
				"type": "dict",
				"options": {
					"http": {"type": "bool"},
					"https": {"type": "bool"},
					"enabled_vlan": {"type": "int"},
					"access_group": {"type": "str"},
				},
			},
			"telnet": {
				"type": "dict",
				"options": {
					"enabled": {"type": "bool"},
					"authentication": {"type": "bool"},
					"password": {"type": "str", "no_log": True},
					"login_retries": {"type": "int"},
					"login_timeout": {"type": "int"},
					"timeout": {"type": "int"},
					"restricted_vlan": {"type": "int"},
					"access_group": {"type": "str"},
				},
			},
		},
		supports_check_mode=True,
	)
	try:
		client = CliClient(Connection(module._socket_path), enable_password=module.params.get("enable_password"))
		current = {"ssh": _parse_ssh(client.run(ShowIpSshConfig())), **_parse_running(running_config_matching(client, MANAGEMENT_ACCESS_CONFIG_PATTERNS))}
		current["telnet"].update(_parse_telnet_config(client.run(ShowTelnetConfig())))
		desired = _desired(module.params, current)
		_validate(module.params, desired)
		cmds = [*_ssh_commands(module.params, current["ssh"], desired["ssh"]), *_service_commands(module.params, current, desired)]
		changed = bool(cmds)
		saved = run_config_commands(client, module, cmds, changed, resolve_save_when(module.params))
		result = {
			"changed": changed,
			"management_access": desired,
			"command": _redacted(cmds, saved),
			"saved": saved,
		}
		if changed and getattr(module, "_diff", False):
			result["diff"] = json_diff(current, desired)
		module.exit_json(**result)
	except Exception as err:
		module.fail_json(msg=f"{type(err).__name__}: {err}", exception=traceback.format_exc())


if __name__ == "__main__":
	main()
