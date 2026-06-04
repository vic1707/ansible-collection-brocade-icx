from pathlib import Path

import pytest

from ansible_collections.bofzilla.icx.plugins.module_utils.commands.show.clock import ShowClock
from ansible_collections.bofzilla.icx.tests.unit.plugins.mock_utils import ParserErrorFixture, ParserSuccessFixture, discover_parser_fixtures

FIXTURES = discover_parser_fixtures(Path(__file__).parents[4] / "fixtures" / "parsers" / "show_clock")


@pytest.mark.parametrize(
	"name,fixture",
	[(name, fixture) for name, fixture in FIXTURES if isinstance(fixture, ParserSuccessFixture)],
	ids=[name for name, fixture in FIXTURES if isinstance(fixture, ParserSuccessFixture)],
)
def test_show_clock_parse_success(name: str, fixture: ParserSuccessFixture):
	assert ShowClock().parse_res(fixture.raw).isoformat() == fixture.expected


@pytest.mark.parametrize(
	"name,fixture",
	[(name, fixture) for name, fixture in FIXTURES if isinstance(fixture, ParserErrorFixture)],
	ids=[name for name, fixture in FIXTURES if isinstance(fixture, ParserErrorFixture)],
)
def test_show_clock_parse_error(name: str, fixture: ParserErrorFixture):
	with pytest.raises(ValueError, match=fixture.error):
		ShowClock().parse_res(fixture.raw)
