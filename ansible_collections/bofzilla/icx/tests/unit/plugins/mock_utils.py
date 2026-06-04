from collections.abc import Callable
from datetime import datetime
from ipaddress import ip_address
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml
from ansible.module_utils.connection import Connection
from pydantic import ConfigDict
from pydantic.dataclasses import dataclass

from ansible_collections.bofzilla.icx.plugins.module_utils.commands.ntp import NtpAssociations, NtpStatus


@dataclass(config=ConfigDict(extra="forbid"))
class ParserSuccessFixture:
	raw: str
	expected: Any


@dataclass(config=ConfigDict(extra="forbid"))
class ParserErrorFixture:
	raw: str
	error: str


@dataclass(config=ConfigDict(extra="forbid"))
class ModuleSuccessFixture:
	state: dict[str, Any]
	expected: dict[str, Any]
	params: dict[str, Any] | None = None
	diff: dict[str, str] | None = None


@dataclass(config=ConfigDict(extra="forbid"))
class ModuleErrorFixture:
	error: str
	params: dict[str, Any] | None = None
	state: dict[str, Any] | None = None


def discover_parser_fixtures(fixtures_dir: str | Path) -> list[tuple[str, ParserSuccessFixture | ParserErrorFixture]]:
	return _discover_fixtures(fixtures_dir, ParserSuccessFixture, ParserErrorFixture)


def discover_module_fixtures(fixtures_dir: str | Path) -> list[tuple[str, ModuleSuccessFixture | ModuleErrorFixture]]:
	return _discover_fixtures(fixtures_dir, ModuleSuccessFixture, ModuleErrorFixture)


def fixture_by_name[T](fixtures: list[tuple[str, T]], name: str) -> T:
	for fixture_name, fixture in fixtures:
		if fixture_name == name:
			return fixture
	raise KeyError(name)


def _discover_fixtures[T](fixtures_dir: str | Path, success_cls: type[T], error_cls: type[T]) -> list[tuple[str, T]]:
	items: list[tuple[str, T]] = []
	root = Path(fixtures_dir)
	for f in sorted(root.glob("*.success.yml")):
		items.append((f.stem.removesuffix(".success"), success_cls(**yaml.safe_load(f.read_text()))))
	for f in sorted(root.glob("*.error.yml")):
		items.append((f.stem.removesuffix(".error"), error_cls(**yaml.safe_load(f.read_text()))))
	return items


class AnsibleExitJson(BaseException):
	pass


class AnsibleFailJson(BaseException):
	pass


def exit_json(*_: Any, **kwargs: Any) -> None:
	raise AnsibleExitJson(kwargs)


def fail_json(*_: Any, **kwargs: Any) -> None:
	raise AnsibleFailJson(kwargs)


def _params_with_defaults(params: dict[str, Any], argument_spec: Any) -> dict[str, Any]:
	if not isinstance(argument_spec, dict):
		return params

	with_defaults = dict(params)
	for name, spec in argument_spec.items():
		if isinstance(spec, dict) and "default" in spec and name not in with_defaults:
			with_defaults[name] = spec["default"]
	return with_defaults


@pytest.fixture
def module_runner(monkeypatch: pytest.MonkeyPatch):
	def _module_runner(py_module: Any, state: dict[str, Any] | None = None) -> Callable[..., tuple[Any, dict[str, Any]]]:
		module = MagicMock()
		module.exit_json.side_effect = exit_json
		module.fail_json.side_effect = fail_json
		mocks: dict[str, Any] = {"AnsibleModule": module}

		def create_module(*args: Any, **kwargs: Any) -> MagicMock:
			argument_spec = kwargs.get("argument_spec", args[0] if args else None)
			module.params = _params_with_defaults(module.params, argument_spec)
			return module

		ansible_module = MagicMock(side_effect=create_module)
		monkeypatch.setattr(py_module, "AnsibleModule", ansible_module)
		mocks["AnsibleModuleFactory"] = ansible_module

		connection = MagicMock()
		connection.__class__ = Connection  # type: ignore[assignment]
		monkeypatch.setattr(py_module, "Connection", lambda *_, **__: connection)
		mocks["Connection"] = connection

		fake_client = _FakeCliClient(state or {})
		client_factory = MagicMock(return_value=fake_client)
		monkeypatch.setattr(py_module, "CliClient", client_factory)
		mocks["CliClient"] = fake_client
		mocks["CliClientFactory"] = client_factory

		def run_with_params(
			*,
			params: dict[str, Any] | None = None,
			diff: bool = False,
			check_mode: bool = False,
			expect: type[BaseException] = AnsibleExitJson,
		) -> tuple[Any, dict[str, Any]]:
			module._diff = diff
			module.check_mode = check_mode
			module.params = params or {}

			with pytest.raises(expect) as excinfo:
				py_module.main()

			return excinfo.value.args[0], mocks

		return run_with_params

	return _module_runner


class _FakeCliClient:
	def __init__(self, state: dict[str, Any]) -> None:
		self.state = state
		self.commands: list[Any] = []

	def run(self, cmd: Any) -> Any:
		self.commands.append(cmd)
		match cmd.__class__.__name__:
			case "ShowClock":
				return datetime.fromisoformat(self.state["clock"])
			case "ShowNtpAssociations":
				return NtpAssociations(servers=frozenset(ip_address(server) for server in self.state["associations"]["servers"]))
			case "ShowNtpStatus":
				return NtpStatus(enabled=self.state["status"]["enabled"])
			case _:
				return None
