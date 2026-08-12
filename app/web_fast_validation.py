from __future__ import annotations

import os
import re

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

from app.web import UI_DIR, _require_access


ASSET_VERSION = "1.30.21"


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
    investigation_seconds = _int(
        "AGENT_FAST_INVESTIGATION_SECONDS",
        240,
        minimum=60,
        maximum=900,
    )
    hard_timeout = _int(
        "AGENT_JOB_HARD_TIMEOUT_SECONDS",
        investigation_seconds
        + _int("AGENT_JOB_HARD_TIMEOUT_GRACE_SECONDS", 15, minimum=5, maximum=120),
        minimum=60,
        maximum=1800,
    )
    return {
        "enabled": _bool("AGENT_FAST_VALIDATION_ENABLED", True),
        "ui_version": ASSET_VERSION,
        "max_rounds": _int("AGENT_FAST_MAX_ROUNDS", 2, minimum=1, maximum=5),
        "tools_per_round": _int("AGENT_FAST_TOOLS_PER_ROUND", 3, minimum=1, maximum=5),
        "max_commands": _int("AGENT_FAST_TOTAL_COMMANDS", 10, minimum=5, maximum=30),
        "max_ai_calls": _int("AGENT_FAST_AI_CALLS", 8, minimum=3, maximum=20),
        "max_investigation_seconds": investigation_seconds,
        "hard_timeout_seconds": hard_timeout,
        "max_host_seconds": _int("AGENT_FAST_HOST_SECONDS", 180, minimum=30, maximum=600),
        "ai_request_timeout_seconds": _float(
            "AGENT_AI_REQUEST_TIMEOUT_SECONDS",
            25.0,
            minimum=5.0,
            maximum=90.0,
        ),
    }


def _versioned_stylesheet(html: str, asset: str) -> str:
    current = f'<link rel="stylesheet" href="/ui/assets/{asset}?v={ASSET_VERSION}">'
    pattern = rf'<link rel="stylesheet" href="/ui/assets/{re.escape(asset)}\?v=[^"]+">'
    html, count = re.subn(pattern, current, html, count=1)
    if not count:
        html = html.replace("</head>", f"  {current}\n</head>")
    return html


def _versioned_script(html: str, asset: str) -> str:
    current = f'<script src="/ui/assets/{asset}?v={ASSET_VERSION}" defer></script>'
    pattern = rf'<script src="/ui/assets/{re.escape(asset)}\?v=[^"]+" defer></script>'
    html, count = re.subn(pattern, current, html, count=1)
    if not count:
        html = html.replace("</body>", f"  {current}\n</body>")
    return html


def _inline_cyber_theme(html: str) -> str:
    marker = 'id="agent-cyber-theme-inline"'
    if marker in html:
        return html
    theme_path = UI_DIR / "cyber-theme.css"
    if not theme_path.exists():
        return html
    css = theme_path.read_text(encoding="utf-8")
    return html.replace(
        "</head>",
        f'  <style id="agent-cyber-theme-inline">\n{css}\n  </style>\n</head>',
    )


def _inline_cyber_brand(html: str) -> str:
    original = '<div class="brand-mark" aria-hidden="true">AI</div>'
    if original not in html:
        return html
    logo = '''<div class="brand-mark" aria-hidden="true" title="Agent IA — inteligência operacional">
        <svg class="brand-ai-logo" viewBox="0 0 48 48" role="img" aria-label="Símbolo neural do Agent IA">
          <defs><linearGradient id="brandCyberGradientInline" x1="7" y1="7" x2="41" y2="41" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#45efff"/><stop offset=".52" stop-color="#35dfff"/><stop offset="1" stop-color="#b03cff"/></linearGradient></defs>
          <path class="brand-head" d="M13 38V22c0-8 5.2-13 12.8-13 6.5 0 11.5 3.9 12.5 10l3.2 6.3-4.5 2.1V35h-8.5l-4.8 4.8H13z"/>
          <path class="brand-trace" d="M18 31V20h6v-5M24 34V25h8v-8M17 25h4l3-3M29 29v-5h6M19 35h5l4-4"/>
          <circle class="brand-node" cx="18" cy="20" r="1.6"/><circle class="brand-node" cx="24" cy="15" r="1.6"/><circle class="brand-node" cx="32" cy="17" r="1.6"/><circle class="brand-node" cx="35" cy="24" r="1.6"/><circle class="brand-node" cx="29" cy="29" r="1.6"/>
        </svg>
      </div>'''
    return html.replace(original, logo, 1)


def _enhanced_index() -> str:
    html = (UI_DIR / "index.html").read_text(encoding="utf-8")
    for asset in (
        "fast-validation-ui.css",
        "investigation-confidence.css",
        "cyber-theme.css",
        "skills.css",
        "skills-storage-mapping.css",
    ):
        html = _versioned_stylesheet(html, asset)
    for asset in (
        "fast-validation-ui.js",
        "investigation-confidence.js",
        "skills.js",
        "skills-auto-discovery.js",
        "runtime-health.js",
    ):
        html = _versioned_script(html, asset)
    html = _inline_cyber_brand(html)
    html = _inline_cyber_theme(html)
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
                "X-Agent-UI-Version": ASSET_VERSION,
            },
        )

    @app.get("/ui/api/fast-validation")
    def fast_validation_status(request: Request) -> dict[str, object]:
        _require_access(request)
        return focused_validation_payload()

    app.state.agent_fast_validation_ui_registered = True
