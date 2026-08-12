from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.core.policies import EnvironmentType
from app.services.custom_skill_registry import (
    create_custom_skill,
    delete_custom_skill,
    get_custom_skill,
    list_custom_skills,
    validate_custom_command,
)
from app.services.custom_skill_runner import run_custom_skill
from app.services.ssh import CommandResult


class FakeExecutor:
    def __init__(self):
        self.commands = []
        self.connected = False
        self.closed = False

    def connect(self):
        self.connected = True

    def close(self):
        self.closed = True

    def run(self, command, environment, approved=False, timeout=60):
        self.commands.append((command, environment, approved))
        if command == "df -h":
            return CommandResult(command, 0, "Filesystem Size Used Avail Use% Mounted on\n/dev/sda 100G 30G 70G 30% /\n", "")
        if command == "findmnt":
            return CommandResult(command, 0, "/dev/sda / ext4 rw\n", "")
        return CommandResult(command, 1, "", "falha")


def _target():
    return SimpleNamespace(
        reference="172.27.232.212",
        host="172.27.232.212",
        port=22,
        environment=EnvironmentType.UNKNOWN,
        inventory=None,
    )


def test_custom_skill_registry_create_list_get_delete(tmp_path: Path):
    path = tmp_path / "custom-skills.json"
    skill = create_custom_skill(
        "Validar Filesystem",
        ["df -h", "findmnt"],
        description="Validação simples",
        path=path,
    )

    assert skill["name"] == "Validar Filesystem"
    assert skill["commands"] == ["df -h", "findmnt"]
    assert list_custom_skills(path)[0]["id"] == skill["id"]
    assert get_custom_skill(skill["id"], path)["description"] == "Validação simples"
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert delete_custom_skill(skill["id"], path=path) is True
    assert list_custom_skills(path) == []


def test_custom_skill_rejects_mutating_or_shell_commands():
    for command in (
        "rm -rf /tmp/teste",
        "mount -a",
        "systemctl restart sshd",
        "df -h | grep backup",
        "cat /opt/agent-ia/app/.env",
    ):
        with pytest.raises(ValueError):
            validate_custom_command(command)


def test_custom_skill_accepts_read_only_diagnostics():
    assert validate_custom_command("df -h") == "df -h"
    assert validate_custom_command("findmnt") == "findmnt"
    assert validate_custom_command("systemctl status sshd") == "systemctl status sshd"
    assert validate_custom_command("ss -lntp") == "ss -lntp"


def test_custom_skill_runner_executes_fixed_commands_with_only_target_input():
    fake = FakeExecutor()
    skill = {
        "id": "abc123",
        "name": "Validar Filesystem",
        "description": "",
        "commands": ["df -h", "findmnt"],
        "mode": "read_only",
    }
    settings = SimpleNamespace(ssh_command_timeout=60)

    with patch("app.services.custom_skill_runner.get_custom_skill", return_value=skill), patch(
        "app.services.custom_skill_runner.resolve_target", return_value=_target()
    ), patch("app.services.custom_skill_runner.build_executor", return_value=fake):
        result = run_custom_skill("abc123", "172.27.232.212", settings=settings)

    assert result["status"] == "healthy"
    assert result["target"] == "172.27.232.212"
    assert [item[0] for item in fake.commands] == ["df -h", "findmnt"]
    assert all(item[2] is False for item in fake.commands)
    assert fake.connected and fake.closed
    assert result["executed_actions"] == []


def test_custom_skill_registry_file_contains_no_execution_target(tmp_path: Path):
    path = tmp_path / "custom-skills.json"
    create_custom_skill("Rede", ["ip addr", "ss -lntp"], path=path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    rendered = json.dumps(payload)
    assert "target" not in rendered
    assert "password" not in rendered
