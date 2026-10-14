import io
import socket
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests
from flask import Blueprint, current_app, jsonify, request, send_file, session

from infrastructure import auth, management_demo
from infrastructure.fleet import (
    SEVERITY_OPTIONS,
    SORT_OPTIONS,
    build_alerts_payload,
    build_server_detail,
    build_server_item,
    build_servers_payload,
    build_virt_lookup,
    filter_servers_items,
    sort_servers_items,
)
from infrastructure.incidents import HISTORY_RANGES, fmt_ago, fmt_date
from infrastructure.inventory import load_inventory, save_inventory
from infrastructure.models import Server
from infrastructure.reports import server_report
from infrastructure.snapshot import format_duration

bp = Blueprint("api", __name__, url_prefix="/api")

VERSION = "0.3.0"


def register_api(app, collector, settings, incident_store, tracker):
    app.extensions["iim_collector"] = collector
    app.extensions["iim_settings"] = settings
    app.extensions["iim_incidents"] = incident_store
    app.extensions["iim_tracker"] = tracker
    app.register_blueprint(bp)


def _collector():
    return current_app.extensions["iim_collector"]


def _settings():
    return current_app.extensions["iim_settings"]


def _management_demo():
    settings = _settings()
    return settings.demo_manager or request.args.get("demo") == "manager"


def _int_arg(name, default, min_value, max_value):
    try:
        value = int(request.args.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(min_value, min(value, max_value))


@bp.get("/health")
def health():
    collector = _collector()
    settings = _settings()
    if _management_demo():
        return jsonify({
            "status": "ok",
            "app": "ARGUS",
            "version": VERSION,
            "prometheus": "demo",
            "inventory": 16,
            "demo_mode": True,
            "demo_manager": True,
            "uptime_sec": int(time.time() - collector.started_at),
            "last_collection_sec": 0,
            "last_collection_queries": 0,
            "last_collection_ms": 0.0,
        })
    result = collector.get_last_result()
    prometheus = "unknown"
    if settings.demo_mode:
        prometheus = "demo"
    elif result is not None:
        prometheus = "connected" if result.prometheus_connected else "unreachable"
    return jsonify({
        "status": "ok",
        "app": "ARGUS",
        "version": VERSION,
        "prometheus": prometheus,
        "inventory": collector.inventory_count(),
        "demo_mode": settings.demo_mode,
        "demo_manager": False,
        "uptime_sec": int(time.time() - collector.started_at),
        "last_collection_sec": int(time.time() - result.collected_at) if result and result.collected_at else None,
        "last_collection_queries": result.query_count if result else None,
        "last_collection_ms": result.duration_ms if result else None,
    })


@bp.get("/overview")
def overview():
    if _management_demo():
        return jsonify(management_demo.build_overview())
    return jsonify(_collector().get_snapshot())


@bp.get("/network-throughput")
def network_throughput():
    if _management_demo():
        return jsonify({"ok": True, "rx_mbps": None, "tx_mbps": None, "total_gbps": None, "demo": True})
    collector = _collector()
    result = collector.get_last_result()
    if result is None or result.net_rx_bps is None or result.net_tx_bps is None:
        return jsonify({"ok": False, "rx_mbps": None, "tx_mbps": None, "total_gbps": None})
    rx_mbps = round(result.net_rx_bps / 1e6, 2)
    tx_mbps = round(result.net_tx_bps / 1e6, 2)
    return jsonify({
        "ok": True,
        "rx_mbps": rx_mbps,
        "tx_mbps": tx_mbps,
        "total_gbps": round((result.net_rx_bps + result.net_tx_bps) / 1e9, 3),
    })


@bp.get("/servers")
def servers():
    args = request.args.to_dict()
    if _management_demo():
        return jsonify(management_demo.build_servers(args))
    virt_store = current_app.extensions.get("iim_virt_store")
    virt_lookup = build_virt_lookup(virt_store) if virt_store else {}
    return jsonify(build_servers_payload(_collector(), _settings(), args, virt_lookup))


@bp.get("/servers/export")
@bp.post("/servers/export")
def servers_export():
    settings = _settings()
    if settings.report_export_auth_required and not session.get("admin_authenticated"):
        return jsonify({"error": "Authentication required"}), 401
    collector = _collector()
    virt_store = current_app.extensions.get("iim_virt_store")
    virt_lookup = build_virt_lookup(virt_store) if virt_store else {}

    body = request.get_json(silent=True) or {}
    fmt = (body.get("format") or request.args.get("format") or "xlsx").lower()
    if fmt not in ("xlsx", "csv", "pdf"):
        fmt = "xlsx"
    scope = body.get("scope") or request.args.get("scope") or "filtered"
    if scope not in ("filtered", "selected", "all"):
        scope = "filtered"
    filters = body.get("filters") or {}
    if not filters:
        filters = {key: value for key, value in request.args.items() if key not in ("format", "scope")}
    report_type = body.get("report_type") or "standard"
    columns = server_report.resolve_columns(report_type, body.get("columns") or [])

    now = time.time()
    items = [
        build_server_item(server, collector.engine.get_health(server.id), now)
        for server in collector.inventory
        if server.enabled
    ]
    valid_ids = {item["id"] for item in items}
    if scope == "selected":
        requested_ids = {str(value) for value in (body.get("server_ids") or [])}
        chosen = [item for item in items if item["id"] in requested_ids and item["id"] in valid_ids]
    elif scope == "all":
        chosen = items
    else:
        chosen = filter_servers_items(items, filters, virt_lookup)
    sort_value = filters.get("sort") if filters.get("sort") in SORT_OPTIONS else "severity"
    sort_servers_items(chosen, sort_value)

    rows, applied, summary = server_report.resolve_dataset(chosen, virt_lookup, filters)
    meta = {
        "generated_at": server_report.trt_text(),
        "generated_by": session.get("admin_username") or "operator",
        "total": summary["total"],
        "filters": applied,
        "scope_text": server_report.scope_text(scope, filters),
    }

    if fmt == "xlsx":
        data = server_report.build_excel(rows, columns, meta)
        mimetype = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif fmt == "csv":
        data = server_report.build_csv(rows, columns)
        mimetype = "text/csv; charset=utf-8"
    else:
        data = server_report.build_pdf(rows, summary, meta)
        mimetype = "application/pdf"
    filename = server_report.generate_filename(fmt, filters)
    return send_file(io.BytesIO(data), as_attachment=True, download_name=filename, mimetype=mimetype)


@bp.get("/servers/<server_id>")
def server_detail(server_id):
    if _management_demo():
        item = management_demo.build_detail(server_id)
        if item is None:
            return jsonify({"error": "Server not found"}), 404
        return jsonify(item)
    collector = _collector()
    server = next(
        (s for s in collector.inventory if s.enabled and s.id == server_id),
        None,
    )
    if server is None:
        return jsonify({"error": "Server not found"}), 404
    return jsonify(build_server_detail(collector, server, time.time()))


@bp.get("/admin/servers")
@auth.admin_login_required
def admin_servers_list():
    collector = _collector()
    items = []
    for server in collector.inventory:
        health = collector.engine.get_health(server.id)
        metrics = health.metrics if health else None
        items.append({
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
            "exporter_hostname": metrics.exporter_hostname if metrics else None,
        })
    return jsonify({"items": items})


def _admin_server_data(body, existing=None):
    server_id = str(body.get("id") or "").strip()
    if existing is not None:
        server_id = existing.id
    hostname = str(body.get("hostname") or "").strip()
    display_name = str(body.get("display_name") or "").strip()
    return {
        "id": server_id,
        "hostname": hostname or server_id,
        "display_name": display_name or hostname or server_id,
        "ip": str(body.get("ip") or "").strip(),
        "site": str(body.get("site") or "").strip(),
        "role": str(body.get("role") or "").strip(),
        "environment": str(body.get("environment") or "").strip(),
        "os": str(body.get("os") or "").strip(),
        "enabled": bool(body.get("enabled", True)),
        "prometheus_instance": str(body.get("prometheus_instance") or "").strip(),
    }


@bp.post("/admin/servers")
@auth.admin_login_required
def admin_servers_add():
    data = _admin_server_data(request.get_json(silent=True) or {})
    if not data["id"]:
        return jsonify({"error": "Server id is required"}), 400
    if not data["ip"]:
        return jsonify({"error": "IP address is required"}), 400
    settings = _settings()
    servers = load_inventory(settings.inventory_path)
    if any(server.id == data["id"] for server in servers):
        return jsonify({"error": "Server id already exists"}), 409
    servers.append(Server(**data))
    save_inventory(settings.inventory_path, servers)
    _collector().reload_inventory()
    return jsonify({"ok": True, "id": data["id"]})


@bp.put("/admin/servers/<server_id>")
@auth.admin_login_required
def admin_servers_update(server_id):
    settings = _settings()
    servers = load_inventory(settings.inventory_path)
    target = next((server for server in servers if server.id == server_id), None)
    if target is None:
        return jsonify({"error": "Server not found"}), 404
    data = _admin_server_data(request.get_json(silent=True) or {}, existing=target)
    if not data["ip"]:
        return jsonify({"error": "IP address is required"}), 400
    servers[servers.index(target)] = Server(**data)
    save_inventory(settings.inventory_path, servers)
    _collector().reload_inventory()
    return jsonify({"ok": True})


@bp.delete("/admin/servers/<server_id>")
@auth.admin_login_required
def admin_servers_delete(server_id):
    settings = _settings()
    servers = load_inventory(settings.inventory_path)
    remaining = [server for server in servers if server.id != server_id]
    if len(remaining) == len(servers):
        return jsonify({"error": "Server not found"}), 404
    save_inventory(settings.inventory_path, remaining)
    _collector().reload_inventory()
    return jsonify({"ok": True})


EXPORTER_PROBES = (
    (9182, "Windows", "windows_cpu_time_total"),
    (9100, "Linux", "node_cpu_seconds_total"),
)


def _scan_one_exporter(server):
    if server.prometheus_instance:
        return server, None
    for port, kind, metric_name in EXPORTER_PROBES:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            sock.connect((server.ip, port))
            sock.close()
            resp = requests.get(
                "http://{0}:{1}/metrics".format(server.ip, port),
                timeout=2.5,
            )
            if resp.status_code == 200 and metric_name in resp.text:
                return server, {"port": port, "os": kind}
        except Exception:
            continue
    return server, None


@bp.post("/admin/scan-exporters")
@auth.admin_login_required
def admin_scan_exporters():
    settings = _settings()
    servers = load_inventory(settings.inventory_path)
    pending = [server for server in servers if not server.prometheus_instance]
    found = []
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = {pool.submit(_scan_one_exporter, server): server for server in pending}
        for future in as_completed(futures):
            server, hit = future.result()
            if hit:
                server.prometheus_instance = "{0}:{1}".format(server.ip, hit["port"])
                server.os = hit["os"]
                found.append({
                    "id": server.id,
                    "hostname": server.hostname,
                    "ip": server.ip,
                    "port": hit["port"],
                    "os": hit["os"],
                })
    if found:
        save_inventory(settings.inventory_path, servers)
        _collector().reload_inventory()
    return jsonify({
        "ok": True,
        "checked": len(pending),
        "found": found,
        "configured": sum(1 for server in servers if server.prometheus_instance),
    })


@bp.get("/alerts")
def alerts():
    args = request.args.to_dict()
    if _management_demo():
        return jsonify(management_demo.build_alerts(args))
    return jsonify(build_alerts_payload(_collector(), _settings(), args))


@bp.get("/history")
def history():
    if _management_demo():
        return jsonify(management_demo.build_history(request.args.to_dict()))
    collector = _collector()
    store = current_app.extensions["iim_incidents"]
    tracker = current_app.extensions["iim_tracker"]
    now = time.time()

    query = (request.args.get("q") or "").strip().lower()
    status = request.args.get("status") or "all"
    if status not in ("all", "active", "recovered"):
        status = "all"
    severity = request.args.get("severity") or "all"
    if severity not in SEVERITY_OPTIONS:
        severity = "all"
    range_key = request.args.get("range") or "all"
    if range_key not in HISTORY_RANGES and range_key != "all":
        range_key = "all"

    since = now - HISTORY_RANGES[range_key] if range_key in HISTORY_RANGES else None
    records = store.list_closed(since=since)
    if status != "recovered":
        records = tracker.active_records() + records

    filtered = []
    for record in records:
        if status != "all" and record["status"] != status:
            continue
        if severity != "all" and record["severity"] != severity:
            continue
        if query:
            haystack = " ".join([
                str(record.get("server_id", "")),
                str(record.get("hostname", "")),
                str(record.get("ip", "")),
            ]).lower()
            if query not in haystack:
                continue
        filtered.append(record)

    filtered.sort(key=lambda r: r["started_at"], reverse=True)

    total = len(filtered)
    page = _int_arg("page", 1, 1, 100000)
    per_page = _int_arg("per_page", 25, 1, 100)
    start = (page - 1) * per_page

    items = []
    for record in filtered[start:start + per_page]:
        record_id = record.get("id") or "active-{0}".format(record["server_id"])
        item = {
            "id": record_id,
            "server_id": record["server_id"],
            "hostname": record["hostname"],
            "ip": record["ip"],
            "site": record["site"],
            "role": record["role"],
            "severity": record["severity"],
            "reason": record["reason"],
            "peak_value": record["peak_value"],
            "status": record["status"],
            "started_at": datetime.fromtimestamp(record["started_at"], tz=timezone.utc).isoformat(),
            "started_text": fmt_date(record["started_at"]),
            "ended_at": datetime.fromtimestamp(record["ended_at"], tz=timezone.utc).isoformat() if record["ended_at"] else None,
            "ended_text": fmt_date(record["ended_at"]) if record["ended_at"] else None,
            "duration_text": format_duration(record["duration_sec"]) if record["duration_sec"] is not None else None,
            "timeline": record.get("timeline", []),
        }
        items.append(item)

    return jsonify({
        "generated_at": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
        "items": items,
    })
