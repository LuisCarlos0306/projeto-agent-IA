(() => {
  let scheduled = false;

  function terminalStatus() {
    const title = document.querySelector("#result-title")?.textContent.trim().toLowerCase() || "";
    if (title.includes("falha")) return "failed";
    if (title.includes("cancelando")) return "cancelling";
    if (title.includes("cancelada")) return "cancelled";

    const summary = document.querySelector(".execution-progress-summary");
    if (!summary) return "running";
    const rawPercent = summary.querySelector(".execution-progress-title > b")?.textContent || "0";
    const percent = Number(rawPercent.replace(/[^0-9]/g, "")) || 0;
    const timeline = [...document.querySelectorAll(".execution-timeline .timeline-item")];
    const lastCompleted = timeline.length > 0 && timeline.every((item) => item.classList.contains("completed"));
    if (percent >= 100 || lastCompleted) return "completed";
    return "running";
  }

  function applyColors() {
    scheduled = false;
    const summary = document.querySelector(".execution-progress-summary");
    if (!summary) return;
    summary.dataset.status = terminalStatus();
  }

  function schedule() {
    if (scheduled) return;
    scheduled = true;
    window.requestAnimationFrame(applyColors);
  }

  const observer = new MutationObserver(schedule);

  function start() {
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: ["class", "data-status", "style"],
    });
    schedule();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
