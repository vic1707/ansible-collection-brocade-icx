import json
import re

from ansible.errors import AnsibleConnectionFailure
from ansible.module_utils.common.text.converters import to_text
from ansible.plugins.cliconf import CliconfBase

ENABLE_PASSWORD_PROMPT = r"[\r\n](?:Local_|Enable )?[Pp]assword: ?$"
ENABLE_USERNAME_PROMPT = r"[\r\n](?:[Uu]ser ?[Nn]ame|[Uu]sername): ?$"


class Cliconf(CliconfBase):
	def enable(self, password: str | None = None, disable_paging: bool = False) -> None:
		"""Ensure the session is in privileged EXEC mode (prompt ends with `#`).

		Called on demand by commands that need it, so callers never have to
		opt into Ansible's `become`. A no-op when already privileged.
		"""
		if self._is_config_mode():
			self.send_command("end")
		if not self._is_privileged_exec():
			username = self._connection.get_option("remote_user")
			prompts = [ENABLE_USERNAME_PROMPT, ENABLE_PASSWORD_PROMPT] if username else ENABLE_PASSWORD_PROMPT
			answers = [username, password or ""] if username else password or ""
			try:
				self.send_command("enable", prompt=prompts, answer=answers)
			except AnsibleConnectionFailure:
				if not password:
					raise AnsibleConnectionFailure("device requires an enable password but none was provided") from None
				raise AnsibleConnectionFailure("failed to enter privileged EXEC mode (is enable_password correct?)") from None
		if not self._is_privileged_exec():
			raise AnsibleConnectionFailure("failed to enter privileged EXEC mode (is enable_password correct?)")
		if disable_paging:
			self.send_command("skip-page-display")

	def _is_privileged_exec(self) -> bool:
		prompt = self._connection.get_prompt()
		value = to_text(prompt).strip() if prompt else ""
		return value.endswith("#") and not self._is_config_prompt(value)

	def _is_config_mode(self) -> bool:
		prompt = self._connection.get_prompt()
		return self._is_config_prompt(to_text(prompt).strip() if prompt else "")

	def _is_config_prompt(self, prompt: str) -> bool:
		return bool(re.search(r"\([^)]+\)# ?$", prompt))

	def get(self, command=None, prompt=None, answer=None, sendonly=False, newline=True, output=None, check_all=False):
		return self.send_command(
			command,
			prompt=prompt,
			answer=answer,
			sendonly=sendonly,
			newline=newline,
			check_all=check_all,
		)

	def get_config(self, source="running", flags=None, format=None):
		return self.send_command("show running-config" if source == "running" else f"show {source}-config")

	def edit_config(self, candidate=None, commit=True, replace=None, diff=False, comment=None):
		if not candidate:
			return
		for line in candidate.splitlines():
			line = line.strip()
			if line and not line.startswith("!"):
				self.send_command(line)

	def get_device_info(self):
		device_info = {"network_os": "icx"}
		data = self.send_command("show version").strip()
		if match := re.search(r"SW:\s+Version\s+(\S+)", data):
			device_info["network_os_version"] = match.group(1)
		if match := re.search(r"HW:\s+(.+)", data):
			device_info["network_os_model"] = match.group(1)
		if match := re.search(r"Serial\s+#:\s+(\S+)", data):
			device_info["network_os_serial"] = match.group(1)
		return device_info

	def get_capabilities(self):
		return json.dumps(
			{
				"rpc": self.get_base_rpc(),
				"device_info": self.get_device_info(),
				"network_api": "cliconf",
				"device_operations": {
					"supports_diff_replace": False,
					"supports_commit": False,
					"supports_rollback": False,
					"supports_defaults": False,
					"supports_onbox_diff": False,
					"supports_commit_comment": False,
					"supports_multiline_delimiter": False,
					"supports_diff_match": False,
					"supports_diff_ignore_lines": False,
					"supports_generate_diff": False,
					"supports_replace": False,
				},
				"format": ["text"],
				"diff_match": [],
				"diff_replace": [],
				"output": [],
			}
		)
