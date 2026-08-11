from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.policies import EnvironmentType
from app.core.settings import get_settings
from app.services.backup_validation import run_backup_validation
from app.services.jobs import enqueue_backup_validation, get_job
from app.web import _operator_name, _require_access, _require_mutation


router = APIRouter(prefix="/ui/api/skills", tags=["interface-skills"])


class BackupValidationPayload(BaseModel):
    target: str = Field(min_length=1, max_length=255)
    environment: EnvironmentType = EnvironmentType.UNKNOWN
    ssh_port: int | None = Field(default=None, ge=1, le=65535)
    mount_point: str = Field(min_length=1, max_length=1024)
    backup_path: str = Field(min_length=1, max_length=1024)
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
                "version": "1.1.0",
                "execution": "read_only",
                "execution_mode": settings.agent_execution_mode,
                "mount_action": "approval_required_disabled",
            }
        }
    }


@router.post("/backup-validation/run")
def execute_backup_validation(payload: BackupValidationPayload, request: Request) -> dict[str, Any]:
    _require_mutation(request)
    settings = get_settings()
    common = {
        "mount_point": payload.mount_point,
        "backup_path": payload.backup_path,
        "redundancy_path": payload.redundancy_path,
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
                metadata={"source": "web_ui_skill", "operator": _operator_name()},
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
