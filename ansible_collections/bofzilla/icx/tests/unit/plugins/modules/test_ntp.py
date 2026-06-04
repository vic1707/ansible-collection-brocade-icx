from pathlib import Path

import pytest

from ansible_collections.bofzilla.icx.plugins.modules import ntp
from ansible_collections.bofzilla.icx.tests.unit.plugins.mock_utils import (
	MODES,
	AnsibleFailJson,
	ErrorFixture,
	SuccessFixture,
	discover_fixtures,
	make_runner,  # noqa: F401
)

FIXTURES = discover_fixtures(Path(__file__).parents[3] / "fixtures" / "ntp")


def _expected_send_commands(expected: dict, check_mode: bool) -> list[str]:
	if check_mode or not expected["changed"]:
		return ["show ntp associations", "show ntp status"]

	commands = ["show ntp associations", "show ntp status"]
	for command in expected["command"]:
		if command == "write memory":
			commands.extend([command, "end"])
		else:
			commands.extend(["configure terminal", "ntp", command, "end"])
	return commands


def _expected_enable_calls(expected: dict, params: dict, check_mode: bool) -> list[str | None]:
	if check_mode or not expected["changed"]:
		return []
	return [params.get("enable_password")] * len(expected["command"])


@pytest.mark.parametrize("name,fixture", FIXTURES, ids=[f[0] for f in FIXTURES])
@pytest.mark.parametrize("mode", MODES)
def test_ntp(name, fixture: SuccessFixture | ErrorFixture, make_runner, mode):  # noqa: F811
	run = make_runner(ntp, fixture.output)
	match fixture:
		case SuccessFixture(params=params, expected=expected, expected_diff=expected_diff):
			data, mocks = run(params=params or {}, **mode)
			module_kwargs = mocks["AnsibleModuleFactory"].call_args.kwargs
			assert module_kwargs["argument_spec"]["servers"]["required"] is True
			assert module_kwargs["argument_spec"]["enabled"]["default"] is True
			assert module_kwargs["supports_check_mode"] is True
			if mode.get("diff"):
				if expected["changed"]:
					assert data["diff"] == expected_diff
					data = {key: value for key, value in data.items() if key != "diff"}
				else:
					assert "diff" not in data
			assert data == expected
			assert [call.args[0] for call in mocks["Connection"].send_command.call_args_list] == _expected_send_commands(expected, check_mode=mode.get("check_mode", False))
			assert [call.args[0] for call in mocks["Connection"].enable.call_args_list] == _expected_enable_calls(expected, params or {}, check_mode=mode.get("check_mode", False))

		case ErrorFixture(params=params, error=error_msg):
			data, mocks = run(params=params or {}, expect=AnsibleFailJson, **mode)
			module_kwargs = mocks["AnsibleModuleFactory"].call_args.kwargs
			assert module_kwargs["argument_spec"]["servers"]["required"] is True
			assert module_kwargs["argument_spec"]["enabled"]["default"] is True
			assert module_kwargs["supports_check_mode"] is True
			assert error_msg == data["msg"]
