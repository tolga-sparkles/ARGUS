import re
import time
from collections import defaultdict
from datetime import datetime, timezone

import requests

from infrastructure.models import CollectResult, DiskInfo, PingInfo, ServerMetrics


class PrometheusUnavailable(Exception):
    pass


def _regex_escape(value):
    return re.escape(value).replace("\\.", "[.]")


def _ip_pattern(ip):
    if ":" in ip:
        return "^([[]{0}[]])(:[0-9]+)?$|^({0})(:[0-9]+)?$".format(_regex_escape(ip))
    return "^({0})(:[0-9]+)?$".format(_regex_escape(ip))


def _exact_pattern(value):
    return "^({0})$".format(_regex_escape(value))


def instance_ip(instance):
    if instance.startswith("["):
        end = instance.find("]")
        return instance[1:end] if end != -1 else instance
    if instance.count(":") > 1:
        return instance
    return instance.split(":", 1)[0]


class PrometheusProvider:
    def __init__(self, settings):
        self.settings = settings
        self.base_url = settings.prometheus_url
        self.timeout = settings.prometheus_timeout

    def _query(self, promql):
        resp = requests.get(
            f"{self.base_url}/api/v1/query",
            params={"query": promql},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        doc = resp.json()
        if doc.get("status") != "success":
            raise PrometheusUnavailable(str(doc.get("error", "query failed"))[:200])
        return doc.get("data", {}).get("result", [])

    def _targets(self, servers):
        exporter_patterns = []
        ping_patterns = []
        for srv in servers:
            if srv.prometheus_instance:
                exporter_patterns.append(_exact_pattern(srv.prometheus_instance))
            else:
                exporter_patterns.append(_ip_pattern(srv.ip))
            ping_patterns.append(_ip_pattern(srv.ip))
        return exporter_patterns, ping_patterns

    def _ping_job_filter(self):
        if not self.settings.ping_job:
            return ""
        return ',job="{0}"'.format(self.settings.ping_job)

    def collect(self, servers):
        s = self.settings
        started_ts = time.time()
        if not self.base_url:
            return CollectResult(
                ok=False,
                collected_at=started_ts,
                prometheus_connected=False,
                ping_data_seen=False,
                error="PROMETHEUS_URL not configured",
            )

        exporter_patterns, ping_patterns = self._targets(servers)
        exporter_filter = 'instance=~"{0}"'.format("|".join(exporter_patterns))
        ping_filter = 'instance=~"{0}"'.format("|".join(ping_patterns))
        ping_job = self._ping_job_filter()

        queries = {
            "ping": '{0}{{{1}{2}}}'.format(s.ping_metric, ping_filter, ping_job),
            "ping_latency": '{0}{{{1}{2}}}'.format(s.ping_latency_metric, ping_filter, ping_job),
            "ping_ts": 'timestamp({0}{{{1}{2}}})'.format(s.ping_metric, ping_filter, ping_job),
            "up": '{0}{{{1}}}'.format(s.up_metric, exporter_filter),
            "up_ts": 'timestamp({0}{{{1}}})'.format(s.up_metric, exporter_filter),
            "cpu": (
                "100 * (1 - ("
                "sum by (instance) (rate({0}{{mode=\"idle\",{1}}}[{3}]))"
                " / sum by (instance) (rate({0}{{{1}}}[{3}]))"
                " or "
                "sum by (instance) (rate({2}{{mode=\"idle\",{1}}}[{3}]))"
                " / sum by (instance) (rate({2}{{{1}}}[{3}]))"
                "))"
            ).format(
                s.cpu_idle_metric_linux,
                exporter_filter,
                s.cpu_idle_metric_windows,
                s.rate_window,
            ),
            "mem_avail": (
                "avg by (instance) ({0}{{{1}}} or {2}{{{1}}})"
            ).format(s.mem_avail_metric_linux, exporter_filter, s.mem_avail_metric_windows),
            "mem_total": (
                "avg by (instance) ({0}{{{1}}} or {2}{{{1}}})"
            ).format(s.mem_total_metric_linux, exporter_filter, s.mem_total_metric_windows),
            "disk": (
                "max by (instance) ("
                "(100 * (1 - ({0}{{fstype=~\"{4}\",mountpoint!~\"{5}\",{1}}}"
                " / {2}{{fstype=~\"{4}\",mountpoint!~\"{5}\",{1}}})))"
                " or "
                "(100 * (1 - ({6}{{volume!~\"{7}\",{1}}} / {3}{{volume!~\"{7}\",{1}}})))"
                ")"
            ).format(
                s.disk_free_metric_linux,
                exporter_filter,
                s.disk_size_metric_linux,
                s.disk_size_metric_windows,
                s.disk_linux_fstype,
                s.disk_linux_mountpoint_ignore,
                s.disk_free_metric_windows,
                s.disk_windows_volume_ignore,
            ),
            "disk_total": (
                "sum by (instance) ({0}{{fstype=~\"{3}\",mountpoint!~\"{4}\",{1}}}"
                " or {2}{{volume!~\"{5}\",{1}}})"
            ).format(
                s.disk_size_metric_linux,
                exporter_filter,
                s.disk_size_metric_windows,
                s.disk_linux_fstype,
                s.disk_linux_mountpoint_ignore,
                s.disk_windows_volume_ignore,
            ),
            "disk_free": (
                "sum by (instance) ({0}{{fstype=~\"{3}\",mountpoint!~\"{4}\",{1}}}"
                " or {2}{{volume!~\"{5}\",{1}}})"
            ).format(
                s.disk_free_metric_linux,
                exporter_filter,
                s.disk_free_metric_windows,
                s.disk_linux_fstype,
                s.disk_linux_mountpoint_ignore,
                s.disk_windows_volume_ignore,
            ),
            "disk_detail_size": (
                "{0}{{fstype=~\"{3}\",mountpoint!~\"{4}\",{1}}}"
                " or {2}{{volume!~\"{5}\",{1}}}"
            ).format(
                s.disk_size_metric_linux,
                exporter_filter,
                s.disk_size_metric_windows,
                s.disk_linux_fstype,
                s.disk_linux_mountpoint_ignore,
                s.disk_windows_volume_ignore,
            ),
            "disk_detail_free": (
                "{0}{{fstype=~\"{3}\",mountpoint!~\"{4}\",{1}}}"
                " or {2}{{volume!~\"{5}\",{1}}}"
            ).format(
                s.disk_free_metric_linux,
                exporter_filter,
                s.disk_free_metric_windows,
                s.disk_linux_fstype,
                s.disk_linux_mountpoint_ignore,
                s.disk_windows_volume_ignore,
            ),
            "disk_win_info": '{0}{{volume!~"{2}",{1}}}'.format(
                s.disk_info_metric_windows, exporter_filter, s.disk_windows_volume_ignore
            ),
            "cpu_cores": (
                "count by (instance) ({0}{{mode=\"idle\",{1}}} or {2}{{mode=\"idle\",{1}}})"
            ).format(s.cpu_idle_metric_linux, exporter_filter, s.cpu_idle_metric_windows),
            "uptime": (
                "(time() - {0}{{{1}}}) or (time() - {2}{{{1}}})"
            ).format(s.uptime_metric_linux, exporter_filter, s.uptime_metric_windows),
            "hostname": '{0}{{{1}}} or {2}{{{1}}}'.format(
                s.hostname_metric_linux, exporter_filter, s.hostname_metric_windows
            ),
            "net_rx": 'sum(rate({0}{{device!~"{3}",{2}}}[{4}]) or rate({1}{{{2}}}[{4}]))'.format(
                s.net_rx_metric_linux, s.net_rx_metric_windows, exporter_filter,
                s.net_device_ignore, s.rate_window,
            ),
            "net_tx": 'sum(rate({0}{{device!~"{3}",{2}}}[{4}]) or rate({1}{{{2}}}[{4}]))'.format(
                s.net_tx_metric_linux, s.net_tx_metric_windows, exporter_filter,
                s.net_device_ignore, s.rate_window,
            ),
        }

        family_data = {}
        prometheus_down = False
        query_count = 0
        for name, promql in queries.items():
            try:
                family_data[name] = self._query(promql)
                query_count += 1
            except requests.RequestException:
                prometheus_down = True
            except PrometheusUnavailable:
                prometheus_down = True
            except Exception:
                family_data[name] = []

        duration_ms = round((time.time() - started_ts) * 1000.0, 1)

        if prometheus_down:
            return CollectResult(
                ok=False,
                collected_at=started_ts,
                prometheus_connected=False,
                ping_data_seen=False,
                error="Prometheus connection failed",
                query_count=query_count,
                duration_ms=duration_ms,
            )

        now = started_ts
        instance_map = {}
        ip_map = {}
        for srv in servers:
            if srv.prometheus_instance:
                instance_map[srv.prometheus_instance] = srv
            else:
                instance_map[srv.ip] = srv
            ip_map[srv.ip] = srv

        by_ip = defaultdict(lambda: {
            "up": None,
            "up_ts": None,
            "ping_reachable": None,
            "ping_ts": None,
            "latency_ms": None,
            "cpu": None,
            "cpu_cores": None,
            "mem_avail": None,
            "mem_total": None,
            "disk_usage": None,
            "disk_total": None,
            "disk_free": None,
            "uptime": None,
            "hostname": None,
        })
        ping_data_seen = False

        for sample in family_data.get("ping", []):
            ip = instance_ip(sample.get("metric", {}).get("instance", ""))
            value = _sample_value(sample)
            if value is None:
                continue
            ping_data_seen = True
            cell = by_ip[ip]
            cell["ping_reachable"] = value > 0

        for sample in family_data.get("ping_ts", []):
            ip = instance_ip(sample.get("metric", {}).get("instance", ""))
            value = _sample_value(sample)
            if value is not None:
                by_ip[ip]["ping_ts"] = value

        for sample in family_data.get("ping_latency", []):
            ip = instance_ip(sample.get("metric", {}).get("instance", ""))
            value = _sample_value(sample)
            if value is None:
                continue
            by_ip[ip]["latency_ms"] = round(value * 1000.0, 1)

        for sample in family_data.get("up", []):
            ip = self._resolve_instance(sample.get("metric", {}).get("instance", ""), instance_map, ip_map)
            value = _sample_value(sample)
            if value is None:
                continue
            cell = by_ip[ip]
            cell["up"] = value > 0

        for sample in family_data.get("up_ts", []):
            ip = self._resolve_instance(sample.get("metric", {}).get("instance", ""), instance_map, ip_map)
            value = _sample_value(sample)
            if value is not None:
                by_ip[ip]["up_ts"] = value

        for sample in family_data.get("hostname", []):
            ip = self._resolve_instance(sample.get("metric", {}).get("instance", ""), instance_map, ip_map)
            labels = sample.get("metric", {})
            name = labels.get("nodename") or labels.get("hostname") or ""
            if name and by_ip[ip]["hostname"] is None:
                by_ip[ip]["hostname"] = name

        for sample in family_data.get("cpu", []):
            ip = self._resolve_instance(sample.get("metric", {}).get("instance", ""), instance_map, ip_map)
            value = _sample_value(sample)
            if value is not None:
                by_ip[ip]["cpu"] = _merge_value(by_ip[ip]["cpu"], value)

        for key in ("mem_avail", "mem_total", "disk", "disk_total", "disk_free", "cpu_cores", "uptime"):
            cell_key = "disk_usage" if key == "disk" else key
            for sample in family_data.get(key, []):
                ip = self._resolve_instance(sample.get("metric", {}).get("instance", ""), instance_map, ip_map)
                value = _sample_value(sample)
                if value is not None:
                    by_ip[ip][cell_key] = _merge_value(by_ip[ip][cell_key], value)

        volumes_by_ip = {}
        for sample in family_data.get("disk_detail_size", []):
            metric = sample.get("metric", {})
            ip = self._resolve_instance(metric.get("instance", ""), instance_map, ip_map)
            value = _sample_value(sample)
            if value is None:
                continue
            name = metric.get("mountpoint") or metric.get("volume") or ""
            if not name:
                continue
            volume = volumes_by_ip.setdefault(ip, {}).setdefault(name, {})
            volume["total"] = value
            volume["fs"] = metric.get("fstype") or ""
            volume["device"] = metric.get("device") or ""

        for sample in family_data.get("disk_detail_free", []):
            metric = sample.get("metric", {})
            ip = self._resolve_instance(metric.get("instance", ""), instance_map, ip_map)
            value = _sample_value(sample)
            if value is None:
                continue
            name = metric.get("mountpoint") or metric.get("volume") or ""
            if not name:
                continue
            volume = volumes_by_ip.setdefault(ip, {}).setdefault(name, {})
            volume["free"] = value

        for sample in family_data.get("disk_win_info", []):
            metric = sample.get("metric", {})
            ip = self._resolve_instance(metric.get("instance", ""), instance_map, ip_map)
            name = metric.get("volume") or ""
            if not name:
                continue
            volume = volumes_by_ip.setdefault(ip, {}).setdefault(name, {})
            volume["fs"] = metric.get("filesystem") or volume.get("fs") or ""
            volume["label"] = metric.get("volume_name") or ""
            if metric.get("disk"):
                volume["device"] = "Disk {0}".format(metric.get("disk"))

        net_rx_bps = None
        net_tx_bps = None
        for family_name, holder_name in (("net_rx", "rx"), ("net_tx", "tx")):
            samples = family_data.get(family_name, [])
            if samples:
                value = _sample_value(samples[0])
                if value is not None:
                    if holder_name == "rx":
                        net_rx_bps = value
                    else:
                        net_tx_bps = value

        metrics = {}
        for srv in servers:
            cell = by_ip.get(srv.ip, {})
            ping = PingInfo()
            if "ping_reachable" in cell and cell["ping_reachable"] is not None:
                ping.data_available = True
                ping.reachable = cell["ping_reachable"]
                ping.latency_ms = cell["latency_ms"]

            telemetry_state = "absent"
            if cell.get("up") is True:
                telemetry_state = "online"
            elif cell.get("up") is False:
                telemetry_state = "stale"

            timestamps = [ts for ts in (cell.get("up_ts"), cell.get("ping_ts")) if ts]
            telemetry_age = None
            last_seen = None
            if timestamps:
                newest = max(timestamps)
                telemetry_age = max(0.0, now - newest)
                last_seen = datetime.fromtimestamp(newest, tz=timezone.utc).isoformat()

            memory_percent = None
            if cell.get("mem_avail") is not None and cell.get("mem_total"):
                memory_percent = round(100.0 * (1.0 - cell["mem_avail"] / cell["mem_total"]), 1)

            memory_total_bytes = round(cell["mem_total"]) if cell.get("mem_total") else None
            memory_used_bytes = None
            if cell.get("mem_total") and cell.get("mem_avail") is not None:
                memory_used_bytes = round(cell["mem_total"] - cell["mem_avail"])

            disk = DiskInfo()
            if cell.get("disk_usage") is not None:
                disk.highest_usage_percent = round(cell["disk_usage"], 1)
            if cell.get("disk_total") is not None:
                disk.total_bytes = round(cell["disk_total"])
                if cell.get("disk_free") is not None:
                    disk.used_bytes = round(cell["disk_total"] - cell["disk_free"])

            volumes = []
            for name in sorted(volumes_by_ip.get(srv.ip, {})):
                volume = volumes_by_ip[srv.ip][name]
                total = volume.get("total")
                free = volume.get("free")
                if total is None or free is None or total <= 0:
                    continue
                used = max(0.0, total - free)
                used_percent = round(100.0 * used / total, 1)
                volumes.append({
                    "name": name,
                    "filesystem": volume.get("fs") or "",
                    "label": volume.get("label") or "",
                    "device": volume.get("device") or "",
                    "used_percent": used_percent,
                    "used_bytes": round(used),
                    "free_bytes": round(free),
                    "total_bytes": round(total),
                    "status": "healthy" if used_percent < 70 else "warning" if used_percent < 85 else "critical",
                })
            disk.volumes = volumes

            metrics[srv.id] = ServerMetrics(
                server_id=srv.id,
                ping=ping,
                cpu_percent=round(cell["cpu"], 1) if cell.get("cpu") is not None else None,
                cpu_cores=round(cell["cpu_cores"]) if cell.get("cpu_cores") is not None else None,
                memory_percent=memory_percent,
                memory_total_bytes=memory_total_bytes,
                memory_used_bytes=memory_used_bytes,
                disk=disk,
                exporter_hostname=cell.get("hostname"),
                uptime_seconds=round(cell["uptime"]) if cell.get("uptime") is not None else None,
                last_seen=last_seen,
                telemetry_state=telemetry_state,
                telemetry_age_seconds=round(telemetry_age, 1) if telemetry_age is not None else None,
            )

        return CollectResult(
            ok=True,
            collected_at=now,
            prometheus_connected=True,
            ping_data_seen=ping_data_seen,
            metrics=metrics,
            query_count=query_count,
            duration_ms=duration_ms,
            net_rx_bps=net_rx_bps,
            net_tx_bps=net_tx_bps,
        )

    def _resolve_instance(self, instance, instance_map, ip_map):
        server = instance_map.get(instance)
        if server:
            return server.ip
        ip = instance_ip(instance)
        if ip in ip_map:
            return ip
        return ip


def _sample_value(sample):
    value = sample.get("value")
    if not value or len(value) < 2:
        return None
    try:
        return float(value[1])
    except (TypeError, ValueError):
        return None


def _merge_value(current, new):
    if current is None:
        return new
    return (current + new) / 2.0
