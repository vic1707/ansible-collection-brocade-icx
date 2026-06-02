import re
from datetime import UTC, datetime, timedelta, timezone

from pydantic import ConfigDict
from pydantic.dataclasses import dataclass

from ansible_collections.bofzilla.icx.plugins.module_utils.command_spec import Command

CLOCK_RE = re.compile(
	r"^\s*"
	r"(?P<time>\d{2}:\d{2}:\d{2}\.\d+)\s+"
	r"GMT(?P<offset>[+-]\d{2})(?::?(?P<offset_minutes>\d{2}))?\s+"
	r"(?P<weekday>\w{3})\s+"
	r"(?P<month>\w{3})\s+"
	r"(?P<day>\d{1,2})\s+"
	r"(?P<year>\d{4})"
	r"\s*$"
)


@dataclass(config=ConfigDict(extra="forbid"))
class ShowClock(Command[datetime]):
	def command(self) -> str:
		return "show clock"

	def parse_res(self, raw: str) -> datetime:
		match = CLOCK_RE.match(raw)
		if not match:
			raise ValueError(f"raw switch output: {raw}")

		offset = _parse_gmt_offset(match["offset"], match["offset_minutes"])
		clock = datetime.strptime(
			f"{match['month']} {match['day']} {match['year']} {match['time']}",
			"%b %d %Y %H:%M:%S.%f",
		)
		return clock.replace(tzinfo=offset)


def _parse_gmt_offset(hours_text: str, minutes_text: str | None) -> timezone:
	hours = int(hours_text[1:])
	minutes = int(minutes_text or 0)
	delta = timedelta(hours=hours, minutes=minutes)
	if hours_text.startswith("-"):
		delta = -delta
	return UTC if delta == timedelta(0) else timezone(delta)
