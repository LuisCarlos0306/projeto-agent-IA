import json
from pathlib import Path

import pytest

from app.services.custom_skill_condition import condition_needs_action
from app.services.custom_skill_registry import create_custom_skill
from app.services.scheduled_agent_status import correction_outcome


ROOT = Path(__file__).resolve().parents[1]


def test_condition_uses_validation_result_to_decide_action() -> None:
    assert condition_needs_action("exit_code_nonzero", exit_code=1, stdout="") is True
    assert condition_needs_action("exit_code_nonzero", exit_code=0, stdout="mounted") is False
    assert condition_needs_action("stdout_contains", exit_code=0, stdout="state=failed", expected="failed") is True
    assert condition_needs_action("stdout_not_contains", exit_code=0, stdout="mounted", expected="mounted") is False


def test_conditional_skill_is_persisted_without_duplicate_corrective_action(tmp_path: Path) -> None:
    registry = tmp_path / "skills.json"
    skill = create_custom_skill(
        "Validar montagem",
        [],
        mode="correction",
        condition={
            "enabled": True,
            "validation": "findmnt -M /mnt/backup_check",
            "operator": "exit_code_nonzero",
            "expected": "",
            "action": {"type": "script", "value": "/db/backup/scripts/mount.sh"},
            "post_validation": "findmnt -M /mnt/backup_check",
            "messages": {
                "no_action": "Unidade montada. Nenhuma ação necessária.",
                "success": "Montagem executada com sucesso.",
                "failure": "A montagem não foi confirmada.",
            },
        },
        path=registry,
    )
    payload = json.loads(registry.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 3
    assert skill["commands"] == []
    assert skill["scripts"] == []
    assert skill["condition"]["action"]["value"] == "/db/backup/scripts/mount.sh"
    assert skill["condition"]["post_validation"] == "findmnt -M /mnt/backup_check"


def test_read_only_skill_cannot_define_corrective_condition(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Diagnóstico ou Correção"):
        create_custom_skill(
            "Leitura condicional",
            [],
            mode="read_only",
            condition={
                "enabled": True,
                "validation": "df -h",
                "operator": "exit_code_nonzero",
                "action": {"type": "command", "value": "mount /mnt/backup_check"},
                "post_validation": "df -h",
            },
            path=tmp_path / "skills.json",
        )


def test_no_action_result_keeps_log_clean() -> None:
    status, message = correction_outcome(
        {
            "action_needed": False,
            "correction_status": "not_needed",
            "correction_message": "Unidade validada. Nenhuma ação necessária.",
            "pending_commands": [],
            "scripts": [],
            "executed_actions": [],
        }
    )
    assert status == "not_needed"
    assert message == "Unidade validada. Nenhuma ação necessária."


def test_conditional_runner_only_proposes_action_after_match() -> None:
    runner = (ROOT / "app" / "services" / "custom_skill_runner.py").read_text(encoding="utf-8")
    assert 'if condition_result["action_needed"]:' in runner
    assert '"action_needed": action_needed' in runner
    assert 'correction_status = "not_needed"' in runner
    assert 'correction_status = "pending_approval"' in runner
    assert 'condition.get("post_validation")' in runner
    assert '"executed_actions": []' in runner


def test_conditional_editor_and_navigation_icons_are_loaded() -> None:
    conditional = (ROOT / "app" / "ui" / "conditional-skills.js").read_text(encoding="utf-8")
    icons = (ROOT / "app" / "ui" / "navigation-icons.js").read_text(encoding="utf-8")
    icon_css = (ROOT / "app" / "ui" / "navigation-icons.css").read_text(encoding="utf-8")
    web = (ROOT / "app" / "web_fast_validation.py").read_text(encoding="utf-8")
    cache = (ROOT / "app" / "web_ui_cache.py").read_text(encoding="utf-8")

    assert "Fluxo condicional" in conditional
    assert "Validação → decisão → correção → pós-validação" in conditional
    assert "/db/backup/scripts/mount.sh" in conditional
    assert "navigation-icons.js" in web
    assert "navigation-icons.css" in web
    assert "conditional-skills.js" in web
    assert "conditional-skills.css" in web
    assert "navigation-icons.js" in cache
    assert "conditional-skills.js" in cache
    assert "nav-svg-icon" in icon_css
    for view in ("dashboard", "investigations", "agents", "skills", "playbooks", "agentflow", "inventory", "settings", "health"):
        assert f"{view}:" in icons
