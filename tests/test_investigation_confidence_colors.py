from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "app" / "ui" / "investigation-confidence.css").read_text(encoding="utf-8")
JS = (ROOT / "app" / "ui" / "investigation-confidence.js").read_text(encoding="utf-8")
WEB = (ROOT / "app" / "web_fast_validation.py").read_text(encoding="utf-8")


def test_confidence_colors_cover_all_levels_and_zero_percent() -> None:
    assert 'data-level="medium"' in CSS
    assert 'data-level="low"' in CSS
    assert 'data-level="high"' in CSS
    assert "currentColor 9%" in CSS
    assert "color: currentColor" in CSS


def test_confidence_component_updates_dashboard_and_history() -> None:
    assert 'decorateRows(document.querySelector("#recent-investigations"), 3)' in JS
    assert 'decorateRows(document.querySelector("#investigations-table"), 5)' in JS
    assert 'data-score="${score}"' in JS
    assert "characterData: true" in JS
    assert "Number(current.dataset.score) === value" in JS


def test_confidence_assets_use_current_ui_version() -> None:
    assert 'ASSET_VERSION = "1.30.28"' in WEB
    assert '"investigation-confidence.css"' in WEB
    assert '"investigation-confidence.js"' in WEB
