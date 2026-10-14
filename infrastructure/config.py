import os
import secrets

import yaml


DEFAULTS = {
    "host": "0.0.0.0",
    "port": 8083,
    "secret_key": None,
    "demo_mode": False,
    "collect_interval": 10,
    "prometheus_url": None,
    "prometheus_timeout": 10,
    "rate_window": "5m",
    "ping_job": None,
    "ping_metric": "probe_success",
    "ping_latency_metric": "probe_duration_seconds",
    "up_metric": "up",
    "cpu_idle_metric_linux": "node_cpu_seconds_total",
    "cpu_idle_metric_windows": "windows_cpu_time_total",
    "mem_avail_metric_linux": "node_memory_MemAvailable_bytes",
    "mem_avail_metric_windows": "windows_os_physical_memory_free_bytes",
    "mem_total_metric_linux": "node_memory_MemTotal_bytes",
    "mem_total_metric_windows": "windows_cs_physical_memory_bytes",
    "disk_free_metric_linux": "node_filesystem_avail_bytes",
    "disk_free_metric_windows": "windows_logical_disk_free_bytes",
    "disk_info_metric_windows": "windows_logical_disk_info",
    "disk_size_metric_linux": "node_filesystem_size_bytes",
    "disk_size_metric_windows": "windows_logical_disk_size_bytes",
    "disk_linux_fstype": "ext4|xfs|btrfs",
    "disk_linux_mountpoint_ignore": "^/boot.*|^/var/lib/(docker|kubelet).*",
    "disk_windows_volume_ignore": "^HarddiskVolume.*",
    "uptime_metric_linux": "node_boot_time_seconds",
    "uptime_metric_windows": "windows_system_system_up_time",
    "hostname_metric_linux": "node_uname_info",
    "hostname_metric_windows": "windows_cs_hostname",
    "net_rx_metric_linux": "node_network_receive_bytes_total",
    "net_tx_metric_linux": "node_network_transmit_bytes_total",
    "net_rx_metric_windows": "windows_net_bytes_received_total",
    "net_tx_metric_windows": "windows_net_bytes_sent_total",
    "net_device_ignore": "lo|veth.*|docker.*|br-.*|virbr.*",
    "thresholds": {
        "cpu_warning": 85,
        "cpu_critical": 95,
        "memory_warning": 85,
        "memory_critical": 95,
        "disk_warning": 85,
        "disk_critical": 95,
        "ping_warning_ms": 120,
        "ping_critical_ms": 300,
    },
    "telemetry_stale_seconds": 180,
    "offline_failures": 3,
    "recovery_successes": 2,
    "attention_limit": 8,
    "alerts_limit": 5,
    "db_path": "data/infrastructure.db",
    "virt_db_path": "data/virtualization.db",
    "mail_db_path": "data/notifications.db",
    "smtp_host": None,
    "smtp_port": 587,
    "smtp_username": None,
    "smtp_password": None,
    "smtp_from": None,
    "smtp_tls": True,
    "smtp_timeout": 10,
    "smtp_retry_limit": 5,
    "mail_max_per_minute": 20,
    "mail_queue_limit": 100,
    "dashboard_url": None,
    "admin_username": None,
    "admin_password_hash": None,
    "session_cookie_secure": False,
    "report_export_auth_required": False,
}


def _deep_merge(base, override):
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def load_env_file(path):
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _env_bool(name, default):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name, default):
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name, default):
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


class Settings:
    def __init__(self, base_dir, values):
        self.base_dir = base_dir
        self.host = values.get("host", DEFAULTS["host"])
        self.port = _env_int("PORT", int(values.get("port", DEFAULTS["port"])))
        self.secret_key = os.environ.get("SECRET_KEY") or values.get("secret_key") or secrets.token_hex(32)
        demo_raw = (os.environ.get("DEMO_MODE") or str(values.get("demo_mode", DEFAULTS["demo_mode"])) or "false").strip().lower()
        self.demo_manager = demo_raw == "manager"
        self.demo_mode = not self.demo_manager and demo_raw in ("1", "true", "yes", "on")
        self.collect_interval = _env_int("COLLECT_INTERVAL", int(values.get("collect_interval", DEFAULTS["collect_interval"])))
        self.prometheus_url = os.environ.get("PROMETHEUS_URL", values.get("prometheus_url")) or None
        if self.prometheus_url:
            self.prometheus_url = self.prometheus_url.rstrip("/")
        self.prometheus_timeout = _env_float("PROMETHEUS_TIMEOUT", float(values.get("prometheus_timeout", DEFAULTS["prometheus_timeout"])))
        self.rate_window = values.get("rate_window", DEFAULTS["rate_window"])

        self.ping_job = values.get("ping_job", DEFAULTS["ping_job"])
        self.ping_metric = values.get("ping_metric", DEFAULTS["ping_metric"])
        self.ping_latency_metric = values.get("ping_latency_metric", DEFAULTS["ping_latency_metric"])
        self.up_metric = values.get("up_metric", DEFAULTS["up_metric"])
        self.cpu_idle_metric_linux = values.get("cpu_idle_metric_linux", DEFAULTS["cpu_idle_metric_linux"])
        self.cpu_idle_metric_windows = values.get("cpu_idle_metric_windows", DEFAULTS["cpu_idle_metric_windows"])
        self.mem_avail_metric_linux = values.get("mem_avail_metric_linux", DEFAULTS["mem_avail_metric_linux"])
        self.mem_avail_metric_windows = values.get("mem_avail_metric_windows", DEFAULTS["mem_avail_metric_windows"])
        self.mem_total_metric_linux = values.get("mem_total_metric_linux", DEFAULTS["mem_total_metric_linux"])
        self.mem_total_metric_windows = values.get("mem_total_metric_windows", DEFAULTS["mem_total_metric_windows"])
        self.disk_free_metric_linux = values.get("disk_free_metric_linux", DEFAULTS["disk_free_metric_linux"])
        self.disk_free_metric_windows = values.get("disk_free_metric_windows", DEFAULTS["disk_free_metric_windows"])
        self.disk_info_metric_windows = values.get("disk_info_metric_windows", DEFAULTS["disk_info_metric_windows"])
        self.disk_size_metric_linux = values.get("disk_size_metric_linux", DEFAULTS["disk_size_metric_linux"])
        self.disk_size_metric_windows = values.get("disk_size_metric_windows", DEFAULTS["disk_size_metric_windows"])
        self.disk_linux_fstype = values.get("disk_linux_fstype", DEFAULTS["disk_linux_fstype"])
        self.disk_linux_mountpoint_ignore = values.get("disk_linux_mountpoint_ignore", DEFAULTS["disk_linux_mountpoint_ignore"])
        self.disk_windows_volume_ignore = values.get("disk_windows_volume_ignore", DEFAULTS["disk_windows_volume_ignore"])
        self.uptime_metric_linux = values.get("uptime_metric_linux", DEFAULTS["uptime_metric_linux"])
        self.uptime_metric_windows = values.get("uptime_metric_windows", DEFAULTS["uptime_metric_windows"])
        self.hostname_metric_linux = values.get("hostname_metric_linux", DEFAULTS["hostname_metric_linux"])
        self.hostname_metric_windows = values.get("hostname_metric_windows", DEFAULTS["hostname_metric_windows"])
        self.net_rx_metric_linux = values.get("net_rx_metric_linux", DEFAULTS["net_rx_metric_linux"])
        self.net_tx_metric_linux = values.get("net_tx_metric_linux", DEFAULTS["net_tx_metric_linux"])
        self.net_rx_metric_windows = values.get("net_rx_metric_windows", DEFAULTS["net_rx_metric_windows"])
        self.net_tx_metric_windows = values.get("net_tx_metric_windows", DEFAULTS["net_tx_metric_windows"])
        self.net_device_ignore = values.get("net_device_ignore", DEFAULTS["net_device_ignore"])

        thresholds = dict(DEFAULTS["thresholds"])
        thresholds.update(values.get("thresholds") or {})
        self.thresholds = {
            "cpu_warning": _env_float("THRESHOLD_CPU_WARNING", float(thresholds.get("cpu_warning"))),
            "cpu_critical": _env_float("THRESHOLD_CPU_CRITICAL", float(thresholds.get("cpu_critical"))),
            "memory_warning": _env_float("THRESHOLD_MEMORY_WARNING", float(thresholds.get("memory_warning"))),
            "memory_critical": _env_float("THRESHOLD_MEMORY_CRITICAL", float(thresholds.get("memory_critical"))),
            "disk_warning": _env_float("THRESHOLD_DISK_WARNING", float(thresholds.get("disk_warning"))),
            "disk_critical": _env_float("THRESHOLD_DISK_CRITICAL", float(thresholds.get("disk_critical"))),
            "ping_warning_ms": _env_float("THRESHOLD_PING_WARNING_MS", float(thresholds.get("ping_warning_ms"))),
            "ping_critical_ms": _env_float("THRESHOLD_PING_CRITICAL_MS", float(thresholds.get("ping_critical_ms"))),
        }
        self.telemetry_stale_seconds = _env_int("TELEMETRY_STALE_SECONDS", int(values.get("telemetry_stale_seconds", DEFAULTS["telemetry_stale_seconds"])))
        self.offline_failures = _env_int("OFFLINE_FAILURES", int(values.get("offline_failures", DEFAULTS["offline_failures"])))
        self.recovery_successes = _env_int("RECOVERY_SUCCESSES", int(values.get("recovery_successes", DEFAULTS["recovery_successes"])))
        self.attention_limit = int(values.get("attention_limit", DEFAULTS["attention_limit"]))
        self.alerts_limit = int(values.get("alerts_limit", DEFAULTS["alerts_limit"]))
        self.db_path = os.path.join(base_dir, values.get("db_path", DEFAULTS["db_path"]))
        self.virt_db_path = os.path.join(base_dir, values.get("virt_db_path", DEFAULTS["virt_db_path"]))
        self.mail_db_path = os.path.join(base_dir, values.get("mail_db_path", DEFAULTS["mail_db_path"]))
        self.smtp_host = os.environ.get("SMTP_HOST") or values.get("smtp_host") or None
        self.smtp_port = _env_int("SMTP_PORT", int(values.get("smtp_port", DEFAULTS["smtp_port"])))
        self.smtp_username = os.environ.get("SMTP_USERNAME") or values.get("smtp_username") or None
        self.smtp_password = os.environ.get("SMTP_PASSWORD") or values.get("smtp_password") or None
        self.smtp_from = os.environ.get("SMTP_FROM") or values.get("smtp_from") or None
        self.smtp_tls = _env_bool("SMTP_TLS", bool(values.get("smtp_tls", DEFAULTS["smtp_tls"])))
        self.smtp_timeout = _env_int("SMTP_CONNECTION_TIMEOUT", int(values.get("smtp_timeout", DEFAULTS["smtp_timeout"])))
        self.smtp_retry_limit = _env_int("SMTP_RETRY_LIMIT", int(values.get("smtp_retry_limit", DEFAULTS["smtp_retry_limit"])))
        self.mail_max_per_minute = _env_int("MAIL_MAX_PER_MINUTE", int(values.get("mail_max_per_minute", DEFAULTS["mail_max_per_minute"])))
        self.mail_queue_limit = _env_int("MAIL_QUEUE_LIMIT", int(values.get("mail_queue_limit", DEFAULTS["mail_queue_limit"])))
        self.dashboard_url = os.environ.get("DASHBOARD_URL") or values.get("dashboard_url") or None
        self.admin_username = os.environ.get("ADMIN_USERNAME") or values.get("admin_username") or None
        self.admin_password_hash = os.environ.get("ADMIN_PASSWORD_HASH") or values.get("admin_password_hash") or None
        self.session_cookie_secure = _env_bool("SESSION_COOKIE_SECURE", bool(values.get("session_cookie_secure", DEFAULTS["session_cookie_secure"])))
        self.report_export_auth_required = _env_bool("REPORT_EXPORT_AUTH_REQUIRED", bool(values.get("report_export_auth_required", DEFAULTS["report_export_auth_required"])))

        self.settings_path = os.path.join(base_dir, "config", "settings.yaml")
        self.inventory_path = os.environ.get("INVENTORY_PATH") or os.path.join(base_dir, "config", "servers.yaml")


def load_settings(base_dir):
    load_env_file(os.path.join(base_dir, ".env"))
    values = dict(DEFAULTS)
    settings_path = os.path.join(base_dir, "config", "settings.yaml")
    if os.path.isfile(settings_path):
        with open(settings_path, "r", encoding="utf-8") as fh:
            _deep_merge(values, yaml.safe_load(fh) or {})
    return Settings(base_dir, values)
