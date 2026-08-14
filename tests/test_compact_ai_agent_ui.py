from __future__ import annotations

from pathlib import Path

from app.web_agents import _compact_agent_rows
from app.web_fast_validation import ASSET_VERSION, _enhanced_index


ROOT = Path(__file__).resolve().parents[1]


def test_compact_provider_assets_are_loaded() -> None:
    html = _enhanced_index()

    assert ASSET_VERSION == "1.30.35"
    assert f"/ui/assets/provider-compact-ui.css?v={ASSET_VERSION}" in html
    assert f"/ui/assets/provider-compact-ui.js?v={ASSET_VERSION}" in html
    assert f"/ui/assets/agents-v3.js?v={ASSET_VERSION}" in html
    assert "agents-v2.js" not in html


def test_provider_catalog_keeps_actions_and_adds_simple_filters() -> None:
    legacy = (ROOT / "app" / "ui" / "settings.js").read_text(encoding="utf-8")
    compact = (ROOT / "app" / "ui" / "provider-compact-ui.js").read_text(encoding="utf-8")

    assert "data-edit-provider" in legacy
    assert "data-test-provider" in legacy
    assert "data-delete-provider" in legacy
    assert 'data-provider-compact-filter' in compact
    assert '["cloud", "Cloud"]' in compact
    assert '["local", "Local"]' in compact
    assert '["gateway", "Gateway"]' in compact


def test_agent_list_uses_lightweight_polling_and_lazy_log_rendering() -> None:
    script = (ROOT / "app" / "ui" / "agents-v3.js").read_text(encoding="utf-8")

    assert 'requestJson("/ui/api/agents?compact=1")' in script
    assert 'event.target.closest(".agent-v2-card[data-agent-id]")' in script
    assert "data-agent-log-body" in script
    assert "hydrateLog(details)" in script
    assert "Abra para carregar os detalhes desta execução." in script


def test_compact_agent_rows_remove_history_without_mutating_source() -> None:
    source = [{"id": "a1", "name": "agent", "history": [{"job_id": "j1"}]}]

    compact = _compact_agent_rows(source)

    assert compact[0]["history"] == []
    assert source[0]["history"] == [{"job_id": "j1"}]
