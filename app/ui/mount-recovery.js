(() => {
  const SCRIPT_PATH = "/db/backup/scripts/mount.sh";
  const POLL_INTERVAL_MS = 1200;
  const MAX_POLLS = 180;

  const state = {
    validationJobId: null,
    recoveryJobId: null,
    remountJobId: null,
    lastValidation: null,
  };

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function healthLabel(value) {
    const labels = {
      healthy: "SAUDÁVEL",
      hanging: "HANGING",
      degraded: "DEGRADADA",
      unmounted: "DESMONTADA",
    };
    return labels[value] || String(value || "DESCONHECIDA").toUpperCase();
  }

  async function mountApi(path, options = {}) {
    const init = { ...options, headers: { ...(options.headers || {}) } };
    if (init.body && typeof init.body !== "string") {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(init.body);
    }
    if ((init.method || "GET").toUpperCase() !== "GET") {
      init.headers["X-Agent-UI"] = "1";
    }
    const response = await fetch(path, init);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.detail || `Erro HTTP ${response.status}`);
    }
    return payload;
  }

  function ensureUi() {
    if (document.querySelector("#mount-validation-modal")) return;

    const topbarStart = document.querySelector("#topbar-start-investigation");
    if (topbarStart && !document.querySelector("#topbar-mount-validation")) {
      const button = document.createElement("button");
      button.id = "topbar-mount-validation";
      button.type = "button";
      button.className = "secondary-button mount-topbar-button";
      button.textContent = "Validar mount";
      topbarStart.insertAdjacentElement("afterend", button);
      button.addEventListener("click", openModal);
    }

    document.body.insertAdjacentHTML("beforeend", `
      <aside class="mount-validation-modal" id="mount-validation-modal" aria-hidden="true" role="dialog" aria-modal="true" aria-labelledby="mount-validation-title">
        <div class="mount-validation-backdrop" data-close-mount-validation></div>
        <div class="mount-validation-panel">
          <header class="mount-validation-header">
            <div><p class="eyebrow">STORAGE / BACKUP</p><h2 id="mount-validation-title">Validar unidade</h2></div>
            <button class="icon-button" type="button" data-close-mount-validation aria-label="Fechar">×</button>
          </header>
          <form id="mount-validation-form" class="mount-validation-form">
            <label><span>Servidor / IP</span><input id="mount-target" required maxlength="255" placeholder="ex.: oda-X11 ou 172.16.250.20"></label>
            <label><span>Ponto de montagem</span><input id="mount-path" required maxlength="1024" placeholder="/mnt/backup_nas_rman"></label>
            <div class="mount-form-row">
              <label><span>Ambiente</span><select id="mount-environment"><option value="production">Produção</option><option value="standby">Standby</option><option value="monitoring">Monitoramento</option><option value="training">Treinamento</option></select></label>
              <label><span>Porta SSH</span><input id="mount-ssh-port" type="number" min="1" max="65535" placeholder="22"></label>
            </div>
            <div class="mount-form-actions"><button class="primary-button" type="submit" id="mount-validate-button">Validar unidade</button></div>
          </form>
          <section class="mount-result" id="mount-result" hidden></section>
        </div>
      </aside>
    `);

    document.querySelectorAll("[data-close-mount-validation]").forEach((item) => item.addEventListener("click", closeModal));
    document.querySelector("#mount-validation-form")?.addEventListener("submit", submitValidation);
  }

  function openModal() {
    const modal = document.querySelector("#mount-validation-modal");
    if (!modal) return;
    modal.setAttribute("aria-hidden", "false");
    modal.classList.add("open");
    setTimeout(() => document.querySelector("#mount-target")?.focus(), 50);
  }

  function closeModal() {
    const modal = document.querySelector("#mount-validation-modal");
    if (!modal) return;
    modal.setAttribute("aria-hidden", "true");
    modal.classList.remove("open");
  }

  function setBusy(buttonId, busy, label) {
    const button = document.querySelector(buttonId);
    if (!button) return;
    button.disabled = busy;
    if (label) button.textContent = label;
  }

  function showResult(html, status = "info") {
    const result = document.querySelector("#mount-result");
    if (!result) return;
    result.hidden = false;
    result.dataset.status = status;
    result.innerHTML = html;
  }

  async function pollJob(jobId) {
    for (let attempt = 0; attempt < MAX_POLLS; attempt += 1) {
      const job = await mountApi(`/ui/api/mounts/jobs/${encodeURIComponent(jobId)}`);
      if (["completed", "failed"].includes(job.status)) return job;
      await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
    }
    throw new Error("A operação não foi concluída dentro do tempo esperado.");
  }

  async function submitValidation(event) {
    event.preventDefault();
    const target = document.querySelector("#mount-target")?.value.trim();
    const path = document.querySelector("#mount-path")?.value.trim();
    const environment = document.querySelector("#mount-environment")?.value || "production";
    const sshPortRaw = document.querySelector("#mount-ssh-port")?.value.trim();
    const ssh_port = sshPortRaw ? Number(sshPortRaw) : null;

    state.validationJobId = null;
    state.lastValidation = null;
    setBusy("#mount-validate-button", true, "Validando...");
    showResult(`<div class="mount-result-title">Validando mount e saúde...</div><p>${escapeHtml(path)}</p>`, "info");

    try {
      const queued = await mountApi("/ui/api/mounts/validate", {
        method: "POST",
        body: { target, path, environment, ssh_port },
      });
      state.validationJobId = queued.job_id;
      const job = await pollJob(queued.job_id);
      if (job.status === "failed") throw new Error(job.error || job.current_phase?.detail || "Falha na validação.");
      state.lastValidation = job.result;
      renderValidation(job.result);
    } catch (error) {
      showResult(`<div class="mount-result-title">❌ FALHA NA VALIDAÇÃO</div><p>${escapeHtml(error.message)}</p>`, "error");
    } finally {
      setBusy("#mount-validate-button", false, "Validar unidade");
    }
  }

  function renderValidation(result) {
    const mounted = Boolean(result?.mounted);
    const health = result?.health || (mounted ? "degraded" : "unmounted");
    const hanging = mounted && health === "hanging";
    const healthy = mounted && health === "healthy";
    const title = hanging
      ? "⚠️ MOUNT HANGING DETECTADO"
      : healthy
        ? "✅ VALIDAÇÃO CONCLUÍDA"
        : "⚠️ VALIDAÇÃO CONCLUÍDA";
    const status = healthy ? "success" : "warning";
    const source = result?.source ? `<div><span>Origem</span><strong>${escapeHtml(result.source)}</strong></div>` : "";
    const fstype = result?.fstype ? `<div><span>Tipo</span><strong>${escapeHtml(result.fstype)}</strong></div>` : "";
    const usage = Number.isFinite(Number(result?.usage_percent))
      ? `<div><span>Uso</span><strong>${escapeHtml(result.usage_percent)}%</strong></div>`
      : "";
    const access = mounted
      ? `<div><span>Acesso</span><strong>${result?.access_ok ? "RESPONDENDO" : result?.access_timeout ? "TIMEOUT" : "FALHA"}</strong></div>`
      : "";
    const reasonText = !mounted ? result?.reason : (hanging && !result?.can_request_remount ? result?.remount_reason : "");
    const reason = reasonText ? `<p class="mount-reason">${escapeHtml(reasonText)}</p>` : "";

    let action = "";
    if (!mounted && result?.can_request_mount) {
      action = `<div class="mount-request-area"><button type="button" class="primary-button" id="mount-request-button">Solicitar montagem</button></div>`;
    } else if (hanging && result?.can_request_remount) {
      action = `<div class="mount-request-area"><button type="button" class="primary-button" id="mount-remount-button">Desmontar e montar novamente</button></div>`;
    }

    showResult(`
      <div class="mount-result-title">${title}</div>
      <div class="mount-result-grid">
        <div><span>Servidor</span><strong>${escapeHtml(result?.target || "—")}</strong></div>
        <div><span>Unidade</span><strong>${escapeHtml(result?.path || "—")}</strong></div>
        <div><span>Status</span><strong>${mounted ? "MONTADA" : "NÃO MONTADA"}</strong></div>
        <div><span>Saúde</span><strong>${escapeHtml(healthLabel(health))}</strong></div>
        ${access}${usage}${source}${fstype}
      </div>
      ${hanging ? '<p class="mount-reason">A unidade está registrada como montada, porém não respondeu à prova de acesso dentro do timeout seguro.</p>' : ""}
      ${reason}
      ${action}
    `, status);

    document.querySelector("#mount-request-button")?.addEventListener("click", renderMountConfirmation);
    document.querySelector("#mount-remount-button")?.addEventListener("click", renderRemountConfirmation);
  }

  function renderMountConfirmation() {
    const result = state.lastValidation;
    if (!result || !state.validationJobId) return;
    const area = document.querySelector(".mount-request-area");
    if (!area) return;
    area.innerHTML = `
      <div class="mount-confirm-box">
        <strong>Confirmar montagem?</strong>
        <p>Será executado somente <code>${escapeHtml(SCRIPT_PATH)}</code> e a unidade será validada novamente.</p>
        <div class="mount-confirm-actions">
          <button type="button" class="primary-button" id="mount-confirm-button">Confirmar</button>
          <button type="button" class="secondary-button" id="mount-cancel-button">Cancelar</button>
        </div>
      </div>
    `;
    document.querySelector("#mount-confirm-button")?.addEventListener("click", submitRecovery);
    document.querySelector("#mount-cancel-button")?.addEventListener("click", () => renderValidation(result));
  }

  function renderRemountConfirmation() {
    const result = state.lastValidation;
    if (!result || !state.validationJobId) return;
    const area = document.querySelector(".mount-request-area");
    if (!area) return;
    area.innerHTML = `
      <div class="mount-confirm-box">
        <strong>Confirmar desmontagem e montagem?</strong>
        <p>O Agent executará somente uma desmontagem normal e temporizada do ponto <code>${escapeHtml(result.path)}</code>, sem <code>-f</code> e sem <code>-l</code>. Se desmontar, executará <code>${escapeHtml(SCRIPT_PATH)}</code> e validará a saúde novamente.</p>
        <p>Se a unidade estiver ocupada ou não desmontar normalmente, a operação será interrompida.</p>
        <div class="mount-confirm-actions">
          <button type="button" class="primary-button" id="mount-remount-confirm-button">Confirmar remontagem</button>
          <button type="button" class="secondary-button" id="mount-remount-cancel-button">Cancelar</button>
        </div>
      </div>
    `;
    document.querySelector("#mount-remount-confirm-button")?.addEventListener("click", submitRemount);
    document.querySelector("#mount-remount-cancel-button")?.addEventListener("click", () => renderValidation(result));
  }

  async function submitRecovery() {
    if (!state.validationJobId) return;
    const confirmButton = document.querySelector("#mount-confirm-button");
    if (confirmButton) {
      confirmButton.disabled = true;
      confirmButton.textContent = "Executando...";
    }
    try {
      const queued = await mountApi("/ui/api/mounts/recover", {
        method: "POST",
        body: { validation_job_id: state.validationJobId, confirm: true },
      });
      state.recoveryJobId = queued.job_id;
      showResult(`<div class="mount-result-title">🔧 SCRIPT DE MONTAGEM SOLICITADO</div><p>Executando ${escapeHtml(SCRIPT_PATH)} e revalidando a unidade...</p>`, "info");
      const job = await pollJob(queued.job_id);
      if (job.status === "failed") throw new Error(job.error || job.current_phase?.detail || "Falha na montagem.");
      renderRecovery(job.result);
    } catch (error) {
      showResult(`<div class="mount-result-title">❌ FALHA NA MONTAGEM</div><p>${escapeHtml(error.message)}</p><p>Resultado: INTERVENÇÃO NECESSÁRIA</p>`, "error");
    }
  }

  async function submitRemount() {
    if (!state.validationJobId) return;
    const confirmButton = document.querySelector("#mount-remount-confirm-button");
    if (confirmButton) {
      confirmButton.disabled = true;
      confirmButton.textContent = "Remontando...";
    }
    try {
      const queued = await mountApi("/ui/api/mounts/remount", {
        method: "POST",
        body: { validation_job_id: state.validationJobId, confirm: true },
      });
      state.remountJobId = queued.job_id;
      showResult(`<div class="mount-result-title">🔧 REMONTAGEM SOLICITADA</div><p>Desmontando sem force/lazy, executando ${escapeHtml(SCRIPT_PATH)} e validando a saúde...</p>`, "info");
      const job = await pollJob(queued.job_id);
      if (job.status === "failed") throw new Error(job.error || job.current_phase?.detail || "Falha na remontagem.");
      renderRemount(job.result);
    } catch (error) {
      showResult(`<div class="mount-result-title">❌ FALHA NA REMONTAGEM</div><p>${escapeHtml(error.message)}</p><p>Resultado: INTERVENÇÃO NECESSÁRIA</p>`, "error");
    }
  }

  function renderRecovery(result) {
    const health = result?.health || result?.after?.health || (result?.mounted ? "degraded" : "unmounted");
    if (result?.mounted && health === "healthy") {
      showResult(`
        <div class="mount-result-title">✅ MONTAGEM REALIZADA</div>
        <div class="mount-result-grid">
          <div><span>Unidade</span><strong>${escapeHtml(result.path)}</strong></div>
          <div><span>Script</span><strong>${escapeHtml(result.script)}</strong></div>
          <div><span>Status</span><strong>MONTADA</strong></div>
          <div><span>Saúde</span><strong>SAUDÁVEL</strong></div>
          <div><span>Resultado</span><strong>SUCESSO</strong></div>
        </div>
      `, "success");
      return;
    }
    showResult(`
      <div class="mount-result-title">❌ MONTAGEM SEM SAÚDE CONFIRMADA</div>
      <div class="mount-result-grid">
        <div><span>Unidade</span><strong>${escapeHtml(result?.path || "—")}</strong></div>
        <div><span>Script</span><strong>${escapeHtml(result?.script || SCRIPT_PATH)}</strong></div>
        <div><span>Status</span><strong>${result?.mounted ? "MONTADA" : "NÃO MONTADA"}</strong></div>
        <div><span>Saúde</span><strong>${escapeHtml(healthLabel(health))}</strong></div>
        <div><span>Resultado</span><strong>INTERVENÇÃO NECESSÁRIA</strong></div>
      </div>
    `, "error");
  }

  function renderRemount(result) {
    const health = result?.health || result?.after?.health || (result?.mounted ? "degraded" : "unmounted");
    if (result?.status === "remounted" && result?.mounted && health === "healthy") {
      showResult(`
        <div class="mount-result-title">✅ REMONTAGEM REALIZADA</div>
        <div class="mount-result-grid">
          <div><span>Unidade</span><strong>${escapeHtml(result.path)}</strong></div>
          <div><span>Status</span><strong>MONTADA</strong></div>
          <div><span>Saúde</span><strong>SAUDÁVEL</strong></div>
          <div><span>Usuário do cron</span><strong>${escapeHtml(result.execution_user || "—")}</strong></div>
          <div><span>Resultado</span><strong>SUCESSO</strong></div>
        </div>
      `, "success");
      return;
    }

    const unmountFailed = result?.status === "unmount_failed";
    showResult(`
      <div class="mount-result-title">❌ ${unmountFailed ? "UNIDADE NÃO FOI DESMONTADA" : "REMONTAGEM NÃO NORMALIZOU A UNIDADE"}</div>
      <div class="mount-result-grid">
        <div><span>Unidade</span><strong>${escapeHtml(result?.path || "—")}</strong></div>
        <div><span>Status</span><strong>${result?.mounted ? "MONTADA" : "NÃO MONTADA"}</strong></div>
        <div><span>Saúde</span><strong>${escapeHtml(healthLabel(health))}</strong></div>
        <div><span>Resultado</span><strong>INTERVENÇÃO NECESSÁRIA</strong></div>
      </div>
      <p class="mount-reason">${unmountFailed ? "A desmontagem normal falhou ou o ponto permaneceu montado. Nenhum force/lazy unmount foi executado." : "A pós-validação não confirmou um mount saudável."}</p>
    `, "error");
  }

  document.addEventListener("DOMContentLoaded", ensureUi, { once: true });
  if (document.readyState !== "loading") ensureUi();
})();
