import re
from typing import Any

from ansible_collections.bofzilla.icx.plugins.module_utils.module_common import blocks_by_prefix, port_list


def parse_vlans(raw: str) -> dict[int, dict[str, Any]]:
	vlans: dict[int, dict[str, Any]] = {}
	for header, body in blocks_by_prefix(raw, "vlan ").items():
		match = re.match(r"vlan (?P<id>\d+)(?: name (?P<name>.+?) by port| by port)?$", header)
		if not match:
			continue
		vlan_id = int(match.group("id"))
		vlans[vlan_id] = {
			"id": vlan_id,
			"name": (match.group("name") or "").strip('"') or None,
			"tagged": [],
			"untagged": [],
			"router_interface": None,
			"management": False,
			"default_gateways": [],
		}
		for line in body:
			if line.startswith("tagged "):
				vlans[vlan_id]["tagged"] = port_list(line.split()[1:])
			elif line.startswith("untagged "):
				vlans[vlan_id]["untagged"] = port_list(line.split()[1:])
			elif line.startswith("router-interface ve "):
				vlans[vlan_id]["router_interface"] = int(line.removeprefix("router-interface ve "))
			elif line == "management-vlan":
				vlans[vlan_id]["management"] = True
			elif line.startswith("default-gateway "):
				_, address, metric = line.split(maxsplit=2)
				vlans[vlan_id]["default_gateways"].append({"address": address, "metric": int(metric)})
	return vlans


def parse_interfaces(raw: str) -> dict[str, dict[str, Any]]:
	interfaces: dict[str, dict[str, Any]] = {}
	for header, body in blocks_by_prefix(raw, "interface ethernet ").items():
		name = header.removeprefix("interface ethernet ")
		state: dict[str, Any] = {
			"name": name,
			"description": None,
			"admin_state": "up",
			"speed_duplex": None,
			"dual_mode": None,
			"voice_vlan": None,
			"poe": {"enabled": None},
		}
		for line in body:
			if line.startswith("port-name "):
				state["description"] = line.removeprefix("port-name ")
			elif line == "disable":
				state["admin_state"] = "down"
			elif line.startswith("speed-duplex "):
				state["speed_duplex"] = line.removeprefix("speed-duplex ")
			elif line.startswith("dual-mode"):
				parts = line.split()
				state["dual_mode"] = int(parts[1]) if len(parts) > 1 else 1
			elif line.startswith("voice-vlan "):
				state["voice_vlan"] = int(line.removeprefix("voice-vlan "))
			elif line.startswith("inline power"):
				state["poe"] = _parse_poe(line)
		interfaces[name] = state
	for name, membership in _interface_membership(raw).items():
		interfaces.setdefault(name, {"name": name, "poe": {"enabled": None}}).update(membership)
	return interfaces


def _parse_poe(line: str) -> dict[str, Any]:
	tokens = line.split()
	poe: dict[str, Any] = {"enabled": True}
	if "decouple-datalink" in tokens:
		poe["decouple_datalink"] = True
	if "power-by-class" in tokens:
		poe["power_by_class"] = int(tokens[tokens.index("power-by-class") + 1])
	if "power-limit" in tokens:
		poe["power_limit"] = int(tokens[tokens.index("power-limit") + 1])
	if "priority" in tokens:
		poe["priority"] = int(tokens[tokens.index("priority") + 1])
	return poe


def _interface_membership(raw: str) -> dict[str, dict[str, Any]]:
	membership: dict[str, dict[str, Any]] = {}
	for vlan_id, vlan in parse_vlans(raw).items():
		for port_range in vlan["tagged"]:
			for port in _expand_port_range(port_range):
				membership.setdefault(port, {"tagged_vlans": [], "untagged_vlan": None})["tagged_vlans"].append(vlan_id)
		for port_range in vlan["untagged"]:
			for port in _expand_port_range(port_range):
				membership.setdefault(port, {"tagged_vlans": [], "untagged_vlan": None})["untagged_vlan"] = vlan_id
	for state in membership.values():
		state["tagged_vlans"] = sorted(state["tagged_vlans"])
	return membership


def _expand_port_range(value: str) -> list[str]:
	if " to " not in value:
		return [value]
	start, end = value.split(" to ", 1)
	start_prefix, start_port = start.rsplit("/", 1)
	end_prefix, end_port = end.rsplit("/", 1)
	if start_prefix != end_prefix:
		raise ValueError(f"cross-slot port range is unsupported: {value}")
	return [f"{start_prefix}/{port}" for port in range(int(start_port), int(end_port) + 1)]


def parse_ve_interfaces(raw: str) -> dict[int, dict[str, Any]]:
	interfaces: dict[int, dict[str, Any]] = {}
	for header, body in blocks_by_prefix(raw, "interface ve ").items():
		ve_id = int(header.removeprefix("interface ve "))
		interfaces[ve_id] = {"id": ve_id, "ip_address": None}
		for line in body:
			if line.startswith("ip address "):
				interfaces[ve_id]["ip_address"] = line.removeprefix("ip address ")
	return interfaces


def parse_lags(raw: str) -> dict[str, dict[str, Any]]:
	lags: dict[str, dict[str, Any]] = {}
	for header, body in blocks_by_prefix(raw, "lag ").items():
		match = re.match(r'lag (?P<name>"[^"]+"|\S+) (?P<mode>dynamic|static|keep-alive)(?: id (?P<id>\d+))?$', header)
		if not match:
			continue
		name = match.group("name").strip('"')
		state: dict[str, Any] = {
			"name": name,
			"mode": match.group("mode"),
			"id": int(match.group("id")) if match.group("id") else None,
			"ports": [],
			"primary_port": None,
			"deployed": False,
			"passive": False,
		}
		for line in body:
			if line.startswith("ports "):
				state["ports"] = port_list(line.split()[1:])
			elif line.startswith("primary-port "):
				state["primary_port"] = line.removeprefix("primary-port ")
			elif line.startswith("deploy"):
				state["deployed"] = True
				state["passive"] = line == "deploy passive"
		lags[name] = state
	return lags
