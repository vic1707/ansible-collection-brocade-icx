from ansible_collections.vic1707.icx.plugins.modules.show import clock
from ansible_collections.vic1707.icx.tests.unit.plugins.mock_utils import module_runner  # noqa: F401


def test_show_clock_result(module_runner):  # noqa: F811
	run = module_runner(clock, {"clock": "2026-06-01T22:42:04.149000+00:00"})
	data, _ = run()
	assert data == {
		"changed": False,
		"clock": "2026-06-01T22:42:04.149000+00:00",
		"command": "show clock",
	}


def test_show_clock_check_mode(module_runner):  # noqa: F811
	run = module_runner(clock, {"clock": "2026-06-01T22:42:04.149000+00:00"})
	data, _ = run(check_mode=True)
	assert data["changed"] is False
	assert data["command"] == "show clock"
