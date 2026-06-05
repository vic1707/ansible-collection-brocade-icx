from pathlib import Path

import pytest

from ansible_collections.bofzilla.icx.plugins.modules import ntp
from ansible_collections.bofzilla.icx.tests.unit.plugins.mock_utils import (
	AnsibleFailJson,
	ModuleErrorFixture,
	ModuleSuccessFixture,
	discover_module_fixtures,
	fixture_by_name,
	module_runner,  # noqa: F401
)

FIXTURES = discover_module_fixtures(Path(__file__).parents[3] / "fixtures" / "modules" / "ntp")


@pytest.mark.parametrize(
	"name,fixture",
	[(name, fixture) for name, fixture in FIXTURES if isinstance(fixture, ModuleSuccessFixture)],
	ids=[name for name, fixture in FIXTURES if isinstance(fixture, ModuleSuccessFixture)],
)
def test_ntp_results(name: str, fixture: ModuleSuccessFixture, module_runner):  # noqa: F811
	run = module_runner(ntp, fixture.state)
	data, _ = run(params=fixture.params or {})
	assert data == fixture.expected


@pytest.mark.parametrize(
	"name,fixture",
	[(name, fixture) for name, fixture in FIXTURES if isinstance(fixture, ModuleErrorFixture)],
	ids=[name for name, fixture in FIXTURES if isinstance(fixture, ModuleErrorFixture)],
)
def test_ntp_errors(name: str, fixture: ModuleErrorFixture, module_runner):  # noqa: F811
	run = module_runner(ntp, fixture.state or {})
	data, _ = run(params=fixture.params or {}, expect=AnsibleFailJson)
	assert data["msg"] == fixture.error


def test_ntp_check_mode_returns_planned_result(module_runner):  # noqa: F811
	fixture = fixture_by_name(FIXTURES, "add-server")
	assert isinstance(fixture, ModuleSuccessFixture)
	run = module_runner(ntp, fixture.state)
	data, _ = run(params=fixture.params or {}, check_mode=True)
	assert data == fixture.expected


def test_ntp_diff_changed(module_runner):  # noqa: F811
	fixture = fixture_by_name(FIXTURES, "replace-server-list")
	assert isinstance(fixture, ModuleSuccessFixture)
	run = module_runner(ntp, fixture.state)
	data, _ = run(params=fixture.params or {}, diff=True)
	assert data["diff"] == fixture.diff
	data = {key: value for key, value in data.items() if key != "diff"}
	assert data == fixture.expected


def test_ntp_diff_unchanged(module_runner):  # noqa: F811
	fixture = fixture_by_name(FIXTURES, "no-change")
	assert isinstance(fixture, ModuleSuccessFixture)
	run = module_runner(ntp, fixture.state)
	data, _ = run(params=fixture.params or {}, diff=True)
	assert "diff" not in data
	assert data == fixture.expected


def test_ntp_uses_running_config_when_associations_are_empty(module_runner):  # noqa: F811
	run = module_runner(
		ntp,
		{
			"associations": {"servers": []},
			"running_config": "Current configuration:\n!\nntp\n server 134.59.1.5\n!\n",
			"status": {"enabled": True},
		},
	)
	data, _ = run(params={"servers": ["134.59.1.5"], "enabled": True, "save_when": "never"})
	assert data == {
		"changed": False,
		"enabled": True,
		"servers": ["134.59.1.5"],
		"command": [],
	}
