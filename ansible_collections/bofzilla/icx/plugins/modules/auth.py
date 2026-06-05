import re
import traceback
from typing import Any

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.connection import Connection

from ansible_collections.bofzilla.icx.plugins.module_utils.cli_client import ICX_ARGUMENT_SPEC, CliClient
from ansible_collections.bofzilla.icx.plugins.module_utils.commands.config import ConfigLine, ShowUsers
from ansible_collections.bofzilla.icx.plugins.module_utils.config_state import running_config_matching
from ansible_collections.bofzilla.icx.plugins.module_utils.module_common import (
	SAVE_WHEN_ARGUMENT_SPEC,
	command_strings,
	first_matching,
	global_config_lines,
	json_diff,
	resolve_save_when,
	run_config_commands,
)

AAA_METHODS = ["enable", "line", "local", "none", "radius", "tacacs", "tacacs+"]
AUTH_CONFIG_PATTERNS = (
	"aaa authentication ",
	"enable password-min-length",
	"enable strict-password-enforcement",
	"enable super-user-password",
	"enable read-only-password",
	"enable port-config-password",
)

DOCUMENTATION = r"""
module: auth
short_description: Configure local authentication on a Brocade ICX switch
description:
  - Manages local users, enable passwords, password policy, and local-first AAA
    method lists.
options:
  users:
    description:
      - Local user accounts to create, update, enable, disable, or remove.
    type: list
    elements: dict
  enable_passwords:
    description:
      - Enable-level passwords for super-user, read-only, and port-config privilege levels.
    type: dict
  password_policy:
    description:
      - Local password minimum length and strict enforcement policy.
    type: dict
  aaa:
    description:
      - Local-first AAA login and enable method-list settings.
    type: dict
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
- bofzilla.icx.auth:
    users:
      - name: admin
        privilege: 0
        password: "{{ vault_icx_admin_password }}"
    aaa:
      login_methods: [local]
      enable_methods: [local]
      privilege_mode: true
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
auth:
  description: Normalized desired authentication state.
  type: dict
"""


def _parse_users(raw: str) -> dict[str, dict[str, Any]]:
	users: dict[str, dict[str, Any]] = {}
	for line in raw.splitlines():
		line = line.strip()
		if not line or line.startswith(("Username", "=", "---")):
			continue
		parts = line.split()
		if len(parts) >= 5 and parts[2] in {"enabled", "disabled"}:
			users[parts[0]] = {
				"name": parts[0],
				"privilege": int(parts[3]),
				"enabled": parts[4] == "enabled",
			}
	return users


def _parse_auth_config(raw: str) -> dict[str, Any]:
	lines = global_config_lines(raw)
	policy: dict[str, Any] = {"strict": "enable strict-password-enforcement" in lines}
	if line := first_matching(lines, "enable password-min-length "):
		policy["min_length"] = int(line.removeprefix("enable password-min-length "))
	aaa: dict[str, Any] = {}
	if line := first_matching(lines, "aaa authentication login default "):
		aaa["login_methods"] = line.removeprefix("aaa authentication login default ").split()
	if line := first_matching(lines, "aaa authentication enable default "):
		aaa["enable_methods"] = line.removeprefix("aaa authentication enable default ").split()
	aaa["privilege_mode"] = "aaa authentication login privilege-mode" in lines
	aaa["enable_implicit_user"] = "aaa authentication enable implicit-user" in lines
	enable_passwords = {
		"super_user": any(line.startswith("enable super-user-password") for line in lines),
		"read_only": any(line.startswith("enable read-only-password") for line in lines),
		"port_config": any(line.startswith("enable port-config-password") for line in lines),
	}
	return {"password_policy": policy, "aaa": aaa, "enable_passwords": enable_passwords}


def _desired(params: dict[str, Any], users: dict[str, dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
	desired_users = {name: dict(user) for name, user in users.items()}
	for item in params.get("users") or []:
		if item.get("state", "present") == "absent":
			desired_users.pop(item["name"], None)
			continue
		current = users.get(item["name"], {})
		desired_users[item["name"]] = {
			"name": item["name"],
			"privilege": item["privilege"] if item.get("privilege") is not None else current.get("privilege", 0),
			"enabled": item["enabled"] if item.get("enabled") is not None else current.get("enabled", True),
		}
	desired = {
		"users": desired_users,
		"password_policy": dict(config["password_policy"]),
		"aaa": dict(config["aaa"]),
		"enable_passwords": dict(config["enable_passwords"]),
	}
	if params.get("password_policy"):
		desired["password_policy"].update({key: value for key, value in params["password_policy"].items() if value is not None})
	if params.get("aaa"):
		desired["aaa"].update({key: value for key, value in params["aaa"].items() if value is not None})
	return desired


def _user_command(item: dict[str, Any], current: dict[str, Any] | None) -> str | None:
	if item.get("privilege") is not None:
		privilege = item["privilege"]
	elif current:
		privilege = current.get("privilege", 0)
	else:
		privilege = 0
	if item.get("state", "present") == "absent":
		return f"no username {item['name']}" if current else None
	if item.get("nopassword"):
		return f"username {item['name']} privilege {privilege} nopassword"
	if item.get("password") is not None:
		if current and item.get("update_password", "on_create") == "on_create":
			return None
		return f"username {item['name']} privilege {privilege} password {item['password']}"
	if current is None:
		raise ValueError(f"user {item['name']} needs password, nopassword, or state=absent")
	if item.get("privilege") is not None and current.get("privilege") != privilege:
		return f"username {item['name']} privilege {privilege} nopassword"
	return None


def _commands(params: dict[str, Any], users: dict[str, dict[str, Any]], config: dict[str, Any], desired: dict[str, Any]) -> list[ConfigLine]:
	cmds: list[ConfigLine] = []
	for item in params.get("users") or []:
		if command := _user_command(item, users.get(item["name"])):
			cmds.append(ConfigLine(command))
		if item.get("enabled") is not None and users.get(item["name"], {}).get("enabled", True) != item["enabled"]:
			cmds.append(ConfigLine(f"username {item['name']} enable" if item["enabled"] else f"no username {item['name']} enable"))

	enable_passwords = params.get("enable_passwords") or {}
	update_password = enable_passwords.get("update_password", "always")
	for key, command_name in {
		"super_user": "enable super-user-password",
		"read_only": "enable read-only-password",
		"port_config": "enable port-config-password",
	}.items():
		if enable_passwords.get(key) is not None and (update_password == "always" or not config["enable_passwords"].get(key)):
			cmds.append(ConfigLine(f"{command_name} {enable_passwords[key]}"))

	policy = params.get("password_policy") or {}
	if policy.get("min_length") is not None and config["password_policy"].get("min_length") != desired["password_policy"].get("min_length"):
		cmds.append(ConfigLine(f"enable password-min-length {desired['password_policy']['min_length']}"))
	if policy.get("strict") is not None and config["password_policy"].get("strict") != desired["password_policy"].get("strict"):
		cmds.append(ConfigLine("enable strict-password-enforcement" if desired["password_policy"]["strict"] else "no enable strict-password-enforcement"))

	aaa = params.get("aaa") or {}
	if aaa.get("login_methods") is not None and config["aaa"].get("login_methods") != desired["aaa"].get("login_methods"):
		cmds.append(ConfigLine(f"aaa authentication login default {' '.join(desired['aaa']['login_methods'])}"))
	if aaa.get("enable_methods") is not None and config["aaa"].get("enable_methods") != desired["aaa"].get("enable_methods"):
		cmds.append(ConfigLine(f"aaa authentication enable default {' '.join(desired['aaa']['enable_methods'])}"))
	for key, line in {
		"privilege_mode": "aaa authentication login privilege-mode",
		"enable_implicit_user": "aaa authentication enable implicit-user",
	}.items():
		if aaa.get(key) is not None and config["aaa"].get(key) != desired["aaa"].get(key):
			cmds.append(ConfigLine(line if desired["aaa"][key] else f"no {line}"))
	return cmds


def _validate_lockout(params: dict[str, Any], desired: dict[str, Any]) -> None:
	aaa = params.get("aaa") or {}
	if any(methods is not None for methods in (aaa.get("login_methods"), aaa.get("enable_methods"))):
		local_methods = [*(aaa.get("login_methods") or []), *(aaa.get("enable_methods") or [])]
		if "local" in local_methods and not any(user["enabled"] and user["privilege"] == 0 for user in desired["users"].values()):
			raise ValueError("local AAA requires at least one enabled privilege 0 user")
	if re.search(r"\bnone\b", " ".join(aaa.get("login_methods") or [])) and not params.get("allow_insecure_none"):
		raise ValueError("AAA method 'none' requires allow_insecure_none=true")


def _redacted(commands: list[ConfigLine], saved: bool) -> list[str]:
	result = command_strings(commands, saved)
	patterns = [
		(r"(username \S+ privilege \d+ password) .+", r"\1 ********"),
		(r"(enable super-user-password) .+", r"\1 ********"),
		(r"(enable read-only-password) .+", r"\1 ********"),
		(r"(enable port-config-password) .+", r"\1 ********"),
	]
	for index, item in enumerate(result):
		for pattern, replacement in patterns:
			item = re.sub(pattern, replacement, item)
		result[index] = item
	return result


def main():
	module = AnsibleModule(
		argument_spec={
			**ICX_ARGUMENT_SPEC,
			**SAVE_WHEN_ARGUMENT_SPEC,
			"users": {
				"type": "list",
				"elements": "dict",
				"options": {
					"name": {"type": "str", "required": True},
					"privilege": {"type": "int", "choices": [0, 4, 5]},
					"password": {"type": "str", "no_log": True},
					"nopassword": {"type": "bool"},
					"enabled": {"type": "bool"},
					"update_password": {"type": "str", "choices": ["on_create", "always"], "default": "on_create"},
					"state": {"type": "str", "choices": ["present", "absent"], "default": "present"},
				},
			},
			"enable_passwords": {
				"type": "dict",
				"no_log": True,
				"options": {
					"super_user": {"type": "str", "no_log": True},
					"read_only": {"type": "str", "no_log": True},
					"port_config": {"type": "str", "no_log": True},
					"update_password": {"type": "str", "choices": ["on_create", "always"], "default": "always"},
				},
			},
			"password_policy": {
				"type": "dict",
				"no_log": False,
				"options": {
					"min_length": {"type": "int"},
					"strict": {"type": "bool"},
				},
			},
			"aaa": {
				"type": "dict",
				"options": {
					"login_methods": {"type": "list", "elements": "str", "choices": AAA_METHODS},
					"enable_methods": {"type": "list", "elements": "str", "choices": AAA_METHODS},
					"privilege_mode": {"type": "bool"},
					"enable_implicit_user": {"type": "bool"},
				},
			},
			"allow_insecure_none": {"type": "bool", "default": False},
		},
		supports_check_mode=True,
	)
	try:
		client = CliClient(Connection(module._socket_path), enable_password=module.params.get("enable_password"))
		config = _parse_auth_config(running_config_matching(client, AUTH_CONFIG_PATTERNS))
		users = _parse_users(client.run(ShowUsers()))
		desired = _desired(module.params, users, config)
		_validate_lockout(module.params, desired)
		cmds = _commands(module.params, users, config, desired)
		changed = bool(cmds)
		saved = run_config_commands(client, module, cmds, changed, resolve_save_when(module.params))
		result = {
			"changed": changed,
			"auth": desired,
			"command": _redacted(cmds, saved),
			"saved": saved,
		}
		if changed and getattr(module, "_diff", False):
			result["diff"] = json_diff({"users": users, **config}, desired)
		module.exit_json(**result)
	except Exception as err:
		module.fail_json(msg=f"{type(err).__name__}: {err}", exception=traceback.format_exc())


if __name__ == "__main__":
	main()
