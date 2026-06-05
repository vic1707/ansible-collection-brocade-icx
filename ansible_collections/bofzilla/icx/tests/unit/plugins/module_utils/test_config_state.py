from ansible_collections.bofzilla.icx.plugins.module_utils.config_state import running_config_matching


class FakeClient:
	def __init__(self, outputs: dict[str, str], fail_include: bool = False) -> None:
		self.outputs = outputs
		self.fail_include = fail_include
		self.commands: list[str] = []

	def run(self, cmd):
		command = cmd.command()
		self.commands.append(command)
		if command == "show running-config":
			return self.outputs["full"]
		if self.fail_include:
			raise RuntimeError("include unsupported")
		return self.outputs.get(cmd.pattern, "")


def test_running_config_matching_uses_include_and_deduplicates():
	client = FakeClient(
		{
			"logging ": "logging host 192.0.2.10\nlogging persistence\n",
			"host ": "logging host 192.0.2.10\nhostname icx\n",
			"full": "unused",
		}
	)

	assert running_config_matching(client, ("logging ", "host ")) == "logging host 192.0.2.10\nlogging persistence\nhostname icx"
	assert client.commands == ["show running-config | include logging ", "show running-config | include host "]


def test_running_config_matching_falls_back_to_full_config():
	client = FakeClient({"full": "hostname icx\nlogging persistence"}, fail_include=True)

	assert running_config_matching(client, ("logging ",)) == "hostname icx\nlogging persistence"
	assert client.commands == ["show running-config | include logging ", "show running-config"]
