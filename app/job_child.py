from __future__ import annotations

import json
import sys

from app.core.settings import get_settings
from app.db.base import ensure_database_schema
from app.services import jobs
from app.services.ai_instrumentation import install_ai_instrumentation
from app.services.confidence_instrumentation import install_confidence_instrumentation
from app.services.focused_validation import install_focused_validation
from app.services.hard_job_alarm import install_hard_job_alarm
from app.services.operational_tool_instrumentation import install_operational_tools
from app.services.ptbr_guard import install_ptbr_guard
from app.services.worker_cancel_watchdog import install_worker_cancel_watchdog


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 2
    if not isinstance(payload, dict) or not payload.get("job_id"):
        return 2

    settings = get_settings()
    ensure_database_schema()
    install_focused_validation()
    install_ai_instrumentation()
    install_ptbr_guard()
    install_operational_tools()
    install_confidence_instrumentation()
    install_worker_cancel_watchdog()
    install_hard_job_alarm()

    jobs._execute_job(payload, settings=settings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
