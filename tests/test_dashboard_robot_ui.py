from __future__ import annotations

from pathlib import Path

from app.web_fast_validation import ASSET_VERSION, _enhanced_index


ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_hides_datastore_general_state_panel() -> None:
    css = (ROOT / "app" / "ui" / "investigation-confidence.css").read_text(encoding="utf-8")

    assert "#datastore-monitor .datastore-main-grid" in css
    assert "display: none !important;" in css


def test_operator_avatar_is_rendered_as_robot_without_purple_gradient() -> None:
    css = (ROOT / "app" / "ui" / "investigation-confidence.css").read_text(encoding="utf-8")

    assert '.operator-avatar::before' in css
    assert 'content: "🤖";' in css
    assert "#7d7cff" not in css


def test_enhanced_index_refreshes_dashboard_assets_without_duplicates() -> None:
    html = _enhanced_index()

    confidence_css = f"/ui/assets/investigation-confidence.css?v={ASSET_VERSION}"
    confidence_js = f"/ui/assets/investigation-confidence.js?v={ASSET_VERSION}"

    assert confidence_css in html
    assert confidence_js in html
    assert html.count("investigation-confidence.css") == 1
    assert html.count("investigation-confidence.js") == 1
