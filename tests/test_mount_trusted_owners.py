import os

from app.services.mount_ops import _parse_probe, trusted_mount_owners


def test_default_trusted_mount_owners_contains_root(monkeypatch):
    monkeypatch.delenv("AGENT_MOUNT_TRUSTED_OWNERS", raising=False)
    assert "root" in trusted_mount_owners()


def test_mssql_can_be_trusted_by_configuration(monkeypatch):
    monkeypatch.setenv("AGENT_MOUNT_TRUSTED_OWNERS", "root,mssql")
    probe = _parse_probe(
        "/mnt/backup",
        "MOUNTED=0\nSCRIPT_PRESENT=1\nSCRIPT_META=mssql|755\n",
    )
    assert probe.script_safe is True


def test_untrusted_owner_is_blocked(monkeypatch):
    monkeypatch.setenv("AGENT_MOUNT_TRUSTED_OWNERS", "root,mssql")
    probe = _parse_probe(
        "/mnt/backup",
        "MOUNTED=0\nSCRIPT_PRESENT=1\nSCRIPT_META=usuario|755\n",
    )
    assert probe.script_safe is False


def test_group_writable_script_remains_blocked(monkeypatch):
    monkeypatch.setenv("AGENT_MOUNT_TRUSTED_OWNERS", "root,mssql")
    probe = _parse_probe(
        "/mnt/backup",
        "MOUNTED=0\nSCRIPT_PRESENT=1\nSCRIPT_META=mssql|775\n",
    )
    assert probe.script_safe is False
