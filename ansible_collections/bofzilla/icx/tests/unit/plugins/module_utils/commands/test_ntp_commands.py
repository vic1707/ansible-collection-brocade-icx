from pathlib import Path

import pytest

from ansible_collections.bofzilla.icx.plugins.module_utils.commands.ntp import ShowNtpAssociations, ShowNtpStatus
from ansible_collections.bofzilla.icx.tests.unit.plugins.mock_utils import ParserErrorFixture, ParserSuccessFixture, discover_parser_fixtures

ASSOCIATION_FIXTURES = discover_parser_fixtures(Path(__file__).parents[4] / "fixtures" / "parsers" / "show_ntp_associations")
STATUS_FIXTURES = discover_parser_fixtures(Path(__file__).parents[4] / "fixtures" / "parsers" / "show_ntp_status")


@pytest.mark.parametrize(
	"name,fixture",
	[(name, fixture) for name, fixture in ASSOCIATION_FIXTURES if isinstance(fixture, ParserSuccessFixture)],
	ids=[name for name, fixture in ASSOCIATION_FIXTURES if isinstance(fixture, ParserSuccessFixture)],
)
def test_show_ntp_associations_parse_success(name: str, fixture: ParserSuccessFixture):
	result = ShowNtpAssociations().parse_res(fixture.raw)
	assert sorted(str(server) for server in result.servers) == fixture.expected["servers"]


@pytest.mark.parametrize(
	"name,fixture",
	[(name, fixture) for name, fixture in STATUS_FIXTURES if isinstance(fixture, ParserSuccessFixture)],
	ids=[name for name, fixture in STATUS_FIXTURES if isinstance(fixture, ParserSuccessFixture)],
)
def test_show_ntp_status_parse_success(name: str, fixture: ParserSuccessFixture):
	assert ShowNtpStatus().parse_res(fixture.raw).enabled is fixture.expected["enabled"]


@pytest.mark.parametrize(
	"name,fixture",
	[(name, fixture) for name, fixture in STATUS_FIXTURES if isinstance(fixture, ParserErrorFixture)],
	ids=[name for name, fixture in STATUS_FIXTURES if isinstance(fixture, ParserErrorFixture)],
)
def test_show_ntp_status_parse_error(name: str, fixture: ParserErrorFixture):
	with pytest.raises(ValueError, match=fixture.error):
		ShowNtpStatus().parse_res(fixture.raw)
