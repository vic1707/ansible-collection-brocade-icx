from pathlib import Path

import pytest

from ansible_collections.bofzilla.icx.plugins.modules import clock
from ansible_collections.bofzilla.icx.tests.unit.plugins.mock_utils import (
	AnsibleFailJson,
	ModuleErrorFixture,
	ModuleSuccessFixture,
	discover_module_fixtures,
	fixture_by_name,
	module_runner,  # noqa: F401
)

FIXTURES = discover_module_fixtures(Path(__file__).parents[3] / "fixtures" / "modules" / "clock")


def test_clock_requires_time_and_timezone_together():
	assert clock.REQUIRED_TOGETHER == [["time", "timezone"]]


@pytest.mark.parametrize(
	"name,fixture",
	[(name, fixture) for name, fixture in FIXTURES if isinstance(fixture, ModuleSuccessFixture)],
	ids=[name for name, fixture in FIXTURES if isinstance(fixture, ModuleSuccessFixture)],
)
def test_clock_results(name: str, fixture: ModuleSuccessFixture, module_runner):  # noqa: F811
	run = module_runner(clock, fixture.state)
	data, _ = run(params=fixture.params or {})
	assert data == fixture.expected


@pytest.mark.parametrize(
	"name,fixture",
	[(name, fixture) for name, fixture in FIXTURES if isinstance(fixture, ModuleErrorFixture)],
	ids=[name for name, fixture in FIXTURES if isinstance(fixture, ModuleErrorFixture)],
)
def test_clock_errors(name: str, fixture: ModuleErrorFixture, module_runner):  # noqa: F811
	run = module_runner(clock, fixture.state or {})
	data, _ = run(params=fixture.params or {}, expect=AnsibleFailJson)
	assert data["msg"] == fixture.error


def test_clock_check_mode_returns_planned_result(module_runner):  # noqa: F811
	fixture = fixture_by_name(FIXTURES, "set-explicit-time")
	assert isinstance(fixture, ModuleSuccessFixture)
	run = module_runner(clock, fixture.state)
	data, _ = run(params=fixture.params or {}, check_mode=True)
	assert data == fixture.expected


def test_clock_diff_changed(module_runner):  # noqa: F811
	fixture = fixture_by_name(FIXTURES, "set-explicit-time")
	assert isinstance(fixture, ModuleSuccessFixture)
	run = module_runner(clock, fixture.state)
	data, _ = run(params=fixture.params or {}, diff=True)
	assert data["diff"] == fixture.diff
	data = {key: value for key, value in data.items() if key != "diff"}
	assert data == fixture.expected


def test_clock_diff_unchanged(module_runner):  # noqa: F811
	fixture = fixture_by_name(FIXTURES, "no-change-within-one-second")
	assert isinstance(fixture, ModuleSuccessFixture)
	run = module_runner(clock, fixture.state)
	data, _ = run(params=fixture.params or {}, diff=True)
	assert "diff" not in data
	assert data == fixture.expected
