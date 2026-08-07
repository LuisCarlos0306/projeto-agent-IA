from __future__ import annotations

from pathlib import Path

from app.web_fast_validation import ASSET_VERSION, _enhanced_index


ROOT = Path(__file__).resolve().parents[1]


def test_enhanced_index_loads_confidence_assets() -> None:
    html = _enhanced_index()

    assert f"/ui/assets/investigation-confidence.css?v={ASSET_VERSION}" in html
    assert f"/ui/assets/investigation-confidence.js?v={ASSET_VERSION}" in html
    assert html.count("investigation-confidence.css") == 1
    assert html.count("investigation-confidence.js") == 1


def test_confidence_script_decorates_recent_and_history_tables() -> None:
    script = (ROOT / "app" / "ui" / "investigation-confidence.js").read_text(encoding="utf-8")

    assert 'observeTable("#recent-investigations", 3)' in script
    assert 'observeTable("#investigations-table", 5)' in script
    assert "Array.from({ length: 10 }" in script
    assert 'data-level="${level}"' in script
    assert 'score >= 70 ? "Alta"' in script


def test_confidence_styles_use_segmented_meter_and_hide_datastore_history_chart() -> None:
    stylesheet = (ROOT / "app" / "ui" / "investigation-confidence.css").read_text(encoding="utf-8")

    assert "grid-template-columns: repeat(10" in stylesheet
    assert '.investigation-confidence-meter[data-level="medium"]' in stylesheet
    assert '.investigation-confidence-meter[data-level="low"]' in stylesheet
    assert "#datastore-monitor .datastore-main-grid > .datastore-panel:not(.datastore-score-panel)" in stylesheet
    assert "display: none !important" in stylesheet
