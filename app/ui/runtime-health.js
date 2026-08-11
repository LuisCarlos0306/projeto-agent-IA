(() => {
  const escapeHtml = (value) => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  const stateLabel = (state) => ({
    available: "Disponível",
    unavailable: "Indisponível",
    not_configured: "Não configurado",
  }[state] || state || "Desconhecido");

  function locationText(item) {
    const location = item?.location || {};
    const host = location.host || "—";
    const port = location.port ? `:${location.port}` : "";
    const database = location.database != null ? ` · base ${location.database}` : "";
    return `${host}${port}${database}`;
  }

  function card(title, item) {
    const state = item?.state || "unknown";
    return `
      <article class="health-card" data-state="${escapeHtml(state)}">
        <div class="health-card-header"><h4>${escapeHtml(title)}</h4><span>${escapeHtml(stateLabel(state))}</span></div>
        <p>${escapeHtml(item?.detail || "Sem informação adicional.")}</p>
        <div class="health-meta"><span>${escapeHtml(locationText(item))}</span><span>origem: .env</span></div>
      </article>
    `;
  }

  async function validateRuntimeAccess(button, result) {
    button.disabled = true;
    button.textContent = "Validando...";
    result.hidden = false;
    result.innerHTML = '<div class="empty-state">Relendo o .env e validando PostgreSQL e Redis...</div>';
    try {
      const response = await fetch("/ui/api/health/infrastructure-access", {
        method: "POST",
        headers: { "X-Agent-UI": "1" },
        cache: "no-store",
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
      result.innerHTML = `
        <div class="panel-subheader"><div><p class="eyebrow">VALIDAÇÃO SOB DEMANDA</p><h3>Acesso usando o .env atual</h3></div><span class="mode-badge">${escapeHtml(payload.status)}</span></div>
        <div class="health-grid compact-health-grid">
          ${card("PostgreSQL", payload.postgres)}
          ${card("Redis", payload.redis)}
        </div>
        <p class="settings-secret-hint">Nenhuma senha, token ou DSN completo é enviado ao navegador.</p>
      `;
    } catch (error) {
      result.innerHTML = `<div class="empty-state">Falha ao validar o .env: ${escapeHtml(error.message)}</div>`;
    } finally {
      button.disabled = false;
      button.textContent = "Validar acesso pelo .env";
    }
  }

  function install() {
    const health = document.querySelector("#view-health article.panel");
    const header = health?.querySelector(".panel-header");
    if (!health || !header || document.querySelector("#validate-runtime-infrastructure")) return;

    const button = document.createElement("button");
    button.type = "button";
    button.id = "validate-runtime-infrastructure";
    button.className = "secondary-button";
    button.textContent = "Validar acesso pelo .env";
    header.appendChild(button);

    const result = document.createElement("div");
    result.id = "runtime-infrastructure-result";
    result.hidden = true;
    health.insertBefore(result, document.querySelector("#provider-health-list"));

    button.addEventListener("click", () => validateRuntimeAccess(button, result));
  }

  document.addEventListener("DOMContentLoaded", install);
})();
