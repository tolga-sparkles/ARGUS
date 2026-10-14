import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

SEVERITY_RANK = {"no_telemetry": 0, "warning": 1, "critical": 2, "offline": 3}

HISTORY_RANGES = {"24h": 24 * 3600, "7d": 7 * 86400, "30d": 30 * 86400}


def _trt(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc) + timedelta(hours=3)


def fmt_clock(ts):
    return _trt(ts).strftime("%H:%M")


def fmt_date(ts):
    return _trt(ts).strftime("%d %b · %H:%M")


def fmt_ago(seconds):
    seconds = int(seconds)
    if seconds < 60:
        return "{0}s ago".format(seconds)
    if seconds < 3600:
        return "{0}m ago".format(seconds // 60)
    if seconds < 86400:
        return "{0}h ago".format(seconds // 3600)
    return "{0}d ago".format(seconds // 86400)


class IncidentStore:
    def __init__(self, db_path):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init()

    def _init(self):
        directory = os.path.dirname(self.db_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id TEXT NOT NULL,
                    hostname TEXT,
                    ip TEXT,
                    site TEXT,
                    role TEXT,
                    severity TEXT NOT NULL,
                    reason TEXT,
                    peak_value TEXT,
                    started_at REAL NOT NULL,
                    ended_at REAL NOT NULL,
                    duration_sec REAL NOT NULL,
                    timeline TEXT NOT NULL DEFAULT '[]'
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_incidents_started ON incidents(started_at)")

    def add_closed(self, record):
        with self._lock, sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO incidents
                (server_id, hostname, ip, site, role, severity, reason, peak_value,
                 started_at, ended_at, duration_sec, timeline)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["server_id"], record["hostname"], record["ip"],
                    record["site"], record["role"], record["severity"], record["reason"],
                    record["peak_value"], record["started_at"], record["ended_at"],
                    record["duration_sec"], json.dumps(record["timeline"]),
                ),
            )

    def list_closed(self, since=None, limit=1000):
        sql = (
            "SELECT id, server_id, hostname, ip, site, role, severity, reason, peak_value, "
            "started_at, ended_at, duration_sec, timeline FROM incidents"
        )
        params = []
        if since is not None:
            sql += " WHERE started_at >= ?"
            params.append(since)
        sql += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        with self._lock, sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(sql, params).fetchall()
        out = []
        for row in rows:
            out.append({
                "id": row[0],
                "server_id": row[1],
                "hostname": row[2],
                "ip": row[3],
                "site": row[4],
                "role": row[5],
                "severity": row[6],
                "reason": row[7],
                "peak_value": row[8],
                "started_at": row[9],
                "ended_at": row[10],
                "duration_sec": row[11],
                "timeline": json.loads(row[12] or "[]"),
                "status": "recovered",
            })
        return out


class IncidentTracker:
    def __init__(self, store):
        self.store = store
        self._active = {}
        self._lock = threading.Lock()

    def _entry(self, ts, severity, message, value):
        return {
            "t": ts,
            "time_text": fmt_clock(ts),
            "severity": severity,
            "message": message,
            "value": value,
        }

    def open(self, server, severity, reason, value, message, ts):
        with self._lock:
            existing = self._active.get(server.id)
            if existing:
                self._update_locked(existing, severity, reason, value, message, ts)
                return
            self._active[server.id] = {
                "server_id": server.id,
                "hostname": server.hostname,
                "ip": server.ip,
                "site": server.site,
                "role": server.role,
                "severity": severity,
                "reason": reason,
                "peak_value": value,
                "started_at": ts,
                "ended_at": None,
                "duration_sec": None,
                "timeline": [self._entry(ts, severity, message, value)],
                "status": "active",
            }

    def _update_locked(self, record, severity, reason, value, message, ts):
        if SEVERITY_RANK.get(severity, -1) > SEVERITY_RANK.get(record["severity"], -1):
            record["severity"] = severity
            record["reason"] = reason
            record["peak_value"] = value
        record["timeline"].append(self._entry(ts, severity, message, value))

    def update(self, server, severity, reason, value, message, ts):
        with self._lock:
            record = self._active.get(server.id)
            if record:
                self._update_locked(record, severity, reason, value, message, ts)

    def close(self, server, message, value, ts):
        with self._lock:
            record = self._active.pop(server.id, None)
            if not record:
                return
            record["ended_at"] = ts
            record["duration_sec"] = max(0.0, ts - record["started_at"])
            record["status"] = "recovered"
            record["timeline"].append(self._entry(ts, "healthy", message, value))
            self.store.add_closed(record)

    def is_open(self, server_id):
        with self._lock:
            return server_id in self._active

    def get_active(self, server_id):
        with self._lock:
            record = self._active.get(server_id)
            return dict(record) if record else None

    def active_records(self):
        with self._lock:
            return [dict(record) for record in self._active.values()]
