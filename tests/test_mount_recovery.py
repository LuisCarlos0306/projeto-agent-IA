import pytest

from app.core.policies import EnvironmentType
from app.services.correction_policy import MOUNT_RECOVERY_SCRIPT, validate_correction
from app.services.mount_jobs import MOUNT_RECOVERY_JOB, MOUNT_VALIDATION_JOB, _mount_activity_document
from app.services.mount_ops import (
    MountOperationError,
    _mount_execution_command,
    probe_mount,
    validate_mount_path,
)
from app.services.ssh import CommandResult, SSHExecutor


class FakeExecutor:
    def __init__(
        self,
        stdout: str,
        *,
        sudo_stdout: str = "",
        exit_code: int = 0,
        sudo_exit_code: int = 0,
        stderr: str = "",
    ):
        self.stdout = stdout
        self.sudo_stdout = sudo_stdout
        self.exit_code = exit_code
        self.sudo_exit_code = sudo_exit_code
        self.stderr = stderr
        self.commands = []

    def run(self, command, environment, approved=False, timeout=60):
        self.commands.append(("run", command, environment, approved, timeout))
        return CommandResult(command, self.exit_code, self.stdout, self.stderr)

    def run_sudo(self, command, environment, approved=False, timeout=60):
        self.commands.append(("sudo", command, environment, approved, timeout))
        return CommandResult(command, self.sudo_exit_code, self.sudo_stdout, self.stderr)


def test_mount_path_accepts_authorized_backup_prefix():
    assert validate_mount_path("/mnt/backup_nas_rman") == "/mnt/backup_nas_rman"


def test_mount_path_rejects_shell_injection():
    with pytest.raises(MountOperationError):
        validate_mount_path("/mnt/backup;reboot")


def test_mount_path_rejects_root_filesystem():
    with pytest.raises(MountOperationError):
        validate_mount_path("/")


def test_probe_accepts_mssql_owned_script_and_discovers_mssql_cron_user():
    executor = FakeExecutor(
        "\n".join(
            [
                "MOUNTED=0",
                "SCRIPT_PRESENT=1",
                "SCRIPT_META=mssql|mssql|755",
            ]
        ),
        sudo_stdout="CRON_ENTRY=mssql|/var/spool/cron/mssql|*/5 * * * *\n",
    )

    result = probe_mount(executor, EnvironmentType.PRODUCTION, "/mnt/backup_nas_rman")

    assert result.mounted is False
    assert result.script_owner == "mssql"
    assert result.script_group == "mssql"
    assert result.script_safe is True
    assert result.cron_found is True
    assert result.cron_user == "mssql"
    assert result.cron_ambiguous is False


def test_probe_accepts_root_owned_script_and_discovers_root_cron_user():
    executor = FakeExecutor(
        "\n".join(
            [
                "MOUNTED=1",
                "FINDMNT=/mnt/backup_nas_rman 172.16.250.10:/BKP_FISICO nfs4 rw,relatime",
                "DF=172.16.250.10:/BKP_FISICO 8.0T 4.0T 4.0T 50% /mnt/backup_nas_rman",
                "SCRIPT_PRESENT=1",
                "SCRIPT_META=root|root|755",
            ]
        ),
        sudo_stdout="CRON_ENTRY=root|/var/spool/cron/root|*/5 * * * *\n",
    )

    result = probe_mount(executor, EnvironmentType.PRODUCTION, "/mnt/backup_nas_rman")

    assert result.mounted is True
    assert result.source == "172.16.250.10:/BKP_FISICO"
    assert result.fstype == "nfs4"
    assert result.script_safe is True
    assert result.cron_user == "root"


def test_probe_blocks_group_writable_mount_script():
    executor = FakeExecutor(
        "\n".join(
            [
                "MOUNTED=0",
                "SCRIPT_PRESENT=1",
                "SCRIPT_META=mssql|mssql|775",
            ]
        ),
        sudo_stdout="CRON_ENTRY=mssql|/var/spool/cron/mssql|*/5 * * * *\n",
    )

    result = probe_mount(executor, EnvironmentType.PRODUCTION, "/mnt/backup_nas_rman")

    assert result.script_executable is True
    assert result.script_safe is False


def test_probe_marks_multiple_cron_users_as_ambiguous():
    executor = FakeExecutor(
        "MOUNTED=0\nSCRIPT_PRESENT=1\nSCRIPT_META=root|root|755\n",
        sudo_stdout="\n".join(
            [
                "CRON_ENTRY=root|/var/spool/cron/root|*/5 * * * *",
                "CRON_ENTRY=mssql|/var/spool/cron/mssql|*/10 * * * *",
            ]
        ),
    )

    result = probe_mount(executor, EnvironmentType.PRODUCTION, "/mnt/backup_nas_rman")

    assert result.cron_found is True
    assert result.cron_ambiguous is True
    assert result.cron_user is None


def test_execution_command_uses_discovered_cron_user():
    assert _mount_execution_command("root") == MOUNT_RECOVERY_SCRIPT
    assert _mount_execution_command("mssql") == f"sudo -u mssql -- {MOUNT_RECOVERY_SCRIPT}"
    assert _mount_execution_command("oracle") == f"sudo -u oracle -- {MOUNT_RECOVERY_SCRIPT}"


def test_correction_policy_allows_exact_script_and_safe_run_as_user():
    direct = validate_correction(MOUNT_RECOVERY_SCRIPT)
    as_mssql = validate_correction(f"sudo -u mssql -- {MOUNT_RECOVERY_SCRIPT}")
    altered = validate_correction(MOUNT_RECOVERY_SCRIPT + " --force")

    assert direct.allowed is True
    assert direct.action_type == "mount_recovery"
    assert as_mssql.allowed is True
    assert as_mssql.action_type == "mount_recovery"
    assert altered.allowed is False


def test_ssh_policy_requires_explicit_approval_for_mount_in_production():
    executor = SSHExecutor("127.0.0.1", 22, "tester")

    with pytest.raises(PermissionError):
        executor._validate(MOUNT_RECOVERY_SCRIPT, EnvironmentType.PRODUCTION, approved=False)

    executor._validate(MOUNT_RECOVERY_SCRIPT, EnvironmentType.PRODUCTION, approved=True)
    executor._validate(
        f"sudo -u mssql -- {MOUNT_RECOVERY_SCRIPT}",
        EnvironmentType.PRODUCTION,
        approved=True,
    )


def test_ssh_policy_rejects_mount_in_unknown_environment():
    executor = SSHExecutor("127.0.0.1", 22, "tester")

    with pytest.raises(PermissionError):
        executor._validate(MOUNT_RECOVERY_SCRIPT, EnvironmentType.UNKNOWN, approved=True)


def test_ssh_policy_rejects_altered_mount_script_after_approval():
    executor = SSHExecutor("127.0.0.1", 22, "tester")

    with pytest.raises(PermissionError):
        executor._validate(MOUNT_RECOVERY_SCRIPT + " --force", EnvironmentType.PRODUCTION, approved=True)


def test_mount_validation_history_is_healthy_with_full_confidence_when_mounted():
    document = _mount_activity_document(
        MOUNT_VALIDATION_JOB,
        {
            "target": "172.27.228.33",
            "resolved_host": "172.27.228.33",
            "environment": "production",
            "path": "/mnt/backup_check",
            "mounted": True,
            "source": "/dev/sdc1",
            "fstype": "xfs",
            "cron_user": "root",
        },
        duration_ms=850,
    )

    assert document["status"] == "healthy"
    assert document["confidence"] == 100
    assert document["profile"] == "mount"
    assert document["analysis"]["operation"] == MOUNT_VALIDATION_JOB
    assert document["analysis"]["deterministic_validation"] is True


def test_mount_validation_history_is_attention_with_full_confidence_when_unmounted():
    document = _mount_activity_document(
        MOUNT_VALIDATION_JOB,
        {
            "target": "172.27.228.33",
            "resolved_host": "172.27.228.33",
            "environment": "production",
            "path": "/mnt/backup_check",
            "mounted": False,
            "can_request_mount": True,
            "cron_user": "root",
        },
        duration_ms=640,
    )

    assert document["status"] == "attention"
    assert document["confidence"] == 100
    assert document["mode"] == "investigate"
    assert document["plans"][0]["playbook"]["title"] == "Validação de mount"


def test_mount_recovery_history_is_healthy_when_post_validation_is_mounted():
    document = _mount_activity_document(
        MOUNT_RECOVERY_JOB,
        {
            "target": "172.27.228.33",
            "resolved_host": "172.27.228.33",
            "environment": "production",
            "path": "/mnt/backup_check",
            "mounted": True,
            "execution_user": "root",
            "after": {"source": "/dev/sdc1", "fstype": "xfs"},
        },
        duration_ms=2100,
    )

    assert document["status"] == "healthy"
    assert document["confidence"] == 100
    assert document["mode"] == "correct"
    assert document["plans"][0]["playbook"]["title"] == "Montagem preventiva"
