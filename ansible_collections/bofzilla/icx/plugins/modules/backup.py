import traceback
from typing import Any

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.connection import Connection

from ansible_collections.bofzilla.icx.plugins.module_utils.cli_client import ICX_ARGUMENT_SPEC, CliClient
from ansible_collections.bofzilla.icx.plugins.module_utils.commands.config import ExecLine
from ansible_collections.bofzilla.icx.plugins.module_utils.module_common import validate_ip

DOCUMENTATION = r"""
module: backup
short_description: Upload ICX configuration backups by SCP or TFTP
description:
  - Operational module for C(copy running-config ...) and
    C(copy startup-config ...). This module is not idempotent because each run
    performs a transfer.
options:
  source:
    description:
      - Configuration source to upload.
    type: str
    choices: [running-config, startup-config]
    default: running-config
  protocol:
    description:
      - Transfer protocol to use.
    type: str
    choices: [tftp, scp]
    required: true
  server:
    description:
      - Remote SCP or TFTP server address or hostname.
    type: str
    required: true
  filename:
    description:
      - Remote backup filename.
    type: str
    required: true
  outgoing_interface:
    description:
      - Optional outgoing interface for SCP transfers.
    type: dict
    suboptions:
      type:
        description:
          - Outgoing interface type.
        type: str
        choices: [ethernet, ve]
        required: true
      name:
        description:
          - Outgoing interface name or number.
        type: str
        required: true
  public_key:
    description:
      - Optional SCP public-key authentication type.
    type: str
    choices: [rsa, dsa]
  remote_port:
    description:
      - Optional SCP remote TCP port.
    type: int
author:
  - bofzilla
"""

EXAMPLES = r"""
- bofzilla.icx.backup:
    source: running-config
    protocol: tftp
    server: 192.168.1.10
    filename: icx-running.cfg
"""

RETURN = r"""
changed:
  description: Whether the transfer command was executed.
  type: bool
command:
  description: Transfer command sent or planned.
  type: str
"""


def _command(params: dict[str, Any]) -> str:
	source = params["source"]
	protocol = params["protocol"]
	server = validate_ip(params["server"]) if params["server"][0].isdigit() else params["server"]
	if protocol == "tftp":
		return f"copy {source} tftp {server} {params['filename']}"
	parts = [f"copy {source} scp {server}"]
	if params.get("outgoing_interface"):
		outgoing = params["outgoing_interface"]
		parts.append(f"outgoing-interface {outgoing['type']} {outgoing['name']}")
	if params.get("public_key"):
		parts.append(f"public-key {params['public_key']}")
	if params.get("remote_port"):
		parts.append(str(params["remote_port"]))
	parts.append(params["filename"])
	return " ".join(parts)


def main():
	module = AnsibleModule(
		argument_spec={
			**ICX_ARGUMENT_SPEC,
			"source": {"type": "str", "choices": ["running-config", "startup-config"], "default": "running-config"},
			"protocol": {"type": "str", "choices": ["tftp", "scp"], "required": True},
			"server": {"type": "str", "required": True},
			"filename": {"type": "str", "required": True},
			"outgoing_interface": {
				"type": "dict",
				"options": {"type": {"type": "str", "choices": ["ethernet", "ve"], "required": True}, "name": {"type": "str", "required": True}},
			},
			"public_key": {"type": "str", "choices": ["rsa", "dsa"]},
			"remote_port": {"type": "int"},
		},
		supports_check_mode=True,
	)
	try:
		command = _command(module.params)
		if not module.check_mode:
			client = CliClient(Connection(module._socket_path), enable_password=module.params.get("enable_password"))
			client.run(ExecLine(command))
		module.exit_json(changed=not module.check_mode, command=command)
	except Exception as err:
		module.fail_json(msg=f"{type(err).__name__}: {err}", exception=traceback.format_exc())


if __name__ == "__main__":
	main()
