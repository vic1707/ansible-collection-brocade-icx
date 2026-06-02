from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml
from ansible.module_utils.connection import Connection
from pydantic import ConfigDict
from pydantic.dataclasses import dataclass


@dataclass(config=ConfigDict(extra="forbid"))
class SuccessFixture:
	output: str
	expected: Any
	params: dict[str, Any] | None = None
	expected_diff: dict[str, str] | None = None


@dataclass(config=ConfigDict(extra="forbid"))
class ErrorFixture:
	output: str
	error: str
	params: dict[str, Any] | None = None


def discover_fixtures(fixtures_dir: str | Path) -> list[tuple[str, SuccessFixture | ErrorFixture]]:
	"""Discover *.success.yml and *.error.yml files under *fixtures_dir*.

	Returns a list of ``(name, fixture)`` tuples where *fixture* is a
	:class:`SuccessFixture` or :class:`ErrorFixture` — use ``match/case``
	to branch in the test.
	"""
	items: list[tuple[str, SuccessFixture | ErrorFixture]] = []
	root = Path(fixtures_dir)
	for f in sorted(root.glob("*.success.yml")):
		data = yaml.safe_load(f.read_text())
		items.append((f.stem.removesuffix(".success"), SuccessFixture(**data)))
	for f in sorted(root.glob("*.error.yml")):
		data = yaml.safe_load(f.read_text())
		items.append((f.stem.removesuffix(".error"), ErrorFixture(**data)))
	return items


MODES = [
	pytest.param({}, id="normal"),
	pytest.param({"check_mode": True}, id="check"),
	pytest.param({"diff": True}, id="diff"),
	pytest.param({"check_mode": True, "diff": True}, id="check_diff"),
]


class AnsibleExitJson(BaseException):
	pass


class AnsibleFailJson(BaseException):
	pass


def exit_json(*_, **kwargs):
	raise AnsibleExitJson(kwargs)


def fail_json(*_, **kwargs):
	raise AnsibleFailJson(kwargs)


@pytest.fixture(scope="module")
def make_runner():
	def _make_runner(
		py_module: Any,
		cli_output: str,
	) -> Callable[..., tuple[dict, dict[str, MagicMock]]]:
		monkeypatch = pytest.MonkeyPatch()
		mocks: dict[str, MagicMock] = {}

		module = MagicMock()
		module.exit_json.side_effect = exit_json
		module.fail_json.side_effect = fail_json
		monkeypatch.setattr(py_module, "AnsibleModule", lambda *_, **__: module)
		mocks["AnsibleModule"] = module

		connection = MagicMock()
		connection.__class__ = Connection  # type: ignore[assignment]
		connection.send_command.return_value = cli_output

		monkeypatch.setattr(py_module, "Connection", lambda *_, **__: connection)
		mocks["Connection"] = connection

		def run_with_params(
			*,
			params: dict[str, Any] | None = None,
			diff: bool = False,
			check_mode: bool = False,
			expect: type[BaseException] = AnsibleExitJson,
		) -> tuple[Any, dict[str, MagicMock]]:
			module = mocks["AnsibleModule"]
			module._diff = diff
			module.check_mode = check_mode
			module.params = params or {}

			with pytest.raises(expect) as excinfo:
				py_module.main()

			return excinfo.value.args[0], mocks

		return run_with_params

	return _make_runner
