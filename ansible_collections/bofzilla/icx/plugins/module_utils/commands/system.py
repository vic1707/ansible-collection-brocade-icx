from pydantic import ConfigDict
from pydantic.dataclasses import dataclass

from ansible_collections.bofzilla.icx.plugins.module_utils.command_spec import Command, enabled


@enabled
@dataclass(config=ConfigDict(extra="forbid"))
class WriteMemory(Command[None]):
	"""Privileged EXEC: ``write memory`` — saves running-config to startup-config."""

	def command(self) -> str:
		return "write memory"

	def parse_res(self, raw: str) -> None:
		return None
