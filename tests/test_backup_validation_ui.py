from pathlib import Path
import json

from app.web_fast_validation import ASSET_VERSION, _enhanced_index


ROOT = Path(__file__).resolve().parents[1]


def test_skills_ui_uses_unified_action_builder_and_visible_target_execution():
    script = (ROOT / "app" / "ui" / "skills.js").read_text(encoding="utf-8")
    stylesheet = (ROOT / "app" / "ui" / "custom-skills.css").read_text(encoding="utf-8")
    html = _enhanced_index()

    assert "+ Criar Skill" in script
    assert 'id="custom-skill-editor-form"' in script
    assert "Nome da Skill" in script
    assert "Permissão da Skill" in script
    assert '>Leitura<' in script
    assert '>Diagnóstico<' in script
    assert '>Correção<' in script

    assert "Ações da Skill" in script
    assert 'id="custom-skill-action-type"' in script
    assert '<option value="command">Comando</option>' in script
    assert '<option value="script">Script</option>' in script
    assert 'id="custom-skill-action-value"' in script
    assert "data-add-skill-action" in script
    assert "data-remove-skill-action" in script
    assert "collectActions" in script

    assert "data-edit-skill" in script
    assert "✎" in script
    assert "data-delete-skill" in script
    assert 'id="custom-skill-run-form"' in script
    assert "IP / Servidor" in script
    assert "A Skill já contém todas as ações cadastradas" in script
    assert "Executar Skill" in script
    assert "renderSkill(saved)" in script

    assert 'method: skillId ? "PUT" : "POST"' in script
    assert "Scripts aguardando aprovação" in script
    assert "Nenhum script foi executado nesta etapa" in script
    assert "mount_point" not in script
    assert "redundancy_path" not in script
    assert "backup_path" not in script

    assert ".custom-skill-edit" in stylesheet
    assert ".custom-action-builder" in stylesheet
    assert ".custom-action-add-row" in stylesheet
    assert ".custom-skill-run-prominent" in stylesheet
    assert ".custom-pending-scripts" in stylesheet
    assert f"/ui/assets/skills.js?v={ASSET_VERSION}" in html
    assert f"/ui/assets/custom-skills.css?v={ASSET_VERSION}" in html
    assert "skills-auto-discovery.js" not in html
    assert "skills-storage-mapping.css" not in html


def test_backup_validation_catalog_keeps_mount_execution_disabled():
    catalog = json.loads((ROOT / "app" / "ui" / "skills-catalog.json").read_text(encoding="utf-8"))
    skill = next(item for item in catalog["skills"] if item["id"] == "backup_validation")
    mount_action = next(item for item in skill["actions"] if item["id"] == "execute_mount_script")

    assert catalog["catalog_version"] == "1.3.0"
    assert skill["version"] == "1.3.0"
    assert mount_action["risk"] == "approval_required"
    assert mount_action["enabled"] is False
    assert mount_action["command"] == "/db/backup/scripts/mount.sh"
