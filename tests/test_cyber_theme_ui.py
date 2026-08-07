from __future__ import annotations

from pathlib import Path

from app.web_fast_validation import ASSET_VERSION, _enhanced_index


ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "app" / "ui"


def test_enhanced_index_loads_versioned_cyber_theme() -> None:
    html = _enhanced_index()

    assert f'/ui/assets/cyber-theme.css?v={ASSET_VERSION}' in html
    assert html.count("cyber-theme.css") == 1


def test_cyber_theme_distributes_cyan_and_violet_accents() -> None:
    stylesheet = (UI / "cyber-theme.css").read_text(encoding="utf-8")

    assert "--violet-neon: #a63cff" in stylesheet
    assert "--cyan-neon: #35e7ff" in stylesheet
    assert ".nav-item.active" in stylesheet
    assert ".primary-button" in stylesheet
    assert "#datastore-monitor .datastore-panel" in stylesheet
    assert ".investigation-confidence-segments i.active" in stylesheet


def test_brand_is_replaced_by_neural_circuit_logo() -> None:
    script = (UI / "investigation-confidence.js").read_text(encoding="utf-8")

    assert "function installCyberBrand()" in script
    assert 'class="brand-ai-logo"' in script
    assert 'class="brand-head"' in script
    assert 'class="brand-trace"' in script
    assert 'stop-color="#b03cff"' in script
    assert "installCyberBrand();" in script
