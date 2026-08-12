from __future__ import annotations

import json
import socket
import uuid
from typing import Any

from app.core.policies import EnvironmentType
from app.core.settings import Settings, get_settings
from app.services.cancellation import ExecutionCancelled, raise_if_cancelled, use_cancellation
from app.services.custom_skill_runner import run_custom_skill
from app.services.progress import use_progress
from app.services.redaction import redact_object


def enqueue_custom_skill(
    skill_id: str,
    reference: str,
    *,
    metadata: dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    from app.services import jobs

    settings = settings or get_settings()
    job_id = str(uuid.uuid4())
    created_at = jobs._now()
    skill_key = f"custom:{skill_id}"
    job = {
        "job_id": job_id,
        "job_type": "skill",
        "skill": skill_key,
        "reference": reference,
        "environment": EnvironmentType.UNKNOWN.value,
        "ssh_port": None,
        "metadata": redact_object(metadata or {}),
        "created_at": created_at,
    }
    queued = {
        "job_id": job_id,
        "job_type": "skill",
        "skill": skill_key,
        "status": "queued",
        "created_at": created_at,
        "percent": 0,
        "current_phase": {
            "stage": "worker_wait",
            "status": "running",
            "detail": "Aguardando worker para executar a skill personalizada.",
            "percent": 0,
            "updated_at": created_at,
        },
        "events": [],
    }
    client = jobs._redis(settings)
    jobs._store(client, settings, job_id, queued)
    client.rpush(settings.agent_queue_name, json.dumps(job, ensure_ascii=False, default=str))
    return {**queued, "queue": settings.agent_queue_name, "worker_pool": settings.agent_worker_name}


def _execute_custom_job(job: dict[str, Any], *, settings: Settings) -> dict[str, Any]:
    from app.services import jobs

    job_id = str(job["job_id"])
    skill_key = str(job.get("skill") or "")
    skill_id = skill_key.split(":", 1)[1] if ":" in skill_key else ""
    client = jobs._redis(settings)
    worker = f"{settings.agent_worker_name}@{socket.gethostname()}"
    started_at = jobs._now()
    jobs._store(
        client,
        settings,
        job_id,
        {
            "job_id": job_id,
            "job_type": "skill",
            "skill": skill_key,
            "status": "running",
            "worker": worker,
            "started_at": started_at,
            "updated_at": started_at,
            "percent": 4,
            "events": [],
        },
    )
    try:
        with use_progress(lambda event: jobs._job_phase(client, settings, job_id, event)), use_cancellation(
            lambda: jobs.job_cancel_requested(job_id, settings=settings)
        ):
            raise_if_cancelled("Job cancelado antes de iniciar a skill personalizada.")
            result = run_custom_skill(
                skill_id,
                str(job.get("reference") or ""),
                environment=EnvironmentType.UNKNOWN,
                ssh_port=None,
                settings=settings,
            )
            raise_if_cancelled("Job cancelado antes da persistência final.")
        current = jobs.get_job(job_id, settings=settings) or {}
        payload = {
            **current,
            "job_id": job_id,
            "job_type": "skill",
            "skill": skill_key,
            "status": "completed",
            "worker": worker,
            "completed_at": jobs._now(),
            "percent": 100,
            "result": result,
        }
        jobs._store(client, settings, job_id, payload)
        return payload
    except ExecutionCancelled as exc:
        current = jobs.get_job(job_id, settings=settings) or {}
        cancelled_at = jobs._now()
        payload = {
            **current,
            "job_id": job_id,
            "job_type": "skill",
            "skill": skill_key,
            "status": "cancelled",
            "worker": worker,
            "cancelled_at": cancelled_at,
            "completed_at": cancelled_at,
            "error": None,
            "current_phase": {
                **dict(current.get("current_phase") or {}),
                "status": "cancelled",
                "detail": str(exc) or "Skill personalizada cancelada pelo operador.",
                "updated_at": cancelled_at,
            },
        }
        jobs._store(client, settings, job_id, payload)
        return payload
    except Exception as exc:
        current = jobs.get_job(job_id, settings=settings) or {}
        payload = {
            **current,
            "job_id": job_id,
            "job_type": "skill",
            "skill": skill_key,
            "status": "failed",
            "worker": worker,
            "completed_at": jobs._now(),
            "error": f"{type(exc).__name__}: {exc}",
        }
        jobs._store(client, settings, job_id, payload)
        return payload


def install_custom_skill_jobs() -> None:
    from app.services import jobs

    if getattr(jobs, "_custom_skill_jobs_installed", False):
        return
    original = jobs._execute_job

    def dispatch(job: dict[str, Any], *, settings: Settings) -> dict[str, Any]:
        if str(job.get("job_type") or "") == "skill" and str(job.get("skill") or "").startswith("custom:"):
            return _execute_custom_job(job, settings=settings)
        return original(job, settings=settings)

    jobs._execute_job = dispatch
    jobs._custom_skill_jobs_installed = True
