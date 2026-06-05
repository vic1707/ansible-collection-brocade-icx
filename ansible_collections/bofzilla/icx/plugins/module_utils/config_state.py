from typing import Any

from ansible_collections.bofzilla.icx.plugins.module_utils.commands.config import ShowRunningConfig, ShowRunningConfigInclude
from ansible_collections.bofzilla.icx.plugins.module_utils.module_common import clean_lines


def running_config(client: Any) -> str:
	return client.run(ShowRunningConfig())


def running_config_matching(client: Any, patterns: list[str] | tuple[str, ...]) -> str:
	"""Return flat running-config lines matching one or more pipe patterns.

	This is intended for global configuration state where block structure is not
	needed. If a device image rejects pipe filtering, fall back to the full
	running-config so modules keep working.
	"""
	lines: list[str] = []
	seen: set[str] = set()
	try:
		for pattern in patterns:
			for line in clean_lines(client.run(ShowRunningConfigInclude(pattern))):
				if line not in seen:
					seen.add(line)
					lines.append(line)
	except Exception:
		return running_config(client)
	return "\n".join(lines)
