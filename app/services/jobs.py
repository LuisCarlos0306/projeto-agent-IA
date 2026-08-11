from __future__ import annotations

import json
import socket
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from redis import Redis

from app.core.policies import EnvironmentType
from app.core.settings import Settings, get_settings
from app.services.backup_validation import run_backup_validation
from app.services.cancellation import ExecutionCancelled, raise_if_cancelled, use_cancellation
from app.services.progress import use_progress
from app.services.redaction import redact_object
from app.services.tracked_runner import run_target_tracked


class JobError(RuntimeError):
    pass


_MAX_JOB_EVENTS = 300


def _redis(settings: Settings) -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)


def _result_key(settings: Settings, job_id: str) -> str:
    return f"{settings.agent_result_prefix}{job_id}"


def _cancel_key(settings: Settings, job_id: str) -> str:
    return f"{settings.agent_result_prefix}{job_id}:cancel"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _store(client: Redis, settings: Settings, job_id: str, payload: dict[str, Any]) -> None:
    client.setex(
        _result_key(settings, job_id),
        max(60, int(settings.agent_job_ttl_seconds)),
        json.dumps(redact_object(payload), ensure_ascii=False, default=str),
    )


def _default_provider(settings: Settings) -> str:
    return str(getattr(settings, "ai_provider", "gemini") or "gemini").strip().lower()


def enqueue_investigation(
    reference: str,
    objective: str,
    *,
    environment: EnvironmentType = EnvironmentType.UNKNOWN,
    mode: str = "propose",
    approve: bool = False,
    ssh_port: int | None = None,
    provider_name: str | None = None,
    model_name: str | None = None,
    playbook_mode: str = "auto",
    playbook_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    if mode == "correct" and approve:
        approve = False
        mode = "propose"
    job_id = str(uuid.uuid4())
    selection = {
        "provider": (provider_name or _default_provider(settings)).strip().lower(),
        "model": (model_name or "").strip(),
        "playbook_mode": (playbook_mode or "auto").strip().lower(),
        "playbook_id": (playbook_id or "").strip() or None,
    }
    job = {
        "job_id": job_id,
        "job_type": "investigation",
        "reference": reference,
        "objective": objective,
        "environment": environment.value,
        "mode": mode,
        "approve": approve,
        "ssh_port": ssh_port,
        **selection,
        "metadata": redact_object(metadata or {}),
        "created_at": _now(),
    }
    client = _redis(settings)
    queued = {
        "job_id": job_id,
        "job_type": "investigation",
        "status": "queued",
        "created_at": job["created_at"],
        "percent": 0,
        "current_phase": {
            "stage": "worker_wait",
            "status": "running",
            "detail": "Aguardando worker operacional disponível.",
            "percent": 0,
            "updated_at": job["created_at"],
        },
        "events": [],
        **selection,
    }
    _store(client, settings, job_id, queued)
    client.rpush(settings.agent_queue_name, json.dumps(job, ensure_ascii=False, default=str))
    return {
        **queued,
        "queue": settings.agent_queue_name,
        "worker_pool": settings.agent_worker_name,
    }


def enqueue_backup_validation(
    reference: str,
    *,
    mount_point: str,
    backup_path: str,
    redundancy_path: str | None = None,
    environment: EnvironmentType = EnvironmentType.UNKNOWN,
    ssh_port: int | None = None,
    min_free_percent: int = 20,
    max_backup_age_hours: int = 30,
    retention_days: int = 7,
    min_restore_points: int = 1,
    metadata: dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    job_id = str(uuid.uuid4())
    created_at = _now()
    skill_payload = {
        "mount_point": mount_point,
        "backup_path": backup_path,
        "redundancy_path": redundancy_path,
        "min_free_percent": int(min_free_percent),
        "max_backup_age_hours": int(max_backup_age_hours),
        "retention_days": int(retention_days),
        "min_restore_points": int(min_restore_points),
    }
    job = {
        "job_id": job_id,
        "job_type": "skill",
        "skill": "backup_validation",
        "reference": reference,
        "environment": environment.value,
        "ssh_port": ssh_port,
        "skill_payload": skill_payload,
        "metadata": redact_object(metadata or {}),
        "created_at": created_at,
    }
    queued = {
        "job_id": job_id,
        "job_type": "skill",
        "skill": "backup_validation",
        "status": "queued",
        "created_at": created_at,
        "percent": 0,
        "current_phase": {
            "stage": "worker_wait",
            "status": "running",
            "detail": "Aguardando worker operacional para executar a Backup Validation.",
            "percent": 0,
            "updated_at": created_at,
        },
        "events": [],
    }
    client = _redis(settings)
    _store(client, settings, job_id, queued)
    client.rpush(settings.agent_queue_name, json.dumps(job, ensure_ascii=False, default=str))
    return {
        **queued,
        "queue": settings.agent_queue_name,
        "worker_pool": settings.agent_worker_name,
    }


def get_job(job_id: str, *, settings: Settings | None = None) -> dict[str, Any] | None:
    settings = settings or get_settings()
    value = _redis(settings).get(_result_key(settings, job_id))
    if not value:
        return None
    payload = json.loads(value)
    return payload if isinstance(payload, dict) else None


def job_cancel_requested(job_id: str, *, settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return bool(_redis(settings).get(_cancel_key(settings, job_id)))


def _job_phase(client: Redis, settings: Settings, job_id: str, event: dict[str, Any]) -> None:
    current = get_job(job_id, settings=settings) or {"job_id": job_id, "status": "running"}
    phase = {
        **event,
        "stage": str(event.get("stage") or "processing"),
        "status": str(event.get("status") or "running"),
        "detail": str(event.get("detail") or ""),
        "percent": max(int(current.get("percent") or 0), int(event.get("percent") or 0)),
        "updated_at": str(event.get("updated_at") or _now()),
        "event_id": str(event.get("event_id") or uuid.uuid4()),
    }
    events = list(current.get("events") or [])
    events.append(phase)
    events = events[-_MAX_JOB_EVENTS:]
    status = "cancelling" if current.get("status") == "cancelling" or job_cancel_requested(job_id, settings=settings) else "running"
    payload = {
        **current,
        "job_id": job_id,
        "status": status,
        "percent": phase["percent"],
        "current_phase": phase,
        "events": events,
        "updated_at": phase["updated_at"],
    }
    _store(client, settings, job_id, payload)


def cancel_job(job_id: str, *, settings: Settings | None = None) -> dict[str, Any] | None:
    settings = settings or get_settings()
    client = _redis(settings)
    current = get_job(job_id, settings=settings)
    if not current:
        return None
    if current.get("status") in {"completed", "failed", "cancelled"}:
        return current

    requested_at = _now()
    client.setex(
        _cancel_key(settings, job_id),
        max(60, int(settings.agent_job_ttl_seconds)),
        "1",
    )

    removed = 0
    if current.get("status") == "queued" and hasattr(client, "lrange") and hasattr(client, "lrem"):
        for raw in client.lrange(settings.agent_queue_name, 0, -1):
            try:
                payload = json.loads(raw)
            except Exception:
                continue
            if str(payload.get("job_id") or "") == str(job_id):
                removed += int(client.lrem(settings.agent_queue_name, 1, raw) or 0)
                break

    if removed:
        cancelled = {
            **current,
            "status": "cancelled",
            "cancel_requested_at": requested_at,
            "cancelled_at": requested_at,
            "completed_at": requested_at,
            "current_phase": {
                "stage": "worker_wait",
                "status": "cancelled",
                "detail": "Job removido da fila antes de iniciar.",
                "percent": int(current.get("percent") or 0),
                "updated_at": requested_at,
            },
        }
        _store(client, settings, job_id, cancelled)
        return cancelled

    cancelling = {
        **current,
        "status": "cancelling",
        "cancel_requested_at": requested_at,
        "updated_at": requested_at,
    }
    _store(client, settings, job_id, cancelling)
    return cancelling


def _execute_job(job: dict[str, Any], *, settings: Settings) -> dict[str, Any]:
    job_id = str(job["job_id"])
    client = _redis(settings)
    worker = f"{settings.agent_worker_name}@{socket.gethostname()}"
    job_type = str(job.get("job_type") or "investigation")
    skill = str(job.get("skill") or "")
    selection = {
        "provider": str(job.get("provider") or _default_provider(settings)),
        "model": str(job.get("model") or ""),
        "playbook_mode": str(job.get("playbook_mode") or "auto"),
        "playbook_id": job.get("playbook_id"),
    }
    job_identity = {"job_type": job_type}
    if skill:
        job_identity["skill"] = skill
    started_at = _now()
    _store(
        client,
        settings,
        job_id,
        {
            "job_id": job_id,
            **job_identity,
            "status": "running",
            "worker": worker,
            "started_at": started_at,
            "updated_at": started_at,
            "percent": 4,
            "events": [],
            **({} if job_type == "skill" else selection),
        },
    )
    try:
        environment = EnvironmentType(job.get("environment") or EnvironmentType.UNKNOWN.value)
        with use_progress(lambda event: _job_phase(client, settings, job_id, event)), use_cancellation(
            lambda: job_cancel_requested(job_id, settings=settings)
        ):
            raise_if_cancelled("Job cancelado antes de iniciar a coleta.")
            if job_type == "skill":
                if skill != "backup_validation":
                    raise JobError(f"skill de worker não suportada: {skill or 'não informada'}")
                skill_payload = dict(job.get("skill_payload") or {})
                result = run_backup_validation(
                    str(job["reference"]),
                    mount_point=str(skill_payload.get("mount_point") or ""),
                    backup_path=str(skill_payload.get("backup_path") or ""),
                    redundancy_path=skill_payload.get("redundancy_path"),
                    environment=environment,
                    ssh_port=job.get("ssh_port"),
                    min_free_percent=int(skill_payload.get("min_free_percent") or 20),
                    max_backup_age_hours=int(skill_payload.get("max_backup_age_hours") or 30),
                    retention_days=int(skill_payload.get("retention_days") or 7),
                    min_restore_points=int(skill_payload.get("min_restore_points") or 1),
                    settings=settings,
                )
            else:
                result = run_target_tracked(
                    str(job["reference"]),
                    str(job.get("objective") or ""),
                    environment=environment,
                    mode=str(job.get("mode") or "propose"),
                    approve=bool(job.get("approve", False)),
                    ssh_port=job.get("ssh_port"),
                    provider_name=selection["provider"],
                    model_name=selection["model"] or None,
                    playbook_mode=selection["playbook_mode"],
                    playbook_id=selection["playbook_id"],
                    settings=settings,
                )
            raise_if_cancelled("Job cancelado antes da persistência final.")
        current = get_job(job_id, settings=settings) or {}
        payload = {
            **current,
            "job_id": job_id,
            **job_identity,
            "status": "completed",
            "worker": worker,
            "completed_at": _now(),
            "percent": 100,
            "investigation_id": result.get("investigation_id"),
            "result": result,
            **({} if job_type == "skill" else selection),
        }
        _store(client, settings, job_id, payload)
        return payload
    except ExecutionCancelled as exc:
        current = get_job(job_id, settings=settings) or {}
        cancelled_at = _now()
        payload = {
            **current,
            "job_id": job_id,
            **job_identity,
            "status": "cancelled",
            "worker": worker,
            "cancelled_at": cancelled_at,
            "completed_at": cancelled_at,
            "error": None,
            "current_phase": {
                **dict(current.get("current_phase") or {}),
                "status": "cancelled",
                "detail": str(exc) or "Coleta cancelada pelo operador.",
                "updated_at": cancelled_at,
            },
            **({} if job_type == "skill" else selection),
        }
        _store(client, settings, job_id, payload)
        return payload
    except Exception as exc:
        current = get_job(job_id, settings=settings) or {}
        payload = {
            **current,
            "job_id": job_id,
            **job_identity,
            "status": "failed",
            "worker": worker,
            "completed_at": _now(),
            "error": f"{type(exc).__name__}: {exc}",
            **({} if job_type == "skill" else selection),
        }
        _store(client, settings, job_id, payload)
        return payload


def run_worker_once(
    *,
    settings: Settings | None = None,
    block_seconds: int | None = None,
) -> dict[str, Any] | None:
    settings = settings or get_settings()
    timeout = settings.agent_queue_block_seconds if block_seconds is None else block_seconds
    item = _redis(settings).blpop(settings.agent_queue_name, timeout=max(0, int(timeout)))
    if not item:
        return None
    _, raw = item
    try:
        job = json.loads(raw)
        if not isinstance(job, dict) or not job.get("job_id"):
            raise JobError("job inválido")
    except Exception as exc:
        raise JobError(f"não foi possível decodificar o job: {exc}") from exc
    return _execute_job(job, settings=settings)


def worker_loop(*, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    while True:
        try:
            run_worker_once(settings=settings)
        except KeyboardInterrupt:
            return
        except Exception:
            time.sleep(2)
