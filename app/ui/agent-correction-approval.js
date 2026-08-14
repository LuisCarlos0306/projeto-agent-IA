(() => {
  const safeText = (value) => String(value ?? "").trim();

  async function requestJson(path, options = {}) {
    const init = { ...options, headers: { ...(options.headers || {}) } };
    if (init.body && typeof init.body !== "string") {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(init.body);
    }
    if ((init.method || "GET").toUpperCase() !== "GET") init.headers["X-Agent-UI"] = "1";
    const response = await fetch(path, init);
    const payload = (response.headers.get("content-type") || "").includes("application/json")
      ? await response.json()
      : await response.text();
    if (!response.ok) {
      const detail = typeof payload === "object" ? payload.detail : payload;
      throw new Error(detail || `Erro HTTP ${response.status}`);
    }
    return payload;
  }

  function agentIdFromDrawer(drawer) {
    return drawer.querySelector("[data-run-agent]")?.dataset.runAgent
      || drawer.querySelector("[data-edit-agent]")?.dataset.editAgent
      || "";
  }

  function hasPendingCorrection(drawer) {
    const firstLog = drawer.querySelector(".agent-v2-history .agent-v2-log");
    return Boolean(firstLog?.querySelector(".agent-v2-correction.pending_approval"));
  }

  function ensureApprovalButton() {
    const drawer = document.querySelector("#agent-detail");
    if (!drawer || drawer.hidden) return;
    drawer.querySelector("[data-approve-agent-correction]")?.remove();
    if (!hasPendingCorrection(drawer)) return;
    const agentId = agentIdFromDrawer(drawer);
    const actions = drawer.querySelector(".agent-v2-actions");
    if (!agentId || !actions) return;

    const button = document.createElement("button");
    button.type = "button";
    button.className = "primary-button agent-correction-approve";
    button.dataset.approveAgentCorrection = agentId;
    button.innerHTML = "✓ <span>Aprovar correção</span>";
    button.title = "Revisar a ação exata, validar pela segunda IA e executar somente após sua confirmação";
    actions.appendChild(button);
  }

  async function approve(agentId, button) {
    const original = button.innerHTML;
    button.disabled = true;
    button.textContent = "Carregando ação...";
    try {
      const preview = await requestJson(`/ui/api/agents/${encodeURIComponent(agentId)}/correction`);
      const action = preview.action || {};
      const message = [
        "CONFIRMAR CORREÇÃO DO AGENTE",
        "",
        `Ação: ${safeText(action.label || action.configured_action)}`,
        `Servidor: ${safeText(preview.target)}`,
        `Ambiente: ${safeText(preview.environment)}`,
        "",
        "Ao confirmar, a ação será revisada pela segunda IA, assinada para este alvo e executada com pós-validação.",
      ].join("\n");
      if (!window.confirm(message)) return;

      button.textContent = "Revisando e executando...";
      const result = await requestJson(
        `/ui/api/agents/${encodeURIComponent(agentId)}/correction/approve`,
        { method: "POST", body: { confirmed: true } },
      );
      window.alert(result.message || (result.success ? "Correção executada com sucesso." : "Correção concluída com erro."));
      document.querySelector('[data-view="agents"]')?.click();
    } catch (error) {
      window.alert(error.message);
    } finally {
      button.disabled = false;
      button.innerHTML = original;
    }
  }

  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-approve-agent-correction]");
    if (!button) return;
    event.preventDefault();
    event.stopPropagation();
    void approve(button.dataset.approveAgentCorrection, button);
  }, true);

  const observer = new MutationObserver(() => ensureApprovalButton());
  document.addEventListener("DOMContentLoaded", () => {
    const drawer = document.querySelector("#agent-detail");
    if (drawer) observer.observe(drawer, { childList: true, subtree: true, attributes: true, attributeFilter: ["hidden"] });
    ensureApprovalButton();
  });
})();
