import os

os.environ.setdefault("ANSIBLE_LOCAL_TEMP", "/private/tmp")

from ansible_collections.bofzilla.icx.plugins.terminal.icx import TerminalModule


def test_terminal_timeout_error_does_not_match_config_labels():
	output = b"Login timeout (seconds)    : 120\r\nIdle timeout (minutes)     : 0\r\nSSH@Mycelium#"
	assert not any(regex.search(output) for regex in TerminalModule.terminal_stderr_re)


def test_terminal_timeout_error_matches_real_timeout():
	output = b"Request timed out\r\nSSH@Mycelium#"
	assert any(regex.search(output) for regex in TerminalModule.terminal_stderr_re)
