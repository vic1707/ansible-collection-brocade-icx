from ipaddress import ip_address

from pydantic import ConfigDict, IPvAnyAddress
from pydantic.dataclasses import dataclass

from ansible_collections.bofzilla.icx.plugins.module_utils.command_spec import Command, config


@dataclass(config=ConfigDict(extra="forbid", frozen=True))
class NtpAssociations:
	servers: frozenset[IPvAnyAddress]


@dataclass(config=ConfigDict(extra="forbid", frozen=True))
class NtpStatus:
	enabled: bool


@config("configure terminal", "ntp")
@dataclass(config=ConfigDict(extra="forbid"))
class SetNtpServer(Command[None]):
	"""NTP sub-mode: ``server <ip-address>``"""

	server: IPvAnyAddress

	def command(self) -> str:
		return f"server {self.server}"

	def parse_res(self, raw: str) -> None:
		return None


@config("configure terminal", "ntp")
@dataclass(config=ConfigDict(extra="forbid"))
class RemoveNtpServer(Command[None]):
	"""NTP sub-mode: ``no server <ip-address>``"""

	server: IPvAnyAddress

	def command(self) -> str:
		return f"no server {self.server}"

	def parse_res(self, raw: str) -> None:
		return None


@config("configure terminal", "ntp")
@dataclass(config=ConfigDict(extra="forbid"))
class DisableNtp(Command[None]):
	"""NTP sub-mode: ``disable``"""

	def command(self) -> str:
		return "disable"

	def parse_res(self, raw: str) -> None:
		return None


@config("configure terminal", "ntp")
@dataclass(config=ConfigDict(extra="forbid"))
class EnableNtp(Command[None]):
	"""NTP sub-mode: ``no disable`` — re-enables NTP after it was disabled."""

	def command(self) -> str:
		return "no disable"

	def parse_res(self, raw: str) -> None:
		return None


@dataclass(config=ConfigDict(extra="forbid"))
class ShowNtpAssociations(Command[NtpAssociations]):
	"""Privileged EXEC: ``show ntp associations``."""

	def command(self) -> str:
		return "show ntp associations"

	def parse_res(self, raw: str) -> NtpAssociations:
		servers: set[IPvAnyAddress] = set()
		for line in raw.splitlines():
			tokens = line.split()
			if "~" not in tokens:
				continue
			for token in tokens:
				if token in {"*", "#", "+", "-", "x", "~"}:
					continue
				try:
					servers.add(ip_address(token))
					break
				except ValueError:
					continue
		return NtpAssociations(servers=frozenset(servers))


@dataclass(config=ConfigDict(extra="forbid"))
class ShowNtpStatus(Command[NtpStatus]):
	"""Privileged EXEC: ``show ntp status``."""

	def command(self) -> str:
		return "show ntp status"

	def parse_res(self, raw: str) -> NtpStatus:
		for line in raw.splitlines():
			if "NTP client mode is enabled" in line:
				return NtpStatus(enabled=True)
			if "NTP client mode is disabled" in line:
				return NtpStatus(enabled=False)
		raise ValueError(f"raw switch output: {raw}")
