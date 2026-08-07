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


def _mark_failed(job: dict[str, Any], settings: Any, detail: str) -> dict[str, Any]:
    job_id = str(job.get("job_id") or "")
    current = jobs.get_job(job_id, settings=settings) or {"job_id": job_id}
    now = jobs._now()
    payload = {
        **current,
        "job_id": job_id,
        "status": "failed",
        "completed_at": now,
        "updated_at": now,
        "error": detail,
        "current_phase": {
            **dict(current.get("current_phase") or {}),
            "stage": "failed",
            "status": "failed",
            "detail": detail,
            "percent": int(current.get("percent") or 0),
            "updated_at": now,
        },
    }
    client = jobs._redis(settings)
    jobs._store(client, settings, job_id, payload)
    client.delete(jobs._cancel_key(settings, job_id))
    return payload


def install_job_process_guard() -> None:
    """Executa cada job em um processo isolado e mata travamentos de forma definitiva.

    O worker pai nunca executa SSH ou chamadas de IA diretamente. Ele cria um
    processo filho em um novo grupo de processos, aguarda o limite operacional e,
    se necessário, envia SIGTERM seguido de SIGKILL para todo o grupo. Isso também
    encerra bibliotecas nativas ou subprocessos que não respeitem timeouts Python.
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
        job_id = str(job.get("job_id") or "desconhecido")
        command = [sys.executable, "-m", "app.job_child"]
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            process.communicate(
                input=json.dumps(job, ensure_ascii=False, default=str),
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            _terminate_process_group(process)
            return _mark_failed(
                job,
                settings,
                f"Timeout operacional: investigação {job_id} foi encerrada à força após {timeout}s. "
                "O processo SSH/IA travado foi finalizado automaticamente.",
            )
        except BaseException:
            _terminate_process_group(process)
            raise

        current = jobs.get_job(job_id, settings=settings)
        if process.returncode == 0 and current:
            return current
        if current and str(current.get("status") or "") in {"completed", "failed", "cancelled"}:
            return current
        return _mark_failed(
            job,
            settings,
            f"O processo isolado da investigação {job_id} encerrou inesperadamente "
            f"com código {process.returncode}.",
        )

    setattr(guarded, "__agent_process_guard__", True)
    jobs._execute_job = guarded
    _INSTALLED = True
