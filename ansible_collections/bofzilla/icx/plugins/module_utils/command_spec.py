from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import ClassVar


class Command[Res](ABC):
	"""Base for all CLI commands.

	``modes`` encodes the execution context:
	- ``None``  → user EXEC (no enable)
	- ``[]``    → privileged EXEC (enable, no config sub-modes, ``end`` after)
	- ``[...]`` → config sub-modes (enable, enter each mode, ``end`` after)
	"""

	modes: ClassVar[list[str] | None] = None

	@abstractmethod
	def command(self) -> str: ...

	@abstractmethod
	def parse_res(self, raw: str) -> Res: ...


def enabled[T: type[Command]](cls: T) -> T:
	"""Mark a command as requiring privileged EXEC mode (``modes = []``)."""
	setattr(cls, "modes", [])  # noqa: B010
	return cls


def config[T: type[Command]](*modes: str) -> Callable[[T], T]:
	"""Mark a command as running in config sub-modes (implies enable)."""

	def decorator(cls: T) -> T:
		setattr(cls, "modes", list(modes))  # noqa: B010
		return cls

	return decorator
