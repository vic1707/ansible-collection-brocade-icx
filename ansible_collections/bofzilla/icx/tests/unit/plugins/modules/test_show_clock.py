from pathlib import Path

import pytest

from ansible_collections.bofzilla.icx.plugins.modules.show import clock
from ansible_collections.bofzilla.icx.tests.unit.plugins.mock_utils import (
	MODES,
	AnsibleFailJson,
	ErrorFixture,
	SuccessFixture,
	discover_fixtures,
	make_runner,  # noqa: F401
)

FIXTURES = discover_fixtures(Path(__file__).parents[3] / "fixtures" / "show" / "clock")


@pytest.mark.parametrize("name,fixture", FIXTURES, ids=[f[0] for f in FIXTURES])
@pytest.mark.parametrize("mode", MODES)
def test_show_clock(name, fixture: SuccessFixture | ErrorFixture, make_runner, mode):  # noqa: F811
	run = make_runner(clock, fixture.output)
	match fixture:
		case SuccessFixture():
			data, _ = run(params=fixture.params or {}, **mode)
			assert data == {"changed": False, "clock": fixture.expected, "command": "show clock"}

		case ErrorFixture(error=error_msg):
			data, _ = run(params=fixture.params or {}, expect=AnsibleFailJson, **mode)
			assert error_msg == data["msg"]
