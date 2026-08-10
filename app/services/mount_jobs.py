from __future__ import annotations

import json
import socket
import uuid
from datetime import datetime, timezone
from typing import Any

from redis import Redis

from app.core.policies import EnvironmentType
from app.core.settings import Settings, get_settings
from app.services.mount_ops import MountOperationError, recover_mount, validate_mount
from app.services.redaction import redact_object


MOUNT_VALIDATION_JOB = "mount_validation"
MOUNT_RECOVERY_JOB = "mount_recovery"
_MOUNT_JOB_TYPES = {MOUNT_VALIDATION_JOB, MOUNT_RECOVERY_JOB}


def _redis(settings: Settings) -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)


def _result_key(settings: Settings, job_id: str) -> str:
    return f"{settings.agent_result_prefix}{job_id}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _store(client: Redis, settings: Settings, job_id: str, payload: dict[str, Any]) -> None:
    client.setex(
        _result_key(settings, job_id),
        max(60, int(settings.agent_job_ttl_seconds)),
        json.dumps(redact_object(payload), ensure_ascii=False, default=str),
    )


def _enqueue(payload: dict[str, Any], *, settings: Settings) -> dict[str, Any]:
    job_id = str(payload["job_id"])
    queued = {
        "job_id": job_id,
        "job_type": payload["job_type"],
        "status": "queued",
        "created_at": payload["created_at"],
        "percent": 0,
        "current_phase": {
            "stage": "worker_wait",
            "status": "running",
            "detail": "Aguardando worker operacional disponível.",
            "percent": 0,
            "updated_at": payload["created_at"],
        },
    }
    client = _redis(settings)
    _store(client, settings, job_id, queued)
    client.rpush(settings.agent_queue_name, json.dumps(redact_object(payload), ensure_ascii=False))
    return {
        **queued,
        "queue": settings.agent_queue_name,
        "worker_pool": settings.agent_worker_name,
    }


def enqueue_mount_validation(
    reference: str,
    path: str,
    *,
    environment: EnvironmentType = EnvironmentType.UNKNOWN,
    ssh_port: int | None = None,
    requested_by: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    payload = {
        "job_id": str(uuid.uuid4()),
        "job_type": MOUNT_VALIDATION_JOB,
        "reference": str(reference).strip(),
        "path": str(path).strip(),
        "environment": environment.value,
        "ssh_port": ssh_port,
        "requested_by": requested_by,
        "created_at": _now(),
    }
    return _enqueue(payload, settings=settings)


def get_mount_job(job_id: str, *, settings: Settings | None = None) -> dict[str, Any] | None:
    settings = settings or get_settings()
    value = _redis(settings).get(_result_key(settings, job_id))
    if not value:
        return None
    payload = json.loads(value)
    if not isinstance(payload, dict):
        return None
    if payload.get("job_type") not in _MOUNT_JOB_TYPES:
        return None
    return payload


def _validated_request_source(
    validation_job_id: str,
    *,
    settings: Settings,
) -> dict[str, Any]:
    current = get_mount_job(validation_job_id, settings=settings)
    if not current or current.get("job_type") != MOUNT_VALIDATION_JOB:
        raise MountOperationError("validação de mount não encontrada")
    if current.get("status") != "completed":
        raise MountOperationError("a validação de mount ainda não foi concluída")
    result = current.get("result")
    if not isinstance(result, dict):
        raise MountOperationError("resultado da validação de mount é inválido")
    if result.get("mounted"):
        raise MountOperationError("a unidade já está montada")
    if not result.get("can_request_mount"):
        raise MountOperationError(str(result.get("reason") or "montagem não autorizada"))
    return result


def enqueue_mount_recovery(
    validation_job_id: str,
    *,
    confirmed: bool,
    requested_by: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    if not confirmed:
        raise MountOperationError("confirmação explícita é obrigatória para solicitar a montagem")
    source = _validated_request_source(validation_job_id, settings=settings)
    payload = {
        "job_id": str(uuid.uuid4()),
        "job_type": MOUNT_RECOVERY_JOB,
        "validation_job_id": validation_job_id,
        "reference": str(source["target"]),
        "path": str(source["path"]),
        "environment": str(source["environment"]),
        "ssh_port": int(source["ssh_port"]) if source.get("ssh_port") is not None else None,
        "requested_by": requested_by,
        "confirmed": True,
        "created_at": _now(),
    }
    return _enqueue(payload, settings=settings)


def is_mount_job(job: dict[str, Any]) -> bool:
    return str(job.get("job_type") or "") in _MOUNT_JOB_TYPES


def execute_mount_job(job: dict[str, Any], *, settings: Settings) -> dict[str, Any]:
    job_id = str(job.get("job_id") or "")
    if not job_id:
        raise MountOperationError("job de mount sem identificador")
    client = _redis(settings)
    worker = f"{settings.agent_worker_name}@{socket.gethostname()}"
    started_at = _now()
    job_type = str(job.get("job_type") or "")
    running = {
        "job_id": job_id,
        "job_type": job_type,
        "status": "running",
        "worker": worker,
        "started_at": started_at,
        "updated_at": started_at,
        "percent": 15,
        "current_phase": {
            "stage": "mount_validation" if job_type == MOUNT_VALIDATION_JOB else "mount_recovery",
            "status": "running",
            "detail": "Validando unidade." if job_type == MOUNT_VALIDATION_JOB else "Executando montagem autorizada.",
            "percent": 15,
            "updated_at": started_at,
        },
    }
    _store(client, settings, job_id, running)

    try:
        environment = EnvironmentType(str(job.get("environment") or EnvironmentType.UNKNOWN.value))
        common = {
            "environment": environment,
            "ssh_port": job.get("ssh_port"),
            "settings": settings,
        }
        if job_type == MOUNT_VALIDATION_JOB:
            result = validate_mount(
                str(job.get("reference") or ""),
                str(job.get("path") or ""),
                **common,
            )
        elif job_type == MOUNT_RECOVERY_JOB:
            if not bool(job.get("confirmed")):
                raise MountOperationError("job de montagem sem confirmação explícita")
            result = recover_mount(
                str(job.get("reference") or ""),
                str(job.get("path") or ""),
                **common,
            )
        else:
            raise MountOperationError(f"tipo de job de mount desconhecido: {job_type}")

        completed_at = _now()
        payload = {
            **running,
            "status": "completed",
            "percent": 100,
            "completed_at": completed_at,
            "updated_at": completed_at,
            "result": redact_object(result),
            "current_phase": {
                "stage": job_type,
                "status": "completed",
                "detail": "Validação concluída." if job_type == MOUNT_VALIDATION_JOB else "Solicitação de montagem concluída.",
                "percent": 100,
                "updated_at": completed_at,
            },
        }
        _store(client, settings, job_id, payload)
        return payload
    except Exception as exc:
        failed_at = _now()
        payload = {
            **running,
            "status": "failed",
            "percent": 100,
            "completed_at": failed_at,
            "updated_at": failed_at,
            "error": f"{type(exc).__name__}: {exc}",
            "current_phase": {
                "stage": job_type,
                "status": "failed",
                "detail": str(exc),
                "percent": 100,
                "updated_at": failed_at,
            },
        }
        _store(client, settings, job_id, payload)
        return payload
