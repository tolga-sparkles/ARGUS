(function () {
  const esc = App.esc;
  const REFRESH_MS = 5000;
  const FLEET_PAGE_SIZE = 30;
  const ROTATE_MS = 8000;
  const CHART_POINTS = 60;

  let fleetItems = [];
  let fleetPage = 0;
  let fleetPages = 1;
  let cpuHistory = [];
  let cpuSeeded = false;
  let throughputHistory = [];
  let lastThroughput = null;
  let loadedOnce = false;

  const ROLE_TAGS = {
    "Database": "DB",
    "Application": "APP",
    "Web": "WEB",
    "File": "FILE",
    "Infrastructure": "INFRA",
    "Cache": "CACHE",
  };

  function roleTag(role) {
    if (ROLE_TAGS[role]) return ROLE_TAGS[role];
    const upper = String(role || "").toUpperCase();
    if (upper.includes("CACHE")) return "CACHE";
    return upper.slice(0, 4) || "SRV";
  }

  function lcg(seed) {
    let state = seed >>> 0;
    return function () {
      state = (state * 1664525 + 1013904223) >>> 0;
      return state / 4294967296;
    };
  }

  function mockThroughputSeries() {
    const rand = lcg(12345);
    const series = [];
    for (let i = 0; i < CHART_POINTS; i++) {
      series.push(round1(40.5 + 4.2 * Math.sin(i / 9.0) + rand() * 2.4));
    }
    return series;
  }

  function mockCpuSeries() {
    const rand = lcg(777);
    const series = [];
    for (let i = 0; i < 45; i++) {
      let value = 34 + 7 * Math.sin(i / 6.0) + rand() * 3;
      if (i >= 27 && i <= 31) value = 88 + rand() * 8;
      series.push(round1(value));
    }
    return series;
  }

  function round1(value) {
    return Math.round(value * 10) / 10;
  }

  async function refresh() {
    const dq = App.demoQS();
    try {
      const serversResp = await fetch("/api/servers?per_page=1000&sort=severity" + (dq ? "&" + dq.slice(1) : ""), { cache: "no-store" });
      if (!serversResp.ok) throw new Error("HTTP " + serversResp.status);
      const serversData = await serversResp.json();
      const alertsResp = await fetch("/api/alerts" + (dq ? "?" + dq.slice(1) : ""), { cache: "no-store" });
      if (!alertsResp.ok) throw new Error("HTTP " + alertsResp.status);
      const alertsData = await alertsResp.json();
      try {
        const throughputResp = await fetch("/api/network-throughput" + (dq ? "?" + dq.slice(1) : ""), { cache: "no-store" });
        if (throughputResp.ok) {
          lastThroughput = await throughputResp.json();
        }
      } catch (e) {
        lastThroughput = null;
      }
      renderWallMode2(serversData, alertsData);
      App.markSync(serversData.generated_at);
      loadedOnce = true;
    } catch (e) {
      if (!loadedOnce) {
        document.getElementById("wall2StatusText").textContent = "MONITORING DATA UNAVAILABLE";
        document.getElementById("wall2Fleet").innerHTML = '<div class="wall2-empty"><div class="wall2-empty-title">Unable to load fleet data.</div></div>';
        document.getElementById("wall2Alerts").innerHTML = '<div class="wall2-empty"><div class="wall2-empty-title">Unable to load alerts.</div></div>';
      }
    }
  }

  function renderWallMode2(serversData, alertsData) {
    const items = serversData.items;
    const counts = { healthy: 0, warning: 0, critical: 0, offline: 0, no_telemetry: 0 };
    items.forEach(item => {
      if (counts[item.state] !== undefined) counts[item.state] += 1;
    });
    fleetItems = items;
    renderWallMode2Header(counts, items);
    renderWallMode2KPIs(counts);
    renderWallMode2Alerts(alertsData.items);
    renderWallMode2FleetGrid();
    renderWallMode2ThroughputChart();
    renderWallMode2CpuChart(items);
  }

  function renderWallMode2Header(counts, items) {
    const problems = counts.warning + counts.critical + counts.offline + counts.no_telemetry;
    const statusEl = document.getElementById("wall2Status");
    const textEl = document.getElementById("wall2StatusText");
    if (problems > 0) {
      statusEl.className = "wall2-status err";
      textEl.textContent = "ATTENTION REQUIRED";
    } else {
      statusEl.className = "wall2-status ok";
      textEl.textContent = "ALL SYSTEMS HEALTHY";
    }
    const reachable = items.filter(i => i.ping_reachable && i.ping_latency_ms !== null && i.ping_latency_ms !== undefined);
    const avgPing = reachable.length
      ? round1(reachable.reduce((sum, i) => sum + i.ping_latency_ms, 0) / reachable.length)
      : null;
    document.getElementById("wall2Ping").textContent = avgPing === null ? "AVG PING —" : "AVG PING " + avgPing + " ms";
  }

  function renderWallMode2KPIs(counts) {
    setKpi("wall2KpiHealthy", "healthy", counts.healthy);
    setKpi("wall2KpiWarning", "warning", counts.warning);
    setKpi("wall2KpiCritical", "critical", counts.critical);
    setKpi("wall2KpiOffline", "offline", counts.offline);
  }

  function setKpi(id, kind, value) {
    const valueEl = document.getElementById(id);
    if (valueEl.textContent !== String(value)) valueEl.textContent = value;
    const card = valueEl.closest(".wall2-kpi");
    card.classList.toggle(kind, true);
    if (value > 0) card.classList.add("has");
    else card.classList.remove("has");
  }

  function renderWallMode2Alerts(alerts) {
    const countEl = document.getElementById("wall2AlertsCount");
    const listEl = document.getElementById("wall2Alerts");
    if (alerts.length === 0) {
      countEl.textContent = "";
      listEl.innerHTML = '<div class="wall2-empty"><div class="wall2-empty-title">No active alerts</div>' +
        '<div class="wall2-empty-sub">All monitored servers are within configured thresholds.</div></div>';
      return;
    }
    countEl.textContent = "· " + alerts.length;
    const visible = alerts.slice(0, 6);
    const rows = visible.map(item =>
      '<div class="wall2-alert sev-' + esc(item.severity) + '">' +
      '<span class="wall2-alert-dot ' + esc(item.severity) + '"></span>' +
      '<div class="wall2-alert-main">' +
        '<div class="wall2-alert-name">' + esc(item.hostname) + '</div>' +
        '<div class="wall2-alert-msg">' + esc(item.message) + '</div>' +
      '</div>' +
      '<span class="wall2-alert-time">' + esc(item.started_text) + '</span>' +
      '</div>'
    ).join("");
    const more = alerts.length > visible.length
      ? '<div class="wall2-alerts-more">+' + (alerts.length - visible.length) + ' more</div>'
      : "";
    listEl.innerHTML = rows + more;
  }

  function renderWallMode2FleetGrid() {
    const gridEl = document.getElementById("wall2Fleet");
    const metaEl = document.getElementById("wall2FleetMeta");
    if (fleetItems.length === 0) {
      metaEl.textContent = "";
      gridEl.innerHTML = '<div class="wall2-empty"><div class="wall2-empty-title">No servers in inventory.</div></div>';
      return;
    }
    fleetPages = Math.max(1, Math.ceil(fleetItems.length / FLEET_PAGE_SIZE));
    if (fleetPage >= fleetPages) fleetPage = fleetPages - 1;
    const start = fleetPage * FLEET_PAGE_SIZE;
    const slice = fleetItems.slice(start, start + FLEET_PAGE_SIZE);

    const tiles = slice.map(item =>
      '<div class="wall2-tile" title="' + esc(item.hostname + " · " + item.ip + " · " + item.state.toUpperCase()) + '">' +
      '<span class="wall2-tile-name">' + esc(item.hostname) + '</span>' +
      '<span class="wall2-tile-role">' + esc(roleTag(item.role)) + '</span>' +
      '<span class="wall2-tile-dot ' + esc(item.state) + '"></span>' +
      '</div>'
    ).join("");

    const hidden = fleetItems.length - (start + slice.length);
    metaEl.textContent = fleetItems.length + " NODES" + (hidden > 0 ? " · +" + hidden + " MORE" : "");

    let dots = "";
    if (fleetPages > 1) {
      dots = '<div class="wall2-page-dots">';
      for (let p = 0; p < fleetPages; p++) {
        dots += '<span class="wall2-page-dot' + (p === fleetPage ? " active" : "") + '"></span>';
      }
      dots += "</div>";
    }
    gridEl.innerHTML = tiles + dots;
  }

  function advanceFleetPage() {
    if (fleetPages <= 1 || !loadedOnce) return;
    fleetPage = (fleetPage + 1) % fleetPages;
    renderWallMode2FleetGrid();
  }

  function setupCanvas(canvas) {
    const dpr = window.devicePixelRatio || 1;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (!width || !height) return null;
    if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) {
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx, width, height };
  }

  function drawEmptyChart(canvas, message) {
    const setup = setupCanvas(canvas);
    if (!setup) return;
    const { ctx, width, height } = setup;
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = "#767f8a";
    ctx.font = "12px -apple-system, 'Segoe UI', Roboto, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(message, width / 2, height / 2);
  }

  function renderWallMode2ThroughputChart() {
    const canvas = document.getElementById("wall2ThroughputChart");
    const sumEl = document.getElementById("wall2ThroughputSum");
    const isDemo = window.WALL2_DEMO === true || App.demoQS() !== "";
    if (!isDemo) {
      sumEl.textContent = "";
      drawEmptyChart(canvas, "Network throughput telemetry is not collected yet.");
      return;
    }
    const series = mockThroughputSeries();
    const avg = series.reduce((s, v) => s + v, 0) / series.length;
    sumEl.textContent = round1(avg) + " Gbps";

    const setup = setupCanvas(canvas);
    if (!setup) return;
    const { ctx, width, height } = setup;
    ctx.clearRect(0, 0, width, height);
    const max = Math.max.apply(null, series) * 1.08;
    const min = Math.min.apply(null, series) * 0.95;
    const barW = width / series.length;
    series.forEach((value, i) => {
      const h = Math.max(2, ((value - min) / (max - min)) * (height - 14));
      const x = i * barW + barW * 0.18;
      const y = height - 6 - h;
      ctx.fillStyle = i % 7 === 6 ? "rgba(88,166,255,0.75)" : "rgba(63,185,80,0.55)";
      ctx.fillRect(x, y, barW * 0.64, h);
    });
  }

  function renderWallMode2CpuChart(items) {
    const canvas = document.getElementById("wall2CpuChart");
    const sumEl = document.getElementById("wall2CpuSum");
    const withCpu = items.filter(i => i.cpu_percent !== null && i.cpu_percent !== undefined);
    const currentAvg = withCpu.length
      ? round1(withCpu.reduce((s, i) => s + i.cpu_percent, 0) / withCpu.length)
      : null;

    if (window.WALL2_DEMO === true && !cpuSeeded) {
      cpuHistory = mockCpuSeries();
      cpuSeeded = true;
    }
    if (currentAvg !== null) {
      cpuHistory.push(currentAvg);
      if (cpuHistory.length > CHART_POINTS) cpuHistory = cpuHistory.slice(-CHART_POINTS);
    }

    if (cpuHistory.length === 0) {
      sumEl.textContent = "";
      drawEmptyChart(canvas, "Collecting CPU data…");
      return;
    }
    sumEl.textContent = currentAvg !== null ? currentAvg + "%" : "—";

    const setup = setupCanvas(canvas);
    if (!setup) return;
    const { ctx, width, height } = setup;
    ctx.clearRect(0, 0, width, height);

    const padTop = 8;
    const padBottom = 16;
    const chartH = height - padTop - padBottom;
    const max = 100;
    const stepX = width / (CHART_POINTS - 1);
    const yOf = value => padTop + chartH * (1 - value / max);

    ctx.strokeStyle = "rgba(210,153,34,0.5)";
    ctx.setLineDash([5, 5]);
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, yOf(85));
    ctx.lineTo(width, yOf(85));
    ctx.stroke();
    ctx.setLineDash([]);

    const startIndex = Math.max(0, CHART_POINTS - cpuHistory.length);
    const series = cpuHistory.slice(-CHART_POINTS);
    const offset = startIndex;

    ctx.beginPath();
    ctx.moveTo(0, height);
    series.forEach((value, i) => {
      ctx.lineTo((offset + i) * stepX, yOf(value));
    });
    ctx.lineTo((offset + series.length - 1) * stepX, height);
    ctx.closePath();
    ctx.fillStyle = "rgba(88,166,255,0.10)";
    ctx.fill();

    series.forEach((value, i) => {
      if (i === 0) return;
      const prev = series[i - 1];
      const color = value >= 90 || prev >= 90 ? "#f85149"
        : value >= 80 || prev >= 80 ? "#d29922"
        : "#58a6ff";
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo((offset + i - 1) * stepX, yOf(prev));
      ctx.lineTo((offset + i) * stepX, yOf(value));
      ctx.stroke();
    });
  }

  setInterval(refresh, REFRESH_MS);
  setInterval(advanceFleetPage, ROTATE_MS);
  window.addEventListener("resize", function () {
    if (loadedOnce) {
      renderWallMode2ThroughputChart();
      renderWallMode2CpuChart(fleetItems);
    }
  });

  window.renderWallMode2Header = renderWallMode2Header;
  window.renderWallMode2KPIs = renderWallMode2KPIs;
  window.renderWallMode2Alerts = renderWallMode2Alerts;
  window.renderWallMode2FleetGrid = renderWallMode2FleetGrid;
  window.renderWallMode2ThroughputChart = renderWallMode2ThroughputChart;
  window.renderWallMode2CpuChart = renderWallMode2CpuChart;

  refresh();
})();
