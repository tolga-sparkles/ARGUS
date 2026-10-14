import time
from datetime import datetime, timezone

from infrastructure.models import SEVERITY_ORDER, ATTENTION_STATES, ServerState


def format_duration(seconds):
    if seconds is None:
        return ""
    seconds = int(seconds)
    if seconds < 60:
        return "{0}s".format(seconds)
    if seconds < 3600:
        minutes, secs = divmod(seconds, 60)
        return "{0}m".format(minutes) if secs == 0 else "{0}m {1}s".format(minutes, secs)
    if seconds < 86400:
        hours, minutes = divmod(seconds, 3600)
        return "{0}h {1}m".format(hours, minutes // 60)
    days, hours = divmod(seconds, 86400)
    return "{0}d {1}h".format(days, hours // 3600)


def format_bytes(value):
    if value is None:
        return ""
    value = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(value) < 1024.0 or unit == "PB":
            return "{0:.1f} {1}".format(value, unit) if unit in ("GB", "TB", "PB") else "{0:.0f} {1}".format(value, unit)
        value /= 1024.0
    return "{0:.0f} B".format(value)


def build_empty_overview(servers, settings):
    now = time.time()
    groups = _build_groups(servers, {})
    return {
        "generated_at": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        "data_state": "no_data",
        "demo_mode": settings.demo_mode,
        "summary": {
            "total": len(servers),
            "healthy": 0,
            "warning": 0,
            "critical": 0,
            "offline": 0,
            "no_telemetry": 0,
        },
        "attention": [],
        "resource_pressure": {
            "highest_cpu": None,
            "highest_memory": None,
            "lowest_disk_free": None,
            "highest_ping": None,
        },
        "groups": groups,
        "collector_health": {
            "prometheus": "unknown",
            "inventory": {"state": "loaded", "count": len(servers)},
            "ping_probe": "unknown",
            "metrics_age_sec": None,
        },
        "recent_events": [],
    }


def build_overview(engine, servers, settings, result):
    now = time.time()
    health_by_id = {}
    summary = {"total": len(servers), "healthy": 0, "warning": 0, "critical": 0, "offline": 0, "no_telemetry": 0}
    for server in servers:
        health = engine.get_health(server.id)
        if health is None:
            continue
        health_by_id[server.id] = health
        summary[health.state.value] = summary.get(health.state.value, 0) + 1

    attention = []
    for server in servers:
        health = health_by_id.get(server.id)
        if health is None or health.state not in ATTENTION_STATES:
            continue
        duration = now - (health.state_since or now)
        if health.state == ServerState.OFFLINE:
            reason = "Unreachable"
            value = format_duration(duration)
            duration_text = ""
        else:
            reason = health.reason or "Resource"
            value = health.value or ""
            duration_text = format_duration(duration)
        attention.append({
            "id": server.id,
            "hostname": server.hostname,
            "ip": server.ip,
            "state": health.state.value,
            "reason": reason,
            "value": value,
            "duration_text": duration_text,
        })
    attention.sort(key=lambda item: (SEVERITY_ORDER[ServerState(item["state"])], item["hostname"]))
    attention = attention[: settings.attention_limit]

    resource_pressure = _build_resource_pressure(servers, health_by_id, settings)

    return {
        "generated_at": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        "data_state": "ok" if result.ok else "unavailable",
        "demo_mode": settings.demo_mode,
        "summary": summary,
        "attention": attention,
        "resource_pressure": resource_pressure,
        "groups": _build_groups(servers, health_by_id),
        "collector_health": {
            "prometheus": _prometheus_state(settings, result),
            "inventory": {"state": "loaded", "count": len(servers)},
            "ping_probe": "ready" if result.ping_data_seen else "unknown",
            "metrics_age_sec": int(now - result.collected_at) if result.collected_at else None,
        },
        "recent_events": engine.recent_events(),
    }


def _prometheus_state(settings, result):
    if settings.demo_mode:
        return "demo"
    if result.prometheus_connected:
        return "connected"
    if result.error:
        return "error"
    return "unknown"


def _build_groups(servers, health_by_id):
    groups = {}
    for server in servers:
        group = groups.setdefault(server.role or "Unassigned", {
            "name": server.role or "Unassigned",
            "total": 0,
            "healthy": 0,
            "warning": 0,
            "critical": 0,
            "offline": 0,
            "no_telemetry": 0,
        })
        group["total"] += 1
        health = health_by_id.get(server.id)
        if health is None:
            continue
        group[health.state.value] = group.get(health.state.value, 0) + 1
    return sorted(groups.values(), key=lambda item: item["name"].lower())


def _build_resource_pressure(servers, health_by_id, settings):
    t = settings.thresholds
    candidates = {"highest_cpu": [], "highest_memory": [], "lowest_disk_free": [], "highest_ping": []}
    for server in servers:
        health = health_by_id.get(server.id)
        if health is None or health.metrics is None:
            continue
        metrics = health.metrics
        if metrics.telemetry_state != "online":
            continue
        if metrics.cpu_percent is not None:
            candidates["highest_cpu"].append((metrics.cpu_percent, server, _severity(metrics.cpu_percent, t["cpu_warning"], t["cpu_critical"]), "{0}%".format(round(metrics.cpu_percent))))
        if metrics.memory_percent is not None:
            candidates["highest_memory"].append((metrics.memory_percent, server, _severity(metrics.memory_percent, t["memory_warning"], t["memory_critical"]), "{0}%".format(round(metrics.memory_percent))))
        if metrics.disk.highest_usage_percent is not None:
            free = 100.0 - metrics.disk.highest_usage_percent
            candidates["lowest_disk_free"].append((free, server, _severity(metrics.disk.highest_usage_percent, t["disk_warning"], t["disk_critical"]), "{0}%".format(round(free))))
        if metrics.ping.data_available and metrics.ping.reachable and metrics.ping.latency_ms is not None:
            candidates["highest_ping"].append((metrics.ping.latency_ms, server, _severity(metrics.ping.latency_ms, t["ping_warning_ms"], t["ping_critical_ms"]), "{0} ms".format(round(metrics.ping.latency_ms))))

    pressure = {}
    for key, sort_desc in (("highest_cpu", True), ("highest_memory", True), ("lowest_disk_free", False), ("highest_ping", True)):
        items = candidates[key]
        if not items:
            pressure[key] = None
            continue
        items.sort(key=lambda item: item[0], reverse=sort_desc)
        value, server, severity, value_text = items[0]
        pressure[key] = {
            "server_id": server.id,
            "hostname": server.hostname,
            "value": round(value, 1),
            "value_text": value_text,
            "severity": severity,
        }
    return pressure


def _severity(value, warning, critical):
    if value >= critical:
        return "critical"
    if value >= warning:
        return "warning"
    return "healthy"
