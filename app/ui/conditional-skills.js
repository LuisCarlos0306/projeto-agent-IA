(() => {
  const cache = new Map();

  const safe = (value) => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

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
    if (!response.ok) throw new Error(typeof payload === "object" ? payload.detail : payload);
    return payload;
  }

  async function refreshSkills() {
    const payload = await requestJson("/ui/api/skills/custom");
    cache.clear();
    (payload.skills || []).forEach((skill) => cache.set(skill.id, skill));
    return payload.skills || [];
  }

  function operatorOptions(selected) {
    const rows = [
      ["exit_code_nonzero", "Agir quando a validação retornar erro / não encontrado"],
      ["exit_code_zero", "Agir quando a validação retornar sucesso"],
      ["stdout_contains", "Agir quando a saída contiver um texto"],
      ["stdout_not_contains", "Agir quando a saída NÃO contiver um texto"],
      ["stdout_empty", "Agir quando a saída estiver vazia"],
      ["stdout_not_empty", "Agir quando a saída tiver conteúdo"],
    ];
    return rows.map(([value, label]) => `<option value="${value}" ${selected === value ? "selected" : ""}>${label}</option>`).join("");
  }

  function conditionalEditor(condition = null) {
    const enabled = Boolean(condition?.enabled);
    const action = condition?.action || {};
    const messages = condition?.messages || {};
    return `
      <section class="conditional-skill" data-conditional-skill>
        <div class="conditional-skill-head">
          <div>
            <span class="conditional-kicker">DECISÃO AUTOMÁTICA</span>
            <strong>Fluxo condicional</strong>
            <small>Valida primeiro. Só propõe a correção quando a regra indicar necessidade.</small>
          </div>
          <label class="conditional-toggle"><input type="checkbox" name="condition_enabled" ${enabled ? "checked" : ""}><span></span><b>${enabled ? "Ativo" : "Desativado"}</b></label>
        </div>
        <div class="conditional-skill-body" ${enabled ? "" : "hidden"}>
          <div class="conditional-flow-strip" aria-label="Fluxo da Skill">
            <span><i>1</i><b>Validação</b></span><em>→</em><span><i>2</i><b>Condição</b></span><em>→</em><span><i>3</i><b>Ação</b></span><em>→</em><span><i>4</i><b>Pós-validação</b></span><em>→</em><span><i>5</i><b>Resultado</b></span>
          </div>
          <div class="conditional-grid">
            <label class="wide"><span>1. Comando de validação <small>somente leitura</small></span><input name="condition_validation" value="${safe(condition?.validation || "")}" placeholder="Ex.: findmnt -M /mnt/backup_check"></label>
            <label class="wide"><span>2. Quando a ação será necessária</span><select name="condition_operator">${operatorOptions(condition?.operator || "exit_code_nonzero")}</select></label>
            <label class="wide conditional-expected" ${["stdout_contains", "stdout_not_contains"].includes(condition?.operator) ? "" : "hidden"}><span>Texto usado na comparação</span><input name="condition_expected" value="${safe(condition?.expected || "")}" placeholder="Texto esperado na saída"></label>
            <label><span>3. Tipo da ação corretiva</span><select name="condition_action_type"><option value="command" ${action.type !== "script" ? "selected" : ""}>Comando</option><option value="script" ${action.type === "script" ? "selected" : ""}>Script</option></select></label>
            <label><span>Comando / script corretivo</span><input name="condition_action_value" value="${safe(action.value || "")}" placeholder="Ex.: /db/backup/scripts/mount.sh"></label>
            <label class="wide"><span>4. Comando de pós-validação <small>somente leitura</small></span><input name="condition_post_validation" value="${safe(condition?.post_validation || "")}" placeholder="Ex.: findmnt -M /mnt/backup_check"></label>
          </div>
          <div class="conditional-messages">
            <label><span>Sem necessidade de ação</span><input name="condition_no_action" value="${safe(messages.no_action || "")}" placeholder="Unidade validada. Nenhuma ação necessária."></label>
            <label><span>Correção confirmada</span><input name="condition_success" value="${safe(messages.success || "")}" placeholder="Montagem executada com sucesso."></label>
            <label><span>Falha após correção</span><input name="condition_failure" value="${safe(messages.failure || "")}" placeholder="A correção não foi confirmada pela pós-validação."></label>
          </div>
          <div class="conditional-policy-note"><strong>Segurança:</strong> a validação e a decisão podem ocorrer automaticamente. A ação corretiva continua sujeita à aprovação e à política do ambiente; a mensagem de sucesso só é válida após a pós-validação.</div>
        </div>
      </section>`;
  }

  async function injectEditor(form) {
    if (!form || form.dataset.conditionalInjected === "1") return;
    form.dataset.conditionalInjected = "1";
    const skillId = form.dataset.skillId || "";
    if (skillId && !cache.has(skillId)) await refreshSkills().catch(() => []);
    const skill = cache.get(skillId);
    const warning = form.querySelector(".custom-mode-warning");
    const actions = form.querySelector(".custom-action-builder");
    const holder = document.createElement("div");
    holder.className = "conditional-skill-holder wide";
    holder.innerHTML = conditionalEditor(skill?.condition || null);
    (warning || actions)?.insertAdjacentElement(warning ? "beforebegin" : "afterend", holder);
    syncConditionalUi(form);
  }

  function syncConditionalUi(form) {
    const enabled = form.querySelector('[name="condition_enabled"]')?.checked;
    const body = form.querySelector(".conditional-skill-body");
    const toggleLabel = form.querySelector(".conditional-toggle b");
    if (body) body.hidden = !enabled;
    if (toggleLabel) toggleLabel.textContent = enabled ? "Ativo" : "Desativado";
    if (enabled) {
      const mode = form.querySelector('[name="mode"]');
      if (mode?.value === "read_only") mode.value = "correction";
    }
    const operator = form.querySelector('[name="condition_operator"]')?.value;
    const expected = form.querySelector(".conditional-expected");
    if (expected) expected.hidden = !["stdout_contains", "stdout_not_contains"].includes(operator);
    const type = form.querySelector('[name="condition_action_type"]')?.value;
    const action = form.querySelector('[name="condition_action_value"]');
    if (action) action.placeholder = type === "script" ? "Ex.: /db/backup/scripts/mount.sh" : "Ex.: systemctl restart servico";
  }

  function collectStandardActions(form) {
    const rows = [...form.querySelectorAll("[data-skill-action-item]")];
    return {
      commands: rows.filter((row) => row.dataset.actionType === "command").map((row) => row.dataset.actionValue),
      scripts: rows.filter((row) => row.dataset.actionType === "script").map((row) => row.dataset.actionValue),
    };
  }

  function collectCondition(form) {
    const data = new FormData(form);
    if (!form.querySelector('[name="condition_enabled"]')?.checked) return { enabled: false };
    return {
      enabled: true,
      validation: String(data.get("condition_validation") || "").trim(),
      operator: String(data.get("condition_operator") || "exit_code_nonzero"),
      expected: String(data.get("condition_expected") || "").trim(),
      action: {
        type: String(data.get("condition_action_type") || "command"),
        value: String(data.get("condition_action_value") || "").trim(),
      },
      post_validation: String(data.get("condition_post_validation") || "").trim(),
      messages: {
        no_action: String(data.get("condition_no_action") || "").trim(),
        success: String(data.get("condition_success") || "").trim(),
        failure: String(data.get("condition_failure") || "").trim(),
      },
    };
  }

  async function submitConditionalEditor(form) {
    const data = new FormData(form);
    const actions = collectStandardActions(form);
    const skillId = form.dataset.skillId || "";
    const message = form.querySelector("#custom-skill-editor-message");
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    try {
      const body = {
        name: String(data.get("name") || "").trim(),
        description: String(data.get("description") || "").trim(),
        mode: String(data.get("mode") || "read_only"),
        commands: actions.commands,
        scripts: actions.scripts,
        condition: collectCondition(form),
      };
      await requestJson(skillId ? `/ui/api/skills/custom/${encodeURIComponent(skillId)}` : "/ui/api/skills/custom", { method: skillId ? "PUT" : "POST", body });
      await refreshSkills();
      if (message) {
        message.hidden = false;
        message.className = "custom-skill-message success";
        message.textContent = skillId ? "Skill atualizada com sucesso." : "Skill criada com sucesso.";
      }
      setTimeout(() => {
        const panel = document.querySelector("#skill-detail");
        if (panel) panel.hidden = true;
        document.querySelector('[data-view="skills"]')?.click();
      }, 450);
    } catch (error) {
      if (message) {
        message.hidden = false;
        message.className = "custom-skill-message error";
        message.textContent = error.message || "Não foi possível salvar a Skill.";
      }
    } finally {
      button.disabled = false;
    }
  }

  async function injectSkillFlow(panel) {
    const run = panel?.querySelector("#custom-skill-run-form");
    if (!run || panel.querySelector(".conditional-skill-summary")) return;
    const skillId = run.dataset.skillId;
    if (!cache.has(skillId)) await refreshSkills().catch(() => []);
    const condition = cache.get(skillId)?.condition;
    if (!condition?.enabled) return;
    const action = condition.action || {};
    const block = document.createElement("section");
    block.className = "conditional-skill-summary";
    block.innerHTML = `
      <div><span>FLUXO CONDICIONAL</span><strong>Validação → decisão → correção → pós-validação</strong></div>
      <div class="conditional-summary-grid">
        <span><b>Validação</b><code>${safe(condition.validation)}</code></span>
        <span><b>Condição</b><small>${safe(condition.operator)}</small></span>
        <span><b>Ação</b><code>${safe(action.value || "—")}</code></span>
        <span><b>Pós-validação</b><code>${safe(condition.post_validation)}</code></span>
      </div>`;
    panel.querySelector(".custom-skill-command-summary")?.insertAdjacentElement("beforebegin", block);
  }

  const observer = new MutationObserver(() => {
    const panel = document.querySelector("#skill-detail");
    const form = panel?.querySelector("#custom-skill-editor-form");
    if (form) injectEditor(form).catch(() => {});
    if (panel && !form) injectSkillFlow(panel).catch(() => {});
  });

  document.addEventListener("DOMContentLoaded", () => {
    refreshSkills().catch(() => []);
    const panel = document.querySelector("#skill-detail");
    if (panel) observer.observe(panel, { childList: true, subtree: true });

    document.addEventListener("change", (event) => {
      if (!event.target.closest("[data-conditional-skill]")) return;
      const form = event.target.closest("#custom-skill-editor-form");
      if (form) syncConditionalUi(form);
    });

    document.addEventListener("submit", (event) => {
      const form = event.target;
      if (form?.id !== "custom-skill-editor-form" || !form.querySelector("[data-conditional-skill]")) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      submitConditionalEditor(form);
    }, true);
  });
})();
