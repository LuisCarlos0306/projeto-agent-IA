from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "app" / "ui"


def test_terminal_progress_colors_cover_all_final_states() -> None:
    css = (UI / "fast-validation-ui.css").read_text(encoding="utf-8")

    assert '.execution-tray[data-status="completed"]' in css
    assert '.execution-progress-summary[data-status="completed"]' in css
    assert '#55d69e' in css
    assert '.execution-tray[data-status="failed"]' in css
    assert '#ff7589' in css
    assert '.execution-tray[data-status="cancelled"]' in css
    assert '#ffc96b' in css


def test_progress_script_marks_summary_completed_at_100_percent() -> None:
    script = (UI / "fast-validation-ui.js").read_text(encoding="utf-8")

    assert "function syncTerminalProgressState()" in script
    assert 'summary.dataset.status = status' in script
    assert 'percent >= 100' in script
    assert 'status = "completed"' in script
    assert 'status = "failed"' in script
    assert 'status = "cancelled"' in script
