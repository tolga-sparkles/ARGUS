import json
import os

import yaml

from infrastructure.models import Server

PING_TARGETS_FILENAME = "ping_targets.json"
EXPORTER_TARGETS_FILENAME = "exporter_targets.json"

HEADER = (
    "# Server inventory.\n"
    "# id must be unique and stable; hostname must never be used as an identifier.\n"
    "# prometheus_instance maps the exporter scrape target explicitly\n"
    "# (\"ip:port\" as seen in Prometheus instance labels). If omitted, the\n"
    "# exporter is matched by ip with any port.\n"
    "# Ping probes are always matched by ip (instance label of probe_success).\n"
)


def _entry_of(server):
    return {
        "id": server.id,
        "hostname": server.hostname,
        "display_name": server.display_name,
        "ip": server.ip,
        "site": server.site,
        "role": server.role,
        "environment": server.environment,
        "os": server.os,
        "enabled": server.enabled,
        "prometheus_instance": server.prometheus_instance,
    }


def save_inventory(path, servers):
    document = HEADER + yaml.safe_dump(
        {"servers": [_entry_of(s) for s in servers]},
        sort_keys=False,
        allow_unicode=True,
    )
    directory = os.path.dirname(path)
    temp_path = "{0}.tmp".format(path)
    with open(temp_path, "w", encoding="utf-8") as fh:
        fh.write(document)
    os.replace(temp_path, path)
    write_ping_targets(path, servers)
    write_exporter_targets(path, servers)


def write_ping_targets(inventory_path, servers):
    data = [{"targets": [server.ip]} for server in servers if server.ip]
    target_path = os.path.join(os.path.dirname(inventory_path), PING_TARGETS_FILENAME)
    temp_path = "{0}.tmp".format(target_path)
    with open(temp_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(temp_path, target_path)
    return target_path


def write_exporter_targets(inventory_path, servers):
    data = [{"targets": [server.prometheus_instance]} for server in servers if server.prometheus_instance]
    target_path = os.path.join(os.path.dirname(inventory_path), EXPORTER_TARGETS_FILENAME)
    temp_path = "{0}.tmp".format(target_path)
    with open(temp_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(temp_path, target_path)
    return target_path


def load_inventory(path):
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    servers = []
    seen_ids = set()
    for entry in raw.get("servers") or []:
        server = Server(
            id=str(entry.get("id", "")).strip(),
            hostname=str(entry.get("hostname", "")).strip(),
            display_name=str(entry.get("display_name", "")).strip(),
            ip=str(entry.get("ip", "")).strip(),
            site=str(entry.get("site", "")).strip(),
            role=str(entry.get("role", "")).strip(),
            environment=str(entry.get("environment", "")).strip(),
            os=str(entry.get("os", "")).strip(),
            enabled=bool(entry.get("enabled", True)),
            prometheus_instance=str(entry.get("prometheus_instance", "")).strip(),
        )
        if not server.id or not server.ip:
            continue
        if server.id in seen_ids:
            continue
        seen_ids.add(server.id)
        if not server.hostname:
            server.hostname = server.id
        if not server.display_name:
            server.display_name = server.hostname
        servers.append(server)
    return servers


def enabled_servers(inventory):
    return [s for s in inventory if s.enabled]
