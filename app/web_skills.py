from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.policies import EnvironmentType
from app.core.settings import get_settings
from app.services.backup_storage_registry import DEFAULT_MOUNT_SCRIPT, get_mapping, save_mapping
from app.services.custom_skill_jobs import enqueue_custom_skill
from app.services.custom_skill_registry import create_custom_skill, delete_custom_skill, get_custom_skill, list_custom_skills
from app.services.custom_skill_runner import run_custom_skill
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
    backup_path: str | None = Field(default=None, max_length=1024)
    mount_point: str | None = Field(default=None, max_length=1024)
    redundancy_path: str | None = Field(default=None, max_length=1024)
    min_free_percent: int = Field(default=20, ge=1, le=99)
    max_backup_age_hours: int = Field(default=30, ge=1, le=2160)
    retention_days: int = Field(default=7, ge=1, le=365)
    min_restore_points: int = Field(default=1, ge=1, le=500)


class CustomSkillCreatePayload(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: str = Field(default="", max_length=300)
    commands: list[str] = Field(min_length=1, max_length=20)


class CustomSkillRunPayload(BaseModel):
    target: str = Field(min_length=1, max_length=255)


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
        },
        "custom_skills": list_custom_skills(),
    }


@router.get("/custom")
def custom_skills(request: Request) -> dict[str, Any]:
    _require_access(request)
    return {"skills": list_custom_skills()}


@router.post("/custom")
def create_skill(payload: CustomSkillCreatePayload, request: Request) -> dict[str, Any]:
    _require_mutation(request)
    try:
        skill = create_custom_skill(payload.name, payload.commands, description=payload.description)
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "created", "skill": skill, "operator": _operator_name()}


@router.delete("/custom/{skill_id}")
def remove_skill(skill_id: str, request: Request) -> dict[str, Any]:
    _require_mutation(request)
    try:
        deleted = delete_custom_skill(skill_id)
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="skill personalizada não encontrada")
    return {"status": "deleted", "skill_id": skill_id, "operator": _operator_name()}


@router.post("/custom/{skill_id}/run")
def execute_custom_skill(skill_id: str, payload: CustomSkillRunPayload, request: Request) -> dict[str, Any]:
    _require_mutation(request)
    if get_custom_skill(skill_id) is None:
        raise HTTPException(status_code=404, detail="skill personalizada não encontrada")
    settings = get_settings()
    if settings.agent_execution_mode.strip().casefold() == "queue":
        try:
            return enqueue_custom_skill(
                skill_id,
                payload.target.strip(),
                metadata={"source": "web_ui_custom_skill", "operator": _operator_name()},
                settings=settings,
            )
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"fila indisponível: {type(exc).__name__}: {exc}") from exc
    try:
        result = run_custom_skill(
            skill_id,
            payload.target.strip(),
            environment=EnvironmentType.UNKNOWN,
            ssh_port=None,
            settings=settings,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}") from exc
    return {"status": "completed", "job_type": "skill", "skill": f"custom:{skill_id}", "result": result}


@router.get("/custom/jobs/{job_id}")
def custom_skill_job(job_id: str, request: Request) -> dict[str, Any]:
    _require_access(request)
    try:
        result = get_job(job_id, settings=get_settings())
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"fila indisponível: {type(exc).__name__}: {exc}") from exc
    if not result or result.get("job_type") != "skill" or not str(result.get("skill") or "").startswith("custom:"):
        raise HTTPException(status_code=404, detail="job de skill personalizada não encontrado ou expirado")
    return result


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
