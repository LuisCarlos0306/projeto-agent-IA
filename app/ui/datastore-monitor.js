const DATASTORE_HISTORY_KEY = "agent-ia-datastore-history-v1";
const DATASTORE_HISTORY_LIMIT = 28;

let datastoreRefreshSeconds = 15;
let datastoreRefreshTimer = null;
let datastoreLoading = false;
let datastoreLastSnapshot = null;

function datastoreEscape(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function datastoreNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function datastoreBytes(value) {
  const bytes = datastoreNumber(value);
  if (bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / (1024 ** index)).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function datastoreCompact(value) {
  return new Intl.NumberFormat("pt-BR", { notation: "compact", maximumFractionDigits: 1 }).format(datastoreNumber(value));
}

function datastorePercent(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "sem limite";
  return `${Number(value).toFixed(1)}%`;
}

function datastoreUptime(seconds) {
  const total = datastoreNumber(seconds);
  if (total < 60) return `${Math.round(total)} s`;
  if (total < 3600) return `${Math.floor(total / 60)} min`;
  if (total < 86400) return `${Math.floor(total / 3600)} h`;
  return `${Math.floor(total / 86400)} d`;
}

function datastoreStateLabel(state) {
  return {
    available: "Disponível",
    degraded: "Atenção",
    unavailable: "Indisponível",
    healthy: "Saudável",
    attention: "Atenção",
    critical: "Crítico",
  }[state] || "Desconhecido";
}

function datastoreHistory() {
  try {
    const parsed = JSON.parse(sessionStorage.getItem(DATASTORE_HISTORY_KEY) || "[]");
    return Array.isArray(parsed) ? parsed.slice(-DATASTORE_HISTORY_LIMIT) : [];
  } catch {
    return [];
  }
}

function saveDatastoreHistory(items) {
  try {
    sessionStorage.setItem(DATASTORE_HISTORY_KEY, JSON.stringify(items.slice(-DATASTORE_HISTORY_LIMIT)));
  } catch {
    // A visualização continua funcionando mesmo quando o navegador bloqueia storage.
  }
}

function appendDatastoreHistory(snapshot) {
  const history = datastoreHistory();
  const point = {
    time: snapshot.collected_at || new Date().toISOString(),
    postgres: snapshot.postgres?.connections?.percent ?? null,
    redis: snapshot.redis?.memory?.percent ?? null,
  };
  history.push(point);
  saveDatastoreHistory(history);
  return history;
}

function datastoreLinePoints(values, width, height, left, top, right, bottom) {
  if (!values.length) return "";
  const drawableWidth = width - left - right;
  const drawableHeight = height - top - bottom;
  const divisor = Math.max(values.length - 1, 1);
  return values.map((item, index) => {
    const x = left + (index / divisor) * drawableWidth;
    const y = top + (1 - Math.max(0, Math.min(100, datastoreNumber(item.value))) / 100) * drawableHeight;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
}

function datastoreAreaPath(points, height, bottom) {
  if (!points) return "";
  const pairs = points.split(" ");
  const first = pairs[0]?.split(",")[0];
  const last = pairs.at(-1)?.split(",")[0];
  if (!first || !last) return "";
  const baseline = height - bottom;
  return `M ${first} ${baseline} L ${points.replaceAll(",", " ")} L ${last} ${baseline} Z`;
}

function datastoreChart(history) {
  const width = 700;
  const height = 218;
  const left = 42;
  const right = 18;
  const top = 15;
  const bottom = 28;
  const postgresValues = history
    .map((item, index) => ({ index, value: item.postgres }))
    .filter((item) => item.value !== null && Number.isFinite(Number(item.value)));
  const redisValues = history
    .map((item, index) => ({ index, value: item.redis }))
    .filter((item) => item.value !== null && Number.isFinite(Number(item.value)));

  if (!postgresValues.length && !redisValues.length) {
    return '<div class="datastore-chart-empty">Aguardando amostras para desenhar o gráfico.</div>';
  }

  const normalize = (items) => items.map((item) => ({ value: item.value }));
  const postgresPoints = datastoreLinePoints(normalize(postgresValues), width, height, left, top, right, bottom);
  const redisPoints = datastoreLinePoints(normalize(redisValues), width, height, left, top, right, bottom);
  const labels = [0, 25, 50, 75, 100];
  const firstTime = history[0]?.time ? new Date(history[0].time) : null;
  const lastTime = history.at(-1)?.time ? new Date(history.at(-1).time) : null;
  const timeFormat = new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit" });

  return `<svg class="datastore-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Histórico de utilização do PostgreSQL e Redis">
    <defs>
      <linearGradient id="postgresArea" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stop-color="#438fff" stop-opacity=".24"/><stop offset="100%" stop-color="#438fff" stop-opacity="0"/></linearGradient>
      <linearGradient id="redisArea" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stop-color="#7f6dff" stop-opacity=".18"/><stop offset="100%" stop-color="#7f6dff" stop-opacity="0"/></linearGradient>
    </defs>
    ${labels.map((label) => {
      const y = top + (1 - label / 100) * (height - top - bottom);
      return `<line class="grid-line" x1="${left}" y1="${y}" x2="${width - right}" y2="${y}"/><text class="axis-label" x="5" y="${y + 4}">${label}%</text>`;
    }).join("")}
    ${postgresPoints ? `<path class="postgres-area" d="${datastoreAreaPath(postgresPoints, height, bottom)}"/><polyline class="postgres-line" points="${postgresPoints}"/>` : ""}
    ${redisPoints ? `<path class="redis-area" d="${datastoreAreaPath(redisPoints, height, bottom)}"/><polyline class="redis-line" points="${redisPoints}"/>` : ""}
    <text class="axis-label" x="${left}" y="${height - 7}">${firstTime && !Number.isNaN(firstTime.getTime()) ? timeFormat.format(firstTime) : "início"}</text>
    <text class="axis-label" text-anchor="end" x="${width - right}" y="${height - 7}">${lastTime && !Number.isNaN(lastTime.getTime()) ? timeFormat.format(lastTime) : "agora"}</text>
  </svg>`;
}

function datastoreScore(snapshot) {
  let score = snapshot.status === "healthy" ? 98 : snapshot.status === "attention" ? 72 : 35;
  const connectionPercent = datastoreNumber(snapshot.postgres?.connections?.percent, 0);
  const memoryPercent = datastoreNumber(snapshot.redis?.memory?.percent, 0);
  if (connectionPercent >= 75) score -= Math.round((connectionPercent - 75) * .8);
  if (memoryPercent >= 75) score -= Math.round((memoryPercent - 75) * .8);
  if (datastoreNumber(snapshot.redis?.clients?.blocked) > 0) score -= 8;
  return Math.max(0, Math.min(100, score));
}

function datastoreSummaryCard(label, value, detail, state = "available") {
  return `<article class="datastore-summary-card">
    <header><span>${datastoreEscape(label)}</span><i class="datastore-state-dot" data-state="${datastoreEscape(state)}"></i></header>
    <strong title="${datastoreEscape(value)}">${datastoreEscape(value)}</strong>
    <small title="${datastoreEscape(detail)}">${datastoreEscape(detail)}</small>
  </article>`;
}

function datastoreStat(label, value, title = "") {
  return `<div class="datastore-stat"${title ? ` title="${datastoreEscape(title)}"` : ""}><span>${datastoreEscape(label)}</span><strong>${datastoreEscape(value)}</strong></div>`;
}

function datastoreDetailCard(snapshot, kind) {
  const isPostgres = kind === "postgres";
  const data = isPostgres ? snapshot.postgres || {} : snapshot.redis || {};
  const percent = isPostgres ? data.connections?.percent : data.memory?.percent;
  const safePercent = Math.max(0, Math.min(100, datastoreNumber(percent, 0)));
  const barLabel = isPostgres ? "Uso de conexões" : "Uso do limite de memória";
  const barValue = percent === null || percent === undefined ? "sem limite configurado" : datastorePercent(percent);

  const stats = isPostgres
    ? [
        datastoreStat("Tamanho", datastoreBytes(data.size_bytes)),
        datastoreStat("Conexões", `${data.connections?.active ?? "—"} / ${data.connections?.max ?? "—"}`),
        datastoreStat("Cache hit", datastorePercent(data.cache_hit_percent)),
        datastoreStat("Commits", datastoreCompact(data.transactions?.committed)),
        datastoreStat("Rollbacks", datastoreCompact(data.transactions?.rolled_back)),
        datastoreStat("Deadlocks", datastoreCompact(data.deadlocks)),
      ]
    : [
        datastoreStat("Memória", datastoreBytes(data.memory?.used_bytes)),
        datastoreStat("Pico", datastoreBytes(data.memory?.peak_bytes)),
        datastoreStat("Clientes", datastoreCompact(data.clients?.connected)),
        datastoreStat("Operações/s", datastoreCompact(data.operations_per_second)),
        datastoreStat("Chaves", datastoreCompact(data.keys)),
        datastoreStat("Fila", datastoreCompact(data.queue?.depth)),
      ];

  return `<article class="datastore-panel datastore-detail-card" data-kind="${kind}">
    <div class="datastore-detail-title">
      <div><h3>${isPostgres ? "PostgreSQL" : "Redis"}</h3><span>${datastoreEscape(data.version || "versão não identificada")}</span></div>
      <span><i class="datastore-state-dot" data-state="${datastoreEscape(data.state)}"></i> ${datastoreEscape(datastoreStateLabel(data.state))}</span>
    </div>
    <div class="datastore-resource-bar">
      <div class="datastore-resource-bar-head"><span>${datastoreEscape(barLabel)}</span><strong>${datastoreEscape(barValue)}</strong></div>
      <div class="datastore-resource-track"><div class="datastore-resource-fill" style="width:${safePercent}%"></div></div>
    </div>
    <div class="datastore-stat-grid">${stats.join("")}</div>
  </article>`;
}

function datastoreRender(snapshot, history) {
  const monitor = document.querySelector("#datastore-monitor");
  if (!monitor) return;
  const postgres = snapshot.postgres || {};
  const redis = snapshot.redis || {};
  const score = datastoreScore(snapshot);
  const collected = snapshot.collected_at ? new Date(snapshot.collected_at) : new Date();
  const collectedText = Number.isNaN(collected.getTime())
    ? "agora"
    : new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(collected);

  monitor.innerHTML = `
    <header class="datastore-monitor-head">
      <div><p class="eyebrow">RECURSOS DA APLICAÇÃO</p><h2>PostgreSQL e Redis</h2><p>Visão operacional segura, sem exibir usuários, senhas ou strings de conexão.</p></div>
      <div class="datastore-monitor-actions">
        <label>Atualização <select id="datastore-refresh-rate">
          <option value="15"${datastoreRefreshSeconds === 15 ? " selected" : ""}>15 segundos</option>
          <option value="30"${datastoreRefreshSeconds === 30 ? " selected" : ""}>30 segundos</option>
          <option value="60"${datastoreRefreshSeconds === 60 ? " selected" : ""}>1 minuto</option>
          <option value="0"${datastoreRefreshSeconds === 0 ? " selected" : ""}>Manual</option>
        </select></label>
        <button class="datastore-refresh" id="datastore-refresh" type="button">Atualizar agora</button>
      </div>
    </header>
    <div class="datastore-summary-grid">
      ${datastoreSummaryCard("PostgreSQL", `${postgres.connections?.active ?? "—"} conexões`, `${datastorePercent(postgres.connections?.percent)} do limite`, postgres.state)}
      ${datastoreSummaryCard("Redis", datastoreBytes(redis.memory?.used_bytes), `${datastoreCompact(redis.operations_per_second)} operações por segundo`, redis.state)}
      ${datastoreSummaryCard("Fila operacional", `${redis.queue?.depth ?? "—"} job(s)`, `modo ${redis.queue?.execution_mode || "—"}`, redis.state)}
      ${datastoreSummaryCard("Última coleta", collectedText, `${history.length} amostra(s) nesta sessão`, snapshot.status)}
    </div>
    <div class="datastore-main-grid">
      <article class="datastore-panel">
        <div class="datastore-panel-head">
          <div><p>UTILIZAÇÃO</p><h3>Histórico de recursos</h3></div>
          <div class="datastore-chart-legend"><span><i></i>Conexões PostgreSQL</span><span><i></i>Memória Redis</span></div>
        </div>
        <div class="datastore-chart-wrap">${datastoreChart(history)}</div>
      </article>
      <article class="datastore-panel datastore-score-panel">
        <div class="datastore-panel-head"><div><p>ESTADO GERAL</p><h3>${datastoreEscape(datastoreStateLabel(snapshot.status))}</h3></div><i class="datastore-state-dot" data-state="${datastoreEscape(snapshot.status)}"></i></div>
        <div class="datastore-score-ring" style="--score:${score}"><div><strong>${score}</strong><span>saúde</span></div></div>
        <div class="datastore-score-list">
          <div class="datastore-score-row"><span>PostgreSQL</span><strong>${datastoreEscape(datastoreStateLabel(postgres.state))}</strong></div>
          <div class="datastore-score-row"><span>Redis</span><strong>${datastoreEscape(datastoreStateLabel(redis.state))}</strong></div>
          <div class="datastore-score-row"><span>Uptime Redis</span><strong>${datastoreEscape(datastoreUptime(redis.uptime_seconds))}</strong></div>
          <div class="datastore-score-row"><span>Cache PostgreSQL</span><strong>${datastoreEscape(datastorePercent(postgres.cache_hit_percent))}</strong></div>
        </div>
      </article>
    </div>
    <div class="datastore-detail-grid">
      ${datastoreDetailCard(snapshot, "postgres")}
      ${datastoreDetailCard(snapshot, "redis")}
    </div>`;

  datastoreBindControls();
}

function datastoreRenderError(message) {
  const monitor = document.querySelector("#datastore-monitor");
  if (!monitor) return;
  monitor.innerHTML = `
    <header class="datastore-monitor-head">
      <div><p class="eyebrow">RECURSOS DA APLICAÇÃO</p><h2>PostgreSQL e Redis</h2><p>Não foi possível atualizar as métricas neste momento.</p></div>
      <div class="datastore-monitor-actions"><button class="datastore-refresh" id="datastore-refresh" type="button">Tentar novamente</button></div>
    </header>
    <div class="datastore-monitor-message error">${datastoreEscape(message)}</div>`;
  datastoreBindControls();
}

async function datastoreLoad() {
  if (datastoreLoading) return;
  datastoreLoading = true;
  const button = document.querySelector("#datastore-refresh");
  if (button) {
    button.disabled = true;
    button.textContent = "Atualizando...";
  }
  try {
    const response = await fetch("/ui/api/datastores/resources", {
      method: "GET",
      headers: { Accept: "application/json" },
      credentials: "same-origin",
      cache: "no-store",
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || `Falha HTTP ${response.status}`);
    datastoreLastSnapshot = payload;
    const history = appendDatastoreHistory(payload);
    datastoreRender(payload, history);
  } catch (error) {
    datastoreRenderError(error instanceof Error ? error.message : "Falha desconhecida ao consultar os bancos.");
  } finally {
    datastoreLoading = false;
  }
}

function datastoreSchedule() {
  if (datastoreRefreshTimer) window.clearInterval(datastoreRefreshTimer);
  datastoreRefreshTimer = null;
  if (datastoreRefreshSeconds <= 0) return;
  datastoreRefreshTimer = window.setInterval(() => {
    if (document.hidden || !document.querySelector("#view-dashboard")?.classList.contains("active")) return;
    void datastoreLoad();
  }, datastoreRefreshSeconds * 1000);
}

function datastoreBindControls() {
  document.querySelector("#datastore-refresh")?.addEventListener("click", () => void datastoreLoad());
  document.querySelector("#datastore-refresh-rate")?.addEventListener("change", (event) => {
    datastoreRefreshSeconds = datastoreNumber(event.target.value, 15);
    datastoreSchedule();
    if (datastoreLastSnapshot) datastoreRender(datastoreLastSnapshot, datastoreHistory());
  });
}

function datastoreInstall() {
  const dashboard = document.querySelector("#view-dashboard");
  if (!dashboard || document.querySelector("#datastore-monitor")) return;
  const monitor = document.createElement("section");
  monitor.id = "datastore-monitor";
  monitor.className = "datastore-monitor";
  monitor.setAttribute("aria-live", "polite");
  monitor.innerHTML = '<div class="datastore-monitor-message">Carregando recursos do PostgreSQL e Redis...</div>';
  const dashboardGrid = dashboard.querySelector(".dashboard-grid");
  if (dashboardGrid) dashboardGrid.before(monitor);
  else dashboard.append(monitor);
  datastoreSchedule();
  void datastoreLoad();
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", datastoreInstall, { once: true });
else datastoreInstall();
