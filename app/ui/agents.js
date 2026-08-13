(() => {
  let agents = [];
  let skills = [];
  let loaded = false;

  const safe = (value) => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

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
    cancelling: "Cancelando",
    cancelled: "Cancelado",
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
          <article class="panel">
            <div class="panel-header stacked-mobile agents-panel-header">
              <div>
                <p class="eyebrow">AUTOMAÇÃO POR SKILL</p>
                <h3>Agentes</h3>
                <p>Vincule uma Skill a um servidor e defina quando ela deve executar automaticamente.</p>
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

  function renderGrid() {
    const grid = document.querySelector("#agents-grid");
    if (!grid) return;
    if (!agents.length) {
      grid.innerHTML = `
        <div class="agents-empty">
          <strong>Nenhum agente criado.</strong>
          <span>Crie um agente para executar uma Skill automaticamente em um servidor.</span>
        </div>`;
      return;
    }
    grid.innerHTML = agents.map((agent) => `
      <article class="agent-card ${agent.enabled ? "enabled" : "disabled"}" data-agent-id="${safe(agent.id)}">
        <div class="agent-card-head">
          <div class="agent-card-icon">◈</div>
          <div class="agent-card-copy">
            <h4>${safe(agent.name)}</h4>
            <p>${safe(agent.skill_name)} · ${safe(agent.target)}</p>
          </div>
          <div class="agent-card-icons">
            <button type="button" data-edit-agent="${safe(agent.id)}" title="Editar agente" aria-label="Editar agente">✎</button>
            <button type="button" data-delete-agent="${safe(agent.id)}" title="Apagar agente" aria-label="Apagar agente">⌫</button>
          </div>
        </div>
        <div class="agent-card-meta">
          <span class="agent-state ${agent.enabled ? "enabled" : "disabled"}">${agent.enabled ? "● Habilitado" : "○ Desabilitado"}</span>
          <span class="skill-chip">${safe(intervalLabel(agent.interval_minutes))}</span>
          <span class="status-badge ${safe(statusClass(agent.last_status))}">${safe(statusLabel(agent.last_status))}</span>
        </div>
        <div class="agent-card-kv">
          <div><span>Última execução</span><strong>${safe(formatDate(agent.last_run_at))}</strong></div>
          <div><span>Próxima execução</span><strong>${agent.enabled ? safe(formatDate(agent.next_run_at)) : "—"}</strong></div>
        </div>
        ${agent.last_error ? `<div class="agent-card-error">${safe(agent.last_error)}</div>` : ""}
        ${agent.skill_missing ? '<div class="agent-card-error">A Skill vinculada não existe mais.</div>' : ""}
        <div class="agent-card-actions">
          <button class="secondary-button" type="button" data-run-agent="${safe(agent.id)}" ${agent.skill_missing ? "disabled" : ""}>Executar agora</button>
          <button class="agent-toggle ${agent.enabled ? "on" : "off"}" type="button" data-toggle-agent="${safe(agent.id)}" data-enabled="${agent.enabled ? "1" : "0"}" ${agent.skill_missing ? "disabled" : ""}>
            ${agent.enabled ? "Desabilitar" : "Habilitar"}
          </button>
        </div>
      </article>`).join("");
  }

  function skillOptions(selected = "") {
    if (!skills.length) return '<option value="">Nenhuma Skill disponível</option>';
    return skills.map((skill) => `
      <option value="${safe(skill.id)}" ${skill.id === selected ? "selected" : ""}>${safe(skill.name)} · ${safe(skill.mode || "read_only")}</option>
    `).join("");
  }

  function editor(agent = null) {
    const detail = document.querySelector("#agent-detail");
    if (!detail) return;
    const editing = Boolean(agent);
    const interval = Number(agent?.interval_minutes || 30);
    const presets = [5, 15, 30, 60, 360, 720, 1440];
    const preset = presets.includes(interval) ? String(interval) : "custom";
    detail.hidden = false;
    detail.innerHTML = `
      <div class="agent-detail-head">
        <div><p class="eyebrow">${editing ? "EDITAR AGENTE" : "NOVO AGENTE"}</p><h3>${editing ? safe(agent.name) : "Criar Agente"}</h3><p>A Skill define o que fazer; o Agente define onde e quando executar.</p></div>
      </div>
      <form id="agent-editor-form" data-agent-id="${safe(agent?.id || "")}" class="agent-editor-form">
        <div class="agent-editor-grid">
          <label><span>Nome do agente</span><input name="name" required maxlength="120" value="${safe(agent?.name || "")}" placeholder="Ex.: Monitor Backup Cliente A"></label>
          <label><span>Skill</span><select name="skill_id" required>${skillOptions(agent?.skill_id || "")}</select></label>
          <label class="wide"><span>IP / Servidor</span><input name="target" required maxlength="255" value="${safe(agent?.target || "")}" placeholder="172.27.232.212"></label>
          <label><span>Frequência</span>
            <select name="interval_preset" id="agent-interval-preset">
              <option value="5" ${preset === "5" ? "selected" : ""}>A cada 5 minutos</option>
              <option value="15" ${preset === "15" ? "selected" : ""}>A cada 15 minutos</option>
              <option value="30" ${preset === "30" ? "selected" : ""}>A cada 30 minutos</option>
              <option value="60" ${preset === "60" ? "selected" : ""}>A cada 1 hora</option>
              <option value="360" ${preset === "360" ? "selected" : ""}>A cada 6 horas</option>
              <option value="720" ${preset === "720" ? "selected" : ""}>A cada 12 horas</option>
              <option value="1440" ${preset === "1440" ? "selected" : ""}>Diário</option>
              <option value="custom" ${preset === "custom" ? "selected" : ""}>Personalizado</option>
            </select>
          </label>
          <label id="agent-custom-interval-field" ${preset !== "custom" ? "hidden" : ""}><span>Intervalo personalizado (minutos)</span><input name="custom_interval" type="number" min="1" max="10080" value="${safe(interval)}"></label>
          <label class="agent-enabled-field"><span>Estado inicial</span><span class="agent-checkbox"><input name="enabled" type="checkbox" ${agent?.enabled !== false ? "checked" : ""}> Habilitado</span></label>
        </div>
        <div class="agent-safety-note">
          <strong>Automação segura:</strong> a Skill pode conter comandos e scripts definidos por você, mas o Agente executa automaticamente apenas comandos comprovadamente somente leitura. As demais ações ficam aguardando aprovação ou são bloqueadas pela política do ambiente.
        </div>
        <div class="agent-editor-actions">
          <button type="button" class="ghost-button" data-close-agent-detail>Cancelar</button>
          <button type="submit" class="primary-button">${editing ? "Salvar alterações" : "Criar Agente"}</button>
        </div>
        <div id="agent-editor-message" class="agent-message" hidden></div>
      </form>`;
    detail.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function detailView(agent) {
    const detail = document.querySelector("#agent-detail");
    if (!detail) return;
    detail.hidden = false;
    detail.innerHTML = `
      <div class="agent-detail-head">
        <div><p class="eyebrow">AGENTE</p><h3>${safe(agent.name)}</h3><p>${safe(agent.skill_name)} em ${safe(agent.target)}</p></div>
        <span class="agent-state ${agent.enabled ? "enabled" : "disabled"}">${agent.enabled ? "● Habilitado" : "○ Desabilitado"}</span>
      </div>
      <div class="agent-detail-grid">
        <div><span>Skill</span><strong>${safe(agent.skill_name)}</strong></div>
        <div><span>Servidor</span><strong>${safe(agent.target)}</strong></div>
        <div><span>Frequência</span><strong>${safe(intervalLabel(agent.interval_minutes))}</strong></div>
        <div><span>Último status</span><strong>${safe(statusLabel(agent.last_status))}</strong></div>
        <div><span>Última execução</span><strong>${safe(formatDate(agent.last_run_at))}</strong></div>
        <div><span>Próxima execução</span><strong>${agent.enabled ? safe(formatDate(agent.next_run_at)) : "—"}</strong></div>
      </div>
      ${agent.last_summary ? `<div class="agent-last-summary"><strong>Último resultado</strong><p>${safe(agent.last_summary)}</p></div>` : ""}
      <div class="agent-detail-actions">
        <button type="button" class="secondary-button" data-run-agent="${safe(agent.id)}" ${agent.skill_missing ? "disabled" : ""}>Executar agora</button>
        <button type="button" class="secondary-button" data-edit-agent="${safe(agent.id)}">Editar</button>
        <button type="button" class="agent-toggle ${agent.enabled ? "on" : "off"}" data-toggle-agent="${safe(agent.id)}" data-enabled="${agent.enabled ? "1" : "0"}" ${agent.skill_missing ? "disabled" : ""}>${agent.enabled ? "Desabilitar" : "Habilitar"}</button>
        <button type="button" class="ghost-button" data-close-agent-detail>Fechar</button>
      </div>
      <div id="agent-run-message" class="agent-message" hidden></div>`;
    detail.scrollIntoView({ behavior: "smooth", block: "start" });
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
    } catch (error) {
      if (grid) grid.innerHTML = `<div class="agents-empty"><strong>Falha ao carregar agentes</strong><span>${safe(error.message)}</span></div>`;
    }
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
      const response = await requestJson(
        agentId ? `/ui/api/agents/${encodeURIComponent(agentId)}` : "/ui/api/agents",
        { method: agentId ? "PUT" : "POST", body },
      );
      await loadAgents(true);
      const saved = response.agent;
      message.hidden = false;
      message.className = "agent-message success";
      message.textContent = agentId ? "Agente atualizado." : "Agente criado.";
      setTimeout(() => detailView(saved), 450);
    } catch (error) {
      message.hidden = false;
      message.className = "agent-message error";
      message.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  }

  async function toggleAgent(agentId, currentlyEnabled) {
    await requestJson(`/ui/api/agents/${encodeURIComponent(agentId)}/toggle`, {
      method: "POST",
      body: { enabled: !currentlyEnabled },
    });
    await loadAgents(true);
    const current = agents.find((item) => item.id === agentId);
    if (current && !document.querySelector("#agent-detail")?.hidden) detailView(current);
  }

  async function runAgent(agentId) {
    const detail = document.querySelector("#agent-detail");
    let message = document.querySelector("#agent-run-message");
    if (!message && detail && !detail.hidden) {
      message = document.createElement("div");
      message.id = "agent-run-message";
      message.className = "agent-message";
      detail.appendChild(message);
    }
    if (message) {
      message.hidden = false;
      message.className = "agent-message pending";
      message.textContent = "Enviando execução para o Worker...";
    }
    const queued = await requestJson(`/ui/api/agents/${encodeURIComponent(agentId)}/run-now`, { method: "POST" });
    if (message) message.textContent = `Job ${queued.job_id} enviado para a fila.`;
    await loadAgents(true);
  }

  async function deleteAgent(agentId) {
    const agent = agents.find((item) => item.id === agentId);
    if (!agent || !window.confirm(`Apagar o agente “${agent.name}”?`)) return;
    await requestJson(`/ui/api/agents/${encodeURIComponent(agentId)}`, { method: "DELETE" });
    const detail = document.querySelector("#agent-detail");
    if (detail) detail.hidden = true;
    await loadAgents(true);
  }

  document.addEventListener("DOMContentLoaded", () => {
    ensureShell();
    document.querySelector("#view-agents")?.addEventListener("click", (event) => {
      if (event.target.closest("#create-scheduled-agent")) return editor();
      const edit = event.target.closest("[data-edit-agent]");
      if (edit) {
        const agent = agents.find((item) => item.id === edit.dataset.editAgent);
        if (agent) editor(agent);
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