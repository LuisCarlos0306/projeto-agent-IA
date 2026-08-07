from __future__ import annotations

import signal
from functools import wraps
from typing import Any

from app.services import jobs
from app.services.worker_cancel_watchdog import _hard_timeout_seconds


_INSTALLED = False


class HardJobTimeout(TimeoutError):
    """Timeout não cooperativo aplicado ao job inteiro no processo worker."""


def _supports_alarm() -> bool:
    return hasattr(signal, "SIGALRM") and hasattr(signal, "setitimer")


def install_hard_job_alarm() -> None:
    """Interrompe qualquer job que ultrapasse o limite duro configurado.

    É uma segunda camada independente do watchdog em thread. Em Linux, SIGALRM
    interrompe o fluxo principal mesmo quando a execução está presa em uma
    espera de rede. A exceção é capturada pelo próprio jobs._execute_job, que
    persiste o job como falho antes de liberar o worker para o próximo item.
    """
    global _INSTALLED
    if _INSTALLED or not _supports_alarm():
        return

    original = jobs._execute_job
    if getattr(original, "__agent_hard_alarm__", False):
        _INSTALLED = True
        return

    @wraps(original)
    def wrapped(job: dict[str, Any], *, settings: Any) -> dict[str, Any]:
        timeout = int(_hard_timeout_seconds())
        previous_handler = signal.getsignal(signal.SIGALRM)

        def _raise_timeout(_signum: int, _frame: Any) -> None:
            job_id = str(job.get("job_id") or "desconhecido")
            raise HardJobTimeout(
                f"Investigação {job_id} interrompida automaticamente após {timeout}s; "
                "o limite operacional foi atingido."
            )

        signal.signal(signal.SIGALRM, _raise_timeout)
        signal.setitimer(signal.ITIMER_REAL, max(1, timeout))
        try:
            return original(job, settings=settings)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_handler)

    setattr(wrapped, "__agent_hard_alarm__", True)
    jobs._execute_job = wrapped
    _INSTALLED = True
