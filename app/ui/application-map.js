(() => {
  const state = {
    payload: null,
    view: "architecture",
    category: "all",
    search: "",
    zoom: 0.82,
    panX: 22,
    panY: 24,
    dragging: false,
    dragOrigin: null,
    selected: null,
    loaded: false,
  };

  const safe = (value) => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  const stateLabel = (value) => ({
    available: "Disponível",
    healthy: "Saudável",
    idle: "Ocioso",
    attention: "Atenção",
    unavailable: "Indisponível",
    not_configured: "Não configurado",
    unknown: "Não verificado",
    external: "Externo",
    inline: "Inline",
  }[value] || value || "Não verificado");

  const categoryIcon = (category) => ({
    entry: "↗",
    web: "▣",
    orchestration: "⌘",
    ai: "✦",
    security: "◇",
    data: "▦",
    execution: "▶",
    external: "◎",
  }[category] || "•");

  async function requestJson(path) {
    const response = await fetch(path, { headers: { Accept: "application/json" } });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload?.detail || `Erro HTTP ${response.status}`);
    return payload;
  }

  function removeLegacyFlow() {
    document.querySelector("#topbar-agent-flow")?.remove();
    const flowNav = document.querySelector('[data-view="agentflow"]');
    if (flowNav) {
      flowNav.innerHTML = '<span class="nav-icon">⌁</span><span>Fluxo</span>';
      flowNav.title = "Mapa da aplicação";
    }
  }

  function navGroup(label, key) {
    const wrapper = document.createElement("div");
    wrapper.className = "app-nav-group";
    wrapper.dataset.navGroup = key;
    wrapper.innerHTML = `<div class="app-nav-group-label">${safe(label)}</div><div class="app-nav-group-items"></div>`;
    return wrapper;
  }

  function organizeSidebar() {
    const nav = document.querySelector(".sidebar .nav");
    if (!nav || nav.dataset.applicationMapOrganized === "1") return;

    const buttons = [...nav.querySelectorAll(":scope > .nav-item")];
    if (!buttons.length) return;
    nav.dataset.applicationMapOrganized = "1";

    const dashboard = buttons.find((item) => item.dataset.view === "dashboard");
    nav.innerHTML = "";
    if (dashboard) nav.appendChild(dashboard);

    const groups = [
      ["OPERAÇÃO", "operation", ["investigations", "agents", "executions", "incidents"]],
      ["AUTOMAÇÃO", "automation", ["skills", "playbooks", "agentflow"]],
      ["AMBIENTE", "environment", ["customers", "inventory", "topology"]],
      ["PLATAFORMA", "platform", ["opencode", "tools", "settings", "health"]],
    ];
    const assigned = new Set(dashboard ? [dashboard] : []);

    groups.forEach(([label, key, views]) => {
      const group = navGroup(label, key);
      const holder = group.querySelector(".app-nav-group-items");
      views.forEach((view) => {
        const item = buttons.find((button) => button.dataset.view === view);
        if (item) {
          holder.appendChild(item);
          assigned.add(item);
        }
      });
      if (holder.children.length) nav.appendChild(group);
    });

    const rest = buttons.filter((button) => !assigned.has(button));
    if (rest.length) {
      let platform = nav.querySelector('[data-nav-group="platform"] .app-nav-group-items');
      if (!platform) {
        const group = navGroup("PLATAFORMA", "platform");
        nav.appendChild(group);
        platform = group.querySelector(".app-nav-group-items");
      }
      rest.forEach((item) => platform.appendChild(item));
    }
  }

  function bindFlowNav() {
    const button = document.querySelector('[data-view="agentflow"]');
    if (!button || button.dataset.applicationMapBound === "1") return;
    button.dataset.applicationMapBound = "1";
    button.addEventListener("click", () => loadMap(false));
  }

  function ensureMapShell() {
    removeLegacyFlow();
    const flowView = document.querySelector("#view-agentflow");
    if (!flowView) return;
    flowView.innerHTML = `
      <article class="panel app-map-panel">
        <div class="app-map-header">
          <div>
            <p class="eyebrow">MAPA DA APLICAÇÃO</p>
            <h3>Arquitetura do Agent IA</h3>
            <p>Componentes, dados, segurança e dependências reais da aplicação em uma única visão.</p>
          </div>
          <div class="app-map-runtime-summary" id="app-map-runtime-summary"></div>
        </div>

        <div class="app-map-toolbar">
          <div class="app-map-tabs" id="app-map-tabs"></div>
          <div class="app-map-tools">
            <label class="app-map-search"><span>⌕</span><input id="app-map-search" type="search" placeholder="Buscar componente, tecnologia ou arquivo..."></label>
            <button type="button" class="app-map-tool" data-map-action="zoom-out" title="Diminuir zoom">−</button>
            <button type="button" class="app-map-tool" data-map-action="zoom-in" title="Aumentar zoom">+</button>
            <button type="button" class="app-map-tool text" data-map-action="fit">Ajustar</button>
            <button type="button" class="app-map-tool text" data-map-action="center">Centralizar</button>
            <button type="button" class="app-map-tool" data-map-action="refresh" title="Atualizar estados">↻</button>
          </div>
        </div>

        <div class="app-map-category-bar" id="app-map-categories"></div>
        <div class="app-map-legend">
          <span><i class="edge direct"></i>chamada direta</span>
          <span><i class="edge async"></i>fila / assíncrono</span>
          <span><i class="edge data"></i>leitura / gravação</span>
          <span><i class="edge security"></i>controle de segurança</span>
          <span><i class="edge ssh"></i>execução SSH</span>
        </div>

        <div class="app-map-workspace">
          <div class="app-map-viewport" id="app-map-viewport" tabindex="0" aria-label="Mapa interativo da aplicação">
            <div class="app-map-stage" id="app-map-stage">
              <svg class="app-map-edges" id="app-map-edges" aria-hidden="true"></svg>
              <div class="app-map-nodes" id="app-map-nodes"></div>
            </div>
            <div class="app-map-empty" id="app-map-empty" hidden>Nenhum componente corresponde aos filtros.</div>
            <div class="app-map-minimap" id="app-map-minimap"></div>
            <div class="app-map-zoom-indicator" id="app-map-zoom-indicator"></div>
          </div>
          <aside class="app-map-detail" id="app-map-detail" hidden aria-hidden="true"></aside>
        </div>
      </article>`;

    if (typeof viewMeta !== "undefined") {
      viewMeta.agentflow = ["MAPA DA APLICAÇÃO", "Arquitetura do Agent IA"];
    }
    bindUi();
  }

  function visibleNodes() {
    if (!state.payload) return [];
    const query = state.search.trim().toLocaleLowerCase("pt-BR");
    return state.payload.nodes.filter((node) => {
      if (!(node.views || []).includes(state.view)) return false;
      if (state.category !== "all" && node.category !== state.category) return false;
      if (!query) return true;
      const haystack = [node.label, node.description, node.detail, node.technology, ...(node.source || [])]
        .join(" ").toLocaleLowerCase("pt-BR");
      return haystack.includes(query);
    });
  }

  function layoutNodes(nodes) {
    const grouped = new Map();
    nodes.forEach((node) => {
      if (!grouped.has(node.layer)) grouped.set(node.layer, []);
      grouped.get(node.layer).push(node);
    });
    [...grouped.values()].forEach((items) => items.sort((a, b) => a.order - b.order));

    const layers = [...grouped.keys()].sort((a, b) => a - b);
    const width = Math.max(1200, 190 + (Math.max(...layers, 0) + 1) * 205);
    const maxRows = Math.max(...[...grouped.values()].map((items) => items.length), 1);
    const height = Math.max(720, 180 + maxRows * 145);
    const positions = new Map();

    layers.forEach((layer) => {
      const items = grouped.get(layer);
      const x = 75 + layer * 205;
      const available = height - 170;
      const step = available / Math.max(items.length, 1);
      items.forEach((node, index) => {
        const y = 72 + step * index + Math.max(0, step / 2 - 54);
        positions.set(node.id, { x, y, width: 166, height: 94 });
      });
    });
    return { width, height, positions };
  }

  function renderTabs() {
    const host = document.querySelector("#app-map-tabs");
    if (!host || !state.payload) return;
    host.innerHTML = state.payload.views.map((view) => `
      <button type="button" class="app-map-tab ${view.id === state.view ? "active" : ""}" data-map-view="${safe(view.id)}" title="${safe(view.description)}">${safe(view.label)}</button>
    `).join("");
  }

  function renderCategories() {
    const host = document.querySelector("#app-map-categories");
    if (!host || !state.payload) return;
    const used = new Set(state.payload.nodes.filter((node) => (node.views || []).includes(state.view)).map((node) => node.category));
    const options = [["all", "Todos"], ...Object.entries(state.payload.categories).filter(([id]) => used.has(id))];
    host.innerHTML = options.map(([id, label]) => `
      <button type="button" class="app-map-category ${state.category === id ? "active" : ""}" data-map-category="${safe(id)}">${id === "all" ? "✣" : categoryIcon(id)}<span>${safe(label)}</span></button>
    `).join("");
  }

  function renderRuntimeSummary() {
    const host = document.querySelector("#app-map-runtime-summary");
    if (!host || !state.payload) return;
    const runtime = state.payload.runtime || {};
    host.innerHTML = `
      <span><strong>${safe(runtime.agents ?? 0)}</strong> agentes</span>
      <span><strong>${safe(runtime.agents_active ?? 0)}</strong> ativos</span>
      <span><strong>${safe(runtime.skills ?? 0)}</strong> Skills</span>
      <span><strong>${safe(runtime.queue_depth ?? 0)}</strong> fila</span>
      <span><strong>${safe(runtime.providers_selectable ?? 0)}</strong> IAs</span>`;
  }

  function edgePath(a, b) {
    const x1 = a.x + a.width;
    const y1 = a.y + a.height / 2;
    const x2 = b.x;
    const y2 = b.y + b.height / 2;
    const bend = Math.max(42, Math.abs(x2 - x1) * 0.43);
    return `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`;
  }

  function renderGraph() {
    const nodeHost = document.querySelector("#app-map-nodes");
    const edgeHost = document.querySelector("#app-map-edges");
    const stage = document.querySelector("#app-map-stage");
    const empty = document.querySelector("#app-map-empty");
    if (!nodeHost || !edgeHost || !stage || !state.payload) return;

    const nodes = visibleNodes();
    const ids = new Set(nodes.map((node) => node.id));
    const layout = layoutNodes(nodes);
    stage.style.width = `${layout.width}px`;
    stage.style.height = `${layout.height}px`;
    edgeHost.setAttribute("viewBox", `0 0 ${layout.width} ${layout.height}`);
    edgeHost.setAttribute("width", layout.width);
    edgeHost.setAttribute("height", layout.height);

    const edges = state.payload.edges.filter((edge) =>
      (edge.views || []).includes(state.view) && ids.has(edge.source) && ids.has(edge.target)
    );
    edgeHost.innerHTML = `<defs>
      <marker id="app-map-arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3 z"></path></marker>
    </defs>${edges.map((edge) => {
      const a = layout.positions.get(edge.source);
      const b = layout.positions.get(edge.target);
      return `<g class="app-map-edge ${safe(edge.kind)}"><path d="${edgePath(a, b)}" marker-end="url(#app-map-arrow)"></path><title>${safe(edge.label)}</title></g>`;
    }).join("")}`;

    nodeHost.innerHTML = nodes.map((node) => {
      const pos = layout.positions.get(node.id);
      const metrics = Object.entries(node.metrics || {}).filter(([, value]) => value !== null && value !== undefined);
      const metric = metrics.length ? `${metrics[0][0].replaceAll("_", " ")}: ${metrics[0][1]}` : node.technology;
      return `<button type="button" class="app-map-node category-${safe(node.category)} state-${safe(node.state)} ${state.selected === node.id ? "selected" : ""}" data-map-node="${safe(node.id)}" style="left:${pos.x}px;top:${pos.y}px;width:${pos.width}px;height:${pos.height}px">
        <span class="app-map-node-icon">${categoryIcon(node.category)}</span>
        <span class="app-map-node-copy"><strong>${safe(node.label)}</strong><small>${safe(metric)}</small></span>
        <span class="app-map-node-state" title="${safe(node.state_detail)}"></span>
      </button>`;
    }).join("");

    empty.hidden = nodes.length > 0;
    state.layout = layout;
    applyTransform();
    renderMinimap(nodes, layout);
  }

  function renderMinimap(nodes, layout) {
    const host = document.querySelector("#app-map-minimap");
    if (!host) return;
    if (!nodes.length) {
      host.innerHTML = "";
      return;
    }
    host.innerHTML = `<span class="app-map-minimap-label">MAPA</span><svg viewBox="0 0 ${layout.width} ${layout.height}" preserveAspectRatio="xMidYMid meet">${nodes.map((node) => {
      const pos = layout.positions.get(node.id);
      return `<rect x="${pos.x}" y="${pos.y}" width="${pos.width}" height="${pos.height}" rx="10" class="category-${safe(node.category)}"></rect>`;
    }).join("")}</svg>`;
  }

  function applyTransform() {
    const stage = document.querySelector("#app-map-stage");
    const indicator = document.querySelector("#app-map-zoom-indicator");
    if (!stage) return;
    stage.style.transform = `translate(${state.panX}px, ${state.panY}px) scale(${state.zoom})`;
    if (indicator) indicator.textContent = `${Math.round(state.zoom * 100)}%`;
  }

  function fitMap() {
    const viewport = document.querySelector("#app-map-viewport");
    if (!viewport || !state.layout) return;
    const padding = 48;
    const zx = (viewport.clientWidth - padding * 2) / state.layout.width;
    const zy = (viewport.clientHeight - padding * 2) / state.layout.height;
    state.zoom = Math.max(0.42, Math.min(1, zx, zy));
    state.panX = Math.max(18, (viewport.clientWidth - state.layout.width * state.zoom) / 2);
    state.panY = Math.max(18, (viewport.clientHeight - state.layout.height * state.zoom) / 2);
    applyTransform();
  }

  function centerMap() {
    const viewport = document.querySelector("#app-map-viewport");
    if (!viewport || !state.layout) return;
    state.panX = (viewport.clientWidth - state.layout.width * state.zoom) / 2;
    state.panY = (viewport.clientHeight - state.layout.height * state.zoom) / 2;
    applyTransform();
  }

  function renderDetail(nodeId) {
    const drawer = document.querySelector("#app-map-detail");
    if (!drawer || !state.payload) return;
    const node = state.payload.nodes.find((item) => item.id === nodeId);
    if (!node) return;
    state.selected = nodeId;
    const incoming = state.payload.edges.filter((edge) => edge.target === node.id);
    const outgoing = state.payload.edges.filter((edge) => edge.source === node.id);
    const byId = new Map(state.payload.nodes.map((item) => [item.id, item]));
    const metricRows = Object.entries(node.metrics || {}).filter(([, value]) => value !== null && value !== undefined);

    drawer.hidden = false;
    drawer.setAttribute("aria-hidden", "false");
    drawer.innerHTML = `
      <div class="app-map-detail-head"><div><p class="eyebrow">${safe(node.category_label)}</p><h3>${safe(node.label)}</h3></div><button type="button" class="icon-button" data-close-map-detail aria-label="Fechar">×</button></div>
      <div class="app-map-detail-state state-${safe(node.state)}"><span></span><strong>${safe(stateLabel(node.state))}</strong><small>${safe(node.state_detail)}</small></div>
      <section><h4>Responsabilidade</h4><p>${safe(node.description)}</p>${node.detail ? `<p>${safe(node.detail)}</p>` : ""}</section>
      <div class="app-map-detail-grid"><div><span>Tecnologia</span><strong>${safe(node.technology)}</strong></div><div><span>Camada</span><strong>${safe(node.category_label)}</strong></div>${metricRows.map(([key, value]) => `<div><span>${safe(key.replaceAll("_", " "))}</span><strong>${safe(value)}</strong></div>`).join("")}</div>
      <section><h4>Dependências de entrada</h4>${incoming.length ? incoming.map((edge) => `<button type="button" class="app-map-relation" data-map-jump="${safe(edge.source)}"><strong>${safe(byId.get(edge.source)?.label || edge.source)}</strong><span>${safe(edge.label)}</span></button>`).join("") : '<p class="muted">Nenhuma dependência de entrada neste mapa.</p>'}</section>
      <section><h4>Saídas / componentes usados</h4>${outgoing.length ? outgoing.map((edge) => `<button type="button" class="app-map-relation" data-map-jump="${safe(edge.target)}"><strong>${safe(byId.get(edge.target)?.label || edge.target)}</strong><span>${safe(edge.label)}</span></button>`).join("") : '<p class="muted">Nenhuma saída registrada.</p>'}</section>
      <section><h4>Arquivos principais</h4>${(node.source || []).length ? `<div class="app-map-source-list">${node.source.map((item) => `<code>${safe(item)}</code>`).join("")}</div>` : '<p class="muted">Componente externo à árvore local.</p>'}</section>`;
    renderGraph();
  }

  function closeDetail() {
    const drawer = document.querySelector("#app-map-detail");
    if (!drawer) return;
    drawer.hidden = true;
    drawer.setAttribute("aria-hidden", "true");
    state.selected = null;
    renderGraph();
  }

  function jumpToNode(nodeId) {
    const node = state.payload?.nodes.find((item) => item.id === nodeId);
    if (!node) return;
    if (!(node.views || []).includes(state.view)) {
      state.view = "architecture";
      state.category = "all";
      state.search = "";
      const search = document.querySelector("#app-map-search");
      if (search) search.value = "";
      renderAll();
    }
    renderDetail(nodeId);
    const pos = state.layout?.positions.get(nodeId);
    const viewport = document.querySelector("#app-map-viewport");
    if (pos && viewport) {
      state.panX = viewport.clientWidth / 2 - (pos.x + pos.width / 2) * state.zoom;
      state.panY = viewport.clientHeight / 2 - (pos.y + pos.height / 2) * state.zoom;
      applyTransform();
    }
  }

  function renderAll() {
    renderTabs();
    renderCategories();
    renderRuntimeSummary();
    renderGraph();
  }

  async function loadMap(force = false) {
    if (state.loaded && !force) {
      renderAll();
      return;
    }
    const stage = document.querySelector("#app-map-nodes");
    if (stage) stage.innerHTML = '<div class="app-map-loading">Carregando arquitetura...</div>';
    try {
      state.payload = await requestJson("/ui/api/application-map");
      state.loaded = true;
      renderAll();
      requestAnimationFrame(fitMap);
    } catch (error) {
      if (stage) stage.innerHTML = `<div class="app-map-error">${safe(error.message)}</div>`;
    }
  }

  function bindUi() {
    const view = document.querySelector("#view-agentflow");
    if (!view || view.dataset.applicationMapBound === "1") return;
    view.dataset.applicationMapBound = "1";

    view.addEventListener("click", (event) => {
      const tab = event.target.closest("[data-map-view]");
      if (tab) {
        state.view = tab.dataset.mapView;
        state.category = "all";
        state.selected = null;
        closeDetail();
        renderAll();
        requestAnimationFrame(fitMap);
        return;
      }
      const category = event.target.closest("[data-map-category]");
      if (category) {
        state.category = category.dataset.mapCategory;
        state.selected = null;
        closeDetail();
        renderAll();
        requestAnimationFrame(fitMap);
        return;
      }
      const node = event.target.closest("[data-map-node]");
      if (node) {
        renderDetail(node.dataset.mapNode);
        return;
      }
      const jump = event.target.closest("[data-map-jump]");
      if (jump) {
        jumpToNode(jump.dataset.mapJump);
        return;
      }
      if (event.target.closest("[data-close-map-detail]")) {
        closeDetail();
        return;
      }
      const action = event.target.closest("[data-map-action]")?.dataset.mapAction;
      if (action === "zoom-in") {
        state.zoom = Math.min(1.5, state.zoom + 0.1);
        applyTransform();
      } else if (action === "zoom-out") {
        state.zoom = Math.max(0.35, state.zoom - 0.1);
        applyTransform();
      } else if (action === "fit") {
        fitMap();
      } else if (action === "center") {
        centerMap();
      } else if (action === "refresh") {
        state.loaded = false;
        loadMap(true);
      }
    });

    view.querySelector("#app-map-search")?.addEventListener("input", (event) => {
      state.search = event.target.value || "";
      state.selected = null;
      closeDetail();
      renderGraph();
      requestAnimationFrame(fitMap);
    });

    const viewport = view.querySelector("#app-map-viewport");
    viewport?.addEventListener("pointerdown", (event) => {
      if (event.target.closest("button")) return;
      state.dragging = true;
      state.dragOrigin = { x: event.clientX, y: event.clientY, panX: state.panX, panY: state.panY };
      viewport.setPointerCapture?.(event.pointerId);
      viewport.classList.add("dragging");
    });
    viewport?.addEventListener("pointermove", (event) => {
      if (!state.dragging || !state.dragOrigin) return;
      state.panX = state.dragOrigin.panX + event.clientX - state.dragOrigin.x;
      state.panY = state.dragOrigin.panY + event.clientY - state.dragOrigin.y;
      applyTransform();
    });
    const stopDrag = () => {
      state.dragging = false;
      state.dragOrigin = null;
      viewport?.classList.remove("dragging");
    };
    viewport?.addEventListener("pointerup", stopDrag);
    viewport?.addEventListener("pointercancel", stopDrag);
    viewport?.addEventListener("wheel", (event) => {
      if (!event.ctrlKey) return;
      event.preventDefault();
      state.zoom = Math.max(0.35, Math.min(1.5, state.zoom + (event.deltaY < 0 ? 0.08 : -0.08)));
      applyTransform();
    }, { passive: false });
  }

  function boot() {
    ensureMapShell();
    bindFlowNav();
    organizeSidebar();
    setTimeout(() => {
      removeLegacyFlow();
      bindFlowNav();
      if (!document.querySelector(".app-nav-group")) organizeSidebar();
    }, 0);
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
