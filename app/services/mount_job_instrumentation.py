from __future__ import annotations

from app.services import jobs
from app.services.mount_jobs import execute_mount_job, is_mount_job


_INSTALLED = False


def install_mount_jobs() -> None:
    """Faz o worker existente reconhecer jobs dedicados de mount.

    A fila Redis continua sendo a mesma. Jobs de investigação seguem para o
    executor original e jobs de mount usam o fluxo restrito deste módulo.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    base_execute_job = jobs._execute_job

    def execute_job(job, *, settings):
        if is_mount_job(job):
            return execute_mount_job(job, settings=settings)
        return base_execute_job(job, settings=settings)

    jobs._execute_job = execute_job
    _INSTALLED = True
