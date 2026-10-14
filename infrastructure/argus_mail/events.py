import time
from datetime import datetime, timedelta, timezone

SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2, "offline": 3}

EVENT_TYPES = (
    "SERVER_OFFLINE",
    "SERVER_RECOVERED",
    "CPU_WARNING",
    "CPU_CRITICAL",
    "CPU_RECOVERED",
    "MEMORY_WARNING",
    "MEMORY_CRITICAL",
    "MEMORY_RECOVERED",
    "DISK_WARNING",
    "DISK_CRITICAL",
    "DISK_RECOVERED",
    "TELEMETRY_LOST",
    "TELEMETRY_RECOVERED",
    "ESCALATED",
    "INCIDENT_OPENED",
    "INCIDENT_RESOLVED",
    "DAILY_REPORT",
    "TEST_EMAIL",
)

EVENT_LABELS = {
    "SERVER_OFFLINE": "Server Offline",
    "SERVER_RECOVERED": "Server Recovery",
    "CPU_WARNING": "CPU Warning",
    "CPU_CRITICAL": "CPU Critical",
    "CPU_RECOVERED": "CPU Recovery",
    "MEMORY_WARNING": "Memory Warning",
    "MEMORY_CRITICAL": "Memory Critical",
    "MEMORY_RECOVERED": "Memory Recovery",
    "DISK_WARNING": "Disk Warning",
    "DISK_CRITICAL": "Disk Critical",
    "DISK_RECOVERED": "Disk Recovery",
    "TELEMETRY_LOST": "Telemetry Lost",
    "TELEMETRY_RECOVERED": "Telemetry Recovery",
    "ESCALATED": "Escalation",
    "INCIDENT_OPENED": "Incident Opened",
    "INCIDENT_RESOLVED": "Incident Resolved",
    "DAILY_REPORT": "Daily Report",
    "TEST_EMAIL": "Test Email",
}

TEMPLATE_BY_EVENT = {
    "SERVER_OFFLINE": "offline",
    "CPU_WARNING": "warning",
    "CPU_CRITICAL": "critical",
    "MEMORY_WARNING": "warning",
    "MEMORY_CRITICAL": "critical",
    "DISK_WARNING": "warning",
    "DISK_CRITICAL": "critical",
    "TELEMETRY_LOST": "warning",
    "ESCALATED": "escalation",
    "SERVER_RECOVERED": "recovery",
    "CPU_RECOVERED": "recovery",
    "MEMORY_RECOVERED": "recovery",
    "DISK_RECOVERED": "recovery",
    "TELEMETRY_RECOVERED": "recovery",
    "INCIDENT_OPENED": "warning",
    "INCIDENT_RESOLVED": "recovery",
}


def _trt(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc) + timedelta(hours=3)


def trt_text(ts):
    return _trt(ts).strftime("%d.%m.%Y %H:%M")


def fmt_duration(seconds):
    if seconds is None:
        return ""
    seconds = int(seconds)
    if seconds < 60:
        return "{0}s".format(seconds)
    if seconds < 3600:
        minutes, secs = divmod(seconds, 60)
        return "{0}m {1:02d}s".format(minutes, secs)
    hours, minutes = divmod(seconds, 3600)
    return "{0}h {1:02d}m".format(hours, minutes // 60)


def build_payload(server, state, reason, value, metrics, tracker, now):
    payload = {
        "server_id": server.id,
        "server_name": server.hostname,
        "ip": server.ip or "",
        "site": server.site or "",
        "role": server.role or "",
        "status": state,
        "severity": state.upper(),
        "reason": reason or "",
        "issue": _issue_text(state, reason),
        "metric": reason or "",
        "value": "{0}{1}".format(round(value), "%") if isinstance(value, (int, float)) else (value or ""),
        "threshold": "",
        "started_at": trt_text(now),
        "recovered_at": "",
        "duration": "",
        "last_seen": "",
        "cpu": "",
        "disk": "",
        "peak_value": "",
        "previous_severity": "",
        "previous_value": "",
    }
    if metrics is not None:
        if metrics.cpu_percent is not None:
            payload["cpu"] = "{0}%".format(metrics.cpu_percent)
        if metrics.disk.highest_usage_percent is not None:
            payload["disk"] = "{0}%".format(metrics.disk.highest_usage_percent)
    if tracker is not None:
        record = tracker.get_active(server.id)
        if record:
            payload["peak_value"] = record.get("peak_value") or ""
            payload["started_at"] = trt_text(record.get("started_at"))
            payload["duration"] = fmt_duration(now - record.get("started_at"))
    return payload


def _issue_text(state, reason):
    if state == "offline":
        return "Host unreachable"
    if state == "no_telemetry":
        return "Exporter telemetry lost"
    if reason in ("CPU", "Memory", "Disk"):
        return "{0} usage exceeded threshold".format(reason.lower().capitalize())
    return reason or state


def transition_event_type(resource, new_state, previous_state, is_new_incident):
    if new_state == "healthy":
        if resource is None:
            return "SERVER_RECOVERED"
        return "{0}_RECOVERED".format(resource)
    if resource == "CPU":
        return "CPU_CRITICAL" if new_state == "critical" else "CPU_WARNING"
    if resource == "Memory":
        return "MEMORY_CRITICAL" if new_state == "critical" else "MEMORY_WARNING"
    if resource == "Disk":
        return "DISK_CRITICAL" if new_state == "critical" else "DISK_WARNING"
    if new_state == "offline":
        return "SERVER_OFFLINE"
    if new_state == "no_telemetry":
        return "TELEMETRY_LOST"
    return None
