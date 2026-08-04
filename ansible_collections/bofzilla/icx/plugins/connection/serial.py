# ruff: noqa: E402

DOCUMENTATION = r"""
author: bofzilla
connection: serial
short_description: Connect to network devices via serial console
description:
  - This connection plugin talks to network devices over a local serial console.
  - It uses the same terminal and cliconf plugins as ansible.netcommon.network_cli.
extends_documentation_fragment:
  - ansible.netcommon.connection_persistent
options:
  port:
    description:
      - Serial port device path (e.g. /dev/ttyUSB0, /dev/cu.usbserial-*).
    default: inventory_hostname
    vars:
      - name: ansible_serial_port
  baud:
    description:
      - Serial port baud rate.
    default: 9600
    vars:
      - name: ansible_serial_baud
  remote_user:
    description:
      - Username for device login prompt.
    vars:
      - name: ansible_user
  password:
    description:
      - Password for device login prompt.
    vars:
      - name: ansible_password
  network_os:
    description:
      - Network OS name for loading terminal and cliconf plugins.
    vars:
      - name: ansible_network_os
  terminal_errors:
    type: str
    description:
      - This option determines how failures while setting terminal parameters are handled.
    vars:
      - name: ansible_network_terminal_errors
    default: fail
    choices: ["ignore", "warn", "fail"]
  persistent_buffer_read_timeout:
    type: float
    description:
      - Seconds to wait for trailing serial output after the prompt is matched.
    default: 0.2
    ini:
      - section: persistent_connection
        key: buffer_read_timeout
    env:
      - name: ANSIBLE_PERSISTENT_BUFFER_READ_TIMEOUT
    vars:
      - name: ansible_buffer_read_timeout
"""

import contextlib
import json
import pickle
import re
import signal
import time
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, cast

from ansible.errors import AnsibleConnectionFailure
from ansible.module_utils.common.text.converters import to_bytes, to_text
from ansible.playbook.play_context import PlayContext
from ansible.plugins.cliconf import CliconfBase
from ansible.plugins.loader import cliconf_loader, terminal_loader
from ansible.plugins.terminal import TerminalBase
from ansible_collections.ansible.netcommon.plugins.plugin_utils.connection_base import NetworkConnectionBase

if TYPE_CHECKING:
	from serial import Serial

LOGIN_RE = re.compile(rb"(?:please enter login name|user ?name|username): ?", re.I)
PASSWORD_RE = re.compile(rb"(?:local_)?password: ?", re.I)
READ_SIZE = 4096
SERIAL_POLL_TIMEOUT = 0.2
CommandText = bytes | str
CommandTextInput = CommandText | Sequence[CommandText] | None


class Connection(NetworkConnectionBase):
	transport = "bofzilla.icx.serial"
	has_pipelining = True

	def __init__(self, play_context, new_stdin, *args, **kwargs):
		super().__init__(play_context, new_stdin, *args, **kwargs)
		self._serial: Serial | None = None
		self._matched_prompt: bytes | None = None

		if not self._network_os:
			raise AnsibleConnectionFailure("Unable to determine ansible_network_os for serial connection")

		terminal = terminal_loader.get(self._network_os, self)
		if not terminal:
			raise AnsibleConnectionFailure(f"network os {self._network_os} is not supported")
		self._terminal = cast(TerminalBase, terminal)

		cliconf = cliconf_loader.get(self._network_os, self) or cliconf_loader.get("ansible.netcommon.default", self)
		if not cliconf:
			raise AnsibleConnectionFailure("Unable to load cliconf plugin")
		self.cliconf = cast(CliconfBase, cliconf)

		self._sub_plugin = {
			"type": "cliconf",
			"name": self.cliconf._load_name,
			"obj": self.cliconf,
		}

	def _connect(self):
		if self._connected:
			return self

		# Disable the persistent-connection alarm — serial login is managed
		# with our own timeout via _read_until.
		old_alarm = signal.signal(signal.SIGALRM, signal.SIG_IGN)
		remaining = signal.alarm(0)
		try:
			port = str(self.get_option("port") or self._play_context.remote_addr)
			baud = int(self.get_option("baud") or 9600)
			self.queue_message("vvvv", f"opening serial port {port} at {baud} baud")

			try:
				import serial
			except ImportError as exc:
				raise AnsibleConnectionFailure("pyserial is required for bofzilla.icx.serial") from exc

			try:
				self._serial = serial.Serial(
					port=port,
					baudrate=baud,
					bytesize=serial.EIGHTBITS,
					parity=serial.PARITY_NONE,
					stopbits=serial.STOPBITS_ONE,
					timeout=SERIAL_POLL_TIMEOUT,
				)
			except Exception as exc:
				raise AnsibleConnectionFailure(f"Failed to open serial port {port}: {exc}") from exc

			self._connected = True
			self._login()
			self._on_open_shell()
			self.queue_message("vvvv", "serial connection established successfully")
			return self
		finally:
			signal.signal(signal.SIGALRM, old_alarm)
			if remaining:
				signal.alarm(remaining)

	def _login(self):
		username = self._play_context.remote_user
		password = self._play_context.password
		timeout = self._get_option("persistent_connect_timeout", 30)

		self._write_line(b"")
		state, data = self._read_until({"login": LOGIN_RE, "password": PASSWORD_RE}, timeout, allow_prompt=True)
		if state == "prompt":
			return

		if state == "login":
			if not username:
				raise AnsibleConnectionFailure("Serial login prompt received but no ansible_user is configured")
			self._write_line(username)
			state, data = self._read_until({"password": PASSWORD_RE}, timeout)

		if state != "password":
			raise AnsibleConnectionFailure(f"Unexpected serial login state {state!r}: {to_text(data, errors='surrogate_then_replace')}")
		if password is None:
			raise AnsibleConnectionFailure("Serial password prompt received but no ansible_password is configured")

		self._write_line(password)
		state, data = self._read_until({}, timeout, allow_prompt=True)
		if state != "prompt":
			raise AnsibleConnectionFailure(f"Device prompt not found after serial login: {to_text(data, errors='surrogate_then_replace')}")

	def close(self):
		if self._serial and self._serial.is_open:
			with contextlib.suppress(Exception):
				self._terminal.on_close_shell()
			with contextlib.suppress(Exception):
				self._logout()
			self._serial.close()
			self._serial = None
		super().close()

	def _logout(self):
		assert self._serial is not None
		self._serial.write(b"\x03\rlogout\r")
		self._serial.flush()

	def exec_command(self, cmd: CommandText, in_data=None, sudoable=True):
		if not self._serial or not self._serial.is_open:
			return super().exec_command(cmd, in_data, sudoable)
		try:
			payload = json.loads(to_text(cmd, errors="surrogate_or_strict"))
			kwargs = {"command": payload["command"]}
			for key in ("prompt", "answer", "sendonly", "newline", "prompt_retry_check", "check_all"):
				if key in payload and payload[key] is not None:
					kwargs[key] = payload[key]
			return self.send(**kwargs)
		except KeyError, TypeError, ValueError:
			return self.send(command=cmd)

	def send(
		self,
		command: CommandText,
		prompt: CommandTextInput = None,
		answer: CommandTextInput = None,
		newline=True,
		sendonly=False,
		prompt_retry_check=False,
		check_all=False,
		strip_prompt=True,
		timeout=None,
	):
		if not self._connected:
			self._connect()

		self._write_line(command)
		if sendonly:
			return None
		return to_text(
			self.receive(
				command=command,
				prompts=prompt,
				answer=answer,
				newline=newline,
				prompt_retry_check=prompt_retry_check,
				check_all=check_all,
				strip_prompt=strip_prompt,
				timeout=timeout,
			),
			errors="surrogate_then_replace",
		)

	def receive(
		self,
		command: CommandText | None = None,
		prompts: CommandTextInput = None,
		answer: CommandTextInput = None,
		newline=True,
		prompt_retry_check=False,
		check_all=False,
		strip_prompt=True,
		timeout=None,
	):
		assert self._serial is not None

		self._matched_prompt = None
		response = bytearray()
		prompt_list = self._listify(prompts)
		answer_list = self._listify(answer)
		prompt_handled = not prompt_list
		error_response = None
		deadline = time.monotonic() + (timeout or self._get_option("persistent_command_timeout", 30))

		if check_all and len(prompt_list) != len(answer_list):
			raise AnsibleConnectionFailure(f"Number of prompts ({len(prompt_list)}) is not same as that of answers ({len(answer_list)})")

		while time.monotonic() < deadline:
			chunk = self._serial.read(READ_SIZE)
			if not chunk:
				continue

			response.extend(chunk)
			window = bytes(response)

			if prompt_list and not prompt_handled:
				prompt_handled = self._handle_prompt(window, prompt_list, answer_list, newline, check_all)
			elif prompt_retry_check and prompt_handled and self._any_prompt_matches(window, prompt_list):
				raise AnsibleConnectionFailure("Prompt answer was rejected by the device")

			if self._find_error(window):
				error_response = window

			if self._find_prompt(window):
				self._drain_after_prompt(response)
				if error_response:
					raise AnsibleConnectionFailure(to_text(error_response, errors="surrogate_then_replace"))
				return self._sanitize(bytes(response), command, strip_prompt)

		raise AnsibleConnectionFailure(f"timeout waiting for response to command: {to_text(command, errors='surrogate_then_replace')}")

	# --- Private helpers ---

	def _read_until(self, patterns: Mapping[str, re.Pattern[bytes]], timeout: int, allow_prompt=False):
		assert self._serial is not None

		response = bytearray()
		deadline = time.monotonic() + timeout
		while time.monotonic() < deadline:
			chunk = self._serial.read(READ_SIZE)
			if not chunk:
				continue

			response.extend(chunk)
			window = bytes(response)
			if allow_prompt and self._find_prompt(window):
				return "prompt", window
			for name, pattern in patterns.items():
				if pattern.search(window):
					return name, window

		return None, bytes(response)

	def _write_line(self, value: CommandText):
		assert self._serial is not None
		self._serial.write(to_bytes(value, errors="surrogate_or_strict") + b"\r")
		self._serial.flush()

	def _handle_prompt(self, window: bytes, prompts: list[CommandText], answers: list[CommandText], newline: bool, check_all: bool) -> bool:
		assert self._serial is not None

		if not prompts:
			return True

		prompt_index = 0 if check_all else next((index for index, prompt in enumerate(prompts) if self._prompt_matches(window, prompt)), None)
		if prompt_index is None:
			return False

		if len(answers) > prompt_index:
			self._serial.write(to_bytes(answers[prompt_index], errors="surrogate_or_strict") + (b"\r" if newline else b""))
			self._serial.flush()

		prompts.pop(prompt_index)
		if len(answers) > prompt_index:
			answers.pop(prompt_index)
		return not prompts

	def _listify(self, value: CommandTextInput) -> list[CommandText]:
		if value is None:
			return []
		if isinstance(value, (bytes, str)):
			return [value]
		return list(value)

	def _any_prompt_matches(self, response: bytes, prompts: Sequence[CommandText]) -> bool:
		return any(self._prompt_matches(response, p) for p in prompts)

	def _prompt_matches(self, response: bytes, prompt: CommandText) -> bool:
		return re.compile(to_bytes(prompt), re.I).search(response) is not None

	def _drain_after_prompt(self, response: bytearray):
		assert self._serial is not None
		time.sleep(self._get_option("persistent_buffer_read_timeout", 0.2))
		while chunk := self._serial.read(READ_SIZE):
			response.extend(chunk)

	def _get_option(self, name: str, default):
		try:
			value = self.get_option(name)
		except KeyError:
			return default
		return default if value is None else value

	def _sanitize(self, response: bytes, command: CommandText | None = None, strip_prompt: bool = True):
		for regex in self._terminal.ansi_re:
			response = regex.sub(b"", response)

		cmd_bytes = to_bytes(command, errors="surrogate_or_strict").strip() if command is not None else None
		prompt_bytes = self._matched_prompt.strip() if self._matched_prompt else None
		cleaned = []

		for line in response.splitlines():
			stripped = line.strip()
			if cmd_bytes and stripped == cmd_bytes:
				continue
			if prompt_bytes and strip_prompt and prompt_bytes in stripped:
				continue
			cleaned.append(line)

		return b"\n".join(cleaned).strip()

	def _find_prompt(self, response: bytes):
		for regex in self._terminal.terminal_stdout_re:
			if match := regex.search(response):
				self._matched_prompt = match.group().strip()
				return True
		return False

	def _find_error(self, response: bytes):
		return any(regex.search(line) for line in response.splitlines() for regex in self._terminal.terminal_stderr_re)

	def _on_open_shell(self):
		try:
			self._terminal.on_open_shell()
		except AnsibleConnectionFailure:
			match self.get_option("terminal_errors"):
				case "ignore":
					return
				case "warn":
					self.queue_message("warning", "on_open_shell: failed to set terminal parameters")
				case _:
					raise

	def update_play_context(self, pc_data):
		pc_data = pickle.loads(to_bytes(pc_data), encoding="bytes")
		play_context = PlayContext()
		play_context.deserialize(pc_data)
		self._play_context = play_context

	def get_prompt(self):
		if not self._connected:
			self._connect()
		return self._matched_prompt
