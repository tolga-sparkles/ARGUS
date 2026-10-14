(function () {
  const esc = App.esc;
  const state = {
    q: "",
    status: "all",
    site: "",
    role: "",
    os: "",
    dc: "",
    host: "",
    sort: "severity",
    page: 1,
    per_page: 50,
    pages: 1,
    total: 0,
  };
  let loadedOnce = false;
  let searchTimer = null;
  let lastRenderedKey = "";
  const selection = new Set();
  let selectAllMatching = false;
  let activeExportDialog = null;

  document.addEventListener("click", function (event) {
    if (!activeExportDialog) return;
    if (event.target.closest("#expCustomize")) activeExportDialog.showCustomize();
    else if (event.target.closest("#expCustCancel")) activeExportDialog.showMain();
  });
  let currentPageItems = [];

  function readURL() {
    const params = new URLSearchParams(location.search);
    state.q = params.get("q") || "";
    state.status = params.get("status") || "all";
    state.site = params.get("site") || "";
    state.role = params.get("role") || "";
    state.os = params.get("os") || "";
    state.dc = params.get("datacenter") || "";
    state.host = params.get("host") || "";
    state.sort = params.get("sort") || "severity";
    state.page = Math.max(1, parseInt(params.get("page") || "1", 10) || 1);
    state.per_page = parseInt(params.get("per_page") || "50", 10);
    if (![25, 50, 100].includes(state.per_page)) state.per_page = 50;
    document.getElementById("serverSearch").value = state.q;
    document.getElementById("sortSelect").value = state.sort;
    document.getElementById("perPageSelect").value = String(state.per_page);
    document.getElementById("siteFilter").value = state.site;
    document.getElementById("roleFilter").value = state.role;
    document.getElementById("osFilter").value = state.os;
    document.getElementById("dcFilter").value = state.dc;
    document.getElementById("hostFilter").value = state.host;
    syncTabs();
  }

  function syncTabs() {
    document.querySelectorAll("#statusTabs .chip").forEach(btn => {
      btn.classList.toggle("active", btn.dataset.status === state.status);
    });
  }

  function syncURL() {
    const params = new URLSearchParams();
    if (state.q) params.set("q", state.q);
    if (state.status !== "all") params.set("status", state.status);
    if (state.site) params.set("site", state.site);
    if (state.role) params.set("role", state.role);
    if (state.os) params.set("os", state.os);
    if (state.dc) params.set("datacenter", state.dc);
    if (state.host) params.set("host", state.host);
    if (state.sort !== "severity") params.set("sort", state.sort);
    if (state.page > 1) params.set("page", String(state.page));
    if (state.per_page !== 50) params.set("per_page", String(state.per_page));
    const qs = params.toString();
    history.replaceState(null, "", location.pathname + (qs ? "?" + qs : ""));
  }

  function buildParams() {
    const params = new URLSearchParams();
    if (state.q) params.set("q", state.q);
    if (state.status !== "all") params.set("status", state.status);
    if (state.site) params.set("site", state.site);
    if (state.role) params.set("role", state.role);
    if (state.os) params.set("os", state.os);
    if (state.dc) params.set("datacenter", state.dc);
    if (state.host) params.set("host", state.host);
    params.set("sort", state.sort);
    params.set("page", String(state.page));
    params.set("per_page", String(state.per_page));
    return params;
  }

  function skeletonRows() {
    let html = "";
    for (let i = 0; i < 8; i++) {
      html += '<tr class="skeleton-row"><td colspan="10"><div class="sk-bar"></div></td></tr>';
    }
    return html;
  }

  async function load() {
    if (!loadedOnce) {
      document.getElementById("serversBody").innerHTML = skeletonRows();
      document.getElementById("serversPagination").innerHTML = "";
    }
    const params = buildParams();
    const dq = App.demoQS();
    try {
      const resp = await fetch("/api/servers?" + params.toString() + (dq ? "&" + dq.slice(1) : ""), { cache: "no-store" });
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      const data = await resp.json();
      if (!loadedOnce) {
        populateSelect("siteFilter", data.meta.sites, state.site);
        populateSelect("roleFilter", data.meta.roles, state.role);
        populateSelect("osFilter", data.meta.oses, state.os);
        populateVirtFilters();
      }
      state.pages = data.pages;
      state.total = data.total;
      currentPageItems = data.items;
      render(data);
      loadedOnce = true;
      App.markSync(data.generated_at);
    } catch (e) {
      showError();
    }
  }

  async function populateVirtFilters() {
    try {
      const resp = await fetch("/api/virtualization/overview", { cache: "no-store" });
      if (!resp.ok) return;
      const data = await resp.json();
      const dcs = [];
      const hosts = [];
      data.datacenters.forEach(dc => {
        if (!dcs.includes(dc.name)) dcs.push(dc.name);
        dc.clusters.forEach(cl => cl.hosts.forEach(h => {
          if (!hosts.includes(h.name)) hosts.push(h.name);
        }));
      });
      fillSelect("dcFilter", "Datacenter: All", dcs, state.dc);
      fillSelect("hostFilter", "Host: All", hosts, state.host);
    } catch (e) {}
  }

  function populateSelect(id, values, selected) {
    fillSelect(id, document.getElementById(id).querySelector("option").textContent, values, selected);
  }

  function fillSelect(id, allLabel, values, selected) {
    const el = document.getElementById(id);
    const current = el.value;
    el.innerHTML = '<option value="">' + allLabel + '</option>';
    values.forEach(v => {
      const opt = document.createElement("option");
      opt.value = v;
      opt.textContent = v;
      el.appendChild(opt);
    });
    el.value = selected || current || "";
  }

  function statusCell(item) {
    if (item.state === "healthy") {
      return '<span class="status-cell healthy"><span class="t-dot healthy"></span>HEALTHY</span>';
    }
    if (item.state === "unknown") {
      return '<span class="status-cell"><span class="t-dot"></span>UNKNOWN</span>';
    }
    return '<span class="sev-badge ' + esc(item.state) + '">' + item.state.toUpperCase() + '</span>';
  }

  function fmtNum(value, suffix) {
    if (value === null || value === undefined) return "—";
    return value + suffix;
  }

  function render(data) {
    const key = JSON.stringify(data.items) + "|" + JSON.stringify([...selection]);
    if (key === lastRenderedKey && loadedOnce) return;
    lastRenderedKey = key;

    document.getElementById("serversCount").textContent = data.total + " NODES";

    if (data.items.length === 0) {
      document.getElementById("serversBody").innerHTML =
        '<tr><td colspan="10"><div class="empty-state">' +
        '<div class="empty-state-title">No servers match your filters.</div>' +
        '<div class="empty-state-sub">Adjust the search or filters to see more results.</div>' +
        '</div></td></tr>';
    } else {
      const rows = data.items.map(item => {
        const checked = selection.has(item.id) ? " checked" : "";
        return '<tr class="t-row' + (selection.has(item.id) ? " selected" : "") + '" data-server-id="' + esc(item.id) + '">' +
        '<td class="td-check"><input type="checkbox" class="row-check" data-id="' + esc(item.id) + '"' + checked + '></td>' +
        '<td><div class="t-server"><span class="t-dot ' + esc(item.state) + '"></span>' +
        '<div class="t-server-text"><div class="t-name">' + esc(item.hostname) + '</div>' +
        '<div class="t-display">' + esc(item.display_name) + '</div></div></div></td>' +
        '<td><span class="t-ip">' + esc(item.ip) + '</span></td>' +
        '<td>' + statusCell(item) + '</td>' +
        '<td><div class="t-val">' + fmtNum(item.cpu_percent, "%") +
        (item.cpu_cores ? '<div class="t-display">' + esc(item.cpu_cores) + ' cores</div>' : "") +
        '</div></td>' +
        '<td><div class="t-val">' + fmtNum(item.memory_percent, "%") +
        (item.memory_total_text ? '<div class="t-display">' + esc(item.memory_used_text || "—") + ' / ' + esc(item.memory_total_text) + '</div>' : "") +
        '</div></td>' +
        '<td><div class="t-val">' + fmtNum(item.disk_usage_percent, "%") +
        (item.disk_total_text ? '<div class="t-display">' + esc(item.disk_used_text || "—") + ' / ' + esc(item.disk_total_text) + '</div>' : "") +
        '</div></td>' +
        '<td><span class="t-val">' + (item.ping_latency_ms !== null && item.ping_latency_ms !== undefined ? item.ping_latency_ms + " ms" : "—") + '</span></td>' +
        '<td><span class="t-val">' + esc(item.uptime_text || "—") + '</span></td>' +
        '<td><span class="t-val dim">' + esc(item.last_seen_text || "—") + '</span></td>' +
        '</tr>';
      }).join("");
      document.getElementById("serversBody").innerHTML = rows;
    }
    renderPagination();
    updateSelectionUI();
  }

  function renderPagination() {
    const el = document.getElementById("serversPagination");
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

  function showError() {
    document.getElementById("serversBody").innerHTML =
      '<tr><td colspan="10"><div class="error-state">' +
      '<div class="error-state-title">Unable to load server inventory.</div>' +
      '<button class="retry-btn" type="button" id="serversRetry">Retry</button>' +
      '</div></td></tr>';
    document.getElementById("serversPagination").innerHTML = "";
  }

  function updateSelectionUI() {
    const strip = document.getElementById("selectionStrip");
    const countEl = document.getElementById("selectionCount");
    const allBtn = document.getElementById("selectAllMatching");
    const checkAll = document.getElementById("checkAll");
    const pageIds = currentPageItems.map(i => i.id);
    const pageSelected = pageIds.filter(id => selection.has(id)).length;

    if (selection.size === 0) {
      strip.hidden = true;
      allBtn.hidden = true;
      selectAllMatching = false;
    } else {
      strip.hidden = false;
      countEl.textContent = selection.size + " selected" + (selectAllMatching ? " · all " + state.total + " matching" : "");
      const allMatchingSelected = selectAllMatching && selection.size >= state.total;
      allBtn.hidden = allMatchingSelected || state.total === 0;
    }
    if (pageIds.length > 0) {
      checkAll.checked = pageSelected === pageIds.length;
      checkAll.indeterminate = pageSelected > 0 && pageSelected < pageIds.length;
    } else {
      checkAll.checked = false;
      checkAll.indeterminate = false;
    }
  }

  async function fetchAllMatchingIds() {
    const params = buildParams();
    params.set("page", "1");
    params.set("per_page", "1000");
    const dq = App.demoQS();
    const resp = await fetch("/api/servers?" + params.toString() + (dq ? "&" + dq.slice(1) : ""), { cache: "no-store" });
    if (!resp.ok) return [];
    const data = await resp.json();
    return data.items.map(i => i.id);
  }

  const COLUMN_DEFS = [
    ["hostname", "Hostname"], ["display_name", "Display Name"], ["ip", "IP Address"],
    ["status", "Status"], ["os", "Operating System"], ["site", "Site"], ["role", "Role"],
    ["environment", "Environment"], ["cpu_percent", "CPU %"], ["cpu_cores", "CPU Cores"],
    ["memory_percent", "Memory %"], ["memory_used_text", "Memory Used"], ["memory_total_text", "Memory Total"],
    ["disk_usage_percent", "Disk Used %"], ["disk_free_percent", "Disk Free %"],
    ["disk_used_text", "Disk Used"], ["disk_total_text", "Disk Total"],
    ["ping_latency_ms", "Ping (ms)"], ["uptime_text", "Uptime"], ["last_seen_text", "Last Seen"],
    ["telemetry_state", "Telemetry State"], ["datacenter", "Datacenter"], ["cluster", "Cluster"],
    ["virt_host", "Virtualization Host"], ["node_type", "VM / Physical"],
  ];

  const PRESET_KEYS = {
    standard: ["hostname", "ip", "status", "os", "role", "cpu_percent", "cpu_cores", "memory_percent", "memory_used_text", "memory_total_text", "disk_usage_percent", "disk_used_text", "disk_total_text", "ping_latency_ms", "last_seen_text"],
    inventory: ["hostname", "display_name", "ip", "os", "site", "role", "environment", "datacenter", "cluster", "virt_host"],
    resource_usage: ["hostname", "status", "cpu_percent", "cpu_cores", "memory_percent", "memory_used_text", "memory_total_text", "disk_usage_percent", "disk_used_text", "disk_total_text", "ping_latency_ms", "uptime_text"],
  };

  const COLUMN_GROUPS = [
    { title: "IDENTITY", keys: ["hostname", "display_name", "ip", "os", "role", "site", "environment"] },
    { title: "HEALTH", keys: ["status", "cpu_percent", "cpu_cores", "memory_percent", "memory_used_text", "memory_total_text", "disk_usage_percent", "disk_free_percent", "disk_used_text", "disk_total_text", "ping_latency_ms", "uptime_text", "last_seen_text", "telemetry_state"] },
    { title: "INFRASTRUCTURE", keys: ["datacenter", "cluster", "virt_host", "node_type"] },
  ];

  const FIELD_DESCS = {
    hostname: "Server identifier",
    display_name: "Human readable name",
    ip: "Network address",
    status: "Current health state",
    os: "Operating system",
    role: "Server role",
    site: "Physical location",
    environment: "Prod / staging / test",
    cpu_percent: "Current processor utilization",
    cpu_cores: "Logical processor count",
    memory_percent: "Memory utilization",
    memory_used_text: "Memory used (GB)",
    memory_total_text: "Total memory (GB)",
    disk_usage_percent: "Disk usage percent",
    disk_free_percent: "Free space percent",
    disk_used_text: "Disk used (GB)",
    disk_total_text: "Total disk (GB)",
    ping_latency_ms: "ICMP latency",
    uptime_text: "Time since boot",
    last_seen_text: "Telemetry freshness",
    telemetry_state: "Exporter state",
    datacenter: "Virtualization location",
    cluster: "Host cluster",
    virt_host: "Physical host",
    node_type: "Node kind",
  };

  const COLUMN_LABELS = {};
  COLUMN_DEFS.forEach(d => { COLUMN_LABELS[d[0]] = d[1]; });

  const PRESET_DESCS = {
    standard: "Core operational columns",
    technical: "Detailed monitoring and infrastructure fields",
    inventory: "Asset and environment oriented export",
    resource_usage: "CPU, memory, disk and uptime focused",
    custom: "Manually choose columns",
  };

  const FORMAT_DESCS = {
    xlsx: "Best for operational reporting",
    csv: "Best for raw data and processing",
    pdf: "Best for management-friendly summary",
  };

  const FORMAT_LABELS = {
    xlsx: "Excel (.xlsx)",
    csv: "CSV (.csv)",
    pdf: "PDF Report (.pdf)",
  };

  function defaultColumnsFor(type) {
    return type === "technical" ? COLUMN_DEFS.map(d => d[0]) : (PRESET_KEYS[type] || PRESET_KEYS.standard);
  }

  async function fetchTotalServers() {
    try {
      const dq = App.demoQS();
      const resp = await fetch("/api/servers?per_page=1" + (dq ? "&" + dq.slice(1) : ""), { cache: "no-store" });
      if (!resp.ok) return state.total;
      const data = await resp.json();
      return data.total;
    } catch (e) {
      return state.total;
    }
  }

  function fieldLabel(key) {
    return COLUMN_LABELS[key] || key;
  }

  function openExportDialog() {
    const hasSelection = selection.size > 0;
    const defaultScope = selectAllMatching ? "selected" : "filtered";

    let scope = defaultScope;
    let reportType = "standard";
    let format = "xlsx";
    let columns = defaultColumnsFor("standard").slice();
    let modified = false;
    let allTotal = state.total;

    const summaryChips =
      '<span class="exp-chip strong" id="expChipCount">' + state.total + ' matching servers</span>' +
      (hasSelection ? '<span class="exp-chip accent" id="expChipSelected">' + selection.size + ' selected</span>' : "") +
      '<span class="exp-chip" id="expChipFilters">Filters applied</span>';

    const html =
      '<div class="exp-layout" id="expMainView">' +
      '<div class="exp-scroll">' +
      '<div class="exp-header">' +
      '<div class="exp-title">Export Servers</div>' +
      '<div class="exp-sub">Choose scope, report type, and file format.</div>' +
      '<div class="exp-summary">' + summaryChips + '</div>' +
      '</div>' +

      '<div class="exp-step"><div class="exp-step-head"><span class="exp-step-num">1</span><span class="exp-step-title">SCOPE</span></div>' +
      '<div class="exp-cards">' +
      '<button class="exp-card" type="button" data-scope="filtered">' +
      '<span class="exp-card-title">Current filtered results</span>' +
      '<span class="exp-card-desc">Export only the servers visible under current filters</span></button>' +
      '<button class="exp-card" type="button" data-scope="selected"' + (hasSelection ? "" : " disabled") + '>' +
      '<span class="exp-card-title">Selected servers</span>' +
      '<span class="exp-card-desc">' + (hasSelection ? 'Export only manually selected rows' : 'No servers selected') + '</span></button>' +
      '<button class="exp-card" type="button" data-scope="all">' +
      '<span class="exp-card-title">All servers</span>' +
      '<span class="exp-card-desc">Ignore filters and export the full inventory</span></button>' +
      '</div>' +
      '<div class="exp-filters" id="expFilters"></div>' +
      '</div>' +

      '<div class="exp-step"><div class="exp-step-head"><span class="exp-step-num">2</span><span class="exp-step-title">REPORT TYPE</span></div>' +
      '<div class="exp-cards exp-cards-mini">' +
      Object.keys(PRESET_DESCS).map(type =>
        '<button class="exp-card mini" type="button" data-type="' + type + '">' +
        '<span class="exp-card-title">' + (type === "resource_usage" ? "Resource Usage" : type[0].toUpperCase() + type.slice(1)) + '</span>' +
        '<span class="exp-card-desc">' + PRESET_DESCS[type] + '</span></button>'
      ).join("") +
      '</div>' +
      '</div>' +

      '<div class="exp-step"><div class="exp-step-head"><span class="exp-step-num">3</span><span class="exp-step-title">COLUMNS</span>' +
      '<span class="exp-col-count" id="expColCount"></span></div>' +
      '<div class="exp-col-chips" id="expColChips"></div>' +
      '<button class="exp-customize-btn" type="button" id="expCustomize">Customize Columns →</button>' +
      '</div>' +

      '<div class="exp-step"><div class="exp-step-head"><span class="exp-step-num">4</span><span class="exp-step-title">FORMAT</span></div>' +
      '<div class="exp-cards exp-cards-mini">' +
      ["xlsx", "csv", "pdf"].map(fmt =>
        '<button class="exp-card mini" type="button" data-fmt="' + fmt + '">' +
        '<span class="exp-card-title">' + FORMAT_LABELS[fmt] + '</span>' +
        '<span class="exp-card-desc">' + FORMAT_DESCS[fmt] + '</span></button>'
      ).join("") +
      '</div>' +
      '<div class="exp-warning" id="expPdfWarn" hidden>PDF works best with fewer columns. Consider Standard or Inventory preset.</div>' +
      '</div>' +
      '</div>' +

      '<div class="exp-footer">' +
      '<div class="exp-footer-summary" id="expFooterSummary">—</div>' +
      '<div class="exp-footer-actions">' +
      '<span class="exp-estimate" id="expEstimate"></span>' +
      '<button class="retry-btn" type="button" id="expCancel">Cancel</button>' +
      '<button class="retry-btn exp-run" type="button" id="expRun">Export</button>' +
      '</div>' +
      '</div>' +
      '</div>' +

      '<div class="exp-layout" id="expCustomizeView" hidden>' +
      '<div class="exp-scroll">' +
      '<div class="exp-header">' +
      '<div class="exp-title">Customize Columns</div>' +
      '<div class="exp-sub" id="expCustCount"></div>' +
      '<div class="exp-quick-actions">' +
      '<button class="chip" type="button" id="expResetStd">Reset to Standard</button>' +
      '<button class="chip" type="button" id="expSelectAllCust">Select All</button>' +
      '<button class="chip" type="button" id="expClearCust">Clear</button>' +
      '</div>' +
      '</div>' +
      '<div class="exp-step"><div class="exp-step-head"><span class="exp-step-title">SELECTED FIELDS</span></div>' +
      '<div class="exp-sel-list" id="expSelList"></div>' +
      '<div class="exp-min-warn" id="expMinWarn" hidden>Select at least one field.</div>' +
      '</div>' +
      '<div class="exp-step">' +
      '<button class="exp-add-field" type="button" id="expAddField">+ Add field</button>' +
      '<div class="exp-picker" id="expPicker" hidden>' +
      '<input class="admin-input" id="expFieldSearch" placeholder="Search fields..." autocomplete="off">' +
      '<div class="exp-picker-groups" id="expPickerGroups"></div>' +
      '</div>' +
      '</div>' +
      '</div>' +
      '<div class="exp-footer">' +
      '<div class="exp-footer-summary" id="expCustFooter">Drag to change export order.</div>' +
      '<div class="exp-footer-actions">' +
      '<button class="retry-btn" type="button" id="expCustCancel">Cancel</button>' +
      '<button class="retry-btn exp-run" type="button" id="expCustApply">Apply</button>' +
      '</div>' +
      '</div>' +
      '</div>';

    App.openDrawer(html);

    const mainView = document.getElementById("expMainView");
    const custView = document.getElementById("expCustomizeView");

    function presetName(type) {
      return type === "resource_usage" ? "Resource Usage" : type[0].toUpperCase() + type.slice(1);
    }

    function effectiveReportType() {
      if (modified && reportType !== "custom") return "Standard · Modified" === "" ? "custom" : "custom";
      return reportType;
    }

    function refresh() {
      document.querySelectorAll(".exp-card[data-scope]").forEach(el => el.classList.toggle("active", el.dataset.scope === scope));
      document.querySelectorAll(".exp-card[data-type]").forEach(el => el.classList.toggle("active", el.dataset.type === reportType));
      document.querySelectorAll(".exp-card[data-fmt]").forEach(el => el.classList.toggle("active", el.dataset.fmt === format));

      const count = scope === "selected" ? selection.size : scope === "all" ? allTotal : state.total;
      const countLabel = count + " server" + (count === 1 ? "" : "s");
      document.getElementById("expFooterSummary").textContent =
        countLabel + " · " + columns.length + " fields · " + FORMAT_LABELS[format].split(" ")[0];

      const typeLabel = modified && reportType !== "custom" ? presetName(reportType) + " · Modified" : presetName(reportType);
      document.getElementById("expColCount").textContent = columns.length + " fields selected" + (modified && reportType !== "custom" ? " · modified" : "");

      const chipsEl = document.getElementById("expColChips");
      const show = columns.slice(0, 5).map(fieldLabel);
      const more = columns.length - show.length;
      chipsEl.innerHTML = show.map(label => '<span class="exp-col-tag">' + esc(label) + '</span>').join("") +
        (more > 0 ? '<span class="exp-col-more">+' + more + ' more</span>' : "");

      const per = format === "xlsx" ? 0.25 : format === "csv" ? 0.14 : 2.4;
      const kb = Math.max(2, Math.round(count * per + 3));
      document.getElementById("expEstimate").textContent = "Estimated file: ~" + kb + " KB";

      const warn = document.getElementById("expPdfWarn");
      warn.hidden = !(format === "pdf" && (reportType === "technical" || columns.length > 8));

      renderFilterChips(scope);
      document.getElementById("expCustCount").textContent = columns.length + " fields selected";
      document.getElementById("expCustFooter").textContent = typeLabel + " · " + columns.length + " fields";
    }

    function renderFilterChips(scopeValue) {
      const el = document.getElementById("expFilters");
      if (scopeValue === "selected") {
        el.innerHTML = '<span class="exp-filters-note">' + selection.size + ' manually selected servers will be exported.</span>';
        return;
      }
      if (scopeValue === "all") {
        el.innerHTML = '<span class="exp-filters-note">Filters will be ignored — full inventory export.</span>';
        return;
      }
      const chips = [];
      const defs = [
        ["status", "Status", "all"], ["site", "Site", ""], ["role", "Role", ""],
        ["os", "OS", ""], ["dc", "Datacenter", ""], ["host", "Virtualization Host", ""],
      ];
      defs.forEach(([key, label, empty]) => {
        const value = state[key];
        if (value && value !== empty) chips.push('<span class="exp-filter-chip">' + esc(label) + ': ' + esc(value) + '</span>');
      });
      if (state.q) chips.push('<span class="exp-filter-chip">Search: ' + esc(state.q) + '</span>');
      el.innerHTML = chips.length
        ? chips.join("")
        : '<span class="exp-filters-note">No filters applied.</span>';
    }

    function renderSelected() {
      const listEl = document.getElementById("expSelList");
      listEl.innerHTML = columns.map((key, idx) =>
        '<div class="exp-sel-row" draggable="true" data-idx="' + idx + '">' +
        '<span class="exp-drag">≡</span>' +
        '<span class="exp-sel-label">' + esc(fieldLabel(key)) + '</span>' +
        '<button class="exp-remove" type="button" data-key="' + key + '" title="Remove">×</button>' +
        '</div>'
      ).join("");
      document.getElementById("expMinWarn").hidden = columns.length > 0;
      document.getElementById("expCustApply").disabled = columns.length === 0;
      document.getElementById("expCustCount").textContent = columns.length + " fields selected";
      renderPicker();
    }

    function renderPicker() {
      const groupsEl = document.getElementById("expPickerGroups");
      const search = (document.getElementById("expFieldSearch").value || "").toLowerCase();
      const selectedKeys = new Set(columns);
      let html = "";
      COLUMN_GROUPS.forEach(group => {
        const keys = group.keys.filter(key => !selectedKeys.has(key) && (!search || fieldLabel(key).toLowerCase().includes(search)));
        if (!keys.length) return;
        html += '<div class="exp-picker-group"><div class="exp-col-group-title">' + group.title + '</div>' +
          keys.map(key =>
            '<button class="exp-field-row" type="button" data-key="' + key + '">' +
            '<span class="exp-field-main"><span class="exp-field-label">' + esc(fieldLabel(key)) + '</span>' +
            '<span class="exp-field-desc">' + esc(FIELD_DESCS[key] || "") + '</span></span>' +
            '<span class="exp-field-add">+</span></button>'
          ).join("") + '</div>';
      });
      groupsEl.innerHTML = html || '<div class="exp-filters-note">No more fields to add.</div>';
    }

    function showMain() { custView.hidden = true; mainView.hidden = false; refresh(); }
    function showCustomize() {
      mainView.hidden = true;
      custView.hidden = false;
      document.getElementById("expFieldSearch").value = "";
      document.getElementById("expPicker").hidden = true;
      renderSelected();
      refresh();
    }

    document.querySelectorAll(".exp-card[data-scope]").forEach(btn => {
      btn.addEventListener("click", function () {
        if (btn.disabled) return;
        scope = btn.dataset.scope;
        refresh();
      });
    });
    document.querySelectorAll(".exp-card[data-type]").forEach(btn => {
      btn.addEventListener("click", function () {
        reportType = btn.dataset.type;
        modified = false;
        columns = defaultColumnsFor(reportType).slice();
        refresh();
        if (reportType === "custom") showCustomize();
      });
    });
    document.querySelectorAll(".exp-card[data-fmt]").forEach(btn => {
      btn.addEventListener("click", function () {
        format = btn.dataset.fmt;
        refresh();
      });
    });

    activeExportDialog = { showCustomize, showMain };
    document.getElementById("expCustApply").addEventListener("click", function () {
      modified = reportType !== "custom" ? true : modified;
      if (reportType !== "custom" && columns.join(",") === defaultColumnsFor(reportType).join(",")) modified = false;
      showMain();
    });
    document.getElementById("expResetStd").addEventListener("click", function () {
      columns = defaultColumnsFor("standard").slice();
      modified = reportType !== "custom";
      renderSelected();
    });
    document.getElementById("expSelectAllCust").addEventListener("click", function () {
      columns = COLUMN_DEFS.map(d => d[0]);
      modified = reportType !== "custom";
      renderSelected();
    });
    document.getElementById("expClearCust").addEventListener("click", function () {
      columns = [];
      modified = reportType !== "custom";
      renderSelected();
    });
    document.getElementById("expAddField").addEventListener("click", function () {
      const picker = document.getElementById("expPicker");
      picker.hidden = !picker.hidden;
      if (!picker.hidden) renderPicker();
    });
    document.getElementById("expFieldSearch").addEventListener("input", renderPicker);
    document.getElementById("expPickerGroups").addEventListener("click", function (event) {
      const row = event.target.closest(".exp-field-row");
      if (!row) return;
      columns.push(row.dataset.key);
      modified = reportType !== "custom";
      renderSelected();
    });

    const selList = document.getElementById("expSelList");
    selList.addEventListener("click", function (event) {
      const remove = event.target.closest(".exp-remove");
      if (!remove) return;
      columns = columns.filter(key => key !== remove.dataset.key);
      modified = reportType !== "custom";
      renderSelected();
    });
    let dragIdx = null;
    selList.addEventListener("dragstart", function (event) {
      const row = event.target.closest(".exp-sel-row");
      if (!row) return;
      dragIdx = parseInt(row.dataset.idx, 10);
      row.classList.add("dragging");
      event.dataTransfer.effectAllowed = "move";
    });
    selList.addEventListener("dragover", function (event) {
      event.preventDefault();
      const after = getDragAfterElement(selList, event.clientY);
      if (after == null) {
        selList.appendChild(document.querySelector(".exp-sel-row.dragging"));
      } else {
        selList.insertBefore(document.querySelector(".exp-sel-row.dragging"), after);
      }
    });
    selList.addEventListener("drop", function (event) {
      event.preventDefault();
      const rows = [...selList.querySelectorAll(".exp-sel-row")];
      columns = rows.map(row => columns[parseInt(row.dataset.idx, 10)]);
      dragIdx = null;
      modified = reportType !== "custom";
      renderSelected();
    });
    selList.addEventListener("dragend", function () {
      document.querySelectorAll(".exp-sel-row").forEach(r => r.classList.remove("dragging"));
    });

    function getDragAfterElement(container, y) {
      const rows = [...container.querySelectorAll(".exp-sel-row:not(.dragging)")];
      return rows.reduce((closest, row) => {
        const box = row.getBoundingClientRect();
        const offset = y - box.top - box.height / 2;
        if (offset < 0 && offset > closest.offset) return { offset, element: row };
        return closest;
      }, { offset: Number.NEGATIVE_INFINITY, element: null }).element;
    }

    document.getElementById("expCancel").addEventListener("click", App.closeDrawer);
    document.getElementById("expRun").addEventListener("click", async function () {
      const button = this;
      button.disabled = true;
      button.textContent = "Preparing export...";
      try {
        const payload = {
          format,
          scope,
          report_type: (modified && reportType !== "custom") ? "custom" : reportType,
          columns,
          filters: {
            q: state.q, status: state.status, site: state.site, role: state.role, os: state.os,
            environment: "", datacenter: state.dc, host: state.host, sort: state.sort,
          },
        };
        if (scope === "selected") payload.server_ids = [...selection];
        const resp = await fetch("/api/servers/export", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({}));
          throw new Error(err.error || "Unable to generate report.");
        }
        const blob = await resp.blob();
        const disposition = resp.headers.get("Content-Disposition") || "";
        const match = disposition.match(/filename="?([^";]+)"?/);
        const filename = match ? match[1] : "servers_export." + format;
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        const count = scope === "selected" ? selection.size : scope === "all" ? allTotal : state.total;
        App.closeDrawer();
        App.toast("Report generated · " + count + " servers exported");
      } catch (e) {
        button.disabled = false;
        button.textContent = "Export";
        App.toast(e.message || "Unable to generate report.", true);
      }
    });

    refresh();
    fetchTotalServers().then(total => {
      allTotal = total;
      refresh();
    });
  }

  document.getElementById("exportBtn").addEventListener("click", openExportDialog);

  document.getElementById("serversBody").addEventListener("click", function (event) {
    const retry = event.target.closest("#serversRetry");
    if (retry) { load(); return; }
    const checkbox = event.target.closest(".row-check");
    if (checkbox) {
      const id = checkbox.dataset.id;
      if (checkbox.checked) selection.add(id);
      else selection.delete(id);
      selectAllMatching = false;
      render({ items: currentPageItems, total: state.total });
      return;
    }
    const row = event.target.closest(".t-row");
    if (row) App.openServerDetail(row.dataset.serverId);
  });

  document.getElementById("checkAll").addEventListener("change", function (event) {
    currentPageItems.forEach(item => {
      if (event.target.checked) selection.add(item.id);
      else selection.delete(item.id);
    });
    selectAllMatching = false;
    render({ items: currentPageItems, total: state.total });
  });

  document.getElementById("selectAllMatching").addEventListener("click", async function () {
    const ids = await fetchAllMatchingIds();
    ids.forEach(id => selection.add(id));
    selectAllMatching = true;
    render({ items: currentPageItems, total: state.total });
  });

  document.getElementById("clearSelection").addEventListener("click", function () {
    selection.clear();
    selectAllMatching = false;
    render({ items: currentPageItems, total: state.total });
  });

  document.getElementById("serversPagination").addEventListener("click", function (event) {
    const btn = event.target.closest(".page-btn");
    if (!btn || btn.disabled) return;
    state.page = parseInt(btn.dataset.page, 10);
    syncURL();
    load();
  });

  document.getElementById("serverSearch").addEventListener("input", function (event) {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(function () {
      state.q = event.target.value.trim();
      state.page = 1;
      syncURL();
      load();
    }, 250);
  });
  document.getElementById("statusTabs").addEventListener("click", function (event) {
    const btn = event.target.closest(".chip");
    if (!btn) return;
    state.status = btn.dataset.status;
    state.page = 1;
    syncTabs();
    syncURL();
    load();
  });
  ["siteFilter", "roleFilter", "osFilter", "dcFilter", "hostFilter", "sortSelect"].forEach(id => {
    document.getElementById(id).addEventListener("change", function (event) {
      if (id === "siteFilter") state.site = event.target.value;
      else if (id === "roleFilter") state.role = event.target.value;
      else if (id === "osFilter") state.os = event.target.value;
      else if (id === "dcFilter") state.dc = event.target.value;
      else if (id === "hostFilter") state.host = event.target.value;
      else if (id === "sortSelect") state.sort = event.target.value;
      state.page = 1;
      syncURL();
      load();
    });
  });
  document.getElementById("perPageSelect").addEventListener("change", function (event) {
    state.per_page = parseInt(event.target.value, 10);
    state.page = 1;
    syncURL();
    load();
  });

  readURL();
  load();
  setInterval(function () { if (loadedOnce) load(); }, 15000);
})();
