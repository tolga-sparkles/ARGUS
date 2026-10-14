import math
import time
from datetime import datetime, timezone

from infrastructure.models import CollectResult, DiskInfo, PingInfo, Server, ServerMetrics


def demo_inventory():
    specs = [
        ("db-srv-01", "DB-SRV-01", "Production Database 01", "Database"),
        ("db-srv-02", "DB-SRV-02", "Production Database 02", "Database"),
        ("db-srv-03", "DB-SRV-03", "Production Database 03", "Database"),
        ("db-srv-04", "DB-SRV-04", "Reporting Database", "Database"),
        ("app-srv-01", "APP-SRV-01", "Application Node 01", "Application"),
        ("app-srv-02", "APP-SRV-02", "Application Node 02", "Application"),
        ("app-srv-03", "APP-SRV-03", "Application Node 03", "Application"),
        ("app-srv-04", "APP-SRV-04", "Application Node 04", "Application"),
        ("app-srv-05", "APP-SRV-05", "Application Node 05", "Application"),
        ("web-srv-01", "WEB-SRV-01", "Web Frontend 01", "Web"),
        ("web-srv-02", "WEB-SRV-02", "Web Frontend 02", "Web"),
        ("web-srv-03", "WEB-SRV-03", "Web Frontend 03", "Web"),
        ("file-srv-01", "FILE-SRV-01", "File Storage 01", "File"),
        ("file-srv-02", "FILE-SRV-02", "File Storage 02", "File"),
        ("infra-srv-01", "INFRA-SRV-01", "Infrastructure Services 01", "Infrastructure"),
        ("infra-srv-02", "INFRA-SRV-02", "Infrastructure Services 02", "Infrastructure"),
    ]
    servers = []
    for index, (sid, hostname, display, role) in enumerate(specs):
        servers.append(Server(
            id=sid,
            hostname=hostname,
            display_name=display,
            ip="192.0.2.{0}".format(11 + index),
            site="Main DC" if index % 4 else "DR DC",
            role=role,
            environment="Production" if index % 3 else "Staging",
            os="Windows" if index % 2 else "Linux",
            enabled=True,
        ))
    return servers


def demo_volumes(os_name):
    if os_name == "Windows":
        return [
            {"name": "C:", "filesystem": "NTFS", "label": "System", "device": "Disk 0",
             "used_percent": 68.0, "used_bytes": 136 * 10**9, "free_bytes": 64 * 10**9,
             "total_bytes": 200 * 10**9, "status": "healthy"},
            {"name": "D:", "filesystem": "NTFS", "label": "Data", "device": "Disk 0",
             "used_percent": 42.0, "used_bytes": 420 * 10**9, "free_bytes": 580 * 10**9,
             "total_bytes": 1000 * 10**9, "status": "healthy"},
        ]
    return [
        {"name": "/", "filesystem": "ext4", "label": "", "device": "/dev/sda",
         "used_percent": 61.0, "used_bytes": 61 * 10**9, "free_bytes": 39 * 10**9,
         "total_bytes": 100 * 10**9, "status": "healthy"},
        {"name": "/var", "filesystem": "xfs", "label": "", "device": "/dev/sda",
         "used_percent": 74.0, "used_bytes": 148 * 10**9, "free_bytes": 52 * 10**9,
         "total_bytes": 200 * 10**9, "status": "warning"},
        {"name": "/data", "filesystem": "ext4", "label": "", "device": "/dev/sdb",
         "used_percent": 32.0, "used_bytes": 320 * 10**9, "free_bytes": 680 * 10**9,
         "total_bytes": 1000 * 10**9, "status": "healthy"},
    ]


class DemoProvider:
    def __init__(self, settings):
        self.settings = settings
        self._started = time.time()

    def collect(self, servers):
        now = time.time()
        metrics = {}
        for index, server in enumerate(servers):
            metrics[server.id] = self._server_metrics(server, index, now)
        return CollectResult(
            ok=True,
            collected_at=now,
            prometheus_connected=False,
            ping_data_seen=True,
            metrics=metrics,
            query_count=0,
            duration_ms=round((time.time() - now) * 1000.0, 1),
        )

    def _server_metrics(self, server, index, now):
        profile = self._profile(server.id)
        wave = math.sin(now / 120.0 + profile["phase"])
        ping = PingInfo(data_available=True, reachable=True, latency_ms=round(2.0 + profile["base_latency"] + 4 * abs(wave), 1))

        cpu = round(profile["base_cpu"] + 5 * wave, 1)
        memory = round(profile["base_memory"] + 4 * math.sin(now / 240.0 + profile["phase"] * 2), 1)
        disk = round(profile["base_disk"] + 2 * math.sin(now / 600.0), 1)
        uptime = round(profile["base_uptime"] + (now - self._started))

        scenario = index % 16
        if scenario == 2:
            memory = round(95.0 + 2 * abs(wave), 1)
        elif scenario == 5:
            cpu = round(95.5 + 2 * abs(wave), 1)
        elif scenario == 8:
            disk = round(95.0 + 2 * abs(wave), 1)
        elif scenario == 11:
            ping.reachable = True
            ping.latency_ms = round(170 + 20 * abs(wave), 1)
        elif scenario == 13:
            ping.reachable = False
            ping.latency_ms = None

        telemetry_state = "stale" if not ping.reachable else "online"

        return ServerMetrics(
            server_id=server.id,
            ping=ping,
            cpu_percent=cpu,
            memory_percent=memory,
            disk=DiskInfo(
                highest_usage_percent=disk,
                total_bytes=1000 * 10**9,
                used_bytes=round(1000 * 10**9 * disk / 100.0),
                volumes=demo_volumes(server.os),
            ),
            uptime_seconds=uptime,
            last_seen=datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
            telemetry_state=telemetry_state,
            telemetry_age_seconds=round(now - max(now - 5, self._started), 1),
        )

    def _profile(self, server_id):
        seed = 0
        for char in server_id:
            seed = (seed * 31 + ord(char)) % 100003
        return {
            "phase": (seed % 628) / 100.0,
            "base_cpu": 18 + seed % 40,
            "base_memory": 35 + (seed // 7) % 35,
            "base_disk": 25 + (seed // 13) % 45,
            "base_latency": 1 + seed % 12,
            "base_uptime": 86400 * (3 + seed % 60),
        }
