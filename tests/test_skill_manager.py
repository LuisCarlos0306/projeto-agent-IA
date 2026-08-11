from app.services.skill_manager import (
    action_is_read_only,
    action_requires_approval,
    get_skill,
    get_skill_action,
    list_skills,
    load_skill_catalog,
)


def test_skill_catalog_loads_backup_validation():
    catalog = load_skill_catalog()

    assert catalog["schema_version"] == 1
    assert catalog["catalog_version"] == "1.2.0"
    assert any(skill["id"] == "backup_validation" for skill in catalog["skills"])


def test_backup_validation_is_the_only_active_initial_skill():
    active = list_skills(include_planned=False)

    assert [skill["id"] for skill in active] == ["backup_validation"]


def test_backup_validation_has_read_only_checks():
    assert action_is_read_only("backup_validation", "validate_filesystem") is True
    assert action_is_read_only("backup_validation", "validate_mount") is True
    assert action_is_read_only("backup_validation", "validate_space") is True
    assert action_is_read_only("backup_validation", "validate_retention") is True
    assert action_is_read_only("backup_validation", "validate_last_backup") is True
    assert action_is_read_only("backup_validation", "validate_redundancy") is True


def test_mount_script_is_registered_but_not_enabled():
    skill = get_skill("backup_validation")
    action = get_skill_action("backup_validation", "execute_mount_script")

    assert skill is not None
    assert skill["version"] == "1.2.0"
    assert "/db/backup/scripts/mount.sh" in skill["dependencies"]["scripts"]
    assert action is not None
    assert action["command"] == "/db/backup/scripts/mount.sh"
    assert action["enabled"] is False
    assert action_requires_approval("backup_validation", "execute_mount_script") is True
