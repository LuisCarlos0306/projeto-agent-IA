from __future__ import annotations

import json
import socket
import uuid
from datetime import datetime, timezone
from typing import Any

from redis import Redis
from sqlalchemy import select

from app.core.policies import EnvironmentType
from app.core.settings import Settings, get_settings
from app.db.base import SessionLocal
from app.db.models import HostORM, InvestigationORM
from app.services.mount_ops import MountOperationError, recover_mount, remount_mount, validate_mount
from app.services.redaction import redact_object, redact_text


MOUNT_VALIDATION_JOB = "mount_validation"
MOUNT_RECOVERY_JOB = "mount_recovery"
MOUNT_REMOUNT_JOB = "mount_remount"
_MOUNT_JOB_TYPES = {MOUNT_VALIDATION_JOB, MOUNT_RECOVERY_JOB, MOUNT_REMOUNT_JOB}


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


def _validation_result(validation_job_id: str, *, settings: Settings) -> dict[str, Any]:
    current = get_mount_job(validation_job_id, settings=settings)
    if not current or current.get("job_type") != MOUNT_VALIDATION_JOB:
        raise MountOperationError("validação de mount não encontrada")
    if current.get("status") != "completed":
        raise MountOperationError("a validação de mount ainda não foi concluída")
    result = current.get("result")
    if not isinstance(result, dict):
        raise MountOperationError("resultado da validação de mount é inválido")
    return result


def _validated_request_source(validation_job_id: str, *, settings: Settings) -> dict[str, Any]:
    result = _validation_result(validation_job_id, settings=settings)
    if result.get("mounted"):
        raise MountOperationError("a unidade já está montada")
    if not result.get("can_request_mount"):
        raise MountOperationError(str(result.get("reason") or "montagem não autorizada"))
    return result


def _validated_remount_source(validation_job_id: str, *, settings: Settings) -> dict[str, Any]:
    result = _validation_result(validation_job_id, settings=settings)
    if not result.get("mounted"):
        raise MountOperationError("a unidade não está montada; use o fluxo de montagem")
    if str(result.get("health") or "") != "hanging":
        raise MountOperationError("a remontagem só pode ser solicitada após detecção de estado Hanging")
    if not result.get("can_request_remount"):
        raise MountOperationError(str(result.get("remount_reason") or "remontagem não autorizada"))
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


def enqueue_mount_remount(
    validation_job_id: str,
    *,
    confirmed: bool,
    requested_by: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    if not confirmed:
        raise MountOperationError("confirmação explícita é obrigatória para solicitar a remontagem")
    source = _validated_remount_source(validation_job_id, settings=settings)
    payload = {
        "job_id": str(uuid.uuid4()),
        "job_type": MOUNT_REMOUNT_JOB,
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


def _duration_ms(started_at: datetime) -> int:
    return max(0, int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000))


def _mount_activity_document(
    job_type: str,
    result: dict[str, Any],
    *,
    duration_ms: int,
) -> dict[str, Any]:
    sanitized = redact_object(result)
    safe_result = dict(sanitized) if isinstance(sanitized, dict) else {}
    path = str(safe_result.get("path") or "").strip()
    target = str(safe_result.get("target") or safe_result.get("resolved_host") or "").strip()
    environment = str(safe_result.get("environment") or EnvironmentType.UNKNOWN.value)
    mounted = bool(safe_result.get("mounted"))
    after = safe_result.get("after") if isinstance(safe_result.get("after"), dict) else {}
    source = safe_result.get("source") or after.get("source")
    fstype = safe_result.get("fstype") or after.get("fstype")
    cron_user = safe_result.get("cron_user") or safe_result.get("execution_user")
    reason = str(safe_result.get("reason") or "").strip()
    health = str(safe_result.get("health") or after.get("health") or ("healthy" if mounted else "unmounted"))
    usage_raw = safe_result.get("usage_percent")
    if usage_raw is None:
        usage_raw = after.get("usage_percent")
    try:
        usage_percent = int(usage_raw) if usage_raw is not None else None
    except (TypeError, ValueError):
        usage_percent = None

    healthy_mount = bool(mounted and health == "healthy")
    capacity_attention = usage_percent is not None and usage_percent >= 90

    if job_type == MOUNT_REMOUNT_JOB:
        title = "Remontagem preventiva"
        objective = f"Remontar ponto Hanging e revalidar {path}"
        if healthy_mount:
            summary = f"O ponto {path} foi desmontado sem force/lazy, montado novamente pelo script padrão e está saudável."
            probable_cause = "O estado Hanging foi eliminado após a remontagem controlada."
        elif mounted:
            summary = f"O ponto {path} permanece montado, porém a saúde após a remontagem é {health}."
            probable_cause = "A remontagem não restabeleceu resposta saudável do filesystem; é necessária análise operacional."
        else:
            summary = f"A remontagem de {path} não restabeleceu o ponto de montagem."
            probable_cause = "A rotina controlada não restabeleceu o filesystem; é necessária análise operacional."
    elif job_type == MOUNT_RECOVERY_JOB:
        title = "Montagem preventiva"
        objective = f"Executar montagem preventiva e revalidar {path}"
        summary = (
            f"A montagem preventiva de {path} foi concluída e o ponto está saudável."
            if healthy_mount
            else f"A rotina de montagem foi executada, mas a saúde final de {path} é {health}."
        )
        probable_cause = (
            "Nenhuma falha de montagem permaneceu após a execução autorizada."
            if healthy_mount
            else "A rotina padrão não restabeleceu um estado saudável; é necessária análise operacional."
        )
    else:
        title = "Validação de mount"
        objective = f"Validar ponto de montagem e saúde de {path}"
        if not mounted:
            summary = f"O ponto de montagem {path} foi validado como não montado."
            probable_cause = reason or "O ponto de montagem não está ativo no momento da validação."
        elif health == "hanging":
            summary = f"O ponto {path} consta como montado, mas a prova de acesso excedeu o timeout e foi classificado como Hanging."
            probable_cause = "O filesystem está presente na tabela de mounts, porém não responde à prova de acesso dentro do tempo seguro."
        elif health == "degraded":
            summary = f"O ponto {path} consta como montado, mas a prova de acesso retornou estado degradado."
            probable_cause = "O filesystem está montado, porém a validação funcional de acesso não foi concluída com sucesso."
        else:
            summary = f"O ponto de montagem {path} está montado e respondeu à prova de acesso."
            probable_cause = "Nenhuma indisponibilidade de montagem foi identificada."

    status = "healthy" if healthy_mount and not capacity_attention else "attention"
    confidence = 100
    facts = [
        f"Ponto validado: {path}",
        f"Estado observado: {'montado' if mounted else 'não montado'}",
        f"Saúde operacional: {health}",
    ]
    if usage_percent is not None:
        facts.append(f"Uso observado: {usage_percent}%")
    if source:
        facts.append(f"Origem observada: {source}")
    if fstype:
        facts.append(f"Tipo de filesystem: {fstype}")
    if cron_user:
        facts.append(f"Usuário da rotina de montagem: {cron_user}")
    if safe_result.get("cron_source"):
        facts.append(f"Cron identificado em: {safe_result['cron_source']}")

    recommendations: list[str] = []
    if health == "hanging" and safe_result.get("can_request_remount"):
        recommendations.append("A remontagem controlada pode ser solicitada pela interface após confirmação humana.")
    elif not mounted and safe_result.get("can_request_mount"):
        recommendations.append("A montagem pode ser solicitada pela interface após confirmação humana.")
    elif not mounted and reason:
        recommendations.append(reason)
    if capacity_attention:
        recommendations.append(f"Filesystem com {usage_percent}% de uso; avaliar capacidade e retenção de backup.")

    ticket_report = (
        f"Validação de mount realizada no alvo {target}. Ponto {path}: "
        f"{'MONTADO' if mounted else 'NÃO MONTADO'}; saúde {health}."
    )
    if usage_percent is not None:
        ticket_report += f" Uso: {usage_percent}%."
    if reason and not mounted:
        ticket_report += f" Observação: {reason}."

    evidence = {
        "type": job_type,
        "status": "success",
        "exit_code": 0,
        "path": path,
        "mounted": mounted,
        "health": health,
        "usage_percent": usage_percent,
        "source": source,
        "fstype": fstype,
        "cron_user": cron_user,
    }
    analysis = {
        "operation": job_type,
        "status": status,
        "confidence": confidence,
        "summary": summary,
        "probable_cause": probable_cause,
        "conclusion": summary,
        "facts": facts,
        "recommendations": recommendations,
        "ticket_report": ticket_report,
        "mount_result": safe_result,
        "deterministic_validation": True,
    }
    return {
        "target": target,
        "objective": objective,
        "environment": environment,
        "mode": "correct" if job_type in {MOUNT_RECOVERY_JOB, MOUNT_REMOUNT_JOB} else "investigate",
        "status": status,
        "confidence": confidence,
        "profile": "mount",
        "model": "deterministic",
        "duration_ms": max(0, int(duration_ms)),
        "plans": [{"playbook": {"id": job_type.replace("_", "-"), "title": title}}],
        "evidence": [evidence],
        "assessments": [],
        "analysis": analysis,
        "diagnostics": [],
    }


def _persist_mount_activity(
    job_type: str,
    result: dict[str, Any],
    *,
    duration_ms: int,
) -> str:
    document = _mount_activity_document(job_type, result, duration_ms=duration_ms)
    resolved_host = str(result.get("resolved_host") or document["target"] or "").strip()
    hostname = None
    if resolved_host:
        with SessionLocal() as session:
            host = session.scalar(
                select(HostORM)
                .where(HostORM.vpn_ip == resolved_host)
                .order_by(HostORM.last_seen_at.desc())
            )
            hostname = host.hostname if host else None

    with SessionLocal() as session:
        row = InvestigationORM(
            target=document["target"],
            hostname=hostname,
            objective=document["objective"],
            environment=document["environment"],
            mode=document["mode"],
            status=document["status"],
            confidence=document["confidence"],
            profile=document["profile"],
            model=document["model"],
            duration_ms=document["duration_ms"],
            plans=document["plans"],
            evidence=document["evidence"],
            assessments=document["assessments"],
            analysis=document["analysis"],
            diagnostics=document["diagnostics"],
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return str(row.id)


def _phase_detail(job_type: str) -> str:
    if job_type == MOUNT_VALIDATION_JOB:
        return "Validando mount e saúde da unidade."
    if job_type == MOUNT_REMOUNT_JOB:
        return "Executando remontagem Hanging autorizada."
    return "Executando montagem autorizada."


def _completed_detail(job_type: str) -> str:
    if job_type == MOUNT_VALIDATION_JOB:
        return "Validação e saúde concluídas."
    if job_type == MOUNT_REMOUNT_JOB:
        return "Solicitação de remontagem concluída."
    return "Solicitação de montagem concluída."


def execute_mount_job(job: dict[str, Any], *, settings: Settings) -> dict[str, Any]:
    job_id = str(job.get("job_id") or "")
    if not job_id:
        raise MountOperationError("job de mount sem identificador")
    client = _redis(settings)
    worker = f"{settings.agent_worker_name}@{socket.gethostname()}"
    started_clock = datetime.now(timezone.utc)
    started_at = started_clock.isoformat()
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
            "stage": job_type,
            "status": "running",
            "detail": _phase_detail(job_type),
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
        elif job_type == MOUNT_REMOUNT_JOB:
            if not bool(job.get("confirmed")):
                raise MountOperationError("job de remontagem sem confirmação explícita")
            result = remount_mount(
                str(job.get("reference") or ""),
                str(job.get("path") or ""),
                **common,
            )
        else:
            raise MountOperationError(f"tipo de job de mount desconhecido: {job_type}")

        result = dict(result)
        try:
            result["investigation_id"] = _persist_mount_activity(
                job_type,
                result,
                duration_ms=_duration_ms(started_clock),
            )
            result["history_persisted"] = True
        except Exception as persistence_exc:
            result["history_persisted"] = False
            result["history_warning"] = (
                "A validação foi concluída, mas não foi possível registrar o histórico: "
                f"{type(persistence_exc).__name__}: {redact_text(str(persistence_exc))}"
            )

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
                "detail": _completed_detail(job_type),
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
