(() => {
  const FILTERS = [
    ["all", "Todos"],
    ["cloud", "Cloud"],
    ["local", "Local"],
    ["gateway", "Gateway"],
    ["custom", "Personalizados"],
  ];

  let activeFilter = "all";
  let observer = null;

  function groupFromTier(text) {
    const value = String(text || "").trim().toLocaleLowerCase("pt-BR");
    if (value.includes("local")) return "local";
    if (value.includes("gateway")) return "gateway";
    if (value.includes("personal")) return "custom";
    return "cloud";
  }

  function classifyCards() {
    const grid = document.querySelector("#provider-config-grid");
    if (!grid) return;
    const cards = [...grid.querySelectorAll(".provider-config-card")];
    const counts = { all: cards.length, cloud: 0, local: 0, gateway: 0, custom: 0 };

    cards.forEach((card) => {
      const group = groupFromTier(card.querySelector(".provider-tier")?.textContent);
      card.dataset.providerGroup = group;
      counts[group] += 1;
      card.hidden = activeFilter !== "all" && activeFilter !== group;

      const stateParagraph = card.querySelector(":scope > p");
      if (stateParagraph && !stateParagraph.dataset.compactState) {
        stateParagraph.dataset.compactState = "1";
        stateParagraph.classList.add("provider-compact-state");
      }
    });

    FILTERS.forEach(([id]) => {
      const button = document.querySelector(`[data-provider-compact-filter="${id}"]`);
      if (!button) return;
      const count = button.querySelector("[data-provider-count]");
      if (count) count.textContent = String(counts[id] || 0);
      button.classList.toggle("active", id === activeFilter);
    });
  }

  function installToolbar() {
    const section = document.querySelector("#view-settings .provider-priority-section");
    if (!section || section.dataset.compactUi === "1") return;
    section.dataset.compactUi = "1";

    const heading = section.querySelector(".provider-priority-head h3");
    const description = section.querySelector(".provider-priority-head p:not(.eyebrow)");
    const eyebrow = section.querySelector(".provider-priority-head .eyebrow");
    if (eyebrow) eyebrow.textContent = "PROVEDORES DE IA";
    if (heading) heading.textContent = "IAs disponíveis";
    if (description) description.textContent = "Visualização compacta. Abra Configurar somente quando precisar alterar chave, endpoint, modelo ou estado.";

    const toolbar = document.createElement("div");
    toolbar.className = "provider-compact-toolbar";
    toolbar.innerHTML = `<div class="provider-compact-filters" role="tablist" aria-label="Filtrar provedores de IA">${FILTERS.map(([id, label]) => `<button type="button" class="provider-compact-filter${id === activeFilter ? " active" : ""}" data-provider-compact-filter="${id}">${label}<span data-provider-count>0</span></button>`).join("")}</div><div class="provider-compact-hint"><span class="provider-compact-dot"></span> Arraste os cards para alterar a prioridade automática.</div>`;

    const grid = section.querySelector("#provider-config-grid");
    grid?.insertAdjacentElement("beforebegin", toolbar);

    toolbar.addEventListener("click", (event) => {
      const button = event.target.closest("[data-provider-compact-filter]");
      if (!button) return;
      activeFilter = button.dataset.providerCompactFilter || "all";
      classifyCards();
    });

    classifyCards();
  }

  function observeGrid() {
    const grid = document.querySelector("#provider-config-grid");
    if (!grid || observer) return;
    observer = new MutationObserver(() => classifyCards());
    observer.observe(grid, { childList: true, subtree: false });
  }

  function boot() {
    installToolbar();
    observeGrid();
    classifyCards();
  }

  document.addEventListener("DOMContentLoaded", () => {
    boot();
    window.setTimeout(boot, 150);
  });
})();
