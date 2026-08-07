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

  function bootConfidenceMeters() {
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
