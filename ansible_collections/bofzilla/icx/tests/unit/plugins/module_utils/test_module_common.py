from ansible_collections.bofzilla.icx.plugins.module_utils.module_common import json_diff, text_diff


def test_json_diff_ends_with_newline():
	diff = json_diff({"before": True}, {"after": True})

	assert diff["before"].endswith("\n")
	assert diff["after"].endswith("\n")


def test_text_diff_ends_with_newline():
	diff = text_diff("before", "after\n")

	assert diff == {"before": "before\n", "after": "after\n"}
