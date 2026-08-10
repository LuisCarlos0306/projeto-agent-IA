import pytest

from app.core.policies import EnvironmentType
from app.services.correction_policy import MOUNT_RECOVERY_SCRIPT, validate_correction
from app.services.mount_ops import MountOperationError, probe_mount, validate_mount_path
from app.services.ssh import CommandResult, SSHExecutor


class FakeExecutor:
    def __init__(self, stdout: str, exit_code: int = 0, stderr: str = ""):
        self.stdout = stdout
        self.exit_code = exit_code
        self.stderr = stderr
        self.commands = []

    def run(self, command, environment, approved=False, timeout=60):
        self.commands.append((command, environment, approved, timeout))
        return CommandResult(command, self.exit_code, self.stdout, self.stderr)


def test_mount_path_accepts_authorized_backup_prefix():
    assert validate_mount_path("/mnt/backup_nas_rman") == "/mnt/backup_nas_rman"


def test_mount_path_rejects_shell_injection():
    with pytest.raises(MountOperationError):
        validate_mount_path("/mnt/backup;reboot")


def test_mount_path_rejects_root_filesystem():
    with pytest.raises(MountOperationError):
        validate_mount_path("/")


def test_probe_reports_mounted_nfs_and_safe_script():
    executor = FakeExecutor(
        "\n".join(
            [
                "MOUNTED=1",
                "FINDMNT=/mnt/backup_nas_rman 172.16.250.10:/BKP_FISICO nfs4 rw,relatime",
                "DF=172.16.250.10:/BKP_FISICO 8.0T 4.0T 4.0T 50% /mnt/backup_nas_rman",
                "SCRIPT_PRESENT=1",
                "SCRIPT_META=root|755",
            ]
        )
    )

    result = probe_mount(executor, EnvironmentType.PRODUCTION, "/mnt/backup_nas_rman")

    assert result.mounted is True
    assert result.source == "172.16.250.10:/BKP_FISICO"
    assert result.fstype == "nfs4"
    assert result.script_safe is True


def test_probe_blocks_group_writable_mount_script():
    executor = FakeExecutor(
        "\n".join(
            [
                "MOUNTED=0",
                "SCRIPT_PRESENT=1",
                "SCRIPT_META=root|775",
            ]
        )
    )

    result = probe_mount(executor, EnvironmentType.PRODUCTION, "/mnt/backup_nas_rman")

    assert result.mounted is False
    assert result.script_safe is False


def test_correction_policy_allows_only_exact_mount_script():
    allowed = validate_correction(MOUNT_RECOVERY_SCRIPT)
    altered = validate_correction(MOUNT_RECOVERY_SCRIPT + " --force")

    assert allowed.allowed is True
    assert allowed.action_type == "mount_recovery"
    assert altered.allowed is False


def test_ssh_policy_accepts_exact_mount_script_after_explicit_approval():
    executor = SSHExecutor("127.0.0.1", 22, "tester")

    executor._validate(MOUNT_RECOVERY_SCRIPT, EnvironmentType.PRODUCTION, approved=True)


def test_ssh_policy_rejects_altered_mount_script_after_approval():
    executor = SSHExecutor("127.0.0.1", 22, "tester")

    with pytest.raises(PermissionError):
        executor._validate(MOUNT_RECOVERY_SCRIPT + " --force", EnvironmentType.PRODUCTION, approved=True)
