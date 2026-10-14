import math
import time
from datetime import datetime, timedelta, timezone

from infrastructure.incidents import fmt_clock, fmt_date
from infrastructure.snapshot import format_duration

ANCHOR = time.time()

SERVERS = [
    {
        "id": "db-srv-01", "hostname": "DB-SRV-01", "display_name": "Production Database 01",
        "ip": "192.0.2.3", "site": "Main DC", "role": "Database", "environment": "Production",
        "os": "Windows Server", "state": "healthy",
        "cpu": 34.0, "mem": 68.0, "disk": 57.0, "ping": 2.1,
        "disks": [{"name": "C:", "usage_percent": 57.0}, {"name": "D:", "usage_percent": 41.0}],
        "uptime": 47 * 86400 + 18 * 3600,
    },
    {
        "id": "db-srv-02", "hostname": "DB-SRV-02", "display_name": "Production Database 02",
        "ip": "192.0.2.4", "site": "Main DC", "role": "Database", "environment": "Production",
        "os": "Windows Server", "state": "warning", "reason": "Memory", "value": "84%", "duration_sec": 7 * 60,
        "cpu": 47.0, "mem": 84.0, "disk": 62.0, "ping": 2.0,
        "disks": [{"name": "C:", "usage_percent": 62.0}, {"name": "D:", "usage_percent": 40.0}],
        "uptime": 21 * 86400 + 6 * 3600,
    },
    {
        "id": "db-lnx-01", "hostname": "DB-LNX-01", "display_name": "Reporting Database",
        "ip": "192.0.2.5", "site": "Main DC", "role": "Database", "environment": "Production",
        "os": "Linux", "state": "healthy",
        "cpu": 41.0, "mem": 59.0, "disk": 48.0, "ping": 2.6,
        "disks": [{"name": "/", "usage_percent": 48.0}, {"name": "/data", "usage_percent": 33.0}],
        "uptime": 63 * 86400,
    },
    {
        "id": "app-srv-01", "hostname": "APP-SRV-01", "display_name": "Core Application 01",
        "ip": "192.0.2.7", "site": "Main DC", "role": "Application", "environment": "Production",
        "os": "Windows Server", "state": "critical", "reason": "Memory", "value": "94%", "duration_sec": 4 * 60 + 32,
        "cpu": 71.0, "mem": 94.0, "disk": 58.0, "ping": 3.2,
        "disks": [{"name": "C:", "usage_percent": 58.0}, {"name": "D:", "usage_percent": 49.0}],
        "uptime": 12 * 86400 + 4 * 3600,
    },
    {
        "id": "app-srv-02", "hostname": "APP-SRV-02", "display_name": "Core Application 02",
        "ip": "192.0.2.8", "site": "Main DC", "role": "Application", "environment": "Production",
        "os": "Windows Server", "state": "healthy",
        "cpu": 36.0, "mem": 55.0, "disk": 44.0, "ping": 2.4,
        "disks": [{"name": "C:", "usage_percent": 44.0}, {"name": "D:", "usage_percent": 29.0}],
        "uptime": 18 * 86400,
    },
    {
        "id": "app-lnx-01", "hostname": "APP-LNX-01", "display_name": "Application Services",
        "ip": "192.0.2.9", "site": "Main DC", "role": "Application", "environment": "Production",
        "os": "Linux", "state": "healthy",
        "cpu": 27.0, "mem": 48.0, "disk": 39.0, "ping": 2.0,
        "disks": [{"name": "/", "usage_percent": 39.0}, {"name": "/data", "usage_percent": 26.0}],
        "uptime": 34 * 86400,
    },
    {
        "id": "app-lnx-02", "hostname": "APP-LNX-02", "display_name": "Integration Services",
        "ip": "192.0.2.10", "site": "Main DC", "role": "Application", "environment": "Production",
        "os": "Linux", "state": "healthy",
        "cpu": 22.0, "mem": 45.0, "disk": 33.0, "ping": 2.2,
        "disks": [{"name": "/", "usage_percent": 33.0}, {"name": "/data", "usage_percent": 21.0}],
        "uptime": 26 * 86400,
    },
    {
        "id": "web-srv-01", "hostname": "WEB-SRV-01", "display_name": "Corporate Web 01",
        "ip": "192.0.2.11", "site": "Main DC", "role": "Web", "environment": "Production",
        "os": "Linux", "state": "healthy",
        "cpu": 18.0, "mem": 42.0, "disk": 31.0, "ping": 1.4,
        "disks": [{"name": "/", "usage_percent": 31.0}, {"name": "/var", "usage_percent": 24.0}],
        "uptime": 41 * 86400,
    },
    {
        "id": "web-srv-02", "hostname": "WEB-SRV-02", "display_name": "Corporate Web 02",
        "ip": "192.0.2.12", "site": "Main DC", "role": "Web", "environment": "Production",
        "os": "Linux", "state": "healthy",
        "cpu": 15.0, "mem": 39.0, "disk": 28.0, "ping": 1.6,
        "disks": [{"name": "/", "usage_percent": 28.0}, {"name": "/var", "usage_percent": 22.0}],
        "uptime": 41 * 86400,
    },
    {
        "id": "web-srv-03", "hostname": "WEB-SRV-03", "display_name": "Internal Portal",
        "ip": "192.0.2.13", "site": "Main DC", "role": "Web", "environment": "Production",
        "os": "Windows Server", "state": "healthy",
        "cpu": 21.0, "mem": 46.0, "disk": 35.0, "ping": 1.9,
        "disks": [{"name": "C:", "usage_percent": 35.0}, {"name": "D:", "usage_percent": 18.0}],
        "uptime": 9 * 86400,
    },
    {
        "id": "file-srv-01", "hostname": "FILE-SRV-01", "display_name": "Corporate File Server",
        "ip": "192.0.2.14", "site": "Main DC", "role": "File", "environment": "Production",
        "os": "Windows Server", "state": "healthy",
        "cpu": 14.0, "mem": 44.0, "disk": 66.0, "ping": 1.8,
        "disks": [{"name": "C:", "usage_percent": 31.0}, {"name": "D:", "usage_percent": 66.0}],
        "uptime": 52 * 86400,
    },
    {
        "id": "file-srv-02", "hostname": "FILE-SRV-02", "display_name": "Archive Storage",
        "ip": "192.0.2.15", "site": "Main DC", "role": "File", "environment": "Production",
        "os": "Windows Server", "state": "warning", "reason": "Disk", "value": "86%", "duration_sec": 18 * 60,
        "cpu": 24.0, "mem": 61.0, "disk": 86.0, "ping": 2.8,
        "disks": [{"name": "C:", "usage_percent": 43.0}, {"name": "D:", "usage_percent": 86.0}],
        "uptime": 30 * 86400,
    },
    {
        "id": "dns-srv-01", "hostname": "DNS-SRV-01", "display_name": "Primary DNS",
        "ip": "192.0.2.16", "site": "Main DC", "role": "Infrastructure", "environment": "Production",
        "os": "Windows Server", "state": "healthy",
        "cpu": 9.0, "mem": 38.0, "disk": 41.0, "ping": 1.2,
        "disks": [{"name": "C:", "usage_percent": 41.0}],
        "uptime": 77 * 86400,
    },
    {
        "id": "ad-srv-01", "hostname": "AD-SRV-01", "display_name": "Domain Controller 01",
        "ip": "192.0.2.17", "site": "Main DC", "role": "Infrastructure", "environment": "Production",
        "os": "Windows Server", "state": "healthy",
        "cpu": 12.0, "mem": 54.0, "disk": 46.0, "ping": 1.1,
        "disks": [{"name": "C:", "usage_percent": 46.0}],
        "uptime": 83 * 86400,
    },
    {
        "id": "vm-host-01", "hostname": "VM-HOST-01", "display_name": "Virtualization Host 01",
        "ip": "192.0.2.18", "site": "Main DC", "role": "Infrastructure", "environment": "Production",
        "os": "Windows Server", "state": "offline", "reason": "Host unreachable", "value": "6m", "duration_sec": 6 * 60,
        "cpu": None, "mem": None, "disk": None, "ping": None,
        "disks": None, "uptime": None,
    },
    {
        "id": "backup-srv-01", "hostname": "BACKUP-SRV-01", "display_name": "Backup Server",
        "ip": "192.0.2.19", "site": "DR DC", "role": "Infrastructure", "environment": "Production",
        "os": "Linux", "state": "healthy",
        "cpu": 23.0, "mem": 51.0, "disk": 72.0, "ping": 6.8,
        "disks": [{"name": "/", "usage_percent": 46.0}, {"name": "/backup", "usage_percent": 72.0}],
        "uptime": 19 * 86400,
    },
]

RECENT_EVENTS = [
    {"minutes_ago": 2, "server": "DB-SRV-02", "message": "Memory entered warning state", "severity": "warning"},
    {"minutes_ago": 6, "server": "FILE-SRV-02", "message": "Disk entered warning state", "severity": "warning"},
    {"minutes_ago": 9, "server": "APP-SRV-01", "message": "Memory entered critical state", "severity": "critical"},
    {"minutes_ago": 14, "server": "VM-HOST-01", "message": "Host became unreachable", "severity": "offline"},
    {"minutes_ago": 22, "server": "WEB-SRV-02", "message": "CPU returned to normal", "severity": "healthy"},
    {"minutes_ago": 33, "server": "BACKUP-SRV-01", "message": "Backup server telemetry recovered", "severity": "healthy"},
]

HISTORY = [
    {
        "id": "demo-1", "server_id": "app-srv-01", "status": "active",
        "severity": "critical", "reason": "Memory", "peak_value": "94%",
        "started_sec_ago": 4 * 60 + 32, "ended_sec_ago": None,
        "timeline": [
            ("Memory entered warning state", "warning", "89%"),
            ("Memory entered critical state", "critical", "94%"),
        ],
    },
    {
        "id": "demo-2", "server_id": "db-srv-02", "status": "active",
        "severity": "warning", "reason": "Memory", "peak_value": "84%",
        "started_sec_ago": 7 * 60, "ended_sec_ago": None,
        "timeline": [
            ("Memory entered warning state", "warning", "84%"),
        ],
    },
    {
        "id": "demo-3", "server_id": "vm-host-01", "status": "active",
        "severity": "offline", "reason": "Unreachable", "peak_value": None,
        "started_sec_ago": 6 * 60, "ended_sec_ago": None,
        "timeline": [
            ("Host became unreachable", "offline", None),
        ],
    },
    {
        "id": "demo-4", "server_id": "web-srv-02", "status": "recovered",
        "severity": "warning", "reason": "CPU", "peak_value": "87%",
        "started_sec_ago": 40 * 60, "ended_sec_ago": 33 * 60 + 46,
        "timeline": [
            ("CPU entered warning state", "warning", "87%"),
            ("CPU returned to normal", "healthy", "61%"),
        ],
    },
    {
        "id": "demo-5", "server_id": "db-lnx-01", "status": "recovered",
        "severity": "critical", "reason": "Memory", "peak_value": "92%",
        "started_sec_ago": 3 * 3600, "ended_sec_ago": 2 * 3600 + 38 * 60,
        "timeline": [
            ("Memory entered warning state", "warning", "86%"),
            ("Memory entered critical state", "critical", "92%"),
            ("Memory returned to normal", "healthy", "70%"),
        ],
    },
    {
        "id": "demo-6", "server_id": "file-srv-01", "status": "recovered",
        "severity": "warning", "reason": "Disk", "peak_value": "84%",
        "started_sec_ago": 5 * 3600, "ended_sec_ago": 4 * 3600 + 51 * 60,
        "timeline": [
            ("Disk entered warning state", "warning", "84%"),
            ("Disk returned to normal", "healthy", "63%"),
        ],
    },
    {
        "id": "demo-7", "server_id": "dns-srv-01", "status": "recovered",
        "severity": "offline", "reason": "Unreachable", "peak_value": None,
        "started_sec_ago": 26 * 3600, "ended_sec_ago": 25 * 3600 + 48 * 60,
        "timeline": [
            ("Host became unreachable", "offline", None),
            ("Host recovered", "healthy", None),
        ],
    },
    {
        "id": "demo-8", "server_id": "backup-srv-01", "status": "recovered",
        "severity": "no_telemetry", "reason": "Telemetry", "peak_value": None,
        "started_sec_ago": 22 * 3600, "ended_sec_ago": 21 * 3600 + 50 * 60,
        "timeline": [
            ("Exporter telemetry lost", "no_telemetry", None),
            ("Telemetry restored", "healthy", None),
        ],
    },
]

SERVER_BY_ID = {srv["id"]: srv for srv in SERVERS}


def _phase(server_id):
    seed = 0
    for char in server_id:
        seed = (seed * 31 + ord(char)) % 100003
    return (seed % 628) / 100.0


def _now():
    return time.time()


def _iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _item(server, now):
    offline = server["state"] == "offline"
    if offline:
        return {
            "id": server["id"],
            "hostname": server["hostname"],
            "display_name": server["display_name"],
            "ip": server["ip"],
            "site": server["site"],
            "role": server["role"],
            "environment": server["environment"],
            "os": server["os"],
            "state": "offline",
            "cpu_percent": None,
            "memory_percent": None,
            "disk_usage_percent": None,
            "ping_latency_ms": None,
            "ping_reachable": False,
            "uptime_seconds": None,
            "uptime_text": "—",
            "last_seen_text": "—",
            "telemetry_state": "absent",
        }

    if server["state"] == "healthy":
        cpu = round(server["cpu"] + 3.0 * math.sin(now / 90.0 + _phase(server["id"])), 1)
        ping = round(server["ping"] + 0.3 * math.sin(now / 47.0 + _phase(server["id"])), 1)
    else:
        cpu = server["cpu"]
        ping = server["ping"]

    uptime = int(server["uptime"] + (now - ANCHOR))

    return {
        "id": server["id"],
        "hostname": server["hostname"],
        "display_name": server["display_name"],
        "ip": server["ip"],
        "site": server["site"],
        "role": server["role"],
        "environment": server["environment"],
        "os": server["os"],
        "state": server["state"],
        "cpu_percent": cpu,
        "memory_percent": server["mem"],
        "disk_usage_percent": server["disk"],
        "ping_latency_ms": ping,
        "ping_reachable": True,
        "uptime_seconds": uptime,
        "uptime_text": format_duration(uptime),
        "last_seen_text": "3s ago",
        "telemetry_state": "online",
    }


def build_servers(args):
    now = _now()
    items = [_item(server, now) for server in SERVERS]

    query = (args.get("q") or "").strip().lower()
    status = args.get("status") or "all"
    site = (args.get("site") or "").strip()
    role = (args.get("role") or "").strip()
    os_name = (args.get("os") or "").strip()

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
        filtered.append(item)

    from infrastructure.fleet import SORT_OPTIONS, _severity_key
    sort = args.get("sort") if args.get("sort") in SORT_OPTIONS else "severity"
    if sort == "severity":
        filtered.sort(key=lambda i: (_severity_key(i["state"]), i["hostname"].lower()))
    elif sort == "hostname":
        filtered.sort(key=lambda i: i["hostname"].lower())
    elif sort == "ip":
        filtered.sort(key=lambda i: tuple(int(p) for p in i["ip"].split(".")))
    elif sort == "cpu":
        filtered.sort(key=lambda i: i["cpu_percent"] if i["cpu_percent"] is not None else float("-inf"), reverse=True)
    elif sort == "memory":
        filtered.sort(key=lambda i: i["memory_percent"] if i["memory_percent"] is not None else float("-inf"), reverse=True)
    elif sort == "disk":
        filtered.sort(key=lambda i: i["disk_usage_percent"] if i["disk_usage_percent"] is not None else float("-inf"), reverse=True)
    elif sort == "ping":
        filtered.sort(key=lambda i: i["ping_latency_ms"] if i["ping_latency_ms"] is not None else float("inf"))
    elif sort == "uptime":
        filtered.sort(key=lambda i: i["uptime_seconds"] if i["uptime_seconds"] is not None else float("-inf"), reverse=True)

    total = len(filtered)
    try:
        page = max(1, int(args.get("page", 1)))
    except ValueError:
        page = 1
    try:
        per_page = max(1, min(int(args.get("per_page", 50)), 1000))
    except ValueError:
        per_page = 50
    start = (page - 1) * per_page

    return {
        "generated_at": _iso(now),
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
        "items": filtered[start:start + per_page],
        "meta": {
            "sites": sorted({srv["site"] for srv in SERVERS}),
            "roles": sorted({srv["role"] for srv in SERVERS}),
            "oses": sorted({srv["os"] for srv in SERVERS}),
        },
    }


def build_detail(server_id):
    server = SERVER_BY_ID.get(server_id)
    if server is None:
        return None
    now = _now()
    item = _item(server, now)
    if server["state"] != "healthy":
        item["reason"] = server.get("reason")
        item["value"] = server.get("value")
        item["state_since"] = now - server.get("duration_sec", 0)
        item["state_started_text"] = "{0} ago".format(_ago(server.get("duration_sec", 0)))
        item["state_duration_text"] = format_duration(server.get("duration_sec", 0))
    item["disks"] = server.get("disks")
    item["packet_loss_percent"] = 0.0 if server["state"] != "offline" else None
    item["volumes"] = _demo_volumes(server["os"]) if server["state"] != "offline" else []
    return item


def _demo_volumes(os_name):
    if os_name == "Windows":
        return [
            {"name": "C:", "filesystem": "NTFS", "label": "System", "device": "Disk 0",
             "used_percent": 68.0, "used_bytes": 136 * 10**9, "free_bytes": 64 * 10**9,
             "total_bytes": 200 * 10**9, "used_text": "126.7 GB", "free_text": "59.6 GB",
             "total_text": "186.3 GB", "status": "healthy"},
            {"name": "D:", "filesystem": "NTFS", "label": "Data", "device": "Disk 0",
             "used_percent": 42.0, "used_bytes": 420 * 10**9, "free_bytes": 580 * 10**9,
             "total_bytes": 1000 * 10**9, "used_text": "391.2 GB", "free_text": "540.2 GB",
             "total_text": "931.3 GB", "status": "healthy"},
        ]
    return [
        {"name": "/", "filesystem": "ext4", "label": "", "device": "/dev/sda",
         "used_percent": 61.0, "used_bytes": 61 * 10**9, "free_bytes": 39 * 10**9,
         "total_bytes": 100 * 10**9, "used_text": "56.8 GB", "free_text": "36.3 GB",
         "total_text": "93.1 GB", "status": "healthy"},
        {"name": "/var", "filesystem": "xfs", "label": "", "device": "/dev/sda",
         "used_percent": 74.0, "used_bytes": 148 * 10**9, "free_bytes": 52 * 10**9,
         "total_bytes": 200 * 10**9, "used_text": "137.8 GB", "free_text": "48.4 GB",
         "total_text": "186.3 GB", "status": "warning"},
        {"name": "/data", "filesystem": "ext4", "label": "", "device": "/dev/sdb",
         "used_percent": 32.0, "used_bytes": 320 * 10**9, "free_bytes": 680 * 10**9,
         "total_bytes": 1000 * 10**9, "used_text": "298.0 GB", "free_text": "633.3 GB",
         "total_text": "931.3 GB", "status": "healthy"},
    ]


def _ago(seconds):
    seconds = int(seconds)
    if seconds < 60:
        return "{0}s".format(seconds)
    if seconds < 3600:
        return "{0}m".format(seconds // 60)
    return "{0}h".format(seconds // 3600)


def build_overview():
    now = _now()
    items = {server["id"]: _item(server, now) for server in SERVERS}
    summary = {"total": 16, "healthy": 12, "warning": 2, "critical": 1, "offline": 1, "no_telemetry": 0}

    attention = []
    for server in SERVERS:
        if server["state"] in ("offline", "critical", "warning"):
            duration = format_duration(server["duration_sec"])
            if server["state"] == "offline":
                attention.append({
                    "id": server["id"], "hostname": server["hostname"], "ip": server["ip"],
                    "state": "offline", "reason": server["reason"], "value": duration, "duration_text": "",
                })
            else:
                attention.append({
                    "id": server["id"], "hostname": server["hostname"], "ip": server["ip"],
                    "state": server["state"], "reason": server["reason"], "value": server["value"],
                    "duration_text": duration,
                })
    attention.sort(key=lambda a: (
        {"offline": 0, "critical": 1, "warning": 2}[a["state"]],
        -SERVER_BY_ID[a["id"]].get("duration_sec", 0),
    ))

    pressure = {
        "highest_cpu": {
            "server_id": "app-srv-01", "hostname": "APP-SRV-01",
            "value": items["app-srv-01"]["cpu_percent"], "value_text": "{0}%".format(round(items["app-srv-01"]["cpu_percent"])),
            "severity": "healthy",
        },
        "highest_memory": {
            "server_id": "app-srv-01", "hostname": "APP-SRV-01",
            "value": 94.0, "value_text": "94%", "severity": "critical",
        },
        "lowest_disk_free": {
            "server_id": "file-srv-02", "hostname": "FILE-SRV-02",
            "value": 14.0, "value_text": "14%", "severity": "warning",
        },
        "highest_ping": {
            "server_id": "backup-srv-01", "hostname": "BACKUP-SRV-01",
            "value": items["backup-srv-01"]["ping_latency_ms"], "value_text": "{0} ms".format(items["backup-srv-01"]["ping_latency_ms"]),
            "severity": "healthy",
        },
    }

    group_defs = {
        "Database": {"total": 3, "healthy": 2, "warning": 1, "critical": 0, "offline": 0},
        "Application": {"total": 4, "healthy": 3, "warning": 0, "critical": 1, "offline": 0},
        "Web": {"total": 3, "healthy": 3, "warning": 0, "critical": 0, "offline": 0},
        "File": {"total": 2, "healthy": 1, "warning": 1, "critical": 0, "offline": 0},
        "Infrastructure": {"total": 4, "healthy": 3, "warning": 0, "critical": 0, "offline": 1},
    }
    groups = [
        {
            "name": name, "total": values["total"], "healthy": values["healthy"],
            "warning": values["warning"], "critical": values["critical"],
            "offline": values["offline"], "no_telemetry": 0,
        }
        for name, values in group_defs.items()
    ]

    events = []
    for entry in RECENT_EVENTS:
        ts = now - entry["minutes_ago"] * 60
        events.append({
            "at": _iso(ts),
            "time_text": fmt_clock(ts),
            "server": entry["server"],
            "message": entry["message"],
            "severity": entry["severity"],
        })

    return {
        "generated_at": _iso(now),
        "data_state": "ok",
        "demo_mode": True,
        "summary": summary,
        "attention": attention,
        "resource_pressure": pressure,
        "groups": groups,
        "collector_health": {
            "prometheus": "management",
            "inventory": {"state": "loaded", "count": 16},
            "ping_probe": "simulated",
            "metrics_age_sec": 0,
            "labels": {
                "prometheus": "Data Provider",
                "inventory": "Inventory",
                "ping_probe": "Ping Engine",
                "metrics": "Refresh",
            },
        },
        "recent_events": events,
    }


def _alert_message(server):
    if server["state"] == "offline":
        return "Host unreachable"
    if server["reason"] == "Ping":
        return "Ping latency {0}".format(server["value"])
    return "{0} usage {1}".format(server["reason"], server["value"])


def build_alerts(args):
    now = _now()
    alerts = []
    for server in SERVERS:
        if server["state"] not in ("offline", "critical", "warning"):
            continue
        duration = format_duration(server["duration_sec"])
        alerts.append({
            "server_id": server["id"],
            "hostname": server["hostname"],
            "ip": server["ip"],
            "site": server["site"],
            "role": server["role"],
            "severity": server["state"],
            "metric": server["reason"],
            "value": server["value"],
            "message": _alert_message(server),
            "started_at": _iso(now - server["duration_sec"]),
            "started_text": _ago(server["duration_sec"]) + " ago",
            "duration_text": duration,
        })

    summary = {"active": 4, "critical": 1, "warning": 2, "offline": 1}

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
    filtered.sort(key=lambda a: {"offline": 0, "critical": 1, "warning": 2}[a["severity"]])

    return {
        "generated_at": _iso(now),
        "summary": summary,
        "items": filtered,
        "meta": {
            "sites": sorted({a["site"] for a in alerts}),
            "roles": sorted({a["role"] for a in alerts}),
        },
    }


def build_history(args):
    from infrastructure.incidents import HISTORY_RANGES
    now = _now()

    records = []
    for entry in HISTORY:
        server = SERVER_BY_ID.get(entry["server_id"], {})
        started = now - entry["started_sec_ago"]
        ended = None if entry["ended_sec_ago"] is None else now - entry["ended_sec_ago"]
        duration_sec = None if ended is None else entry["started_sec_ago"] - entry["ended_sec_ago"]
        timeline = []
        for index, (message, severity, value) in enumerate(entry["timeline"]):
            ts = started + index * 30
            timeline.append({
                "t": ts,
                "time_text": fmt_clock(ts),
                "severity": severity,
                "message": message,
                "value": value,
            })
        records.append({
            "id": entry["id"],
            "server_id": entry["server_id"],
            "hostname": server.get("hostname", entry["server_id"]),
            "ip": server.get("ip", ""),
            "site": server.get("site", ""),
            "role": server.get("role", ""),
            "severity": entry["severity"],
            "reason": entry["reason"],
            "peak_value": entry["peak_value"],
            "status": entry["status"],
            "started_at": started,
            "ended_at": ended,
            "duration_sec": duration_sec,
            "timeline": timeline,
        })

    query = (args.get("q") or "").strip().lower()
    status = args.get("status") or "all"
    severity = args.get("severity") or "all"
    range_key = args.get("range") or "all"
    since = now - HISTORY_RANGES[range_key] if range_key in HISTORY_RANGES else None

    filtered = []
    for record in records:
        if status != "all" and record["status"] != status:
            continue
        if severity != "all" and record["severity"] != severity:
            continue
        if query and query not in (record["hostname"] + " " + record["ip"] + " " + record["server_id"]).lower():
            continue
        if since is not None and record["started_at"] < since:
            continue
        filtered.append(record)

    filtered.sort(key=lambda r: r["started_at"], reverse=True)

    total = len(filtered)
    try:
        page = max(1, int(args.get("page", 1)))
    except ValueError:
        page = 1
    try:
        per_page = max(1, min(int(args.get("per_page", 25)), 100))
    except ValueError:
        per_page = 25
    start = (page - 1) * per_page

    items = []
    for record in filtered[start:start + per_page]:
        items.append({
            "id": record["id"],
            "server_id": record["server_id"],
            "hostname": record["hostname"],
            "ip": record["ip"],
            "site": record["site"],
            "role": record["role"],
            "severity": record["severity"],
            "reason": record["reason"],
            "peak_value": record["peak_value"],
            "status": record["status"],
            "started_at": _iso(record["started_at"]),
            "started_text": fmt_date(record["started_at"]),
            "ended_at": _iso(record["ended_at"]) if record["ended_at"] else None,
            "ended_text": fmt_date(record["ended_at"]) if record["ended_at"] else None,
            "duration_text": format_duration(record["duration_sec"]) if record["duration_sec"] is not None else None,
            "timeline": record["timeline"],
        })

    return {
        "generated_at": _iso(now),
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
        "items": items,
    }
