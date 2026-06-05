import re
import traceback

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.connection import Connection

from ansible_collections.bofzilla.icx.plugins.module_utils.cli_client import ICX_ARGUMENT_SPEC, CliClient
from ansible_collections.bofzilla.icx.plugins.module_utils.commands.config import ShowChassis, ShowLldpNeighbors, ShowRunningConfig, ShowVersion

DOCUMENTATION = r"""
module: facts
short_description: Gather facts from a Brocade ICX switch
description:
  - Collects version-derived facts and optional raw running-config, chassis, and LLDP neighbor output.
options:
  include_config:
    description:
      - Include raw running-config output.
    type: bool
    default: false
  include_chassis:
    description:
      - Include raw chassis output.
    type: bool
    default: false
  include_lldp:
    description:
      - Include raw LLDP neighbors output.
    type: bool
    default: false
author:
  - bofzilla
"""

EXAMPLES = r"""
- bofzilla.icx.facts:
    include_chassis: true
    include_lldp: true
"""

RETURN = r"""
ansible_facts:
  description: ICX facts under the C(icx) key.
  type: dict
  returned: success
changed:
  description: Always false.
  type: bool
command:
  description: Show commands sent.
  type: list
  elements: str
"""


def _device_info(version: str) -> dict[str, str]:
	info: dict[str, str] = {}
	if match := re.search(r"SW:\s+Version\s+(\S+)", version):
		info["version"] = match.group(1)
	if match := re.search(r"HW:\s+(.+)", version):
		info["model"] = match.group(1).strip()
	if match := re.search(r"Serial\s+#:\s+(\S+)", version):
		info["serial"] = match.group(1)
	return info


def main():
	module = AnsibleModule(
		argument_spec={
			**ICX_ARGUMENT_SPEC,
			"include_config": {"type": "bool", "default": False},
			"include_chassis": {"type": "bool", "default": False},
			"include_lldp": {"type": "bool", "default": False},
		},
		supports_check_mode=True,
	)
	try:
		client = CliClient(Connection(module._socket_path), enable_password=module.params.get("enable_password"))
		version = client.run(ShowVersion())
		facts = {"device": _device_info(version), "version_raw": version}
		commands = ["show version"]
		if module.params["include_config"]:
			facts["running_config"] = client.run(ShowRunningConfig())
			commands.append("show running-config")
		if module.params["include_chassis"]:
			facts["chassis"] = client.run(ShowChassis())
			commands.append("show chassis")
		if module.params["include_lldp"]:
			facts["lldp_neighbors"] = client.run(ShowLldpNeighbors())
			commands.append("show lldp neighbors")
		module.exit_json(changed=False, ansible_facts={"icx": facts}, command=commands)
	except Exception as err:
		module.fail_json(msg=f"{type(err).__name__}: {err}", exception=traceback.format_exc())


if __name__ == "__main__":
	main()
