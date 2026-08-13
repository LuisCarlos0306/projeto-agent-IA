from __future__ import annotations

import json
import os

import typer
from rich.console import Console
from rich.panel import Panel

from app.core.settings import get_settings
from app.db.base import ensure_database_schema
from app.services.ai_instrumentation import install_ai_instrumentation
from app.services.confidence_instrumentation import install_confidence_instrumentation
from app.services.custom_skill_jobs import install_custom_skill_jobs
from app.services.focused_validation import install_focused_validation
from app.services.hard_job_alarm import install_hard_job_alarm
from app.services.job_process_guard import install_job_process_guard
from app.services.mapped_backup_validation import install_mapped_backup_validation
from app.services.operational_tool_instrumentation import install_operational_tools
from app.services.ptbr_guard import install_ptbr_guard
from app.services.scheduled_agent_scheduler import start_agent_scheduler
from app.services.worker_cancel_watchdog import _hard_timeout_seconds, install_worker_cancel_watchdog
from app.services.jobs import get_job, run_worker_once, worker_loop
from app.services.secrets import secret_backend_status


install_focused_validation()
install_ai_instrumentation()
install_ptbr_guard()
install_operational_tools()
install_confidence_instrumentation()
install_worker_cancel_watchdog()
install_hard_job_alarm()
install_job_process_guard()
install_mapped_backup_validation()
install_custom_skill_jobs()
app = typer.Typer(no_args_is_help=True)
console = Console()


@app.command("run")
def run(
    once: bool = typer.Option(False, "--once", help="Processa no máximo um job e encerra."),
    block_seconds: int | None = typer.Option(None, "--bloqueio", help="Tempo de espera por job."),
) -> None:
    """Executa jobs da fila Redis usando a conectividade deste worker."""
    settings = get_settings()
    ensure_database_schema()
    focused = os.getenv("AGENT_FAST_VALIDATION_ENABLED", "true").strip().lower()
    cancel_grace = os.getenv("AGENT_CANCEL_FORCE_EXIT_SECONDS", "20").strip()
    hard_timeout = _hard_timeout_seconds()
    console.print(Panel(
        f"Worker: {settings.agent_worker_name}\n"
        f"Fila: {settings.agent_queue_name}\n"
        f"Redis: configurado\n"
        f"Segredos: {secret_backend_status(settings).get('backend')}\n"
        f"StrictHostKeyChecking: {settings.ssh_strict_host_key_checking}\n"
        f"Coleta focada: {focused}\n"
        f"Skills personalizadas: leitura controlada\n"
        f"Agentes agendados: habilitados no modo contínuo\n"
        f"Idioma das mensagens: pt-BR\n"
        f"Confiança por evidências: ativa\n"
        f"Cancelamento forçado: {cancel_grace}s\n"
        f"Timeout duro por job: {hard_timeout}s\n"
        f"Isolamento por processo: ativo",
        title="Agent IA Worker",
    ))
    if once:
        result = run_worker_once(settings=settings, block_seconds=block_seconds)
        console.print(json.dumps(result or {"status": "empty"}, ensure_ascii=False, indent=2, default=str))
        return
    start_agent_scheduler(settings=settings)
    worker_loop(settings=settings)


@app.command("job")
def job(job_id: str = typer.Argument(..., help="UUID do job.")) -> None:
    """Consulta o estado de um job distribuído."""
    result = get_job(job_id)
    if not result:
        console.print(Panel("Job não encontrado ou expirado.", title="Job", border_style="yellow"))
        raise typer.Exit(2)
    console.print(Panel(json.dumps(result, ensure_ascii=False, indent=2, default=str), title="Job distribuído"))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
