from dataclasses import dataclass, field
from enum import Enum


class ServerState(str, Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    OFFLINE = "offline"
    NO_TELEMETRY = "no_telemetry"
    SUSPECT = "suspect"


SEVERITY_ORDER = {
    ServerState.OFFLINE: 0,
    ServerState.CRITICAL: 1,
    ServerState.WARNING: 2,
    ServerState.NO_TELEMETRY: 3,
    ServerState.HEALTHY: 4,
    ServerState.SUSPECT: 5,
}

ATTENTION_STATES = (ServerState.OFFLINE, ServerState.CRITICAL, ServerState.WARNING)


@dataclass
class Server:
    id: str
    hostname: str
    display_name: str
    ip: str
    site: str
    role: str
    environment: str
    os: str
    enabled: bool
    prometheus_instance: str = ""


@dataclass
class PingInfo:
    data_available: bool = False
    reachable: bool = None
    latency_ms: float = None


@dataclass
class DiskInfo:
    highest_usage_percent: float = None
    total_bytes: float = None
    used_bytes: float = None
    volumes: list = field(default_factory=list)


@dataclass
class ServerMetrics:
    server_id: str
    ping: PingInfo = field(default_factory=PingInfo)
    cpu_percent: float = None
    cpu_cores: float = None
    memory_percent: float = None
    memory_total_bytes: float = None
    memory_used_bytes: float = None
    disk: DiskInfo = field(default_factory=DiskInfo)
    uptime_seconds: float = None
    exporter_hostname: str = None
    last_seen: str = None
    telemetry_state: str = "absent"
    telemetry_age_seconds: float = None


@dataclass
class CollectResult:
    ok: bool
    collected_at: float
    prometheus_connected: bool
    ping_data_seen: bool
    error: str = None
    metrics: dict = field(default_factory=dict)
    query_count: int = 0
    duration_ms: float = 0.0
    net_rx_bps: float = None
    net_tx_bps: float = None


@dataclass
class ServerHealth:
    server_id: str
    state: ServerState
    reason: str = None
    value: str = None
    state_since: float = None
    metrics: ServerMetrics = None
    suspect: bool = False
