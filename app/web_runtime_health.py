from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.services.runtime_infrastructure_health import validate_runtime_infrastructure_from_env
from app.web import _require_mutation


router = APIRouter(prefix="/ui/api/health", tags=["interface-health"])


@router.post("/infrastructure-access")
def validate_infrastructure_access(request: Request) -> dict[str, Any]:
    _require_mutation(request)
    return validate_runtime_infrastructure_from_env()
