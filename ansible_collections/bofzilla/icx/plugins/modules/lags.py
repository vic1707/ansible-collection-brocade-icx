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
	port_list_command,
	quote_if_needed,
	resolve_save_when,
	run_config_commands,
)
from ansible_collections.bofzilla.icx.plugins.module_utils.switching import parse_lags

DOCUMENTATION = r"""
module: lags
short_description: Configure link aggregation groups on a Brocade ICX switch
description:
  - Manages static, dynamic, and keep-alive LAG definitions, ports, primary
    port, and deployment state.
options:
  lags:
    description:
      - Link aggregation groups to manage.
    type: list
    elements: dict
    required: true
    suboptions:
      name:
        description:
          - LAG name.
        type: str
        required: true
      mode:
        description:
          - LAG type. C(dynamic) uses LACP, C(static) is manually bundled, and C(keep-alive) is a single-port keepalive LAG.
        type: str
        choices: [static, dynamic, keep-alive]
      id:
        description:
          - Numeric LAG ID for C(static) and C(dynamic) LAGs.
        type: int
      ports:
        description:
          - Ethernet member ports.
        type: list
        elements: str
      primary_port:
        description:
          - Primary member port.
        type: str
      deployed:
        description:
          - Whether the LAG should be deployed.
        type: bool
      passive:
        description:
          - Whether to deploy a dynamic LAG in passive mode.
        type: bool
      state:
        description:
          - Whether the LAG should exist.
        type: str
        choices: [present, absent]
        default: present
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
- bofzilla.icx.lags:
    lags:
      - name: uplink
        mode: dynamic
        id: 1
        ports: [1/1/47, 1/1/48]
        primary_port: 1/1/47
        deployed: true
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
lags:
  description: Normalized desired LAG definitions.
  type: list
"""


def _desired(item: dict[str, Any], current: dict[str, Any] | None) -> dict[str, Any] | None:
	if item.get("state", "present") == "absent":
		return None
	return {
		"name": item["name"],
		"mode": item.get("mode", current.get("mode") if current else "static"),
		"id": item.get("id", current.get("id") if current else None),
		"ports": item.get("ports", current.get("ports") if current else []),
		"primary_port": item.get("primary_port", current.get("primary_port") if current else None),
		"deployed": item.get("deployed", current.get("deployed") if current else False),
		"passive": item.get("passive", current.get("passive") if current else False),
	}


def _lag_header(lag: dict[str, Any]) -> str:
	header = f"lag {quote_if_needed(lag['name'])} {lag['mode']}"
	if lag.get("id") is not None and lag["mode"] in {"static", "dynamic"}:
		header += f" id {lag['id']}"
	return header


def _commands(item: dict[str, Any], current: dict[str, Any] | None, desired: dict[str, Any] | None) -> list[ConfigLine]:
	cmds: list[ConfigLine] = []
	if desired is None:
		if current is not None:
			cmds.append(ConfigLine(f"no lag {quote_if_needed(item['name'])} {current['mode']}" + (f" id {current['id']}" if current.get("id") else "")))
		return cmds
	if current is None or current.get("mode") != desired.get("mode") or current.get("id") != desired.get("id"):
		if current is not None:
			cmds.append(ConfigLine(f"no lag {quote_if_needed(current['name'])} {current['mode']}" + (f" id {current['id']}" if current.get("id") else "")))
		cmds.append(ConfigLine(_lag_header(desired)))
	mode = _lag_header(desired)
	if current is None or current.get("ports", []) != desired.get("ports", []):
		if current and current.get("ports"):
			cmds.append(ConfigLine(f"no ports {port_list_command(current['ports'])}", mode))
		if desired.get("ports"):
			cmds.append(ConfigLine(f"ports {port_list_command(desired['ports'])}", mode))
	if (current is None or current.get("primary_port") != desired.get("primary_port")) and desired.get("primary_port"):
		cmds.append(ConfigLine(f"primary-port {desired['primary_port']}", mode))
	if current is None or current.get("deployed") != desired.get("deployed") or current.get("passive") != desired.get("passive"):
		if desired.get("deployed"):
			cmds.append(ConfigLine("deploy passive" if desired.get("passive") else "deploy", mode))
		elif current and current.get("deployed"):
			cmds.append(ConfigLine("no deploy", mode))
	return cmds


def main():
	module = AnsibleModule(
		argument_spec={
			**ICX_ARGUMENT_SPEC,
			**SAVE_WHEN_ARGUMENT_SPEC,
			"lags": {
				"type": "list",
				"elements": "dict",
				"required": True,
				"options": {
					"name": {"type": "str", "required": True},
					"mode": {"type": "str", "choices": ["static", "dynamic", "keep-alive"]},
					"id": {"type": "int"},
					"ports": {"type": "list", "elements": "str"},
					"primary_port": {"type": "str"},
					"deployed": {"type": "bool"},
					"passive": {"type": "bool"},
					"state": {"type": "str", "choices": ["present", "absent"], "default": "present"},
				},
			},
		},
		supports_check_mode=True,
	)
	try:
		client = CliClient(Connection(module._socket_path), enable_password=module.params.get("enable_password"))
		current_all = parse_lags(client.run(ShowRunningConfig()))
		current_items: list[dict[str, Any] | None] = []
		desired_items: list[dict[str, Any] | None] = []
		cmds: list[ConfigLine] = []
		for item in module.params["lags"]:
			current = current_all.get(item["name"])
			desired = _desired(item, current)
			current_items.append(current)
			desired_items.append(desired)
			cmds.extend(_commands(item, current, desired))
		changed = bool(cmds)
		saved = run_config_commands(client, module, cmds, changed, resolve_save_when(module.params))
		result: dict[str, Any] = {
			"changed": changed,
			"lags": [item for item in desired_items if item is not None],
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
