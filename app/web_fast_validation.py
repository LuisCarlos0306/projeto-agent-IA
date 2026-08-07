from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

from app.web import UI_DIR, _require_access


ASSET_VERSION = "1.30.8"


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().casefold() in {"1", "true", "yes", "on", "sim"}


def _int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def focused_validation_payload() -> dict[str, object]:
    return {
        "enabled": _bool("AGENT_FAST_VALIDATION_ENABLED", True),
        "max_rounds": _int("AGENT_FAST_MAX_ROUNDS", 2, minimum=1, maximum=5),
        "tools_per_round": _int("AGENT_FAST_TOOLS_PER_ROUND", 3, minimum=1, maximum=5),
        "max_commands": _int("AGENT_FAST_TOTAL_COMMANDS", 10, minimum=5, maximum=30),
        "max_ai_calls": _int("AGENT_FAST_AI_CALLS", 8, minimum=3, maximum=20),
        "max_investigation_seconds": _int(
            "AGENT_FAST_INVESTIGATION_SECONDS",
            240,
            minimum=60,
            maximum=900,
        ),
        "max_host_seconds": _int("AGENT_FAST_HOST_SECONDS", 180, minimum=30, maximum=600),
        "ai_request_timeout_seconds": _float(
            "AGENT_AI_REQUEST_TIMEOUT_SECONDS",
            25.0,
            minimum=5.0,
            maximum=90.0,
        ),
    }


def _enhanced_index() -> str:
    html = (UI_DIR / "index.html").read_text(encoding="utf-8")
    stylesheets = (
        f'<link rel="stylesheet" href="/ui/assets/fast-validation-ui.css?v={ASSET_VERSION}">',
        f'<link rel="stylesheet" href="/ui/assets/investigation-confidence.css?v={ASSET_VERSION}">',
    )
    scripts = (
        f'<script src="/ui/assets/fast-validation-ui.js?v={ASSET_VERSION}" defer></script>',
        f'<script src="/ui/assets/investigation-confidence.js?v={ASSET_VERSION}" defer></script>',
    )
    for stylesheet in stylesheets:
        if stylesheet not in html:
            html = html.replace("</head>", f"  {stylesheet}\n</head>")
    for script in scripts:
        if script not in html:
            html = html.replace("</body>", f"  {script}\n</body>")
    return html


def register_fast_validation_ui(app: FastAPI) -> None:
    if getattr(app.state, "agent_fast_validation_ui_registered", False):
        return

    @app.get("/ui", include_in_schema=False)
    @app.get("/ui/", include_in_schema=False)
    def fast_validation_interface(request: Request) -> HTMLResponse:
        _require_access(request)
        return HTMLResponse(
            _enhanced_index(),
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )

    @app.get("/ui/api/fast-validation")
    def fast_validation_status(request: Request) -> dict[str, object]:
        _require_access(request)
        return focused_validation_payload()

    app.state.agent_fast_validation_ui_registered = True
