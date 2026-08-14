from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.services.application_map import application_map_payload
from app.web import _require_access


router = APIRouter(prefix="/ui/api/application-map", tags=["interface-application-map"])


@router.get("")
def application_map(request: Request) -> dict[str, Any]:
    _require_access(request)
    return application_map_payload()
