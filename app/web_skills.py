from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.policies import EnvironmentType
from app.core.settings import get_settings
from app.services.backup_storage_registry import DEFAULT_MOUNT_SCRIPT, get_mapping, save_mapping
from app.services.jobs import enqueue_backup_validation, get_job
from app.services.mapped_backup_validation import run_backup_validation
from app.web import _operator_name, _require_access, _require_mutation


router = APIRouter(prefix="/ui/api/skills", tags=["interface-skills"])


class StorageUnitPayload(BaseModel):
    mount_point: str = Field(min_length=1, max_length=1024)
    role: str = Field(default="outro", max_length=32)
    label: str = Field(default="", max_length=120)
    min_free_percent: int = Field(default=20, ge=1, le=99)


class StorageMappingPayload(BaseModel):
    target: str = Field(min_length=1, max_length=255)
    mount_script: str = Field(default=DEFAULT_MOUNT_SCRIPT, min_length=1, max_length=1024)
    units: list[StorageUnitPayload] = Field(min_length=1, max_length=30)


class BackupValidationPayload(BaseModel):
    target: str = Field(min_length=1, max_length=255)
    environment: EnvironmentType = EnvironmentType.UNKNOWN
    ssh_port: int | None = Field(default=None, ge=1, le=65535)
    # Compatibilidade com telas 1.1/1.2. No modo mapeado estes valores são ignorados.
    backup_path: str | None = Field(default=None, max_length=1024)
    mount_point: str | None = Field(default=None, max_length=1024)
    redundancy_path: str | None = Field(default=None, max_length=1024)
    min_free_percent: int = Field(default=20, ge=1, le=99)
    max_backup_age_hours: int = Field(default=30, ge=1, le=2160)
    retention_days: int = Field(default=7, ge=1, le=365)
    min_restore_points: int = Field(default=1, ge=1, le=500)


@router.get("")
def skill_runtime_status(request: Request) -> dict[str, Any]:
    _require_access(request)
    settings = get_settings()
    return {
        "skills": {
            "backup_validation": {
                "status": "active",
                "version": "1.3.0",
                "execution": "read_only",
                "execution_mode": settings.agent_execution_mode,
                "storage_source": "manual_mapping",
                "mount_action": "validation_request_only",
            }
        }
    }


@router.get("/backup-validation/mappings/{target:path}")
def read_backup_mapping(target: str, request: Request) -> dict[str, Any]:
    _require_access(request)
    mapping = get_mapping(target)
    if not mapping:
        raise HTTPException(status_code=404, detail="servidor ainda não possui mapeamento de storage")
    return mapping


@router.post("/backup-validation/mappings")
def write_backup_mapping(payload: StorageMappingPayload, request: Request) -> dict[str, Any]:
    _require_mutation(request)
    try:
        mapping = save_mapping(payload.model_dump(mode="json"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "status": "saved",
        "mapping": mapping,
        "operator": _operator_name(),
    }


@router.post("/backup-validation/run")
def execute_backup_validation(payload: BackupValidationPayload, request: Request) -> dict[str, Any]:
    _require_mutation(request)
    settings = get_settings()
    if not get_mapping(payload.target.strip()):
        raise HTTPException(
            status_code=422,
            detail="servidor sem mapeamento. Cadastre primeiro o script e as unidades esperadas na configuração da skill.",
        )

    common = {
        "backup_path": "",
        "mount_point": None,
        "redundancy_path": None,
        "environment": payload.environment,
        "ssh_port": payload.ssh_port,
        "min_free_percent": payload.min_free_percent,
        "max_backup_age_hours": payload.max_backup_age_hours,
        "retention_days": payload.retention_days,
        "min_restore_points": payload.min_restore_points,
        "settings": settings,
    }

    if settings.agent_execution_mode.strip().casefold() == "queue":
        try:
            return enqueue_backup_validation(
                payload.target.strip(),
                metadata={"source": "web_ui_skill_mapped", "operator": _operator_name()},
                **common,
            )
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"fila indisponível: {type(exc).__name__}: {exc}") from exc

    try:
        result = run_backup_validation(payload.target.strip(), **common)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}") from exc
    return {"status": "completed", "job_type": "skill", "skill": "backup_validation", "result": result}


@router.get("/jobs/{job_id}")
def skill_job(job_id: str, request: Request) -> dict[str, Any]:
    _require_access(request)
    try:
        result = get_job(job_id, settings=get_settings())
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"fila indisponível: {type(exc).__name__}: {exc}") from exc
    if not result or result.get("job_type") != "skill":
        raise HTTPException(status_code=404, detail="job de skill não encontrado ou expirado")
    return result
