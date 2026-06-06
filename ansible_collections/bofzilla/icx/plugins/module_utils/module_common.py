import json
from collections.abc import Iterable
from ipaddress import ip_address, ip_interface
from typing import Any

from ansible_collections.bofzilla.icx.plugins.module_utils.commands.config import ConfigLine
from ansible_collections.bofzilla.icx.plugins.module_utils.commands.system import WriteMemory

SAVE_WHEN_ARGUMENT_SPEC = {
	"save_when": {"type": "str", "choices": ["changed", "always", "never"], "default": "changed"},
	"save": {"type": "bool", "required": False},
}


def resolve_save_when(params: dict[str, Any]) -> str:
	if params.get("save") is True:
		return "changed"
	if params.get("save") is False:
		return "never"
	return params.get("save_when") or "changed"


def should_save(save_when: str, changed: bool) -> bool:
	return save_when == "always" or (save_when == "changed" and changed)


def run_config_commands(client: Any, module: Any, commands: list[ConfigLine], changed: bool, save_when: str) -> bool:
	save = should_save(save_when, changed)
	if changed and not module.check_mode:
		for cmd in commands:
			client.run(cmd)
	if save and not module.check_mode:
		client.run(WriteMemory())
	return save


def command_strings(commands: Iterable[Any], saved: bool = False) -> list[str]:
	result = [cmd.command() for cmd in commands]
	if saved:
		result.append("write memory")
	return result


def json_diff(before: Any, after: Any) -> dict[str, str]:
	return text_diff(
		json.dumps(before, indent=2, sort_keys=True),
		json.dumps(after, indent=2, sort_keys=True),
	)


def text_diff(before: str, after: str) -> dict[str, str]:
	return {
		"before": _ensure_trailing_newline(before),
		"after": _ensure_trailing_newline(after),
	}


def _ensure_trailing_newline(value: str) -> str:
	return value if value.endswith("\n") else f"{value}\n"


def validate_ip(value: str) -> str:
	return str(ip_address(value))


def validate_ip_interface(value: str) -> str:
	return str(ip_interface(value))


def clean_lines(raw: str) -> list[str]:
	lines: list[str] = []
	for line in raw.splitlines():
		line = line.strip()
		if not line or line == "!" or line.startswith("Current configuration:"):
			continue
		lines.append(line)
	return lines


def config_blocks(raw: str) -> list[list[str]]:
	blocks: list[list[str]] = []
	current: list[str] = []
	for original in raw.splitlines():
		line = original.strip()
		if not line or line.startswith("Current configuration:"):
			continue
		if line == "!":
			if current:
				blocks.append(current)
				current = []
			continue
		current.append(line)
	if current:
		blocks.append(current)
	return blocks


def global_config_lines(raw: str) -> list[str]:
	headers = ("vlan ", "interface ", "lag ", "router ", "vrf ", "ip dhcp-server-pool ", "ntp")
	lines: list[str] = []
	for block in config_blocks(raw):
		if block and not block[0].startswith(headers):
			lines.extend(block)
	return lines


def blocks_by_prefix(raw: str, prefix: str) -> dict[str, list[str]]:
	items: dict[str, list[str]] = {}
	for block in config_blocks(raw):
		if block and block[0].startswith(prefix):
			items[block[0]] = block[1:]
	return items


def first_matching(lines: Iterable[str], prefix: str) -> str | None:
	for line in lines:
		if line.startswith(prefix):
			return line
	return None


def bool_line(lines: Iterable[str], line: str) -> bool:
	return line in set(lines)


def quote_if_needed(value: str) -> str:
	if any(ch.isspace() for ch in value):
		return f'"{value}"'
	return value


def port_list(tokens: list[str]) -> list[str]:
	ports: list[str] = []
	i = 0
	while i < len(tokens):
		if tokens[i] in {"ethernet", "ethe"} and i + 1 < len(tokens):
			start = tokens[i + 1]
			if i + 3 < len(tokens) and tokens[i + 2] == "to":
				ports.append(f"{start} to {tokens[i + 3]}")
				i += 4
			else:
				ports.append(start)
				i += 2
		else:
			i += 1
	return ports


def port_list_command(ports: list[str]) -> str:
	parts: list[str] = []
	for port in ports:
		if " to " in port:
			start, end = port.split(" to ", 1)
			parts.append(f"ethernet {start} to {end}")
		else:
			parts.append(f"ethernet {port}")
	return " ".join(parts)


def vlan_header(vlan_id: int, name: str | None = None) -> str:
	if name:
		return f"vlan {vlan_id} name {quote_if_needed(name)} by port"
	return f"vlan {vlan_id} by port"
