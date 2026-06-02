from datetime import datetime
from typing import Literal, cast, get_args

from pydantic import ConfigDict, Field
from pydantic.dataclasses import dataclass

from ansible_collections.bofzilla.icx.plugins.module_utils.command_spec import Command, config, enabled


def _now() -> datetime:
	return datetime.now().replace(tzinfo=None)


GmtOffset = Literal[
	"gmt+00",
	"gmt+01",
	"gmt+02",
	"gmt+03",
	"gmt+03:30",
	"gmt+04",
	"gmt+04:30",
	"gmt+05",
	"gmt+05:30",
	"gmt+06",
	"gmt+06:30",
	"gmt+07",
	"gmt+08",
	"gmt+09",
	"gmt+09:30",
	"gmt+10",
	"gmt+10:30",
	"gmt+11",
	"gmt+11:30",
	"gmt+12",
	"gmt-01",
	"gmt-02",
	"gmt-03",
	"gmt-03:30",
	"gmt-04",
	"gmt-05",
	"gmt-06",
	"gmt-07",
	"gmt-08",
	"gmt-08:30",
	"gmt-09",
	"gmt-09:30",
	"gmt-10",
	"gmt-11",
	"gmt-12",
]

_VALID_OFFSETS: frozenset[str] = frozenset(get_args(GmtOffset))


def _local_gmt_offset() -> GmtOffset:
	"""Detect the local timezone as a GmtOffset string"""
	offset = datetime.now().astimezone().utcoffset()

	if offset is None:
		return "gmt+00"

	total = int(offset.total_seconds() // 60)
	hours, minutes = divmod(abs(total), 60)
	sign = "+" if total >= 0 else "-"
	tz = f"gmt{sign}{hours:02d}" + (f":{minutes:02d}" if minutes else "")
	assert tz in _VALID_OFFSETS, f"invalid timezone: '{tz}'"
	return cast(GmtOffset, tz)


@enabled
@dataclass(config=ConfigDict(extra="forbid"))
class SetClock(Command[None]):
	"""Privileged EXEC: ``clock set <hh:mm:ss> <mm-dd-yyyy>``"""

	time: datetime = Field(default_factory=_now)

	@property
	def wall_time(self) -> datetime:
		return self.time.replace(tzinfo=None)

	def command(self) -> str:
		return f"clock set {self.wall_time.strftime('%H:%M:%S')} {self.wall_time.strftime('%m-%d-%Y')}"

	def parse_res(self, raw: str) -> None:
		return None


@config("configure terminal")
@dataclass(config=ConfigDict(extra="forbid"))
class SetClockTimezone(Command[None]):
	"""Config mode: ``clock timezone gmt <offset>``"""

	timezone: GmtOffset = Field(default_factory=_local_gmt_offset)

	def command(self) -> str:
		return f"clock timezone gmt {self.timezone}"

	def parse_res(self, raw: str) -> None:
		return None


@config("configure terminal")
@dataclass(config=ConfigDict(extra="forbid"))
class SetClockSummerTime(Command[None]):
	"""Config mode: ``clock summer-time`` / ``no clock summer-time``"""

	enabled: bool = True

	def command(self) -> str:
		return "clock summer-time" if self.enabled else "no clock summer-time"

	def parse_res(self, raw: str) -> None:
		return None
