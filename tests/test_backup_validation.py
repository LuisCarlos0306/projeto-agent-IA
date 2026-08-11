import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.core.policies import EnvironmentType
from app.services.backup_validation import MOUNT_SCRIPT, run_backup_validation
from app.services.ssh import CommandResult


class FakeExecutor:
    def __init__(self, *, mounted=True):
        self.mounted = mounted
        self.commands = []
        self.connected = False
        self.closed = False

    def connect(self):
        self.connected = True

    def close(self):
        self.closed = True

    def run(self, command, environment, approved=False, timeout=60):
        self.commands.append(command)
        assert environment == EnvironmentType.PRODUCTION
        assert approved is False
        if command.startswith("findmnt "):
            if self.mounted:
                return CommandResult(command, 0, "server:/backup /mnt/backup_check nfs4 rw,relatime\n", "")
            return CommandResult(command, 1, "", "")
        if command.startswith("stat "):
            return CommandResult(command, 0, "nfs|1000|4096\n", "")
        if command.startswith("df "):
            return CommandResult(
                command,
                0,
                "Filesystem 1024-blocks Used Available Capacity Mounted on\n"
                "server:/backup 100000 40000 60000 40% /mnt/backup_check\n",
                "",
            )
        if "-newermt" in command:
            return CommandResult(command, 0, "3\n", "")
        if command.startswith("find ") and "/mnt/redundancy" in command:
            changed = time.time() - 1800
            return CommandResult(command, 0, f"{changed}|2048|/mnt/redundancy/copy.bkp\n", "")
        if command.startswith("find "):
            changed = time.time() - 3600
            return CommandResult(command, 0, f"{changed}|4096|/mnt/backup_check/app/backup.bkp\n", "")
        raise AssertionError(f"comando não esperado: {command}")


def target():
    return SimpleNamespace(
        reference="cliente01",
        host="192.0.2.10",
        port=22,
        environment=EnvironmentType.PRODUCTION,
        inventory=None,
    )


def execute(fake):
    with patch("app.services.backup_validation.resolve_target", return_value=target()), patch(
        "app.services.backup_validation.build_executor", return_value=fake
    ):
        return run_backup_validation(
            "cliente01",
            mount_point="/mnt/backup_check",
            backup_path="/mnt/backup_check/app",
            redundancy_path="/mnt/redundancy",
            environment=EnvironmentType.PRODUCTION,
            min_free_percent=20,
            max_backup_age_hours=30,
            retention_days=7,
            min_restore_points=2,
            settings=SimpleNamespace(),
        )


def test_backup_validation_returns_structured_healthy_result_without_correction():
    fake = FakeExecutor(mounted=True)
    result = execute(fake)

    assert result["status"] == "healthy"
    assert result["checks"]["mount"]["status"] == "healthy"
    assert result["checks"]["space"]["free_percent"] == 60
    assert result["checks"]["retention"]["recent_files"] == 3
    assert result["checks"]["last_backup"]["status"] == "healthy"
    assert result["checks"]["redundancy"]["status"] == "healthy"
    assert result["action_available"] is None
    assert result["executed_actions"] == []
    assert fake.connected and fake.closed
    assert all(MOUNT_SCRIPT not in command for command in fake.commands)


def test_unmounted_storage_stops_backup_scans_and_only_suggests_mount():
    fake = FakeExecutor(mounted=False)
    result = execute(fake)

    assert result["status"] == "critical"
    assert result["checks"]["mount"]["status"] == "critical"
    assert result["checks"]["last_backup"]["status"] == "inconclusive"
    assert result["checks"]["retention"]["status"] == "inconclusive"
    assert result["action_available"]["command"] == MOUNT_SCRIPT
    assert result["action_available"]["enabled"] is False
    assert not any(command.startswith("df ") for command in fake.commands)
    assert not any(command.startswith("find ") for command in fake.commands)
    assert all(MOUNT_SCRIPT not in command for command in fake.commands)


def test_backup_path_must_belong_to_mount_point():
    with pytest.raises(ValueError, match="dentro do ponto de montagem"):
        run_backup_validation(
            "192.0.2.10",
            mount_point="/mnt/backup_check",
            backup_path="/tmp/backup",
            settings=SimpleNamespace(),
        )
