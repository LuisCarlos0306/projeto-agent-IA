from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from functools import wraps
from typing import Any

from app.services import jobs
from app.services.worker_cancel_watchdog import _hard_timeout_seconds


_INSTALLED = False
_TERMINAL = {"completed", "failed", "cancelled"}


def _cancel_grace_seconds() -> int:
    try:
        return max(2, min(int(os.getenv("AGENT_CANCEL_FORCE_EXIT_SECONDS", "20")), 120))
    except ValueError:
        return 20


def _terminate_process_group(process: subprocess.Popen[str], grace_seconds: float = 3.0) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=max(0.2, grace_seconds))
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        pass


def _store_terminal(
    job: dict[str, Any],
    settings: Any,
    *,
    status: str,
    detail: str,
) -> dict[str, Any]:
    job_id = str(job.get("job_id") or "")
    current = jobs.get_job(job_id, settings=settings) or {"job_id": job_id}
    now = jobs._now()
    payload = {
        **current,
        "job_id": job_id,
        "status": status,
        "completed_at": now,
        "updated_at": now,
        "error": detail if status == "failed" else None,
        "current_phase": {
            **dict(current.get("current_phase") or {}),
            "stage": status,
            "status": status,
            "detail": detail,
            "percent": int(current.get("percent") or 0),
            "updated_at": now,
        },
    }
    if status == "cancelled":
        payload["cancelled_at"] = now
    client = jobs._redis(settings)
    jobs._store(client, settings, job_id, payload)
    client.delete(jobs._cancel_key(settings, job_id))
    return payload


def install_job_process_guard() -> None:
    """Executa cada job em processo isolado e mata travamentos de forma definitiva.

    O worker pai nunca executa SSH ou chamadas de IA diretamente. Cada job roda
    em um novo grupo de processos. O pai monitora timeout total e cancelamento;
    se o filho não sair no prazo, todo o grupo recebe SIGTERM e depois SIGKILL.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    original = jobs._execute_job
    if getattr(original, "__agent_process_guard__", False):
        _INSTALLED = True
        return

    @wraps(original)
    def guarded(job: dict[str, Any], *, settings: Any) -> dict[str, Any]:
        timeout = max(30, int(_hard_timeout_seconds()))
        cancel_grace = _cancel_grace_seconds()
        job_id = str(job.get("job_id") or "desconhecido")
        process = subprocess.Popen(
            [sys.executable, "-m", "app.job_child"],
            stdin=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            if process.stdin is None:
                raise RuntimeError("stdin do processo isolado indisponível")
            process.stdin.write(json.dumps(job, ensure_ascii=False, default=str))
            process.stdin.close()
        except BaseException:
            _terminate_process_group(process)
            raise

        deadline = time.monotonic() + timeout
        cancel_seen_at: float | None = None

        while process.poll() is None:
            now = time.monotonic()

            if jobs.job_cancel_requested(job_id, settings=settings):
                cancel_seen_at = cancel_seen_at or now
                if now - cancel_seen_at >= cancel_grace:
                    _terminate_process_group(process)
                    return _store_terminal(
                        job,
                        settings,
                        status="cancelled",
                        detail=(
                            f"Cancelamento forçado: investigação {job_id} não encerrou em "
                            f"{cancel_grace}s e o processo travado foi finalizado automaticamente."
                        ),
                    )

            if now >= deadline:
                _terminate_process_group(process)
                return _store_terminal(
                    job,
                    settings,
                    status="failed",
                    detail=(
                        f"Timeout operacional: investigação {job_id} foi encerrada à força após {timeout}s. "
                        "O processo SSH/IA travado foi finalizado automaticamente."
                    ),
                )

            time.sleep(0.25)

        current = jobs.get_job(job_id, settings=settings)
        if current and str(current.get("status") or "") in _TERMINAL:
            return current
        if process.returncode == 0 and current:
            return current
        return _store_terminal(
            job,
            settings,
            status="failed",
            detail=(
                f"O processo isolado da investigação {job_id} encerrou inesperadamente "
                f"com código {process.returncode}."
            ),
        )

    setattr(guarded, "__agent_process_guard__", True)
    jobs._execute_job = guarded
    _INSTALLED = True
