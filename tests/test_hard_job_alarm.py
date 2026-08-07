from __future__ import annotations

from app.services import hard_job_alarm


def test_hard_job_alarm_is_installed_on_execute_job(monkeypatch) -> None:
    original = hard_job_alarm.jobs._execute_job
    hard_job_alarm._INSTALLED = False
    monkeypatch.setattr(hard_job_alarm, "_supports_alarm", lambda: True)

    hard_job_alarm.install_hard_job_alarm()

    assert getattr(hard_job_alarm.jobs._execute_job, "__agent_hard_alarm__", False) is True
    hard_job_alarm.jobs._execute_job = original
    hard_job_alarm._INSTALLED = False


def test_hard_job_timeout_message_is_portuguese() -> None:
    error = hard_job_alarm.HardJobTimeout(
        "Investigação job-1 interrompida automaticamente após 255s; o limite operacional foi atingido."
    )
    text = str(error)
    assert "interrompida automaticamente" in text
    assert "limite operacional" in text
