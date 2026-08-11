(() => {
  let catalog = null;
  let loaded = false;

  const statusLabel = (status) => status === "active" ? "Ativa" : status === "planned" ? "Planejada" : status;
  const riskLabel = (risk) => ({
    read_only: "Somente leitura",
    approval_required: "Requer aprovação",
    blocked: "Bloqueada",
  }[risk] || risk);
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
    const response = await fetch("/ui/assets/skills-catalog.json?v=1.0.0", { cache: "no-store" });
    if (!response.ok) throw new Error(`Falha ao carregar skills: HTTP ${response.status}`);
    catalog = await response.json();
    return catalog;
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
    `;
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
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
  });
})();
