import traceback
from ipaddress import ip_address

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.connection import Connection

from ansible_collections.bofzilla.icx.plugins.module_utils.cli_client import ICX_ARGUMENT_SPEC, CliClient
from ansible_collections.bofzilla.icx.plugins.module_utils.commands.ntp import (
	DisableNtp,
	EnableNtp,
	RemoveNtpServer,
	SetNtpServer,
	ShowNtpAssociations,
	ShowNtpStatus,
)
from ansible_collections.bofzilla.icx.plugins.module_utils.commands.system import WriteMemory
from ansible_collections.bofzilla.icx.plugins.module_utils.config_state import running_config_matching
from ansible_collections.bofzilla.icx.plugins.module_utils.module_common import SAVE_WHEN_ARGUMENT_SPEC, clean_lines, config_blocks, resolve_save_when, should_save, text_diff

NtpCommand = RemoveNtpServer | SetNtpServer | DisableNtp | EnableNtp

DOCUMENTATION = r"""
module: ntp
short_description: Configure NTP on a Brocade ICX switch
description:
  - Configure the canonical NTP server list and enable or disable the NTP client on a
    Brocade ICX switch.
  - Commands are issued in Global Configuration mode.
options:
  servers:
    description:
      - Canonical list of NTP servers that should be configured.
      - Servers not in this list are removed, and missing servers are added.
    type: list
    elements: str
    required: true
  enabled:
    description:
      - Whether the NTP client should be enabled.
    type: bool
    default: true
  save:
    description:
      - Deprecated compatibility alias for C(save_when).
    type: bool
    default: false
    required: false
  save_when:
    description:
      - Whether to save the running-config to startup-config.
    type: str
    choices: [changed, always, never]
    default: changed
  enable_password:
    description:
      - Password used to enter privileged EXEC mode (C(enable)).
    type: str
    required: false

attributes:
  check_mode:
    support: full
    details: Compares current NTP state and reports what would change without changing the device.
  diff_mode:
    support: full
  idempotent:
    support: full
    details: NTP server presence and enabled/disabled state are compared before applying changes.

author:
  - bofzilla
"""

EXAMPLES = r"""
- name: Configure NTP servers
  bofzilla.icx.ntp:
    servers:
      - 129.6.15.28
      - 129.6.15.29
    enabled: true
    save: true
    enable_password: "{{ vault_icx_enable_password }}"

- name: Disable NTP with no configured servers
  bofzilla.icx.ntp:
    servers: []
    enabled: false
    save: true
    enable_password: "{{ vault_icx_enable_password }}"
"""

RETURN = r"""
command:
  description: The CLI command(s) sent to the device.
  type: list
  elements: str
  returned: success
saved:
  description: Whether the configuration was saved to startup-config.
  type: bool
  returned: when save is true
servers:
  description: The desired canonical NTP server list.
  type: list
  elements: str
  returned: success
enabled:
  description: The desired NTP client state.
  type: bool
  returned: success
"""


def _configured_servers(raw: str):
	servers = set()
	for line in clean_lines(raw):
		if line.startswith("server "):
			servers.add(ip_address(line.split()[1]))
	for block in config_blocks(raw):
		if not block or block[0] != "ntp":
			continue
		for line in block[1:]:
			if line.startswith("server "):
				servers.add(ip_address(line.split()[1]))
	return frozenset(servers)


def main():
	module = AnsibleModule(
		argument_spec={
			**ICX_ARGUMENT_SPEC,
			**SAVE_WHEN_ARGUMENT_SPEC,
			"servers": {"type": "list", "elements": "str", "required": True},
			"enabled": {"type": "bool", "default": True},
		},
		supports_check_mode=True,
	)
	try:
		desired_servers = frozenset(SetNtpServer(server=server).server for server in module.params["servers"])
		desired_enabled = module.params["enabled"]

		client = CliClient(Connection(module._socket_path), enable_password=module.params.get("enable_password"))
		associations = client.run(ShowNtpAssociations())
		current_servers = associations.servers | _configured_servers(running_config_matching(client, ("server ",)))
		status = client.run(ShowNtpStatus())

		cmds: list[NtpCommand] = [
			*(RemoveNtpServer(server=server) for server in sorted(current_servers - desired_servers, key=str)),
			*(SetNtpServer(server=server) for server in sorted(desired_servers - current_servers, key=str)),
		]
		if status.enabled != desired_enabled:
			cmds.append(EnableNtp() if desired_enabled else DisableNtp())

		changed = bool(cmds)
		save = should_save(resolve_save_when(module.params), changed)
		result: dict = {
			"changed": changed,
			"enabled": desired_enabled,
			"servers": sorted(str(server) for server in desired_servers),
			"command": [cmd.command() for cmd in cmds],
		}
		if changed and getattr(module, "_diff", False):
			before = [
				f"enabled: {'true' if status.enabled else 'false'}",
				f"servers: {', '.join(str(server) for server in sorted(current_servers, key=str)) if current_servers else 'none'}",
			]
			after = [
				f"enabled: {'true' if desired_enabled else 'false'}",
				f"servers: {', '.join(str(server) for server in sorted(desired_servers, key=str)) if desired_servers else 'none'}",
			]
			result["diff"] = text_diff("\n".join(before), "\n".join(after))

		if changed and not module.check_mode:
			for cmd in cmds:
				client.run(cmd)
			if save:
				client.run(WriteMemory())

		if changed and save:
			result["command"].append("write memory")
			result["saved"] = True

		module.exit_json(**result)
	except Exception as err:
		module.fail_json(msg=f"{type(err).__name__}: {err}", exception=traceback.format_exc())


if __name__ == "__main__":
	main()
