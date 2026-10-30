# Ansible collection: vic1707.icx

An unofficial collection for Brocade ICX switches over SSH or a serial console.

## Installation

Requires Python 3.12+ and ansible-core 2.16+ on the controller.

```sh
python -m pip install 'pydantic>=2,<3' 'paramiko>=4,<5' pyserial
ansible-galaxy collection install vic1707.icx
```

Galaxy installs `ansible.netcommon` automatically; install Python dependencies
separately. Paramiko 4 supports the legacy SSH algorithms required by older ICX firmware.

## Usage

Set `ansible_network_os: vic1707.icx.icx` and
`ansible_connection: ansible.netcommon.network_cli` for SSH, or
`ansible_connection: vic1707.icx.serial` for a serial console.
See the repository's [example playbooks](https://github.com/vic1707/ansible-collection-brocade-icx/tree/main/example_playbooks).

```sh
ansible-doc --list vic1707.icx
ansible-doc vic1707.icx.facts
```
