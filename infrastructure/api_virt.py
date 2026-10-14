from flask import Blueprint, current_app, jsonify, request

from infrastructure import auth
from infrastructure.virtualization import STATUSES

bp = Blueprint("virt_api", __name__, url_prefix="/api")


def register_virt_api(app, store):
    app.extensions["iim_virt_store"] = store
    app.register_blueprint(bp)


def _store():
    return current_app.extensions["iim_virt_store"]


def _body():
    return request.get_json(silent=True) or {}


def _num(value, default=0, minimum=0, maximum=100):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(value, maximum))


def _status(value):
    value = str(value or "").lower()
    return value if value in STATUSES else "healthy"


@bp.get("/virtualization/overview")
def virt_overview():
    return jsonify(_store().overview())


@bp.post("/virtualization/reseed")
@auth.admin_login_required
def virt_reseed():
    _store().reseed()
    return jsonify({"ok": True})


@bp.get("/datacenters")
def datacenters_list():
    return jsonify({"items": _store().list_datacenters()})


@bp.post("/datacenters")
@auth.admin_login_required
def datacenters_add():
    data = _body()
    name = str(data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Datacenter name is required"}), 400
    dc_id = _store().add_datacenter({"name": name, "description": data.get("description")})
    return jsonify({"ok": True, "id": dc_id})


@bp.put("/datacenters/<int:dc_id>")
@auth.admin_login_required
def datacenters_update(dc_id):
    data = _body()
    name = str(data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Datacenter name is required"}), 400
    if not _store().update_datacenter(dc_id, {"name": name, "description": data.get("description")}):
        return jsonify({"error": "Datacenter not found"}), 404
    return jsonify({"ok": True})


@bp.delete("/datacenters/<int:dc_id>")
@auth.admin_login_required
def datacenters_delete(dc_id):
    if _store().get_datacenter(dc_id) is None:
        return jsonify({"error": "Datacenter not found"}), 404
    _store().delete_datacenter(dc_id)
    return jsonify({"ok": True})


@bp.get("/clusters")
def clusters_list():
    return jsonify({"items": _store().list_clusters()})


@bp.post("/clusters")
@auth.admin_login_required
def clusters_add():
    data = _body()
    name = str(data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Cluster name is required"}), 400
    if _store().get_datacenter(int(data.get("datacenter_id") or 0)) is None:
        return jsonify({"error": "Datacenter not found"}), 400
    cluster_id = _store().add_cluster({
        "datacenter_id": int(data["datacenter_id"]), "name": name,
        "description": data.get("description"), "sort_order": int(data.get("sort_order") or 0),
    })
    return jsonify({"ok": True, "id": cluster_id})


@bp.put("/clusters/<int:cluster_id>")
@auth.admin_login_required
def clusters_update(cluster_id):
    data = _body()
    name = str(data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Cluster name is required"}), 400
    if _store().get_datacenter(int(data.get("datacenter_id") or 0)) is None:
        return jsonify({"error": "Datacenter not found"}), 400
    if not _store().update_cluster(cluster_id, {
        "datacenter_id": int(data["datacenter_id"]), "name": name,
        "description": data.get("description"), "sort_order": int(data.get("sort_order") or 0),
    }):
        return jsonify({"error": "Cluster not found"}), 404
    return jsonify({"ok": True})


@bp.delete("/clusters/<int:cluster_id>")
@auth.admin_login_required
def clusters_delete(cluster_id):
    if _store().get_cluster(cluster_id) is None:
        return jsonify({"error": "Cluster not found"}), 404
    _store().delete_cluster(cluster_id)
    return jsonify({"ok": True})


@bp.get("/hosts")
def hosts_list():
    store = _store()
    query = request.args.get("q") or ""
    status = request.args.get("status") or ""
    if status not in ("",) + STATUSES:
        status = ""
    return jsonify({"items": store.list_hosts(query, status)})


@bp.get("/hosts/<int:host_id>")
def hosts_get(host_id):
    host = _store().get_host(host_id)
    if host is None:
        return jsonify({"error": "Host not found"}), 404
    return jsonify(host)


def _host_data(data):
    return {
        "cluster_id": int(data.get("cluster_id") or 0),
        "name": str(data.get("name") or "").strip(),
        "ip_address": str(data.get("ip_address") or "").strip(),
        "cpu_usage": _num(data.get("cpu_usage")),
        "ram_usage": _num(data.get("ram_usage")),
        "disk_usage": _num(data.get("disk_usage")),
        "status": _status(data.get("status")),
        "cpu_capacity": str(data.get("cpu_capacity") or "").strip(),
        "ram_capacity": str(data.get("ram_capacity") or "").strip(),
        "disk_capacity": str(data.get("disk_capacity") or "").strip(),
        "notes": str(data.get("notes") or "").strip(),
        "active": bool(data.get("active", True)),
        "sort_order": int(data.get("sort_order") or 0),
    }


@bp.post("/hosts")
@auth.admin_login_required
def hosts_add():
    data = _host_data(_body())
    if not data["name"]:
        return jsonify({"error": "Host name is required"}), 400
    if _store().get_cluster(data["cluster_id"]) is None:
        return jsonify({"error": "Cluster not found"}), 400
    host_id = _store().add_host(data)
    return jsonify({"ok": True, "id": host_id})


@bp.put("/hosts/<int:host_id>")
@auth.admin_login_required
def hosts_update(host_id):
    data = _host_data(_body())
    if not data["name"]:
        return jsonify({"error": "Host name is required"}), 400
    if _store().get_cluster(data["cluster_id"]) is None:
        return jsonify({"error": "Cluster not found"}), 400
    if not _store().update_host(host_id, data):
        return jsonify({"error": "Host not found"}), 404
    return jsonify({"ok": True})


@bp.delete("/hosts/<int:host_id>")
@auth.admin_login_required
def hosts_delete(host_id):
    if _store().get_host(host_id) is None:
        return jsonify({"error": "Host not found"}), 404
    _store().delete_host(host_id)
    return jsonify({"ok": True})


@bp.get("/vms")
def vms_list():
    store = _store()
    query = request.args.get("q") or ""
    status = request.args.get("status") or ""
    if status not in ("",) + STATUSES:
        status = ""
    return jsonify({"items": store.list_vms(query, status)})


@bp.get("/vms/<int:vm_id>")
def vms_get(vm_id):
    vm = _store().get_vm(vm_id)
    if vm is None:
        return jsonify({"error": "VM not found"}), 404
    return jsonify(vm)


def _vm_data(data):
    return {
        "host_id": int(data.get("host_id") or 0),
        "name": str(data.get("name") or "").strip(),
        "ip_address": str(data.get("ip_address") or "").strip(),
        "os": str(data.get("os") or "").strip(),
        "role": str(data.get("role") or "").strip(),
        "cpu_usage": _num(data.get("cpu_usage")),
        "ram_usage": _num(data.get("ram_usage")),
        "disk_usage": _num(data.get("disk_usage")),
        "status": _status(data.get("status")),
        "uptime": str(data.get("uptime") or "").strip(),
        "notes": str(data.get("notes") or "").strip(),
        "active": bool(data.get("active", True)),
        "sort_order": int(data.get("sort_order") or 0),
    }


@bp.post("/vms")
@auth.admin_login_required
def vms_add():
    data = _vm_data(_body())
    if not data["name"]:
        return jsonify({"error": "VM name is required"}), 400
    if _store().get_host(data["host_id"]) is None:
        return jsonify({"error": "Host not found"}), 400
    vm_id = _store().add_vm(data)
    return jsonify({"ok": True, "id": vm_id})


@bp.put("/vms/<int:vm_id>")
@auth.admin_login_required
def vms_update(vm_id):
    data = _vm_data(_body())
    if not data["name"]:
        return jsonify({"error": "VM name is required"}), 400
    if _store().get_host(data["host_id"]) is None:
        return jsonify({"error": "Host not found"}), 400
    if not _store().update_vm(vm_id, data):
        return jsonify({"error": "VM not found"}), 404
    return jsonify({"ok": True})


@bp.delete("/vms/<int:vm_id>")
@auth.admin_login_required
def vms_delete(vm_id):
    if _store().get_vm(vm_id) is None:
        return jsonify({"error": "VM not found"}), 404
    _store().delete_vm(vm_id)
    return jsonify({"ok": True})
