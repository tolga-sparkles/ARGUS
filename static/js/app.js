(function () {
  let lastSyncAt = 0;
  let serverOffsetMs = 0;

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, c => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function fmtDuration(seconds) {
    if (seconds === null || seconds === undefined) return "—";
    seconds = Math.max(0, Math.floor(seconds));
    if (seconds < 60) return seconds + "s";
    if (seconds < 3600) {
      const m = Math.floor(seconds / 60), s = seconds % 60;
      return s === 0 ? m + "m" : m + "m " + s + "s";
    }
    if (seconds < 86400) {
      const h = Math.floor(seconds / 3600), m = Math.floor((seconds % 3600) / 60);
      return h + "h " + m + "m";
    }
    const d = Math.floor(seconds / 86400), h = Math.floor((seconds % 86400) / 3600);
    return d + "d " + h + "h";
  }

  function fmtAgo(seconds) {
    if (seconds === null || seconds === undefined) return "—";
    seconds = Math.max(0, Math.floor(seconds));
    if (seconds < 60) return seconds + "s ago";
    if (seconds < 3600) return Math.floor(seconds / 60) + "m ago";
    if (seconds < 86400) return Math.floor(seconds / 3600) + "h ago";
    return Math.floor(seconds / 86400) + "d ago";
  }

  function nowTRT() {
    return new Date(Date.now() + serverOffsetMs + 3 * 60 * 60 * 1000);
  }

  function tick() {
    const clock = document.getElementById("clock");
    if (clock) {
      const trt = nowTRT();
      const months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
      clock.textContent =
        String(trt.getUTCDate()).padStart(2, "0") + " " + months[trt.getUTCMonth()] + " " +
        trt.getUTCFullYear() + " · " +
        String(trt.getUTCHours()).padStart(2, "0") + ":" +
        String(trt.getUTCMinutes()).padStart(2, "0") + ":" +
        String(trt.getUTCSeconds()).padStart(2, "0");
    }
    const sync = document.getElementById("syncInfo");
    if (sync) {
      sync.textContent = lastSyncAt === 0
        ? "LAST SYNC —"
        : "LAST SYNC " + Math.max(0, Math.round((Date.now() - lastSyncAt) / 1000)) + "s AGO";
    }
  }

  function markSync(generatedAt) {
    if (generatedAt) {
      const ts = Date.parse(generatedAt);
      if (!Number.isNaN(ts)) serverOffsetMs = ts - Date.now();
    }
    lastSyncAt = Date.now();
    tick();
  }

  function setHealthFoot(mode) {
    const dot = document.getElementById("healthDot");
    const foot = document.getElementById("healthFoot");
    if (!dot || !foot) return;
    if (mode === "ok") {
      dot.className = "sidebar-foot-dot ok";
      foot.textContent = "MONITORING ACTIVE";
    } else if (mode === "degraded") {
      dot.className = "sidebar-foot-dot warn";
      foot.textContent = "MONITORING DEGRADED";
    } else {
      dot.className = "sidebar-foot-dot";
      foot.textContent = "STATUS UNKNOWN";
    }
  }

  function demoQS() {
    const params = new URLSearchParams(location.search);
    return params.get("demo") === "manager" ? "&demo=manager" : "";
  }

  function ensureDemoBadge(enabled) {
    if (!enabled) return;
    let badge = document.getElementById("demoBadge");
    if (!badge) {
      const row = document.querySelector(".status-bar .status-row");
      if (!row) return;
      badge = document.createElement("span");
      badge.className = "demo-badge";
      badge.id = "demoBadge";
      badge.textContent = "DEMO";
      row.prepend(badge);
    }
    badge.hidden = false;
  }

  async function pollHealth() {
    try {
      const resp = await fetch("/api/health" + (demoQS() ? "?" + demoQS().slice(1) : ""), { cache: "no-store" });
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      const data = await resp.json();
      ensureDemoBadge(data.demo_mode);
      if (data.prometheus === "unreachable") {
        setHealthFoot("degraded");
      } else {
        setHealthFoot("ok");
      }
    } catch (e) {
      setHealthFoot("unknown");
    }
  }

  const drawer = document.getElementById("drawer");
  const overlay = document.getElementById("drawerOverlay");

  function openDrawer(html) {
    if (!drawer || !overlay) return;
    document.getElementById("drawerContent").innerHTML = html;
    overlay.classList.add("show");
    drawer.classList.add("show");
  }

  function closeDrawer() {
    if (!drawer || !overlay) return;
    overlay.classList.remove("show");
    drawer.classList.remove("show");
    drawer.classList.remove("wide");
  }

  function drawerError(message) {
    return '<div class="error-state">' +
      '<div class="error-state-title">' + esc(message || "Unable to load data.") + '</div>' +
      '<button class="retry-btn" type="button" onclick="App.closeDrawer()">Close</button>' +
      '</div>';
  }

  function metricRow(label, value, valueClass, raw) {
    return '<div class="dr-row">' +
      '<span class="dr-row-label">' + esc(label) + '</span>' +
      '<span class="dr-row-value' + (valueClass ? " " + valueClass : "") + '">' +
      (raw ? value : esc(value === null || value === undefined ? "—" : value)) +
      '</span>' +
      '</div>';
  }

  function barFillClass(value) {
    if (value === null || value === undefined) return "";
    if (value >= 90) return " crit";
    if (value >= 70) return " warn";
    return "";
  }

  function storageBarClass(value) {
    if (value === null || value === undefined) return "";
    if (value >= 85) return " crit";
    if (value >= 70) return " warn";
    return " ok";
  }

  function meterRow(label, percent, valueText, subText) {
    const has = percent !== null && percent !== undefined;
    const width = has ? Math.max(0, Math.min(100, percent)) : 0;
    return '<div class="dr-meter">' +
      '<div class="dr-row">' +
      '<span class="dr-row-label">' + esc(label) + '</span>' +
      '<span class="dr-row-value">' + esc(valueText === null || valueText === undefined ? "—" : valueText) + '</span>' +
      '</div>' +
      (has ? '<div class="dr-bar"><div class="dr-bar-fill' + barFillClass(percent) + '" style="width:' + width + '%"></div></div>' : "") +
      (subText ? '<div class="dr-meter-sub">' + esc(subText) + '</div>' : "") +
      '</div>';
  }

  function serverDetailHTML(d) {
    const state = d.state || "unknown";
    const ping = d.ping_reachable
      ? (d.ping_latency_ms !== null && d.ping_latency_ms !== undefined ? d.ping_latency_ms + " ms" : "—")
      : "—";
    const telemetry = d.telemetry_state === "online"
      ? '<span class="dr-value-online">Online</span>'
      : d.telemetry_state === "stale"
        ? '<span class="dr-value-stale">Stale</span>'
        : '<span class="dr-value-off">Not reporting</span>';
    const badgeState = state === "healthy" ? "healthy" : state;
    const stateBadge = '<span class="dr-state-badge ' + esc(badgeState) + '">' +
      '<span class="dr-state-dot"></span>' + state.toUpperCase() + '</span>';
    const durationLine = (d.state_since && d.state_duration_text)
      ? '<div class="dr-state-duration">In this state for ' + esc(d.state_duration_text) + '</div>'
      : "";
    const packetLoss = d.packet_loss_percent === null || d.packet_loss_percent === undefined
      ? "—" : d.packet_loss_percent + "%";
    const hasStorage = d.disk_usage_percent !== null && d.disk_usage_percent !== undefined;
    const storageSummary = hasStorage
      ? '<div class="srv-storage-summary">' +
        '<div class="srv-storage-pct-row">' +
        '<span class="srv-storage-pct' + storageBarClass(d.disk_usage_percent) + '">' + d.disk_usage_percent + '%</span>' +
        '<span class="srv-storage-pct-label">USED</span>' +
        '</div>' +
        '<div class="dr-bar" style="margin:7px 0 8px"><div class="dr-bar-fill' + storageBarClass(d.disk_usage_percent) + '" style="width:' + Math.min(100, d.disk_usage_percent) + '%"></div></div>' +
        '<div class="srv-storage-inline">' + esc(d.disk_used_text || "—") + ' used · ' + esc(d.disk_free_text || "—") + ' free · ' + esc(d.disk_total_text || "—") + ' total</div>' +
        '</div>'
      : '<div class="srv-storage-none">No storage telemetry available</div>';
    const volumes = d.volumes || [];
    const volumesPanel = volumes.length
      ? '<button class="srv-vol-toggle" type="button" id="srvVolToggle">▸ View disks &amp; volumes (' + volumes.length + ')</button>' +
        '<div class="srv-vol-panel" id="srvVolPanel" hidden>' +
        volumes.map(v =>
          '<div class="srv-vol">' +
          '<div class="srv-vol-top">' +
          '<span class="srv-vol-name">' + esc(v.name) + '</span>' +
          '<span class="srv-vol-fs">' + esc(v.filesystem || "—") + (v.label ? ' · ' + esc(v.label) : '') + '</span>' +
          '<span class="srv-vol-pct ' + esc(v.status || "healthy") + '">' + v.used_percent + '%</span>' +
          '</div>' +
          '<div class="dr-bar srv-vol-bar"><div class="dr-bar-fill' + storageBarClass(v.used_percent) + '" style="width:' + Math.min(100, v.used_percent) + '%"></div></div>' +
          '<div class="srv-vol-detail">' + esc(v.used_text) + ' used · ' + esc(v.free_text) + ' free · ' + esc(v.total_text) + ' total</div>' +
          '</div>'
        ).join("") +
        '</div>'
      : "";
    const cpuVal = d.cpu_percent === null || d.cpu_percent === undefined ? null : d.cpu_percent + "%";
    const memVal = d.memory_percent === null || d.memory_percent === undefined ? null : d.memory_percent + "%";
    const memSub = d.memory_total_text ? (d.memory_used_text || "—") + " used / " + d.memory_total_text + " total" : "";
    return '<div class="srv-detail">' +
      '<div class="dr-header">' +
      '<div class="dr-eyebrow">SERVER DETAILS</div>' +
      '<div class="dr-name-wrap">' +
      '<span class="dr-name">' + esc(d.hostname) + '</span>' +
      stateBadge +
      '</div>' +
      '<div class="dr-sub">' + esc(d.display_name || "") + '</div>' +
      '<div class="dr-meta-row">' +
      (d.ip ? '<span class="dr-ip-chip">' + esc(d.ip) + '</span>' : "") +
      (d.os ? '<span class="os-badge">' + esc(d.os) + '</span>' : "") +
      '</div>' +
      durationLine +
      '</div>' +
      '<div class="dr-section"><div class="dr-sec-title">NETWORK</div>' +
      metricRow("Ping", ping) +
      metricRow("Packet Loss", packetLoss) +
      '</div>' +
      '<div class="dr-section"><div class="dr-sec-title">SYSTEM</div>' +
      meterRow("CPU", d.cpu_percent, cpuVal) +
      metricRow("CPU Cores", d.cpu_cores === null || d.cpu_cores === undefined ? "—" : d.cpu_cores) +
      meterRow("Memory", d.memory_percent, memVal, memSub) +
      metricRow("Uptime", d.uptime_text || "—") +
      '</div>' +
      '<div class="dr-section"><div class="dr-sec-title">STORAGE</div>' +
      storageSummary +
      volumesPanel +
      '</div>' +
      '<div class="dr-section"><div class="dr-sec-title">TELEMETRY</div>' +
      metricRow("Agent / Exporter", telemetry, "", true) +
      metricRow("Last Seen", d.last_seen_text || "—", "dim") +
      '</div>' +
      '<div class="dr-section"><div class="dr-sec-title">INVENTORY</div>' +
      metricRow("Site", d.site || "—") +
      metricRow("Role", d.role || "—") +
      metricRow("Environment", d.environment || "—") +
      metricRow("OS", d.os || "—") +
      '</div>' +
      '</div>';
  }

  async function openServerDetail(serverId) {
    openDrawer('<div class="drawer-loading">Loading…</div>');
    if (drawer) drawer.classList.add("wide");
    try {
      const resp = await fetch("/api/servers/" + encodeURIComponent(serverId) + (demoQS() ? "?" + demoQS().slice(1) : ""), { cache: "no-store" });
      if (!resp.ok) {
        openDrawer(drawerError("Unable to load server details."));
        return;
      }
      const data = await resp.json();
      openDrawer(serverDetailHTML(data));
      const toggle = document.getElementById("srvVolToggle");
      const panel = document.getElementById("srvVolPanel");
      if (toggle && panel) {
        toggle.addEventListener("click", function () {
          const open = panel.hidden;
          panel.hidden = !open;
          toggle.textContent = open ? "▾ Hide disks & volumes" : "▸ View disks & volumes (" + (data.volumes || []).length + ")";
        });
      }
    } catch (e) {
      openDrawer(drawerError("Unable to load server details."));
    }
  }

  function incidentTitle(item) {
    const reason = item.reason || "Resource";
    if (reason === "Unreachable") return "Host unreachable";
    if (reason === "Telemetry") return "Telemetry outage";
    return reason + " pressure";
  }

  function incidentDetailHTML(item) {
    const timeline = (item.timeline || []).map(entry =>
      '<div class="tl-row">' +
      '<span class="tl-dot ' + esc(entry.severity) + '"></span>' +
      '<span class="tl-time">' + esc(entry.time_text) + '</span>' +
      '<span class="tl-msg">' + esc(entry.message) + '</span>' +
      '<span class="tl-val">' + esc(entry.value || "") + '</span>' +
      '</div>'
    ).join("");
    const transition = item.severity.toUpperCase() + " → " + (item.status === "active" ? "ACTIVE" : "RECOVERED");
    return '<div class="dr-header">' +
      '<div class="dr-eyebrow">INCIDENT DETAIL</div>' +
      '<div class="dr-name">' + esc(item.hostname) + '</div>' +
      '<div class="dr-sub">' + esc(incidentTitle(item)) + '</div>' +
      '<div class="dr-ip">' + esc(item.ip || "") + '</div>' +
      '<span class="sev-badge ' + esc(item.severity) + '">' + esc(transition) + '</span>' +
      '</div>' +
      '<div class="dr-section"><div class="dr-sec-title">TIMELINE</div>' +
      (timeline || '<div class="dr-row"><span class="dr-row-label">No stored events.</span></div>') +
      '</div>' +
      '<div class="dr-section"><div class="dr-sec-title">SUMMARY</div>' +
      metricRow("Duration", item.duration_text || "—") +
      metricRow("Peak Value", item.peak_value || "—") +
      metricRow("Started", item.started_text || "—") +
      metricRow("Recovered", item.ended_text || "—") +
      '</div>';
  }

  function openIncidentDetail(item) {
    openDrawer(incidentDetailHTML(item));
  }

  function toast(message, isError) {
    let el = document.getElementById("appToast");
    if (!el) {
      el = document.createElement("div");
      el.id = "appToast";
      el.className = "app-toast";
      document.body.appendChild(el);
    }
    el.textContent = message;
    el.classList.toggle("error", !!isError);
    el.classList.add("show");
    clearTimeout(el._timer);
    el._timer = setTimeout(function () { el.classList.remove("show"); }, 3200);
  }

  if (overlay) {
    overlay.addEventListener("click", closeDrawer);
  }
  const drawerClose = document.getElementById("drawerClose");
  if (drawerClose) {
    drawerClose.addEventListener("click", closeDrawer);
  }
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") closeDrawer();
  });

  setInterval(tick, 1000);
  setInterval(pollHealth, 15000);
  pollHealth();
  tick();

  window.App = {
    esc,
    fmtDuration,
    fmtAgo,
    nowTRT,
    tick,
    markSync,
    demoQS,
    toast,
    openServerDetail,
    openIncidentDetail,
    openDrawer,
    closeDrawer,
  };
})();
