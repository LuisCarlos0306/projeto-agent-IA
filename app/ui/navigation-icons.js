(() => {
  const paths = {
    dashboard: '<path d="M3.5 10.5 12 3.8l8.5 6.7"></path><path d="M5.5 9.7V20h13V9.7"></path><path d="M9.5 20v-6h5v6"></path>',
    investigations: '<circle cx="10.5" cy="10.5" r="6.2"></circle><path d="m15.2 15.2 5 5"></path><path d="M7.6 10.5h1.6l1-2 1.5 4 1-2h1.2"></path>',
    agents: '<rect x="5" y="7" width="14" height="11" rx="3"></rect><path d="M12 3v4M8.5 12h.01M15.5 12h.01M9 15h6"></path>',
    executions: '<rect x="3.5" y="4.5" width="17" height="15" rx="2.5"></rect><path d="m7.5 9 2.5 2.5L7.5 14M12.5 14h4"></path>',
    incidents: '<path d="M12 3.4 21 19H3L12 3.4Z"></path><path d="M12 9v4.5M12 16.5h.01"></path>',
    skills: '<path d="m12 3 1.2 3.5L17 8l-3.8 1.4L12 13l-1.2-3.6L7 8l3.8-1.5L12 3Z"></path><path d="m18.2 13.2.7 2.1 2.1.7-2.1.8-.7 2.2-.8-2.2-2.1-.8 2.1-.7.8-2.1Z"></path>',
    playbooks: '<path d="M5 5.5h12.5a2 2 0 0 1 2 2V19H7a2 2 0 0 1-2-2V5.5Z"></path><path d="M7 5.5V19M9.5 9h6M9.5 12h6M9.5 15h4"></path>',
    agentflow: '<circle cx="6" cy="6" r="2.2"></circle><circle cx="18" cy="6" r="2.2"></circle><circle cx="12" cy="18" r="2.2"></circle><path d="M8.2 6h7.6M7.2 8l3.6 7.8M16.8 8l-3.6 7.8"></path>',
    customers: '<circle cx="9" cy="9" r="3"></circle><circle cx="17" cy="10" r="2.3"></circle><path d="M3.8 19c.6-3 2.4-4.6 5.2-4.6s4.6 1.6 5.2 4.6M14.5 15.2c2.7-.7 4.7.4 5.7 2.8"></path>',
    inventory: '<rect x="4" y="4" width="16" height="5" rx="1.5"></rect><rect x="4" y="10" width="16" height="5" rx="1.5"></rect><rect x="4" y="16" width="16" height="4" rx="1.5"></rect><path d="M7 6.5h.01M7 12.5h.01M7 18h.01M10 6.5h7M10 12.5h7M10 18h7"></path>',
    topology: '<circle cx="12" cy="5" r="2.2"></circle><circle cx="5" cy="18" r="2.2"></circle><circle cx="19" cy="18" r="2.2"></circle><path d="m10.8 7-4.6 8.8M13.2 7l4.6 8.8M7.2 18h9.6"></path>',
    opencode: '<path d="m8.5 7-5 5 5 5M15.5 7l5 5-5 5M13.5 4l-3 16"></path>',
    tools: '<path d="M14.2 6.2a4.8 4.8 0 0 0-6.1 6.1l-4.5 4.5a2.3 2.3 0 0 0 3.2 3.2l4.5-4.5a4.8 4.8 0 0 0 6.1-6.1l-3 3-2.8-.8-.8-2.8 3.4-2.6Z"></path>',
    settings: '<path d="M4 7h7M15 7h5M4 17h5M13 17h7M11 4v6M9 14v6"></path><circle cx="13" cy="7" r="2"></circle><circle cx="11" cy="17" r="2"></circle>',
    health: '<path d="M20.3 5.8a5.1 5.1 0 0 0-7.2 0L12 6.9l-1.1-1.1a5.1 5.1 0 0 0-7.2 7.2L12 21l8.3-8a5.1 5.1 0 0 0 0-7.2Z"></path><path d="M6.8 13h2.5l1.4-3.2 2.2 6.1 1.4-2.9h2.9"></path>',
  };

  function svgFor(view) {
    return `<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">${paths[view] || '<circle cx="12" cy="12" r="4"></circle>'}</svg>`;
  }

  function decorate() {
    document.querySelectorAll(".sidebar .nav-item[data-view]").forEach((button) => {
      const icon = button.querySelector(".nav-icon");
      if (!icon) return;
      const view = button.dataset.view || "";
      if (icon.dataset.svgView === view) return;
      icon.dataset.svgView = view;
      icon.classList.add("nav-svg-icon");
      icon.innerHTML = svgFor(view);
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    decorate();
    const nav = document.querySelector(".sidebar .nav");
    if (nav) new MutationObserver(decorate).observe(nav, { childList: true, subtree: true });
  });
})();
