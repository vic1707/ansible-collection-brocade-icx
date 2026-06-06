from typing import ClassVar

from pydantic import ConfigDict
from pydantic.dataclasses import dataclass

from ansible_collections.bofzilla.icx.plugins.module_utils.command_spec import Command, enabled


@dataclass(config=ConfigDict(extra="forbid"))
@enabled
class ShowRunningConfig(Command[str]):
	disable_paging: ClassVar[bool] = True

	def command(self) -> str:
		return "show running-config"

	def parse_res(self, raw: str) -> str:
		return raw


@dataclass(config=ConfigDict(extra="forbid"))
@enabled
class ShowRunningConfigInclude(Command[str]):
	pattern: str

	def command(self) -> str:
		return f"show running-config | include {self.pattern}"

	def parse_res(self, raw: str) -> str:
		return raw


@dataclass(config=ConfigDict(extra="forbid"))
@enabled
class ShowIpSshConfig(Command[str]):
	def command(self) -> str:
		return "show ip ssh config"

	def parse_res(self, raw: str) -> str:
		return raw


@dataclass(config=ConfigDict(extra="forbid"))
class ShowUsers(Command[str]):
	def command(self) -> str:
		return "show users"

	def parse_res(self, raw: str) -> str:
		return raw


@dataclass(config=ConfigDict(extra="forbid"))
class ShowVersion(Command[str]):
	def command(self) -> str:
		return "show version"

	def parse_res(self, raw: str) -> str:
		return raw


@dataclass(config=ConfigDict(extra="forbid"))
@enabled
class ShowTelnetConfig(Command[str]):
	def command(self) -> str:
		return "show telnet config"

	def parse_res(self, raw: str) -> str:
		return raw


@dataclass(config=ConfigDict(extra="forbid"))
@enabled
class ShowChassis(Command[str]):
	disable_paging: ClassVar[bool] = True

	def command(self) -> str:
		return "show chassis"

	def parse_res(self, raw: str) -> str:
		return raw


@dataclass(config=ConfigDict(extra="forbid"))
class ShowLldpNeighbors(Command[str]):
	detail: bool = False

	def command(self) -> str:
		return "show lldp neighbors detail ports all" if self.detail else "show lldp neighbors"

	def parse_res(self, raw: str) -> str:
		return raw


@dataclass(config=ConfigDict(extra="forbid"))
class ConfigLine(Command[None]):
	line: str
	submodes: str | tuple[str, ...] = ()

	@property
	def modes(self) -> list[str]:
		if isinstance(self.submodes, str):
			return ["configure terminal", self.submodes]
		return ["configure terminal", *self.submodes]

	def command(self) -> str:
		return self.line

	def parse_res(self, raw: str) -> None:
		return None


@dataclass(config=ConfigDict(extra="forbid"))
@enabled
class ExecLine(Command[None]):
	line: str

	def command(self) -> str:
		return self.line

	def parse_res(self, raw: str) -> None:
		return None
