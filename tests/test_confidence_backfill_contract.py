from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_backfill_script_is_safe_by_default():
    source = (ROOT / "scripts" / "recalculate_confidence.py").read_text(encoding="utf-8")
    assert "--apply" in source
    assert "backfill_confidence(apply=args.apply)" in source


def test_worker_and_child_install_confidence_instrumentation():
    worker = (ROOT / "app" / "worker.py").read_text(encoding="utf-8")
    child = (ROOT / "app" / "job_child.py").read_text(encoding="utf-8")
    assert "install_confidence_instrumentation()" in worker
    assert "install_confidence_instrumentation()" in child


def test_web_installs_confidence_instrumentation():
    source = (ROOT / "app" / "web_main.py").read_text(encoding="utf-8")
    assert "install_confidence_instrumentation()" in source
