import os
import sqlite3
import threading
import time
from datetime import datetime, timezone

STATUSES = ("healthy", "warning", "critical", "offline")


def _now():
    return time.time()


def _iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


SEED = {
    "datacenters": [],
    "clusters": [],
    "hosts": [],
    "vms": [],
}


class VirtualizationStore:
    def __init__(self, db_path, seed_if_empty=True):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._init()
        if seed_if_empty and self.count("datacenters") == 0:
            self._seed()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self):
        directory = os.path.dirname(self.db_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS datacenters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT,
                    created_at REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS clusters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    datacenter_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    sort_order INTEGER DEFAULT 0,
                    created_at REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS hosts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cluster_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    ip_address TEXT,
                    cpu_usage REAL DEFAULT 0,
                    ram_usage REAL DEFAULT 0,
                    disk_usage REAL DEFAULT 0,
                    status TEXT DEFAULT 'healthy',
                    cpu_capacity TEXT,
                    ram_capacity TEXT,
                    disk_capacity TEXT,
                    notes TEXT,
                    active INTEGER DEFAULT 1,
                    sort_order INTEGER DEFAULT 0,
                    created_at REAL,
                    updated_at REAL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS vms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    host_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    ip_address TEXT,
                    os TEXT,
                    role TEXT,
                    cpu_usage REAL DEFAULT 0,
                    ram_usage REAL DEFAULT 0,
                    disk_usage REAL DEFAULT 0,
                    status TEXT DEFAULT 'healthy',
                    uptime TEXT,
                    notes TEXT,
                    active INTEGER DEFAULT 1,
                    sort_order INTEGER DEFAULT 0,
                    created_at REAL,
                    updated_at REAL
                )
            """)

    def count(self, table):
        with self._lock, self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM {0}".format(table)).fetchone()[0]

    def _seed(self):
        now = _now()
        with self._lock, self._connect() as conn:
            for dc in SEED["datacenters"]:
                conn.execute("INSERT INTO datacenters (name, description, created_at) VALUES (?, ?, ?)",
                             (dc["name"], dc["description"], now))
            for cl in SEED["clusters"]:
                conn.execute("INSERT INTO clusters (datacenter_id, name, description, sort_order, created_at) VALUES (?, ?, ?, ?, ?)",
                             (cl["datacenter_id"], cl["name"], cl["description"], cl["sort_order"], now))
            for host in SEED["hosts"]:
                conn.execute(
                    "INSERT INTO hosts (cluster_id, name, ip_address, cpu_usage, ram_usage, disk_usage, status, "
                    "cpu_capacity, ram_capacity, disk_capacity, notes, active, sort_order, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)",
                    (host["cluster_id"], host["name"], host["ip_address"], host["cpu_usage"], host["ram_usage"],
                     host["disk_usage"], host["status"], host["cpu_capacity"], host["ram_capacity"], host["disk_capacity"],
                     host["notes"], host["sort_order"], now, now),
                )
            for vm in SEED["vms"]:
                conn.execute(
                    "INSERT INTO vms (host_id, name, ip_address, os, role, cpu_usage, ram_usage, disk_usage, status, "
                    "uptime, notes, active, sort_order, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)",
                    (vm["host_id"], vm["name"], vm["ip_address"], vm["os"], vm["role"], vm["cpu_usage"], vm["ram_usage"],
                     vm["disk_usage"], vm["status"], vm["uptime"], vm["notes"], vm["sort_order"], now, now),
                )

    def reseed(self):
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM vms")
            conn.execute("DELETE FROM hosts")
            conn.execute("DELETE FROM clusters")
            conn.execute("DELETE FROM datacenters")
        self._seed()

    def overview(self):
        with self._lock, self._connect() as conn:
            datacenters = [dict(r) for r in conn.execute("SELECT * FROM datacenters ORDER BY id").fetchall()]
            clusters = [dict(r) for r in conn.execute("SELECT * FROM clusters ORDER BY sort_order, id").fetchall()]
            hosts = [dict(r) for r in conn.execute("SELECT * FROM hosts ORDER BY sort_order, id").fetchall()]
            vms = [dict(r) for r in conn.execute("SELECT * FROM vms ORDER BY sort_order, id").fetchall()]

        hosts_by_cluster = {}
        for host in hosts:
            hosts_by_cluster.setdefault(host["cluster_id"], []).append(host)
        vms_by_host = {}
        for vm in vms:
            vms_by_host.setdefault(vm["host_id"], []).append(vm)
        clusters_by_dc = {}
        for cluster in clusters:
            clusters_by_dc.setdefault(cluster["datacenter_id"], []).append(cluster)

        def host_payload(host):
            host_vms = [vm_payload(vm, host) for vm in vms_by_host.get(host["id"], []) if vm["active"]]
            return {
                "id": host["id"],
                "name": host["name"],
                "ip_address": host["ip_address"],
                "status": host["status"],
                "cpu_usage": host["cpu_usage"],
                "ram_usage": host["ram_usage"],
                "disk_usage": host["disk_usage"],
                "cpu_capacity": host["cpu_capacity"],
                "ram_capacity": host["ram_capacity"],
                "disk_capacity": host["disk_capacity"],
                "notes": host["notes"],
                "active": bool(host["active"]),
                "updated_at": _iso(host["updated_at"]) if host["updated_at"] else None,
                "vm_count": len(host_vms),
                "vms": host_vms,
            }

        def vm_payload(vm, host=None):
            return {
                "id": vm["id"],
                "name": vm["name"],
                "ip_address": vm["ip_address"],
                "os": vm["os"],
                "role": vm["role"],
                "cpu_usage": vm["cpu_usage"],
                "ram_usage": vm["ram_usage"],
                "disk_usage": vm["disk_usage"],
                "status": vm["status"],
                "uptime": vm["uptime"],
                "notes": vm["notes"],
                "active": bool(vm["active"]),
                "host_id": vm["host_id"],
                "updated_at": _iso(vm["updated_at"]) if vm["updated_at"] else None,
            }

        payload = []
        for dc in datacenters:
            dc_clusters = []
            for cluster in clusters_by_dc.get(dc["id"], []):
                cluster_hosts = [host_payload(h) for h in hosts_by_cluster.get(cluster["id"], []) if h["active"]]
                dc_clusters.append({
                    "id": cluster["id"],
                    "name": cluster["name"],
                    "description": cluster["description"],
                    "host_count": len(cluster_hosts),
                    "vm_count": sum(h["vm_count"] for h in cluster_hosts),
                    "hosts": cluster_hosts,
                })
            payload.append({
                "id": dc["id"],
                "name": dc["name"],
                "description": dc["description"],
                "host_count": sum(c["host_count"] for c in dc_clusters),
                "vm_count": sum(c["vm_count"] for c in dc_clusters),
                "clusters": dc_clusters,
            })

        active_hosts = [h for h in hosts if h["active"]]
        active_vms = [v for v in vms if v["active"]]
        all_nodes = active_hosts + active_vms

        def avg(field):
            values = [node[field] for node in all_nodes if node[field] is not None]
            return round(sum(values) / len(values), 1) if values else 0

        def count_states(items):
            return {status: sum(1 for i in items if i["status"] == status) for status in STATUSES}

        host_states = count_states(active_hosts)
        vm_states = count_states(active_vms)

        return {
            "generated_at": _iso(_now()),
            "datacenters": payload,
            "summary": {
                "hosts": len(active_hosts),
                "vms": len(active_vms),
                "hosts_healthy": host_states.get("healthy", 0),
                "hosts_warning": host_states.get("warning", 0),
                "hosts_critical": host_states.get("critical", 0),
                "hosts_offline": host_states.get("offline", 0),
                "vms_healthy": vm_states.get("healthy", 0),
                "vms_warning": vm_states.get("warning", 0),
                "vms_critical": vm_states.get("critical", 0),
                "vms_offline": vm_states.get("offline", 0),
                "avg_cpu": avg("cpu_usage"),
                "avg_ram": avg("ram_usage"),
                "avg_disk": avg("disk_usage"),
            },
        }

    def list_datacenters(self):
        with self._lock, self._connect() as conn:
            rows = [dict(r) for r in conn.execute("SELECT * FROM datacenters ORDER BY id").fetchall()]
        for dc in rows:
            dc["cluster_count"] = self._cluster_count(dc["id"])
            dc["host_count"], dc["vm_count"] = self._dc_counts(dc["id"])
        return rows

    def list_clusters(self):
        with self._lock, self._connect() as conn:
            rows = [dict(r) for r in conn.execute(
                "SELECT c.*, d.name AS datacenter_name FROM clusters c "
                "LEFT JOIN datacenters d ON d.id = c.datacenter_id ORDER BY c.sort_order, c.id").fetchall()]
        for cluster in rows:
            cluster["host_count"] = self._host_count(cluster["id"])
        return rows

    def list_hosts(self, query="", status=""):
        with self._lock, self._connect() as conn:
            rows = [dict(r) for r in conn.execute(
                "SELECT h.*, c.name AS cluster_name, d.name AS datacenter_name FROM hosts h "
                "LEFT JOIN clusters c ON c.id = h.cluster_id "
                "LEFT JOIN datacenters d ON d.id = c.datacenter_id "
                "ORDER BY h.sort_order, h.id").fetchall()]
        out = []
        for host in rows:
            host["vm_count"] = self._vm_count(host["id"])
            host["updated_at"] = _iso(host["updated_at"]) if host["updated_at"] else None
            host["created_at"] = _iso(host["created_at"]) if host["created_at"] else None
            if query and query.lower() not in (host["name"] or "").lower() and query.lower() not in (host["ip_address"] or "").lower():
                continue
            if status and host["status"] != status:
                continue
            out.append(host)
        return out

    def list_vms(self, query="", status=""):
        with self._lock, self._connect() as conn:
            rows = [dict(r) for r in conn.execute(
                "SELECT v.*, h.name AS host_name FROM vms v "
                "LEFT JOIN hosts h ON h.id = v.host_id "
                "ORDER BY v.sort_order, v.id").fetchall()]
        out = []
        for vm in rows:
            vm["updated_at"] = _iso(vm["updated_at"]) if vm["updated_at"] else None
            vm["created_at"] = _iso(vm["created_at"]) if vm["created_at"] else None
            if query and query.lower() not in (vm["name"] or "").lower() and query.lower() not in (vm["ip_address"] or "").lower():
                continue
            if status and vm["status"] != status:
                continue
            out.append(vm)
        return out

    def get_host(self, host_id):
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM hosts WHERE id = ?", (host_id,)).fetchone()
        if not row:
            return None
        host = dict(row)
        host["updated_at"] = _iso(host["updated_at"]) if host["updated_at"] else None
        host["vm_count"] = self._vm_count(host["id"])
        return host

    def get_vm(self, vm_id):
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM vms WHERE id = ?", (vm_id,)).fetchone()
        if not row:
            return None
        vm = dict(row)
        vm["updated_at"] = _iso(vm["updated_at"]) if vm["updated_at"] else None
        return vm

    def get_datacenter(self, dc_id):
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM datacenters WHERE id = ?", (dc_id,)).fetchone()
        return dict(row) if row else None

    def get_cluster(self, cluster_id):
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM clusters WHERE id = ?", (cluster_id,)).fetchone()
        return dict(row) if row else None

    def _cluster_count(self, dc_id):
        with self._lock, self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM clusters WHERE datacenter_id = ?", (dc_id,)).fetchone()[0]

    def _dc_counts(self, dc_id):
        with self._lock, self._connect() as conn:
            hosts = conn.execute(
                "SELECT COUNT(*) FROM hosts h JOIN clusters c ON c.id = h.cluster_id WHERE c.datacenter_id = ?",
                (dc_id,)).fetchone()[0]
            vms = conn.execute(
                "SELECT COUNT(*) FROM vms v JOIN hosts h ON h.id = v.host_id JOIN clusters c ON c.id = h.cluster_id "
                "WHERE c.datacenter_id = ?",
                (dc_id,)).fetchone()[0]
        return hosts, vms

    def _host_count(self, cluster_id):
        with self._lock, self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM hosts WHERE cluster_id = ?", (cluster_id,)).fetchone()[0]

    def _vm_count(self, host_id):
        with self._lock, self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM vms WHERE host_id = ?", (host_id,)).fetchone()[0]

    def add_host(self, data):
        now = _now()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO hosts (cluster_id, name, ip_address, cpu_usage, ram_usage, disk_usage, status, "
                "cpu_capacity, ram_capacity, disk_capacity, notes, active, sort_order, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (data["cluster_id"], data["name"], data.get("ip_address"), data.get("cpu_usage", 0),
                 data.get("ram_usage", 0), data.get("disk_usage", 0), data.get("status", "healthy"),
                 data.get("cpu_capacity"), data.get("ram_capacity"), data.get("disk_capacity"),
                 data.get("notes"), 1 if data.get("active", True) else 0, data.get("sort_order", 0), now, now),
            )
            return cur.lastrowid

    def update_host(self, host_id, data):
        now = _now()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE hosts SET cluster_id=?, name=?, ip_address=?, cpu_usage=?, ram_usage=?, disk_usage=?, "
                "status=?, cpu_capacity=?, ram_capacity=?, disk_capacity=?, notes=?, active=?, sort_order=?, updated_at=? "
                "WHERE id=?",
                (data["cluster_id"], data["name"], data.get("ip_address"), data.get("cpu_usage", 0),
                 data.get("ram_usage", 0), data.get("disk_usage", 0), data.get("status", "healthy"),
                 data.get("cpu_capacity"), data.get("ram_capacity"), data.get("disk_capacity"),
                 data.get("notes"), 1 if data.get("active", True) else 0, data.get("sort_order", 0), now, host_id),
            )
            return cur.rowcount > 0

    def delete_host(self, host_id):
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM vms WHERE host_id = ?", (host_id,))
            conn.execute("DELETE FROM hosts WHERE id = ?", (host_id,))

    def add_vm(self, data):
        now = _now()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO vms (host_id, name, ip_address, os, role, cpu_usage, ram_usage, disk_usage, status, "
                "uptime, notes, active, sort_order, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (data["host_id"], data["name"], data.get("ip_address"), data.get("os"), data.get("role"),
                 data.get("cpu_usage", 0), data.get("ram_usage", 0), data.get("disk_usage", 0),
                 data.get("status", "healthy"), data.get("uptime"), data.get("notes"),
                 1 if data.get("active", True) else 0, data.get("sort_order", 0), now, now),
            )
            return cur.lastrowid

    def update_vm(self, vm_id, data):
        now = _now()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE vms SET host_id=?, name=?, ip_address=?, os=?, role=?, cpu_usage=?, ram_usage=?, "
                "disk_usage=?, status=?, uptime=?, notes=?, active=?, sort_order=?, updated_at=? WHERE id=?",
                (data["host_id"], data["name"], data.get("ip_address"), data.get("os"), data.get("role"),
                 data.get("cpu_usage", 0), data.get("ram_usage", 0), data.get("disk_usage", 0),
                 data.get("status", "healthy"), data.get("uptime"), data.get("notes"),
                 1 if data.get("active", True) else 0, data.get("sort_order", 0), now, vm_id),
            )
            return cur.rowcount > 0

    def delete_vm(self, vm_id):
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM vms WHERE id = ?", (vm_id,))

    def add_datacenter(self, data):
        with self._lock, self._connect() as conn:
            cur = conn.execute("INSERT INTO datacenters (name, description, created_at) VALUES (?, ?, ?)",
                               (data["name"], data.get("description"), _now()))
            return cur.lastrowid

    def update_datacenter(self, dc_id, data):
        with self._lock, self._connect() as conn:
            cur = conn.execute("UPDATE datacenters SET name=?, description=? WHERE id=?",
                               (data["name"], data.get("description"), dc_id))
            return cur.rowcount > 0

    def delete_datacenter(self, dc_id):
        with self._lock, self._connect() as conn:
            cluster_ids = [r[0] for r in conn.execute("SELECT id FROM clusters WHERE datacenter_id = ?", (dc_id,)).fetchall()]
            for cluster_id in cluster_ids:
                host_ids = [r[0] for r in conn.execute("SELECT id FROM hosts WHERE cluster_id = ?", (cluster_id,)).fetchall()]
                for host_id in host_ids:
                    conn.execute("DELETE FROM vms WHERE host_id = ?", (host_id,))
                conn.execute("DELETE FROM hosts WHERE cluster_id = ?", (cluster_id,))
            conn.execute("DELETE FROM clusters WHERE datacenter_id = ?", (dc_id,))
            conn.execute("DELETE FROM datacenters WHERE id = ?", (dc_id,))

    def add_cluster(self, data):
        with self._lock, self._connect() as conn:
            cur = conn.execute("INSERT INTO clusters (datacenter_id, name, description, sort_order, created_at) VALUES (?, ?, ?, ?, ?)",
                               (data["datacenter_id"], data["name"], data.get("description"), data.get("sort_order", 0), _now()))
            return cur.lastrowid

    def update_cluster(self, cluster_id, data):
        with self._lock, self._connect() as conn:
            cur = conn.execute("UPDATE clusters SET datacenter_id=?, name=?, description=?, sort_order=? WHERE id=?",
                               (data["datacenter_id"], data["name"], data.get("description"), data.get("sort_order", 0), cluster_id))
            return cur.rowcount > 0

    def delete_cluster(self, cluster_id):
        with self._lock, self._connect() as conn:
            host_ids = [r[0] for r in conn.execute("SELECT id FROM hosts WHERE cluster_id = ?", (cluster_id,)).fetchall()]
            for host_id in host_ids:
                conn.execute("DELETE FROM vms WHERE host_id = ?", (host_id,))
            conn.execute("DELETE FROM hosts WHERE cluster_id = ?", (cluster_id,))
            conn.execute("DELETE FROM clusters WHERE id = ?", (cluster_id,))
