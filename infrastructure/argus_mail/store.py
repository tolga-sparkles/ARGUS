import json
import os
import sqlite3
import threading
import time


class MailStore:
    def __init__(self, db_path):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._init()
        self._seed()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self):
        directory = os.path.dirname(self.db_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS notification_recipients (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL,
                    department TEXT,
                    role TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    verified INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS notification_groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS notification_group_members (
                    group_id INTEGER NOT NULL,
                    recipient_id INTEGER NOT NULL,
                    PRIMARY KEY (group_id, recipient_id)
                );
                CREATE TABLE IF NOT EXISTS notification_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    cooldown_seconds INTEGER NOT NULL DEFAULT 1800,
                    reminder_interval_seconds INTEGER NOT NULL DEFAULT 3600,
                    max_reminders INTEGER NOT NULL DEFAULT 3,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS notification_rule_targets (
                    rule_id INTEGER NOT NULL,
                    target_type TEXT NOT NULL,
                    target_id INTEGER NOT NULL,
                    PRIMARY KEY (rule_id, target_type, target_id)
                );
                CREATE TABLE IF NOT EXISTS notification_templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL,
                    subject_template TEXT NOT NULL,
                    html_body TEXT NOT NULL,
                    text_body TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS notification_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    incident_id INTEGER,
                    server_id TEXT,
                    dedup_key TEXT NOT NULL UNIQUE,
                    payload TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS notification_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id INTEGER NOT NULL,
                    recipient_email TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    html_body TEXT NOT NULL,
                    text_body TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at REAL NOT NULL,
                    last_error TEXT,
                    created_at REAL NOT NULL,
                    sent_at REAL
                );
                CREATE TABLE IF NOT EXISTS notification_deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id INTEGER,
                    recipient_email TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    sent_at REAL,
                    failed_at REAL,
                    error TEXT,
                    message_id TEXT,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS notification_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS daily_report_configs (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    enabled INTEGER NOT NULL DEFAULT 1,
                    hour INTEGER NOT NULL DEFAULT 15,
                    minute INTEGER NOT NULL DEFAULT 50,
                    timezone TEXT NOT NULL DEFAULT 'Europe/Istanbul',
                    recipient_group_id INTEGER,
                    include_summary INTEGER NOT NULL DEFAULT 1,
                    include_incidents INTEGER NOT NULL DEFAULT 1,
                    include_resources INTEGER NOT NULL DEFAULT 1,
                    include_availability INTEGER NOT NULL DEFAULT 1,
                    include_offline INTEGER NOT NULL DEFAULT 1,
                    include_warnings INTEGER NOT NULL DEFAULT 1,
                    include_criticals INTEGER NOT NULL DEFAULT 1,
                    include_virtualization INTEGER NOT NULL DEFAULT 1,
                    attachment TEXT NOT NULL DEFAULT 'none',
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS notification_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    actor TEXT,
                    action TEXT NOT NULL,
                    detail TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_queue_status ON notification_queue(status);
                CREATE INDEX IF NOT EXISTS idx_deliveries_created ON notification_deliveries(created_at);
                CREATE INDEX IF NOT EXISTS idx_events_created ON notification_events(created_at);
                """
            )

    def _seed(self):
        now = time.time()
        defaults = {
            "email_enabled": "1",
            "critical_enabled": "1",
            "warning_enabled": "0",
            "offline_enabled": "1",
            "recovery_enabled": "1",
            "default_cooldown": "1800",
            "default_reminder": "3600",
            "max_reminders": "3",
        }
        with self._lock, self._connect() as conn:
            for key, value in defaults.items():
                conn.execute(
                    "INSERT OR IGNORE INTO notification_settings (key, value) VALUES (?, ?)",
                    (key, value),
                )
            if conn.execute("SELECT COUNT(*) FROM notification_templates").fetchone()[0] == 0:
                for template in DEFAULT_TEMPLATES:
                    conn.execute(
                        "INSERT INTO notification_templates "
                        "(name, type, subject_template, html_body, text_body, enabled, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
                        (template["name"], template["type"], template["subject"],
                         template["html"], template["text"], now, now),
                    )
            if conn.execute("SELECT COUNT(*) FROM daily_report_configs").fetchone()[0] == 0:
                conn.execute(
                    "INSERT INTO daily_report_configs (id, enabled, hour, minute, timezone, updated_at) "
                    "VALUES (1, 1, 15, 50, 'Europe/Istanbul', ?)",
                    (now,),
                )

    # ---------- settings ----------

    def get_settings(self):
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM notification_settings").fetchall()
        return {row["key"]: row["value"] for row in rows}

    def set_settings(self, values):
        with self._lock, self._connect() as conn:
            for key, value in values.items():
                conn.execute(
                    "INSERT INTO notification_settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, str(value)),
                )

    # ---------- recipients ----------

    def list_recipients(self):
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT r.*, "
                "(SELECT COUNT(*) FROM notification_rule_targets t "
                " JOIN notification_rules ru ON ru.id = t.rule_id "
                " WHERE t.target_type = 'recipient' AND t.target_id = r.id AND ru.enabled = 1) AS rule_count "
                "FROM notification_recipients r ORDER BY r.name"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_recipient(self, recipient_id):
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM notification_recipients WHERE id = ?", (recipient_id,)).fetchone()
        return dict(row) if row else None

    def add_recipient(self, data):
        now = time.time()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO notification_recipients "
                "(name, email, department, role, status, verified, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (data["name"], data["email"], data.get("department", ""), data.get("role", ""),
                 data.get("status", "active"), 1 if data.get("verified") else 0, now),
            )
            return cur.lastrowid

    def update_recipient(self, recipient_id, data):
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE notification_recipients SET name=?, email=?, department=?, role=?, status=?, verified=? WHERE id=?",
                (data["name"], data["email"], data.get("department", ""), data.get("role", ""),
                 data.get("status", "active"), 1 if data.get("verified") else 0, recipient_id),
            )
            return cur.rowcount > 0

    def delete_recipient(self, recipient_id):
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM notification_group_members WHERE recipient_id = ?", (recipient_id,))
            conn.execute("DELETE FROM notification_rule_targets WHERE target_type = 'recipient' AND target_id = ?", (recipient_id,))
            conn.execute("DELETE FROM notification_recipients WHERE id = ?", (recipient_id,))

    def active_recipient_emails(self):
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT email FROM notification_recipients WHERE status = 'active'"
            ).fetchall()
        return [row["email"] for row in rows]

    # ---------- groups ----------

    def list_groups(self):
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT g.*, "
                "(SELECT COUNT(*) FROM notification_group_members m WHERE m.group_id = g.id) AS member_count "
                "FROM notification_groups g ORDER BY g.name"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_group(self, group_id):
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM notification_groups WHERE id = ?", (group_id,)).fetchone()
        if not row:
            return None
        group = dict(row)
        members = conn.execute(
            "SELECT r.* FROM notification_group_members m "
            "JOIN notification_recipients r ON r.id = m.recipient_id "
            "WHERE m.group_id = ? ORDER BY r.name",
            (group_id,),
        ).fetchall()
        group["members"] = [dict(m) for m in members]
        return group

    def add_group(self, data):
        now = time.time()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO notification_groups (name, description, enabled, created_at) VALUES (?, ?, ?, ?)",
                (data["name"], data.get("description", ""), 1 if data.get("enabled", True) else 0, now),
            )
            return cur.lastrowid

    def update_group(self, group_id, data):
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE notification_groups SET name=?, description=?, enabled=? WHERE id=?",
                (data["name"], data.get("description", ""), 1 if data.get("enabled", True) else 0, group_id),
            )
            if "member_ids" in data:
                conn.execute("DELETE FROM notification_group_members WHERE group_id = ?", (group_id,))
                for member_id in data["member_ids"] or []:
                    conn.execute(
                        "INSERT OR IGNORE INTO notification_group_members (group_id, recipient_id) VALUES (?, ?)",
                        (group_id, member_id),
                    )
            return True

    def delete_group(self, group_id):
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM notification_group_members WHERE group_id = ?", (group_id,))
            conn.execute("DELETE FROM notification_rule_targets WHERE target_type = 'group' AND target_id = ?", (group_id,))
            conn.execute("DELETE FROM notification_groups WHERE id = ?", (group_id,))

    def group_recipient_emails(self, group_id):
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT r.email FROM notification_group_members m "
                "JOIN notification_recipients r ON r.id = m.recipient_id "
                "WHERE m.group_id = ? AND r.status = 'active'",
                (group_id,),
            ).fetchall()
        return [row["email"] for row in rows]

    # ---------- rules ----------

    def list_rules(self):
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT r.*, "
                "(SELECT COUNT(*) FROM notification_rule_targets t WHERE t.rule_id = r.id) AS target_count "
                "FROM notification_rules r ORDER BY r.name"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_rule(self, rule_id):
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM notification_rules WHERE id = ?", (rule_id,)).fetchone()
        if not row:
            return None
        rule = dict(row)
        targets = conn.execute(
            "SELECT target_type, target_id FROM notification_rule_targets WHERE rule_id = ?",
            (rule_id,),
        ).fetchall()
        rule["targets"] = [{"type": t["target_type"], "id": t["target_id"]} for t in targets]
        return rule

    def add_rule(self, data):
        now = time.time()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO notification_rules (name, event_type, enabled, cooldown_seconds, "
                "reminder_interval_seconds, max_reminders, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (data["name"], data["event_type"], 1 if data.get("enabled", True) else 0,
                 int(data.get("cooldown_seconds", 1800)), int(data.get("reminder_interval_seconds", 3600)),
                 int(data.get("max_reminders", 3)), now, now),
            )
            rule_id = cur.lastrowid
            for target in data.get("targets") or []:
                conn.execute(
                    "INSERT OR IGNORE INTO notification_rule_targets (rule_id, target_type, target_id) VALUES (?, ?, ?)",
                    (rule_id, target["type"], target["id"]),
                )
            return rule_id

    def update_rule(self, rule_id, data):
        now = time.time()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE notification_rules SET name=?, event_type=?, enabled=?, cooldown_seconds=?, "
                "reminder_interval_seconds=?, max_reminders=?, updated_at=? WHERE id=?",
                (data["name"], data["event_type"], 1 if data.get("enabled", True) else 0,
                 int(data.get("cooldown_seconds", 1800)), int(data.get("reminder_interval_seconds", 3600)),
                 int(data.get("max_reminders", 3)), now, rule_id),
            )
            if cur.rowcount == 0:
                return False
            conn.execute("DELETE FROM notification_rule_targets WHERE rule_id = ?", (rule_id,))
            for target in data.get("targets") or []:
                conn.execute(
                    "INSERT OR IGNORE INTO notification_rule_targets (rule_id, target_type, target_id) VALUES (?, ?, ?)",
                    (rule_id, target["type"], target["id"]),
                )
            return True

    def delete_rule(self, rule_id):
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM notification_rule_targets WHERE rule_id = ?", (rule_id,))
            conn.execute("DELETE FROM notification_rules WHERE id = ?", (rule_id,))

    def enabled_rules(self):
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM notification_rules WHERE enabled = 1").fetchall()
        rules = []
        for row in rows:
            rule = dict(row)
            targets = conn.execute(
                "SELECT target_type, target_id FROM notification_rule_targets WHERE rule_id = ?",
                (rule["id"],),
            ).fetchall()
            rule["targets"] = [{"type": t["target_type"], "id": t["target_id"]} for t in targets]
            rules.append(rule)
        return rules

    # ---------- templates ----------

    def list_templates(self):
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM notification_templates ORDER BY id").fetchall()
        return [dict(row) for row in rows]

    def get_template(self, template_id=None, template_type=None):
        with self._lock, self._connect() as conn:
            if template_id is not None:
                row = conn.execute("SELECT * FROM notification_templates WHERE id = ?", (template_id,)).fetchone()
            elif template_type is not None:
                row = conn.execute("SELECT * FROM notification_templates WHERE type = ?", (template_type,)).fetchone()
            else:
                row = None
        return dict(row) if row else None

    def update_template(self, template_id, data):
        now = time.time()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE notification_templates SET subject_template=?, html_body=?, text_body=?, "
                "enabled=?, updated_at=? WHERE id=?",
                (data.get("subject_template", ""), data.get("html_body", ""), data.get("text_body", ""),
                 1 if data.get("enabled", True) else 0, now, template_id),
            )
            return cur.rowcount > 0

    # ---------- events ----------

    def add_event(self, event_type, severity, dedup_key, payload, incident_id=None, server_id=None):
        now = time.time()
        with self._lock, self._connect() as conn:
            try:
                cur = conn.execute(
                    "INSERT INTO notification_events "
                    "(event_type, severity, incident_id, server_id, dedup_key, payload, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (event_type, severity, incident_id, server_id, dedup_key,
                     json.dumps(payload, ensure_ascii=False), now),
                )
                return cur.lastrowid, None
            except sqlite3.IntegrityError:
                return None, "duplicate"

    # ---------- queue ----------

    def enqueue(self, event_id, recipient_email, subject, html_body, text_body, next_attempt_at=None):
        now = time.time()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO notification_queue "
                "(event_id, recipient_email, subject, html_body, text_body, status, attempts, "
                "next_attempt_at, created_at) VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, ?)",
                (event_id, recipient_email, subject, html_body, text_body,
                 next_attempt_at if next_attempt_at is not None else now, now),
            )
            return cur.lastrowid

    def queue_size(self):
        with self._lock, self._connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM notification_queue WHERE status IN ('pending', 'retrying', 'sending')"
            ).fetchone()[0]

    def queue_full(self, limit):
        return self.queue_size() >= limit

    def next_due(self):
        now = time.time()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM notification_queue "
                "WHERE status IN ('pending', 'retrying') AND next_attempt_at <= ? "
                "ORDER BY next_attempt_at LIMIT 1",
                (now,),
            ).fetchone()
            if row:
                conn.execute("UPDATE notification_queue SET status = 'sending' WHERE id = ?", (row["id"],))
        return dict(row) if row else None

    def mark_sent(self, queue_id, message_id=None):
        now = time.time()
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM notification_queue WHERE id = ?", (queue_id,)).fetchone()
            if not row:
                return
            conn.execute(
                "UPDATE notification_queue SET status = 'sent', sent_at = ? WHERE id = ?",
                (now, queue_id),
            )
            conn.execute(
                "INSERT INTO notification_deliveries "
                "(event_id, recipient_email, subject, status, attempts, sent_at, message_id, created_at) "
                "VALUES (?, ?, ?, 'sent', ?, ?, ?, ?)",
                (row["event_id"], row["recipient_email"], row["subject"],
                 row["attempts"] + 1, now, message_id, now),
            )

    def mark_failed(self, queue_id, error, backoff_seconds, max_attempts):
        now = time.time()
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM notification_queue WHERE id = ?", (queue_id,)).fetchone()
            if not row:
                return
            attempts = row["attempts"] + 1
            if attempts >= max_attempts:
                conn.execute(
                    "UPDATE notification_queue SET status = 'failed', attempts = ?, last_error = ? WHERE id = ?",
                    (attempts, str(error)[:500], queue_id),
                )
                conn.execute(
                    "INSERT INTO notification_deliveries "
                    "(event_id, recipient_email, subject, status, attempts, failed_at, error, created_at) "
                    "VALUES (?, ?, ?, 'failed', ?, ?, ?, ?)",
                    (row["event_id"], row["recipient_email"], row["subject"], attempts, now,
                     str(error)[:500], now),
                )
            else:
                conn.execute(
                    "UPDATE notification_queue SET status = 'retrying', attempts = ?, "
                    "next_attempt_at = ?, last_error = ? WHERE id = ?",
                    (attempts, now + backoff_seconds, str(error)[:500], queue_id),
                )

    # ---------- deliveries ----------

    def list_deliveries(self, limit=200):
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM notification_deliveries ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_delivery(self, delivery_id):
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM notification_deliveries WHERE id = ?", (delivery_id,)).fetchone()
        return dict(row) if row else None

    def delivery_stats(self):
        with self._lock, self._connect() as conn:
            now = time.time()
            day_start = now - (now % 86400)
            sent_today = conn.execute(
                "SELECT COUNT(*) FROM notification_deliveries WHERE status = 'sent' AND created_at >= ?",
                (day_start,),
            ).fetchone()[0]
            failed_today = conn.execute(
                "SELECT COUNT(*) FROM notification_deliveries WHERE status = 'failed' AND created_at >= ?",
                (day_start,),
            ).fetchone()[0]
            pending = conn.execute(
                "SELECT COUNT(*) FROM notification_queue WHERE status IN ('pending', 'retrying', 'sending')"
            ).fetchone()[0]
            last = conn.execute(
                "SELECT MAX(sent_at) FROM notification_deliveries WHERE status = 'sent'"
            ).fetchone()[0]
        return {
            "sent_today": sent_today,
            "failed_today": failed_today,
            "pending": pending,
            "last_sent_at": last,
        }

    # ---------- daily report ----------

    def get_daily_report_config(self):
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM daily_report_configs WHERE id = 1").fetchone()
        return dict(row) if row else None

    def update_daily_report_config(self, data):
        now = time.time()
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE daily_report_configs SET enabled=?, hour=?, minute=?, timezone=?, "
                "recipient_group_id=?, include_summary=?, include_incidents=?, include_resources=?, "
                "include_availability=?, include_offline=?, include_warnings=?, include_criticals=?, "
                "include_virtualization=?, attachment=?, updated_at=? WHERE id = 1",
                (
                    1 if data.get("enabled", True) else 0,
                    int(data.get("hour", 15)), int(data.get("minute", 50)),
                    data.get("timezone", "Europe/Istanbul"),
                    data.get("recipient_group_id"),
                    1 if data.get("include_summary", True) else 0,
                    1 if data.get("include_incidents", True) else 0,
                    1 if data.get("include_resources", True) else 0,
                    1 if data.get("include_availability", True) else 0,
                    1 if data.get("include_offline", True) else 0,
                    1 if data.get("include_warnings", True) else 0,
                    1 if data.get("include_criticals", True) else 0,
                    1 if data.get("include_virtualization", True) else 0,
                    data.get("attachment", "none"), now,
                ),
            )
            return True

    # ---------- audit ----------

    def audit(self, actor, action, detail=""):
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO notification_audit (ts, actor, action, detail) VALUES (?, ?, ?, ?)",
                (time.time(), actor, action, detail[:400]),
            )

    def list_audit(self, limit=100):
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM notification_audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]


DEFAULT_TEMPLATES = [
    {
        "name": "Critical Alert",
        "type": "critical",
        "subject": "[CRITICAL] {{server_name}} - {{reason}}",
        "html": """<div style="font-family:Arial,Helvetica,sans-serif;max-width:560px;margin:0 auto;background:#0f1117;color:#e1e4e8;padding:24px;border-radius:10px">
<img src="cid:argus-banner" alt="ARGUS" style="width:100%;max-width:600px;height:auto;display:block;margin:0 auto 18px">
<h2 style="color:#f85149;margin:0 0 4px">CRITICAL ALERT</h2>
<p style="color:#767f8a;margin:0 0 18px">Example Organization · ARGUS Operations Center</p>
<table style="width:100%;border-collapse:collapse;font-size:14px">
<tr><td style="color:#98a1ad;padding:6px 0">Server</td><td style="color:#f0f6fc"><b>{{server_name}}</b></td></tr>
<tr><td style="color:#98a1ad;padding:6px 0">IP</td><td style="color:#f0f6fc">{{ip}}</td></tr>
<tr><td style="color:#98a1ad;padding:6px 0">Issue</td><td style="color:#f0f6fc">{{issue}}</td></tr>
<tr><td style="color:#98a1ad;padding:6px 0">Current</td><td style="color:#f85149"><b>{{value}}</b></td></tr>
<tr><td style="color:#98a1ad;padding:6px 0">Threshold</td><td style="color:#f0f6fc">{{threshold}}</td></tr>
<tr><td style="color:#98a1ad;padding:6px 0">CPU</td><td style="color:#f0f6fc">{{cpu}}</td></tr>
<tr><td style="color:#98a1ad;padding:6px 0">Disk</td><td style="color:#f0f6fc">{{disk}}</td></tr>
<tr><td style="color:#98a1ad;padding:6px 0">Detected</td><td style="color:#f0f6fc">{{started_at}}</td></tr>
<tr><td style="color:#98a1ad;padding:6px 0">Status</td><td style="color:#f85149"><b>ACTIVE</b></td></tr>
</table>
<p style="margin-top:20px"><a href="{{dashboard_url}}" style="background:#21262d;color:#58a6ff;padding:10px 16px;border-radius:6px;text-decoration:none;font-size:13px">View in Operations Center</a></p>
</div>""",
        "text": """Example Organization · ARGUS Operations Center

CRITICAL ALERT

Server: {{server_name}}
IP: {{ip}}
Issue: {{issue}}
Current: {{value}}
Threshold: {{threshold}}
CPU: {{cpu}}
Disk: {{disk}}
Detected: {{started_at}}
Status: ACTIVE

{{dashboard_url}}
""",
    },
    {
        "name": "Warning Alert",
        "type": "warning",
        "subject": "[WARNING] {{server_name}} - {{reason}}",
        "html": """<div style="font-family:Arial,Helvetica,sans-serif;max-width:560px;margin:0 auto;background:#0f1117;color:#e1e4e8;padding:24px;border-radius:10px">
<img src="cid:argus-banner" alt="ARGUS" style="width:100%;max-width:600px;height:auto;display:block;margin:0 auto 18px">

<h2 style="color:#d29922;margin:0 0 4px">WARNING ALERT</h2>
<p style="color:#767f8a;margin:0 0 18px">Example Organization · ARGUS Operations Center</p>
<table style="width:100%;border-collapse:collapse;font-size:14px">
<tr><td style="color:#98a1ad;padding:6px 0">Server</td><td style="color:#f0f6fc"><b>{{server_name}}</b></td></tr>
<tr><td style="color:#98a1ad;padding:6px 0">IP</td><td style="color:#f0f6fc">{{ip}}</td></tr>
<tr><td style="color:#98a1ad;padding:6px 0">Issue</td><td style="color:#f0f6fc">{{issue}}</td></tr>
<tr><td style="color:#98a1ad;padding:6px 0">Current</td><td style="color:#d29922"><b>{{value}}</b></td></tr>
<tr><td style="color:#98a1ad;padding:6px 0">Threshold</td><td style="color:#f0f6fc">{{threshold}}</td></tr>
<tr><td style="color:#98a1ad;padding:6px 0">Detected</td><td style="color:#f0f6fc">{{started_at}}</td></tr>
</table>
<p style="margin-top:20px"><a href="{{dashboard_url}}" style="background:#21262d;color:#58a6ff;padding:10px 16px;border-radius:6px;text-decoration:none;font-size:13px">View in Operations Center</a></p>
</div>""",
        "text": """ARGUS Operations Center

WARNING ALERT

Server: {{server_name}}
IP: {{ip}}
Issue: {{issue}}
Current: {{value}}
Threshold: {{threshold}}
Detected: {{started_at}}

{{dashboard_url}}
""",
    },
    {
        "name": "Offline Alert",
        "type": "offline",
        "subject": "[OFFLINE] {{server_name}} - Server Unreachable",
        "html": """<div style="font-family:Arial,Helvetica,sans-serif;max-width:560px;margin:0 auto;background:#0f1117;color:#e1e4e8;padding:24px;border-radius:10px">
<img src="cid:argus-banner" alt="ARGUS" style="width:100%;max-width:600px;height:auto;display:block;margin:0 auto 18px">

<h2 style="color:#b62324;margin:0 0 4px">SERVER OFFLINE</h2>
<p style="color:#767f8a;margin:0 0 18px">Example Organization · ARGUS Operations Center</p>
<table style="width:100%;border-collapse:collapse;font-size:14px">
<tr><td style="color:#98a1ad;padding:6px 0">Server</td><td style="color:#f0f6fc"><b>{{server_name}}</b></td></tr>
<tr><td style="color:#98a1ad;padding:6px 0">IP</td><td style="color:#f0f6fc">{{ip}}</td></tr>
<tr><td style="color:#98a1ad;padding:6px 0">Status</td><td style="color:#f85149"><b>OFFLINE</b></td></tr>
<tr><td style="color:#98a1ad;padding:6px 0">Reason</td><td style="color:#f0f6fc">{{issue}}</td></tr>
<tr><td style="color:#98a1ad;padding:6px 0">Last Seen</td><td style="color:#f0f6fc">{{last_seen}}</td></tr>
<tr><td style="color:#98a1ad;padding:6px 0">Detected</td><td style="color:#f0f6fc">{{started_at}}</td></tr>
</table>
<p style="margin-top:20px"><a href="{{dashboard_url}}" style="background:#21262d;color:#58a6ff;padding:10px 16px;border-radius:6px;text-decoration:none;font-size:13px">View Server</a></p>
</div>""",
        "text": """ARGUS Operations Center

SERVER OFFLINE

Server: {{server_name}}
IP: {{ip}}
Status: OFFLINE
Reason: {{issue}}
Last Seen: {{last_seen}}
Detected: {{started_at}}

{{dashboard_url}}
""",
    },
    {
        "name": "Recovery",
        "type": "recovery",
        "subject": "[RECOVERED] {{server_name}} - Back to Normal",
        "html": """<div style="font-family:Arial,Helvetica,sans-serif;max-width:560px;margin:0 auto;background:#0f1117;color:#e1e4e8;padding:24px;border-radius:10px">
<img src="cid:argus-banner" alt="ARGUS" style="width:100%;max-width:600px;height:auto;display:block;margin:0 auto 18px">

<h2 style="color:#3fb950;margin:0 0 4px">INCIDENT RECOVERED</h2>
<p style="color:#767f8a;margin:0 0 18px">Example Organization · ARGUS Operations Center</p>
<table style="width:100%;border-collapse:collapse;font-size:14px">
<tr><td style="color:#98a1ad;padding:6px 0">Server</td><td style="color:#f0f6fc"><b>{{server_name}}</b></td></tr>
<tr><td style="color:#98a1ad;padding:6px 0">Issue</td><td style="color:#f0f6fc">{{issue}}</td></tr>
<tr><td style="color:#98a1ad;padding:6px 0">Peak</td><td style="color:#f0f6fc">{{peak_value}}</td></tr>
<tr><td style="color:#98a1ad;padding:6px 0">Current</td><td style="color:#3fb950"><b>{{value}}</b></td></tr>
<tr><td style="color:#98a1ad;padding:6px 0">Started</td><td style="color:#f0f6fc">{{started_at}}</td></tr>
<tr><td style="color:#98a1ad;padding:6px 0">Recovered</td><td style="color:#f0f6fc">{{recovered_at}}</td></tr>
<tr><td style="color:#98a1ad;padding:6px 0">Duration</td><td style="color:#f0f6fc">{{duration}}</td></tr>
</table>
<p style="margin-top:20px"><a href="{{dashboard_url}}" style="background:#21262d;color:#58a6ff;padding:10px 16px;border-radius:6px;text-decoration:none;font-size:13px">View Incident</a></p>
</div>""",
        "text": """ARGUS Operations Center

INCIDENT RECOVERED

Server: {{server_name}}
Issue: {{issue}}
Peak: {{peak_value}}
Current: {{value}}
Started: {{started_at}}
Recovered: {{recovered_at}}
Duration: {{duration}}

{{dashboard_url}}
""",
    },
    {
        "name": "Escalation",
        "type": "escalation",
        "subject": "[ESCALATED] {{server_name}} - {{reason}}",
        "html": """<div style="font-family:Arial,Helvetica,sans-serif;max-width:560px;margin:0 auto;background:#0f1117;color:#e1e4e8;padding:24px;border-radius:10px">
<img src="cid:argus-banner" alt="ARGUS" style="width:100%;max-width:600px;height:auto;display:block;margin:0 auto 18px">

<h2 style="color:#f85149;margin:0 0 4px">ESCALATED</h2>
<p style="color:#767f8a;margin:0 0 18px">Example Organization · ARGUS Operations Center</p>
<table style="width:100%;border-collapse:collapse;font-size:14px">
<tr><td style="color:#98a1ad;padding:6px 0">Server</td><td style="color:#f0f6fc"><b>{{server_name}}</b></td></tr>
<tr><td style="color:#98a1ad;padding:6px 0">Issue</td><td style="color:#f0f6fc">{{issue}}</td></tr>
<tr><td style="color:#98a1ad;padding:6px 0">Transition</td><td style="color:#d29922"><b>{{previous_severity}} → {{severity}}</b></td></tr>
<tr><td style="color:#98a1ad;padding:6px 0">Value</td><td style="color:#f0f6fc">{{previous_value}} → {{value}}</td></tr>
<tr><td style="color:#98a1ad;padding:6px 0">Detected</td><td style="color:#f0f6fc">{{started_at}}</td></tr>
</table>
<p style="margin-top:20px"><a href="{{dashboard_url}}" style="background:#21262d;color:#58a6ff;padding:10px 16px;border-radius:6px;text-decoration:none;font-size:13px">View in Operations Center</a></p>
</div>""",
        "text": """ARGUS Operations Center

ESCALATED

Server: {{server_name}}
Issue: {{issue}}
Transition: {{previous_severity}} -> {{severity}}
Value: {{previous_value}} -> {{value}}
Detected: {{started_at}}

{{dashboard_url}}
""",
    },
    {
        "name": "Daily Report",
        "type": "daily_report",
        "subject": "[DAILY REPORT] Internal Infrastructure {{report_date}}",
        "html": """<div style="font-family:Arial,Helvetica,sans-serif;max-width:640px;margin:0 auto;background:#0f1117;color:#e1e4e8;padding:24px;border-radius:10px">
<img src="cid:argus-banner" alt="ARGUS" style="width:100%;max-width:600px;height:auto;display:block;margin:0 auto 18px">
<h2 style="margin:0 0 4px">DAILY REPORT</h2>
<p style="color:#767f8a;margin:0 0 18px">Example Organization · ARGUS Operations Center · {{report_date}} {{report_time}} TRT</p>
{{report_html}}
</div>""",
        "text": """ARGUS Operations Center

DAILY REPORT — {{report_date}} {{report_time}} TRT

{{report_body}}
""",
    },
    {
        "name": "Test Email",
        "type": "test",
        "subject": "[ARGUS] Test Email",
        "html": """<div style="font-family:Arial,Helvetica,sans-serif;max-width:560px;margin:0 auto;background:#0f1117;color:#e1e4e8;padding:24px;border-radius:10px">
<img src="cid:argus-banner" alt="ARGUS" style="width:100%;max-width:600px;height:auto;display:block;margin:0 auto 18px">

<h2 style="color:#58a6ff;margin:0 0 8px">TEST EMAIL</h2>
<p style="color:#98a1ad;margin:0">ARGUS email notification system çalışıyor.</p>
<p style="color:#767f8a;margin:8px 0 0">{{started_at}}</p>
</div>""",
        "text": """ARGUS Operations Center

TEST EMAIL

ARGUS email notification system çalışıyor.
{{started_at}}
""",
    },
]
