from pathlib import Path

from app.services.scheduled_agent_run_log import execution_outcome
from app.services.scheduled_agent_status import correction_outcome


ROOT = Path(__file__).resolve().parents[1]


def test_agents_v3_ui_is_compact_and_loads_details_lazily() -> None:
    script = (ROOT / "app" / "ui" / "agents-v3.js").read_text(encoding="utf-8")
    style = (ROOT / "app" / "ui" / "agents-v2.css").read_text(encoding="utf-8")
    web = (ROOT / "app" / "web_fast_validation.py").read_text(encoding="utf-8")
    cache = (ROOT / "app" / "web_ui_cache.py").read_text(encoding="utf-8")

    assert "Agentes IA" in script
    assert 'dataset.view = "agents"' in script
    assert 'dataset.view = "agentflow"' in script
    assert "Fluxo dos Agentes IA" in script
    assert "+ Criar Agente" in script
    assert "agent-v2-grid" in script
    assert "agent-v2-drawer" in script
    assert 'requestJson("/ui/api/agents?compact=1")' in script
    assert 'event.target.closest(".agent-v2-card[data-agent-id]")' in script
    assert "data-agent-log-body" in script
    assert "hydrateLog(details)" in script
    assert "Ações realizadas" in script
    assert "Erro detalhado" in script
    assert "Ação recomendada" in script
    assert "agent-v2-card" in style
    assert "agent-v2-drawer" in style
    assert "agent-v2-flow-step" in style
    assert '"agents-v3.js"' in web
    assert '"agents-v2.css"' in web
    assert 'agents-v3.js?v={_ASSET_VERSION}' in cache
    assert 'agents-v2.css?v={_ASSET_VERSION}' in cache


def test_execution_state_is_separate_from_manual_correction_state() -> None:
    job = {"status": "completed"}
    result = {
        "summary": "Diagnóstico concluído.",
        "commands": [],
        "pending_commands": [
            {"command": "mount /mnt/backup_check", "status": "pending_approval"}
        ],
    }

    assert execution_outcome(job, result) == "completed_success"
    correction_status, correction_message = correction_outcome(result, "completed")
    assert correction_status == "pending_approval"
    assert "Montagem não executada" in correction_message


def test_execution_outcome_reports_error_and_cancelled() -> None:
    assert execution_outcome(
        {"status": "completed"},
        {"commands": [{"command": "df -h", "exit_code": 1}]},
    ) == "completed_error"
    assert execution_outcome({"status": "failed"}, {}) == "completed_error"
    assert execution_outcome({"status": "cancelled"}, {}) == "cancelled"


def test_agent_run_details_are_persistent_and_redacted() -> None:
    model = (ROOT / "app" / "db" / "agent_run_models.py").read_text(encoding="utf-8")
    service = (ROOT / "app" / "services" / "scheduled_agent_run_log.py").read_text(encoding="utf-8")
    presenter = (ROOT / "app" / "services" / "scheduled_agent_presenter.py").read_text(encoding="utf-8")

    assert '__tablename__ = "scheduled_agent_run_details"' in model
    assert "started_at" in model
    assert "completed_at" in model
    assert "duration_ms" in model
    assert "failure_stage" in model
    assert "error_code" in model
    assert "actions_json" in model
    assert "recommendation" in model
    assert "redact_object" in service
    assert "record_run_detail" in service
    assert "run_detail_map" in service
    assert 'payload["current_execution"]' in presenter
    assert 'payload["display_state"]' in presenter
    assert 'payload["last_result"]' in presenter


def test_play_activates_agent_and_stop_only_pauses_future_cycles() -> None:
    script = (ROOT / "app" / "ui" / "agents-v3.js").read_text(encoding="utf-8")
    web = (ROOT / "app" / "web_agents.py").read_text(encoding="utf-8")

    assert '/ui/api/agents/${encodeURIComponent(agentId)}/start' in script
    assert '/ui/api/agents/${encodeURIComponent(agentId)}/stop' in script
    assert '@router.post("/{agent_id}/start")' in web
    assert '@router.post("/{agent_id}/stop")' in web
    assert "set_agent_enabled(agent_id, True)" in web
    assert "set_agent_enabled(agent_id, False)" in web
    assert '"running_execution_continues"' in web


def test_ui_refreshes_runtime_state_started_by_scheduler() -> None:
    script = (ROOT / "app" / "ui" / "agents-v3.js").read_text(encoding="utf-8")
    presenter = (ROOT / "app" / "services" / "scheduled_agent_presenter.py").read_text(encoding="utf-8")

    assert "current_execution" in script
    assert "scheduleRefresh" in script
    assert "1600" in script
    assert "5000" in script
    assert "get_job" in presenter
    assert '"percent"' in presenter
    assert '"stage"' in presenter
    assert '"detail"' in presenter


def test_agents_keep_corrective_actions_under_existing_approval_policy() -> None:
    script = (ROOT / "app" / "ui" / "agents-v3.js").read_text(encoding="utf-8")
    registry = (ROOT / "app" / "services" / "scheduled_agent_registry.py").read_text(encoding="utf-8")
    runner = (ROOT / "app" / "services" / "custom_skill_runner.py").read_text(encoding="utf-8")

    assert "Aguardando aprovação" in script
    assert '"automatic_correction": False' in registry
    assert '"status": "pending_approval"' in runner
    assert '"status": "blocked_by_policy"' in runner
    assert '"executed_actions": []' in runner


def test_mount_success_still_requires_post_validation() -> None:
    unverified_status, unverified_message = correction_outcome(
        {"executed_actions": [{"command": "mount /mnt/backup_check", "exit_code": 0}]}
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


def test_scheduler_reconciles_history_and_skips_overlap() -> None:
    scheduler = (ROOT / "app" / "services" / "scheduled_agent_scheduler.py").read_text(encoding="utf-8")
    status = (ROOT / "app" / "services" / "scheduled_agent_status.py").read_text(encoding="utf-8")

    assert "scheduled-agent:{agent_id}:lock" in scheduler
    assert "_BUSY_STATES" in scheduler
    assert "_defer_busy_agent" in scheduler
    assert "reconcile_agent_statuses(settings=settings)" in scheduler
    assert "record_run_detail" in status
    assert "execution_outcome" in status


def test_worker_starts_scheduler_only_in_continuous_mode() -> None:
    worker = (ROOT / "app" / "worker.py").read_text(encoding="utf-8")
    once_position = worker.index("if once:")
    scheduler_position = worker.index("start_agent_scheduler(settings=settings)")
    assert scheduler_position > once_position
    assert "Agentes agendados: habilitados no modo contínuo" in worker
