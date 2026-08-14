from pathlib import Path

from app.services.application_map import application_map_payload


ROOT = Path(__file__).resolve().parents[1]


def test_application_map_exposes_full_architecture_and_views(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.application_map._runtime",
        lambda settings: {
            "health": {
                "status": "healthy",
                "version": "test",
                "database": {"state": "available", "detail": "ok"},
                "queue": {"state": "available", "detail": "ok", "depth": 0, "execution_mode": "queue"},
                "providers": [{"selectable": True}],
                "playbooks": {"state": "available", "count": 2},
                "worker": {"state": "external", "detail": "worker"},
            },
            "skills": [{"id": "skill-1"}],
            "agents": [{"id": "agent-1", "enabled": True, "last_status": "running"}],
        },
    )
    payload = application_map_payload()
    ids = {node["id"] for node in payload["nodes"]}
    views = {view["id"] for view in payload["views"]}

    assert {"architecture", "runtime", "data", "security"} == views
    assert {
        "ui",
        "fastapi",
        "orchestrator",
        "skills",
        "playbooks",
        "agents",
        "scheduler",
        "ai_router",
        "reviewer",
        "policies",
        "redis",
        "postgres",
        "worker",
        "runner",
        "ssh",
        "post_validation",
        "servers",
        "audit",
    }.issubset(ids)
    assert any(edge["kind"] == "async" for edge in payload["edges"])
    assert any(edge["kind"] == "security" for edge in payload["edges"])
    assert any(edge["kind"] == "ssh" for edge in payload["edges"])
    assert payload["runtime"]["agents_active"] == 1
    assert payload["runtime"]["skills"] == 1


def test_application_map_ui_replaces_agent_flow_and_has_graph_controls() -> None:
    script = (ROOT / "app" / "ui" / "application-map.js").read_text(encoding="utf-8")
    style = (ROOT / "app" / "ui" / "application-map.css").read_text(encoding="utf-8")
    web = (ROOT / "app" / "web_application_map.py").read_text(encoding="utf-8")
    fast = (ROOT / "app" / "web_fast_validation.py").read_text(encoding="utf-8")
    cache = (ROOT / "app" / "web_ui_cache.py").read_text(encoding="utf-8")

    assert "/ui/api/application-map" in script
    assert "Arquitetura do Agent IA" in script
    assert "MAPA DA APLICAÇÃO" in script
    assert "data-map-action=\"zoom-in\"" in script
    assert "data-map-action=\"zoom-out\"" in script
    assert "data-map-action=\"fit\"" in script
    assert "data-map-action=\"center\"" in script
    assert "pointermove" in script
    assert "app-map-minimap" in script
    assert 'document.querySelector("#topbar-agent-flow")?.remove()' in script
    assert "OPERAÇÃO" in script
    assert "AUTOMAÇÃO" in script
    assert "AMBIENTE" in script
    assert "PLATAFORMA" in script
    assert "overflow-y:auto" in style
    assert "app-map-viewport" in style
    assert "app-map-detail" in style
    assert 'APIRouter(prefix="/ui/api/application-map"' in web
    assert '"application-map.css"' in fast
    assert '"application-map.js"' in fast
    assert "application-map.css?v={_ASSET_VERSION}" in cache
    assert "application-map.js?v={_ASSET_VERSION}" in cache


def test_application_map_preserves_correction_guardrails() -> None:
    service = (ROOT / "app" / "services" / "application_map.py").read_text(encoding="utf-8")
    approvals = (ROOT / "app" / "services" / "approvals.py").read_text(encoding="utf-8")
    execution = (ROOT / "app" / "services" / "approved_execution.py").read_text(encoding="utf-8")

    assert "Aprovação humana" in service
    assert "Segunda IA / Revisão" in service
    assert "Pós-validação" in service
    assert "known_hosts / SSH trust" in service
    assert "action_digest" in approvals
    assert "environment_allows_correction" in execution
