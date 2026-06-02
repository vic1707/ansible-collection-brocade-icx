from pathlib import Path

import pytest

from ansible_collections.bofzilla.icx.plugins.modules import clock
from ansible_collections.bofzilla.icx.tests.unit.plugins.mock_utils import (
	MODES,
	AnsibleFailJson,
	ErrorFixture,
	SuccessFixture,
	discover_fixtures,
	make_runner,  # noqa: F401
)

FIXTURES = discover_fixtures(Path(__file__).parents[3] / "fixtures" / "clock")


def test_clock_requires_time_and_timezone_together():
	assert clock.REQUIRED_TOGETHER == [["time", "timezone"]]


def _expected_send_commands(expected: dict, check_mode: bool) -> list[str]:
	if check_mode or not expected["changed"]:
		return ["show clock"]

	commands = ["show clock"]
	for command in expected["command"]:
		if command.startswith(("clock timezone", "clock summer-time", "no clock summer-time")):
			commands.extend(["configure terminal", command, "end"])
		else:
			commands.append(command)
	return commands


@pytest.mark.parametrize("name,fixture", FIXTURES, ids=[f[0] for f in FIXTURES])
@pytest.mark.parametrize("mode", MODES)
def test_clock(name, fixture: SuccessFixture | ErrorFixture, make_runner, mode):  # noqa: F811
	run = make_runner(clock, fixture.output)
	match fixture:
		case SuccessFixture(params=params, expected=expected, expected_diff=expected_diff):
			data, mocks = run(params=params or {}, **mode)
			if mode.get("diff"):
				if expected["changed"]:
					assert data["diff"] == expected_diff
					data = {key: value for key, value in data.items() if key != "diff"}
				else:
					assert "diff" not in data
			assert data == expected
			assert [call.args[0] for call in mocks["Connection"].send_command.call_args_list] == _expected_send_commands(expected, check_mode=mode.get("check_mode", False))

		case ErrorFixture(params=params, error=error_msg):
			data, _ = run(params=params or {}, expect=AnsibleFailJson, **mode)
			assert error_msg == data["msg"]
