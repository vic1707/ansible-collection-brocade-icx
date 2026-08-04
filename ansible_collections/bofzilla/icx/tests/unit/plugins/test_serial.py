import os
import re
from unittest.mock import Mock, call

os.environ.setdefault("ANSIBLE_LOCAL_TEMP", "/private/tmp")

from ansible_collections.bofzilla.icx.plugins.cliconf.icx import ENABLE_PASSWORD_PROMPT
from ansible_collections.bofzilla.icx.plugins.connection.serial import Connection


def test_serial_logout_cancels_prompts_and_ends_session():
	connection = object.__new__(Connection)
	connection._serial = Mock()

	connection._logout()

	connection._serial.write.assert_called_once_with(b"\x03\rlogout\r")
	connection._serial.flush.assert_called_once_with()


def test_serial_answers_optional_enable_prompts_by_position():
	connection = object.__new__(Connection)
	connection._serial = Mock()
	prompts = [r"User Name: ?$", r"Password: ?$"]
	answers = ["admin", "secret"]

	assert not connection._handle_prompt(b"\r\nUser Name:", prompts, answers, True, False)
	assert connection._handle_prompt(b"\r\nPassword:", prompts, answers, True, False)

	assert connection._serial.write.call_args_list == [call(b"admin\r"), call(b"secret\r")]


def test_enable_password_prompt_matches_router_image():
	assert re.search(ENABLE_PASSWORD_PROMPT, "\r\nEnable Password:")
