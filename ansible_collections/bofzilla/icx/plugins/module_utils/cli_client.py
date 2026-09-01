from typing import Protocol, cast, runtime_checkable

from ansible.module_utils.connection import Connection

from ansible_collections.bofzilla.icx.plugins.module_utils.command_spec import Command
from ansible_collections.bofzilla.icx.plugins.module_utils.commands.config import ConfigLine

ICX_ARGUMENT_SPEC = {
	"enable_password": {"type": "str", "no_log": True},
}


@runtime_checkable
class ICXConnection(Protocol):
	"""Typed surface of the persistent connection exposed to modules.

	The real object is an :class:`ansible.module_utils.connection.Connection`
	RPC proxy that resolves every attribute through ``__getattr__``; declaring
	the methods we rely on here restores type checking and editor completion.
	"""

	def enable(self, password: str | None = None, disable_paging: bool = False) -> None: ...

	def send_command(self, command: str) -> str: ...


class CliClient:
	def __init__(self, connection: Connection, enable_password: str | None = None) -> None:
		self._conn = cast(ICXConnection, connection)
		self.enable_password = enable_password

	def run[Res](self, cmd: Command[Res]) -> Res:
		if cmd.modes is None:
			return cmd.parse_res(self._conn.send_command(cmd.command()))

		self._conn.enable(self.enable_password, disable_paging=cmd.disable_paging)
		for mode in cmd.modes:
			self._conn.send_command(mode)

		try:
			return cmd.parse_res(self._conn.send_command(cmd.command()))
		finally:
			if cmd.modes:
				self._conn.send_command("end")

	def run_config(self, commands: list[ConfigLine]) -> None:
		if not commands:
			return

		self._conn.enable(self.enable_password)
		self._conn.send_command("configure terminal")
		current_modes: list[str] = []
		in_config = True
		try:
			for index, cmd in enumerate(commands):
				desired_modes = cmd.modes[1:]
				common = 0
				while common < min(len(current_modes), len(desired_modes)) and current_modes[common] == desired_modes[common]:
					common += 1
				for _ in current_modes[common:]:
					self._conn.send_command("exit")
				for mode in desired_modes[common:]:
					self._conn.send_command(mode)
				cmd.parse_res(self._conn.send_command(cmd.command()))
				current_modes = desired_modes
				if not desired_modes:
					self._conn.send_command("end")
					in_config = False
					if index < len(commands) - 1:
						self._conn.send_command("configure terminal")
						in_config = True
		finally:
			if in_config:
				self._conn.send_command("end")
