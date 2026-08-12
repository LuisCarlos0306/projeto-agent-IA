(() => {
  const DEFAULT_MOUNT_SCRIPT = "/db/backup/scripts/mount.sh";

  function safe(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

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

  function unitRow(unit = {}) {
    const role = unit.role || "principal";
    return `
      <div class="storage-map-unit">
        <label><span>Função</span><select data-map-role>
          <option value="principal" ${role === "principal" ? "selected" : ""}>Principal</option>
          <option value="redundancia" ${role === "redundancia" ? "selected" : ""}>Redundância</option>
          <option value="externa" ${role === "externa" ? "selected" : ""}>Externa</option>
          <option value="outro" ${role === "outro" ? "selected" : ""}>Outro</option>
        </select></label>
        <label><span>Nome</span><input data-map-label value="${safe(unit.label || "")}" placeholder="Ex.: NAS backup"></label>
        <label class="skill-field-wide"><span>Ponto de montagem</span><input data-map-path value="${safe(unit.mount_point || "")}" placeholder="/mnt/backup_check" required></label>
        <label><span>Livre mínimo (%)</span><input data-map-free type="number" min="1" max="99" value="${safe(unit.min_free_percent || 20)}"></label>
        <button class="ghost-button storage-map-remove" type="button" data-remove-storage-unit>Remover</button>
      </div>
    `;
  }

  function mappingPanel() {
    return `
      <section class="skill-run-panel storage-mapping-panel" id="backup-storage-mapping-panel">
        <div class="skill-run-head">
          <div>
            <p class="eyebrow">CONFIGURAÇÃO MANUAL · UMA VEZ</p>
            <h4>Mapear unidades do servidor</h4>
            <p>Cadastre o script e as unidades esperadas. Depois disso a validação diária precisa somente do servidor/IP.</p>
          </div>
          <span class="risk-badge read_only">Configuração local</span>
        </div>
        <div class="skill-run-form">
          <div class="skill-form-grid">
            <label><span>Servidor / IP</span><input id="storage-map-target" maxlength="255" placeholder="172.27.232.212"></label>
            <label class="skill-field-wide"><span>Script de montagem</span><input id="storage-map-script" value="${DEFAULT_MOUNT_SCRIPT}" readonly></label>
          </div>
          <div class="storage-map-head">
            <strong>Unidades esperadas</strong>
            <button class="secondary-button" id="storage-map-add" type="button">Adicionar unidade</button>
          </div>
          <div id="storage-map-units">${unitRow()}</div>
          <div class="skill-run-actions">
            <span class="skill-run-note" id="storage-map-status">O mapeamento fica salvo no Agent IA e não executa nenhum comando no servidor.</span>
            <div class="storage-map-buttons">
              <button class="ghost-button" id="storage-map-load" type="button">Carregar mapeamento</button>
              <button class="primary-button" id="storage-map-save" type="button">Salvar mapeamento</button>
            </div>
          </div>
        </div>
      </section>
    `;
  }

  function replaceExecutionForm(form) {
    if (!form || form.dataset.mappedStorageUi === "1") return;
    form.dataset.mappedStorageUi = "1";
    form.innerHTML = `
      <div class="skill-form-grid">
        <label><span>Servidor / IP</span><input name="target" required maxlength="255" placeholder="172.27.232.212 ou host do inventário" autocomplete="off"></label>
        <label><span>Porta SSH</span><input name="ssh_port" type="number" min="1" max="65535" placeholder="Automática"></label>
        <label><span>Ambiente</span><select name="environment"><option value="unknown">Não informado</option><option value="production">Produção</option><option value="standby">Standby</option><option value="monitoring">Monitoramento</option><option value="training">Treinamento</option></select></label>
      </div>
      <div class="skill-warning skill-field-wide"><strong>Validação por mapeamento</strong><br>Filesystem, unidades e script não são solicitados nesta tela. O Agent consulta o cadastro salvo para este servidor e verifica todas as unidades esperadas.</div>
      <div class="skill-run-actions">
        <span class="skill-run-note">Se tudo estiver correto, o retorno será “Nenhuma necessidade de atuação”. Se uma unidade estiver desmontada, o Agent solicitará validação antes de qualquer ação.</span>
        <button class="primary-button" type="submit" id="backup-validation-submit">Validar servidor</button>
      </div>
    `;

    const panel = form.closest(".skill-run-panel");
    if (panel && !document.querySelector("#backup-storage-mapping-panel")) {
      panel.insertAdjacentHTML("beforebegin", mappingPanel());
    }
  }

  function collectUnits() {
    return [...document.querySelectorAll("#storage-map-units .storage-map-unit")].map((row) => ({
      role: row.querySelector("[data-map-role]")?.value || "outro",
      label: row.querySelector("[data-map-label]")?.value.trim() || "",
      mount_point: row.querySelector("[data-map-path]")?.value.trim() || "",
      min_free_percent: Number(row.querySelector("[data-map-free]")?.value || 20),
    }));
  }

  function fillMapping(mapping) {
    const target = document.querySelector("#storage-map-target");
    const script = document.querySelector("#storage-map-script");
    const units = document.querySelector("#storage-map-units");
    if (target) target.value = mapping.target || "";
    if (script) script.value = mapping.mount_script || DEFAULT_MOUNT_SCRIPT;
    if (units) units.innerHTML = (mapping.units || []).map(unitRow).join("") || unitRow();
  }

  function mappingStatus(message, error = false) {
    const element = document.querySelector("#storage-map-status");
    if (!element) return;
    element.textContent = message;
    element.style.fontWeight = "600";
    element.dataset.state = error ? "error" : "ok";
  }

  async function loadMapping() {
    const target = document.querySelector("#storage-map-target")?.value.trim() || "";
    if (!target) return mappingStatus("Informe o servidor/IP para carregar o mapeamento.", true);
    try {
      const mapping = await requestJson(`/ui/api/skills/backup-validation/mappings/${encodeURIComponent(target)}`);
      fillMapping(mapping);
      mappingStatus(`Mapeamento carregado: ${(mapping.units || []).length} unidade(s).`);
    } catch (error) {
      mappingStatus(error.message, true);
    }
  }

  async function saveMapping() {
    const target = document.querySelector("#storage-map-target")?.value.trim() || "";
    if (!target) return mappingStatus("Informe o servidor/IP.", true);
    const units = collectUnits();
    if (!units.length || units.some((unit) => !unit.mount_point)) {
      return mappingStatus("Informe o ponto de montagem de todas as unidades.", true);
    }
    const button = document.querySelector("#storage-map-save");
    if (button) button.disabled = true;
    try {
      const response = await requestJson("/ui/api/skills/backup-validation/mappings", {
        method: "POST",
        body: { target, mount_script: DEFAULT_MOUNT_SCRIPT, units },
      });
      fillMapping(response.mapping || {});
      mappingStatus(`Mapeamento salvo: ${(response.mapping?.units || []).length} unidade(s). Nenhum comando foi executado no servidor.`);
      const executionTarget = document.querySelector('#backup-validation-form [name="target"]');
      if (executionTarget && !executionTarget.value) executionTarget.value = target;
    } catch (error) {
      mappingStatus(error.message, true);
    } finally {
      if (button) button.disabled = false;
    }
  }

  function resultStatus(status) {
    return ({ healthy: "OK", attention: "ALERTA", critical: "CRÍTICO", inconclusive: "NÃO VALIDADO" })[status] || status || "NÃO VALIDADO";
  }

  function renderMappedResult(result) {
    const element = document.querySelector("#backup-validation-result");
    if (!element) return;
    const units = result.units || [];
    element.hidden = false;
    element.innerHTML = `
      <div class="skill-result-header">
        <div><p class="eyebrow">RESULTADO</p><h4>${safe(result.target || result.resolved_host || "Servidor")}</h4><p>${safe(result.operator_message || "")}</p></div>
        <span class="skill-overall ${safe(result.status)}">${safe(resultStatus(result.status))}</span>
      </div>
      <div class="skill-result-list">
        ${units.map((unit) => `
          <div class="skill-result-row">
            <div class="skill-result-main"><span class="skill-result-dot ${safe(unit.status)}"></span><div><strong>${safe(unit.label || unit.mount_point)}</strong><p>${safe(unit.role)} · ${safe(unit.detail)}</p></div></div>
            <span class="skill-result-badge ${safe(unit.status)}">${safe(resultStatus(unit.status))}</span>
          </div>
        `).join("")}
      </div>
      <div class="skill-warning"><strong>Script mapeado</strong><br><code>${safe(result.mapping?.mount_script || DEFAULT_MOUNT_SCRIPT)}</code></div>
      ${result.action_required ? `
        <div class="skill-action-suggestion">
          <div><strong>Atuação necessária</strong><p>${safe(result.action_available?.detail || "Solicite validação da montagem.")}</p></div>
          <button class="secondary-button" type="button" disabled>Solicitar validação</button>
        </div>
      ` : `<div class="skill-warning"><strong>Nenhuma necessidade de atuação</strong><br>Todas as unidades mapeadas estão disponíveis. Nenhuma montagem foi executada.</div>`}
    `;
  }

  function renderRunning(detail = "Consultando mapeamento e validando as unidades do servidor.", percent = null) {
    const element = document.querySelector("#backup-validation-result");
    if (!element) return;
    element.hidden = false;
    element.innerHTML = `<div class="skill-running"><span class="skill-running-spinner"></span><div><strong>Validando servidor...</strong><p>${safe(detail)}${percent != null ? ` · ${safe(percent)}%` : ""}</p></div></div>`;
  }

  async function pollJob(jobId) {
    for (let attempt = 0; attempt < 300; attempt += 1) {
      await sleep(1000);
      const job = await requestJson(`/ui/api/skills/jobs/${encodeURIComponent(jobId)}`);
      if (job.status === "completed") return job.result || {};
      if (job.status === "failed") throw new Error(job.error || "Worker não concluiu a validação.");
      if (job.status === "cancelled") throw new Error("Validação cancelada.");
      renderRunning(job.current_phase?.detail || "Aguardando worker operacional.", job.percent);
    }
    throw new Error("A validação excedeu o tempo máximo de acompanhamento.");
  }

  async function validateMappedServer(form) {
    const data = new FormData(form);
    const target = String(data.get("target") || "").trim();
    const port = String(data.get("ssh_port") || "").trim();
    const button = form.querySelector("#backup-validation-submit");
    if (button) {
      button.disabled = true;
      button.textContent = "Validando...";
    }
    renderRunning();
    try {
      const response = await requestJson("/ui/api/skills/backup-validation/run", {
        method: "POST",
        body: {
          target,
          environment: String(data.get("environment") || "unknown"),
          ssh_port: port ? Number(port) : null,
        },
      });
      const result = response.status === "completed" ? (response.result || response) : await pollJob(response.job_id);
      renderMappedResult(result);
    } catch (error) {
      const element = document.querySelector("#backup-validation-result");
      if (element) {
        element.hidden = false;
        element.innerHTML = `<div class="skill-result-error"><strong>Falha na validação</strong><p>${safe(error.message)}</p></div>`;
      }
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = "Validar servidor";
      }
    }
  }

  function enhance() {
    replaceExecutionForm(document.querySelector("#backup-validation-form"));
  }

  const observer = new MutationObserver(enhance);
  document.addEventListener("DOMContentLoaded", () => {
    enhance();
    observer.observe(document.body, { childList: true, subtree: true });

    document.addEventListener("click", (event) => {
      if (event.target.closest("#storage-map-add")) {
        document.querySelector("#storage-map-units")?.insertAdjacentHTML("beforeend", unitRow({ role: "redundancia" }));
      }
      if (event.target.closest("[data-remove-storage-unit]")) {
        const rows = document.querySelectorAll("#storage-map-units .storage-map-unit");
        if (rows.length > 1) event.target.closest(".storage-map-unit")?.remove();
      }
      if (event.target.closest("#storage-map-save")) saveMapping();
      if (event.target.closest("#storage-map-load")) loadMapping();
    });

    document.addEventListener("submit", (event) => {
      if (event.target?.id !== "backup-validation-form") return;
      event.preventDefault();
      event.stopImmediatePropagation();
      validateMappedServer(event.target);
    }, true);
  });
})();
