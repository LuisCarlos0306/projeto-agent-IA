from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_worker_installs_process_guard() -> None:
    source = (ROOT / "app" / "worker.py").read_text(encoding="utf-8")
    assert "install_job_process_guard" in source
    assert "Isolamento por processo: ativo" in source


def test_process_guard_uses_own_process_group_and_sigkill() -> None:
    source = (ROOT / "app" / "services" / "job_process_guard.py").read_text(encoding="utf-8")
    assert "start_new_session=True" in source
    assert "os.killpg(process.pid, signal.SIGTERM)" in source
    assert "os.killpg(process.pid, signal.SIGKILL)" in source
    assert "_hard_timeout_seconds()" in source
    assert "job_cancel_requested" in source
    assert 'status="cancelled"' in source
    assert 'status="failed"' in source


def test_job_child_installs_operational_instrumentation() -> None:
    source = (ROOT / "app" / "job_child.py").read_text(encoding="utf-8")
    for expected in (
        "install_focused_validation()",
        "install_ai_instrumentation()",
        "install_ptbr_guard()",
        "install_operational_tools()",
        "install_worker_cancel_watchdog()",
        "install_hard_job_alarm()",
        "jobs._execute_job(payload, settings=settings)",
    ):
        assert expected in source
