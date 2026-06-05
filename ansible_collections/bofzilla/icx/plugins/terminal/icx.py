import re

from ansible.plugins.terminal import TerminalBase


class TerminalModule(TerminalBase):
	terminal_stdout_re = [
		re.compile(rb"(?:^|[\r\n])[\w@\+\-\.:\/\[\]]+(?:\([^\)]+\)){0,3}[>#] ?$"),
		re.compile(rb"Finished downloading public key file!"),
	]

	terminal_stderr_re = [
		re.compile(rb"^\s*(Error|Invalid|Ambiguous|Incomplete|Bad)\b", re.I),
		re.compile(rb"^\s*(Access denied|Authentication failed|Command authorization failed|Permission denied)\b", re.I),
		re.compile(rb"\bnot found\b", re.I),
		re.compile(rb"\btimed ?out\b", re.I),
		re.compile(rb"returned error code:"),
	]

	def on_open_shell(self):
		# No-op: paging disable (skip-page-display) requires privileged EXEC
		# mode, which isn't available yet at shell-open time. Paging will be
		# disabled after privilege escalation when needed.
		pass
