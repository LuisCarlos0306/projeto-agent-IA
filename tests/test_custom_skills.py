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
    update_custom_skill,
    validate_custom_command,
    validate_script_path,
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
        environment=EnvironmentType.MONITORING,
        inventory=None,
    )


def test_custom_skill_registry_create_edit_list_get_delete(tmp_path: Path):
    path = tmp_path / "custom-skills.json"
    skill = create_custom_skill(
        "Validar Filesystem",
        ["df -h", "findmnt"],
        description="Validação simples",
        mode="diagnostic",
        scripts=["/db/backup/scripts/mount.sh"],
        path=path,
    )

    assert skill["name"] == "Validar Filesystem"
    assert skill["mode"] == "diagnostic"
    assert skill["commands"] == ["df -h", "findmnt"]
    assert skill["scripts"] == ["/db/backup/scripts/mount.sh"]

    edited = update_custom_skill(
        skill["id"],
        name="Filesystem e Backup",
        commands=["df -h"],
        scripts=["/db/backup/scripts/mount.sh"],
        description="Nome alterado pelo lápis",
        mode="correction",
        path=path,
    )
    assert edited["name"] == "Filesystem e Backup"
    assert edited["mode"] == "correction"
    assert get_custom_skill(skill["id"], path)["description"] == "Nome alterado pelo lápis"
    assert list_custom_skills(path)[0]["id"] == skill["id"]
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert delete_custom_skill(skill["id"], path=path) is True
    assert list_custom_skills(path) == []


def test_custom_skill_rejects_mutating_or_shell_commands_in_read_only_mode():
    for command in (
        "rm -rf /tmp/teste",
        "mount -a",
        "systemctl restart sshd",
        "df -h | grep backup",
        "cat /opt/agent-ia/app/.env",
        "hostnamectl set-hostname teste",
        "timedatectl set-timezone UTC",
        "ip link set eth0 down",
        "journalctl --vacuum-time=1d",
        "dmesg -C",
    ):
        with pytest.raises(ValueError):
            validate_custom_command(command)


def test_diagnostic_and_correction_can_register_commands_outside_read_only_catalog(tmp_path: Path):
    assert validate_custom_command("mount /mnt/backup_check", "diagnostic") == "mount /mnt/backup_check"
    assert validate_custom_command("systemctl restart sshd", "correction") == "systemctl restart sshd"
    assert validate_custom_command("df -h | grep backup", "correction") == "df -h | grep backup"

    path = tmp_path / "custom-skills.json"
    skill = create_custom_skill(
        "Montagem controlada",
        ["mount /mnt/backup_check", "systemctl restart autofs"],
        mode="correction",
        path=path,
    )
    assert skill["mode"] == "correction"
    assert skill["commands"] == ["mount /mnt/backup_check", "systemctl restart autofs"]


def test_custom_skill_accepts_read_only_diagnostics():
    assert validate_custom_command("df -h") == "df -h"
    assert validate_custom_command("findmnt") == "findmnt"
    assert validate_custom_command("systemctl status sshd") == "systemctl status sshd"
    assert validate_custom_command("ss -lntp") == "ss -lntp"
    assert validate_custom_command("ip addr") == "ip addr"
    assert validate_custom_command("hostname -I") == "hostname -I"


def test_custom_script_path_is_restricted_to_allowed_roots(monkeypatch):
    assert validate_script_path("/db/backup/scripts/mount.sh") == "/db/backup/scripts/mount.sh"
    with pytest.raises(ValueError):
        validate_script_path("/tmp/teste.sh")
    with pytest.raises(ValueError):
        validate_script_path("/db/backup/scripts/mount.sh --force")

    monkeypatch.setenv("AGENT_CUSTOM_SKILL_SCRIPT_ROOTS", "/opt/custom/scripts")
    assert validate_script_path("/opt/custom/scripts/check.sh") == "/opt/custom/scripts/check.sh"
    with pytest.raises(ValueError):
        validate_script_path("/db/backup/scripts/mount.sh")


def test_read_only_skill_rejects_scripts(tmp_path: Path):
    with pytest.raises(ValueError):
        create_custom_skill(
            "Leitura simples",
            ["df -h"],
            mode="read_only",
            scripts=["/db/backup/scripts/mount.sh"],
            path=tmp_path / "custom-skills.json",
        )


def test_custom_skill_runner_executes_only_safe_commands_and_keeps_corrections_pending():
    fake = FakeExecutor()
    skill = {
        "id": "abc123",
        "name": "Validar Filesystem",
        "description": "",
        "commands": ["df -h", "mount /mnt/backup_check"],
        "scripts": ["/db/backup/scripts/mount.sh"],
        "mode": "correction",
    }
    settings = SimpleNamespace(ssh_command_timeout=60)

    with patch("app.services.custom_skill_runner.get_custom_skill", return_value=skill), patch(
        "app.services.custom_skill_runner.resolve_target", return_value=_target()
    ), patch("app.services.custom_skill_runner.build_executor", return_value=fake):
        result = run_custom_skill("abc123", "172.27.232.212", settings=settings)

    assert result["status"] == "attention"
    assert result["mode"] == "correction"
    assert result["target"] == "172.27.232.212"
    assert [item[0] for item in fake.commands] == ["df -h"]
    assert all(item[2] is False for item in fake.commands)
    assert fake.connected and fake.closed
    assert result["approval_required"] is True
    assert result["pending_commands"][0]["command"] == "mount /mnt/backup_check"
    assert result["pending_commands"][0]["status"] == "pending_approval"
    assert result["scripts"][0]["path"] == "/db/backup/scripts/mount.sh"
    assert result["scripts"][0]["status"] == "pending_approval"
    assert result["executed_actions"] == []


def test_custom_skill_registry_file_contains_no_execution_target(tmp_path: Path):
    path = tmp_path / "custom-skills.json"
    create_custom_skill("Rede", ["ip addr", "ss -lntp"], mode="diagnostic", path=path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    rendered = json.dumps(payload)
    assert payload["schema_version"] == 2
    assert "target" not in rendered
    assert "password" not in rendered
