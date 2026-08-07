from __future__ import annotations

from threading import Event

from app.services import worker_cancel_watchdog as watchdog


def test_cancel_force_exit_seconds_is_bounded(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_CANCEL_FORCE_EXIT_SECONDS", "1")
    assert watchdog._grace_seconds() == 5

    monkeypatch.setenv("AGENT_CANCEL_FORCE_EXIT_SECONDS", "999")
    assert watchdog._grace_seconds() == 120

    monkeypatch.setenv("AGENT_CANCEL_FORCE_EXIT_SECONDS", "valor-invalido")
    assert watchdog._grace_seconds() == 20


def test_hard_timeout_uses_budget_plus_grace(monkeypatch) -> None:
    class Config:
        max_investigation_seconds = 240

    monkeypatch.delenv("AGENT_JOB_HARD_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("AGENT_JOB_HARD_TIMEOUT_GRACE_SECONDS", raising=False)
    monkeypatch.setattr(watchdog.investigation_budget, "get_performance_config", lambda: Config())

    assert watchdog._hard_timeout_seconds() == 255

    monkeypatch.setenv("AGENT_JOB_HARD_TIMEOUT_SECONDS", "30")
    assert watchdog._hard_timeout_seconds() == 60

    monkeypatch.setenv("AGENT_JOB_HARD_TIMEOUT_SECONDS", "9999")
    assert watchdog._hard_timeout_seconds() == 1800


def test_watchdog_marks_job_and_forces_worker_exit(monkeypatch) -> None:
    marked: list[tuple[str, object, str]] = []
    exits: list[int] = []

    monkeypatch.setattr(watchdog, "_poll_seconds", lambda: 0.001)
    monkeypatch.setattr(watchdog, "_grace_seconds", lambda: 0)
    monkeypatch.setattr(watchdog, "_hard_timeout_seconds", lambda: 999)
    monkeypatch.setattr(
        watchdog.jobs,
        "job_cancel_requested",
        lambda job_id, settings=None: True,
    )
    monkeypatch.setattr(
        watchdog,
        "_mark_job_cancelled",
        lambda job_id, settings, detail: marked.append((job_id, settings, detail)),
    )
    monkeypatch.setattr(watchdog, "_FORCE_EXIT", lambda code: exits.append(code))

    settings = object()
    watchdog._watch("job-123", settings, Event())

    assert marked
    assert marked[0][0] == "job-123"
    assert "Cancelamento forçado" in marked[0][2]
    assert exits == [130]


def test_watchdog_marks_timeout_and_restarts_worker(monkeypatch) -> None:
    marked: list[tuple[str, object, str]] = []
    exits: list[int] = []

    monkeypatch.setattr(watchdog, "_poll_seconds", lambda: 0.001)
    monkeypatch.setattr(watchdog, "_hard_timeout_seconds", lambda: 0)
    monkeypatch.setattr(
        watchdog.jobs,
        "job_cancel_requested",
        lambda job_id, settings=None: False,
    )
    monkeypatch.setattr(
        watchdog,
        "_mark_job_timed_out",
        lambda job_id, settings, detail: marked.append((job_id, settings, detail)),
    )
    monkeypatch.setattr(watchdog, "_FORCE_EXIT", lambda code: exits.append(code))

    settings = object()
    watchdog._watch("job-timeout", settings, Event())

    assert marked
    assert marked[0][0] == "job-timeout"
    assert "interrompida automaticamente" in marked[0][2]
    assert exits == [124]
