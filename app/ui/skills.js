(() => {
  let catalog = null;
  let loaded = false;

  const statusLabel = (status) => status === "active" ? "Ativa" : status === "planned" ? "Planejada" : status;
  const riskLabel = (risk) => ({
    read_only: "Somente leitura",
    approval_required: "Requer aprovação",
    blocked: "Bloqueada",
  }[risk] || risk);
  const resultStatusLabel = (status) => ({
    healthy: "OK",
    attention: "ALERTA",
    critical: "CRÍTICO",
    inconclusive: "NÃO VALIDADO",
  }[status] || status || "NÃO VALIDADO");
  const iconFor = (skill) => ({
    backup_validation: "✓",
    linux_diagnostics: "⌁",
    backup_operations: "⚙",
    database_backup: "◉",
  }[skill.id] || "◇");

  function safe(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  async function fetchCatalog() {
    if (catalog) return catalog;
    const response = await fetch("/ui/assets/skills-catalog.json?v=1.1.0", { cache: "no-store" });
    if (!response.ok) throw new Error(`Falha ao carregar skills: HTTP ${response.status}`);
    catalog = await response.json();
    return catalog;
  }

  async function requestJson(path, options = {}) {
    const init = { ...options, headers: { ...(options.headers || {}) } };
    if (init.body && typeof init.body !== "string") {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(init.body);
    }
    if ((init.method || "GET").toUpperCase() !== "GET") init.headers["X-Agent-UI"] = "1";
    const response = await fetch(path, init);
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json") ? await response.json() : await response.text();
    if (!response.ok) {
      const detail = typeof payload === "object" ? payload.detail : payload;
      throw new Error(detail || `Erro HTTP ${response.status}`);
    }
    return payload;
  }

  function renderCards(skills) {
    const grid = document.querySelector("#skills-grid");
    if (!grid) return;
    if (!skills.length) {
      grid.innerHTML = '<div class="skills-empty">Nenhuma skill cadastrada.</div>';
      return;
    }
    grid.innerHTML = skills.map((skill) => `
      <article class="skill-card" data-skill-id="${safe(skill.id)}">
        <div class="skill-card-head">
          <div class="skill-icon" aria-hidden="true">${safe(iconFor(skill))}</div>
          <div>
            <h4>${safe(skill.display_name)}</h4>
            <p>${safe(skill.description)}</p>
          </div>
        </div>
        <div class="skill-card-meta">
          <span class="skill-status ${safe(skill.status)}">${safe(statusLabel(skill.status))}</span>
          <span class="skill-chip">v${safe(skill.version)}</span>
          <span class="skill-chip">${safe(skill.category)}</span>
        </div>
        <div class="skill-card-footer">
          <span class="skill-chip">${safe(skill.scope)}</span>
          <button class="skill-open" type="button" data-open-skill="${safe(skill.id)}" ${skill.status !== "active" ? "disabled" : ""}>${skill.status === "active" ? "Abrir" : "Em breve"}</button>
        </div>
      </article>
    `).join("");
  }

  function dependencyTags(values) {
    if (!values?.length) return '<span class="skill-chip">Nenhuma dependência cadastrada</span>';
    return values.map((item) => `<span class="skill-chip">${safe(item)}</span>`).join("");
  }

  function backupExecutionPanel(skill) {
    if (skill.id !== "backup_validation") return "";
    return `
      <section class="skill-run-panel">
        <div class="skill-run-head">
          <div>
            <p class="eyebrow">EXECUÇÃO CONTROLADA</p>
            <h4>Validar backup no servidor</h4>
            <p>Somente consultas são executadas. Nenhuma montagem ou alteração é realizada nesta etapa.</p>
          </div>
          <span class="risk-badge read_only">Somente leitura</span>
        </div>
        <form id="backup-validation-form" class="skill-run-form">
          <div class="skill-form-grid">
            <label><span>Servidor / IP</span><input name="target" required maxlength="255" placeholder="172.27.232.203 ou host do inventário" autocomplete="off"></label>
            <label><span>Porta SSH</span><input name="ssh_port" type="number" min="1" max="65535" placeholder="Automática"></label>
            <label><span>Ambiente</span><select name="environment"><option value="unknown">Não informado</option><option value="production">Produção</option><option value="standby">Standby</option><option value="monitoring">Monitoramento</option><option value="training">Treinamento</option></select></label>
            <label><span>Ponto de montagem</span><input name="mount_point" required placeholder="/mnt/backup_check"></label>
            <label class="skill-field-wide"><span>Diretório do backup</span><input name="backup_path" required placeholder="/mnt/backup_check/oracle/logico/WINT"></label>
            <label class="skill-field-wide"><span>Diretório de redundância <small>opcional</small></span><input name="redundancy_path" placeholder="/mnt/hdexterno/oracle/logico/WINT"></label>
            <label><span>Espaço livre mínimo (%)</span><input name="min_free_percent" type="number" min="1" max="99" value="20" required></label>
            <label><span>Idade máxima do backup (h)</span><input name="max_backup_age_hours" type="number" min="1" max="2160" value="30" required></label>
            <label><span>Janela de retenção (dias)</span><input name="retention_days" type="number" min="1" max="365" value="7" required></label>
            <label><span>Mínimo de arquivos/pontos</span><input name="min_restore_points" type="number" min="1" max="500" value="1" required></label>
          </div>
          <div class="skill-run-actions">
            <span class="skill-run-note">A retenção desta primeira versão é genérica por arquivos recentes e poderá ser especializada por cliente.</span>
            <button class="primary-button" type="submit" id="backup-validation-submit">Executar validação</button>
          </div>
        </form>
        <div id="backup-validation-result" class="skill-result" hidden></div>
      </section>
    `;
  }

  function renderDetail(skill) {
    const panel = document.querySelector("#skill-detail");
    if (!panel) return;
    const actions = skill.actions || [];
    const readOnly = actions.filter((item) => item.risk === "read_only" && item.enabled).length;
    const approval = actions.filter((item) => item.risk === "approval_required").length;
    panel.hidden = false;
    panel.innerHTML = `
      <div class="skill-detail-header">
        <div class="skill-detail-title">
          <div class="skill-icon" aria-hidden="true">${safe(iconFor(skill))}</div>
          <div>
            <p class="eyebrow">SKILL ATIVA</p>
            <h3>${safe(skill.display_name)}</h3>
            <p>${safe(skill.description)}</p>
          </div>
        </div>
        <div class="skill-card-meta">
          <span class="skill-status active">Ativa</span>
          <span class="skill-chip">v${safe(skill.version)}</span>
          <span class="skill-chip">${safe(skill.mode)}</span>
        </div>
      </div>
      <div class="skill-detail-grid">
        <section class="skill-subpanel">
          <h4>Ações configuradas</h4>
          <div class="skill-actions-list">
            ${actions.map((action) => `
              <div class="skill-action">
                <div>
                  <strong>${safe(action.label)}</strong>
                  <p>${safe(action.description)}${action.command ? `<br><code>${safe(action.command)}</code>` : ""}</p>
                </div>
                <span class="risk-badge ${safe(action.risk)}">${safe(riskLabel(action.risk))}${action.enabled ? "" : " · não habilitada"}</span>
              </div>
            `).join("") || '<div class="skills-empty">Nenhuma ação cadastrada.</div>'}
          </div>
        </section>
        <aside class="skill-subpanel">
          <h4>Resumo da skill</h4>
          <div class="skill-kv">
            <div class="skill-kv-row"><span>Escopo</span><strong>${safe(skill.scope)}</strong></div>
            <div class="skill-kv-row"><span>Consultas liberadas</span><strong>${readOnly}</strong></div>
            <div class="skill-kv-row"><span>Ações com aprovação</span><strong>${approval}</strong></div>
            <div class="skill-kv-row"><span>Execução corretiva</span><strong>${approval ? "Protegida" : "Não configurada"}</strong></div>
          </div>
          <h4 style="margin-top:18px">Comandos permitidos</h4>
          <div class="skill-dependency-list">${dependencyTags(skill.dependencies?.commands)}</div>
          <h4 style="margin-top:18px">Scripts conhecidos</h4>
          <div class="skill-dependency-list">${dependencyTags(skill.dependencies?.scripts)}</div>
          ${approval ? '<div class="skill-warning">A execução operacional permanece bloqueada nesta etapa. O catálogo apenas registra que a ação exige aprovação humana explícita, segunda IA e pós-validação.</div>' : ""}
        </aside>
      </div>
      ${backupExecutionPanel(skill)}
    `;
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function checkRow(key, check) {
    return `
      <div class="skill-result-row">
        <div class="skill-result-main">
          <span class="skill-result-dot ${safe(check.status)}"></span>
          <div><strong>${safe(check.label || key)}</strong><p>${safe(check.detail || "")}</p></div>
        </div>
        <span class="skill-result-badge ${safe(check.status)}">${safe(resultStatusLabel(check.status))}</span>
      </div>
    `;
  }

  function renderValidationResult(result) {
    const element = document.querySelector("#backup-validation-result");
    if (!element) return;
    const checks = result.checks || {};
    const order = ["filesystem", "mount", "space", "retention", "last_backup", "redundancy"];
    const action = result.action_available;
    element.hidden = false;
    element.innerHTML = `
      <div class="skill-result-header">
        <div>
          <p class="eyebrow">RESULTADO</p>
          <h4>${safe(result.target || result.resolved_host || "Servidor")}</h4>
          <p>${safe(result.resolved_host || "")} · SSH ${safe(result.ssh_port || "-")} · ${safe(result.environment || "unknown")}</p>
        </div>
        <span class="skill-overall ${safe(result.status)}">${safe(resultStatusLabel(result.status))}</span>
      </div>
      <div class="skill-result-list">
        ${order.filter((key) => checks[key]).map((key) => checkRow(key, checks[key])).join("")}
      </div>
      ${action ? `
        <div class="skill-action-suggestion">
          <div>
            <strong>${safe(action.label)}</strong>
            <p>${safe(action.detail)}</p>
            <code>${safe(action.command)}</code>
          </div>
          <button class="secondary-button" type="button" disabled title="Aguardando integração da aprovação operacional">Solicitar montagem</button>
        </div>
      ` : ""}
    `;
    element.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function renderRunning() {
    const element = document.querySelector("#backup-validation-result");
    if (!element) return;
    element.hidden = false;
    element.innerHTML = '<div class="skill-running"><span class="skill-running-spinner"></span><div><strong>Validando backup...</strong><p>Conectando ao alvo e executando apenas consultas permitidas.</p></div></div>';
  }

  async function submitBackupValidation(form) {
    const button = form.querySelector("#backup-validation-submit");
    const data = new FormData(form);
    const numberOrNull = (name) => {
      const value = String(data.get(name) || "").trim();
      return value ? Number(value) : null;
    };
    const body = {
      target: String(data.get("target") || "").trim(),
      environment: String(data.get("environment") || "unknown"),
      ssh_port: numberOrNull("ssh_port"),
      mount_point: String(data.get("mount_point") || "").trim(),
      backup_path: String(data.get("backup_path") || "").trim(),
      redundancy_path: String(data.get("redundancy_path") || "").trim() || null,
      min_free_percent: Number(data.get("min_free_percent") || 20),
      max_backup_age_hours: Number(data.get("max_backup_age_hours") || 30),
      retention_days: Number(data.get("retention_days") || 7),
      min_restore_points: Number(data.get("min_restore_points") || 1),
    };
    button.disabled = true;
    button.textContent = "Validando...";
    renderRunning();
    try {
      const response = await requestJson("/ui/api/skills/backup-validation/run", { method: "POST", body });
      renderValidationResult(response.result || response);
    } catch (error) {
      const element = document.querySelector("#backup-validation-result");
      if (element) {
        element.hidden = false;
        element.innerHTML = `<div class="skill-result-error"><strong>Falha na validação</strong><p>${safe(error.message)}</p></div>`;
      }
    } finally {
      button.disabled = false;
      button.textContent = "Executar validação";
    }
  }

  async function loadSkills() {
    if (loaded) return;
    const grid = document.querySelector("#skills-grid");
    try {
      const data = await fetchCatalog();
      renderCards(data.skills || []);
      loaded = true;
    } catch (error) {
      if (grid) grid.innerHTML = `<div class="skills-empty">${safe(error.message)}</div>`;
    }
  }

  if (typeof viewMeta !== "undefined") {
    viewMeta.skills = ["CAPACIDADES DO AGENTE", "Skills"];
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelector('[data-view="skills"]')?.addEventListener("click", loadSkills);
    document.querySelector("#skills-grid")?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-open-skill]");
      if (!button || !catalog) return;
      const skill = (catalog.skills || []).find((item) => item.id === button.dataset.openSkill);
      if (skill) renderDetail(skill);
    });
    document.querySelector("#skill-detail")?.addEventListener("submit", (event) => {
      if (event.target?.id !== "backup-validation-form") return;
      event.preventDefault();
      submitBackupValidation(event.target);
    });
  });
})();
