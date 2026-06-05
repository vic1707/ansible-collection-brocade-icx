import traceback

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.connection import Connection

from ansible_collections.bofzilla.icx.plugins.module_utils.cli_client import CliClient
from ansible_collections.bofzilla.icx.plugins.module_utils.commands.show.clock import ShowClock

DOCUMENTATION = r"""
module: clock
short_description: Retrieve the current clock from a Brocade ICX switch
description:
  - Retrieves the current running clock from a Brocade ICX switch via `show clock`.

attributes:
  check_mode:
    support: full
  diff_mode:
    support: none
  idempotent:
    support: full

author:
  - bofzilla
"""

EXAMPLES = r"""
- name: Retrieve running clock
  bofzilla.icx.show.clock:
"""

RETURN = r"""
clock:
  description: Parsed clock as an ISO-8601 timestamp.
  type: str
  returned: success
command:
  description: The CLI command sent to the device.
  type: str
  returned: success
"""


def main():
	module = AnsibleModule(argument_spec={}, supports_check_mode=True)
	try:
		client = CliClient(Connection(module._socket_path))
		cmd = ShowClock()
		clock = client.run(cmd)
		module.exit_json(changed=False, clock=clock.isoformat(), command=cmd.command())
	except Exception as err:
		module.fail_json(msg=f"{type(err).__name__}: {err}", exception=traceback.format_exc())


if __name__ == "__main__":
	main()
