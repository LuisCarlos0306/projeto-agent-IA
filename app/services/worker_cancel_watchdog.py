from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from threading import Event, Thread
from typing import Any, Callable

from app.services import jobs


_INSTALLED = False
_FORCE_EXIT: Callable[[int], Any] = os._exit


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _grace_seconds() -> int:
    raw = os.getenv("AGENT_CANCEL_FORCE_EXIT_SECONDS", "20")
    try:
        value = int(raw)
    except ValueError:
        value = 20
    return max(5, min(120, value))


def _poll_seconds() -> float:
    raw = os.getenv("AGENT_CANCEL_WATCHDOG_POLL_SECONDS", "1")
    try:
        value = float(raw)
    except ValueError:
        value = 1.0
    return max(0.2, min(5.0, value))


def _mark_job_cancelled(job_id: str, settings: Any, detail: str) -> None:
    client = jobs._redis(settings)
    current = jobs.get_job(job_id, settings=settings) or {"job_id": job_id}
    cancelled_at = _now()
    phase = {
        **dict(current.get("current_phase") or {}),
        "stage": str((current.get("current_phase") or {}).get("stage") or "evidence_analysis"),
        "status": "cancelled",
        "detail": detail,
        "updated_at": cancelled_at,
    }
    payload = {
        **current,
        "job_id": job_id,
        "status": "cancelled",
        "error": None,
        "cancelled_at": cancelled_at,
        "completed_at": cancelled_at,
        "updated_at": cancelled_at,
        "current_phase": phase,
    }
    jobs._store(client, settings, job_id, payload)


def _watch(job_id: str, settings: Any, finished: Event) -> None:
    poll = _poll_seconds()
    requested_at: float | None = None
    grace = _grace_seconds()

    while not finished.wait(poll):
        try:
            requested = jobs.job_cancel_requested(job_id, settings=settings)
        except Exception:
            continue
        if not requested:
            requested_at = None
            continue
        if requested_at is None:
            requested_at = time.monotonic()
            continue
        if time.monotonic() - requested_at < grace:
            continue

        detail = (
            f"Cancelamento forçado após {grace}s: o worker não encerrou a operação atual "
            "dentro do período de tolerância."
        )
        try:
            _mark_job_cancelled(job_id, settings, detail)
        except Exception as exc:
            print(
                f"[agent-worker] falha ao persistir cancelamento forçado de {job_id}: {exc}",
                file=sys.stderr,
                flush=True,
            )
        print(
            f"[agent-worker] {detail} Job {job_id}. Reinício controlado do processo.",
            file=sys.stderr,
            flush=True,
        )
        _FORCE_EXIT(130)
        return


def install_worker_cancel_watchdog() -> None:
    """Reinicia o processo se uma coleta ignorar o cancelamento por tempo excessivo.

    O serviço systemd usa Restart=on-failure. Antes da saída forçada, o estado do
    job é persistido como cancelado para que a interface não permaneça presa em
    `cancelling`.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    original = jobs._execute_job
    if getattr(original, "__agent_cancel_watchdog__", False):
        _INSTALLED = True
        return

    def wrapped(job: dict[str, Any], *, settings: Any) -> dict[str, Any]:
        job_id = str(job.get("job_id") or "")
        if not job_id:
            return original(job, settings=settings)

        finished = Event()
        watcher = Thread(
            target=_watch,
            args=(job_id, settings, finished),
            name=f"agent-cancel-watchdog-{job_id[:8]}",
            daemon=True,
        )
        watcher.start()
        try:
            return original(job, settings=settings)
        finally:
            finished.set()

    setattr(wrapped, "__agent_cancel_watchdog__", True)
    jobs._execute_job = wrapped
    _INSTALLED = True
