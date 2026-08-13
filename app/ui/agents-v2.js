(() => {
  let agents = [];
  let skills = [];
  let selectedAgentId = null;
  let drawerMode = null;
  let refreshTimer = null;
  const BUSY = new Set(["queued", "running", "cancelling"]);

  const safe = (value) => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  const fmtDate = (value, seconds = false) => {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: seconds ? "medium" : "short" }).format(date);
  };

  const fmtDuration = (ms) => {
    const value = Number(ms);
    if (!Number.isFinite(value) || value < 0) return "—";
    if (value < 1000) return `${Math.round(value)} ms`;
    if (value < 60000) return `${(value / 1000).toFixed(1)} s`;
    return `${(value / 60000).toFixed(1)} min`;
  };

  const intervalLabel = (minutes) => {
    const value = Number(minutes || 0);
    if (value === 1) return "1 minuto";
    if (value < 60) return `${value} minutos`;
    if (value === 60) return "1 hora";
    if (value < 1440 && value % 60 === 0) return `${value / 60} horas`;
    if (value === 1440) return "Diário";
    if (value % 1440 === 0) return `${value / 1440} dias`;
    return `${value} minutos`;
  };

  const stateLabel = (state) => ({
    pending: "Pendente",
    queued: "Pendente",
    running: "Em execução",
    cancelling: "Cancelando",
    completed_success: "Concluído com sucesso",
    completed_error: "Concluído com erro",
    cancelled: "Cancelado",
    healthy: "Concluído com sucesso",
    completed: "Concluído com sucesso",
    attention: "Concluído com sucesso",
    critical: "Concluído com erro",
    failed: "Concluído com erro",
    schedule_error: "Concluído com erro",
    invalid_skill: "Concluído com erro",
  }[state] || state || "Pendente");

  const stateClass = (state) => {
    if (["completed_success", "healthy", "completed", "attention"].includes(state)) return "success";
    if (["completed_error", "critical", "failed", "schedule_error", "invalid_skill"].includes(state)) return "error";
    if (["running", "cancelling"].includes(state)) return "running";
    if (state === "cancelled") return "cancelled";
    return "pending";
  };

  const correctionLabel = (status) => ({
    executed_success: "Correção concluída",
    executed_failed: "Correção com erro",
    executed_unverified: "Correção sem confirmação",
    pending_approval: "Aguardando aprovação",
    blocked: "Correção bloqueada",
    not_needed: "Correção não necessária",
    not_evaluated: "Correção não avaliada",
  }[status] || "Correção não necessária");

  async function requestJson(path, options = {}) {
    const init = { ...options, headers: { ...(options.headers || {}) } };
    if (init.body && typeof init.body !== "string") {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(init.body);
    }
    if ((init.method || "GET").toUpperCase() !== "GET") init.headers["X-Agent-UI"] = "1";
    const response = await fetch(path, init);
    const type = response.headers.get("content-type") || "";
    const payload = type.includes("application/json") ? await response.json() : await response.text();
    if (!response.ok) {
      const detail = typeof payload === "object" ? payload.detail : payload;
      throw new Error(detail || `Erro HTTP ${response.status}`);
    }
    return payload;
  }

  const flowIcon = () => `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="6" r="2"></circle><circle cx="19" cy="6" r="2"></circle><circle cx="12" cy="18" r="2"></circle><path d="M7 6h10M6.5 7.5l4.4 8M17.5 7.5l-4.4 8"></path></svg>`;

  function bindNav(button, view) {
    if (!button || button.dataset.agentsV2Bound === "1") return;
    button.dataset.agentsV2Bound = "1";
    button.addEventListener("click", () => {
      if (typeof showView === "function") showView(view);
      loadAgents(true);
    });
  }

  function ensureShell() {
    document.querySelector('[data-view="agents"]')?.remove();
    document.querySelector('[data-view="agentflow"]')?.remove();
    document.querySelector("#view-agents")?.remove();
    document.querySelector("#view-agentflow")?.remove();

    const dashboard = document.querySelector('[data-view="dashboard"]');
    const agentsNav = document.createElement("button");
    agentsNav.className = "nav-item";
    agentsNav.dataset.view = "agents";
    agentsNav.innerHTML = '<span class="nav-icon">◉</span><span>Agentes IA</span>';
    dashboard?.insertAdjacentElement("afterend", agentsNav);

    const flowNav = document.createElement("button");
    flowNav.className = "nav-item";
    flowNav.dataset.view = "agentflow";
    flowNav.innerHTML = `<span class="nav-icon agent-flow-nav-icon">${flowIcon()}</span><span>Fluxo</span>`;
    agentsNav.insertAdjacentElement("afterend", flowNav);
    bindNav(agentsNav, "agents");
    bindNav(flowNav, "agentflow");

    const topActions = document.querySelector(".topbar-actions");
    document.querySelector("#topbar-agent-flow")?.remove();
    if (topActions) {
      const button = document.createElement("button");
      button.className = "icon-button agent-flow-top-button";
      button.id = "topbar-agent-flow";
      button.type = "button";
      button.title = "Fluxos de execução dos Agentes IA";
      button.setAttribute("aria-label", "Abrir Fluxos de execução");
      button.innerHTML = flowIcon();
      topActions.prepend(button);
      bindNav(button, "agentflow");
    }

    const dashboardView = document.querySelector("#view-dashboard");
    const agentsView = document.createElement("section");
    agentsView.className = "view";
    agentsView.id = "view-agents";
    agentsView.innerHTML = `
      <article class="panel agents-v2-panel">
        <div class="panel-header stacked-mobile agents-v2-header">
          <div><p class="eyebrow">AGENTES IA</p><h3>Gestão dos agentes</h3><p>Lista compacta com estado real. Clique em um agente para abrir configurações, execução e logs.</p></div>
          <button class="primary-button" id="create-scheduled-agent" type="button">+ Criar Agente</button>
        </div>
        <div class="agent-v2-summary" id="agent-list-summary"></div>
        <div class="agent-v2-grid" id="agents-grid"><div class="empty-state">Carregando agentes...</div></div>
      </article>
      <div class="agent-v2-backdrop" id="agent-drawer-backdrop" hidden></div>
      <aside class="agent-v2-drawer" id="agent-detail" hidden aria-hidden="true"></aside>`;
    dashboardView?.insertAdjacentElement("afterend", agentsView);

    const flowView = document.createElement("section");
    flowView.className = "view";
    flowView.id = "view-agentflow";
    flowView.innerHTML = `
      <article class="panel agent-v2-flow-panel">
        <div class="panel-header stacked-mobile">
          <div><p class="eyebrow">FLUXOS DE EXECUÇÃO</p><h3>Fluxo dos Agentes IA</h3><p>Acompanhe etapas, agente em execução, resultado e pontos que dependem de aprovação.</p></div>
          <span class="mode-badge">estrutura preparada para dependências</span>
        </div>
        <div class="agent-v2-flow-note">Dependências entre agentes ainda não estão configuradas. Cada linha representa o fluxo operacional de um agente.</div>
        <div class="agent-v2-flow-list" id="agent-flow-list"><div class="empty-state">Carregando fluxos...</div></div>
      </article>`;
    agentsView.insertAdjacentElement("afterend", flowView);

    if (typeof viewMeta !== "undefined") {
      viewMeta.agents = ["AGENTES IA", "Gestão dos agentes"];
      viewMeta.agentflow = ["FLUXOS DE EXECUÇÃO", "Fluxo dos Agentes IA"];
    }
  }

  const currentState = (agent) => agent.current_execution?.status || agent.display_state || agent.last_status || "pending";

  function lastResultText(agent) {
    const last = agent.last_result;
    if (!last) return "Nenhuma execução concluída.";
    if ((last.execution_state || last.status) === "completed_error") return last.error || last.summary || "Execução concluída com erro.";
    return last.summary || "Execução concluída.";
  }

  function renderSummary() {
    const target = document.querySelector("#agent-list-summary");
    if (!target) return;
    const running = agents.filter((item) => BUSY.has(currentState(item))).length;
    const active = agents.filter((item) => item.enabled).length;
    const errors = agents.filter((item) => stateClass(currentState(item)) === "error").length;
    target.innerHTML = `<span><strong>${agents.length}</strong> agentes</span><span class="ok"><strong>${active}</strong> ativos</span><span class="run"><strong>${running}</strong> em execução</span><span class="err"><strong>${errors}</strong> com último erro</span>`;
  }

  function renderGrid() {
    const grid = document.querySelector("#agents-grid");
    if (!grid) return;
    renderSummary();
    if (!agents.length) {
      grid.innerHTML = '<div class="agents-empty"><strong>Nenhum agente criado.</strong><span>Crie um agente e vincule uma Skill a um servidor.</span></div>';
      return;
    }
    grid.innerHTML = agents.map((agent) => {
      const state = currentState(agent);
      const running = BUSY.has(state);
      return `<button class="agent-v2-card ${agent.enabled ? "enabled" : "disabled"} ${running ? "is-running" : ""}" type="button" data-agent-id="${safe(agent.id)}">
        <div class="agent-v2-card-head"><span class="agent-v2-avatar">AI</span><span class="agent-v2-title"><strong>${safe(agent.name)}</strong><small>${safe(agent.skill_name)} · ${safe(agent.target)}</small></span><span class="agent-v2-schedule-dot ${agent.enabled ? "enabled" : "disabled"}" title="${agent.enabled ? "Agendamento ativo" : "Agendamento parado"}"></span></div>
        <div class="agent-v2-state ${safe(stateClass(state))}">${running ? '<span class="agent-v2-spinner"></span>' : '<span class="agent-v2-state-dot"></span>'}<strong>${safe(stateLabel(state))}</strong>${running && agent.current_execution?.percent != null ? `<small>${safe(agent.current_execution.percent)}%</small>` : ""}</div>
        <div class="agent-v2-last"><span>Última execução</span><strong>${safe(fmtDate(agent.last_run_at))}</strong></div>
        <p>${safe(lastResultText(agent))}</p>
      </button>`;
    }).join("");
  }

  function splitActions(row) {
    const actions = row.actions || [];
    return {
      executed: actions.filter((item) => ["command", "correction"].includes(item.type)),
      pending: actions.filter((item) => ["pending", "script"].includes(item.type)),
    };
  }

  function renderAction(action) {
    const ok = action.status === "success" || action.exit_code === 0;
    return `<div class="agent-v2-action ${ok ? "success" : "error"}"><div><strong>${safe(action.value || action.command || action.path || action.description || "Ação")}</strong><span>${safe(action.status || (ok ? "success" : "error"))}${action.exit_code != null ? ` · exit ${safe(action.exit_code)}` : ""}</span></div>${action.stdout ? `<details><summary>Saída</summary><pre>${safe(action.stdout)}</pre></details>` : ""}${action.stderr ? `<details><summary>Erro do comando</summary><pre>${safe(action.stderr)}</pre></details>` : ""}</div>`;
  }

  function renderHistoryItem(row) {
    const state = row.execution_state || row.status || "completed_success";
    const { executed, pending } = splitActions(row);
    return `<details class="agent-v2-log ${safe(stateClass(state))}"><summary><span class="agent-v2-log-state"><span class="agent-v2-state-dot"></span><strong>${safe(stateLabel(state))}</strong></span><span>${safe(fmtDate(row.completed_at))}</span></summary><div class="agent-v2-log-body">
      <div class="agent-v2-log-meta"><div><span>Início</span><strong>${safe(fmtDate(row.started_at, true))}</strong></div><div><span>Conclusão</span><strong>${safe(fmtDate(row.completed_at, true))}</strong></div><div><span>Duração</span><strong>${safe(fmtDuration(row.duration_ms))}</strong></div><div><span>Job</span><strong>${safe(row.job_id || "—")}</strong></div></div>
      <section><h5>Resultado</h5><p>${safe(row.summary || row.result?.summary || "Sem resumo retornado.")}</p></section>
      <section><h5>Ações realizadas</h5>${executed.length ? executed.map(renderAction).join("") : '<p class="muted">Nenhuma ação executada nesta validação.</p>'}</section>
      ${pending.length ? `<section><h5>Etapas que não foram executadas</h5>${pending.map((item) => `<div class="agent-v2-pending"><strong>${safe(item.value || "Ação")}</strong><span>${safe(item.reason || item.status || "Pendente")}</span></div>`).join("")}</section>` : ""}
      ${row.error ? `<section class="agent-v2-error"><h5>Erro detalhado</h5><p>${safe(row.error)}</p>${row.failure_stage ? `<p><strong>Etapa:</strong> ${safe(row.failure_stage)}</p>` : ""}${row.error_code ? `<p><strong>Código:</strong> ${safe(row.error_code)}</p>` : ""}${row.recommendation ? `<p><strong>Ação recomendada:</strong> ${safe(row.recommendation)}</p>` : ""}</section>` : ""}
      <section class="agent-v2-correction ${safe(row.correction_status || "not_needed")}"><h5>Correção</h5><strong>${safe(correctionLabel(row.correction_status))}</strong><p>${safe(row.correction_message || "Nenhuma correção foi necessária nesta execução.")}</p></section>
    </div></details>`;
  }

  const renderHistory = (history = []) => history.length ? history.slice(0, 5).map(renderHistoryItem).join("") : '<div class="agent-history-empty">Nenhuma execução concluída.</div>';

  function showDrawer() {
    const drawer = document.querySelector("#agent-detail");
    const backdrop = document.querySelector("#agent-drawer-backdrop");
    if (drawer) { drawer.hidden = false; drawer.setAttribute("aria-hidden", "false"); }
    if (backdrop) backdrop.hidden = false;
  }

  function closeDrawer() {
    selectedAgentId = null;
    drawerMode = null;
    const drawer = document.querySelector("#agent-detail");
    const backdrop = document.querySelector("#agent-drawer-backdrop");
    if (drawer) { drawer.hidden = true; drawer.setAttribute("aria-hidden", "true"); }
    if (backdrop) backdrop.hidden = true;
  }

  function renderDrawer(agent, message = "") {
    const drawer = document.querySelector("#agent-detail");
    if (!drawer) return;
    drawerMode = "detail";
    showDrawer();
    const state = currentState(agent);
    const current = agent.current_execution;
    drawer.innerHTML = `<header class="agent-v2-drawer-head"><div><p class="eyebrow">AGENTE IA</p><h3>${safe(agent.name)}</h3><p>${safe(agent.skill_name)} · ${safe(agent.target)}</p></div><button class="icon-button" type="button" data-close-agent-detail aria-label="Fechar">×</button></header>
      ${message ? `<div class="agent-message success">${safe(message)}</div>` : ""}
      <div class="agent-v2-status-row"><span class="agent-v2-status ${safe(stateClass(state))}">${BUSY.has(state) ? '<span class="agent-v2-spinner"></span>' : '<span class="agent-v2-state-dot"></span>'}${safe(stateLabel(state))}</span><span class="agent-v2-enabled ${agent.enabled ? "enabled" : "disabled"}"><span></span>${agent.enabled ? "Agendamento ativo" : "Agendamento parado"}</span></div>
      ${current ? `<section class="agent-v2-current"><div class="agent-v2-spinner large"></div><div><strong>Agente em execução</strong><p>${safe(current.detail || "Executando Skill...")}</p><small>${safe(current.stage || "processamento")} · ${safe(current.percent ?? 0)}%</small></div><div class="agent-v2-progress"><span style="width:${Math.max(2, Math.min(100, Number(current.percent || 0)))}%"></span></div></section>` : ""}
      <div class="agent-v2-detail-grid"><div><span>Skill</span><strong>${safe(agent.skill_name)}</strong></div><div><span>Servidor</span><strong>${safe(agent.target)}</strong></div><div><span>Frequência</span><strong>${safe(intervalLabel(agent.interval_minutes))}</strong></div><div><span>Próximo ciclo</span><strong>${agent.enabled ? safe(fmtDate(agent.next_run_at)) : "—"}</strong></div></div>
      <div class="agent-v2-actions"><button class="agent-v2-control play" type="button" data-run-agent="${safe(agent.id)}" ${BUSY.has(state) || agent.skill_missing ? "disabled" : ""}>▶ <span>Executar</span></button><button class="agent-v2-control stop" type="button" data-stop-agent="${safe(agent.id)}" ${!agent.enabled ? "disabled" : ""}>■ <span>Pausar</span></button><button class="secondary-button" type="button" data-edit-agent="${safe(agent.id)}">Editar</button><button class="ghost-button danger" type="button" data-delete-agent="${safe(agent.id)}">Remover</button></div>
      <section class="agent-v2-last-result"><div class="agent-v2-section-title"><span>ÚLTIMO RESULTADO</span><strong>${safe(stateLabel(agent.last_result?.execution_state || agent.last_result?.status || state))}</strong></div><p>${safe(lastResultText(agent))}</p>${agent.last_error ? `<div class="agent-v2-error"><strong>Erro:</strong> ${safe(agent.last_error)}</div>` : ""}</section>
      <section class="agent-v2-history"><div class="agent-v2-section-title"><span>LOGS</span><strong>Últimas 5 execuções concluídas</strong></div>${renderHistory(agent.history || [])}</section>`;
  }

  function skillOptions(selected = "") {
    if (!skills.length) return '<option value="">Nenhuma Skill disponível</option>';
    return skills.map((skill) => `<option value="${safe(skill.id)}" ${skill.id === selected ? "selected" : ""}>${safe(skill.name)} · ${safe(skill.mode || "read_only")}</option>`).join("");
  }

  function editor(agent = null) {
    selectedAgentId = agent?.id || null;
    drawerMode = "editor";
    const drawer = document.querySelector("#agent-detail");
    if (!drawer) return;
    showDrawer();
    const editing = Boolean(agent);
    const interval = Number(agent?.interval_minutes || 30);
    const presets = [5, 15, 30, 60, 360, 720, 1440];
    const preset = presets.includes(interval) ? String(interval) : "custom";
    drawer.innerHTML = `<header class="agent-v2-drawer-head"><div><p class="eyebrow">${editing ? "EDITAR AGENTE" : "NOVO AGENTE"}</p><h3>${editing ? safe(agent.name) : "Criar Agente"}</h3></div><button class="icon-button" type="button" data-close-agent-detail>×</button></header><form id="agent-editor-form" data-agent-id="${safe(agent?.id || "")}" class="agent-v2-editor"><div class="agent-v2-editor-grid">
      <label><span>Nome do agente</span><input name="name" required maxlength="120" value="${safe(agent?.name || "")}" placeholder="Ex.: Monitor Backup"></label><label><span>Skill</span><select name="skill_id" required>${skillOptions(agent?.skill_id || "")}</select></label><label class="wide"><span>IP / Servidor</span><input name="target" required maxlength="255" value="${safe(agent?.target || "")}" placeholder="172.27.232.212"></label>
      <label><span>Frequência</span><select name="interval_preset" id="agent-interval-preset"><option value="5" ${preset === "5" ? "selected" : ""}>A cada 5 minutos</option><option value="15" ${preset === "15" ? "selected" : ""}>A cada 15 minutos</option><option value="30" ${preset === "30" ? "selected" : ""}>A cada 30 minutos</option><option value="60" ${preset === "60" ? "selected" : ""}>A cada 1 hora</option><option value="360" ${preset === "360" ? "selected" : ""}>A cada 6 horas</option><option value="720" ${preset === "720" ? "selected" : ""}>A cada 12 horas</option><option value="1440" ${preset === "1440" ? "selected" : ""}>Diário</option><option value="custom" ${preset === "custom" ? "selected" : ""}>Personalizado</option></select></label>
      <label id="agent-custom-interval-field" ${preset !== "custom" ? "hidden" : ""}><span>Intervalo personalizado (minutos)</span><input name="custom_interval" type="number" min="1" max="10080" value="${safe(interval)}"></label><label><span>Agendamento</span><span class="agent-checkbox"><input name="enabled" type="checkbox" ${agent?.enabled !== false ? "checked" : ""}> Ativo</span></label>
      </div><div class="agent-safety-note"><strong>Estado correto:</strong> a execução geral e a correção são exibidas separadamente. “Aguardando aprovação” aparece somente na etapa corretiva que realmente depende de aprovação manual.</div><div class="agent-editor-actions"><button type="button" class="ghost-button" data-close-agent-detail>Cancelar</button><button type="submit" class="primary-button">${editing ? "Salvar alterações" : "Criar Agente"}</button></div><div id="agent-editor-message" class="agent-message" hidden></div></form>`;
  }

  function flowStep(label, state, detail = "") {
    return `<div class="agent-v2-flow-step ${safe(state)}"><span class="agent-v2-flow-step-icon"></span><strong>${safe(label)}</strong>${detail ? `<small>${safe(detail)}</small>` : ""}</div>`;
  }

  function renderFlow() {
    const target = document.querySelector("#agent-flow-list");
    if (!target) return;
    if (!agents.length) { target.innerHTML = '<div class="empty-state">Nenhum agente disponível.</div>'; return; }
    target.innerHTML = agents.map((agent) => {
      const state = currentState(agent);
      const current = agent.current_execution;
      const last = agent.last_result;
      const correctionPending = last?.correction_status === "pending_approval";
      const error = stateClass(state) === "error";
      let queue = "pending", skill = "pending", server = "pending", result = "pending";
      if (state === "queued") queue = "active";
      if (["running", "cancelling"].includes(state)) { queue = "success"; skill = "active"; server = "active"; }
      if (!BUSY.has(state) && state !== "pending") { queue = "success"; skill = error ? "error" : "success"; server = error ? "error" : "success"; result = error ? "error" : state === "cancelled" ? "cancelled" : "success"; }
      return `<article class="agent-v2-flow-lane"><header><div><strong>${safe(agent.name)}</strong><span>${safe(agent.skill_name)} · ${safe(agent.target)}</span></div><span class="agent-v2-status ${safe(stateClass(state))}">${BUSY.has(state) ? '<span class="agent-v2-spinner"></span>' : '<span class="agent-v2-state-dot"></span>'}${safe(stateLabel(state))}</span></header><div class="agent-v2-flow-track">${flowStep("Agente", agent.enabled ? "success" : "stopped", agent.enabled ? "Ativo" : "Pausado")}<span class="agent-v2-flow-link"></span>${flowStep("Skill", skill, agent.skill_name)}<span class="agent-v2-flow-link"></span>${flowStep("Fila / Worker", queue, current?.stage || "Worker")}<span class="agent-v2-flow-link"></span>${flowStep("Servidor", server, agent.target)}<span class="agent-v2-flow-link"></span>${flowStep("Resultado", result, BUSY.has(state) ? "Aguardando conclusão" : stateLabel(state))}${correctionPending ? `<span class="agent-v2-flow-link"></span>${flowStep("Aprovação", "approval", "Correção manual pendente")}` : ""}</div></article>`;
    }).join("");
  }

  function scheduleRefresh() {
    clearTimeout(refreshTimer);
    if (!document.querySelector("#view-agents.active, #view-agentflow.active")) return;
    const running = agents.some((item) => BUSY.has(currentState(item)));
    refreshTimer = setTimeout(() => loadAgents(true).catch(() => {}), running ? 1400 : 4500);
  }

  async function loadAgents() {
    ensureShellOnce();
    try {
      const [agentPayload, skillPayload] = await Promise.all([requestJson("/ui/api/agents"), requestJson("/ui/api/skills/custom")]);
      agents = agentPayload.agents || [];
      skills = skillPayload.skills || [];
      renderGrid();
      renderFlow();
      if (selectedAgentId && drawerMode === "detail") {
        const selected = agents.find((item) => item.id === selectedAgentId);
        if (selected) renderDrawer(selected);
      }
      scheduleRefresh();
    } catch (error) {
      const grid = document.querySelector("#agents-grid");
      if (grid) grid.innerHTML = `<div class="agents-empty"><strong>Falha ao carregar agentes</strong><span>${safe(error.message)}</span></div>`;
    }
  }

  async function submitEditor(form) {
    const data = new FormData(form);
    const agentId = form.dataset.agentId;
    const preset = String(data.get("interval_preset") || "30");
    const body = { name: String(data.get("name") || "").trim(), skill_id: String(data.get("skill_id") || "").trim(), target: String(data.get("target") || "").trim(), interval_minutes: preset === "custom" ? Number(data.get("custom_interval") || 30) : Number(preset), enabled: data.get("enabled") === "on" };
    const message = form.querySelector("#agent-editor-message");
    try {
      const response = await requestJson(agentId ? `/ui/api/agents/${encodeURIComponent(agentId)}` : "/ui/api/agents", { method: agentId ? "PUT" : "POST", body });
      await loadAgents(true);
      selectedAgentId = response.agent.id;
      renderDrawer(agents.find((item) => item.id === selectedAgentId) || response.agent, agentId ? "Agente atualizado." : "Agente criado.");
    } catch (error) {
      message.hidden = false;
      message.className = "agent-message error";
      message.textContent = error.message;
    }
  }

  async function runAgent(agentId) {
    await requestJson(`/ui/api/agents/${encodeURIComponent(agentId)}/start`, { method: "POST" });
    await loadAgents(true);
    const current = agents.find((item) => item.id === agentId);
    if (current) renderDrawer(current, "Agente ativado e execução iniciada.");
  }

  async function stopAgent(agentId) {
    await requestJson(`/ui/api/agents/${encodeURIComponent(agentId)}/stop`, { method: "POST" });
    await loadAgents(true);
    const current = agents.find((item) => item.id === agentId);
    if (current) renderDrawer(current, BUSY.has(currentState(current)) ? "Próximos ciclos pausados. A execução atual continuará até terminar." : "Agendamento pausado.");
  }

  async function deleteAgent(agentId) {
    const agent = agents.find((item) => item.id === agentId);
    if (!agent || !window.confirm(`Remover o agente “${agent.name}”?`)) return;
    await requestJson(`/ui/api/agents/${encodeURIComponent(agentId)}`, { method: "DELETE" });
    closeDrawer();
    await loadAgents(true);
  }

  let shellReady = false;
  function ensureShellOnce() { if (!shellReady) { ensureShell(); shellReady = true; bindEvents(); } }

  function bindEvents() {
    document.querySelector("#view-agents")?.addEventListener("click", (event) => {
      if (event.target.closest("#create-scheduled-agent")) { editor(); return; }
      const card = event.target.closest("[data-agent-id]");
      if (card) { selectedAgentId = card.dataset.agentId; drawerMode = "detail"; const agent = agents.find((item) => item.id === selectedAgentId); if (agent) renderDrawer(agent); }
    });
    document.querySelector("#agent-drawer-backdrop")?.addEventListener("click", closeDrawer);
    document.querySelector("#agent-detail")?.addEventListener("click", (event) => {
      if (event.target.closest("[data-close-agent-detail]")) { closeDrawer(); return; }
      const run = event.target.closest("[data-run-agent]"); if (run) { runAgent(run.dataset.runAgent).catch((error) => window.alert(error.message)); return; }
      const stop = event.target.closest("[data-stop-agent]"); if (stop) { stopAgent(stop.dataset.stopAgent).catch((error) => window.alert(error.message)); return; }
      const edit = event.target.closest("[data-edit-agent]"); if (edit) { const agent = agents.find((item) => item.id === edit.dataset.editAgent); if (agent) editor(agent); return; }
      const remove = event.target.closest("[data-delete-agent]"); if (remove) deleteAgent(remove.dataset.deleteAgent).catch((error) => window.alert(error.message));
    });
    document.querySelector("#agent-detail")?.addEventListener("change", (event) => { if (event.target.id === "agent-interval-preset") { const field = document.querySelector("#agent-custom-interval-field"); if (field) field.hidden = event.target.value !== "custom"; } });
    document.querySelector("#agent-detail")?.addEventListener("submit", (event) => { if (event.target.id === "agent-editor-form") { event.preventDefault(); submitEditor(event.target); } });
    document.addEventListener("keydown", (event) => { if (event.key === "Escape" && selectedAgentId) closeDrawer(); });
  }

  document.addEventListener("DOMContentLoaded", () => { ensureShellOnce(); });
})();
