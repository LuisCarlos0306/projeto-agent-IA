from pathlib import Path
import json

from app.web_fast_validation import ASSET_VERSION, _enhanced_index


ROOT = Path(__file__).resolve().parents[1]


def test_backup_validation_ui_uses_manual_mapping_and_simple_daily_form():
    script = (ROOT / "app" / "ui" / "skills.js").read_text(encoding="utf-8")
    mapping = (ROOT / "app" / "ui" / "skills-auto-discovery.js").read_text(encoding="utf-8")
    stylesheet = (ROOT / "app" / "ui" / "skills-storage-mapping.css").read_text(encoding="utf-8")
    html = _enhanced_index()

    assert 'id="backup-validation-form"' in script
    assert "CONFIGURAÇÃO MANUAL · UMA VEZ" in mapping
    assert "Mapear unidades do servidor" in mapping
    assert "Salvar mapeamento" in mapping
    assert "Validar servidor" in mapping
    assert "/ui/api/skills/backup-validation/mappings" in mapping
    assert "/ui/api/skills/backup-validation/run" in mapping
    assert "Filesystem, unidades e script não são solicitados nesta tela" in mapping
    assert "Nenhuma necessidade de atuação" in mapping
    assert "Solicitar validação" in mapping
    assert DEFAULT_MOUNT_SCRIPT in mapping
    assert ".storage-map-unit" in stylesheet
    assert f"/ui/assets/skills-auto-discovery.js?v={ASSET_VERSION}" in html
    assert f"/ui/assets/skills-storage-mapping.css?v={ASSET_VERSION}" in html


def test_backup_validation_catalog_keeps_mount_execution_disabled():
    catalog = json.loads((ROOT / "app" / "ui" / "skills-catalog.json").read_text(encoding="utf-8"))
    skill = next(item for item in catalog["skills"] if item["id"] == "backup_validation")
    mount_action = next(item for item in skill["actions"] if item["id"] == "execute_mount_script")

    assert catalog["catalog_version"] == "1.3.0"
    assert skill["version"] == "1.3.0"
    assert mount_action["risk"] == "approval_required"
    assert mount_action["enabled"] is False
    assert mount_action["command"] == "/db/backup/scripts/mount.sh"


DEFAULT_MOUNT_SCRIPT = "/db/backup/scripts/mount.sh"
