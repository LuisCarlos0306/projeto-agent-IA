from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_agents_ui_exposes_create_toggle_run_and_skill_binding() -> None:
    script = (ROOT / "app" / "ui" / "agents.js").read_text(encoding="utf-8")
    web = (ROOT / "app" / "web_fast_validation.py").read_text(encoding="utf-8")
    main = (ROOT / "app" / "web_main.py").read_text(encoding="utf-8")

    assert 'data-view="agents"' in script
    assert "+ Criar Agente" in script
    assert "Skill" in script
    assert "IP / Servidor" in script
    assert "Frequência" in script
    assert "Habilitar" in script
    assert "Desabilitar" in script
    assert "Executar agora" in script
    assert "/ui/api/agents" in script
    assert '"agents.js"' in web
    assert "agents_router" in main


def test_agents_keep_corrective_scripts_out_of_automatic_execution() -> None:
    script = (ROOT / "app" / "ui" / "agents.js").read_text(encoding="utf-8")
    registry = (ROOT / "app" / "services" / "scheduled_agent_registry.py").read_text(encoding="utf-8")
    runner = (ROOT / "app" / "services" / "custom_skill_runner.py").read_text(encoding="utf-8")

    assert "Scripts corretivos cadastrados na Skill continuam aguardando aprovação" in script
    assert '"automatic_correction": False' in registry
    assert '"status": "pending_approval"' in runner
    assert '"enabled": False' in runner
    assert '"executed_actions": []' in runner


def test_worker_starts_scheduler_only_in_continuous_mode() -> None:
    worker = (ROOT / "app" / "worker.py").read_text(encoding="utf-8")

    once_position = worker.index("if once:")
    scheduler_position = worker.index("start_agent_scheduler(settings=settings)")
    assert scheduler_position > once_position
    assert "Agentes agendados: habilitados no modo contínuo" in worker


def test_agent_configuration_is_persistent_in_postgresql() -> None:
    model = (ROOT / "app" / "db" / "agent_models.py").read_text(encoding="utf-8")
    base = (ROOT / "app" / "db" / "base.py").read_text(encoding="utf-8")

    assert '__tablename__ = "scheduled_agents"' in model
    assert "skill_id" in model
    assert "target" in model
    assert "interval_minutes" in model
    assert "enabled" in model
    assert "next_run_at" in model
    assert "agent_models" in base


def test_scheduler_uses_redis_lock_before_queueing_due_agent() -> None:
    scheduler = (ROOT / "app" / "services" / "scheduled_agent_scheduler.py").read_text(encoding="utf-8")

    assert "scheduled-agent:{agent_id}:lock" in scheduler
    assert "nx=True" in scheduler
    assert "enqueue_custom_skill" in scheduler
    assert '"automatic": source == "schedule"' in scheduler
