from __future__ import annotations

from typing import Any

from app.core.settings import Settings, get_settings
from app.services.application_health import application_health
from app.services.custom_skill_registry import list_custom_skills
from app.services.scheduled_agent_registry import list_agents


CATEGORY_LABELS = {
    "entry": "Entradas",
    "web": "Web / API",
    "orchestration": "Orquestração",
    "ai": "Inteligência Artificial",
    "security": "Segurança",
    "data": "Dados",
    "execution": "Execução",
    "external": "Ambiente externo",
}


def _node(
    node_id: str,
    label: str,
    category: str,
    layer: int,
    order: int,
    *,
    description: str,
    technology: str,
    source: list[str],
    views: list[str],
    runtime_key: str | None = None,
    detail: str = "",
) -> dict[str, Any]:
    return {
        "id": node_id,
        "label": label,
        "category": category,
        "category_label": CATEGORY_LABELS[category],
        "layer": layer,
        "order": order,
        "description": description,
        "detail": detail,
        "technology": technology,
        "source": source,
        "views": views,
        "runtime_key": runtime_key,
        "state": "unknown",
        "state_detail": "Estado runtime não consultado.",
        "metrics": {},
    }


def _edge(source: str, target: str, kind: str, label: str, views: list[str]) -> dict[str, Any]:
    return {
        "source": source,
        "target": target,
        "kind": kind,
        "label": label,
        "views": views,
    }


def _architecture() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = [
        _node(
            "ui",
            "Interface Web",
            "entry",
            0,
            0,
            description="Dashboard operacional usada pelo operador para investigar, acompanhar agentes, Skills, inventário e saúde.",
            technology="HTML · CSS · JavaScript",
            source=["app/ui/index.html", "app/ui/app.js", "app/ui/agents-v2.js"],
            views=["architecture", "runtime"],
        ),
        _node(
            "cli",
            "CLI Agent IA",
            "entry",
            0,
            1,
            description="Entrada de linha de comando para investigação e operação controlada.",
            technology="Python CLI",
            source=["app/cli/entrypoint.py", "app/cli/main.py"],
            views=["architecture"],
        ),
        _node(
            "checkmk",
            "Checkmk / Webhooks",
            "entry",
            0,
            2,
            description="Entrada externa de alertas e eventos de monitoramento.",
            technology="HTTP Webhook",
            source=["app/main.py", "app/services/checkmk_playbooks.py"],
            views=["architecture", "runtime"],
        ),
        _node(
            "fastapi",
            "FastAPI / Agent Web",
            "web",
            1,
            0,
            description="Camada HTTP principal que expõe UI, APIs, webhooks e módulos operacionais.",
            technology="FastAPI · Uvicorn",
            source=["app/main.py", "app/web_main.py"],
            views=["architecture", "runtime"],
            runtime_key="web",
        ),
        _node(
            "routers",
            "Módulos Web / APIs",
            "web",
            1,
            1,
            description="Routers de Agentes, Skills, Playbooks, Execuções, Topologia, Configurações e Saúde.",
            technology="FastAPI Routers",
            source=["app/web_agents.py", "app/web_skills.py", "app/web_playbooks.py", "app/web_executions.py"],
            views=["architecture"],
        ),
        _node(
            "orchestrator",
            "Orquestração adaptativa",
            "orchestration",
            2,
            0,
            description="Coordena investigação, hipóteses, coleta de evidências, ferramentas e conclusão.",
            technology="Python services",
            source=["app/services/adaptive_orchestrator.py", "app/services/dynamic_agent.py"],
            views=["architecture", "runtime"],
        ),
        _node(
            "skills",
            "Skills",
            "orchestration",
            2,
            1,
            description="Catálogo de capacidades configuradas pelo operador, com comandos e scripts classificados por permissão.",
            technology="JSON registry · Python",
            source=["app/services/custom_skill_registry.py", "app/services/custom_skill_runner.py"],
            views=["architecture", "runtime", "data"],
            runtime_key="skills",
        ),
        _node(
            "playbooks",
            "Playbooks",
            "orchestration",
            2,
            2,
            description="Fluxos declarativos usados para investigação orientada e execução controlada.",
            technology="YAML · Python",
            source=["app/services/playbooks.py"],
            views=["architecture", "runtime", "data"],
            runtime_key="playbooks",
        ),
        _node(
            "agents",
            "Agentes agendados",
            "orchestration",
            2,
            3,
            description="Vinculam uma Skill a um alvo e executam ciclos automáticos no intervalo configurado.",
            technology="PostgreSQL · Scheduler",
            source=["app/services/scheduled_agent_registry.py", "app/services/scheduled_agent_scheduler.py"],
            views=["architecture", "runtime", "data"],
            runtime_key="agents",
        ),
        _node(
            "scheduler",
            "Scheduler",
            "orchestration",
            3,
            0,
            description="Identifica agentes vencidos, evita sobreposição e envia execuções para a fila.",
            technology="Thread · Redis lock",
            source=["app/services/scheduled_agent_scheduler.py"],
            views=["architecture", "runtime"],
            runtime_key="scheduler",
        ),
        _node(
            "ai_router",
            "Roteamento de IA",
            "ai",
            3,
            1,
            description="Seleciona provedores e modelos disponíveis para análise e revisão.",
            technology="Provider router",
            source=["app/services/ai.py", "app/services/ai_providers.py"],
            views=["architecture", "runtime"],
            runtime_key="providers",
        ),
        _node(
            "reviewer",
            "Segunda IA / Revisão",
            "ai",
            3,
            2,
            description="Revisa propostas corretivas antes de qualquer execução autorizada.",
            technology="AI reviewer",
            source=["app/services/approved_execution.py"],
            views=["architecture", "security"],
        ),
        _node(
            "policies",
            "Políticas operacionais",
            "security",
            3,
            3,
            description="Classifica ações e ambientes, bloqueando alterações não permitidas.",
            technology="Policy engine",
            source=["app/core/policies.py", "app/services/correction_policy.py"],
            views=["architecture", "security"],
        ),
        _node(
            "environment",
            "Classificação de ambiente",
            "security",
            3,
            4,
            description="Determina produção, standby, monitoramento, treinamento ou ambiente desconhecido.",
            technology="Environment classifier",
            source=["app/services/environment_classifier.py", "app/services/environment_fingerprint.py"],
            views=["architecture", "security"],
        ),
        _node(
            "redis",
            "Redis",
            "data",
            4,
            0,
            description="Fila de jobs, estados transitórios, cache e locks do scheduler.",
            technology="Redis",
            source=["app/services/jobs.py", "app/services/scheduled_agent_scheduler.py"],
            views=["architecture", "runtime", "data"],
            runtime_key="redis",
        ),
        _node(
            "postgres",
            "PostgreSQL",
            "data",
            4,
            1,
            description="Persistência de investigações, agentes, históricos, execuções e auditoria.",
            technology="PostgreSQL · SQLAlchemy",
            source=["app/db/base.py", "app/db/models.py", "app/db/agent_models.py"],
            views=["architecture", "runtime", "data"],
            runtime_key="postgres",
        ),
        _node(
            "skill_store",
            "Registro local de Skills",
            "data",
            4,
            2,
            description="Persistência local controlada das Skills personalizadas.",
            technology="JSON · modo 0600",
            source=["app/services/custom_skill_registry.py"],
            views=["data", "security"],
            runtime_key="skills",
        ),
        _node(
            "approvals",
            "Aprovação humana",
            "security",
            4,
            3,
            description="Autoriza explicitamente ações corretivas exatas usando tokens assinados e prazo limitado.",
            technology="Signed approval token",
            source=["app/services/approvals.py", "app/services/approved_execution.py"],
            views=["architecture", "security"],
        ),
        _node(
            "worker",
            "Agent IA Worker",
            "execution",
            5,
            0,
            description="Consome jobs da fila e executa investigações e Skills no modo contínuo.",
            technology="Python worker",
            source=["app/worker.py"],
            views=["architecture", "runtime"],
            runtime_key="worker",
        ),
        _node(
            "runner",
            "Runner / Resolve Target",
            "execution",
            5,
            1,
            description="Resolve inventário, ambiente, bastion e constrói o executor permitido para o alvo.",
            technology="Python executor",
            source=["app/services/runner.py"],
            views=["architecture", "runtime", "security"],
        ),
        _node(
            "known_hosts",
            "known_hosts / SSH trust",
            "security",
            5,
            2,
            description="Valida identidade SSH e impede redução das proteções de host conhecido.",
            technology="OpenSSH trust",
            source=["app/services/runner.py"],
            views=["security"],
        ),
        _node(
            "ssh",
            "Executor SSH",
            "execution",
            6,
            0,
            description="Executa comandos permitidos no servidor remoto com timeout, redaction e política.",
            technology="SSH",
            source=["app/services/runner.py"],
            views=["architecture", "runtime", "security"],
        ),
        _node(
            "post_validation",
            "Pós-validação",
            "security",
            6,
            1,
            description="Confirma funcionalmente o resultado depois de uma ação corretiva autorizada.",
            technology="Validation gates",
            source=["app/services/approved_execution.py", "app/services/correction_comparison.py"],
            views=["architecture", "security"],
        ),
        _node(
            "inventory",
            "Inventário / Topologia",
            "data",
            6,
            2,
            description="Metadados aprendidos sobre alvos, clientes, ambientes e topologia operacional.",
            technology="PostgreSQL · discovery",
            source=["app/services/discovery.py", "app/services/customer_topology.py"],
            views=["architecture", "data"],
        ),
        _node(
            "servers",
            "Servidores / NAS / NFS / CIFS",
            "external",
            7,
            0,
            description="Ambientes autorizados onde o Agent IA coleta evidências e, quando permitido, executa ações aprovadas.",
            technology="Linux · SSH · storage",
            source=[],
            views=["architecture", "runtime"],
        ),
        _node(
            "audit",
            "Resultados / Auditoria",
            "data",
            7,
            1,
            description="Resultados de investigações, histórico de agentes, evidências e trilha de auditoria.",
            technology="PostgreSQL · Redis results",
            source=["app/services/persistence.py", "app/services/execution_store.py"],
            views=["architecture", "data", "security"],
        ),
    ]

    edges = [
        _edge("ui", "fastapi", "direct", "HTTP / UI APIs", ["architecture", "runtime"]),
        _edge("cli", "orchestrator", "direct", "comandos", ["architecture"]),
        _edge("checkmk", "fastapi", "direct", "webhook", ["architecture", "runtime"]),
        _edge("fastapi", "routers", "direct", "routers", ["architecture"]),
        _edge("routers", "orchestrator", "direct", "investigação", ["architecture"]),
        _edge("routers", "skills", "direct", "CRUD / execução", ["architecture"]),
        _edge("routers", "agents", "direct", "gestão", ["architecture"]),
        _edge("orchestrator", "ai_router", "direct", "análise", ["architecture", "runtime"]),
        _edge("orchestrator", "policies", "security", "avaliação de ação", ["architecture", "security"]),
        _edge("orchestrator", "environment", "security", "classificação", ["architecture", "security"]),
        _edge("skills", "agents", "direct", "referência", ["architecture", "runtime", "data"]),
        _edge("playbooks", "orchestrator", "direct", "orienta investigação", ["architecture", "runtime"]),
        _edge("agents", "scheduler", "async", "intervalo", ["architecture", "runtime"]),
        _edge("scheduler", "redis", "async", "enqueue + lock", ["architecture", "runtime", "data"]),
        _edge("fastapi", "redis", "async", "jobs / resultados", ["architecture", "runtime", "data"]),
        _edge("agents", "postgres", "data", "configuração / histórico", ["architecture", "runtime", "data"]),
        _edge("orchestrator", "postgres", "data", "investigações", ["architecture", "data"]),
        _edge("skills", "skill_store", "data", "persistência", ["data"]),
        _edge("redis", "worker", "async", "consumo da fila", ["architecture", "runtime"]),
        _edge("worker", "runner", "direct", "execução do job", ["architecture", "runtime"]),
        _edge("runner", "known_hosts", "security", "confiança SSH", ["security"]),
        _edge("runner", "ssh", "direct", "executor", ["architecture", "runtime", "security"]),
        _edge("ssh", "servers", "ssh", "SSH", ["architecture", "runtime"]),
        _edge("ai_router", "reviewer", "security", "segunda revisão", ["architecture", "security"]),
        _edge("reviewer", "approvals", "security", "proposta revisada", ["security"]),
        _edge("policies", "approvals", "security", "ação elegível", ["architecture", "security"]),
        _edge("approvals", "runner", "security", "execução autorizada", ["architecture", "security"]),
        _edge("runner", "post_validation", "security", "resultado", ["architecture", "security"]),
        _edge("post_validation", "audit", "data", "confirmação", ["architecture", "data", "security"]),
        _edge("servers", "inventory", "data", "discovery", ["architecture", "data"]),
        _edge("inventory", "postgres", "data", "metadados", ["data"]),
        _edge("worker", "audit", "data", "resultado do job", ["architecture", "data"]),
    ]
    return nodes, edges


def _runtime(settings: Settings) -> dict[str, Any]:
    try:
        health = application_health(settings)
    except Exception as exc:
        health = {
            "status": "attention",
            "version": "desconhecida",
            "database": {"state": "unknown", "detail": f"{type(exc).__name__}: saúde indisponível"},
            "queue": {"state": "unknown", "detail": "Fila não consultada.", "depth": None},
            "providers": [],
            "playbooks": {"state": "unknown", "count": None},
            "worker": {"state": "unknown", "detail": "Worker não consultado."},
        }
    try:
        skills = list_custom_skills()
    except Exception:
        skills = []
    try:
        agents = list_agents()
    except Exception:
        agents = []
    return {"health": health, "skills": skills, "agents": agents}


def _apply_runtime(nodes: list[dict[str, Any]], runtime: dict[str, Any]) -> None:
    health = runtime["health"]
    skills = runtime["skills"]
    agents = runtime["agents"]
    providers = health.get("providers") or []
    selectable = [item for item in providers if item.get("selectable")]
    active_agents = [item for item in agents if item.get("enabled")]
    running_agents = [
        item for item in agents
        if str(item.get("last_status") or "") in {"queued", "running", "cancelling"}
    ]

    states = {
        "web": ("available", f"Interface carregada · versão {health.get('version') or 'desconhecida'}", {"version": health.get("version")}),
        "postgres": (
            health.get("database", {}).get("state", "unknown"),
            health.get("database", {}).get("detail", ""),
            {},
        ),
        "redis": (
            health.get("queue", {}).get("state", "unknown"),
            health.get("queue", {}).get("detail", ""),
            {"queue_depth": health.get("queue", {}).get("depth"), "mode": health.get("queue", {}).get("execution_mode")},
        ),
        "worker": (
            "available" if health.get("worker", {}).get("state") in {"external", "inline"} else health.get("worker", {}).get("state", "unknown"),
            health.get("worker", {}).get("detail", ""),
            {"mode": health.get("worker", {}).get("state")},
        ),
        "scheduler": (
            "available" if active_agents else "idle",
            "Scheduler usado pelo Worker contínuo." if agents else "Nenhum agente configurado.",
            {"active_agents": len(active_agents), "running_agents": len(running_agents)},
        ),
        "skills": ("available" if skills else "idle", f"{len(skills)} Skill(s) personalizada(s) cadastrada(s).", {"count": len(skills)}),
        "agents": ("available" if agents else "idle", f"{len(agents)} agente(s), {len(active_agents)} ativo(s).", {"count": len(agents), "active": len(active_agents), "running": len(running_agents)}),
        "playbooks": (
            health.get("playbooks", {}).get("state", "unknown"),
            f"{health.get('playbooks', {}).get('count') or 0} playbook(s) disponível(is).",
            {"count": health.get("playbooks", {}).get("count")},
        ),
        "providers": (
            "available" if selectable else "attention",
            f"{len(selectable)} provedor(es) de IA selecionável(is) de {len(providers)} configurado(s).",
            {"configured": len(providers), "selectable": len(selectable)},
        ),
    }
    for node in nodes:
        key = node.get("runtime_key")
        if key == "skill_store":
            key = "skills"
        if not key or key not in states:
            continue
        state, detail, metrics = states[key]
        node["state"] = state
        node["state_detail"] = detail
        node["metrics"] = metrics


def application_map_payload(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    nodes, edges = _architecture()
    runtime = _runtime(settings)
    _apply_runtime(nodes, runtime)
    return {
        "version": runtime["health"].get("version"),
        "status": runtime["health"].get("status", "attention"),
        "views": [
            {"id": "architecture", "label": "Arquitetura", "description": "Mapa completo dos componentes e dependências da aplicação."},
            {"id": "runtime", "label": "Runtime", "description": "Componentes que participam da operação em tempo de execução."},
            {"id": "data", "label": "Dados", "description": "Persistência, filas, inventário, histórico e registros locais."},
            {"id": "security", "label": "Segurança", "description": "Políticas, confiança SSH, revisão, aprovação e pós-validação."},
        ],
        "categories": CATEGORY_LABELS,
        "nodes": nodes,
        "edges": edges,
        "runtime": {
            "queue_depth": runtime["health"].get("queue", {}).get("depth"),
            "providers_selectable": sum(1 for item in runtime["health"].get("providers") or [] if item.get("selectable")),
            "skills": len(runtime["skills"]),
            "agents": len(runtime["agents"]),
            "agents_active": sum(1 for item in runtime["agents"] if item.get("enabled")),
        },
    }
