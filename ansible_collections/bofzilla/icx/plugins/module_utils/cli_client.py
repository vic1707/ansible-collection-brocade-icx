from typing import Protocol, cast, runtime_checkable

from ansible.module_utils.connection import Connection

from ansible_collections.bofzilla.icx.plugins.module_utils.command_spec import Command

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

	def enable(self, password: str | None = None) -> None: ...

	def send_command(self, command: str) -> str: ...


class CliClient:
	def __init__(self, connection: Connection, enable_password: str | None = None) -> None:
		self._conn = cast(ICXConnection, connection)
		self.enable_password = enable_password

	def run[Res](self, cmd: Command[Res]) -> Res:
		if cmd.modes is None:
			return cmd.parse_res(self._conn.send_command(cmd.command()))

		self._conn.enable(self.enable_password)
		for mode in cmd.modes:
			self._conn.send_command(mode)

		try:
			return cmd.parse_res(self._conn.send_command(cmd.command()))
		finally:
			self._conn.send_command("end")
