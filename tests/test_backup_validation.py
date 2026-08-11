import time
from types import SimpleNamespace
from unittest.mock import patch

from app.core.policies import EnvironmentType
from app.services.backup_validation import MOUNT_SCRIPT, run_backup_validation
from app.services.ssh import CommandResult


class FakeExecutor:
    def __init__(self, *, primary_mounted=True, redundancy_mounted=True):
        self.primary_mounted = primary_mounted
        self.redundancy_mounted = redundancy_mounted
        self.commands = []
        self.connected = False
        self.closed = False

    def connect(self):
        self.connected = True

    def close(self):
        self.closed = True

    def result(self, command, code=0, stdout="", stderr=""):
        return CommandResult(command, code, stdout, stderr)

    def run(self, command, environment, approved=False, timeout=60):
        self.commands.append(command)
        assert environment == EnvironmentType.PRODUCTION
        assert approved is False

        if command == "findmnt -rn -o SOURCE,TARGET,FSTYPE":
            rows = ["/dev/mapper/root / xfs"]
            if self.primary_mounted:
                rows.append("/dev/mapper/u01 /u01 xfs")
            if self.redundancy_mounted:
                rows.append("172.16.10.20:/BKP /mnt/backup_check nfs4")
            return self.result(command, stdout="\n".join(rows) + "\n")

        if command == "findmnt -s -rn -o SOURCE,TARGET,FSTYPE":
            return self.result(
                command,
                stdout=(
                    "/dev/mapper/root / xfs\n"
                    "/dev/mapper/u01 /u01 xfs\n"
                    "172.16.10.20:/BKP /mnt/backup_check nfs4\n"
                ),
            )

        if command.startswith("findmnt -rn -T "):
            if self.primary_mounted:
                return self.result(command, stdout="/dev/mapper/u01 /u01 xfs\n")
            return self.result(command, stdout="/dev/mapper/root / xfs\n")

        if command.startswith("stat "):
            return self.result(command, stdout="xfs|1000|4096\n")

        if command.startswith("df "):
            return self.result(
                command,
                stdout=(
                    "Filesystem 1024-blocks Used Available Capacity Mounted on\n"
                    "/dev/mapper/u01 100000 40000 60000 40% /u01\n"
                ),
            )

        if "-newermt" in command:
            return self.result(command, stdout="3\n")

        if command.startswith("find /mnt/backup_check "):
            changed = time.time() - 1800
            return self.result(command, stdout=f"{changed}|2048|/mnt/backup_check/datapump/copy.bkp\n")

        if command.startswith("find /u01/backup "):
            changed = time.time() - 3600
            return self.result(command, stdout=f"{changed}|4096|/u01/backup/backup.bkp\n")

        raise AssertionError(f"comando não esperado: {command}")


def target():
    return SimpleNamespace(
        reference="cliente01",
        host="192.0.2.10",
        port=22,
        environment=EnvironmentType.PRODUCTION,
        inventory=None,
    )


def execute(fake, **overrides):
    values = {
        "backup_path": "/u01/backup",
        "environment": EnvironmentType.PRODUCTION,
        "min_free_percent": 20,
        "max_backup_age_hours": 30,
        "retention_days": 7,
        "min_restore_points": 2,
        "settings": SimpleNamespace(),
    }
    values.update(overrides)
    with patch("app.services.backup_validation.resolve_target", return_value=target()), patch(
        "app.services.backup_validation.build_executor", return_value=fake
    ):
        return run_backup_validation("cliente01", **values)


def test_discovers_internal_mount_and_redundancy_without_manual_mount_fields():
    fake = FakeExecutor(primary_mounted=True, redundancy_mounted=True)
    result = execute(fake)

    assert result["status"] == "healthy"
    assert result["mount_point"] == "/u01"
    assert result["redundancy_path"] == "/mnt/backup_check"
    assert result["checks"]["mount"]["status"] == "healthy"
    assert result["checks"]["space"]["free_percent"] == 60
    assert result["checks"]["retention"]["recent_files"] == 3
    assert result["checks"]["last_backup"]["status"] == "healthy"
    assert result["checks"]["redundancy"]["status"] == "healthy"
    assert result["discovery"]["method"].startswith("findmnt -T")
    assert result["action_available"] is None
    assert result["executed_actions"] == []
    assert fake.connected and fake.closed
    assert all(MOUNT_SCRIPT not in command for command in fake.commands)


def test_configured_primary_mount_missing_blocks_underlay_backup_scan():
    fake = FakeExecutor(primary_mounted=False, redundancy_mounted=True)
    result = execute(fake)

    assert result["status"] == "critical"
    assert result["mount_point"] == "/u01"
    assert result["checks"]["mount"]["status"] == "critical"
    assert "cairia no filesystem /" in result["checks"]["mount"]["detail"]
    assert result["checks"]["last_backup"]["status"] == "inconclusive"
    assert result["checks"]["retention"]["status"] == "inconclusive"
    assert result["action_available"]["command"] == MOUNT_SCRIPT
    assert result["action_available"]["enabled"] is False
    assert "/u01" in result["action_available"]["detail"]
    assert not any(command.startswith("df /u01") for command in fake.commands)
    assert not any(command.startswith("find /u01/backup ") for command in fake.commands)
    assert all(MOUNT_SCRIPT not in command for command in fake.commands)


def test_configured_redundancy_is_detected_when_unmounted():
    fake = FakeExecutor(primary_mounted=True, redundancy_mounted=False)
    result = execute(fake)

    assert result["mount_point"] == "/u01"
    assert result["redundancy_path"] == "/mnt/backup_check"
    assert result["checks"]["redundancy"]["status"] == "attention"
    assert "está desmontada" in result["checks"]["redundancy"]["detail"]
    assert result["action_available"]["command"] == MOUNT_SCRIPT
    assert "/mnt/backup_check" in result["action_available"]["detail"]


def test_legacy_manual_mount_values_do_not_override_server_discovery():
    fake = FakeExecutor(primary_mounted=True, redundancy_mounted=True)
    result = execute(
        fake,
        mount_point="/mnt/errado",
        redundancy_path="/mnt/errado/redundancia",
    )

    assert result["mount_point"] == "/u01"
    assert result["redundancy_path"] == "/mnt/backup_check"
