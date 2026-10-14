(function () {
  const esc = App.esc;
  const content = document.getElementById("adminContent");
  let sub = "overview";

  const SUBS = [
    ["overview", "Overview"],
    ["recipients", "Recipients"],
    ["groups", "Groups"],
    ["rules", "Alert Rules"],
    ["daily", "Daily Reports"],
    ["templates", "Templates"],
    ["deliveries", "Delivery Log"],
    ["settings", "Email Settings"],
  ];

  async function api(path, options) {
    const resp = await fetch(path, options);
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.error || "Request failed");
    return data;
  }

  function errorState(message) {
    return '<div class="error-state"><div class="error-state-title">' + esc(message) + '</div>' +
      '<button class="retry-btn" type="button" id="ntRetry">Retry</button></div>';
  }

  function kpiCard(value, label, cls) {
    return '<div class="kpi-card"><div class="kpi-value' + (cls ? " " + cls : "") + '">' + esc(value) + '</div><div class="kpi-label">' + label + '</div></div>';
  }

  function formField(label, html) {
    return '<div class="admin-field"><label>' + esc(label) + '</label>' + html + '</div>';
  }

  function inputHtml(id, value, placeholder, type) {
    return '<input class="admin-input" id="' + id + '" value="' + esc(value === undefined ? "" : value) + '" placeholder="' + esc(placeholder || "") + '"' + (type ? ' type="' + type + '"' : "") + '>';
  }

  function selectHtml(id, options, value) {
    return '<select class="admin-input" id="' + id + '">' +
      options.map(o => '<option value="' + esc(o.value) + '"' + (String(o.value) === String(value) ? " selected" : "") + '>' + esc(o.label) + '</option>').join("") +
      '</select>';
  }

  function checkboxHtml(id, label, checked) {
    return '<label class="admin-check-line"><input type="checkbox" class="admin-check" id="' + id + '"' + (checked ? " checked" : "") + '> ' + esc(label) + '</label>';
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

  async function openForm(title, fields, submitLabel, saveFn, extraButtons) {
    const html = '<div class="dr-header"><div class="dr-eyebrow">' + esc(title) + '</div></div>' +
      fields.map(f => formField(f.label, f.html)).join("") +
      '<div class="admin-form-actions">' +
      (extraButtons || "") +
      '<button class="retry-btn" type="button" id="admSave">' + esc(submitLabel) + '</button>' +
      '<button class="retry-btn" type="button" id="admCancel">Cancel</button></div>';
    App.openDrawer(html);
    document.getElementById("admCancel").addEventListener("click", App.closeDrawer);
    document.getElementById("admSave").addEventListener("click", async function () {
      try {
        await saveFn();
        App.closeDrawer();
        render();
      } catch (e) {
        alert(e.message);
      }
    });
    return html;
  }

  function subNav() {
    return '<nav class="admin-subnav" style="margin-bottom:16px">' +
      SUBS.map(s =>
        '<a class="admin-nav-item' + (sub === s[0] ? " active" : "") + '" href="#" data-sub="' + s[0] + '">' + s[1] + '</a>'
      ).join("") +
      '</nav>';
  }

  function toolbar(searchId, addBtnId, addLabel) {
    return '<div class="toolbar"><div class="toolbar-left">' +
      '<input type="text" class="search-input" id="' + searchId + '" placeholder="Search..." autocomplete="off">' +
      '</div><div class="toolbar-meta"><button class="retry-btn" type="button" id="' + addBtnId + '">+ ' + addLabel + '</button></div></div>';
  }

  // ---------- Overview ----------

  async function renderOverview() {
    let data;
    try {
      data = await api("/api/admin/notifications/overview");
    } catch (e) {
      content.innerHTML = errorState("Unable to load notification overview.");
      return;
    }
    const s = data.stats;
    const smtp = data.smtp;
    const demoBadge = data.demo_mode
      ? '<div class="demo-badge" style="display:inline-block">DEMO MODE · External email delivery disabled</div>'
      : "";
    const smtpState = smtp.connected
      ? '<span class="status-dot ok" style="display:inline-block"></span> Connected'
      : '<span class="status-dot err" style="display:inline-block"></span> ' + (smtp.error || "Not connected");
    content.innerHTML = subNav() +
      '<section class="card"><h2>EMAIL NOTIFICATIONS</h2>' +
      '<div class="status-line" style="margin-top:8px"><span class="status-dot ' + (data.enabled ? "ok" : "") + '"></span>' +
      '<span class="status-text">' + (data.enabled ? "Enabled" : "Disabled") + '</span>' + demoBadge + '</div>' +
      '<div class="collector-list"><div class="collector-row"><span class="collector-name">SMTP</span><span class="collector-status">' + smtpState + '</span></div>' +
      '<div class="collector-row"><span class="collector-name">Queue</span><span class="collector-status">' + data.queue.pending + ' pending' + (data.queue.degraded ? ' · DEGRADED' : "") + '</span></div>' +
      '<div class="collector-row"><span class="collector-name">Last Email</span><span class="collector-status">' + esc(s.last_sent_at || "—") + '</span></div>' +
      '</div></section>' +
      '<div class="kpi-grid kpi-grid-5" style="grid-template-columns:repeat(5,minmax(0,1fr))">' +
      kpiCard(s.sent_today, "SENT TODAY", "") +
      kpiCard(s.failed_today, "FAILED", s.failed_today > 0 ? "has" : "") +
      kpiCard(s.pending, "PENDING", "") +
      kpiCard(s.recipients, "RECIPIENTS", "") +
      kpiCard(s.active_rules, "ACTIVE RULES", "") +
      '</div>' +
      '<div class="toolbar" style="margin-top:10px"><button class="retry-btn" type="button" id="ntTestBtn">Send Test Email</button>' +
      '<span class="toolbar-meta">' + (data.demo_mode ? "Demo mode: simüle edilir, dışarı mail gitmez." : "SMTP üzerinden gerçek test maili gönderir.") + '</span></div>' +
      await testFormatPanel(data.demo_mode);
    document.getElementById("ntTestBtn").addEventListener("click", () => testEmailForm());
    bindTestFormatPanel();
  }

  async function testFormatPanel(demoMode) {
    let servers = [];
    let recipients = [];
    try {
      const res = await fetch("/api/servers?per_page=300", { cache: "no-store" });
      servers = (await res.json()).items || [];
    } catch (e) {}
    try {
      const res = await api("/api/admin/notifications/recipients");
      recipients = res.items || [];
    } catch (e) {}

    const serverOptions = servers.map(s =>
      '<option value="' + esc(s.id) + '">' + esc(s.hostname) + ' (' + esc(s.ip || "—") + ') · ' + s.state.toUpperCase() + '</option>'
    ).join("");
    const recipientOptions = recipients.map(r =>
      '<option value="' + esc(r.email) + '">' + esc(r.name) + ' — ' + esc(r.email) + '</option>'
    ).join("");
    return '<section class="card" style="margin-top:14px"><h2>TEST NOTIFICATION FORMATS</h2>' +
      '<p class="vt-meta" style="margin-bottom:10px">Canlı sunucu verisiyle şablon testi — gerçek SMTP üzerinden gönderilir, Delivery Log\'a düşer.</p>' +
      formField("Template", selectHtml("nt_tpl", [
        { value: "critical", label: "Critical Alert" },
        { value: "warning", label: "Warning Alert" },
        { value: "offline", label: "Offline Alert" },
        { value: "recovery", label: "Recovery" },
        { value: "escalation", label: "Escalation" },
        { value: "daily_report", label: "Daily Report (genel özet)" },
        { value: "test", label: "Test Email" },
      ], "critical")) +
      formField("Server (canlı veri)", '<select class="admin-input" id="nt_srv">' + serverOptions + '</select><span class="vt-meta" id="nt_srv_hint"></span>') +
      formField("Recipient", selectHtml("nt_rcp",
        [{ value: "", label: "— elle yaz —" }].concat(recipients.map(r => ({ value: r.email, label: r.name + " — " + r.email }))), "") +
        ' ' + inputHtml("nt_email", "", "kime@adres")) +
      '<div class="admin-form-actions" style="margin-top:12px"><button class="retry-btn" type="button" id="ntFmtSend">Send Test Format</button>' +
      '<span class="vt-meta" id="nt_fmt_result" style="margin-left:10px"></span></div></section>';
  }

  function bindTestFormatPanel() {
    const tplEl = document.getElementById("nt_tpl");
    const srvEl = document.getElementById("nt_srv");
    const rcpEl = document.getElementById("nt_rcp");
    const emailEl = document.getElementById("nt_email");
    const btn = document.getElementById("ntFmtSend");
    if (!tplEl || !btn) return;

    function suggestServer() {
      const tpl = tplEl.value;
      const want = {
        critical: "critical", warning: "warning", offline: "offline",
        recovery: "healthy", escalation: "critical",
      }[tpl];
      if (!want || !srvEl) return;
      let matched = null;
      [...srvEl.options].forEach(opt => {
        const state = opt.textContent.split("· ")[1] || "";
        if (!matched && state.trim().toUpperCase().startsWith(want.toUpperCase())) matched = opt.value;
      });
      if (matched) srvEl.value = matched;
      const hint = document.getElementById("nt_srv_hint");
      if (hint) hint.textContent = matched ? " — duruma uygun sunucu seçildi" : "";
    }
    tplEl.addEventListener("change", function () {
      suggestServer();
      const needsServer = ["critical", "warning", "offline", "recovery", "escalation"].includes(tplEl.value);
      if (srvEl) srvEl.disabled = !needsServer;
    });
    rcpEl.addEventListener("change", function () {
      if (rcpEl.value) emailEl.value = rcpEl.value;
    });
    suggestServer();
    btn.addEventListener("click", async function () {
      const email = (rcpEl.value || emailEl.value || "").trim();
      if (!email) {
        document.getElementById("nt_fmt_result").textContent = "Alıcı email gerekli.";
        return;
      }
      btn.disabled = true;
      document.getElementById("nt_fmt_result").textContent = "Gönderiliyor…";
      try {
        const res = await api("/api/admin/notifications/test-format", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            template_type: tplEl.value,
            email: email,
            server_id: srvEl.value || "",
          }),
        });
        document.getElementById("nt_fmt_result").textContent = res.message || "OK";
      } catch (e) {
        document.getElementById("nt_fmt_result").textContent = "Hata: " + e.message;
      } finally {
        btn.disabled = false;
      }
    });
  }

  function testEmailForm() {
    const fields = [
      { label: "Recipient Email", html: inputHtml("tf_email", "", "admin@example.com") },
    ];
    openForm("Send Test Email", fields, "Send Test", async function () {
      const v = formValues(["tf_email"]);
      const res = await api("/api/admin/notifications/test-email", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: v.tf_email }),
      });
      alert(res.message || "Test email sent.");
    });
  }

  // ---------- Recipients ----------

  async function renderRecipients() {
    let res;
    try {
      res = await api("/api/admin/notifications/recipients");
    } catch (e) {
      content.innerHTML = errorState("Unable to load recipients.");
      return;
    }
    const items = res.items;
    content.innerHTML = subNav() + toolbar("nrSearch", "nrAdd", "Add Recipient") +
      '<div class="table-wrap"><table class="data-table"><thead><tr>' +
      '<th>NAME</th><th>EMAIL</th><th>DEPARTMENT</th><th>ROLE</th><th>STATUS</th><th>RULES</th><th>ACTIONS</th>' +
      '</tr></thead><tbody id="nrBody"></tbody></table></div>';
    renderRecipientRows(items);
    document.getElementById("nrSearch").addEventListener("input", function (e) {
      const q = e.target.value.toLowerCase();
      renderRecipientRows(items.filter(r => (r.name || "").toLowerCase().includes(q) || (r.email || "").toLowerCase().includes(q)));
    });
    document.getElementById("nrAdd").addEventListener("click", () => recipientForm(null));
  }

  function renderRecipientRows(items) {
    const body = document.getElementById("nrBody");
    body.innerHTML = items.map(r =>
      '<tr>' +
      '<td><span class="t-name">' + esc(r.name) + '</span></td>' +
      '<td><span class="t-ip">' + esc(r.email) + '</span></td>' +
      '<td>' + esc(r.department || "—") + '</td>' +
      '<td>' + esc(r.role || "—") + '</td>' +
      '<td>' + (r.status === "active" ? '<span class="sev-badge healthy">ACTIVE</span>' : '<span class="sev-badge unknown">' + r.status.toUpperCase() + '</span>') +
      (r.verified ? ' <span class="sev-badge healthy">VERIFIED</span>' : ' <span class="sev-badge warning">PENDING</span>') + '</td>' +
      '<td><span class="t-val">' + (r.rule_count || 0) + '</span></td>' +
      '<td><button class="check-now-btn" data-act="edit" data-id="' + r.id + '">EDIT</button> ' +
      '<button class="check-now-btn err" data-act="del" data-id="' + r.id + '">DEL</button></td>' +
      '</tr>'
    ).join("") || '<tr><td colspan="7"><div class="empty-state"><div class="empty-state-title">No recipients yet.</div></div></td></tr>';
    body.querySelectorAll("button").forEach(btn => {
      btn.addEventListener("click", async function () {
        const r = items.find(x => x.id === parseInt(btn.dataset.id, 10));
        if (!r) return;
        if (btn.dataset.act === "edit") recipientForm(r);
        else if (confirm("Delete recipient " + r.email + "?")) {
          await api("/api/admin/notifications/recipients/" + r.id, { method: "DELETE" });
          render();
        }
      });
    });
  }

  function recipientForm(recipient) {
    const ids = ["rf_name", "rf_email", "rf_department", "rf_role", "rf_status", "rf_verified"];
    const fields = [
      { label: "Name", html: inputHtml("rf_name", recipient ? recipient.name : "", "Example User") },
      { label: "Email", html: inputHtml("rf_email", recipient ? recipient.email : "", "user@example.com") },
      { label: "Department", html: inputHtml("rf_department", recipient ? recipient.department : "") },
      { label: "Role", html: inputHtml("rf_role", recipient ? recipient.role : "", "Infrastructure Manager") },
      { label: "Status", html: selectHtml("rf_status", ["active", "disabled", "pending"].map(v => ({ value: v, label: v })), recipient ? recipient.status : "active") },
      { label: "Verified", html: '<input type="checkbox" class="admin-check" id="rf_verified"' + (recipient && recipient.verified ? " checked" : "") + '>' },
    ];
    openForm(recipient ? "Edit Recipient" : "Add Recipient", fields, "Save", async function () {
      const v = formValues(ids);
      const payload = {
        name: v.rf_name, email: v.rf_email, department: v.rf_department, role: v.rf_role,
        status: v.rf_status, verified: v.rf_verified,
      };
      await api(recipient ? "/api/admin/notifications/recipients/" + recipient.id : "/api/admin/notifications/recipients", {
        method: recipient ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    });
  }

  // ---------- Groups ----------

  async function renderGroups() {
    let res;
    try {
      res = await api("/api/admin/notifications/groups");
    } catch (e) {
      content.innerHTML = errorState("Unable to load groups.");
      return;
    }
    const items = res.items;
    content.innerHTML = subNav() + toolbar("ngSearch", "ngAdd", "Add Group") +
      '<div class="table-wrap"><table class="data-table"><thead><tr>' +
      '<th>NAME</th><th>DESCRIPTION</th><th>MEMBERS</th><th>ENABLED</th><th>ACTIONS</th>' +
      '</tr></thead><tbody id="ngBody"></tbody></table></div>';
    renderGroupRows(items);
    document.getElementById("ngSearch").addEventListener("input", function (e) {
      const q = e.target.value.toLowerCase();
      renderGroupRows(items.filter(g => (g.name || "").toLowerCase().includes(q)));
    });
    document.getElementById("ngAdd").addEventListener("click", () => groupForm(null, null));
  }

  function renderGroupRows(items) {
    const body = document.getElementById("ngBody");
    body.innerHTML = items.map(g =>
      '<tr>' +
      '<td><span class="t-name">' + esc(g.name) + '</span></td>' +
      '<td>' + esc(g.description || "—") + '</td>' +
      '<td><span class="t-val">' + (g.member_count || 0) + '</span></td>' +
      '<td>' + (g.enabled ? '<span class="sev-badge healthy">ENABLED</span>' : '<span class="sev-badge unknown">DISABLED</span>') + '</td>' +
      '<td><button class="check-now-btn" data-act="edit" data-id="' + g.id + '">EDIT</button> ' +
      '<button class="check-now-btn err" data-act="del" data-id="' + g.id + '">DEL</button></td>' +
      '</tr>'
    ).join("") || '<tr><td colspan="5"><div class="empty-state"><div class="empty-state-title">No groups yet.</div></div></td></tr>';
    body.querySelectorAll("button").forEach(btn => {
      btn.addEventListener("click", async function () {
        const g = items.find(x => x.id === parseInt(btn.dataset.id, 10));
        if (!g) return;
        if (btn.dataset.act === "edit") {
          const detail = await api("/api/admin/notifications/groups/" + g.id);
          groupForm(detail, null);
        } else if (confirm("Delete group " + g.name + "?")) {
          await api("/api/admin/notifications/groups/" + g.id, { method: "DELETE" });
          render();
        }
      });
    });
  }

  async function groupForm(group, members) {
    const recipients = await api("/api/admin/notifications/recipients").catch(() => ({ items: [] }));
    const selected = new Set((group && group.members ? group.members : []).map(m => m.id));
    const checkboxes = recipients.items.map(r =>
      '<div><label class="admin-check-line"><input type="checkbox" class="admin-check ng-member" value="' + r.id + '"' + (selected.has(r.id) ? " checked" : "") + '> ' + esc(r.name) + ' (' + esc(r.email) + ')</label></div>'
    ).join("");
    const fields = [
      { label: "Group Name", html: inputHtml("gf_name", group ? group.name : "", "Infrastructure Team") },
      { label: "Description", html: inputHtml("gf_desc", group ? group.description : "") },
      { label: "Enabled", html: '<input type="checkbox" class="admin-check" id="gf_enabled"' + (group ? (group.enabled ? " checked" : "") : " checked") + '>' },
      { label: "Members", html: '<div style="max-height:220px;overflow-y:auto;border:1px solid var(--border);border-radius:6px;padding:8px">' + (checkboxes || "No recipients") + '</div>' },
    ];
    openForm(group ? "Edit Group" : "Add Group", fields, "Save", async function () {
      const v = formValues(["gf_name", "gf_desc", "gf_enabled"]);
      const memberIds = [...document.querySelectorAll(".ng-member:checked")].map(el => parseInt(el.value, 10));
      const payload = { name: v.gf_name, description: v.gf_desc, enabled: v.gf_enabled, member_ids: memberIds };
      await api(group ? "/api/admin/notifications/groups/" + group.id : "/api/admin/notifications/groups", {
        method: group ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    });
  }

  // ---------- Rules ----------

  async function renderRules() {
    let res;
    try {
      res = await api("/api/admin/notifications/rules");
    } catch (e) {
      content.innerHTML = errorState("Unable to load rules.");
      return;
    }
    const items = res.items;
    const events = res.events || [];
    content.innerHTML = subNav() + toolbar("nrlSearch", "nrlAdd", "Add Alert Rule") +
      '<div class="table-wrap"><table class="data-table"><thead><tr>' +
      '<th>RULE</th><th>EVENT</th><th>COOLDOWN</th><th>REMINDER</th><th>ENABLED</th><th>ACTIONS</th>' +
      '</tr></thead><tbody id="nrlBody"></tbody></table></div>';
    renderRuleRows(items, events);
    document.getElementById("nrlSearch").addEventListener("input", function (e) {
      const q = e.target.value.toLowerCase();
      renderRuleRows(items.filter(r => (r.name || "").toLowerCase().includes(q) || (r.event_type || "").toLowerCase().includes(q)), events);
    });
    document.getElementById("nrlAdd").addEventListener("click", () => ruleForm(null, events));
  }

  function renderRuleRows(items, events) {
    const body = document.getElementById("nrlBody");
    body.innerHTML = items.map(r =>
      '<tr>' +
      '<td><span class="t-name">' + esc(r.name) + '</span></td>' +
      '<td><span class="t-ip">' + esc(r.event_type) + '</span></td>' +
      '<td>' + Math.round((r.cooldown_seconds || 0) / 60) + 'm</td>' +
      '<td>' + (r.reminder_interval_seconds ? Math.round(r.reminder_interval_seconds / 60) + 'm (max ' + r.max_reminders + ')' : "—") + '</td>' +
      '<td>' + (r.enabled ? '<span class="sev-badge healthy">ON</span>' : '<span class="sev-badge unknown">OFF</span>') + '</td>' +
      '<td><button class="check-now-btn" data-act="edit" data-id="' + r.id + '">EDIT</button> ' +
      '<button class="check-now-btn err" data-act="del" data-id="' + r.id + '">DEL</button></td>' +
      '</tr>'
    ).join("") || '<tr><td colspan="6"><div class="empty-state"><div class="empty-state-title">No rules yet.</div><div class="empty-state-sub">Rule olmadan mail gönderilmez — örn. MEMORY_CRITICAL → Infrastructure Team.</div></div></td></tr>';
    body.querySelectorAll("button").forEach(btn => {
      btn.addEventListener("click", async function () {
        const r = items.find(x => x.id === parseInt(btn.dataset.id, 10));
        if (!r) return;
        if (btn.dataset.act === "edit") {
          const detail = await api("/api/admin/notifications/rules/" + r.id).catch(() => r);
          ruleForm(detail, events);
        } else if (confirm("Delete rule " + r.name + "?")) {
          await api("/api/admin/notifications/rules/" + r.id, { method: "DELETE" });
          render();
        }
      });
    });
  }

  async function ruleForm(rule, events) {
    const [recipients, groups] = await Promise.all([
      api("/api/admin/notifications/recipients").catch(() => ({ items: [] })),
      api("/api/admin/notifications/groups").catch(() => ({ items: [] })),
    ]);
    const targetKeys = new Set((rule && rule.targets ? rule.targets : []).map(t => t.type + ":" + t.id));
    const targetOptions = [
      ...recipients.items.map(r => ({ type: "recipient", id: r.id, label: r.name + " (" + r.email + ")" })),
      ...groups.items.map(g => ({ type: "group", id: g.id, label: "Grup: " + g.name })),
    ].map(o =>
      '<div><label class="admin-check-line"><input type="checkbox" class="admin-check nr-target" value="' + o.type + ':' + o.id + '"' + (targetKeys.has(o.type + ":" + o.id) ? " checked" : "") + '> ' + esc(o.label) + '</label></div>'
    ).join("");
    const eventLabel = (rule && rule.event_type ? rule.event_type : "MEMORY_CRITICAL").split("_").map(w => w[0] + w.slice(1).toLowerCase()).join(" ");
    const fields = [
      { label: "Rule Name", html: inputHtml("nrf_name", rule ? rule.name : "", "Critical Memory Alert") },
      { label: "Event Type", html: selectHtml("nrf_event", events.map(e => ({ value: e.value, label: e.label })), rule ? rule.event_type : "MEMORY_CRITICAL") },
      { label: "Recipients / Groups", html: '<div style="max-height:200px;overflow-y:auto;border:1px solid var(--border);border-radius:6px;padding:8px">' + (targetOptions || "Önce recipient/grup ekle") + '</div>' },
      { label: "Cooldown (min)", html: inputHtml("nrf_cooldown", rule ? Math.round((rule.cooldown_seconds || 1800) / 60) : 30, "", "number") },
      { label: "Reminder Interval (min, 0 = kapalı)", html: inputHtml("nrf_reminder", rule ? Math.round((rule.reminder_interval_seconds || 0) / 60) : 0, "", "number") },
      { label: "Max Reminders", html: inputHtml("nrf_max", rule ? rule.max_reminders : 3, "", "number") },
      { label: "Enabled", html: '<input type="checkbox" class="admin-check" id="nrf_enabled"' + (rule ? (rule.enabled ? " checked" : "") : " checked") + '>' },
      { label: "Preview", html: '<div class="collector-list"><div class="collector-row"><span class="collector-name">WHEN</span><span class="collector-status" id="nrfPrevWhen">' + esc(eventLabel) + ' olur</span></div>' +
        '<div class="collector-row"><span class="collector-name">THEN</span><span class="collector-status">Send Email</span></div></div>' },
    ];
    openForm(rule ? "Edit Alert Rule" : "Add Alert Rule", fields, "Save", async function () {
      const v = formValues(["nrf_name", "nrf_event", "nrf_cooldown", "nrf_reminder", "nrf_max", "nrf_enabled"]);
      const targets = [...document.querySelectorAll(".nr-target:checked")].map(el => {
        const parts = el.value.split(":");
        return { type: parts[0], id: parseInt(parts[1], 10) };
      });
      const payload = {
        name: v.nrf_name, event_type: v.nrf_event, enabled: v.nrf_enabled,
        cooldown_seconds: parseInt(v.nrf_cooldown || 30, 10) * 60,
        reminder_interval_seconds: parseInt(v.nrf_reminder || 0, 10) * 60,
        max_reminders: parseInt(v.nrf_max || 3, 10),
        targets,
      };
      await api(rule ? "/api/admin/notifications/rules/" + rule.id : "/api/admin/notifications/rules", {
        method: rule ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    });
    document.getElementById("nrf_event").addEventListener("change", function (e) {
      const label = e.target.value.split("_").map(w => w[0] + w.slice(1).toLowerCase()).join(" ");
      const el = document.getElementById("nrfPrevWhen");
      if (el) el.textContent = label + " olur";
    });
  }

  // ---------- Daily Reports ----------

  async function renderDaily() {
    let config, groups;
    try {
      [config, groups] = await Promise.all([
        api("/api/admin/notifications/daily-report"),
        api("/api/admin/notifications/groups"),
      ]);
    } catch (e) {
      content.innerHTML = errorState("Unable to load daily report config.");
      return;
    }
    const c = config || {};
    const hourOptions = [];
    for (let h = 0; h < 24; h++) hourOptions.push({ value: h, label: String(h).padStart(2, "0") + ":00" });
    const minuteOptions = [0, 15, 30, 45, 50].map(m => ({ value: m, label: ":" + String(m).padStart(2, "0") }));
    content.innerHTML = subNav() +
      '<section class="card"><h2>DAILY REPORT</h2>' +
      formField("Enabled", '<input type="checkbox" class="admin-check" id="dr_enabled"' + (c.enabled ? " checked" : "") + '>') +
      formField("Schedule (TR)", selectHtml("dr_hour", hourOptions, c.hour || 15) + ' <span style="color:var(--dim)">:</span> ' + selectHtml("dr_minute", minuteOptions, c.minute || 50)) +
      formField("Recipient Group", selectHtml("dr_group", [{ value: "", label: "—" }].concat(groups.items.map(g => ({ value: g.id, label: g.name }))), c.recipient_group_id || "")) +
      formField("Include", '<div style="display:grid;grid-template-columns:1fr 1fr;gap:4px">' +
        checkboxHtml("dr_summary", "Summary", c.include_summary !== 0) +
        checkboxHtml("dr_incidents", "Incidents", c.include_incidents !== 0) +
        checkboxHtml("dr_resources", "Resource Usage", c.include_resources !== 0) +
        checkboxHtml("dr_availability", "Availability", c.include_availability !== 0) +
        checkboxHtml("dr_offline", "Offline Servers", c.include_offline !== 0) +
        checkboxHtml("dr_warnings", "Warning Servers", c.include_warnings !== 0) +
        checkboxHtml("dr_criticals", "Critical Servers", c.include_criticals !== 0) +
        checkboxHtml("dr_virt", "Virtualization", c.include_virtualization !== 0) +
        '</div>') +
      formField("Attachment", selectHtml("dr_attachment", [{ value: "none", label: "None" }, { value: "pdf", label: "PDF" }, { value: "xlsx", label: "XLSX" }], c.attachment || "none")) +
      '<div class="admin-form-actions" style="margin-top:12px">' +
      '<button class="retry-btn" type="button" id="drSave">Save</button> ' +
      '<button class="retry-btn" type="button" id="drSendNow">Send Now</button></div></section>';
    document.getElementById("drSave").addEventListener("click", async function () {
      const v = formValues(["dr_enabled", "dr_hour", "dr_minute", "dr_group", "dr_summary", "dr_incidents", "dr_resources", "dr_availability", "dr_offline", "dr_warnings", "dr_criticals", "dr_virt", "dr_attachment"]);
      await api("/api/admin/notifications/daily-report", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          enabled: v.dr_enabled, hour: parseInt(v.dr_hour, 10), minute: parseInt(v.dr_minute, 10),
          recipient_group_id: v.dr_group ? parseInt(v.dr_group, 10) : null,
          include_summary: v.dr_summary, include_incidents: v.dr_incidents, include_resources: v.dr_resources,
          include_availability: v.dr_availability, include_offline: v.dr_offline, include_warnings: v.dr_warnings,
          include_criticals: v.dr_criticals, include_virtualization: v.dr_virt, attachment: v.dr_attachment,
        }),
      });
      alert("Daily report config saved.");
      render();
    });
    document.getElementById("drSendNow").addEventListener("click", async function () {
      const res = await api("/api/admin/notifications/daily-report/send-now", { method: "POST" });
      alert(res.message);
    });
  }

  // ---------- Templates ----------

  async function renderTemplates() {
    let res;
    try {
      res = await api("/api/admin/notifications/templates");
    } catch (e) {
      content.innerHTML = errorState("Unable to load templates.");
      return;
    }
    content.innerHTML = subNav() +
      '<section class="card"><h2>EMAIL TEMPLATES</h2><div class="page-list">' +
      res.items.map(t =>
        '<div class="admin-group-row"><div class="ai-main"><div class="ai-name">' + esc(t.name) + '</div>' +
        '<div class="ai-msg">' + esc(t.type) + ' · ' + esc(t.subject_template) + '</div></div>' +
        '<div class="ai-meta"><span>' + (t.enabled ? '<span class="sev-badge healthy">ENABLED</span>' : '<span class="sev-badge unknown">DISABLED</span>') + '</span>' +
        '<button class="check-now-btn" data-id="' + t.id + '">EDIT</button></div></div>'
      ).join("") + '</div></section>';
    content.querySelectorAll("button[data-id]").forEach(btn => {
      btn.addEventListener("click", async function () {
        const t = await api("/api/admin/notifications/templates/" + btn.dataset.id);
        templateForm(t);
      });
    });
  }

  function templateForm(template) {
    const fields = [
      { label: "Subject Template", html: inputHtml("tpl_subject", template.subject_template, "", "text") },
      { label: "HTML Body", html: '<textarea class="admin-input" id="tpl_html" rows="8">' + esc(template.html_body || "") + '</textarea>' },
      { label: "Plain Text Body", html: '<textarea class="admin-input" id="tpl_text" rows="6">' + esc(template.text_body || "") + '</textarea>' },
      { label: "Placeholders", html: '<span class="vt-meta">' + ["server_name", "ip", "reason", "issue", "value", "threshold", "peak_value", "cpu", "disk", "started_at", "recovered_at", "duration", "last_seen", "dashboard_url", "report_date", "report_body"].join(", ") + '</span>' },
    ];
    const previewBtn = '<button class="retry-btn" type="button" id="tplPreview">Preview</button> ';
    openForm("Edit Template: " + template.name, fields, "Save", async function () {
      const v = formValues(["tpl_subject"]);
      await api("/api/admin/notifications/templates/" + template.id, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          subject_template: v.tpl_subject,
          html_body: document.getElementById("tpl_html").value,
          text_body: document.getElementById("tpl_text").value,
          enabled: true,
        }),
      });
    }, previewBtn);
    document.getElementById("tplPreview").addEventListener("click", async function () {
      const res = await api("/api/admin/notifications/templates/" + template.id + "/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      App.openDrawer('<div class="dr-header"><div class="dr-eyebrow">PREVIEW</div><div class="dr-name">' + esc(res.subject) + '</div></div>' +
        '<div class="dr-section"><div class="dr-sec-title">PLAIN TEXT</div><div class="preview-block"><pre style="white-space:pre-wrap;font-family:inherit;font-size:12.5px;color:var(--text)">' + esc(res.text_body) + '</pre></div></div>' +
        '<div class="dr-section"><div class="dr-sec-title">HTML</div><div class="preview-block">' + res.html_body + '</div></div>' +
        '<div class="admin-form-actions" style="margin-top:14px"><button class="retry-btn" type="button" onclick="App.closeDrawer()">Close</button></div>');
    });
  }

  // ---------- Delivery Log ----------

  async function renderDeliveries() {
    let res;
    try {
      res = await api("/api/admin/notifications/deliveries");
    } catch (e) {
      content.innerHTML = errorState("Unable to load delivery log.");
      return;
    }
    const items = res.items;
    content.innerHTML = subNav() +
      '<div class="table-wrap"><table class="data-table"><thead><tr>' +
      '<th>TIME</th><th>RECIPIENT</th><th>SUBJECT</th><th>STATUS</th><th>ATTEMPTS</th><th>ACTIONS</th>' +
      '</tr></thead><tbody id="ndBody"></tbody></table></div>';
    const body = document.getElementById("ndBody");
    body.innerHTML = items.map(d =>
      '<tr>' +
      '<td><span class="t-val">' + esc(d.created_text || "—") + '</span></td>' +
      '<td><span class="t-ip">' + esc(d.recipient_email) + '</span></td>' +
      '<td style="max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + esc(d.subject || "—") + '</td>' +
      '<td>' + (d.status === "sent" ? '<span class="sev-badge healthy">SENT</span>' :
        d.status === "failed" ? '<span class="sev-badge critical">FAILED</span>' :
          '<span class="sev-badge warning">' + d.status.toUpperCase() + '</span>') + '</td>' +
      '<td><span class="t-val">' + d.attempts + '</span></td>' +
      '<td><button class="check-now-btn" data-id="' + d.id + '">DETAIL</button></td>' +
      '</tr>'
    ).join("") || '<tr><td colspan="6"><div class="empty-state"><div class="empty-state-title">No deliveries yet.</div></div></td></tr>';
    body.querySelectorAll("button").forEach(btn => {
      btn.addEventListener("click", async function () {
        const d = await api("/api/admin/notifications/deliveries/" + btn.dataset.id);
        App.openDrawer('<div class="dr-header"><div class="dr-eyebrow">DELIVERY DETAIL</div><div class="dr-name">' + esc(d.subject || "—") + '</div></div>' +
          '<div class="dr-section"><div class="dr-sec-title">DETAILS</div>' +
          detailRow("Recipient", d.recipient_email) +
          detailRow("Event ID", d.event_id || "—") +
          detailRow("Status", d.status) +
          detailRow("Attempts", d.attempts) +
          detailRow("Created", d.created_text || "—") +
          detailRow("Sent", d.sent_text || "—") +
          detailRow("Message ID", d.message_id || "—") +
          detailRow("Error", d.error || "—") +
          '</div>' +
          '<div class="admin-form-actions" style="margin-top:14px"><button class="retry-btn" type="button" onclick="App.closeDrawer()">Close</button></div>');
      });
    });
  }

  function detailRow(label, value) {
    return '<div class="dr-row"><span class="dr-row-label">' + esc(label) + '</span>' +
      '<span class="dr-row-value" style="max-width:60%">' + esc(value === null || value === undefined ? "—" : value) + '</span></div>';
  }

  // ---------- Settings ----------

  async function renderSettings() {
    let res;
    try {
      res = await api("/api/admin/notifications/settings");
    } catch (e) {
      content.innerHTML = errorState("Unable to load settings.");
      return;
    }
    const v = res.values || {};
    const smtp = res.smtp || {};
    content.innerHTML = subNav() +
      '<section class="card"><h2>SMTP CONFIGURATION</h2><div class="collector-list">' +
      '<div class="collector-row"><span class="collector-name">Host</span><span class="collector-status">' + esc(smtp.host || "—") + '</span></div>' +
      '<div class="collector-row"><span class="collector-name">Port</span><span class="collector-status">' + esc(smtp.port || "—") + '</span></div>' +
      '<div class="collector-row"><span class="collector-name">From Address</span><span class="collector-status">' + esc(smtp.from || "—") + '</span></div>' +
      '<div class="collector-row"><span class="collector-name">TLS</span><span class="collector-status">' + (smtp.tls ? "ON" : "OFF") + '</span></div>' +
      '<div class="collector-row"><span class="collector-name">Password</span><span class="collector-status">' + (smtp.password_configured ? "Configured" : "Not configured") + '</span></div>' +
      '<div class="collector-row"><span class="collector-name">Demo Mode</span><span class="collector-status">' + (res.demo_mode ? "ON — external delivery disabled" : "OFF") + '</span></div>' +
      '</div>' +
      '<div class="toolbar" style="margin-top:10px"><button class="retry-btn" type="button" id="ntSmtpTest">Test SMTP Connection</button></div>' +
      '<p class="vt-meta" style="margin-top:8px">SMTP bilgileri .env dosyasından okunur (SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM, SMTP_TLS).</p></section>' +
      '<section class="card" style="margin-top:14px"><h2>NOTIFICATION SETTINGS</h2>' +
      checkboxHtml("ns_email", "Email Notifications", v.email_enabled !== "0") + '<br>' +
      checkboxHtml("ns_critical", "Critical Alerts", v.critical_enabled !== "0") + '<br>' +
      checkboxHtml("ns_warning", "Warning Alerts", v.warning_enabled === "1") + '<br>' +
      checkboxHtml("ns_offline", "Offline Alerts", v.offline_enabled !== "0") + '<br>' +
      checkboxHtml("ns_recovery", "Recovery Alerts", v.recovery_enabled !== "0") + '<br>' +
      '<div style="margin-top:12px">' +
      formField("Default Cooldown (min)", inputHtml("ns_cooldown", Math.round(parseInt(v.default_cooldown || 1800, 10) / 60), "", "number")) +
      formField("Default Reminder (min)", inputHtml("ns_reminder", Math.round(parseInt(v.default_reminder || 3600, 10) / 60), "", "number")) +
      formField("Max Reminders", inputHtml("ns_max", v.max_reminders || 3, "", "number")) +
      '</div>' +
      '<div class="admin-form-actions" style="margin-top:12px"><button class="retry-btn" type="button" id="ntSave">Save</button></div></section>';
    document.getElementById("ntSmtpTest").addEventListener("click", async function () {
      const r = await api("/api/admin/notifications/smtp-test", { method: "POST" });
      alert(r.ok ? "SMTP connection successful." : "SMTP failed: " + (r.error || "unknown"));
    });
    document.getElementById("ntSave").addEventListener("click", async function () {
      const f = formValues(["ns_email", "ns_critical", "ns_warning", "ns_offline", "ns_recovery", "ns_cooldown", "ns_reminder", "ns_max"]);
      await api("/api/admin/notifications/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email_enabled: f.ns_email, critical_enabled: f.ns_critical, warning_enabled: f.ns_warning,
          offline_enabled: f.ns_offline, recovery_enabled: f.ns_recovery,
          default_cooldown: parseInt(f.ns_cooldown || 30, 10) * 60,
          default_reminder: parseInt(f.ns_reminder || 60, 10) * 60,
          max_reminders: parseInt(f.ns_max || 3, 10),
        }),
      });
      alert("Settings saved.");
      render();
    });
  }

  // ---------- router ----------

  function render() {
    if (sub === "overview") renderOverview();
    else if (sub === "recipients") renderRecipients();
    else if (sub === "groups") renderGroups();
    else if (sub === "rules") renderRules();
    else if (sub === "daily") renderDaily();
    else if (sub === "templates") renderTemplates();
    else if (sub === "deliveries") renderDeliveries();
    else renderSettings();
  }

  content.addEventListener("click", function (event) {
    if (event.target.id === "ntRetry") {
      render();
      return;
    }
    const link = event.target.closest("a[data-sub]");
    if (link) {
      event.preventDefault();
      sub = link.dataset.sub;
      render();
    }
  });

  render();
})();
