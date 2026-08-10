from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.policies import EnvironmentType
from app.core.settings import get_settings
from app.services.mount_jobs import (
    enqueue_mount_recovery,
    enqueue_mount_validation,
    get_mount_job,
)
from app.services.mount_ops import MountOperationError
from app.web import _operator_name, _require_access, _require_mutation


router = APIRouter(tags=["mount-validation"])


class MountValidationPayload(BaseModel):
    target: str = Field(min_length=1, max_length=255)
    path: str = Field(min_length=2, max_length=1024)
    environment: EnvironmentType = EnvironmentType.UNKNOWN
    ssh_port: int | None = Field(default=None, ge=1, le=65535)


class MountRecoveryPayload(BaseModel):
    validation_job_id: str = Field(min_length=16, max_length=128)
    confirm: bool = False


@router.post("/ui/api/mounts/validate")
def request_mount_validation(
    payload: MountValidationPayload,
    request: Request,
) -> dict[str, Any]:
    _require_mutation(request)
    try:
        return enqueue_mount_validation(
            payload.target.strip(),
            payload.path.strip(),
            environment=payload.environment,
            ssh_port=payload.ssh_port,
            requested_by=_operator_name(),
            settings=get_settings(),
        )
    except MountOperationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"não foi possível enfileirar a validação de mount: {type(exc).__name__}: {exc}",
        ) from exc


@router.post("/ui/api/mounts/recover")
def request_mount_recovery(
    payload: MountRecoveryPayload,
    request: Request,
) -> dict[str, Any]:
    _require_mutation(request)
    if not payload.confirm:
        raise HTTPException(status_code=422, detail="confirmação explícita é obrigatória")
    try:
        return enqueue_mount_recovery(
            payload.validation_job_id,
            confirmed=True,
            requested_by=_operator_name(),
            settings=get_settings(),
        )
    except MountOperationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"não foi possível enfileirar a montagem: {type(exc).__name__}: {exc}",
        ) from exc


@router.get("/ui/api/mounts/jobs/{job_id}")
def mount_job_detail(job_id: str, request: Request) -> dict[str, Any]:
    _require_access(request)
    try:
        result = get_mount_job(job_id, settings=get_settings())
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"fila indisponível: {type(exc).__name__}: {exc}",
        ) from exc
    if not result:
        raise HTTPException(status_code=404, detail="job de mount não encontrado ou expirado")
    return result
