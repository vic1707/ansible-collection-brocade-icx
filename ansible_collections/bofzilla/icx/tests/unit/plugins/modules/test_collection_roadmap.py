from ansible_collections.bofzilla.icx.plugins.modules import (
	auth,
	backup,
	facts,
	interfaces,
	lags,
	lldp,
	logging,
	management_access,
	management_oob,
	snmp,
	system,
	vlans,
)
from ansible_collections.bofzilla.icx.tests.unit.plugins.mock_utils import AnsibleFailJson, module_runner  # noqa: F401

EMPTY_CONFIG = "Current configuration:\n!\n"


def test_system_configures_changed_state_with_diff_and_default_save(module_runner):  # noqa: F811
	run = module_runner(system, {"running_config": EMPTY_CONFIG})
	data, _ = run(
		params={
			"hostname": "icx-homelab",
			"dns_servers": ["1.1.1.1", "9.9.9.9"],
			"logging": {"console": False, "cli_command": True},
		},
		diff=True,
	)
	assert data["changed"] is True
	assert data["saved"] is True
	assert data["command"] == [
		"hostname icx-homelab",
		"ip dns server-address 1.1.1.1 9.9.9.9",
		"logging cli-command",
		"write memory",
	]
	assert "diff" in data


def test_system_no_change_is_idempotent(module_runner):  # noqa: F811
	run = module_runner(
		system,
		{
			"running_config": """Current configuration:
!
hostname icx-homelab
ip dns server-address 1.1.1.1
logging cli-command
!
""",
		},
	)
	data, _ = run(params={"hostname": "icx-homelab", "dns_servers": ["1.1.1.1"], "logging": {"cli_command": True}}, diff=True)
	assert data["changed"] is False
	assert data["command"] == []
	assert "diff" not in data


def test_auth_creates_local_admin_and_redacts_passwords(module_runner):  # noqa: F811
	run = module_runner(auth, {"running_config": EMPTY_CONFIG, "users": ""})
	data, _ = run(
		params={
			"users": [{"name": "admin", "privilege": 0, "password": "dummy"}],
			"enable_passwords": {"super_user": "dummy"},
			"aaa": {"login_methods": ["local"], "enable_methods": ["local"], "privilege_mode": True},
		}
	)
	assert data["changed"] is True
	assert data["saved"] is True
	assert data["command"] == [
		"username admin privilege 0 password ********",
		"enable super-user-password ********",
		"aaa authentication login default local",
		"aaa authentication enable default local",
		"aaa authentication login privilege-mode",
		"write memory",
	]
	assert "dummy" not in repr(data)


def test_auth_rejects_local_aaa_without_super_user(module_runner):  # noqa: F811
	run = module_runner(auth, {"running_config": EMPTY_CONFIG, "users": ""})
	data, _ = run(params={"aaa": {"login_methods": ["local"]}}, expect=AnsibleFailJson)
	assert data["msg"] == "ValueError: local AAA requires at least one enabled privilege 0 user"


def test_management_access_configures_services_and_redacts_telnet_password(module_runner):  # noqa: F811
	run = module_runner(
		management_access,
		{
			"running_config": EMPTY_CONFIG,
			"ip_ssh_config": """SSH server : Disabled
SSH port : 22
Authentication methods : Password Public-key
SCP : Disabled
SSH IPv4 clients : All
""",
		},
	)
	data, _ = run(
		params={
			"ssh": {"enabled": True, "host_keys": [{"type": "rsa", "modulus": 2048}], "scp": True, "allowed_clients": ["192.168.1.10"]},
			"tftp": {"enabled": False},
			"web": {"http": False, "https": True},
			"telnet": {"authentication": True, "password": "dummy", "timeout": 30},
		}
	)
	assert data["changed"] is True
	assert data["command"] == [
		"crypto key generate rsa modulus 2048",
		"ip ssh scp enable",
		"ip ssh client 192.168.1.10",
		"tftp disable",
		"web-management https",
		"enable telnet authentication",
		"enable telnet password ********",
		"telnet timeout 30",
		"write memory",
	]


def test_management_access_disables_telnet(module_runner):  # noqa: F811
	run = module_runner(
		management_access,
		{
			"running_config": EMPTY_CONFIG,
			"ip_ssh_config": "SSH server : Disabled\n",
			"telnet_config": "Telnet server                   : Enabled\n",
		},
	)
	data, _ = run(params={"telnet": {"enabled": False}})
	assert data["changed"] is True
	assert data["command"] == ["no telnet server", "write memory"]


def test_management_oob_enables_dhcp_client(module_runner):  # noqa: F811
	run = module_runner(management_oob, {"running_config": EMPTY_CONFIG})
	data, _ = run(
		params={
			"mode": "dhcp",
		}
	)
	assert data["changed"] is True
	assert data["management_oob"]["mode"] == "dhcp"
	assert data["command"] == [
		"ip dhcp-client enable",
		"write memory",
	]


def test_management_oob_configures_static_address(module_runner):  # noqa: F811
	run = module_runner(management_oob, {"running_config": EMPTY_CONFIG})
	data, _ = run(
		params={
			"mode": "static",
			"ip_address": "192.168.1.105/24",
			"default_gateway": "192.168.1.1",
		}
	)
	assert data["changed"] is True
	assert data["command"] == [
		"ip address 192.168.1.105/24",
		"ip default-gateway 192.168.1.1",
		"write memory",
	]


def test_management_oob_dhcp_no_change(module_runner):  # noqa: F811
	run = module_runner(
		management_oob,
		{
			"running_config": """Current configuration:
!
ip address 192.168.99.23 255.255.255.0 dynamic
!
""",
		},
	)
	data, _ = run(params={"mode": "dhcp"})
	assert data["changed"] is False
	assert data["command"] == []


def test_management_oob_rejects_static_fields_in_dhcp_mode(module_runner):  # noqa: F811
	run = module_runner(management_oob, {"running_config": EMPTY_CONFIG})
	data, _ = run(params={"mode": "dhcp", "ip_address": "192.168.1.105/24"}, expect=AnsibleFailJson)
	assert data["msg"] == "ValueError: ip_address is only valid when mode=static"


def test_vlans_configures_management_vlan_flag(module_runner):  # noqa: F811
	run = module_runner(vlans, {"running_config": EMPTY_CONFIG})
	data, _ = run(params={"vlans": [{"id": 99, "name": "mgmt", "management": True}]})
	assert data["command"] == [
		"vlan 99 name mgmt by port",
		"management-vlan",
		"write memory",
	]


def test_vlans_no_change(module_runner):  # noqa: F811
	run = module_runner(vlans, {"running_config": "Current configuration:\n!\nvlan 10 name users by port\nrouter-interface ve 10\n!\n"})
	data, _ = run(params={"vlans": [{"id": 10, "name": "users", "router_interface": 10}]})
	assert data["changed"] is False
	assert data["command"] == []


def test_interfaces_access_port_translates_membership_and_poe(module_runner):  # noqa: F811
	run = module_runner(
		interfaces,
		{
			"running_config": """Current configuration:
!
vlan 1 by port
untagged ethernet 1/1/2
!
interface ethernet 1/1/2
!
""",
		},
	)
	data, _ = run(params={"interfaces": [{"name": "1/1/2", "description": "lab", "mode": "access", "access_vlan": 20, "poe": {"enabled": True, "priority": 2}}]})
	assert data["command"] == [
		"no untagged ethernet 1/1/2",
		"untagged ethernet 1/1/2",
		"port-name lab",
		"inline power priority 2",
		"write memory",
	]


def test_interfaces_trunk_check_mode_plans_without_running(module_runner):  # noqa: F811
	run = module_runner(interfaces, {"running_config": "Current configuration:\n!\ninterface ethernet 1/1/48\n!\n"})
	data, mocks = run(params={"interfaces": [{"name": "1/1/48", "mode": "trunk", "allowed_vlans": [10, 20]}]}, check_mode=True)
	assert data["changed"] is True
	assert data["saved"] is True
	assert [cmd.command() for cmd in mocks["CliClient"].commands if cmd.__class__.__name__ == "ConfigLine"] == []


def test_interfaces_rejects_native_vlan_on_trunk(module_runner):  # noqa: F811
	run = module_runner(interfaces, {"running_config": EMPTY_CONFIG})
	data, _ = run(params={"interfaces": [{"name": "1/1/48", "mode": "trunk", "native_vlan": 1, "allowed_vlans": [10, 20]}]}, expect=AnsibleFailJson)
	assert data["msg"] == "ValueError: interface 1/1/48: native_vlan is invalid with mode=trunk; use mode=general for a native VLAN"


def test_interfaces_rejects_general_without_native_vlan(module_runner):  # noqa: F811
	run = module_runner(interfaces, {"running_config": EMPTY_CONFIG})
	data, _ = run(params={"interfaces": [{"name": "1/1/3", "mode": "general", "allowed_vlans": [10, 20]}]}, expect=AnsibleFailJson)
	assert data["msg"] == "ValueError: interface 1/1/3: native_vlan is required with mode=general"


def test_lags_create_dynamic_lag(module_runner):  # noqa: F811
	run = module_runner(lags, {"running_config": EMPTY_CONFIG})
	data, _ = run(params={"lags": [{"name": "uplink", "mode": "dynamic", "id": 1, "ports": ["1/1/47", "1/1/48"], "primary_port": "1/1/47", "deployed": True}]})
	assert data["command"] == [
		"lag uplink dynamic id 1",
		"ports ethernet 1/1/47 ethernet 1/1/48",
		"primary-port 1/1/47",
		"deploy",
		"write memory",
	]


def test_lldp_updates_global_settings(module_runner):  # noqa: F811
	run = module_runner(lldp, {"running_config": EMPTY_CONFIG})
	data, _ = run(params={"enabled": True, "transmit_interval": 40, "tagged_packets": True})
	assert data["command"] == ["lldp tagged-packets process", "lldp transmit-interval 40", "write memory"]


def test_logging_replaces_hosts(module_runner):  # noqa: F811
	run = module_runner(logging, {"running_config": "Current configuration:\n!\nlogging host 192.168.1.2\n!\n"})
	data, _ = run(params={"hosts": [{"address": "192.168.1.3", "udp_port": 1514}]})
	assert data["command"] == ["no logging host 192.168.1.2", "logging host 192.168.1.3 udp-port 1514", "write memory"]


def test_snmp_redacts_communities(module_runner):  # noqa: F811
	run = module_runner(snmp, {"running_config": EMPTY_CONFIG})
	data, _ = run(params={"communities": [{"name": "private", "access": "ro"}], "contact": "ops"})
	assert data["command"] == ["snmp-server community ******** ro", "snmp-server contact ops", "write memory"]
	assert data["snmp"]["communities"] == [{"name": "********", "access": "ro"}]


def test_snmp_redacted_existing_community_is_opaque_match(module_runner):  # noqa: F811
	run = module_runner(snmp, {"running_config": "Current configuration:\n!\nsnmp-server community ..... ro\n!\n"})
	data, _ = run(params={"communities": [{"name": "private", "access": "ro"}]})
	assert data["changed"] is False
	assert data["command"] == []


def test_facts_returns_read_only_data(module_runner):  # noqa: F811
	run = module_runner(facts, {"version": "SW: Version 08.0.30\nHW: ICX7250\nSerial #: ABC123\n", "lldp_neighbors": "neighbors"})
	data, _ = run(params={"include_lldp": True})
	assert data["changed"] is False
	assert data["ansible_facts"]["icx"]["device"] == {"version": "08.0.30", "model": "ICX7250", "serial": "ABC123"}
	assert data["command"] == ["show version", "show lldp neighbors"]


def test_backup_check_mode_is_non_mutating(module_runner):  # noqa: F811
	run = module_runner(backup, {})
	data, mocks = run(params={"protocol": "tftp", "server": "192.168.1.10", "filename": "icx.cfg"}, check_mode=True)
	assert data == {"changed": False, "command": "copy running-config tftp 192.168.1.10 icx.cfg"}
	assert mocks["CliClient"].commands == []
