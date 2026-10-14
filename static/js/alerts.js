(function () {
  const esc = App.esc;
  const state = { severity: "all", q: "", site: "", role: "" };
  let loadedOnce = false;
  let searchTimer = null;
  let lastRenderedKey = "";

  function skeleton() {
    let html = "";
    for (let i = 0; i < 4; i++) {
      html += '<div class="alert-item"><div class="sk-bar"></div></div>';
    }
    return html;
  }

  async function load() {
    if (!loadedOnce) {
      document.getElementById("alertsList").innerHTML = skeleton();
    }
    const params = new URLSearchParams();
    if (state.severity !== "all") params.set("severity", state.severity);
    if (state.q) params.set("q", state.q);
    if (state.site) params.set("site", state.site);
    if (state.role) params.set("role", state.role);
    try {
      const dq = App.demoQS();
      const resp = await fetch("/api/alerts?" + params.toString() + (dq ? "&" + dq.slice(1) : ""), { cache: "no-store" });
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      const data = await resp.json();
      if (!loadedOnce) {
        populateSelect("alertRoleFilter", data.meta.roles, state.role);
        populateSelect("alertSiteFilter", data.meta.sites, state.site);
      }
      renderSummary(data.summary);
      render(data.items);
      loadedOnce = true;
      App.markSync(data.generated_at);
    } catch (e) {
      document.getElementById("alertsList").innerHTML =
        '<div class="error-state">' +
        '<div class="error-state-title">Unable to load alerts.</div>' +
        '<button class="retry-btn" type="button" id="alertsRetry">Retry</button>' +
        '</div>';
    }
  }

  function populateSelect(id, values, selected) {
    const el = document.getElementById(id);
    const current = el.value;
    el.innerHTML = '<option value="">' + (id === "alertRoleFilter" ? "Role: All" : "Site: All") + '</option>';
    values.forEach(v => {
      const opt = document.createElement("option");
      opt.value = v;
      opt.textContent = v;
      el.appendChild(opt);
    });
    el.value = selected || current || "";
  }

  function renderSummary(summary) {
    setSummary("sumActive", summary.active, "has");
    setSummary("sumCritical", summary.critical, "has");
    setSummary("sumWarning", summary.warning, "has");
    setSummary("sumOffline", summary.offline, "has");
  }

  function setSummary(id, value, activeClass) {
    const el = document.getElementById(id);
    if (el.textContent !== String(value)) el.textContent = value;
    if (value > 0) el.classList.add(activeClass);
    else el.classList.remove(activeClass);
  }

  function render(items) {
    const key = JSON.stringify(items);
    if (key === lastRenderedKey && loadedOnce) return;
    lastRenderedKey = key;

    if (items.length === 0) {
      document.getElementById("alertsList").innerHTML =
        '<div class="empty-state">' +
        '<div class="empty-state-title">No active alerts</div>' +
        '<div class="empty-state-sub">All monitored servers are within configured thresholds.</div>' +
        '</div>';
      return;
    }
    const rows = items.map(item =>
      '<div class="alert-item" data-server-id="' + esc(item.server_id) + '">' +
      '<span class="sev-badge ' + esc(item.severity) + '">' + item.severity.toUpperCase() + '</span>' +
      '<div class="ai-main">' +
        '<div class="ai-name">' + esc(item.hostname) + '</div>' +
        '<div class="ai-msg">' + esc(item.message) + '</div>' +
        '<div class="ai-ip">' + esc(item.ip) + '</div>' +
      '</div>' +
      '<div class="ai-meta">' +
        '<span class="ai-time">Started ' + esc(item.started_text) + '</span>' +
        '<span class="ai-value">Current ' + esc(item.value || "—") + '</span>' +
      '</div>' +
      '</div>'
    ).join("");
    document.getElementById("alertsList").innerHTML = rows;
  }

  document.getElementById("alertsList").addEventListener("click", function (event) {
    const retry = event.target.closest("#alertsRetry");
    if (retry) { load(); return; }
    const row = event.target.closest(".alert-item");
    if (row) App.openServerDetail(row.dataset.serverId);
  });
  document.getElementById("severityTabs").addEventListener("click", function (event) {
    const btn = event.target.closest(".chip");
    if (!btn) return;
    state.severity = btn.dataset.severity;
    document.querySelectorAll("#severityTabs .chip").forEach(chip => {
      chip.classList.toggle("active", chip.dataset.severity === state.severity);
    });
    load();
  });
  document.getElementById("alertSearch").addEventListener("input", function (event) {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(function () {
      state.q = event.target.value.trim();
      load();
    }, 250);
  });
  document.getElementById("alertRoleFilter").addEventListener("change", function (event) {
    state.role = event.target.value;
    load();
  });
  document.getElementById("alertSiteFilter").addEventListener("change", function (event) {
    state.site = event.target.value;
    load();
  });

  load();
  setInterval(function () { if (loadedOnce) load(); }, 10000);
})();
