(() => {
  let agents = [];
  let skills = [];
  let loaded = false;
  let selectedAgentId = null;
  let refreshTimer = null;
  const liveRuns = new Map();
  const BUSY_STATES = new Set(["queued", "running", "cancelling"]);

  const safe = (value) => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  const formatDate = (value) => {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" }).format(date);
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

  const statusLabel = (status) => ({
    healthy: "OK",
    attention: "Alerta",
    critical: "Crítico",
    completed: "Concluído",
    queued: "Na fila",
    running: "Executando",
    cancelling: "Parando",
    cancelled: "Interrompido",
    failed: "Falhou",
    schedule_error: "Falha no agendamento",
    invalid_skill: "Skill removida",
  }[status] || status || "Nunca executado");

  const statusClass = (status) => {
    if (["healthy", "completed"].includes(status)) return "healthy";
    if (["failed", "critical", "schedule_error", "invalid_skill"].includes(status)) return "critical";
    if (["attention", "queued", "running", "cancelling"].includes(status)) return "attention";
    return "inconclusive";
  };

  const correctionLabel = (status) => ({
    executed_success: "Correção OK",
    executed_failed: "Correção falhou",
    executed_unverified: "Aguardando confirmação",
    pending_approval: "Aguardando aprovação",
    blocked: "Bloqueada",
    not_needed: "Sem correção",
    not_evaluated: "Não avaliada",
  }[status] || "Sem correção");

  const correctionClass = (status) => ({
    executed_success: "success",
    executed_failed: "error",
    executed_unverified: "warning",
    pending_approval: "warning",
    blocked: "error",
    not_needed: "neutral",
    not_evaluated: "neutral",
  }[status] || "neutral");

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

  function ensureShell() {
    if (!document.querySelector('[data-view="agents"]')) {
      const skillsNav = document.querySelector('[data-view="skills"]');
      const button = document.createElement("button");
      button.className = "nav-item";
      button.dataset.view = "agents";
      button.innerHTML = '<span class="nav-icon">◈</span><span>Agentes</span>';
      skillsNav?.insertAdjacentElement("afterend", button);
      button.addEventListener("click", () => {
        if (typeof showView === "function") showView("agents");
        loadAgents(true);
      });
    }

    if (!document.querySelector("#view-agents")) {
      const skillsView = document.querySelector("#view-skills");
      const section = document.createElement("section");
      section.className = "view";
      section.id = "view-agents";
      section.innerHTML = `
        <div class="agents-layout">
          <article class="panel agents-main-panel">
            <div class="panel-header stacked-mobile agents-panel-header">
              <div>
                <p class="eyebrow">AUTOMAÇÃO POR SKILL</p>
                <h3>Agentes</h3>
                <p>Play ativa e executa imediatamente; depois o Agente segue sozinho no intervalo configurado.</p>
              </div>
              <button class="primary-button" id="create-scheduled-agent" type="button">+ Criar Agente</button>
            </div>
            <div class="agents-grid" id="agents-grid"><div class="empty-state">Abra esta seção para carregar os agentes.</div></div>
          </article>
          <article class="panel agent-detail-panel" id="agent-detail" hidden></article>
        </div>`;
      skillsView?.insertAdjacentElement("afterend", section);
    }
    if (typeof viewMeta !== "undefined") viewMeta.agents = ["AUTOMAÇÃO POR SKILL", "Agentes"];
  }

  function renderHistory(history = [], compact = false) {
    const rows = (history || []).slice(0, 5);
    if (!rows.length) return '<div class="agent-history-empty">Nenhuma validação concluída.</div>';
    return `<div class="agent-history-list ${compact ? "compact" : ""}">
      ${rows.map((row) => `
        <div class="agent-history-row">
          <div class="agent-history-top">
            <span>${safe(formatDate(row.completed_at))}</span>
            <span class="status-badge ${safe(statusClass(row.status))}">${safe(statusLabel(row.status))}</span>
          </div>
          ${row.summary ? `<p>${safe(row.summary)}</p>` : ""}
          <div class="agent-correction ${safe(correctionClass(row.correction_status))}">
            <strong>${safe(correctionLabel(row.correction_status))}</strong>
            ${row.correction_message ? `<span>${safe(row.correction_message)}</span>` : ""}
          </div>
        </div>`).join("")}
    </div>`;
  }

  function liveStatus(agent) {
    const browserLive = liveRuns.get(agent.id);
    if (browserLive) return browserLive;
    if (!BUSY_STATES.has(String(agent.last_status || ""))) return null;
    const status = String(agent.last_status || "running");
    return {
      status,
      detail: status === "queued"
        ? "Execução automática aguardando o Worker..."
        : status === "cancelling"
          ? "Execução em processo de encerramento..."
          : "Agente executando a Skill no servidor...",
      percent: null,
      jobId: agent.last_job_id || null,
      automatic: true,
    };
  }

  const isBusy = (agent) => Boolean(liveStatus(agent));

  function renderGrid() {
    const grid = document.querySelector("#agents-grid");
    if (!grid) return;
    if (!agents.length) {
      grid.innerHTML = '<div class="agents-empty"><strong>Nenhum agente criado.</strong><span>Crie um agente para executar uma Skill automaticamente em um servidor.</span></div>';
      return;
    }

    grid.innerHTML = agents.map((agent) => {
      const live = liveStatus(agent);
      const effectiveStatus = live?.status || agent.last_status;
      const busy = Boolean(live);
      return `
        <article class="agent-card ${agent.enabled ? "enabled" : "disabled"}" data-agent-id="${safe(agent.id)}">
          <div class="agent-card-layout">
            <div class="agent-card-main">
              <div class="agent-card-head">
                <div class="agent-card-icon">◈</div>
                <div class="agent-card-copy"><p class="eyebrow">AGENTE</p><h4>${safe(agent.name)}</h4></div>
                <button class="agent-live-indicator ${agent.enabled ? "enabled" : "disabled"}" type="button" data-toggle-agent="${safe(agent.id)}" data-enabled="${agent.enabled ? "1" : "0"}" title="${agent.enabled ? "Desativar agendamento" : "Ativar agendamento"}">
                  <span class="agent-indicator-dot"></span>${agent.enabled ? "Ativo" : "Parado"}
                </button>
                <div class="agent-card-icons">
                  <button type="button" data-edit-agent="${safe(agent.id)}" title="Editar agente" aria-label="Editar agente">✎</button>
                  <button type="button" data-delete-agent="${safe(agent.id)}" title="Apagar agente" aria-label="Apagar agente">⌫</button>
                </div>
              </div>

              <div class="agent-info-grid">
                <div><span>Skill</span><strong>${safe(agent.skill_name)}</strong></div>
                <div><span>Servidor</span><strong>${safe(agent.target)}</strong></div>
                <div><span>Frequência</span><strong>${safe(intervalLabel(agent.interval_minutes))}</strong></div>
                <div><span>Status</span><strong class="status-text ${safe(statusClass(effectiveStatus))}">${safe(statusLabel(effectiveStatus))}</strong></div>
                <div><span>Última execução concluída</span><strong>${safe(formatDate(agent.last_run_at))}</strong></div>
                <div><span>Próximo ciclo</span><strong>${agent.enabled ? safe(formatDate(agent.next_run_at)) : "—"}</strong></div>
              </div>

              ${live ? `<div class="agent-live-run"><span class="agent-live-spinner"></span><div><strong>${safe(statusLabel(live.status))}</strong><p>${safe(live.detail)}</p>${live.percent != null ? `<small>${safe(live.percent)}%</small>` : ""}</div></div>` : ""}
              ${agent.last_error && !busy ? `<div class="agent-card-error">${safe(agent.last_error)}</div>` : ""}
              ${agent.skill_missing ? '<div class="agent-card-error">A Skill vinculada não existe mais.</div>' : ""}

              <div class="agent-card-actions agent-icon-actions">
                <button class="agent-control play" type="button" data-run-agent="${safe(agent.id)}" title="Ativar e executar agora" aria-label="Ativar e executar agente agora" ${agent.skill_missing || busy ? "disabled" : ""}>▶</button>
                <button class="agent-control stop" type="button" data-stop-agent="${safe(agent.id)}" title="Parar próximos ciclos" aria-label="Parar agendamento" ${!agent.enabled ? "disabled" : ""}>■</button>
                <span class="agent-control-hint">Play ativa + executa agora · Stop pausa os próximos ciclos</span>
              </div>
            </div>

            <aside class="agent-mini-history">
              <div class="agent-history-title"><span>HISTÓRICO</span><strong>Últimas 5 validações concluídas</strong></div>
              ${renderHistory(agent.history || [], true)}
            </aside>
          </div>
        </article>`;
    }).join("");
  }

  function skillOptions(selected = "") {
    if (!skills.length) return '<option value="">Nenhuma Skill disponível</option>';
    return skills.map((skill) => `<option value="${safe(skill.id)}" ${skill.id === selected ? "selected" : ""}>${safe(skill.name)} · ${safe(skill.mode || "read_only")}</option>`).join("");
  }

  function editor(agent = null) {
    const detail = document.querySelector("#agent-detail");
    if (!detail) return;
    selectedAgentId = null;
    const editing = Boolean(agent);
    const interval = Number(agent?.interval_minutes || 30);
    const presets = [5, 15, 30, 60, 360, 720, 1440];
    const preset = presets.includes(interval) ? String(interval) : "custom";
    detail.hidden = false;
    detail.innerHTML = `
      <div class="agent-detail-head"><div><p class="eyebrow">${editing ? "EDITAR AGENTE" : "NOVO AGENTE"}</p><h3>${editing ? safe(agent.name) : "Criar Agente"}</h3><p>A Skill define o que fazer; o Agente define onde e a frequência.</p></div></div>
      <form id="agent-editor-form" data-agent-id="${safe(agent?.id || "")}" class="agent-editor-form">
        <div class="agent-editor-grid">
          <label><span>Nome do agente</span><input name="name" required maxlength="120" value="${safe(agent?.name || "")}" placeholder="Ex.: Monitor Backup Cliente A"></label>
          <label><span>Skill</span><select name="skill_id" required>${skillOptions(agent?.skill_id || "")}</select></label>
          <label class="wide"><span>IP / Servidor</span><input name="target" required maxlength="255" value="${safe(agent?.target || "")}" placeholder="172.27.232.212"></label>
          <label><span>Frequência</span><select name="interval_preset" id="agent-interval-preset">
            <option value="5" ${preset === "5" ? "selected" : ""}>A cada 5 minutos</option>
            <option value="15" ${preset === "15" ? "selected" : ""}>A cada 15 minutos</option>
            <option value="30" ${preset === "30" ? "selected" : ""}>A cada 30 minutos</option>
            <option value="60" ${preset === "60" ? "selected" : ""}>A cada 1 hora</option>
            <option value="360" ${preset === "360" ? "selected" : ""}>A cada 6 horas</option>
            <option value="720" ${preset === "720" ? "selected" : ""}>A cada 12 horas</option>
            <option value="1440" ${preset === "1440" ? "selected" : ""}>Diário</option>
            <option value="custom" ${preset === "custom" ? "selected" : ""}>Personalizado</option>
          </select></label>
          <label id="agent-custom-interval-field" ${preset !== "custom" ? "hidden" : ""}><span>Intervalo personalizado (minutos)</span><input name="custom_interval" type="number" min="1" max="10080" value="${safe(interval)}"></label>
          <label class="agent-enabled-field"><span>Estado inicial</span><span class="agent-checkbox"><input name="enabled" type="checkbox" ${agent?.enabled !== false ? "checked" : ""}> Ativo</span></label>
        </div>
        <div class="agent-safety-note"><strong>Execução controlada:</strong> o Play ativa o agendamento e executa imediatamente. Ações corretivas só aparecem como sucesso depois da execução autorizada e da pós-validação.</div>
        <div class="agent-editor-actions"><button type="button" class="ghost-button" data-close-agent-detail>Cancelar</button><button type="submit" class="primary-button">${editing ? "Salvar alterações" : "Criar Agente"}</button></div>
        <div id="agent-editor-message" class="agent-message" hidden></div>
      </form>`;
    detail.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function detailView(agent, transientMessage = "") {
    const detail = document.querySelector("#agent-detail");
    if (!detail) return;
    selectedAgentId = agent.id;
    const live = liveStatus(agent);
    const latest = (agent.history || [])[0];
    detail.hidden = false;
    detail.innerHTML = `
      <div class="agent-detail-head">
        <div><p class="eyebrow">AGENTE</p><h3>${safe(agent.name)}</h3><p>Execução vinculada à Skill <strong>${safe(agent.skill_name)}</strong></p></div>
        <button class="agent-live-indicator ${agent.enabled ? "enabled" : "disabled"}" type="button" data-toggle-agent="${safe(agent.id)}" data-enabled="${agent.enabled ? "1" : "0"}"><span class="agent-indicator-dot"></span>${agent.enabled ? "Ativo" : "Parado"}</button>
      </div>

      <div class="agent-detail-layout">
        <div>
          <div class="agent-detail-grid">
            <div><span>Skill vinculada</span><strong>${safe(agent.skill_name)}</strong></div>
            <div><span>Servidor</span><strong>${safe(agent.target)}</strong></div>
            <div><span>Frequência</span><strong>${safe(intervalLabel(agent.interval_minutes))}</strong></div>
            <div><span>Status da validação</span><strong class="status-text ${safe(statusClass(live?.status || agent.last_status))}">${safe(statusLabel(live?.status || agent.last_status))}</strong></div>
            <div><span>Última execução concluída</span><strong>${safe(formatDate(agent.last_run_at))}</strong></div>
            <div><span>Próximo ciclo</span><strong>${agent.enabled ? safe(formatDate(agent.next_run_at)) : "—"}</strong></div>
          </div>

          ${live ? `<div class="agent-live-run detail"><span class="agent-live-spinner"></span><div><strong>${safe(statusLabel(live.status))}</strong><p>${safe(live.detail)}</p>${live.percent != null ? `<small>${safe(live.percent)}%</small>` : ""}</div></div>` : ""}
          ${!live && agent.last_summary ? `<div class="agent-last-summary"><strong>Último resultado da validação</strong><p>${safe(agent.last_summary)}</p></div>` : ""}
          ${!live && latest ? `<div class="agent-correction-result ${safe(correctionClass(latest.correction_status))}"><span>RESULTADO DA CORREÇÃO</span><strong>${safe(correctionLabel(latest.correction_status))}</strong><p>${safe(latest.correction_message || "")}</p></div>` : ""}
          ${transientMessage ? `<div class="agent-message success">${safe(transientMessage)}</div>` : ""}

          <div class="agent-detail-actions agent-icon-actions">
            <button class="agent-control play" type="button" data-run-agent="${safe(agent.id)}" title="Ativar e executar agora" aria-label="Ativar e executar agente agora" ${agent.skill_missing || live ? "disabled" : ""}>▶</button>
            <button class="agent-control stop" type="button" data-stop-agent="${safe(agent.id)}" title="Parar próximos ciclos" aria-label="Parar agendamento" ${!agent.enabled ? "disabled" : ""}>■</button>
            <button type="button" class="secondary-button" data-edit-agent="${safe(agent.id)}">Editar</button>
            <button type="button" class="ghost-button" data-close-agent-detail>Fechar</button>
          </div>
          <div id="agent-run-message" class="agent-message" hidden></div>
        </div>

        <aside class="agent-detail-history"><div class="agent-history-title"><span>LOG</span><strong>Últimas 5 validações concluídas</strong></div>${renderHistory(agent.history || [])}</aside>
      </div>`;
    detail.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function refreshSelectedDetail() {
    if (!selectedAgentId) return;
    const detail = document.querySelector("#agent-detail");
    if (!detail || detail.hidden || detail.querySelector("#agent-editor-form")) return;
    const selected = agents.find((item) => item.id === selectedAgentId);
    if (selected) detailView(selected);
  }

  async function refreshAgents() {
    const payload = await requestJson("/ui/api/agents");
    agents = payload.agents || [];
    renderGrid();
    refreshSelectedDetail();
  }

  async function loadAgents(force = false) {
    if (loaded && !force) return;
    ensureShell();
    const grid = document.querySelector("#agents-grid");
    try {
      const [agentPayload, skillPayload] = await Promise.all([
        requestJson("/ui/api/agents"),
        requestJson("/ui/api/skills/custom"),
      ]);
      agents = agentPayload.agents || [];
      skills = skillPayload.skills || [];
      renderGrid();
      loaded = true;
      refreshSelectedDetail();
    } catch (error) {
      if (grid) grid.innerHTML = `<div class="agents-empty"><strong>Falha ao carregar agentes</strong><span>${safe(error.message)}</span></div>`;
    }
  }

  function startAutoRefresh() {
    if (refreshTimer) return;
    refreshTimer = window.setInterval(() => {
      const view = document.querySelector("#view-agents");
      if (!view?.classList.contains("active") || document.visibilityState !== "visible") return;
      refreshAgents().catch(() => {});
    }, 2000);
  }

  async function submitEditor(form) {
    const data = new FormData(form);
    const agentId = form.dataset.agentId;
    const preset = String(data.get("interval_preset") || "30");
    const interval = preset === "custom" ? Number(data.get("custom_interval") || 30) : Number(preset);
    const body = {
      name: String(data.get("name") || "").trim(),
      skill_id: String(data.get("skill_id") || "").trim(),
      target: String(data.get("target") || "").trim(),
      interval_minutes: interval,
      enabled: data.get("enabled") === "on",
    };
    const button = form.querySelector('button[type="submit"]');
    const message = form.querySelector("#agent-editor-message");
    button.disabled = true;
    try {
      const response = await requestJson(agentId ? `/ui/api/agents/${encodeURIComponent(agentId)}` : "/ui/api/agents", { method: agentId ? "PUT" : "POST", body });
      await loadAgents(true);
      detailView(response.agent, agentId ? "Agente atualizado." : "Agente criado.");
    } catch (error) {
      message.hidden = false;
      message.className = "agent-message error";
      message.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  }

  async function toggleAgent(agentId, currentlyEnabled) {
    await requestJson(`/ui/api/agents/${encodeURIComponent(agentId)}/toggle`, { method: "POST", body: { enabled: !currentlyEnabled } });
    await refreshAgents();
    const current = agents.find((item) => item.id === agentId);
    if (current && selectedAgentId === agentId) detailView(current, current.enabled ? "Agendamento ativado. O próximo ciclo seguirá o intervalo configurado." : "Agendamento parado.");
  }

  async function stopAgent(agentId) {
    const response = await requestJson(`/ui/api/agents/${encodeURIComponent(agentId)}/stop`, { method: "POST" });
    await refreshAgents();
    const current = agents.find((item) => item.id === agentId);
    if (current && selectedAgentId === agentId) {
      detailView(current, response.running_execution_continues ? "Agendamento parado. A execução atual continuará até finalizar." : "Agendamento parado.");
    }
  }

  function updateLive(agentId, job) {
    liveRuns.set(agentId, {
      status: String(job.status || "running"),
      detail: String(job.current_phase?.detail || "Aguardando retorno do Worker..."),
      percent: job.percent == null ? null : Number(job.percent),
      jobId: job.job_id,
      automatic: false,
    });
    renderGrid();
    refreshSelectedDetail();
  }

  async function pollAgentJob(agentId, jobId) {
    for (let attempt = 0; attempt < 600; attempt += 1) {
      const job = await requestJson(`/ui/api/skills/custom/jobs/${encodeURIComponent(jobId)}`);
      updateLive(agentId, job);
      if (["completed", "failed", "cancelled"].includes(String(job.status || ""))) {
        liveRuns.delete(agentId);
        await refreshAgents();
        const current = agents.find((item) => item.id === agentId);
        if (current && selectedAgentId === agentId) {
          detailView(current, job.status === "completed" ? "Execução finalizada. O log foi registrado e o próximo ciclo permanece agendado." : `Execução ${statusLabel(job.status).toLowerCase()}.`);
        }
        return job;
      }
      await sleep(1000);
    }
    liveRuns.delete(agentId);
    await refreshAgents();
    throw new Error("Tempo máximo de acompanhamento excedido.");
  }

  async function runAgent(agentId) {
    if (liveRuns.has(agentId)) return;
    const queued = await requestJson(`/ui/api/agents/${encodeURIComponent(agentId)}/start`, { method: "POST" });
    if (queued.agent) {
      const index = agents.findIndex((item) => item.id === agentId);
      const updated = { ...queued.agent, last_status: queued.status, last_job_id: queued.job_id };
      if (index >= 0) agents[index] = updated;
    }
    updateLive(agentId, queued);
    await refreshAgents();
    try {
      await pollAgentJob(agentId, queued.job_id);
    } catch (error) {
      liveRuns.delete(agentId);
      await refreshAgents();
      const message = document.querySelector("#agent-run-message");
      if (message) {
        message.hidden = false;
        message.className = "agent-message error";
        message.textContent = error.message;
      } else {
        window.alert(error.message);
      }
    }
  }

  async function deleteAgent(agentId) {
    const agent = agents.find((item) => item.id === agentId);
    if (!agent || !window.confirm(`Apagar o agente “${agent.name}”?`)) return;
    await requestJson(`/ui/api/agents/${encodeURIComponent(agentId)}`, { method: "DELETE" });
    liveRuns.delete(agentId);
    if (selectedAgentId === agentId) selectedAgentId = null;
    const detail = document.querySelector("#agent-detail");
    if (detail) detail.hidden = true;
    await refreshAgents();
  }

  document.addEventListener("DOMContentLoaded", () => {
    ensureShell();
    startAutoRefresh();

    document.querySelector("#view-agents")?.addEventListener("click", (event) => {
      if (event.target.closest("#create-scheduled-agent")) return editor();

      const edit = event.target.closest("[data-edit-agent]");
      if (edit) {
        const agent = agents.find((item) => item.id === edit.dataset.editAgent);
        if (agent) editor(agent);
        return;
      }

      const stop = event.target.closest("[data-stop-agent]");
      if (stop) {
        stopAgent(stop.dataset.stopAgent).catch((error) => window.alert(error.message));
        return;
      }

      const toggle = event.target.closest("[data-toggle-agent]");
      if (toggle) {
        toggleAgent(toggle.dataset.toggleAgent, toggle.dataset.enabled === "1").catch((error) => window.alert(error.message));
        return;
      }

      const run = event.target.closest("[data-run-agent]");
      if (run) {
        runAgent(run.dataset.runAgent).catch((error) => window.alert(error.message));
        return;
      }

      const remove = event.target.closest("[data-delete-agent]");
      if (remove) {
        deleteAgent(remove.dataset.deleteAgent).catch((error) => window.alert(error.message));
        return;
      }

      if (event.target.closest("[data-close-agent-detail]")) {
        selectedAgentId = null;
        const detail = document.querySelector("#agent-detail");
        if (detail) detail.hidden = true;
        return;
      }

      const card = event.target.closest(".agent-card");
      if (card && !event.target.closest("button")) {
        const agent = agents.find((item) => item.id === card.dataset.agentId);
        if (agent) detailView(agent);
      }
    });

    document.querySelector("#agent-detail")?.addEventListener("change", (event) => {
      if (event.target.id === "agent-interval-preset") {
        const field = document.querySelector("#agent-custom-interval-field");
        if (field) field.hidden = event.target.value !== "custom";
      }
    });

    document.querySelector("#agent-detail")?.addEventListener("submit", (event) => {
      if (event.target.id !== "agent-editor-form") return;
      event.preventDefault();
      submitEditor(event.target);
    });
  });
})();
