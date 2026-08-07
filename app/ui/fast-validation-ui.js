(() => {
  const DEFAULT_CONFIG = {
    enabled: true,
    max_rounds: 2,
    tools_per_round: 3,
    max_commands: 10,
    max_ai_calls: 8,
    max_investigation_seconds: 240,
    max_host_seconds: 180,
    ai_request_timeout_seconds: 25,
  };

  const REASONING_LABELS = {
    mission_interpretation: "Entendendo o objetivo informado",
    planning_round_1: "Planejando a coleta essencial",
    planning_round_2: "Planejando a verificação complementar",
    analysis_round_1: "Analisando as primeiras evidências",
    analysis_round_2: "Confirmando as evidências coletadas",
    final_analysis: "Gerando uma conclusão objetiva",
    final_critic: "Validando a conclusão com a IA revisora",
    correction_planning: "Preparando uma proposta segura",
  };

  let config = { ...DEFAULT_CONFIG };
  let updateScheduled = false;

  function formatDuration(seconds) {
    const value = Math.max(0, Math.round(Number(seconds) || 0));
    const minutes = Math.floor(value / 60);
    const remainder = value % 60;
    if (minutes) return `${minutes}min${remainder ? ` ${remainder}s` : ""}`;
    return `${remainder}s`;
  }

  function parseDuration(value) {
    const text = String(value || "").toLowerCase();
    const hours = Number(text.match(/(\d+)h/)?.[1] || 0);
    const minutes = Number(text.match(/(\d+)min/)?.[1] || 0);
    const seconds = Number(text.match(/(\d+)s/)?.[1] || 0);
    return (hours * 3600) + (minutes * 60) + seconds;
  }

  function reasoningPurpose(value) {
    const text = String(value || "");
    const match = text.match(/(?:etapa objetiva:|etapa)\s+([a-z0-9_]+)(?:\s+concluída)?/i);
    return match?.[1] || "";
  }

  function friendlyText(value) {
    const text = String(value || "").trim();
    const purpose = reasoningPurpose(text);
    if (purpose && REASONING_LABELS[purpose]) {
      if (/concluída/i.test(text)) return `${REASONING_LABELS[purpose]} — concluído`;
      if (/não retornou/i.test(text)) return `${REASONING_LABELS[purpose]} — fallback seguro acionado`;
      return REASONING_LABELS[purpose];
    }
    if (/^ai[ _-]reasoning$/i.test(text)) return "IA analisando evidências";
    if (/^investigation[ _-]budget$/i.test(text)) return "Controlando tempo e limites";
    return text;
  }

  function replaceText(element, next) {
    if (element && next && element.textContent.trim() !== next) element.textContent = next;
  }

  function elapsedFromPanel(panel) {
    const rows = [...panel.querySelectorAll(".execution-live-meta > span")];
    const timeRow = rows.find((row) => row.querySelector("b")?.textContent.trim() === "Tempo");
    if (!timeRow) return 0;
    return parseDuration(timeRow.textContent.replace(/^Tempo/i, ""));
  }

  function translateCurrentStage(panel) {
    const rows = [...panel.querySelectorAll(".execution-live-meta > span")];
    const stageRow = rows.find((row) => row.querySelector("b")?.textContent.trim() === "Etapa");
    if (stageRow) {
      const current = stageRow.textContent.replace(/^Etapa/i, "").trim();
      const translated = friendlyText(current);
      if (translated !== current) {
        const label = stageRow.querySelector("b");
        stageRow.textContent = translated;
        stageRow.prepend(label || Object.assign(document.createElement("b"), { textContent: "Etapa" }));
      }
    }

    document.querySelectorAll(".execution-timeline .timeline-item p, .execution-tray-copy > span").forEach((node) => {
      replaceText(node, friendlyText(node.textContent));
    });

    document.querySelectorAll(".execution-timeline .timeline-item strong").forEach((node) => {
      if (node.textContent.trim() === "Coletando e analisando evidências") {
        replaceText(node, "Coleta focada e análise da IA");
      }
    });
  }

  function ensureBadges(panel) {
    const headerCopy = panel.querySelector(".execution-live-header > div");
    if (!headerCopy) return;
    const title = headerCopy.querySelector("h3");
    replaceText(title, config.enabled ? "Coleta rápida e objetiva" : "Coleta e comandos");

    let badges = headerCopy.querySelector(".fast-validation-badges");
    if (!badges) {
      badges = document.createElement("div");
      badges.className = "fast-validation-badges";
      headerCopy.appendChild(badges);
    }
    const signature = JSON.stringify(config);
    if (badges.dataset.signature === signature) return;
    badges.dataset.signature = signature;
    badges.innerHTML = config.enabled
      ? `<span>Modo rápido ativo</span><span>Limite ${formatDuration(config.max_investigation_seconds)}</span>`
      : "<span>Modo completo</span>";
  }

  function ensureStatus(panel) {
    let status = panel.querySelector(".fast-validation-status");
    if (!status) {
      status = document.createElement("section");
      status.className = "fast-validation-status";
      panel.querySelector(".execution-live-header")?.insertAdjacentElement("afterend", status);
    }

    const elapsed = elapsedFromPanel(panel);
    const remaining = Math.max(0, Number(config.max_investigation_seconds) - elapsed);
    const activeDetail = friendlyText(
      document.querySelector(".execution-timeline .timeline-item.active p")?.textContent
      || panel.querySelector(".execution-live-meta > span:nth-child(2)")?.textContent
      || "Coletando somente o necessário para concluir.",
    );

    let state = "normal";
    let timing = `Limite restante: ${formatDuration(remaining)}`;
    if (!config.enabled) {
      state = "disabled";
      timing = "Sem limite rápido aplicado";
    } else if (remaining === 0) {
      state = "limit";
      timing = "Limite atingido — encerramento seguro em andamento";
    } else if (remaining <= 60) {
      state = "warning";
      timing = `Encerramento seguro em até ${formatDuration(remaining)}`;
    }

    const signature = [state, timing, activeDetail, JSON.stringify(config)].join("|");
    if (status.dataset.signature === signature) return;
    status.dataset.signature = signature;
    status.dataset.state = state;
    status.innerHTML = `<span class="fast-validation-pulse" aria-hidden="true"></span><div><strong>${config.enabled ? "Coleta focada ativa" : "Coleta focada desativada"}</strong><p>${activeDetail}</p><small>${timing} · até ${config.max_rounds} rodadas · ${config.tools_per_round} ferramentas por rodada · timeout da IA ${formatDuration(config.ai_request_timeout_seconds)}</small></div>`;
  }

  function syncTerminalProgressState() {
    const summary = document.querySelector(".execution-progress-summary");
    if (!summary) return;

    const title = String(document.querySelector("#result-title")?.textContent || "").trim().toLowerCase();
    const percentText = String(summary.querySelector(".execution-progress-title > b")?.textContent || "0");
    const percent = Number(percentText.replace(/[^0-9]/g, "")) || 0;
    const timeline = [...document.querySelectorAll(".execution-timeline .timeline-item")];

    let status = "running";
    if (title.includes("falha")) status = "failed";
    else if (title.includes("cancelando")) status = "cancelling";
    else if (title.includes("cancelada")) status = "cancelled";
    else if (percent >= 100 || (timeline.length > 0 && timeline.every((item) => item.classList.contains("completed")))) status = "completed";

    summary.dataset.status = status;
  }

  function enhanceProgress() {
    syncTerminalProgressState();

    const panel = document.querySelector(".execution-live-panel");
    if (!panel) return;
    translateCurrentStage(panel);
    ensureBadges(panel);
    ensureStatus(panel);

    const summary = document.querySelector(".execution-progress-summary > p");
    if (summary) {
      replaceText(
        summary,
        config.enabled
          ? `Modo rápido: no máximo ${config.max_rounds} rodadas e ${config.max_commands} comandos. Se a IA não responder no prazo, a investigação encerra com fallback seguro.`
          : "O acompanhamento continua mesmo com este painel fechado.",
      );
    }
  }

  function scheduleEnhancement() {
    if (updateScheduled) return;
    updateScheduled = true;
    window.requestAnimationFrame(() => {
      updateScheduled = false;
      enhanceProgress();
    });
  }

  async function loadConfig() {
    try {
      const response = await fetch("/ui/api/fast-validation", { cache: "no-store" });
      if (response.ok) config = { ...DEFAULT_CONFIG, ...(await response.json()) };
    } catch {
      config = { ...DEFAULT_CONFIG };
    }
    scheduleEnhancement();
  }

  function start() {
    void loadConfig();
    const observer = new MutationObserver(scheduleEnhancement);
    observer.observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ["class", "data-status", "style"] });
    window.setInterval(scheduleEnhancement, 1000);
    scheduleEnhancement();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
