import traceback
from datetime import timedelta

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.connection import Connection

from ansible_collections.bofzilla.icx.plugins.module_utils.cli_client import ICX_ARGUMENT_SPEC, CliClient
from ansible_collections.bofzilla.icx.plugins.module_utils.commands.clock import (
	SetClock,
	SetClockSummerTime,
	SetClockTimezone,
)
from ansible_collections.bofzilla.icx.plugins.module_utils.commands.show.clock import ShowClock
from ansible_collections.bofzilla.icx.plugins.module_utils.commands.system import WriteMemory

REQUIRED_TOGETHER = [["time", "timezone"]]
TIME_TOLERANCE = timedelta(seconds=1)

DOCUMENTATION = r"""
module: clock
short_description: Set the system clock on a Brocade ICX switch
description:
  - Sets the system clock, timezone, and summer-time on a Brocade ICX switch.
  - C(time) uses Privileged EXEC mode (C(clock set)).
  - C(timezone) and C(summer_time) use Global Configuration mode
    (C(clock timezone), C(clock summer-time)).
options:
  time:
    description:
      - The date and time to set, as an ISO-8601 string (e.g.
        C(2026-06-03T14:30:00)).
      - Timezone information, if present, is stripped — only the wall-clock
        value is sent to the device.
      - Must be provided together with C(timezone).
      - When omitted, defaults to the current local time on the Ansible
        controller.
    type: str
    required: false
  timezone:
    description:
      - GMT offset timezone to configure on the device (e.g. C(gmt+05:30),
        C(gmt-08), C(gmt+00)).
      - Must be lowercase, matching what the switch expects.
      - Must be provided together with C(time).
      - When omitted, the timezone is auto-detected from the Ansible controller's
        local timezone when supported by FastIron.
    type: str
    required: false
  summer_time:
    description:
      - Whether to enable summer time (daylight saving) on the device.
      - When omitted, the summer-time setting is left unchanged.
    type: bool
    required: false
  save:
    description:
      - Whether to save the running-config to startup-config after applying
        configuration-mode commands (C(timezone), C(summer_time)).
      - Has no effect when only C(time) is set (C(clock set) writes directly
        to the hardware RTC and is not part of the config).
    type: bool
    default: false
    required: false
  enable_password:
    description:
      - Password used to enter privileged EXEC mode (C(enable)).
    type: str
    required: false

attributes:
  check_mode:
    support: full
    details: Compares the current clock and reports what would be set without changing the device.
  diff_mode:
    support: partial
    details: Reports current and desired clock/timezone. The current summer-time state is not read and is reported as unknown when summer_time is provided.
  idempotent:
    support: partial
    details:
      - Clock and timezone are compared before applying changes.
      - Times within one second are considered equal.
      - Summer-time is applied when provided because current summer-time state is not read.

author:
  - bofzilla
"""

EXAMPLES = r"""
- name: Set clock to current local time and timezone
  bofzilla.icx.clock:
    enable_password: "{{ vault_icx_enable_password }}"

- name: Set clock to a specific time and timezone
  bofzilla.icx.clock:
    time: "2026-06-03T14:30:00"
    timezone: gmt+00
    enable_password: "{{ vault_icx_enable_password }}"

- name: Set clock to India timezone and save config
  bofzilla.icx.clock:
    time: "2026-06-03T14:30:00"
    timezone: gmt+05:30
    save: true
    enable_password: "{{ vault_icx_enable_password }}"

- name: Enable summer time
  bofzilla.icx.clock:
    summer_time: true
    save: true
    enable_password: "{{ vault_icx_enable_password }}"
"""

RETURN = r"""
clock:
  description: The time that was (or would be) set, as ISO-8601.
  type: str
  returned: success
command:
  description: The CLI command(s) sent to the device.
  type: list
  elements: str
  returned: success
timezone:
  description: The timezone that was configured, if any.
  type: str
  returned: when timezone is specified
summer_time:
  description: Whether summer time was enabled or disabled, if specified.
  type: bool
  returned: when summer_time is specified
saved:
  description: Whether the configuration was saved to startup-config.
  type: bool
  returned: when save is true and config commands were run
"""


def main():
	module = AnsibleModule(
		argument_spec={
			**ICX_ARGUMENT_SPEC,
			"time": {"type": "str"},
			"timezone": {"type": "str"},
			"summer_time": {"type": "bool"},
			"save": {"type": "bool", "default": False},
		},
		required_together=REQUIRED_TOGETHER,
		supports_check_mode=True,
	)
	try:
		time_param = module.params.get("time")
		timezone_param = module.params.get("timezone")
		summer_time_param = module.params.get("summer_time")
		save_param = module.params.get("save")

		commands: list[str] = []

		tz_cmd = SetClockTimezone(timezone=timezone_param) if timezone_param is not None else SetClockTimezone()
		summer_cmd = SetClockSummerTime(enabled=summer_time_param) if summer_time_param is not None else None
		time_cmd = SetClock(time=time_param) if time_param is not None else SetClock()

		client = CliClient(Connection(module._socket_path), enable_password=module.params.get("enable_password"))
		current_clock = client.run(ShowClock())

		timezone_offset = tz_cmd.timezone.removeprefix("gmt")
		sign = -1 if timezone_offset.startswith("-") else 1
		hours_text, _, minutes_text = timezone_offset[1:].partition(":")
		desired_offset = sign * timedelta(hours=int(hours_text), minutes=int(minutes_text or 0))

		current_wall_time = current_clock.replace(tzinfo=None)
		current_offset = current_clock.utcoffset()
		changed = abs(current_wall_time - time_cmd.wall_time) > TIME_TOLERANCE or current_offset != desired_offset or summer_cmd is not None
		result: dict = {"changed": changed}
		if result["changed"] and getattr(module, "_diff", False):
			if current_offset is None:
				current_timezone = "unknown"
			else:
				total_minutes = int(current_offset.total_seconds() // 60)
				hours, minutes = divmod(abs(total_minutes), 60)
				current_timezone = f"gmt{'+' if total_minutes >= 0 else '-'}{hours:02d}" + (f":{minutes:02d}" if minutes else "")
			before = [
				f"clock: {current_wall_time.isoformat()}",
				f"timezone: {current_timezone}",
			]
			after = [
				f"clock: {time_cmd.wall_time.isoformat()}",
				f"timezone: {tz_cmd.timezone}",
			]
			if summer_cmd:
				before.append("summer_time: unknown")
				after.append(f"summer_time: {'true' if summer_cmd.enabled else 'false'}")
			result["diff"] = {
				"before": "\n".join(before),
				"after": "\n".join(after),
			}

		if result["changed"] and not module.check_mode:
			client.run(tz_cmd)
			if summer_cmd:
				client.run(summer_cmd)
			client.run(time_cmd)
			if save_param:
				client.run(WriteMemory())

		if result["changed"]:
			commands.append(tz_cmd.command())
			if summer_cmd:
				commands.append(summer_cmd.command())
			commands.append(time_cmd.command())
			if save_param:
				commands.append("write memory")
				result["saved"] = True
		result["timezone"] = tz_cmd.timezone
		if summer_cmd:
			result["summer_time"] = summer_cmd.enabled
		result["clock"] = time_cmd.wall_time.isoformat()
		result["command"] = commands

		module.exit_json(**result)
	except Exception as err:
		module.fail_json(msg=f"{type(err).__name__}: {err}", exception=traceback.format_exc())


if __name__ == "__main__":
	main()
