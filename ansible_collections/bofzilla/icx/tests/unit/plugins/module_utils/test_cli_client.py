from typing import cast

from ansible.module_utils.connection import Connection

from ansible_collections.bofzilla.icx.plugins.module_utils.cli_client import CliClient
from ansible_collections.bofzilla.icx.plugins.module_utils.command_spec import Command, config, enabled


@enabled
class EnabledCommand(Command[str]):
	def command(self) -> str:
		return "show example"

	def parse_res(self, raw: str) -> str:
		return raw


@enabled
class PagingCommand(Command[str]):
	disable_paging = True

	def command(self) -> str:
		return "show long-example"

	def parse_res(self, raw: str) -> str:
		return raw


@config("configure terminal")
class ConfigCommand(Command[str]):
	def command(self) -> str:
		return "example config"

	def parse_res(self, raw: str) -> str:
		return raw


class FakeConnection:
	def __init__(self) -> None:
		self.calls: list[str] = []

	def enable(self, password: str | None = None, disable_paging: bool = False) -> None:
		self.calls.append(f"enable:{password}:{disable_paging}")

	def send_command(self, command: str) -> str:
		self.calls.append(command)
		return "ok"


def test_enabled_command_does_not_send_end():
	conn = FakeConnection()
	result = CliClient(cast(Connection, conn)).run(EnabledCommand())

	assert result == "ok"
	assert conn.calls == ["enable:None:False", "show example"]


def test_enabled_command_can_request_paging_disable():
	conn = FakeConnection()
	result = CliClient(cast(Connection, conn)).run(PagingCommand())

	assert result == "ok"
	assert conn.calls == ["enable:None:True", "show long-example"]


def test_config_command_sends_end_after_submode():
	conn = FakeConnection()
	result = CliClient(cast(Connection, conn)).run(ConfigCommand())

	assert result == "ok"
	assert conn.calls == ["enable:None:False", "configure terminal", "example config", "end"]
