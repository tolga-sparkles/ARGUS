import time
from datetime import datetime, timezone

from infrastructure.incidents import fmt_ago
from infrastructure.inventory import enabled_servers
from infrastructure.models import ATTENTION_STATES, SEVERITY_ORDER, ServerState
from infrastructure.snapshot import format_bytes, format_duration

SORT_OPTIONS = ("severity", "hostname", "ip", "cpu", "memory", "disk", "ping", "uptime")
STATUS_OPTIONS = ("all", "healthy", "warning", "critical", "offline", "no_telemetry")
SEVERITY_OPTIONS = ("all", "critical", "warning", "offline", "no_telemetry")

_UNKNOWN = "unknown"


def _severity_key(state):
    member = ServerState._value2member_map_.get(state)
    return SEVERITY_ORDER.get(member, 99)


def _state_of(health):
    if health is None:
        return _UNKNOWN
    return health.state.value


def build_server_item(server, health, now):
    state = _state_of(health)
    metrics = health.metrics if health else None
    ping = metrics.ping if metrics else None

    cpu = None
    memory = None
    disk_usage = None
    uptime = None
    last_seen_text = "—"
    telemetry_state = "absent"
    if metrics:
        cpu = metrics.cpu_percent
        memory = metrics.memory_percent
        if metrics.disk:
            disk_usage = metrics.disk.highest_usage_percent
        uptime = metrics.uptime_seconds
        telemetry_state = metrics.telemetry_state
        if metrics.telemetry_age_seconds is not None:
            last_seen_text = fmt_ago(metrics.telemetry_age_seconds)

    return {
        "id": server.id,
        "hostname": server.hostname,
        "display_name": server.display_name,
        "ip": server.ip,
        "site": server.site,
        "role": server.role,
        "environment": server.environment,
        "os": server.os,
        "state": state,
        "cpu_percent": cpu,
        "cpu_cores": metrics.cpu_cores if metrics else None,
        "memory_percent": memory,
        "memory_total_bytes": metrics.memory_total_bytes if metrics else None,
        "memory_used_bytes": metrics.memory_used_bytes if metrics else None,
        "memory_total_text": format_bytes(metrics.memory_total_bytes) if metrics else "",
        "memory_used_text": format_bytes(metrics.memory_used_bytes) if metrics else "",
        "disk_usage_percent": disk_usage,
        "disk_total_bytes": metrics.disk.total_bytes if metrics and metrics.disk else None,
        "disk_used_bytes": metrics.disk.used_bytes if metrics and metrics.disk else None,
        "disk_free_bytes": (metrics.disk.total_bytes - metrics.disk.used_bytes)
        if metrics and metrics.disk and metrics.disk.total_bytes is not None and metrics.disk.used_bytes is not None else None,
        "disk_total_text": format_bytes(metrics.disk.total_bytes) if metrics and metrics.disk else "",
        "disk_used_text": format_bytes(metrics.disk.used_bytes) if metrics and metrics.disk else "",
        "disk_free_text": format_bytes(metrics.disk.total_bytes - metrics.disk.used_bytes)
        if metrics and metrics.disk and metrics.disk.total_bytes is not None and metrics.disk.used_bytes is not None else "",
        "ping_latency_ms": ping.latency_ms if ping and ping.data_available and ping.reachable else None,
        "ping_reachable": ping.reachable if ping and ping.data_available else None,
        "uptime_seconds": uptime,
        "uptime_text": format_duration(uptime) if uptime is not None else "—",
        "exporter_hostname": metrics.exporter_hostname if metrics else None,
        "last_seen_text": last_seen_text,
        "telemetry_state": telemetry_state,
    }


def build_server_detail(collector, server, now):
    health = collector.engine.get_health(server.id)
    item = build_server_item(server, health, now)
    if health is not None and health.state != ServerState.HEALTHY:
        started = health.state_since or now
        item["state_since"] = started
        item["state_started_text"] = fmt_ago(now - started)
        item["state_duration_text"] = format_duration(now - started)
    item["reason"] = health.reason if health else None
    item["value"] = health.value if health else None
    item["disks"] = None
    item["packet_loss_percent"] = None
    volumes = []
    if health is not None and health.metrics and health.metrics.disk and health.metrics.disk.volumes:
        for volume in health.metrics.disk.volumes:
            volumes.append({
                "name": volume["name"],
                "filesystem": volume.get("filesystem") or "",
                "label": volume.get("label") or "",
                "device": volume.get("device") or "",
                "used_percent": volume["used_percent"],
                "used_bytes": volume["used_bytes"],
                "free_bytes": volume["free_bytes"],
                "total_bytes": volume["total_bytes"],
                "used_text": format_bytes(volume["used_bytes"]),
                "free_text": format_bytes(volume["free_bytes"]),
                "total_text": format_bytes(volume["total_bytes"]),
                "status": volume.get("status") or "healthy",
            })
    item["volumes"] = volumes
    return item


def build_virt_lookup(virt_store):
    lookup = {}
    try:
        overview = virt_store.overview()
    except Exception:
        return lookup
    for dc in overview.get("datacenters", []):
        for cluster in dc.get("clusters", []):
            for host in cluster.get("hosts", []):
                host_key = host["name"].lower()
                lookup[host_key] = {
                    "kind": "host",
                    "host": host["name"],
                    "cluster": cluster["name"],
                    "datacenter": dc["name"],
                }
                lookup.setdefault(host.get("ip_address", ""), lookup[host_key])
                for vm in host.get("vms", []):
                    lookup[vm["name"].lower()] = {
                        "kind": "vm",
                        "host": host["name"],
                        "cluster": cluster["name"],
                        "datacenter": dc["name"],
                    }
                    if vm.get("ip_address"):
                        lookup.setdefault(vm["ip_address"], lookup[vm["name"].lower()])
    return lookup


def virt_info_for(item, virt_lookup):
    if not virt_lookup:
        return None
    return virt_lookup.get(item["hostname"].lower()) or virt_lookup.get(item["ip"])


def filter_servers_items(items, args, virt_lookup=None):
    query = (args.get("q") or "").strip().lower()
    status = args.get("status") or "all"
    site = (args.get("site") or "").strip()
    role = (args.get("role") or "").strip()
    os_name = (args.get("os") or "").strip()
    environment = (args.get("environment") or "").strip()
    datacenter = (args.get("datacenter") or "").strip()
    cluster = (args.get("cluster") or "").strip()
    virt_host = (args.get("host") or "").strip()
    node_type = (args.get("type") or "").strip()

    filtered = []
    for item in items:
        if query and query not in item["hostname"].lower() and query not in item["ip"].lower() and query not in item["display_name"].lower():
            continue
        if status != "all" and item["state"] != status:
            continue
        if site and item["site"] != site:
            continue
        if role and item["role"] != role:
            continue
        if os_name and item["os"] != os_name:
            continue
        if environment and item["environment"] != environment:
            continue
        if datacenter or cluster or virt_host or node_type:
            info = virt_info_for(item, virt_lookup)
            if datacenter and (not info or info["datacenter"] != datacenter):
                continue
            if cluster and (not info or info["cluster"] != cluster):
                continue
            if virt_host and (not info or info["host"] != virt_host):
                continue
            if node_type:
                if node_type == "virtual" and (not info or info["kind"] != "vm"):
                    continue
                if node_type == "physical" and info and info["kind"] == "vm":
                    continue
        filtered.append(item)
    return filtered


def sort_servers_items(items, sort):
    if sort == "severity":
        items.sort(key=lambda i: (_severity_key(i["state"]), i["hostname"].lower()))
    elif sort == "hostname":
        items.sort(key=lambda i: i["hostname"].lower())
    elif sort == "ip":
        items.sort(key=lambda i: _ip_key(i["ip"]))
    elif sort == "cpu":
        items.sort(key=lambda i: _desc(i["cpu_percent"]))
    elif sort == "memory":
        items.sort(key=lambda i: _desc(i["memory_percent"]))
    elif sort == "disk":
        items.sort(key=lambda i: _desc(i["disk_usage_percent"]))
    elif sort == "ping":
        items.sort(key=lambda i: _asc(i["ping_latency_ms"]))
    elif sort == "uptime":
        items.sort(key=lambda i: _desc(i["uptime_seconds"]))
    return items


def paginate_servers_items(items, page, per_page):
    page = max(1, min(page, 100000))
    per_page = max(1, min(per_page, 1000))
    start = (page - 1) * per_page
    return items[start:start + per_page]


def build_servers_payload(collector, settings, args, virt_lookup=None):
    now = time.time()
    inventory = enabled_servers(collector.inventory)
    items = [
        build_server_item(server, collector.engine.get_health(server.id), now)
        for server in inventory
    ]

    filtered = filter_servers_items(items, args, virt_lookup)
    sort = args.get("sort") if args.get("sort") in SORT_OPTIONS else "severity"
    sort_servers_items(filtered, sort)

    total = len(filtered)
    page = _int_arg(args, "page", 1, 1, 100000)
    per_page = _int_arg(args, "per_page", 50, 1, 1000)
    page_items = paginate_servers_items(filtered, page, per_page)

    return {
        "generated_at": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
        "items": page_items,
        "meta": {
            "sites": sorted({s.site for s in inventory if s.site}),
            "roles": sorted({s.role for s in inventory if s.role}),
            "oses": sorted({s.os for s in inventory if s.os}),
        },
    }


def build_alerts_payload(collector, settings, args):
    now = time.time()
    inventory = enabled_servers(collector.inventory)
    alerts = []
    for server in inventory:
        health = collector.engine.get_health(server.id)
        if health is None or health.state not in ATTENTION_STATES:
            continue
        started = health.state_since or now
        alerts.append({
            "server_id": server.id,
            "hostname": server.hostname,
            "ip": server.ip,
            "site": server.site,
            "role": server.role,
            "severity": health.state.value,
            "metric": health.reason or "Resource",
            "value": health.value,
            "message": _alert_message(health),
            "started_at": datetime.fromtimestamp(started, tz=timezone.utc).isoformat(),
            "started_text": fmt_ago(now - started),
            "duration_text": format_duration(now - started),
        })

    summary = {"active": len(alerts), "critical": 0, "warning": 0, "offline": 0}
    for alert in alerts:
        summary[alert["severity"]] = summary.get(alert["severity"], 0) + 1

    severity = args.get("severity") or "all"
    query = (args.get("q") or "").strip().lower()
    site = (args.get("site") or "").strip()
    role = (args.get("role") or "").strip()

    filtered = []
    for alert in alerts:
        if severity != "all" and alert["severity"] != severity:
            continue
        if query and query not in alert["hostname"].lower() and query not in alert["ip"].lower():
            continue
        if site and alert["site"] != site:
            continue
        if role and alert["role"] != role:
            continue
        filtered.append(alert)

    filtered.sort(key=lambda a: (SEVERITY_ORDER[ServerState(a["severity"])], a["started_at"]))

    return {
        "generated_at": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        "summary": summary,
        "items": filtered,
        "meta": {
            "sites": sorted({a["site"] for a in alerts if a["site"]}),
            "roles": sorted({a["role"] for a in alerts if a["role"]}),
        },
    }


def _alert_message(health):
    if health.state == ServerState.OFFLINE:
        return "Unreachable"
    if health.reason == "Ping":
        return "Ping latency {0}".format(health.value or "—")
    return "{0} usage {1}".format(health.reason or "Resource", health.value or "—")


def _desc(value):
    if value is None:
        return float("-inf")
    return value


def _asc(value):
    if value is None:
        return float("inf")
    return value


def _ip_key(ip):
    try:
        return tuple(int(part) for part in ip.split("."))
    except ValueError:
        return ()


def _int_arg(args, name, default, min_value, max_value):
    try:
        value = int(args.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(min_value, min(value, max_value))
