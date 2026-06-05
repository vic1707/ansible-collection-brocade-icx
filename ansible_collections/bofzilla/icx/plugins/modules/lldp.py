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
)

DOCUMENTATION = r"""
module: lldp
short_description: Configure global LLDP settings on a Brocade ICX switch
description:
  - Manages common global LLDP controls exposed by FastIron.
options:
  enabled:
    description:
      - Whether LLDP is globally enabled.
    type: bool
  tagged_packets:
    description:
      - Whether LLDP processes tagged LLDP packets.
    type: bool
  snmp_notification_interval:
    description:
      - Minimum seconds between LLDP SNMP notifications.
    type: int
  transmit_delay:
    description:
      - LLDP transmit delay in seconds.
    type: int
  transmit_hold:
    description:
      - LLDP transmit hold multiplier.
    type: int
  transmit_interval:
    description:
      - LLDP transmit interval in seconds.
    type: int
  max_neighbors:
    description:
      - Maximum LLDP neighbors retained for the device.
    type: int
  max_neighbors_per_port:
    description:
      - Maximum LLDP neighbors retained per port.
    type: int
  save_when:
    description:
      - When to save running-config to startup-config.
    type: str
    choices: [changed, always, never]
    default: changed
author:
  - bofzilla
"""
LLDP_CONFIG_PATTERNS = (
	"lldp ",
	"no lldp run",
)

EXAMPLES = r"""
- bofzilla.icx.lldp:
    enabled: true
    transmit_interval: 40
    tagged_packets: true
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
lldp:
  description: Normalized desired LLDP settings.
  type: dict
"""


def _parse(raw: str) -> dict[str, Any]:
	lines = global_config_lines(raw)
	state: dict[str, Any] = {"enabled": "no lldp run" not in lines, "tagged_packets": "lldp tagged-packets process" in lines}
	for key, prefix in {
		"snmp_notification_interval": "lldp snmp-notification-interval ",
		"transmit_delay": "lldp transmit-delay ",
		"transmit_hold": "lldp transmit-hold ",
		"transmit_interval": "lldp transmit-interval ",
		"max_neighbors": "lldp max-total-neighbors ",
		"max_neighbors_per_port": "lldp max-neighbors-per-port ",
	}.items():
		for line in lines:
			if line.startswith(prefix):
				state[key] = int(line.removeprefix(prefix))
				break
	return state


def _commands(params: dict[str, Any], current: dict[str, Any], desired: dict[str, Any]) -> list[ConfigLine]:
	cmds: list[ConfigLine] = []
	if params.get("enabled") is not None and current.get("enabled") != desired.get("enabled"):
		cmds.append(ConfigLine("lldp run" if desired["enabled"] else "no lldp run"))
	if params.get("tagged_packets") is not None and current.get("tagged_packets") != desired.get("tagged_packets"):
		cmds.append(ConfigLine("lldp tagged-packets process" if desired["tagged_packets"] else "no lldp tagged-packets process"))
	for key, command in {
		"snmp_notification_interval": "lldp snmp-notification-interval",
		"transmit_delay": "lldp transmit-delay",
		"transmit_hold": "lldp transmit-hold",
		"transmit_interval": "lldp transmit-interval",
		"max_neighbors": "lldp max-total-neighbors",
		"max_neighbors_per_port": "lldp max-neighbors-per-port",
	}.items():
		if params.get(key) is not None and current.get(key) != desired.get(key):
			cmds.append(ConfigLine(f"{command} {desired[key]}"))
	return cmds


def main():
	module = AnsibleModule(
		argument_spec={
			**ICX_ARGUMENT_SPEC,
			**SAVE_WHEN_ARGUMENT_SPEC,
			"enabled": {"type": "bool"},
			"tagged_packets": {"type": "bool"},
			"snmp_notification_interval": {"type": "int"},
			"transmit_delay": {"type": "int"},
			"transmit_hold": {"type": "int"},
			"transmit_interval": {"type": "int"},
			"max_neighbors": {"type": "int"},
			"max_neighbors_per_port": {"type": "int"},
		},
		supports_check_mode=True,
	)
	try:
		client = CliClient(Connection(module._socket_path), enable_password=module.params.get("enable_password"))
		current = _parse(running_config_matching(client, LLDP_CONFIG_PATTERNS))
		desired = dict(current)
		desired.update(
			{
				key: value
				for key, value in module.params.items()
				if key in current
				or key
				in {"enabled", "tagged_packets", "snmp_notification_interval", "transmit_delay", "transmit_hold", "transmit_interval", "max_neighbors", "max_neighbors_per_port"}
				if value is not None
			}
		)
		cmds = _commands(module.params, current, desired)
		changed = bool(cmds)
		saved = run_config_commands(client, module, cmds, changed, resolve_save_when(module.params))
		result = {"changed": changed, "lldp": desired, "command": command_strings(cmds, saved), "saved": saved}
		if changed and getattr(module, "_diff", False):
			result["diff"] = json_diff(current, desired)
		module.exit_json(**result)
	except Exception as err:
		module.fail_json(msg=f"{type(err).__name__}: {err}", exception=traceback.format_exc())


if __name__ == "__main__":
	main()
