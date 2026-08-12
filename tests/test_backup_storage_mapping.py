from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.core.policies import EnvironmentType
from app.services.backup_storage_registry import DEFAULT_MOUNT_SCRIPT, get_mapping, save_mapping
from app.services.mapped_backup_validation import run_backup_validation
from app.services.ssh import CommandResult


class FakeExecutor:
    def __init__(self, mounted: dict[str, bool]):
        self.mounted = mounted
        self.commands: list[str] = []
        self.closed = False

    def connect(self):
        return None

    def close(self):
        self.closed = True

    def run(self, command, environment, approved=False, timeout=60):
        self.commands.append(command)
        assert environment == EnvironmentType.TRAINING
        assert approved is False
        if command.startswith("findmnt "):
            path = next((item for item in self.mounted if item in command), "")
            if path and self.mounted[path]:
                return CommandResult(command, 0, f"server:/backup {path} nfs4 rw,relatime\n", "")
            return CommandResult(command, 1, "", "")
        if command.startswith("df "):
            path = next((item for item in self.mounted if item in command), "/mnt/backup_check")
            return CommandResult(
                command,
                0,
                "Filesystem 1024-blocks Used Available Capacity Mounted on\n"
                f"server:/backup 100000 40000 60000 40% {path}\n",
                "",
            )
        raise AssertionError(f"comando não esperado: {command}")


def resolved_target():
    return SimpleNamespace(
        reference="172.27.232.212",
        host="172.27.232.212",
        port=22,
        environment=EnvironmentType.TRAINING,
        inventory=None,
    )


def test_mapping_is_saved_once_and_reloaded_by_target(tmp_path, monkeypatch):
    registry = tmp_path / "backup-storage-map.json"
    monkeypatch.setenv("AGENT_BACKUP_STORAGE_MAP_PATH", str(registry))

    saved = save_mapping(
        {
            "target": "172.27.232.212",
            "mount_script": DEFAULT_MOUNT_SCRIPT,
            "units": [
                {"role": "principal", "label": "Backup principal", "mount_point": "/mnt/backup_check", "min_free_percent": 20},
                {"role": "redundancia", "label": "HD externo", "mount_point": "/mnt/hdexterno", "min_free_percent": 15},
            ],
        }
    )

    loaded = get_mapping("172.27.232.212")
    assert loaded == saved
    assert registry.exists()
    assert registry.stat().st_mode & 0o777 == 0o600
    assert loaded["mount_script"] == DEFAULT_MOUNT_SCRIPT
    assert len(loaded["units"]) == 2


def test_mapping_rejects_arbitrary_mount_script(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_BACKUP_STORAGE_MAP_PATH", str(tmp_path / "map.json"))
    with pytest.raises(ValueError, match="único script permitido"):
        save_mapping(
            {
                "target": "srv01",
                "mount_script": "/tmp/mount.sh",
                "units": [{"mount_point": "/mnt/backup", "role": "principal"}],
            }
        )


def test_mapped_validation_reports_no_action_when_all_units_are_mounted(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_BACKUP_STORAGE_MAP_PATH", str(tmp_path / "map.json"))
    save_mapping(
        {
            "target": "172.27.232.212",
            "units": [
                {"role": "principal", "label": "Backup principal", "mount_point": "/mnt/backup_check", "min_free_percent": 20},
                {"role": "redundancia", "label": "HD externo", "mount_point": "/mnt/hdexterno", "min_free_percent": 20},
            ],
        }
    )
    fake = FakeExecutor({"/mnt/backup_check": True, "/mnt/hdexterno": True})
    with patch("app.services.mapped_backup_validation.resolve_target", return_value=resolved_target()), patch(
        "app.services.mapped_backup_validation.build_executor", return_value=fake
    ):
        result = run_backup_validation(
            "172.27.232.212",
            environment=EnvironmentType.TRAINING,
            settings=SimpleNamespace(),
        )

    assert result["status"] == "healthy"
    assert result["mode"] == "mapped_storage"
    assert result["action_required"] is False
    assert result["action_available"] is None
    assert "Nenhuma necessidade de atuação" in result["operator_message"]
    assert result["executed_actions"] == []
    assert fake.closed is True
    assert all(DEFAULT_MOUNT_SCRIPT not in command for command in fake.commands)


def test_mapped_validation_only_requests_validation_when_unit_is_unmounted(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_BACKUP_STORAGE_MAP_PATH", str(tmp_path / "map.json"))
    save_mapping(
        {
            "target": "172.27.232.212",
            "units": [
                {"role": "principal", "label": "Backup principal", "mount_point": "/mnt/backup_check"},
                {"role": "redundancia", "label": "HD externo", "mount_point": "/mnt/hdexterno"},
            ],
        }
    )
    fake = FakeExecutor({"/mnt/backup_check": True, "/mnt/hdexterno": False})
    with patch("app.services.mapped_backup_validation.resolve_target", return_value=resolved_target()), patch(
        "app.services.mapped_backup_validation.build_executor", return_value=fake
    ):
        result = run_backup_validation(
            "172.27.232.212",
            environment=EnvironmentType.TRAINING,
            settings=SimpleNamespace(),
        )

    assert result["status"] == "critical"
    assert result["action_required"] is True
    assert result["action_available"]["label"] == "Solicitar validação da montagem"
    assert result["action_available"]["command"] == DEFAULT_MOUNT_SCRIPT
    assert result["action_available"]["enabled"] is False
    assert result["action_available"]["targets"] == ["/mnt/hdexterno"]
    assert result["executed_actions"] == []
    assert all(DEFAULT_MOUNT_SCRIPT not in command for command in fake.commands)
