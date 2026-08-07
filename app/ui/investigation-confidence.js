(() => {
  function clampConfidence(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return 0;
    return Math.max(0, Math.min(100, Math.round(number)));
  }

  function confidenceLevel(value) {
    if (value >= 70) return "high";
    if (value >= 40) return "medium";
    return "low";
  }

  function confidenceMarkup(value) {
    const score = clampConfidence(value);
    const active = Math.max(0, Math.min(10, Math.ceil(score / 10)));
    const level = confidenceLevel(score);
    const segments = Array.from({ length: 10 }, (_item, index) => (
      `<i class="${index < active ? "active" : ""}" aria-hidden="true"></i>`
    )).join("");
    const label = score >= 70 ? "Alta" : score >= 40 ? "Média" : "Baixa";
    return `<div class="investigation-confidence-meter" data-level="${level}" title="Confiança ${label}: ${score}%" aria-label="Confiança ${label}: ${score}%">
      <span class="investigation-confidence-segments">${segments}</span>
      <strong>${score}%</strong>
    </div>`;
  }

  function decorateRows(tableBody, columnIndex) {
    if (!tableBody) return;
    tableBody.querySelectorAll("tr").forEach((row) => {
      const cell = row.children[columnIndex];
      if (!cell || cell.querySelector(".investigation-confidence-meter")) return;
      const match = String(cell.textContent || "").match(/(-?\d+(?:[.,]\d+)?)\s*%/);
      if (!match) return;
      const value = Number(match[1].replace(",", "."));
      cell.classList.add("investigation-confidence-cell");
      cell.innerHTML = confidenceMarkup(value);
    });
  }

  function decorateAll() {
    decorateRows(document.querySelector("#recent-investigations"), 3);
    decorateRows(document.querySelector("#investigations-table"), 5);
  }

  function observeTable(selector, columnIndex) {
    const tableBody = document.querySelector(selector);
    if (!tableBody) return;
    decorateRows(tableBody, columnIndex);
    const observer = new MutationObserver(() => decorateRows(tableBody, columnIndex));
    observer.observe(tableBody, { childList: true, subtree: true });
  }

  function installCyberBrand() {
    const mark = document.querySelector(".brand-mark");
    if (!mark || mark.querySelector(".brand-ai-logo")) return;
    mark.setAttribute("title", "Agent IA — inteligência operacional");
    mark.innerHTML = `
      <svg class="brand-ai-logo" viewBox="0 0 48 48" role="img" aria-label="Símbolo neural do Agent IA">
        <defs>
          <linearGradient id="brandCyberGradient" x1="7" y1="7" x2="41" y2="41" gradientUnits="userSpaceOnUse">
            <stop offset="0" stop-color="#45efff"/>
            <stop offset=".52" stop-color="#35dfff"/>
            <stop offset="1" stop-color="#b03cff"/>
          </linearGradient>
        </defs>
        <path class="brand-head" d="M13 38V22c0-8 5.2-13 12.8-13 6.5 0 11.5 3.9 12.5 10l3.2 6.3-4.5 2.1V35h-8.5l-4.8 4.8H13z"/>
        <path class="brand-trace" d="M18 31V20h6v-5M24 34V25h8v-8M17 25h4l3-3M29 29v-5h6M19 35h5l4-4"/>
        <circle class="brand-node" cx="18" cy="20" r="1.6"/>
        <circle class="brand-node" cx="24" cy="15" r="1.6"/>
        <circle class="brand-node" cx="32" cy="17" r="1.6"/>
        <circle class="brand-node" cx="35" cy="24" r="1.6"/>
        <circle class="brand-node" cx="29" cy="29" r="1.6"/>
      </svg>`;
  }

  function bootConfidenceMeters() {
    installCyberBrand();
    observeTable("#recent-investigations", 3);
    observeTable("#investigations-table", 5);
    decorateAll();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootConfidenceMeters, { once: true });
  } else {
    bootConfidenceMeters();
  }
})();
