from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "app" / "ui"


def test_dashboard_loads_confidence_assets_directly() -> None:
    html = (UI / "index.html").read_text(encoding="utf-8")

    assert '/ui/assets/investigation-confidence.css?v=1.30.9' in html
    assert '/ui/assets/investigation-confidence.js?v=1.30.9' in html
    assert '/ui/assets/product-polish.js?v=1.30.9' in html


def test_datastore_monitor_cache_version_is_current() -> None:
    script = (UI / "product-polish.js").read_text(encoding="utf-8")

    assert '/ui/assets/datastore-monitor.css?v=1.30.9' in script
    assert '/ui/assets/datastore-monitor.js?v=1.30.9' in script
    assert 'datastore-monitor.js?v=1.30.4' not in script


def test_resource_history_is_hidden_and_confidence_meter_is_available() -> None:
    stylesheet = (UI / "investigation-confidence.css").read_text(encoding="utf-8")
    script = (UI / "investigation-confidence.js").read_text(encoding="utf-8")

    assert '#datastore-monitor .datastore-main-grid > .datastore-panel:not(.datastore-score-panel)' in stylesheet
    assert 'display: none !important' in stylesheet
    assert 'investigation-confidence-meter' in script
    assert 'Array.from({ length: 10 }' in script
