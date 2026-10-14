(function () {
  const esc = App.esc;
  const REFRESH_MS = 10000;
  const EXPAND_KEY = "virtExpanded";

  let tree = null;
  let summary = null;
  let selected = null;
  let loadedOnce = false;
  let expanded = loadExpanded();

  function loadExpanded() {
    try {
      const raw = JSON.parse(localStorage.getItem(EXPAND_KEY) || "{}");
      return new Set(raw.items || []);
    } catch (e) {
      return new Set();
    }
  }

  function saveExpanded() {
    try {
      localStorage.setItem(EXPAND_KEY, JSON.stringify({ items: [...expanded] }));
    } catch (e) {}
  }

  function nodeKey(type, id) {
    return type + ":" + id;
  }

  function isExpanded(type, id) {
    if (type === "datacenter" || type === "cluster" || type === "host") return !expanded.has("!" + nodeKey(type, id));
    return expanded.has(nodeKey(type, id));
  }

  function toggleExpanded(type, id) {
    const key = nodeKey(type, id);
    const bang = "!" + key;
    const group = type === "datacenter" || type === "cluster" || type === "host";
    if (isExpanded(type, id)) {
      if (group) expanded.add(bang);
      else expanded.delete(key);
    } else {
      if (group) expanded.delete(bang);
      else expanded.add(key);
    }
    saveExpanded();
    renderTree();
  }

  async function refresh() {
    try {
      const resp = await fetch("/api/virtualization/overview", { cache: "no-store" });
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      const data = await resp.json();
      tree = data;
      summary = data.summary;
      if (!loadedOnce) {
        const first = findFirstHost(data);
        if (first) selected = { type: "host", id: first.id };
        loadedOnce = true;
      }
      renderKPIs();
      renderTree();
      renderDetail();
      App.markSync(data.generated_at);
    } catch (e) {
      if (!loadedOnce) {
        document.getElementById("virtTree").innerHTML =
          '<div class="error-state"><div class="error-state-title">Unable to load virtualization data.</div>' +
          '<button class="retry-btn" type="button" onclick="window.location.reload()">Retry</button></div>';
      }
    }
  }

  function findFirstHost(data) {
    for (const dc of data.datacenters) {
      for (const cluster of dc.clusters) {
        if (cluster.hosts.length) return cluster.hosts[0];
      }
    }
    return null;
  }

  function renderKPIs() {
    const s = summary;
    setKpi("vkHosts", s.hosts, "");
    setKpi("vkVms", s.vms, "");
    setKpiColored("vkHealthy", s.hosts_healthy, "has");
    setKpiColored("vkWarning", s.hosts_warning, "has");
    setKpiColored("vkCritical", s.hosts_critical, "has");
    setKpiColored("vkOffline", s.hosts_offline, "has");
    setKpi("vkAvgCpu", s.avg_cpu + "%", "");
    setKpi("vkAvgRam", s.avg_ram + "%", "");
    setKpi("vkAvgDisk", s.avg_disk + "%", "");
  }

  function setKpi(id, value) {
    const el = document.getElementById(id);
    if (el.textContent !== String(value)) el.textContent = value;
  }

  function setKpiColored(id, value, activeClass) {
    const el = document.getElementById(id);
    if (el.textContent !== String(value)) el.textContent = value;
    if (value > 0) el.classList.add(activeClass);
    else el.classList.remove(activeClass);
  }

  function statusDot(state) {
    return '<span class="vt-dot ' + esc(state) + '"></span>';
  }

  function vmNode(vm, host) {
    const derived = (!host.active || host.status === "offline") ? "host_unavailable" : vm.status;
    const open = isExpanded("vm", vm.id);
    const active = selected && selected.type === "vm" && selected.id === vm.id;
    return '<div class="vt-node vm">' +
      '<div class="vt-row ' + (active ? "active" : "") + '" data-type="vm" data-id="' + vm.id + '">' +
      (open ? '<span class="vt-caret open" data-toggle="vm:' + vm.id + '">▾</span>' : '<span class="vt-caret" data-toggle="vm:' + vm.id + '">▸</span>') +
      statusDot(derived) +
      '<span class="vt-name">' + esc(vm.name) + '</span>' +
      '<span class="vt-tag">' + esc((vm.role || "vm").toUpperCase()) + '</span>' +
      '</div>' +
      (open ? '<div class="vt-children"><div class="vt-leaf">' +
        '<span class="vt-leaf-line">' + esc(vm.ip_address || "—") + '</span>' +
        '<span class="vt-leaf-line">' + esc(vm.os || "—") + '</span>' +
        '</div></div>' : "") +
      '</div>';
  }

  function hostNode(host) {
    const open = isExpanded("host", host.id);
    const active = selected && selected.type === "host" && selected.id === host.id;
    return '<div class="vt-node host">' +
      '<div class="vt-row ' + (active ? "active" : "") + '" data-type="host" data-id="' + host.id + '">' +
      (open ? '<span class="vt-caret open" data-toggle="host:' + host.id + '">▾</span>' : '<span class="vt-caret" data-toggle="host:' + host.id + '">▸</span>') +
      statusDot(host.status) +
      '<span class="vt-name vt-name-strong">' + esc(host.name) + '</span>' +
      '<span class="vt-meta">' + host.vm_count + ' VMs</span>' +
      '</div>' +
      (open ? '<div class="vt-children">' + host.vms.map(vm => vmNode(vm, host)).join("") + '</div>' : "") +
      '</div>';
  }

  function clusterNode(cluster) {
    const open = isExpanded("cluster", cluster.id);
    const active = selected && selected.type === "cluster" && selected.id === cluster.id;
    return '<div class="vt-node cluster">' +
      '<div class="vt-row ' + (active ? "active" : "") + '" data-type="cluster" data-id="' + cluster.id + '">' +
      (open ? '<span class="vt-caret open" data-toggle="cluster:' + cluster.id + '">▾</span>' : '<span class="vt-caret" data-toggle="cluster:' + cluster.id + '">▸</span>') +
      '<span class="vt-cluster-icon"></span>' +
      '<span class="vt-name">' + esc(cluster.name) + '</span>' +
      '<span class="vt-meta">' + cluster.host_count + ' hosts</span>' +
      '</div>' +
      (open ? '<div class="vt-children">' + cluster.hosts.map(hostNode).join("") + '</div>' : "") +
      '</div>';
  }

  function datacenterNode(dc) {
    const open = isExpanded("datacenter", dc.id);
    const active = selected && selected.type === "datacenter" && selected.id === dc.id;
    return '<div class="vt-node dc">' +
      '<div class="vt-row ' + (active ? "active" : "") + '" data-type="datacenter" data-id="' + dc.id + '">' +
      (open ? '<span class="vt-caret open" data-toggle="datacenter:' + dc.id + '">▾</span>' : '<span class="vt-caret" data-toggle="datacenter:' + dc.id + '">▸</span>') +
      '<span class="vt-dc-icon"></span>' +
      '<span class="vt-name vt-name-strong">' + esc(dc.name) + '</span>' +
      '<span class="vt-meta">' + dc.vm_count + ' VMs</span>' +
      '</div>' +
      (open ? '<div class="vt-children">' + dc.clusters.map(clusterNode).join("") + '</div>' : "") +
      '</div>';
  }

  function renderTree() {
    const el = document.getElementById("virtTree");
    if (!tree) return;
    if (tree.datacenters.length === 0) {
      el.innerHTML = '<div class="empty-state"><div class="empty-state-title">No virtualization environments defined.</div>' +
        '<div class="empty-state-sub">Add datacenters and hosts from the Admin panel.</div></div>';
      return;
    }
    el.innerHTML = tree.datacenters.map(datacenterNode).join("");
    document.getElementById("virtTreeMeta").textContent =
      summary.hosts + " hosts · " + summary.vms + " VMs";
  }

  function meter(label, value) {
    const cls = value === null || value === undefined ? "" : value <= 69 ? "c-green" : value <= 84 ? "c-amber" : "c-red";
    const text = value === null || value === undefined ? "—" : value + "%";
    return '<div class="vt-meter-row">' +
      '<span class="vt-meter-label">' + esc(label) + '</span>' +
      '<div class="meter"><div class="meter-fill ' + cls + '" style="width:' + Math.min(100, value || 0) + '%"></div></div>' +
      '<span class="vt-meter-val">' + esc(text) + '</span>' +
      '</div>';
  }

  function detailRow(label, value) {
    return '<div class="dr-row">' +
      '<span class="dr-row-label">' + esc(label) + '</span>' +
      '<span class="dr-row-value">' + esc(value === null || value === undefined ? "—" : value) + '</span>' +
      '</div>';
  }

  function renderHostDetail(host) {
    const status = host.status || "unknown";
    return '<div class="vt-detail-head">' +
      '<div class="vt-detail-title">' + esc(host.name) + '</div>' +
      '<div class="vt-detail-sub mono">' + esc(host.ip_address || "") + '</div>' +
      '<span class="sev-badge ' + esc(status) + '">' + status.toUpperCase() + '</span>' +
      '</div>' +
      '<div class="vt-meters">' + meter("CPU", host.cpu_usage) + meter("RAM", host.ram_usage) + meter("Disk", host.disk_usage) + '</div>' +
      '<div class="dr-section"><div class="dr-sec-title">CAPACITY</div>' +
      detailRow("Total CPU", host.cpu_capacity || "—") +
      detailRow("Total RAM", host.ram_capacity || "—") +
      detailRow("Total Disk", host.disk_capacity || "—") +
      '</div>' +
      '<div class="dr-section"><div class="dr-sec-title">INFORMATION</div>' +
      detailRow("VMs Running", host.vm_count) +
      detailRow("Last Update", host.updated_at ? "recently" : "—") +
      (host.notes ? detailRow("Notes", host.notes) : "") +
      '</div>' +
      (host.vms.length ? '<div class="dr-section"><div class="dr-sec-title">VIRTUAL MACHINES</div>' +
        host.vms.map(vm =>
          '<div class="vt-vm-link" data-type="vm" data-id="' + vm.id + '">' +
          statusDot((!host.active || host.status === "offline") ? "host_unavailable" : vm.status) +
          '<span>' + esc(vm.name) + '</span>' +
          '<span class="vt-vm-link-meta">' + esc((vm.role || "").toUpperCase()) + '</span>' +
          '</div>').join("") +
        '</div>' : "") ;
  }

  function renderVmDetail(vm, host) {
    const derived = (!host.active || host.status === "offline") ? "host_unavailable" : vm.status;
    const status = derived === "host_unavailable" ? "host_unavailable" : (vm.status || "unknown");
    return '<div class="vt-detail-head">' +
      '<div class="vt-detail-title">' + esc(vm.name) + '</div>' +
      '<div class="vt-detail-sub mono">' + esc(vm.ip_address || "") + '</div>' +
      '<span class="sev-badge ' + esc(status) + '">' + (derived === "host_unavailable" ? "HOST UNAVAILABLE" : status.toUpperCase()) + '</span>' +
      '</div>' +
      '<div class="vt-meters">' +
      (derived === "host_unavailable" ? meter("CPU", null) + meter("RAM", null) + meter("Disk", null)
        : meter("CPU", vm.cpu_usage) + meter("RAM", vm.ram_usage) + meter("Disk", vm.disk_usage)) +
      '</div>' +
      '<div class="dr-section"><div class="dr-sec-title">INFORMATION</div>' +
      detailRow("Host", host.name) +
      detailRow("OS", vm.os || "—") +
      detailRow("Role", vm.role || "—") +
      detailRow("Uptime", vm.uptime || "—") +
      detailRow("Last Update", vm.updated_at ? "recently" : "—") +
      (vm.notes ? detailRow("Notes", vm.notes) : "") +
      '</div>';
  }

  function renderDetail() {
    const el = document.getElementById("virtDetail");
    if (!tree || !selected) {
      el.innerHTML = '<div class="placeholder">Select a node from the tree.</div>';
      return;
    }
    if (selected.type === "host") {
      const host = findHost(selected.id);
      el.innerHTML = host ? renderHostDetail(host) : '<div class="placeholder">Host not found.</div>';
      return;
    }
    if (selected.type === "vm") {
      const found = findVm(selected.id);
      el.innerHTML = found ? renderVmDetail(found.vm, found.host) : '<div class="placeholder">VM not found.</div>';
      return;
    }
    if (selected.type === "datacenter") {
      const dc = tree.datacenters.find(d => d.id === selected.id);
      el.innerHTML = dc
        ? '<div class="vt-detail-head"><div class="vt-detail-title">' + esc(dc.name) + '</div>' +
          '<div class="vt-detail-sub">' + esc(dc.description || "") + '</div></div>' +
          '<div class="dr-section"><div class="dr-sec-title">SUMMARY</div>' +
          detailRow("Clusters", dc.clusters.length) +
          detailRow("Hosts", dc.host_count) +
          detailRow("VMs", dc.vm_count) +
          '</div>'
        : '<div class="placeholder">Not found.</div>';
      return;
    }
    if (selected.type === "cluster") {
      for (const dc of tree.datacenters) {
        const cluster = dc.clusters.find(c => c.id === selected.id);
        if (cluster) {
          el.innerHTML = '<div class="vt-detail-head"><div class="vt-detail-title">' + esc(cluster.name) + '</div>' +
            '<div class="vt-detail-sub">' + esc(cluster.description || "") + '</div></div>' +
            '<div class="dr-section"><div class="dr-sec-title">SUMMARY</div>' +
            detailRow("Hosts", cluster.host_count) +
            detailRow("VMs", cluster.vm_count) +
            '</div>';
          return;
        }
      }
    }
    el.innerHTML = '<div class="placeholder">Select a node from the tree.</div>';
  }

  function findHost(hostId) {
    for (const dc of tree.datacenters) {
      for (const cluster of dc.clusters) {
        const host = cluster.hosts.find(h => h.id === hostId);
        if (host) return host;
      }
    }
    return null;
  }

  function findVm(vmId) {
    for (const dc of tree.datacenters) {
      for (const cluster of dc.clusters) {
        for (const host of cluster.hosts) {
          const vm = host.vms.find(v => v.id === vmId);
          if (vm) return { vm, host };
        }
      }
    }
    return null;
  }

  document.addEventListener("click", function (event) {
    const vmLink = event.target.closest(".vt-vm-link");
    if (vmLink) {
      selected = { type: "vm", id: parseInt(vmLink.dataset.id, 10) };
      renderTree();
      renderDetail();
      return;
    }
    if (!event.target.closest("#virtTree")) return;
    const toggle = event.target.closest(".vt-caret");
    if (toggle) {
      const parts = toggle.dataset.toggle.split(":");
      toggleExpanded(parts[0], parseInt(parts[1], 10));
      return;
    }
    const row = event.target.closest(".vt-row");
    if (row) {
      selected = { type: row.dataset.type, id: parseInt(row.dataset.id, 10) };
      renderTree();
      renderDetail();
    }
  });

  refresh();
  setInterval(refresh, REFRESH_MS);
})();
