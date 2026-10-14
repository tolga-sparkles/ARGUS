(function () {
  const esc = App.esc;
  const state = { q: "", status: "all", severity: "all", range: "all", page: 1, pages: 1 };
  let loadedOnce = false;
  let searchTimer = null;
  let lastRenderedKey = "";
  let itemsCache = [];

  function readURL() {
    const params = new URLSearchParams(location.search);
    state.q = params.get("q") || "";
    state.status = params.get("status") || "all";
    state.severity = params.get("severity") || "all";
    state.range = params.get("range") || "all";
    state.page = Math.max(1, parseInt(params.get("page") || "1", 10) || 1);
    document.getElementById("historySearch").value = state.q;
    document.getElementById("severitySelect").value = state.severity;
    document.getElementById("rangeSelect").value = state.range;
    syncTabs();
  }

  function syncTabs() {
    document.querySelectorAll("#historyStatusTabs .chip").forEach(btn => {
      btn.classList.toggle("active", btn.dataset.status === state.status);
    });
  }

  function syncURL() {
    const params = new URLSearchParams();
    if (state.q) params.set("q", state.q);
    if (state.status !== "all") params.set("status", state.status);
    if (state.severity !== "all") params.set("severity", state.severity);
    if (state.range !== "all") params.set("range", state.range);
    if (state.page > 1) params.set("page", String(state.page));
    const qs = params.toString();
    history.replaceState(null, "", location.pathname + (qs ? "?" + qs : ""));
  }

  function skeleton() {
    let html = "";
    for (let i = 0; i < 4; i++) {
      html += '<div class="hist-row"><div class="sk-bar"></div></div>';
    }
    return html;
  }

  async function load() {
    if (!loadedOnce) {
      document.getElementById("historyList").innerHTML = skeleton();
    }
    const params = new URLSearchParams();
    if (state.q) params.set("q", state.q);
    if (state.status !== "all") params.set("status", state.status);
    if (state.severity !== "all") params.set("severity", state.severity);
    if (state.range !== "all") params.set("range", state.range);
    params.set("page", String(state.page));
    params.set("per_page", "25");
    try {
      const dq = App.demoQS();
      const resp = await fetch("/api/history?" + params.toString() + (dq ? "&" + dq.slice(1) : ""), { cache: "no-store" });
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      const data = await resp.json();
      state.pages = data.pages;
      render(data.items);
      renderPagination();
      loadedOnce = true;
      App.markSync(data.generated_at);
    } catch (e) {
      document.getElementById("historyList").innerHTML =
        '<div class="error-state">' +
        '<div class="error-state-title">Unable to load history.</div>' +
        '<button class="retry-btn" type="button" id="historyRetry">Retry</button>' +
        '</div>';
      document.getElementById("historyPagination").innerHTML = "";
    }
  }

  function transitionText(item) {
    const reason = (item.reason || "Resource").toUpperCase();
    return reason + " " + item.severity.toUpperCase() +
      " → " + (item.status === "active" ? "ACTIVE" : "RECOVERED");
  }

  function render(items) {
    const key = JSON.stringify(items);
    if (key === lastRenderedKey && loadedOnce) return;
    lastRenderedKey = key;
    itemsCache = items;

    if (items.length === 0) {
      document.getElementById("historyList").innerHTML =
        '<div class="empty-state">' +
        '<div class="empty-state-icon"><svg viewBox="0 0 16 16" width="15" height="15"><path fill="currentColor" d="M8 1a7 7 0 100 14A7 7 0 008 1zm.5 3h-1v4.2l3.4 2 .5-.8-2.9-1.7V4z"/></svg></div>' +
        '<div class="empty-state-title">No infrastructure history available.</div>' +
        '<div class="empty-state-sub">State changes will appear here as incidents are detected and recovered.</div>' +
        '</div>';
      return;
    }
    const rows = items.map((item, idx) =>
      '<div class="hist-row" data-idx="' + idx + '">' +
      '<div class="hist-main">' +
        '<div class="hist-name">' + esc(item.hostname) + '</div>' +
        '<div class="hist-ip">' + esc(item.ip || "") + '</div>' +
      '</div>' +
      '<div class="hist-title">' + esc(transitionText(item)) + '</div>' +
      '<div class="hist-meta">' +
        '<span>Started <b>' + esc(item.started_text) + '</b></span>' +
        '<span>' + (item.ended_text ? 'Recovered <b>' + esc(item.ended_text) + '</b>' : '<b class="hist-active">ACTIVE</b>') + '</span>' +
        '<span>Duration <b>' + esc(item.duration_text || "—") + '</b></span>' +
        '<span>Peak <b>' + esc(item.peak_value || "—") + '</b></span>' +
      '</div>' +
      '</div>'
    ).join("");
    document.getElementById("historyList").innerHTML = rows;
  }

  function renderPagination() {
    const el = document.getElementById("historyPagination");
    if (state.pages <= 1) { el.innerHTML = ""; return; }
    let html = '<button class="page-btn" data-page="' + (state.page - 1) + '"' + (state.page <= 1 ? " disabled" : "") + '>‹</button>';
    const start = Math.max(1, state.page - 3);
    const end = Math.min(state.pages, state.page + 3);
    for (let p = start; p <= end; p++) {
      html += '<button class="page-btn' + (p === state.page ? " active" : "") + '" data-page="' + p + '">' + p + '</button>';
    }
    html += '<button class="page-btn" data-page="' + (state.page + 1) + '"' + (state.page >= state.pages ? " disabled" : "") + '>›</button>';
    el.innerHTML = html;
  }

  document.getElementById("historyList").addEventListener("click", function (event) {
    const retry = event.target.closest("#historyRetry");
    if (retry) { load(); return; }
    const row = event.target.closest(".hist-row");
    if (!row) return;
    const item = itemsCache[parseInt(row.dataset.idx, 10)];
    if (item) App.openIncidentDetail(item);
  });
  document.getElementById("historyPagination").addEventListener("click", function (event) {
    const btn = event.target.closest(".page-btn");
    if (!btn || btn.disabled) return;
    state.page = parseInt(btn.dataset.page, 10);
    syncURL();
    load();
  });
  document.getElementById("historyStatusTabs").addEventListener("click", function (event) {
    const btn = event.target.closest(".chip");
    if (!btn) return;
    state.status = btn.dataset.status;
    state.page = 1;
    syncTabs();
    syncURL();
    load();
  });
  document.getElementById("historySearch").addEventListener("input", function (event) {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(function () {
      state.q = event.target.value.trim();
      state.page = 1;
      syncURL();
      load();
    }, 250);
  });
  document.getElementById("severitySelect").addEventListener("change", function (event) {
    state.severity = event.target.value;
    state.page = 1;
    syncURL();
    load();
  });
  document.getElementById("rangeSelect").addEventListener("change", function (event) {
    state.range = event.target.value;
    state.page = 1;
    syncURL();
    load();
  });

  readURL();
  load();
})();
