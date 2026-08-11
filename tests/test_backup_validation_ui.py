from pathlib import Path
import json

from app.web_fast_validation import ASSET_VERSION, _enhanced_index


ROOT = Path(__file__).resolve().parents[1]


def test_backup_validation_ui_exposes_read_only_execution_form():
    script = (ROOT / "app" / "ui" / "skills.js").read_text(encoding="utf-8")
    stylesheet = (ROOT / "app" / "ui" / "skills.css").read_text(encoding="utf-8")
    html = _enhanced_index()

    assert 'id="backup-validation-form"' in script
    assert "/ui/api/skills/backup-validation/run" in script
    assert "/ui/api/skills/jobs/" in script
    assert "Executar validação" in script
    assert "Somente consultas são executadas" in script
    assert "Solicitar montagem" in script
    assert "disabled" in script
    assert ".skill-result-row" in stylesheet
    assert ".skill-run-form" in stylesheet
    assert f"/ui/assets/skills.js?v={ASSET_VERSION}" in html
    assert f"/ui/assets/skills.css?v={ASSET_VERSION}" in html


def test_backup_validation_catalog_keeps_mount_action_disabled():
    catalog = json.loads((ROOT / "app" / "ui" / "skills-catalog.json").read_text(encoding="utf-8"))
    skill = next(item for item in catalog["skills"] if item["id"] == "backup_validation")
    mount_action = next(item for item in skill["actions"] if item["id"] == "execute_mount_script")

    assert catalog["catalog_version"] == "1.1.0"
    assert skill["version"] == "1.1.0"
    assert mount_action["risk"] == "approval_required"
    assert mount_action["enabled"] is False
    assert mount_action["command"] == "/db/backup/scripts/mount.sh"
