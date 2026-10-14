import time

from flask import Blueprint, current_app, jsonify, request, session

from infrastructure import auth
from infrastructure.argus_mail import get_runtime
from infrastructure.argus_mail.events import EVENT_LABELS, EVENT_TYPES, trt_text
from infrastructure.argus_mail.mailer import render

bp = Blueprint("mail_api", __name__, url_prefix="/api/admin/notifications")

EVENT_OPTIONS = [{"value": name, "label": EVENT_LABELS.get(name, name)} for name in EVENT_TYPES]

SAMPLE_PAYLOAD = {
    "server_name": "APP-SRV-01",
    "ip": "192.0.2.6",
    "reason": "Memory usage exceeded critical threshold",
    "issue": "Memory usage exceeded critical threshold",
    "value": "94%",
    "threshold": "90%",
    "cpu": "71%",
    "disk": "58%",
    "peak_value": "94%",
    "previous_severity": "WARNING",
    "previous_value": "84%",
    "started_at": "18.08.2026 10:42",
    "recovered_at": "18.08.2026 11:01",
    "duration": "19m 04s",
    "last_seen": "10:41",
    "dashboard_url": "/servers?server_id=app-srv-01",
    "report_date": "18 Ağustos 2026",
    "report_body": "GENEL DURUM\n200 monitored servers\n194 Healthy\n4 Warning\n1 Critical\n1 Offline",
}


def _runtime():
    return get_runtime()


def _actor():
    return session.get("admin_username") or "admin"


def _body():
    return request.get_json(silent=True) or {}


def _audit(action, detail=""):
    runtime = _runtime()
    if runtime is not None:
        runtime.store.audit(_actor(), action, detail)


@bp.get("/overview")
@auth.admin_login_required
def notifications_overview():
    runtime = _runtime()
    settings = current_app.extensions["iim_settings"]
    if runtime is None:
        return jsonify({"error": "Mail service not available"}), 503
    stats = runtime.store.delivery_stats()
    smtp = runtime.mailer.test_connection() if not settings.demo_mode else {"ok": False, "error": "demo"}
    settings_map = runtime.store.get_settings()
    recipients = runtime.store.list_recipients()
    rules = runtime.store.enabled_rules()
    return jsonify({
        "demo_mode": settings.demo_mode,
        "enabled": settings_map.get("email_enabled", "1") == "1",
        "smtp": {
            "configured": runtime.mailer.configured(),
            "connected": smtp.get("ok", False),
            "error": smtp.get("error", ""),
        },
        "queue": runtime.worker.queue_health(),
        "stats": {
            "sent_today": stats["sent_today"],
            "failed_today": stats["failed_today"],
            "pending": stats["pending"],
            "last_sent_at": trt_text(stats["last_sent_at"]) if stats["last_sent_at"] else None,
            "recipients": len([r for r in recipients if r["status"] == "active"]),
            "active_rules": len(rules),
        },
        "events": EVENT_OPTIONS,
    })


@bp.post("/test-email")
@auth.admin_login_required
def notifications_test_email():
    runtime = _runtime()
    if runtime is None:
        return jsonify({"error": "Mail service not available"}), 503
    email = str(_body().get("email") or "").strip()
    if not email or "@" not in email:
        return jsonify({"error": "Valid email is required"}), 400
    ok, message = runtime.engine.send_test_email(email)
    _audit("TEST_EMAIL_SENT", email)
    return jsonify({"ok": ok, "message": message})


TEST_TEMPLATE_TYPES = ("critical", "warning", "offline", "recovery", "escalation", "daily_report", "test")


def _worst_metric(metrics, thresholds):
    candidates = []
    if metrics is not None:
        if metrics.cpu_percent is not None:
            candidates.append(("CPU", metrics.cpu_percent, thresholds["cpu_warning"], thresholds["cpu_critical"]))
        if metrics.memory_percent is not None:
            candidates.append(("Memory", metrics.memory_percent, thresholds["memory_warning"], thresholds["memory_critical"]))
        if metrics.disk.highest_usage_percent is not None:
            candidates.append(("Disk", metrics.disk.highest_usage_percent, thresholds["disk_warning"], thresholds["disk_critical"]))
    worst = None
    for name, value, warn, crit in candidates:
        ratio = value / crit if crit else 0
        if worst is None or ratio > worst[0]:
            worst = (ratio, name, value, warn, crit)
    return worst[1:] if worst else None


@bp.post("/test-format")
@auth.admin_login_required
def notifications_test_format():
    runtime = _runtime()
    if runtime is None:
        return jsonify({"error": "Mail service not available"}), 503
    settings = current_app.extensions["iim_settings"]
    data = _body()
    template_type = str(data.get("template_type") or "test").strip()
    email = str(data.get("email") or "").strip().lower()
    server_id = str(data.get("server_id") or "").strip()
    if not email or "@" not in email:
        return jsonify({"error": "Valid email is required"}), 400
    if template_type not in TEST_TEMPLATE_TYPES:
        return jsonify({"error": "Unknown template type"}), 400

    if template_type == "daily_report":
        ok, message = runtime.daily.send_to(email)
        _audit("TEST_FORMAT_SENT", "daily_report -> {0}".format(email))
        return jsonify({"ok": ok, "message": message})

    template = runtime.store.get_template(template_type=template_type)
    if template is None:
        return jsonify({"error": "Template not found"}), 404

    server = None
    health = None
    if template_type != "test" and runtime.engine.collector is not None:
        server = next(
            (s for s in runtime.engine.collector.inventory if s.id == server_id),
            None,
        )
        if server is None:
            return jsonify({"error": "Server not found"}), 404
        health = runtime.engine.collector.engine.get_health(server.id)

    if template_type == "test":
        payload = {"started_at": trt_text(time.time())}
    else:
        metrics = health.metrics if health else None
        payload = runtime.engine._base_payload(server, metrics, time.time())
        worst = _worst_metric(metrics, settings.thresholds)
        if template_type in ("critical", "warning"):
            if worst:
                name, value, warn, crit = worst
                payload["reason"] = name
                payload["metric"] = name
                payload["issue"] = "{0} usage exceeded {1} threshold".format(
                    name, template_type)
                payload["value"] = "{0}%".format(value)
                payload["threshold"] = "{0}%".format(crit if template_type == "critical" else warn)
            else:
                payload["reason"] = "Resource usage"
                payload["issue"] = "Resource usage exceeded {0} threshold".format(template_type)
                payload["value"] = "—"
                payload["threshold"] = "—"
        elif template_type == "offline":
            payload["reason"] = "Host unreachable"
            payload["issue"] = "Host unreachable"
            payload["value"] = ""
            payload["last_seen"] = payload.get("started_at", "")
        elif template_type == "recovery":
            payload["issue"] = "Resource usage"
            payload["peak_value"] = payload.get("peak_value") or "—"
            payload["value"] = "{0}%".format(worst[1]) if worst else "—"
            payload["recovered_at"] = trt_text(time.time())
            payload["duration"] = payload.get("duration") or "—"
        elif template_type == "escalation":
            payload["reason"] = worst[0] if worst else "Memory"
            payload["issue"] = "{0} usage escalated".format(worst[0] if worst else "Memory")
            payload["previous_severity"] = "WARNING"
            payload["previous_value"] = "84%"
            payload["severity"] = "CRITICAL"
            payload["value"] = "{0}%".format(worst[1]) if worst else "94%"

    subject = render(template["subject_template"], payload)
    html_body = render(template["html_body"], payload)
    text_body = render(template["text_body"], payload)

    if settings.demo_mode:
        _audit("TEST_FORMAT_SENT", "{0} simulated -> {1}".format(template_type, email))
        return jsonify({"ok": True, "message": "Demo mode: test mail simulated (dışarı gitmedi)"})

    event_id, _ = runtime.store.add_event(
        event_type="TEST_EMAIL", severity="info",
        dedup_key="testfmt:{0}:{1}".format(template_type, int(time.time())),
        payload=payload, server_id=server.id if server else None,
    )
    runtime.store.enqueue(event_id, email, subject, html_body, text_body)
    _audit("TEST_FORMAT_SENT", "{0} -> {1}".format(template_type, email))
    return jsonify({"ok": True, "message": "Test mail queued ({0} şablonu)".format(template_type)})


@bp.post("/smtp-test")
@auth.admin_login_required
def notifications_smtp_test():
    runtime = _runtime()
    settings = current_app.extensions["iim_settings"]
    if runtime is None:
        return jsonify({"error": "Mail service not available"}), 503
    if settings.demo_mode:
        result = {"ok": False, "error": "Demo mode: SMTP not used"}
    else:
        result = runtime.mailer.test_connection()
    _audit("SMTP_TEST", "ok" if result["ok"] else result.get("error", ""))
    return jsonify(result)


# ---------- recipients ----------

@bp.get("/recipients")
@auth.admin_login_required
def recipients_list():
    runtime = _runtime()
    if runtime is None:
        return jsonify({"items": []})
    return jsonify({"items": runtime.store.list_recipients()})


def _recipient_data(data):
    return {
        "name": str(data.get("name") or "").strip(),
        "email": str(data.get("email") or "").strip().lower(),
        "department": str(data.get("department") or "").strip(),
        "role": str(data.get("role") or "").strip(),
        "status": str(data.get("status") or "active").strip(),
        "verified": bool(data.get("verified", False)),
    }


@bp.post("/recipients")
@auth.admin_login_required
def recipients_add():
    data = _recipient_data(_body())
    if not data["name"] or not data["email"]:
        return jsonify({"error": "Name and email are required"}), 400
    recipient_id = _runtime().store.add_recipient(data)
    _audit("RECIPIENT_ADDED", data["email"])
    return jsonify({"ok": True, "id": recipient_id})


@bp.put("/recipients/<int:recipient_id>")
@auth.admin_login_required
def recipients_update(recipient_id):
    data = _recipient_data(_body())
    if not data["name"] or not data["email"]:
        return jsonify({"error": "Name and email are required"}), 400
    if not _runtime().store.update_recipient(recipient_id, data):
        return jsonify({"error": "Recipient not found"}), 404
    _audit("RECIPIENT_UPDATED", data["email"])
    return jsonify({"ok": True})


@bp.delete("/recipients/<int:recipient_id>")
@auth.admin_login_required
def recipients_delete(recipient_id):
    runtime = _runtime()
    recipient = runtime.store.get_recipient(recipient_id)
    if recipient is None:
        return jsonify({"error": "Recipient not found"}), 404
    runtime.store.delete_recipient(recipient_id)
    _audit("RECIPIENT_DELETED", recipient["email"])
    return jsonify({"ok": True})


# ---------- groups ----------

@bp.get("/groups")
@auth.admin_login_required
def groups_list():
    runtime = _runtime()
    if runtime is None:
        return jsonify({"items": []})
    return jsonify({"items": runtime.store.list_groups()})


@bp.get("/groups/<int:group_id>")
@auth.admin_login_required
def groups_get(group_id):
    group = _runtime().store.get_group(group_id)
    if group is None:
        return jsonify({"error": "Group not found"}), 404
    return jsonify(group)


@bp.post("/groups")
@auth.admin_login_required
def groups_add():
    data = _body()
    name = str(data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Group name is required"}), 400
    group_id = _runtime().store.add_group({"name": name, "description": data.get("description"), "enabled": data.get("enabled", True)})
    _audit("GROUP_ADDED", name)
    return jsonify({"ok": True, "id": group_id})


@bp.put("/groups/<int:group_id>")
@auth.admin_login_required
def groups_update(group_id):
    data = _body()
    name = str(data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Group name is required"}), 400
    if _runtime().store.get_group(group_id) is None:
        return jsonify({"error": "Group not found"}), 404
    member_ids = [int(value) for value in (data.get("member_ids") or []) if str(value).isdigit()]
    _runtime().store.update_group(group_id, {
        "name": name, "description": data.get("description"),
        "enabled": data.get("enabled", True), "member_ids": member_ids,
    })
    _audit("GROUP_UPDATED", name)
    return jsonify({"ok": True})


@bp.delete("/groups/<int:group_id>")
@auth.admin_login_required
def groups_delete(group_id):
    runtime = _runtime()
    group = runtime.store.get_group(group_id)
    if group is None:
        return jsonify({"error": "Group not found"}), 404
    runtime.store.delete_group(group_id)
    _audit("GROUP_DELETED", group["name"])
    return jsonify({"ok": True})


# ---------- rules ----------

@bp.get("/rules")
@auth.admin_login_required
def rules_list():
    runtime = _runtime()
    if runtime is None:
        return jsonify({"items": [], "events": EVENT_OPTIONS})
    return jsonify({"items": runtime.store.list_rules(), "events": EVENT_OPTIONS})


@bp.get("/rules/<int:rule_id>")
@auth.admin_login_required
def rules_get(rule_id):
    rule = _runtime().store.get_rule(rule_id)
    if rule is None:
        return jsonify({"error": "Rule not found"}), 404
    return jsonify(rule)


def _rule_data(data):
    targets = []
    for target in data.get("targets") or []:
        try:
            target_id = int(target.get("id"))
        except (TypeError, ValueError):
            continue
        target_type = target.get("type")
        if target_type in ("recipient", "group"):
            targets.append({"type": target_type, "id": target_id})
    return {
        "name": str(data.get("name") or "").strip(),
        "event_type": str(data.get("event_type") or "").strip(),
        "enabled": bool(data.get("enabled", True)),
        "cooldown_seconds": int(data.get("cooldown_seconds") or 1800),
        "reminder_interval_seconds": int(data.get("reminder_interval_seconds") or 3600),
        "max_reminders": int(data.get("max_reminders") or 3),
        "targets": targets,
    }


@bp.post("/rules")
@auth.admin_login_required
def rules_add():
    data = _rule_data(_body())
    if not data["name"] or not data["event_type"]:
        return jsonify({"error": "Name and event type are required"}), 400
    rule_id = _runtime().store.add_rule(data)
    _audit("RULE_ADDED", data["name"])
    return jsonify({"ok": True, "id": rule_id})


@bp.put("/rules/<int:rule_id>")
@auth.admin_login_required
def rules_update(rule_id):
    data = _rule_data(_body())
    if not data["name"] or not data["event_type"]:
        return jsonify({"error": "Name and event type are required"}), 400
    if not _runtime().store.update_rule(rule_id, data):
        return jsonify({"error": "Rule not found"}), 404
    _audit("RULE_UPDATED", data["name"])
    return jsonify({"ok": True})


@bp.delete("/rules/<int:rule_id>")
@auth.admin_login_required
def rules_delete(rule_id):
    runtime = _runtime()
    rule = runtime.store.get_rule(rule_id)
    if rule is None:
        return jsonify({"error": "Rule not found"}), 404
    runtime.store.delete_rule(rule_id)
    _audit("RULE_DELETED", rule["name"])
    return jsonify({"ok": True})


# ---------- templates ----------

@bp.get("/templates")
@auth.admin_login_required
def templates_list():
    runtime = _runtime()
    if runtime is None:
        return jsonify({"items": []})
    items = runtime.store.list_templates()
    for item in items:
        item.pop("html_body", None)
        item.pop("text_body", None)
    return jsonify({"items": items})


@bp.get("/templates/<int:template_id>")
@auth.admin_login_required
def templates_get(template_id):
    template = _runtime().store.get_template(template_id=template_id)
    if template is None:
        return jsonify({"error": "Template not found"}), 404
    return jsonify(template)


@bp.put("/templates/<int:template_id>")
@auth.admin_login_required
def templates_update(template_id):
    data = _body()
    if not _runtime().store.update_template(template_id, {
        "subject_template": data.get("subject_template", ""),
        "html_body": data.get("html_body", ""),
        "text_body": data.get("text_body", ""),
        "enabled": data.get("enabled", True),
    }):
        return jsonify({"error": "Template not found"}), 404
    _audit("TEMPLATE_UPDATED", "id={0}".format(template_id))
    return jsonify({"ok": True})


@bp.post("/templates/<int:template_id>/preview")
@auth.admin_login_required
def templates_preview(template_id):
    runtime = _runtime()
    template = runtime.store.get_template(template_id=template_id)
    if template is None:
        return jsonify({"error": "Template not found"}), 404
    payload = dict(SAMPLE_PAYLOAD)
    payload.update(_body().get("payload") or {})
    return jsonify({
        "subject": render(template["subject_template"], payload),
        "html_body": render(template["html_body"], payload),
        "text_body": render(template["text_body"], payload),
    })


# ---------- deliveries ----------

@bp.get("/deliveries")
@auth.admin_login_required
def deliveries_list():
    runtime = _runtime()
    if runtime is None:
        return jsonify({"items": []})
    limit = min(int(request.args.get("limit") or 200), 1000)
    items = runtime.store.list_deliveries(limit)
    for item in items:
        item["created_text"] = trt_text(item["created_at"]) if item.get("created_at") else None
    return jsonify({"items": items})


@bp.get("/deliveries/<int:delivery_id>")
@auth.admin_login_required
def deliveries_get(delivery_id):
    delivery = _runtime().store.get_delivery(delivery_id)
    if delivery is None:
        return jsonify({"error": "Delivery not found"}), 404
    delivery["created_text"] = trt_text(delivery["created_at"]) if delivery.get("created_at") else None
    delivery["sent_text"] = trt_text(delivery["sent_at"]) if delivery.get("sent_at") else None
    return jsonify(delivery)


# ---------- settings ----------

@bp.get("/settings")
@auth.admin_login_required
def settings_get():
    runtime = _runtime()
    if runtime is None:
        return jsonify({"error": "Mail service not available"}), 503
    settings = current_app.extensions["iim_settings"]
    return jsonify({
        "values": runtime.store.get_settings(),
        "smtp": {
            "configured": runtime.mailer.configured(),
            "host": runtime.mailer.host or "",
            "port": runtime.mailer.port or "",
            "username": runtime.mailer.username or "",
            "from": runtime.mailer.from_address or "",
            "tls": bool(runtime.mailer.use_tls),
            "password_configured": bool(runtime.mailer.password),
        },
        "demo_mode": settings.demo_mode,
    })


SETTING_KEYS = (
    "email_enabled", "critical_enabled", "warning_enabled", "offline_enabled",
    "recovery_enabled", "default_cooldown", "default_reminder", "max_reminders",
)


@bp.put("/settings")
@auth.admin_login_required
def settings_update():
    runtime = _runtime()
    if runtime is None:
        return jsonify({"error": "Mail service not available"}), 503
    data = _body()
    values = {}
    for key in SETTING_KEYS:
        if key in data:
            values[key] = "1" if data[key] is True else "0" if data[key] is False else str(data[key])
    runtime.store.set_settings(values)
    _audit("SETTINGS_UPDATED", ", ".join(sorted(values.keys())))
    return jsonify({"ok": True})


# ---------- daily report ----------

@bp.get("/daily-report")
@auth.admin_login_required
def daily_report_get():
    runtime = _runtime()
    if runtime is None:
        return jsonify({"error": "Mail service not available"}), 503
    return jsonify(runtime.store.get_daily_report_config() or {})


@bp.put("/daily-report")
@auth.admin_login_required
def daily_report_update():
    runtime = _runtime()
    if runtime is None:
        return jsonify({"error": "Mail service not available"}), 503
    data = _body()
    runtime.store.update_daily_report_config({
        "enabled": data.get("enabled", True),
        "hour": data.get("hour", 15),
        "minute": data.get("minute", 50),
        "timezone": data.get("timezone", "Europe/Istanbul"),
        "recipient_group_id": data.get("recipient_group_id"),
        "include_summary": data.get("include_summary", True),
        "include_incidents": data.get("include_incidents", True),
        "include_resources": data.get("include_resources", True),
        "include_availability": data.get("include_availability", True),
        "include_offline": data.get("include_offline", True),
        "include_warnings": data.get("include_warnings", True),
        "include_criticals": data.get("include_criticals", True),
        "include_virtualization": data.get("include_virtualization", True),
        "attachment": data.get("attachment", "none"),
    })
    _audit("DAILY_REPORT_UPDATED", "")
    return jsonify({"ok": True})


@bp.post("/daily-report/send-now")
@auth.admin_login_required
def daily_report_send_now():
    runtime = _runtime()
    if runtime is None:
        return jsonify({"error": "Mail service not available"}), 503
    ok, message = runtime.daily.send_now()
    _audit("DAILY_REPORT_SEND_NOW", message)
    return jsonify({"ok": ok, "message": message})


# ---------- audit ----------

@bp.get("/audit")
@auth.admin_login_required
def audit_list():
    runtime = _runtime()
    if runtime is None:
        return jsonify({"items": []})
    items = runtime.store.list_audit(100)
    for item in items:
        item["ts_text"] = trt_text(item["ts"]) if item.get("ts") else None
    return jsonify({"items": items})
