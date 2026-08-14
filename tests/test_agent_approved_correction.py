from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.core.policies import ActionType, EnvironmentType, classify_command
from app.services.correction_policy import STANDARD_MOUNT_SCRIPT
from app.services.custom_skill_approved_correction import (
    CustomSkillCorrectionError,
    _structured_action,
    execute_approved_agent_correction,
)
from app.services.ssh import CommandResult


def test_mount_is_classified_as_filesystem_correction() -> None:
    assert classify_command("mount /mnt/backup_check") == ActionType.FILESYSTEM_ADJUSTMENT
    assert classify_command(STANDARD_MOUNT_SCRIPT) == ActionType.FILESYSTEM_ADJUSTMENT


def test_conditional_mount_command_is_mapped_to_standard_script() -> None:
    skill = {
        "condition": {
            "enabled": True,
            "validation": "findmnt -M /mnt/backup_check",
            "action": {"type": "command", "value": "mount /mnt/backup_check"},
            "post_validation": "findmnt -M /mnt/backup_check",
        }
    }
    action = _structured_action(skill)
    assert action["tool"] == "backup.mount_standard"
    assert action["arguments"]["mount_point"] == "/mnt/backup_check"
    assert action["configured_action"] == "mount /mnt/backup_check"
    assert STANDARD_MOUNT_SCRIPT in action["label"]


def test_standard_mount_script_uses_findmnt_to_discover_target() -> None:
    skill = {
        "condition": {
            "enabled": True,
            "validation": "findmnt -M /mnt/backup_check",
            "action": {"type": "script", "value": STANDARD_MOUNT_SCRIPT},
            "post_validation": "findmnt -M /mnt/backup_check",
        }
    }
    action = _structured_action(skill)
    assert action["tool"] == "backup.mount_standard"
    assert action["arguments"]["mount_point"] == "/mnt/backup_check"


class FakeExecutor:
    def __init__(self) -> None:
        self.connected = False
        self.closed = False
        self.sudo_commands: list[str] = []

    def connect(self) -> None:
        self.connected = True

    def close(self) -> None:
        self.closed = True

    def run(self, command, environment, approved=False, timeout=60):
        assert approved is False
        return CommandResult(command, 0, "/mnt/backup_check\n", "")

    def run_sudo(self, command, environment, approved=False, timeout=60):
        assert approved is True
        self.sudo_commands.append(command)
        return CommandResult(command, 0, "montagem concluída", "")


def test_approved_mount_executes_fixed_script_and_persists_success() -> None:
    settings = SimpleNamespace(ssh_command_timeout=60)
    preview = {
        "agent_id": "11111111-1111-1111-1111-111111111111",
        "job_id": "job-1",
        "skill_id": "skill-1",
        "skill_name": "Validar montagem",
        "target": "srv-backup",
        "resolved_host": "10.0.0.10",
        "environment": "monitoring",
        "ssh_port": 22,
        "action": {
            "tool": "backup.mount_standard",
            "arguments": {"mount_point": "/mnt/backup_check"},
            "configured_action": "mount /mnt/backup_check",
            "label": "Montar /mnt/backup_check",
        },
        "condition": {
            "validation": {"command": "findmnt -M /mnt/backup_check", "exit_code": 1, "stdout": "", "stderr": ""},
            "action_needed": True,
        },
    }
    skill = {
        "id": "skill-1",
        "name": "Validar montagem",
        "condition": {
            "enabled": True,
            "post_validation": "findmnt -M /mnt/backup_check",
            "messages": {"success": "Montagem executada com sucesso."},
        },
    }
    target = SimpleNamespace(
        reference="srv-backup",
        host="10.0.0.10",
        port=22,
        environment=EnvironmentType.MONITORING,
        inventory={"environment": "monitoring"},
    )
    fake = FakeExecutor()
    job = {
        "job_id": "job-1",
        "status": "completed",
        "result": {
            "action_needed": True,
            "correction_status": "pending_approval",
            "pending_commands": [{"command": "mount /mnt/backup_check", "status": "pending_approval"}],
            "scripts": [],
            "executed_actions": [],
            "commands": [],
        },
    }

    with patch("app.services.custom_skill_approved_correction.correction_preview", return_value=preview), patch(
        "app.services.custom_skill_approved_correction.get_agent", return_value={"skill_id": "skill-1"}
    ), patch("app.services.custom_skill_approved_correction.get_custom_skill", return_value=skill), patch(
        "app.services.custom_skill_approved_correction.review_corrections",
        return_value={"approved": True, "status": "approved", "provider": "reviewer", "model": "model", "confidence": 100},
    ), patch("app.services.custom_skill_approved_correction.create_approval_token", return_value="signed.token"), patch(
        "app.services.custom_skill_approved_correction.verify_approval_token",
        return_value={"investigation_id": "agent:11111111-1111-1111-1111-111111111111:job-1", "target": "srv-backup"},
    ), patch("app.services.custom_skill_approved_correction.token_digest", return_value="digest"), patch(
        "app.services.custom_skill_approved_correction.resolve_target", return_value=target
    ), patch("app.services.custom_skill_approved_correction.build_executor", return_value=fake), patch(
        "app.services.jobs.get_job", return_value=job
    ), patch("app.services.jobs._redis", return_value=object()), patch(
        "app.services.jobs._store"
    ) as store, patch("app.services.custom_skill_approved_correction.update_agent_runtime"), patch(
        "app.services.custom_skill_approved_correction.update_agent_history_result"
    ), patch("app.services.custom_skill_approved_correction.record_run_detail"):
        result = execute_approved_agent_correction(preview["agent_id"], requested_by="luis", settings=settings)

    assert result["success"] is True
    assert result["message"] == "Montagem executada com sucesso."
    assert fake.sudo_commands == [STANDARD_MOUNT_SCRIPT]
    assert fake.connected and fake.closed
    stored = store.call_args.args[-1]
    stored_result = stored["result"]
    assert stored_result["correction_status"] == "executed_success"
    assert stored_result["approval_required"] is False
    assert stored_result["executed_actions"][0]["post_validation"]["ok"] is True


def test_unapproved_or_protected_environment_never_executes() -> None:
    source = __import__("pathlib").Path("app/services/custom_skill_approved_correction.py").read_text(encoding="utf-8")
    assert "environment_allows_correction" in source
    assert "review_corrections" in source
    assert "create_approval_token" in source
    assert "verify_approval_token" in source
    assert "approved=True" in source
    assert "APPROVAL_SECRET" in source
    assert "Produção" not in source or "somente proposta" in source
