(function () {
  const esc = App.esc;
  const REFRESH_MS = 5000;
  let cache = {};
  let fullscreen = false;

  function renderInto(key, elementId, html) {
    if (cache[key] === html) return;
    cache[key] = html;
    document.getElementById(elementId).innerHTML = html;
  }

  async function refresh() {
    try {
      const dq = App.demoQS();
      const serversResp = await fetch("/api/servers?per_page=1000&sort=severity" + (dq ? "&" + dq.slice(1) : ""), { cache: "no-store" });
      if (!serversResp.ok) throw new Error("HTTP " + serversResp.status);
      const serversData = await serversResp.json();
      const alertsResp = await fetch("/api/alerts" + (dq ? "?" + dq.slice(1) : ""), { cache: "no-store" });
      if (!alertsResp.ok) throw new Error("HTTP " + alertsResp.status);
      const alertsData = await alertsResp.json();
      render(serversData.items, alertsData.items);
    } catch (e) {
      const groups = document.getElementById("wallGroups");
      if (groups) {
        groups.innerHTML = '<div class="empty-state"><div class="empty-state-title">Monitoring data unavailable.</div></div>';
      }
    }
  }

  function render(items, alerts) {
    renderKPIs(items);
    renderGroups(items);
    renderIssues(alerts);
  }

  function setKpi(id, value) {
    const el = document.getElementById(id);
    if (el.textContent !== String(value)) el.textContent = value;
    if (value > 0) el.classList.add("has");
    else el.classList.remove("has");
  }

  function renderKPIs(items) {
    const counts = { healthy: 0, warning: 0, critical: 0, offline: 0 };
    items.forEach(item => {
      if (counts[item.state] !== undefined) counts[item.state] += 1;
    });
    setKpi("wallHealthy", counts.healthy);
    setKpi("wallWarning", counts.warning);
    setKpi("wallCritical", counts.critical);
    setKpi("wallOffline", counts.offline);
  }

  function renderGroups(items) {
    const groups = {};
    items.forEach(item => {
      const name = item.role || "Unassigned";
      if (!groups[name]) groups[name] = [];
      groups[name].push(item);
    });
    const names = Object.keys(groups).sort((a, b) => a.localeCompare(b));
    const sections = names.map(name => {
      const list = groups[name];
      const tiles = list.map(item => {
        const cpu = item.cpu_percent === null || item.cpu_percent === undefined ? "—" : item.cpu_percent;
        const mem = item.memory_percent === null || item.memory_percent === undefined ? "—" : item.memory_percent;
        return '<div class="wall-tile" data-server-id="' + esc(item.id) + '" data-state="' + esc(item.state) + '" data-key="' + esc(item.id + "|" + item.state + "|" + cpu + "|" + mem) + '" title="' + esc(item.hostname + " · " + item.ip + " · " + item.state.toUpperCase()) + '">' +
          '<div class="wall-tile-name">' + esc(item.hostname) + '</div>' +
          '<div class="wall-tile-metrics">CPU ' + cpu + ' · RAM ' + mem + '</div>' +
          '<span class="wall-tile-dot ' + esc(item.state) + '"></span>' +
          '</div>';
      }).join("");
      return '<div class="wall-group-title">' + esc(name.toUpperCase()) + ' · ' + list.length + '</div>' +
        '<div class="wall-tile-grid">' + tiles + '</div>';
    }).join("");
    renderInto("wall-groups", "wallGroups", sections || '<div class="empty-state"><div class="empty-state-title">No servers in inventory.</div></div>');
  }

  function issueText(item) {
    if (item.severity === "offline") return "No response";
    return item.message;
  }

  function renderIssues(alerts) {
    const top = alerts.slice(0, 6);
    if (top.length === 0) {
      renderInto("wall-issues-empty", "wallIssues",
        '<div class="empty-state"><div class="empty-state-title">No active issues</div>' +
        '<div class="empty-state-sub">All monitored servers are within configured thresholds.</div></div>');
      return;
    }
    const rows = top.map(item =>
      '<div class="wall-issue-row">' +
      '<span class="sev-badge ' + esc(item.severity) + '">' + item.severity.toUpperCase() + '</span>' +
      '<div class="wi-main">' +
        '<div class="wi-name">' + esc(item.hostname) + '</div>' +
        '<div class="wi-issue">' + esc(issueText(item)) + '</div>' +
      '</div>' +
      '<span class="wi-duration">' + esc(item.duration_text) + '</span>' +
      '</div>'
    ).join("");
    renderInto("wall-issues", "wallIssues", rows);
  }

  function tickClock() {
    const el = document.getElementById("wallClock");
    if (!el) return;
    const trt = App.nowTRT();
    el.textContent =
      String(trt.getUTCHours()).padStart(2, "0") + ":" +
      String(trt.getUTCMinutes()).padStart(2, "0") + " TRT";
  }

  document.getElementById("wallFullscreenBtn").addEventListener("click", function () {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen && document.documentElement.requestFullscreen();
    } else {
      document.exitFullscreen && document.exitFullscreen();
    }
  });
  document.addEventListener("fullscreenchange", function () {
    fullscreen = !!document.fullscreenElement;
    document.getElementById("wallFullscreenBtn").textContent = fullscreen ? "Exit Fullscreen" : "Fullscreen";
  });

  tickClock();
  refresh();
  setInterval(refresh, REFRESH_MS);
  setInterval(tickClock, 1000);
})();
