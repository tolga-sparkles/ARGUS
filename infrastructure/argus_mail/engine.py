import time

from infrastructure.argus_mail.events import (
    EVENT_LABELS,
    TEMPLATE_BY_EVENT,
    fmt_duration,
    trt_text,
)
from infrastructure.argus_mail.mailer import render


class NotificationEngine:
    def __init__(self, store, settings, tracker, collector=None, virt_store=None):
        self.store = store
        self.settings = settings
        self.tracker = tracker
        self.collector = collector
        self.virt_store = virt_store
        self._reminder_state = {}
        self._dashboard_base = settings.dashboard_url

    def emit_transition(self, server, previous_state, new_state, reason, value, metrics, now):
        if self.settings.demo_mode:
            return
        from infrastructure.argus_mail.events import transition_event_type

        resource = reason if reason in ("CPU", "Memory", "Disk") else None
        if new_state == "healthy":
            event_type = transition_event_type(resource, new_state, previous_state, False)
            severity = "recovery"
        elif previous_state == "warning" and new_state == "critical":
            event_type = "ESCALATED"
            severity = "critical"
        else:
            event_type = transition_event_type(resource, new_state, previous_state, False)
            severity = new_state
        if not event_type:
            return

        self._process_event(
            event_type=event_type,
            severity=severity,
            server=server,
            payload_extra={
                "value": "{0}{1}".format(round(value), "%") if isinstance(value, (int, float)) else (value or ""),
                "previous_value": "",
            },
            metrics=metrics,
            now=now,
        )

    def _process_event(self, event_type, severity, server, payload_extra, metrics, now, incident_id=None):
        settings_map = self.store.get_settings()
        if settings_map.get("email_enabled", "1") != "1":
            return
        if severity == "warning" and settings_map.get("warning_enabled", "0") != "1":
            return
        if severity == "critical" and settings_map.get("critical_enabled", "1") != "1":
            return
        if severity == "offline" and settings_map.get("offline_enabled", "1") != "1":
            return
        if severity == "recovery" and settings_map.get("recovery_enabled", "1") != "1":
            return

        rules = self.store.enabled_rules()
        matching = [rule for rule in rules if rule["event_type"] == event_type]
        if not matching:
            return

        payload = self._base_payload(server, metrics, now)
        payload.update(payload_extra or {})

        template_type = TEMPLATE_BY_EVENT.get(event_type, "warning")
        template = self.store.get_template(template_type=template_type)
        if template is None or not template["enabled"]:
            return

        dedup_key = "{0}:{1}:{2}".format(server.id, event_type, int(now // 60))
        event_id, duplicate = self.store.add_event(
            event_type=event_type,
            severity=severity,
            dedup_key=dedup_key,
            payload=payload,
            incident_id=incident_id,
            server_id=server.id,
        )
        if duplicate:
            return

        for rule in matching:
            recipients = self._rule_recipients(rule)
            if not recipients:
                continue
            subject = render(template["subject_template"], payload)
            html_body = render(template["html_body"], payload)
            text_body = render(template["text_body"], payload)
            for email in recipients:
                if self.store.queue_full(self.settings.mail_queue_limit):
                    return
                self.store.enqueue(event_id, email, subject, html_body, text_body)

    def _rule_recipients(self, rule):
        emails = []
        for target in rule.get("targets") or []:
            if target["type"] == "recipient":
                recipient = self.store.get_recipient(target["id"])
                if recipient and recipient["status"] == "active" and recipient["verified"]:
                    emails.append(recipient["email"])
            elif target["type"] == "group":
                emails.extend(self.store.group_recipient_emails(target["id"]))
        return sorted(set(emails))

    def _base_payload(self, server, metrics, now):
        payload = {
            "server_id": server.id,
            "server_name": server.hostname,
            "ip": server.ip or "",
            "site": server.site or "",
            "role": server.role or "",
            "started_at": trt_text(now),
            "recovered_at": "",
            "duration": "",
            "last_seen": "",
            "cpu": "",
            "disk": "",
            "peak_value": "",
            "threshold": "",
            "previous_severity": "",
            "previous_value": "",
            "dashboard_url": self._dashboard_link(server.id),
        }
        if metrics is not None:
            if metrics.cpu_percent is not None:
                payload["cpu"] = "{0}%".format(metrics.cpu_percent)
            if metrics.disk.highest_usage_percent is not None:
                payload["disk"] = "{0}%".format(metrics.disk.highest_usage_percent)
        record = self.tracker.get_active(server.id)
        if record:
            payload["peak_value"] = record.get("peak_value") or ""
            payload["started_at"] = trt_text(record.get("started_at"))
            payload["duration"] = fmt_duration(now - record.get("started_at"))
        return payload

    def _dashboard_link(self, server_id):
        base = (self._dashboard_base or "").rstrip("/")
        if base:
            return "{0}/servers?server_id={1}".format(base, server_id)
        return "/servers?server_id={0}".format(server_id)

    def send_test_email(self, recipient_email):
        template = self.store.get_template(template_type="test")
        if template is None:
            return False, "Test template not found"
        payload = {"started_at": trt_text(time.time())}
        subject = render(template["subject_template"], payload)
        html_body = render(template["html_body"], payload)
        text_body = render(template["text_body"], payload)
        if self.settings.demo_mode:
            self.store.audit("admin", "TEST_EMAIL", "demo simulated -> {0}".format(recipient_email))
            return True, "Demo email generated (simulated)"
        event_id, _ = self.store.add_event(
            event_type="TEST_EMAIL", severity="info",
            dedup_key="test:{0}:{1}".format(recipient_email, int(time.time())),
            payload=payload, server_id=None,
        )
        self.store.enqueue(event_id, recipient_email, subject, html_body, text_body)
        return True, "Test email queued"
