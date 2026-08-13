from pathlib import Path

from app.services.scheduled_agent_status import correction_outcome


ROOT = Path(__file__).resolve().parents[1]


def test_agents_ui_exposes_visual_controls_history_and_skill_binding() -> None:
    script = (ROOT / "app" / "ui" / "agents.js").read_text(encoding="utf-8")
    style = (ROOT / "app" / "ui" / "agents.css").read_text(encoding="utf-8")
    web = (ROOT / "app" / "web_fast_validation.py").read_text(encoding="utf-8")
    cache = (ROOT / "app" / "web_ui_cache.py").read_text(encoding="utf-8")
    main = (ROOT / "app" / "web_main.py").read_text(encoding="utf-8")

    assert 'data-view="agents"' in script
    assert "+ Criar Agente" in script
    assert "Skill vinculada" in script
    assert "Servidor" in script
    assert "Frequência" in script
    assert "Últimas 5 validações concluídas" in script
    assert "RESULTADO DA CORREÇÃO" in script
    assert ">▶<" in script
    assert ">■<" in script
    assert "Ativo" in script
    assert "Parado" in script
    assert "agent-live-indicator" in style
    assert "agent-live-spinner" in style
    assert "agent-mini-history" in style
    assert "/ui/api/agents" in script
    assert '"agents.js"' in web
    assert '"agents.css"' in web
    assert "_inject_agent_assets(content)" in cache
    assert 'agents.js?v={_ASSET_VERSION}' in cache
    assert 'agents.css?v={_ASSET_VERSION}' in cache
    assert 'runtime-health.js?v={_ASSET_VERSION}' in cache
    assert "agents_router" in main


def test_play_activates_agent_runs_immediately_and_ui_auto_refreshes() -> None:
    script = (ROOT / "app" / "ui" / "agents.js").read_text(encoding="utf-8")
    web = (ROOT / "app" / "web_agents.py").read_text(encoding="utf-8")

    assert '/ui/api/agents/${encodeURIComponent(agentId)}/start' in script
    assert "Play ativa + executa agora" in script
    assert "BUSY_STATES" in script
    assert "startAutoRefresh" in script
    assert "refreshAgents().catch" in script
    assert '@router.post("/{agent_id}/start")' in web
    assert "set_agent_enabled(agent_id, True)" in web
    assert 'source="manual"' in web
    assert "advance_schedule=False" in web
    assert '"scheduled": True' in web


def test_stop_pauses_only_future_cycles() -> None:
    script = (ROOT / "app" / "ui" / "agents.js").read_text(encoding="utf-8")
    web = (ROOT / "app" / "web_agents.py").read_text(encoding="utf-8")

    assert "data-stop-agent" in script
    assert '/ui/api/agents/${encodeURIComponent(agentId)}/stop' in script
    assert '@router.post("/{agent_id}/stop")' in web
    assert "set_agent_enabled(agent_id, False)" in web
    assert '"running_execution_continues"' in web


def test_agents_keep_non_read_only_actions_out_of_automatic_execution() -> None:
    script = (ROOT / "app" / "ui" / "agents.js").read_text(encoding="utf-8")
    registry = (ROOT / "app" / "services" / "scheduled_agent_registry.py").read_text(encoding="utf-8")
    runner = (ROOT / "app" / "services" / "custom_skill_runner.py").read_text(encoding="utf-8")

    assert "Ações corretivas só aparecem como sucesso depois da execução autorizada e da pós-validação" in script
    assert '"automatic_correction": False' in registry
    assert '"status": "pending_approval"' in runner
    assert '"status": "blocked_by_policy"' in runner
    assert '"enabled": False' in runner
    assert '"executed_actions": []' in runner


def test_mount_result_requires_post_validation_before_reporting_success() -> None:
    pending_status, pending_message = correction_outcome(
        {
            "pending_commands": [
                {"command": "mount /mnt/backup_check", "status": "pending_approval"}
            ]
        }
    )
    assert pending_status == "pending_approval"
    assert "Montagem não executada" in pending_message

    unverified_status, unverified_message = correction_outcome(
        {
            "executed_actions": [
                {"command": "mount /mnt/backup_check", "exit_code": 0}
            ]
        }
    )
    assert unverified_status == "executed_unverified"
    assert "pós-validação ainda não confirmou" in unverified_message

    success_status, success_message = correction_outcome(
        {
            "executed_actions": [
                {
                    "command": "mount /mnt/backup_check",
                    "exit_code": 0,
                    "post_validation": {"ok": True},
                }
            ]
        }
    )
    assert success_status == "executed_success"
    assert "Montagem executada com sucesso" in success_message


def test_worker_starts_scheduler_only_in_continuous_mode() -> None:
    worker = (ROOT / "app" / "worker.py").read_text(encoding="utf-8")

    once_position = worker.index("if once:")
    scheduler_position = worker.index("start_agent_scheduler(settings=settings)")
    assert scheduler_position > once_position
    assert "Agentes agendados: habilitados no modo contínuo" in worker


def test_agent_configuration_and_history_are_persistent_in_postgresql() -> None:
    model = (ROOT / "app" / "db" / "agent_models.py").read_text(encoding="utf-8")
    registry = (ROOT / "app" / "services" / "scheduled_agent_registry.py").read_text(encoding="utf-8")
    base = (ROOT / "app" / "db" / "base.py").read_text(encoding="utf-8")

    assert '__tablename__ = "scheduled_agents"' in model
    assert '__tablename__ = "scheduled_agent_run_history"' in model
    assert "correction_status" in model
    assert "correction_message" in model
    assert "list_agent_history" in registry
    assert '"history": list_agent_history' in registry
    assert "skill_id" in model
    assert "target" in model
    assert "interval_minutes" in model
    assert "enabled" in model
    assert "next_run_at" in model
    assert "agent_models" in base


def test_scheduler_uses_redis_lock_reconciles_history_and_skips_overlap() -> None:
    scheduler = (ROOT / "app" / "services" / "scheduled_agent_scheduler.py").read_text(encoding="utf-8")

    assert "scheduled-agent:{agent_id}:lock" in scheduler
    assert "nx=True" in scheduler
    assert "enqueue_custom_skill" in scheduler
    assert '"automatic": source == "schedule"' in scheduler
    assert "reconcile_agent_statuses(settings=settings)" in scheduler
    assert "_BUSY_STATES" in scheduler
    assert "_defer_busy_agent" in scheduler
    assert "if last_status in _BUSY_STATES" in scheduler
