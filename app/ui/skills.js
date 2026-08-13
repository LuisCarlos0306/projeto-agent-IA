(() => {
  let skills = [];
  let loaded = false;

  const MODE_LABELS = {
    read_only: "Leitura",
    diagnostic: "Diagnóstico",
    correction: "Correção",
  };

  const ACTION_LABELS = {
    command: "Comando",
    script: "Script",
  };

  function safe(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const modeLabel = (mode) => MODE_LABELS[mode] || "Leitura";
  const actionLabel = (type) => ACTION_LABELS[type] || "Comando";

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

  function ensureHeader() {
    const view = document.querySelector("#view-skills");
    const header = view?.querySelector(".panel-header");
    if (!header || header.querySelector("#create-custom-skill")) return;
    header.querySelector(".mode-badge")?.remove();
    const button = document.createElement("button");
    button.id = "create-custom-skill";
    button.type = "button";
    button.className = "primary-button skill-create-button";
    button.textContent = "+ Criar Skill";
    header.appendChild(button);
    const title = header.querySelector("h3");
    const description = header.querySelector("p:not(.eyebrow)");
    if (title) title.textContent = "Minhas Skills";
    if (description) description.textContent = "Crie Skills com ações controladas e execute informando somente o IP ou servidor.";
  }

  function renderGrid() {
    const grid = document.querySelector("#skills-grid");
    if (!grid) return;
    if (!skills.length) {
      grid.innerHTML = `
        <div class="skills-empty custom-skills-empty">
          <strong>Nenhuma Skill personalizada criada.</strong>
          <span>Clique em “Criar Skill” para cadastrar nome, permissão e ações.</span>
        </div>`;
      return;
    }
    grid.innerHTML = skills.map((skill) => {
      const actionCount = (skill.commands?.length || 0) + (skill.scripts?.length || 0);
      return `
        <article class="skill-card custom-skill-card" data-skill-id="${safe(skill.id)}">
          <div class="skill-card-head">
            <div class="skill-icon" aria-hidden="true">✦</div>
            <div class="custom-skill-card-copy">
              <h4>${safe(skill.name)}</h4>
              <p>${safe(skill.description || "Skill personalizada")}</p>
            </div>
            <div class="custom-skill-card-actions">
              <button class="custom-skill-edit" type="button" data-edit-skill="${safe(skill.id)}" title="Editar Skill" aria-label="Editar Skill ${safe(skill.name)}">✎</button>
              <button class="custom-skill-delete" type="button" data-delete-skill="${safe(skill.id)}" title="Apagar Skill" aria-label="Apagar Skill ${safe(skill.name)}">⌫</button>
            </div>
          </div>
          <div class="skill-card-meta">
            <span class="skill-status active">Ativa</span>
            <span class="skill-chip custom-mode ${safe(skill.mode || "read_only")}">${safe(modeLabel(skill.mode))}</span>
            <span class="skill-chip">${actionCount} ação(ões)</span>
          </div>
          <div class="skill-card-footer">
            <span class="skill-chip">Personalizada</span>
            <button class="skill-open" type="button" data-open-custom-skill="${safe(skill.id)}">Abrir / Executar</button>
          </div>
        </article>`;
    }).join("");
  }

  function actionRow(type, value) {
    return `
      <div class="custom-skill-action-item" data-skill-action-item data-action-type="${safe(type)}" data-action-value="${safe(value)}">
        <span class="custom-action-type ${safe(type)}">${safe(actionLabel(type))}</span>
        <code>${safe(value)}</code>
        <button type="button" data-remove-skill-action title="Remover ação" aria-label="Remover ação">×</button>
      </div>`;
  }

  function initialActions(skill) {
    if (!skill) return [];
    return [
      ...(skill.commands || []).map((value) => ({ type: "command", value })),
      ...(skill.scripts || []).map((value) => ({ type: "script", value })),
    ];
  }

  function editorForm(skill = null) {
    const editing = Boolean(skill);
    const mode = skill?.mode || "read_only";
    const actions = initialActions(skill);
    return `
      <div class="skill-detail-header">
        <div class="skill-detail-title">
          <div class="skill-icon">${editing ? "✎" : "＋"}</div>
          <div>
            <p class="eyebrow">${editing ? "EDITAR SKILL" : "NOVA SKILL"}</p>
            <h3>${editing ? `Editar ${safe(skill.name)}` : "Criar Skill"}</h3>
            <p>Defina a permissão e adicione cada ação escolhendo se ela é um comando ou um script.</p>
          </div>
        </div>
      </div>
      <form id="custom-skill-editor-form" data-skill-id="${safe(skill?.id || "")}" class="custom-skill-editor">
        <div class="custom-skill-editor-grid">
          <label><span>Nome da Skill</span><input name="name" required maxlength="80" value="${safe(skill?.name || "")}" placeholder="Ex.: Validação de Filesystem e backups"></label>
          <label><span>Permissão da Skill</span>
            <select name="mode" required>
              <option value="read_only" ${mode === "read_only" ? "selected" : ""}>Leitura</option>
              <option value="diagnostic" ${mode === "diagnostic" ? "selected" : ""}>Diagnóstico</option>
              <option value="correction" ${mode === "correction" ? "selected" : ""}>Correção</option>
            </select>
          </label>
          <label class="wide"><span>Descrição <small>opcional</small></span><input name="description" maxlength="300" value="${safe(skill?.description || "")}" placeholder="Ex.: Valida filesystem, mounts e espaço"></label>

          <div class="wide custom-action-builder">
            <div class="custom-action-builder-title">
              <div><strong>Ações da Skill</strong><small>Selecione o tipo, informe o comando ou caminho do script e clique em Adicionar.</small></div>
            </div>
            <div class="custom-action-add-row">
              <label><span>Tipo</span>
                <select id="custom-skill-action-type">
                  <option value="command">Comando</option>
                  <option value="script">Script</option>
                </select>
              </label>
              <label class="custom-action-value"><span>Comando ou caminho do script</span><input id="custom-skill-action-value" autocomplete="off" placeholder="Ex.: df -h"></label>
              <button type="button" class="secondary-button" data-add-skill-action>Adicionar</button>
            </div>
            <div id="custom-skill-action-list" class="custom-skill-action-list">
              ${actions.length ? actions.map((item) => actionRow(item.type, item.value)).join("") : '<div class="custom-action-empty">Nenhuma ação adicionada.</div>'}
            </div>
          </div>
        </div>
        <div class="skill-warning custom-mode-warning">
          <strong>Política de execução:</strong> Leitura aceita apenas consultas seguras. Diagnóstico e Correção podem cadastrar comandos e scripts definidos por você; somente ações comprovadamente de leitura executam automaticamente. As demais aguardam aprovação e política do ambiente.
        </div>
        <div class="custom-skill-editor-actions">
          <button type="button" class="ghost-button" data-close-skill-detail>Cancelar</button>
          <button type="submit" class="primary-button">${editing ? "Salvar alterações" : "Criar Skill"}</button>
        </div>
        <div id="custom-skill-editor-message" class="custom-skill-message" hidden></div>
      </form>`;
  }

  function renderEditor(skill = null) {
    const panel = document.querySelector("#skill-detail");
    if (!panel) return;
    panel.hidden = false;
    panel.innerHTML = editorForm(skill);
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function renderSkill(skill) {
    const panel = document.querySelector("#skill-detail");
    if (!panel) return;
    const scripts = skill.scripts || [];
    const commands = skill.commands || [];
    panel.hidden = false;
    panel.innerHTML = `
      <div class="skill-detail-header">
        <div class="skill-detail-title">
          <div class="skill-icon">✦</div>
          <div><p class="eyebrow">SKILL PERSONALIZADA</p><h3>${safe(skill.name)}</h3><p>${safe(skill.description || "Skill personalizada")}</p></div>
        </div>
        <span class="risk-badge ${skill.mode === "correction" ? "approval_required" : "read_only"}">${safe(modeLabel(skill.mode))}</span>
      </div>

      <section class="skill-run-panel custom-skill-run-panel custom-skill-run-prominent">
        <div class="skill-run-head">
          <div><p class="eyebrow">EXECUTAR</p><h4>Informe o IP / Servidor</h4><p>A Skill já contém todas as ações cadastradas. Para executar, preencha somente o alvo.</p></div>
        </div>
        <form id="custom-skill-run-form" data-skill-id="${safe(skill.id)}" class="custom-skill-run-form">
          <label><span>IP / Servidor</span><input name="target" required maxlength="255" autocomplete="off" autofocus placeholder="Ex.: 172.27.232.212"></label>
          <button class="primary-button" type="submit">Executar Skill</button>
        </form>
        <div id="custom-skill-result" class="skill-result" hidden></div>
      </section>

      <div class="custom-skill-command-summary custom-skill-actions-summary">
        <strong>Ações configuradas</strong>
        <div>
          ${commands.map((command) => `<span class="custom-definition-item"><b>Comando</b><code>${safe(command)}</code></span>`).join("")}
          ${scripts.map((script) => `<span class="custom-definition-item"><b>Script</b><code>${safe(script)}</code></span>`).join("")}
          ${!commands.length && !scripts.length ? '<span class="custom-empty-definition">Nenhuma ação.</span>' : ""}
        </div>
      </div>
      ${skill.mode !== "read_only" || scripts.length ? '<div class="skill-warning"><strong>Execução controlada:</strong> ações cadastradas fora do conjunto somente leitura ficam pendentes de aprovação ou da política do ambiente; não são executadas automaticamente.</div>' : ""}`;
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
    setTimeout(() => panel.querySelector('input[name="target"]')?.focus(), 80);
  }

  function renderRunning(detail = "Aguardando worker operacional.") {
    const element = document.querySelector("#custom-skill-result");
    if (!element) return;
    element.hidden = false;
    element.innerHTML = `<div class="skill-running"><span class="skill-running-spinner"></span><div><strong>Executando Skill...</strong><p>${safe(detail)}</p></div></div>`;
  }

  function renderResult(result) {
    const element = document.querySelector("#custom-skill-result");
    if (!element) return;
    const ok = result.status === "healthy";
    const scripts = result.scripts || [];
    const pendingCommands = result.pending_commands || [];
    element.hidden = false;
    element.innerHTML = `
      <div class="skill-result-header">
        <div><p class="eyebrow">RESULTADO</p><h4>${safe(result.name)}</h4><p>${safe(result.resolved_host || result.target || "")}</p></div>
        <span class="skill-overall ${ok ? "healthy" : "attention"}">${ok ? "OK" : "ALERTA"}</span>
      </div>
      <p class="custom-skill-summary">${safe(result.summary || "")}</p>
      <div class="custom-command-results">
        ${(result.commands || []).map((row) => `
          <article class="custom-command-result ${row.exit_code === 0 ? "ok" : "error"}">
            <div class="custom-command-result-head"><code>${safe(row.command)}</code><strong>exit ${safe(row.exit_code)}</strong></div>
            ${row.stdout ? `<pre>${safe(row.stdout)}</pre>` : ""}
            ${row.stderr ? `<pre class="stderr">${safe(row.stderr)}</pre>` : ""}
          </article>`).join("")}
      </div>
      ${pendingCommands.length || scripts.length ? `
        <div class="custom-pending-scripts">
          <strong>Ações protegidas</strong>
          ${pendingCommands.map((row) => `<div class="custom-pending-script"><code>${safe(row.command)}</code><span>${row.status === "blocked_by_policy" ? "Bloqueado pela política" : "Aprovação necessária"}</span>${row.reason ? `<small>${safe(row.reason)}</small>` : ""}</div>`).join("")}
          ${scripts.map((row) => `<div class="custom-pending-script"><code>${safe(row.path)}</code><span>Aprovação necessária</span>${row.reason ? `<small>${safe(row.reason)}</small>` : ""}</div>`).join("")}
          <p>Comandos não seguros e scripts não foram executados automaticamente.</p>
        </div>` : ""}`;
  }

  async function pollJob(jobId) {
    for (let attempt = 0; attempt < 300; attempt += 1) {
      await sleep(1000);
      const job = await requestJson(`/ui/api/skills/custom/jobs/${encodeURIComponent(jobId)}`);
      if (job.status === "completed") return job.result || {};
      if (job.status === "failed") throw new Error(job.error || "Worker não concluiu a Skill.");
      if (job.status === "cancelled") throw new Error("Execução cancelada.");
      renderRunning(job.current_phase?.detail || "Executando ações da Skill.");
    }
    throw new Error("Tempo máximo de acompanhamento excedido.");
  }

  async function submitRun(form) {
    const button = form.querySelector('button[type="submit"]');
    const skillId = form.dataset.skillId;
    const target = String(new FormData(form).get("target") || "").trim();
    button.disabled = true;
    button.textContent = "Executando...";
    renderRunning();
    try {
      const response = await requestJson(`/ui/api/skills/custom/${encodeURIComponent(skillId)}/run`, { method: "POST", body: { target } });
      const result = response.status === "completed" ? response.result : await pollJob(response.job_id);
      renderResult(result || {});
    } catch (error) {
      const element = document.querySelector("#custom-skill-result");
      if (element) {
        element.hidden = false;
        element.innerHTML = `<div class="skill-result-error"><strong>Falha na execução</strong><p>${safe(error.message)}</p></div>`;
      }
    } finally {
      button.disabled = false;
      button.textContent = "Executar Skill";
    }
  }

  function collectActions(form) {
    const rows = [...form.querySelectorAll("[data-skill-action-item]")];
    return {
      commands: rows.filter((row) => row.dataset.actionType === "command").map((row) => row.dataset.actionValue),
      scripts: rows.filter((row) => row.dataset.actionType === "script").map((row) => row.dataset.actionValue),
    };
  }

  function addAction(form) {
    const type = form.querySelector("#custom-skill-action-type")?.value || "command";
    const input = form.querySelector("#custom-skill-action-value");
    const value = String(input?.value || "").trim();
    if (!value) {
      input?.focus();
      return;
    }
    const list = form.querySelector("#custom-skill-action-list");
    list?.querySelector(".custom-action-empty")?.remove();
    if ([...form.querySelectorAll("[data-skill-action-item]")].some((row) => row.dataset.actionType === type && row.dataset.actionValue === value)) {
      input.setCustomValidity("Esta ação já foi adicionada.");
      input.reportValidity();
      input.setCustomValidity("");
      return;
    }
    list?.insertAdjacentHTML("beforeend", actionRow(type, value));
    input.value = "";
    input.placeholder = type === "script" ? "Ex.: /db/backup/scripts/mount.sh" : "Ex.: df -h";
    input.focus();
  }

  async function submitEditor(form) {
    const data = new FormData(form);
    const skillId = form.dataset.skillId;
    const message = form.querySelector("#custom-skill-editor-message");
    const button = form.querySelector('button[type="submit"]');
    const actions = collectActions(form);
    button.disabled = true;
    try {
      const body = {
        name: String(data.get("name") || "").trim(),
        description: String(data.get("description") || "").trim(),
        mode: String(data.get("mode") || "read_only"),
        commands: actions.commands,
        scripts: actions.scripts,
      };
      const response = await requestJson(
        skillId ? `/ui/api/skills/custom/${encodeURIComponent(skillId)}` : "/ui/api/skills/custom",
        { method: skillId ? "PUT" : "POST", body },
      );
      await loadSkills(true);
      const saved = skills.find((item) => item.id === response.skill?.id) || response.skill;
      if (saved) {
        renderSkill(saved);
      } else {
        message.hidden = false;
        message.className = "custom-skill-message success";
        message.textContent = skillId ? "Skill atualizada com sucesso." : "Skill criada com sucesso.";
      }
    } catch (error) {
      message.hidden = false;
      message.className = "custom-skill-message error";
      message.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  }

  async function removeSkill(skillId) {
    const skill = skills.find((item) => item.id === skillId);
    if (!skill) return;
    if (!window.confirm(`Apagar a Skill “${skill.name}”?`)) return;
    await requestJson(`/ui/api/skills/custom/${encodeURIComponent(skillId)}`, { method: "DELETE" });
    const panel = document.querySelector("#skill-detail");
    if (panel) panel.hidden = true;
    await loadSkills(true);
  }

  async function loadSkills(force = false) {
    if (loaded && !force) return;
    ensureHeader();
    const grid = document.querySelector("#skills-grid");
    try {
      const payload = await requestJson("/ui/api/skills/custom");
      skills = payload.skills || [];
      renderGrid();
      loaded = true;
    } catch (error) {
      if (grid) grid.innerHTML = `<div class="skills-empty">${safe(error.message)}</div>`;
    }
  }

  if (typeof viewMeta !== "undefined") viewMeta.skills = ["CAPACIDADES PERSONALIZADAS", "Skills"];

  document.addEventListener("DOMContentLoaded", () => {
    ensureHeader();
    document.querySelector('[data-view="skills"]')?.addEventListener("click", () => loadSkills(true));
    document.querySelector("#view-skills")?.addEventListener("click", (event) => {
      if (event.target.closest("#create-custom-skill")) return renderEditor();
      const edit = event.target.closest("[data-edit-skill]");
      if (edit) {
        const skill = skills.find((item) => item.id === edit.dataset.editSkill);
        if (skill) renderEditor(skill);
        return;
      }
      const open = event.target.closest("[data-open-custom-skill]");
      if (open) {
        const skill = skills.find((item) => item.id === open.dataset.openCustomSkill);
        if (skill) renderSkill(skill);
        return;
      }
      const remove = event.target.closest("[data-delete-skill]");
      if (remove) {
        removeSkill(remove.dataset.deleteSkill).catch((error) => window.alert(error.message));
        return;
      }
      if (event.target.closest("[data-close-skill-detail]")) {
        const panel = document.querySelector("#skill-detail");
        if (panel) panel.hidden = true;
      }
    });

    document.querySelector("#skill-detail")?.addEventListener("click", (event) => {
      const add = event.target.closest("[data-add-skill-action]");
      if (add) {
        const form = add.closest("#custom-skill-editor-form");
        if (form) addAction(form);
        return;
      }
      const remove = event.target.closest("[data-remove-skill-action]");
      if (remove) {
        const row = remove.closest("[data-skill-action-item]");
        const list = row?.parentElement;
        row?.remove();
        if (list && !list.querySelector("[data-skill-action-item]")) {
          list.innerHTML = '<div class="custom-action-empty">Nenhuma ação adicionada.</div>';
        }
      }
    });

    document.querySelector("#skill-detail")?.addEventListener("change", (event) => {
      if (event.target?.id !== "custom-skill-action-type") return;
      const form = event.target.closest("#custom-skill-editor-form");
      const input = form?.querySelector("#custom-skill-action-value");
      if (input) input.placeholder = event.target.value === "script" ? "Ex.: /db/backup/scripts/mount.sh" : "Ex.: df -h";
    });

    document.querySelector("#skill-detail")?.addEventListener("keydown", (event) => {
      if (event.target?.id !== "custom-skill-action-value" || event.key !== "Enter") return;
      event.preventDefault();
      const form = event.target.closest("#custom-skill-editor-form");
      if (form) addAction(form);
    });

    document.querySelector("#skill-detail")?.addEventListener("submit", (event) => {
      if (event.target.id === "custom-skill-editor-form") {
        event.preventDefault();
        submitEditor(event.target);
      } else if (event.target.id === "custom-skill-run-form") {
        event.preventDefault();
        submitRun(event.target);
      }
    });
  });
})();