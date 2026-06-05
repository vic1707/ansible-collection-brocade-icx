from typing import Any

import pytest
from pydantic import ValidationError

from ansible_collections.bofzilla.icx.plugins.module_utils.commands.config import ConfigLine, ExecLine, ShowLldpNeighbors


def test_config_line_builds_single_submode_stack():
	cmd = ConfigLine("ip address 192.168.1.10/24", "interface ve 99")

	assert cmd.modes == ["configure terminal", "interface ve 99"]


def test_config_line_builds_tuple_submode_stack():
	cmd = ConfigLine("server 1.1.1.1", ("ntp",))

	assert cmd.modes == ["configure terminal", "ntp"]


def test_command_dataclasses_reject_unknown_fields():
	params: dict[str, Any] = {"line": "copy running-config startup-config", "unexpected": True}

	with pytest.raises(ValidationError):
		ExecLine(**params)


def test_command_dataclasses_coerce_field_types():
	detail: Any = "true"
	cmd = ShowLldpNeighbors(detail=detail)

	assert cmd.detail is True
