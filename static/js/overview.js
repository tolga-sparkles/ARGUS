const REFRESH_MS = 5000;
let snapshot = null;
let lastMetricsAgeSync = 0;
let cache = {};
const esc = App.esc;

function renderInto(key, elementId, html) {
  if (cache[key] === html) return;
  cache[key] = html;
  document.getElementById(elementId).innerHTML = html;
}

async function refresh() {
  try {
    const dq = App.demoQS();
    const resp = await fetch("/api/overview" + (dq ? "?" + dq.slice(1) : ""), { cache: "no-store" });
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    const data = await resp.json();
    snapshot = data;
    lastMetricsAgeSync = Date.now();
    App.markSync(data.generated_at);
    renderAll();
  } catch (e) {
    if (snapshot === null) setBanner("CONNECTING TO MONITORING…", "", "neutral");
  }
}

function tick() {
  updateMetricsAge();
}

function updateMetricsAge() {
  const el = document.getElementById("metricsAgeVal");
  if (!el || !snapshot) return;
  const age = snapshot.collector_health.metrics_age_sec;
  if (age === null || age === undefined) { el.textContent = "Unknown"; return; }
  const current = age + Math.max(0, (Date.now() - lastMetricsAgeSync) / 1000);
  el.textContent = "Last collection " + Math.round(current) + "s ago";
}

function renderAll() {
  renderStatus();
  renderKPIs();
  renderAttention();
  renderPressure();
  renderGroups();
  renderAlerts();
  renderCollector();
  renderEvents();
  document.getElementById("serverTotal").textContent = snapshot.summary.total;
  tick();
}

function setBanner(text, sub, tone) {
  const dot = document.getElementById("statusDot");
  const bar = document.getElementById("statusBar");
  const subEl = document.getElementById("statusSub");
  document.getElementById("statusText").textContent = text;
  const cls = tone === "ok" ? " ok" : tone === "err" ? " err" : tone === "warn" ? " warn" : "";
  dot.className = "status-dot" + cls;
  bar.className = "status-pulse" + cls;
  if (sub) { subEl.textContent = sub; subEl.hidden = false; }
  else { subEl.hidden = true; }
}

function renderStatus() {
  const s = snapshot.summary;
  const problems = s.warning + s.critical + s.offline + s.no_telemetry;
  if (snapshot.data_state === "no_data") {
    setBanner("CONNECTING TO MONITORING…", "", "neutral");
  } else if (snapshot.data_state !== "ok") {
    const sub = snapshot.collector_health.prometheus === "error"
      ? "Prometheus connection failed"
      : "Monitoring data source unavailable";
    setBanner("MONITORING DATA UNAVAILABLE", sub, "err");
  } else if (problems === 0) {
    setBanner("INFRASTRUCTURE OPERATIONAL", "", "ok");
  } else if (s.critical + s.offline + s.no_telemetry === 0) {
    setBanner("INFRASTRUCTURE ATTENTION REQUIRED", "", "warn");
  } else {
    setBanner("INFRASTRUCTURE ATTENTION REQUIRED", "", "err");
  }
}

function renderKPIs() {
  const s = snapshot.summary;
  setKpi("kpiHealthy", s.healthy, "has");
  setKpi("kpiWarning", s.warning, "has");
  setKpi("kpiCritical", s.critical, "has");
  setKpi("kpiOffline", s.offline, "has");
  const note = document.getElementById("kpiNote");
  if (s.no_telemetry > 0) {
    note.textContent = "+ " + s.no_telemetry + " servers with no telemetry (NO TELEMETRY)";
    note.hidden = false;
  } else {
    note.hidden = true;
  }
}

function setKpi(id, value, activeClass) {
  const el = document.getElementById(id);
  if (el.textContent !== String(value)) el.textContent = value;
  if (value > 0) el.classList.add(activeClass);
  else el.classList.remove(activeClass);
}

function renderAttention() {
  const list = snapshot.attention;
  const countEl = document.getElementById("attentionCount");
  if (list.length > 0) {
    countEl.textContent = String(list.length);
    countEl.hidden = false;
  } else {
    countEl.hidden = true;
  }
  if (list.length === 0) {
    renderInto("attention-empty", "attentionList",
      '<div class="empty-state"><div class="empty-state-title">No servers require attention.</div></div>');
    return;
  }
  const rows = list.map(item => {
    return '<button class="attn-row" data-server-id="' + esc(item.id) + '">' +
      '<span class="sev-badge ' + esc(item.state) + '">' + esc(item.state).toUpperCase() + '</span>' +
      '<div class="attn-main">' +
        '<div class="attn-name">' + esc(item.hostname) + '</div>' +
        '<div class="attn-ip">' + esc(item.ip) + '</div>' +
      '</div>' +
      '<div class="attn-meta">' +
        '<span class="attn-reason">' + esc(item.reason) + '</span>' +
        '<span class="attn-value">' + esc(item.value) + '</span>' +
        '<span class="attn-duration">' + esc(item.duration_text) + '</span>' +
      '</div>' +
      '</button>';
  }).join("");
  renderInto("attention-" + list.map(i => i.id + i.state + i.value + i.duration_text).join("|"), "attentionList", rows);
}

function renderPressure() {
  const p = snapshot.resource_pressure;
  const tiles = [
    ["highest_cpu", "Highest CPU"],
    ["highest_memory", "Highest Memory"],
    ["lowest_disk_free", "Lowest Disk Free"],
    ["highest_ping", "Highest Ping"],
  ];
  const html = tiles.filter(([key]) => p[key]).map(([key, label]) => {
    const item = p[key];
    const text = key === "lowest_disk_free" ? item.value_text + " free" : item.value_text;
    return '<div class="pressure-item">' +
      '<div class="pressure-label">' + label + '</div>' +
      '<div class="pressure-server">' + esc(item.hostname) + '</div>' +
      '<div class="pressure-value ' + esc(item.severity) + '">' + esc(text) + '</div>' +
      '</div>';
  }).join("");
  const section = document.getElementById("pressureSection");
  if (html) {
    renderInto("pressure", "pressureGrid", html);
    section.hidden = false;
  } else {
    section.hidden = true;
  }
}

function renderGroups() {
  const groups = snapshot.groups;
  if (groups.length === 0) {
    renderInto("groups-empty", "groupList",
      '<div class="empty-state"><div class="empty-state-title">No server groups defined.</div>' +
      '<div class="empty-state-sub">Add servers to the inventory (config/servers.yaml).</div></div>');
    return;
  }
  const rows = groups.map(g => {
    const segs = [];
    const segDefs = [
      ["healthy", "seg healthy"],
      ["warning", "seg warning"],
      ["critical", "seg critical"],
      ["offline", "seg offline"],
      ["no_telemetry", "seg none"],
    ];
    for (const [field, cls] of segDefs) {
      const count = g[field] || 0;
      if (count > 0) {
        const pct = (count / g.total * 100).toFixed(2);
        segs.push('<span class="group-' + cls + '" style="width:' + pct + '%"></span>');
      }
    }
    const issues = [];
    if (g.offline > 0) issues.push('<span class="red">' + g.offline + ' offline</span>');
    if (g.critical > 0) issues.push('<span class="red">' + g.critical + ' critical</span>');
    if (g.warning > 0) issues.push('<span class="amber">' + g.warning + ' warning</span>');
    if (g.no_telemetry > 0) issues.push(g.no_telemetry + ' no telemetry');
    return '<div class="group-row">' +
      '<span class="group-name">' + esc(g.name) + '</span>' +
      '<span class="group-bar">' + segs.join("") + '</span>' +
      '<span class="group-count">' + g.healthy + ' / ' + g.total + ' healthy</span>' +
      '<span class="group-issues">' + issues.join(" · ") + '</span>' +
      '</div>';
  }).join("");
  renderInto("groups-" + JSON.stringify(groups), "groupList", rows);
}

function alertIssue(item) {
  if (item.state === "offline") return "Unreachable";
  if (item.reason === "Ping") return "Ping latency " + item.value;
  return item.reason + " usage " + item.value;
}

function renderAlerts() {
  const alerts = snapshot.attention.slice(0, 5);
  if (alerts.length === 0) {
    renderInto("alerts-empty", "alertList",
      '<div class="empty-state"><div class="empty-state-title">No active alerts</div>' +
      '<div class="empty-state-sub">All monitored servers are within configured thresholds.</div></div>');
    return;
  }
  const rows = alerts.map(item => {
    const duration = item.state === "offline" ? item.value : item.duration_text;
    return '<div class="alert-row">' +
      '<span class="sev-dot ' + esc(item.state) + '"></span>' +
      '<span class="sev-badge ' + esc(item.state) + '">' + esc(item.state).toUpperCase() + '</span>' +
      '<div class="alert-main">' +
        '<div class="alert-server">' + esc(item.hostname) + '</div>' +
        '<div class="alert-issue">' + esc(alertIssue(item)) + '</div>' +
      '</div>' +
      '<span class="alert-duration">' + esc(duration) + '</span>' +
      '</div>';
  }).join("");
  renderInto("alerts-" + JSON.stringify(alerts), "alertList", rows);
}

function renderCollector() {
  const c = snapshot.collector_health;
  const labels = c.labels || {};
  const prometheus = row(labels.prometheus || "Prometheus", c.prometheus);
  const inventory = row(labels.inventory || "Inventory", c.inventory && c.inventory.state === "loaded" ? "ok" : "unknown",
    "Loaded · " + c.inventory.count + " nodes");
  const pingProbe = row(labels.ping_probe || "Ping Probe", c.ping_probe);
  const metrics = '<div class="collector-row">' +
    '<span class="collector-name">' + esc(labels.metrics || "Metrics") + '</span>' +
    '<span class="collector-status"><span id="metricsAgeVal">Unknown</span></span></div>';
  renderInto("collector-" + c.prometheus + c.ping_probe + c.inventory.count, "collectorList",
    prometheus + inventory + pingProbe + metrics);
}

function row(name, state, customText) {
  const textMap = {
    "connected": "Connected",
    "error": "Connection failed",
    "demo": "Demo data source",
    "management": "Management Demo",
    "simulated": "Simulated",
    "ready": "Ready",
    "ok": "OK",
    "unknown": "Unknown",
  };
  const dotClass = state === "connected" || state === "ready" || state === "ok" ? "ok"
    : state === "error" ? "err" : state === "demo" || state === "management" || state === "simulated" ? "demo" : "";
  const text = customText || textMap[state] || "Unknown";
  const textClass = state === "demo" || state === "management" || state === "simulated" ? " demo-text" : "";
  return '<div class="collector-row">' +
    '<span class="collector-name">' + name + '</span>' +
    '<span class="collector-status"><span class="state-dot ' + dotClass + '"></span><span class="' + textClass + '">' + esc(text) + '</span></span></div>';
}

function renderEvents() {
  const events = snapshot.recent_events;
  if (events.length === 0) {
    renderInto("events-empty", "eventList",
      '<div class="empty-state">' +
      '<div class="empty-state-icon"><svg viewBox="0 0 16 16" width="15" height="15"><path fill="currentColor" d="M8 1a7 7 0 100 14A7 7 0 008 1zm.5 3h-1v4.2l3.4 2 .5-.8-2.9-1.7V4z"/></svg></div>' +
      '<div class="empty-state-title">No recent infrastructure events.</div>' +
      '<div class="empty-state-sub">Infrastructure state changes will appear here.</div>' +
      '</div>');
    return;
  }
  const rows = events.map(e =>
    '<div class="event-row">' +
    '<span class="event-time">' + esc(e.time_text) + '</span>' +
    '<span class="sev-dot ' + esc(e.severity) + '"></span>' +
    '<span class="event-server">' + esc(e.server) + '</span>' +
    '<span class="event-message">' + esc(e.message) + '</span>' +
    '</div>'
  ).join("");
  renderInto("events-" + JSON.stringify(events), "eventList", rows);
}

function openServerDetail(serverId) {
  App.openServerDetail(serverId);
}

document.addEventListener("click", function (event) {
  const row = event.target.closest(".attn-row");
  if (row) App.openServerDetail(row.dataset.serverId);
});

setInterval(refresh, REFRESH_MS);
setInterval(tick, 1000);
refresh();
