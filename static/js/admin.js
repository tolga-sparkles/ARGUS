(function () {
  const esc = App.esc;
  const tab = window.ADMIN_TAB || "dashboard";
  const content = document.getElementById("adminContent");
  let searchTimer = null;

  const STATUS_OPTIONS = ["healthy", "warning", "critical", "offline"];

  function badge(status) {
    if (status === "healthy") return '<span class="sev-badge healthy">HEALTHY</span>';
    return '<span class="sev-badge ' + esc(status) + '">' + esc(status).toUpperCase() + '</span>';
  }

  function activeBadge(active) {
    return active
      ? '<span class="sev-badge healthy">ACTIVE</span>'
      : '<span class="sev-badge unknown">INACTIVE</span>';
  }

  function errorState(message, retryId) {
    return '<div class="error-state">' +
      '<div class="error-state-title">' + esc(message) + '</div>' +
      '<button class="retry-btn" type="button" id="' + retryId + '">Retry</button></div>';
  }

  async function api(path, options) {
    const resp = await fetch(path, options);
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.error || "Request failed");
    return data;
  }

  function toolbar(searchId, statusId, addBtnId, addLabel) {
    return '<div class="toolbar">' +
      '<div class="toolbar-left">' +
      '<input type="text" class="search-input" id="' + searchId + '" placeholder="Search..." autocomplete="off">' +
      '<select class="filter-select" id="' + statusId + '">' +
      '<option value="">Status: All</option>' +
      STATUS_OPTIONS.map(s => '<option value="' + s + '">Status: ' + s[0].toUpperCase() + s.slice(1) + '</option>').join("") +
      '</select>' +
      '</div>' +
      '<div class="toolbar-meta"><button class="retry-btn" type="button" id="' + addBtnId + '">+ ' + addLabel + '</button></div>' +
      '</div>';
  }

  function formField(label, html) {
    return '<div class="admin-field"><label>' + esc(label) + '</label>' + html + '</div>';
  }

  function inputHtml(id, value, placeholder, disabled) {
    return '<input class="admin-input" id="' + id + '" value="' + esc(value || "") + '" placeholder="' + esc(placeholder || "") + '"' + (disabled ? " disabled" : "") + '>';
  }

  function selectHtml(id, options, value) {
    return '<select class="admin-input" id="' + id + '">' +
      options.map(o => '<option value="' + esc(o.value) + '"' + (String(o.value) === String(value) ? " selected" : "") + '>' + esc(o.label) + '</option>').join("") +
      '</select>';
  }

  function statusSelectHtml(id, value) {
    return selectHtml(id, STATUS_OPTIONS.map(s => ({ value: s, label: s })), value || "healthy");
  }

  function formValues(ids) {
    const out = {};
    ids.forEach(id => {
      const el = document.getElementById(id);
      if (!el) return;
      if (el.type === "checkbox") out[id] = el.checked;
      else out[id] = el.value;
    });
    return out;
  }

  async function openForm(title, fields, submitLabel, saveFn) {
    const html = '<div class="dr-header"><div class="dr-eyebrow">' + esc(title) + '</div></div>' +
      fields.map(f => formField(f.label, f.html)).join("") +
      '<div class="admin-form-actions"><button class="retry-btn" type="button" id="admSave">' + esc(submitLabel) + '</button>' +
      '<button class="retry-btn" type="button" id="admCancel">Cancel</button></div>';
    App.openDrawer(html);
    document.getElementById("admCancel").addEventListener("click", App.closeDrawer);
    document.getElementById("admSave").addEventListener("click", async function () {
      try {
        await saveFn();
        App.closeDrawer();
        load();
      } catch (e) {
        alert(e.message);
      }
    });
  }

  function hostForm(host, clusters) {
    const ids = ["hf_name", "hf_ip", "hf_cluster", "hf_status", "hf_cpu", "hf_ram", "hf_disk",
      "hf_cpu_cap", "hf_ram_cap", "hf_disk_cap", "hf_notes", "hf_sort", "hf_active"];
    const fields = [
      { label: "Host Name", html: inputHtml("hf_name", host ? host.name : "", "smp3") },
      { label: "IP Address", html: inputHtml("hf_ip", host ? host.ip_address : "", "192.0.2.2") },
      { label: "Cluster", html: selectHtml("hf_cluster", clusters.map(c => ({ value: c.id, label: c.name + " (" + c.datacenter_name + ")" })), host ? host.cluster_id : (clusters[0] ? clusters[0].id : "")) },
      { label: "Status", html: statusSelectHtml("hf_status", host ? host.status : "healthy") },
      { label: "CPU Usage %", html: inputHtml("hf_cpu", host ? host.cpu_usage : 0) },
      { label: "RAM Usage %", html: inputHtml("hf_ram", host ? host.ram_usage : 0) },
      { label: "Disk Usage %", html: inputHtml("hf_disk", host ? host.disk_usage : 0) },
      { label: "CPU Capacity", html: inputHtml("hf_cpu_cap", host ? host.cpu_capacity : "", "2 × 32 Core") },
      { label: "RAM Capacity", html: inputHtml("hf_ram_cap", host ? host.ram_capacity : "", "512 GB") },
      { label: "Disk Capacity", html: inputHtml("hf_disk_cap", host ? host.disk_capacity : "", "8 TB") },
      { label: "Notes", html: inputHtml("hf_notes", host ? host.notes : "") },
      { label: "Sort Order", html: inputHtml("hf_sort", host ? host.sort_order : 0) },
      { label: "Active", html: '<input type="checkbox" class="admin-check" id="hf_active"' + (host ? (host.active ? " checked" : "") : " checked") + '>' },
    ];
    openForm(host ? "Edit Host" : "Add Host", fields, "Save", async function () {
      const v = formValues(ids);
      const payload = {
        name: v.hf_name, ip_address: v.hf_ip, cluster_id: parseInt(v.hf_cluster, 10),
        status: v.hf_status, cpu_usage: parseFloat(v.hf_cpu || 0), ram_usage: parseFloat(v.hf_ram || 0),
        disk_usage: parseFloat(v.hf_disk || 0), cpu_capacity: v.hf_cpu_cap, ram_capacity: v.hf_ram_cap,
        disk_capacity: v.hf_disk_cap, notes: v.hf_notes, sort_order: parseInt(v.hf_sort || 0, 10), active: v.hf_active,
      };
      await api(host ? "/api/hosts/" + host.id : "/api/hosts", {
        method: host ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    });
  }

  function vmForm(vm, hosts) {
    const ids = ["vf_name", "vf_host", "vf_ip", "vf_os", "vf_role", "vf_status", "vf_cpu", "vf_ram",
      "vf_disk", "vf_uptime", "vf_notes", "vf_sort", "vf_active"];
    const fields = [
      { label: "VM Name", html: inputHtml("vf_name", vm ? vm.name : "", "NEW-SRV-01") },
      { label: "Host", html: selectHtml("vf_host", hosts.map(h => ({ value: h.id, label: h.name })), vm ? vm.host_id : (hosts[0] ? hosts[0].id : "")) },
      { label: "IP Address", html: inputHtml("vf_ip", vm ? vm.ip_address : "") },
      { label: "OS", html: inputHtml("vf_os", vm ? vm.os : "", "Windows Server 2022") },
      { label: "Role", html: inputHtml("vf_role", vm ? vm.role : "", "app") },
      { label: "Status", html: statusSelectHtml("vf_status", vm ? vm.status : "healthy") },
      { label: "CPU Usage %", html: inputHtml("vf_cpu", vm ? vm.cpu_usage : 0) },
      { label: "RAM Usage %", html: inputHtml("vf_ram", vm ? vm.ram_usage : 0) },
      { label: "Disk Usage %", html: inputHtml("vf_disk", vm ? vm.disk_usage : 0) },
      { label: "Uptime", html: inputHtml("vf_uptime", vm ? vm.uptime : "") },
      { label: "Notes", html: inputHtml("vf_notes", vm ? vm.notes : "") },
      { label: "Sort Order", html: inputHtml("vf_sort", vm ? vm.sort_order : 0) },
      { label: "Active", html: '<input type="checkbox" class="admin-check" id="vf_active"' + (vm ? (vm.active ? " checked" : "") : " checked") + '>' },
    ];
    openForm(vm ? "Edit VM" : "Add VM", fields, "Save", async function () {
      const v = formValues(ids);
      const payload = {
        name: v.vf_name, host_id: parseInt(v.vf_host, 10), ip_address: v.vf_ip, os: v.vf_os, role: v.vf_role,
        status: v.vf_status, cpu_usage: parseFloat(v.vf_cpu || 0), ram_usage: parseFloat(v.vf_ram || 0),
        disk_usage: parseFloat(v.vf_disk || 0), uptime: v.vf_uptime, notes: v.vf_notes,
        sort_order: parseInt(v.vf_sort || 0, 10), active: v.vf_active,
      };
      await api(vm ? "/api/vms/" + vm.id : "/api/vms", {
        method: vm ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    });
  }

  function dcForm(dc) {
    const fields = [
      { label: "Datacenter Name", html: inputHtml("df_name", dc ? dc.name : "") },
      { label: "Description", html: inputHtml("df_desc", dc ? dc.description : "") },
    ];
    openForm(dc ? "Edit Datacenter" : "Add Datacenter", fields, "Save", async function () {
      const v = formValues(["df_name", "df_desc"]);
      await api(dc ? "/api/datacenters/" + dc.id : "/api/datacenters", {
        method: dc ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: v.df_name, description: v.df_desc }),
      });
    });
  }

  function clusterForm(cluster, datacenters) {
    const fields = [
      { label: "Cluster Name", html: inputHtml("cf_name", cluster ? cluster.name : "") },
      { label: "Datacenter", html: selectHtml("cf_dc", datacenters.map(d => ({ value: d.id, label: d.name })), cluster ? cluster.datacenter_id : (datacenters[0] ? datacenters[0].id : "")) },
      { label: "Description", html: inputHtml("cf_desc", cluster ? cluster.description : "") },
      { label: "Sort Order", html: inputHtml("cf_sort", cluster ? cluster.sort_order : 0) },
    ];
    openForm(cluster ? "Edit Cluster" : "Add Cluster", fields, "Save", async function () {
      const v = formValues(["cf_name", "cf_dc", "cf_desc", "cf_sort"]);
      await api(cluster ? "/api/clusters/" + cluster.id : "/api/clusters", {
        method: cluster ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: v.cf_name, datacenter_id: parseInt(v.cf_dc, 10), description: v.cf_desc, sort_order: parseInt(v.cf_sort || 0, 10) }),
      });
    });
  }

  function serverForm(server) {
    const ids = ["sf_id", "sf_hostname", "sf_display", "sf_ip", "sf_site", "sf_role", "sf_env", "sf_os", "sf_prom", "sf_enabled"];
    const fields = [
      { label: "ID (stable)", html: inputHtml("sf_id", server ? server.id : "", "win-srv-02", !!server) },
      { label: "Hostname", html: inputHtml("sf_hostname", server ? server.hostname : "", "SRV-01") },
      { label: "Display Name", html: inputHtml("sf_display", server ? server.display_name : "") },
      { label: "IP Address", html: inputHtml("sf_ip", server ? server.ip : "", "192.0.2.1") },
      { label: "Site", html: inputHtml("sf_site", server ? server.site : "", "Main DC") },
      { label: "Role", html: inputHtml("sf_role", server ? server.role : "") },
      { label: "Environment", html: inputHtml("sf_env", server ? server.environment : "", "Production") },
      { label: "OS", html: selectHtml("sf_os", ["Linux", "Windows"].map(v => ({ value: v, label: v })), server ? server.os : "Linux") },
      { label: "Prometheus Instance", html: inputHtml("sf_prom", server ? server.prometheus_instance : "", "192.0.2.1:9182") },
      { label: "Enabled", html: '<input type="checkbox" class="admin-check" id="sf_enabled"' + (server ? (server.enabled ? " checked" : "") : " checked") + '>' },
    ];
    if (server && server.exporter_hostname && server.exporter_hostname.toLowerCase() !== (server.hostname || "").toLowerCase()) {
      fields.push({ label: "Exporter Bilgisi", html: '<div class="admin-env-item"><span class="vt-meta">Exporter bu cihazı bildiriyor: ' + esc(server.exporter_hostname) + '</span></div>' });
    }
    openForm(server ? "Edit Server" : "Add Server", fields, "Save", async function () {
      const v = formValues(ids);
      const payload = {
        id: v.sf_id, hostname: v.sf_hostname, display_name: v.sf_display, ip: v.sf_ip,
        site: v.sf_site, role: v.sf_role, environment: v.sf_env, os: v.sf_os,
        prometheus_instance: v.sf_prom, enabled: v.sf_enabled,
      };
      await api(server ? "/api/admin/servers/" + server.id : "/api/admin/servers", {
        method: server ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    });
  }

  async function renderServers() {
    let serversRes;
    try {
      serversRes = await api("/api/admin/servers");
    } catch (e) {
      serversRes = null;
    }
    if (!serversRes) {
      content.innerHTML = errorState("Unable to load servers.", "admRetry");
      return;
    }
    const servers = serversRes.items;
    content.innerHTML =
      '<div class="toolbar"><div class="toolbar-left">' +
      '<input type="text" class="search-input" id="admSrvSearch" placeholder="Search..." autocomplete="off">' +
      '</div><div class="toolbar-meta"><button class="retry-btn" type="button" id="admSrvAdd">+ Add Server</button></div></div>' +
      '<div class="table-wrap"><table class="data-table"><thead><tr>' +
      '<th>ID</th><th>HOSTNAME</th><th>DISPLAY NAME</th><th>IP</th><th>OS</th><th>SITE</th><th>ROLE</th><th>ENV</th><th>PROM INSTANCE</th><th>EXPORTER HOSTNAME</th><th>ENABLED</th><th>ACTIONS</th>' +
      '</tr></thead><tbody id="admSrvBody"></tbody></table></div>';
    renderSrvRows(servers);
    document.getElementById("admSrvSearch").addEventListener("input", function (e) {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => renderSrvRows(servers, e.target.value), 200);
    });
    document.getElementById("admSrvAdd").addEventListener("click", () => serverForm(null));
  }

  function renderSrvRows(servers, q) {
    q = (q || "").toLowerCase();
    const body = document.getElementById("admSrvBody");
    const rows = servers.filter(s => {
      if (q && !(s.id || "").toLowerCase().includes(q) &&
        !(s.hostname || "").toLowerCase().includes(q) &&
        !(s.display_name || "").toLowerCase().includes(q) &&
        !(s.ip || "").toLowerCase().includes(q)) return false;
      return true;
    }).map(s =>
      '<tr>' +
      '<td><span class="t-name">' + esc(s.id) + '</span></td>' +
      '<td>' + esc(s.hostname || "—") + '</td>' +
      '<td>' + esc(s.display_name || "—") + '</td>' +
      '<td><span class="t-ip">' + esc(s.ip || "—") + '</span></td>' +
      '<td>' + esc(s.os || "—") + '</td>' +
      '<td>' + esc(s.site || "—") + '</td>' +
      '<td>' + esc(s.role || "—") + '</td>' +
      '<td>' + esc(s.environment || "—") + '</td>' +
      '<td><span class="t-ip">' + esc(s.prometheus_instance || "—") + '</span></td>' +
      '<td>' + (s.exporter_hostname ? esc(s.exporter_hostname) : '<span class="vt-meta">—</span>') + '</td>' +
      '<td>' + activeBadge(s.enabled) + '</td>' +
      '<td><button class="check-now-btn" data-act="edit" data-id="' + esc(s.id) + '">EDIT</button>' +
      ' <button class="check-now-btn err" data-act="del" data-id="' + esc(s.id) + '">DEL</button></td>' +
      '</tr>'
    ).join("");
    body.innerHTML = rows || '<tr><td colspan="12"><div class="empty-state"><div class="empty-state-title">No servers found.</div></div></td></tr>';
    body.querySelectorAll("button").forEach(btn => {
      btn.addEventListener("click", async function () {
        const server = servers.find(s => s.id === btn.dataset.id);
        if (!server) return;
        if (btn.dataset.act === "edit") serverForm(server);
        else if (confirm("Delete server " + server.id + " from the inventory?")) {
          await api("/api/admin/servers/" + encodeURIComponent(server.id), { method: "DELETE" });
          load();
        }
      });
    });
  }

  async function renderScan() {
    content.innerHTML =
      '<section class="card"><h2>EXPORTER TARAMA</h2>' +
      '<div class="toolbar" style="margin-top:10px">' +
      '<button class="retry-btn" type="button" id="admScanBtn">Tara</button>' +
      '<span class="toolbar-meta">Envanterdeki sunucularda 9182 (Windows) ve 9100 (Linux) portlarını tarar; bulduklarını otomatik ekler.</span>' +
      '</div>' +
      '<div id="admScanResult" style="margin-top:14px"></div></section>';
    document.getElementById("admScanBtn").addEventListener("click", runScan);
    runScan();
  }

  async function runScan() {
    const result = document.getElementById("admScanResult");
    const btn = document.getElementById("admScanBtn");
    result.innerHTML = '<div class="placeholder">Taranıyor… (sunucu sayısına göre 1–2 dakika sürebilir)</div>';
    btn.disabled = true;
    try {
      const data = await api("/api/admin/scan-exporters", { method: "POST" });
      renderScanResult(data);
    } catch (e) {
      result.innerHTML = errorState("Tarama başarısız: " + e.message, "admRetry");
    } finally {
      btn.disabled = false;
    }
  }

  function renderScanResult(data) {
    const result = document.getElementById("admScanResult");
    const found = data.found || [];
    let html =
      '<div class="collector-list">' +
      '<div class="collector-row"><span class="collector-name">Kontrol edilen</span><span class="collector-status">' + data.checked + ' sunucu (exporter tanımsız)</span></div>' +
      '<div class="collector-row"><span class="collector-name">Yeni bulunan</span><span class="collector-status">' + found.length + ' sunucu</span></div>' +
      '<div class="collector-row"><span class="collector-name">Toplam tanımlı</span><span class="collector-status">' + data.configured + ' exporter hedefi</span></div>' +
      '</div>';
    if (found.length) {
      html += '<div class="page-list" style="margin-top:12px">' +
        found.map(f =>
          '<div class="admin-group-row"><div class="ai-main"><div class="ai-name">' + esc(f.hostname) + '</div>' +
          '<div class="ai-msg">' + esc(f.ip) + ':' + f.port + ' · ' + esc(f.os) + '</div></div>' +
          '<div class="ai-meta"><span class="sev-badge healthy">EKLENDİ</span></div></div>'
        ).join("") +
        '</div><div class="placeholder" style="margin-top:10px">Prometheus hedefleri otomatik oluşturuldu — canlı veri ~1 dakika içinde gelir.</div>';
    } else {
      html += '<div class="placeholder" style="margin-top:12px">Yeni exporter bulunamadı. Kurduğun makinelerde servis çalışıyor ve 9182/9100 portu açık olmalı.</div>';
    }
    result.innerHTML = html;
  }

  async function renderDashboard() {
    try {
      const overview = await api("/api/virtualization/overview");
      const s = overview.summary;
      content.innerHTML =
        '<div class="kpi-grid kpi-grid-6">' +
        kpiCard(s.hosts, "HOSTS", "") + kpiCard(s.vms, "VMS", "") +
        kpiCard(s.hosts_healthy, "HEALTHY HOST", "has") + kpiCard(s.hosts_warning, "WARNING HOST", "has") +
        kpiCard(s.hosts_critical, "CRITICAL HOST", "has") + kpiCard(s.hosts_offline, "OFFLINE HOST", "has") +
        '</div>' +
        '<div class="kpi-grid kpi-grid-3">' +
        kpiCard(s.avg_cpu + "%", "AVG CPU", "") + kpiCard(s.avg_ram + "%", "AVG RAM", "") + kpiCard(s.avg_disk + "%", "AVG DISK", "") +
        '</div>' +
        '<section class="card"><h2>ENVIRONMENT</h2><div class="admin-env">' +
        overview.datacenters.map(dc =>
          '<div class="admin-env-item"><span class="vt-dc-icon"></span>' + esc(dc.name) +
          '<span class="vt-meta">' + dc.clusters.length + ' clusters · ' + dc.host_count + ' hosts · ' + dc.vm_count + ' VMs</span></div>'
        ).join("") +
        '</div></section>';
    } catch (e) {
      content.innerHTML = errorState("Unable to load dashboard.", "admRetry");
    }
  }

  function kpiCard(value, label, activeClass) {
    return '<div class="kpi-card"><div class="kpi-value' + (activeClass ? " " + activeClass : "") + '">' + esc(value) + '</div><div class="kpi-label">' + label + '</div></div>';
  }

  async function renderHosts() {
    const [hostsRes, clustersRes] = await Promise.all([
      api("/api/hosts"), api("/api/clusters"),
    ]).catch(e => [null, null]);
    if (!hostsRes) {
      content.innerHTML = errorState("Unable to load hosts.", "admRetry");
      return;
    }
    const hosts = hostsRes.items;
    const clusters = clustersRes.items;
    content.innerHTML = toolbar("admHostSearch", "admHostStatus", "admHostAdd", "Add Host") +
      '<div class="table-wrap"><table class="data-table"><thead><tr>' +
      '<th>HOST NAME</th><th>IP</th><th>DATACENTER</th><th>CLUSTER</th><th>STATUS</th><th>CPU</th><th>RAM</th><th>DISK</th><th>VM COUNT</th><th>ACTIONS</th>' +
      '</tr></thead><tbody id="admHostsBody"></tbody></table></div>';
    renderHostRows(hosts, clusters);
    document.getElementById("admHostSearch").addEventListener("input", function (e) {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => renderHostRows(hosts, clusters, e.target.value, document.getElementById("admHostStatus").value), 200);
    });
    document.getElementById("admHostStatus").addEventListener("change", function (e) {
      renderHostRows(hosts, clusters, document.getElementById("admHostSearch").value, e.target.value);
    });
    document.getElementById("admHostAdd").addEventListener("click", () => hostForm(null, clusters));
  }

  function renderHostRows(hosts, clusters, q, status) {
    q = (q || "").toLowerCase();
    const body = document.getElementById("admHostsBody");
    const rows = hosts.filter(h => {
      if (q && !(h.name || "").toLowerCase().includes(q) && !(h.ip_address || "").toLowerCase().includes(q)) return false;
      if (status && h.status !== status) return false;
      return true;
    }).map(h =>
      '<tr>' +
      '<td><span class="t-name">' + esc(h.name) + '</span></td>' +
      '<td><span class="t-ip">' + esc(h.ip_address || "—") + '</span></td>' +
      '<td>' + esc(h.datacenter_name || "—") + '</td>' +
      '<td>' + esc(h.cluster_name || "—") + '</td>' +
      '<td>' + badge(h.status) + '</td>' +
      '<td><span class="t-val">' + h.cpu_usage + '%</span></td>' +
      '<td><span class="t-val">' + h.ram_usage + '%</span></td>' +
      '<td><span class="t-val">' + h.disk_usage + '%</span></td>' +
      '<td><span class="t-val">' + h.vm_count + '</span></td>' +
      '<td>' + activeBadge(h.active) +
      ' <button class="check-now-btn" data-act="edit" data-id="' + h.id + '">EDIT</button>' +
      ' <button class="check-now-btn err" data-act="del" data-id="' + h.id + '">DEL</button></td>' +
      '</tr>'
    ).join("");
    body.innerHTML = rows || '<tr><td colspan="10"><div class="empty-state"><div class="empty-state-title">No hosts found.</div></div></td></tr>';
    body.querySelectorAll("button").forEach(btn => {
      btn.addEventListener("click", async function () {
        const host = hosts.find(h => h.id === parseInt(btn.dataset.id, 10));
        if (!host) return;
        if (btn.dataset.act === "edit") hostForm(host, clusters);
        else if (confirm("Delete host " + host.name + " and its VMs?")) {
          await api("/api/hosts/" + host.id, { method: "DELETE" });
          load();
        }
      });
    });
  }

  async function renderVms() {
    const [vmsRes, hostsRes] = await Promise.all([api("/api/vms"), api("/api/hosts")]).catch(e => [null, null]);
    if (!vmsRes) {
      content.innerHTML = errorState("Unable to load VMs.", "admRetry");
      return;
    }
    const vms = vmsRes.items;
    const hosts = hostsRes.items;
    content.innerHTML = toolbar("admVmSearch", "admVmStatus", "admVmAdd", "Add VM") +
      '<div class="table-wrap"><table class="data-table"><thead><tr>' +
      '<th>VM NAME</th><th>HOST</th><th>IP</th><th>OS</th><th>ROLE</th><th>STATUS</th><th>CPU</th><th>RAM</th><th>DISK</th><th>ACTIONS</th>' +
      '</tr></thead><tbody id="admVmsBody"></tbody></table></div>';
    renderVmRows(vms, hosts);
    document.getElementById("admVmSearch").addEventListener("input", function (e) {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => renderVmRows(vms, hosts, e.target.value, document.getElementById("admVmStatus").value), 200);
    });
    document.getElementById("admVmStatus").addEventListener("change", function (e) {
      renderVmRows(vms, hosts, document.getElementById("admVmSearch").value, e.target.value);
    });
    document.getElementById("admVmAdd").addEventListener("click", () => vmForm(null, hosts));
  }

  function renderVmRows(vms, hosts, q, status) {
    q = (q || "").toLowerCase();
    const body = document.getElementById("admVmsBody");
    const rows = vms.filter(v => {
      if (q && !(v.name || "").toLowerCase().includes(q) && !(v.ip_address || "").toLowerCase().includes(q)) return false;
      if (status && v.status !== status) return false;
      return true;
    }).map(v =>
      '<tr>' +
      '<td><span class="t-name">' + esc(v.name) + '</span></td>' +
      '<td>' + esc(v.host_name || "—") + '</td>' +
      '<td><span class="t-ip">' + esc(v.ip_address || "—") + '</span></td>' +
      '<td>' + esc(v.os || "—") + '</td>' +
      '<td>' + esc(v.role || "—") + '</td>' +
      '<td>' + badge(v.status) + '</td>' +
      '<td><span class="t-val">' + v.cpu_usage + '%</span></td>' +
      '<td><span class="t-val">' + v.ram_usage + '%</span></td>' +
      '<td><span class="t-val">' + v.disk_usage + '%</span></td>' +
      '<td>' + activeBadge(v.active) +
      ' <button class="check-now-btn" data-act="edit" data-id="' + v.id + '">EDIT</button>' +
      ' <button class="check-now-btn err" data-act="del" data-id="' + v.id + '">DEL</button></td>' +
      '</tr>'
    ).join("");
    body.innerHTML = rows || '<tr><td colspan="10"><div class="empty-state"><div class="empty-state-title">No VMs found.</div></div></td></tr>';
    body.querySelectorAll("button").forEach(btn => {
      btn.addEventListener("click", async function () {
        const vm = vms.find(v => v.id === parseInt(btn.dataset.id, 10));
        if (!vm) return;
        if (btn.dataset.act === "edit") vmForm(vm, hosts);
        else if (confirm("Delete VM " + vm.name + "?")) {
          await api("/api/vms/" + vm.id, { method: "DELETE" });
          load();
        }
      });
    });
  }

  async function renderGroups() {
    const [dcRes, clRes] = await Promise.all([api("/api/datacenters"), api("/api/clusters")]).catch(e => [null, null]);
    if (!dcRes) {
      content.innerHTML = errorState("Unable to load groups.", "admRetry");
      return;
    }
    const dcs = dcRes.items;
    const clusters = clRes.items;
    content.innerHTML =
      '<div class="admin-groups-grid">' +
      '<section class="card"><h2>DATACENTERS</h2><div class="toolbar" style="margin-bottom:8px"><button class="retry-btn" type="button" id="admDcAdd">+ Add Datacenter</button></div>' +
      '<div class="page-list">' + dcs.map(dc =>
        '<div class="admin-group-row"><div class="ai-main"><div class="ai-name">' + esc(dc.name) + '</div>' +
        '<div class="ai-msg">' + esc(dc.description || "") + '</div></div>' +
        '<div class="ai-meta"><span class="ai-time">' + dc.cluster_count + ' clusters · ' + dc.host_count + ' hosts · ' + dc.vm_count + ' VMs</span>' +
        '<span><button class="check-now-btn" data-act="edit" data-id="' + dc.id + '">EDIT</button> ' +
        '<button class="check-now-btn err" data-act="del" data-id="' + dc.id + '">DEL</button></span></div></div>'
      ).join("") + '</div></section>' +
      '<section class="card"><h2>CLUSTERS</h2><div class="toolbar" style="margin-bottom:8px"><button class="retry-btn" type="button" id="admClAdd">+ Add Cluster</button></div>' +
      '<div class="page-list">' + clusters.map(cl =>
        '<div class="admin-group-row"><div class="ai-main"><div class="ai-name">' + esc(cl.name) + '</div>' +
        '<div class="ai-msg">' + esc(cl.datacenter_name || "") + (cl.description ? " · " + esc(cl.description) : "") + '</div></div>' +
        '<div class="ai-meta"><span class="ai-time">' + cl.host_count + ' hosts</span>' +
        '<span><button class="check-now-btn" data-act="edit" data-id="' + cl.id + '">EDIT</button> ' +
        '<button class="check-now-btn err" data-act="del" data-id="' + cl.id + '">DEL</button></span></div></div>'
      ).join("") + '</div></section>' +
      '</div>';
    document.getElementById("admDcAdd").addEventListener("click", () => dcForm(null));
    document.getElementById("admClAdd").addEventListener("click", () => clusterForm(null, dcs));
    content.querySelectorAll("button[data-act]").forEach(btn => {
      btn.addEventListener("click", async function () {
        const isDc = btn.closest("section").querySelector("h2").textContent.includes("DATACENTERS");
        if (btn.dataset.act === "edit") {
          if (isDc) dcForm(dcs.find(d => d.id === parseInt(btn.dataset.id, 10)));
          else clusterForm(clusters.find(c => c.id === parseInt(btn.dataset.id, 10)), dcs);
        } else {
          const name = isDc
            ? dcs.find(d => d.id === parseInt(btn.dataset.id, 10)).name
            : clusters.find(c => c.id === parseInt(btn.dataset.id, 10)).name;
          if (confirm("Delete " + name + " and everything under it?")) {
            await api((isDc ? "/api/datacenters/" : "/api/clusters/") + btn.dataset.id, { method: "DELETE" });
            load();
          }
        }
      });
    });
  }

  async function renderSettings() {
    content.innerHTML =
      '<section class="card"><h2>SETTINGS</h2>' +
      '<div class="collector-list">' +
      '<div class="collector-row"><span class="collector-name">Storage</span><span class="collector-status">SQLite · data/virtualization.db</span></div>' +
      '<div class="collector-row"><span class="collector-name">Structure</span><span class="collector-status">Datacenter → Cluster → Host → VM</span></div>' +
      '<div class="collector-row"><span class="collector-name">Demo Data</span><span class="collector-status">Kaldırıldı — sadece elle eklenen kayıtlar tutulur</span></div>' +
      '</div>' +
      '<div class="toolbar" style="margin-top:14px">' +
      '<button class="retry-btn" type="button" id="admReseed">Reset to demo data</button>' +
      '<span class="toolbar-meta">All current virtualization data will be replaced by the seed dataset.</span>' +
      '</div></section>';
    document.getElementById("admReseed").addEventListener("click", async function () {
      if (!confirm("Reset all virtualization data to the demo seed?")) return;
      await api("/api/virtualization/reseed", { method: "POST" });
      load();
    });
  }

  function load() {
    if (tab === "dashboard") renderDashboard();
    else if (tab === "servers") renderServers();
    else if (tab === "scan") renderScan();
    else if (tab === "notifications") return;
    else if (tab === "hosts") renderHosts();
    else if (tab === "vms") renderVms();
    else if (tab === "groups") renderGroups();
    else renderSettings();
  }

  content.addEventListener("click", function (event) {
    if (event.target.id === "admRetry") load();
  });

  load();
})();
