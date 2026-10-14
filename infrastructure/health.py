import time
from collections import deque
from datetime import datetime, timedelta, timezone

from infrastructure.models import ServerHealth, ServerMetrics, ServerState

try:
    from infrastructure.argus_mail import emit as mail_emit
except Exception:
    mail_emit = None


class _Track:
    def __init__(self):
        self.failures = 0
        self.successes = 0
        self.state = ServerState.HEALTHY
        self.state_since = time.time()
        self.last_reason = None
        self.last_value = None
        self.initialized = False
        self.suspect = False


class HealthEngine:
    def __init__(self, settings, tracker=None):
        self.settings = settings
        self.tracker = tracker
        self._tracks = {}
        self._health = {}
        self._events = deque(maxlen=50)

    def evaluate(self, server, metrics):
        track = self._tracks.setdefault(server.id, _Track())
        now = time.time()
        ping = metrics.ping
        reachable = ping.reachable if ping.data_available else None

        if ping.data_available and reachable is False:
            track.failures += 1
            track.successes = 0
        elif ping.data_available and reachable is True:
            track.failures = 0
            track.successes += 1
        else:
            track.failures = 0
            track.successes = 0

        suspect = False
        if track.failures >= self.settings.offline_failures:
            candidate = ServerState.OFFLINE
            reason = "Unreachable"
            value = None
        elif track.failures > 0:
            suspect = True
            candidate = track.state
            reason = track.last_reason
            value = track.last_value
        elif track.state == ServerState.OFFLINE and track.successes < self.settings.recovery_successes:
            candidate = ServerState.OFFLINE
            reason = "Unreachable"
            value = None
        else:
            candidate, reason, value = self._evaluate_resources(metrics)

        if not track.initialized:
            track.initialized = True
            track.state = candidate
            track.state_since = now
            track.suspect = suspect
            if candidate in (ServerState.CRITICAL, ServerState.WARNING):
                track.last_reason = reason
                track.last_value = value
            self._commit(server, track, metrics, candidate, reason, value)
            if candidate != ServerState.HEALTHY:
                self._notify_tracker(server, track, candidate, reason, value, now)
            self._mail_hook(server, None, candidate, reason, value, metrics, now)
            return

        if candidate != track.state:
            self._emit_transition(server, track, candidate, reason, value, now, metrics)
            track.state = candidate
            track.state_since = now
        track.suspect = suspect

        if candidate in (ServerState.CRITICAL, ServerState.WARNING):
            track.last_reason = reason
            track.last_value = value

        self._commit(server, track, metrics, candidate, reason, value)

    def _commit(self, server, track, metrics, candidate, reason, value):
        self._health[server.id] = ServerHealth(
            server_id=server.id,
            state=candidate,
            reason=reason,
            value=value,
            state_since=track.state_since,
            metrics=metrics,
            suspect=track.suspect,
        )

    def _evaluate_resources(self, metrics):
        if metrics.telemetry_state != "online":
            return ServerState.NO_TELEMETRY, "Telemetry", None

        t = self.settings.thresholds
        checks = []
        if metrics.cpu_percent is not None:
            checks.append(("CPU", metrics.cpu_percent, t["cpu_warning"], t["cpu_critical"], "%"))
        if metrics.memory_percent is not None:
            checks.append(("Memory", metrics.memory_percent, t["memory_warning"], t["memory_critical"], "%"))
        if metrics.disk.highest_usage_percent is not None:
            checks.append(("Disk", metrics.disk.highest_usage_percent, t["disk_warning"], t["disk_critical"], "%"))
        if metrics.ping.data_available and metrics.ping.reachable and metrics.ping.latency_ms is not None:
            checks.append(("Ping", metrics.ping.latency_ms, t["ping_warning_ms"], t["ping_critical_ms"], " ms"))

        worst = None
        for name, value, warn, crit, unit in checks:
            severity = None
            if value >= crit:
                severity = ServerState.CRITICAL
            elif value >= warn:
                severity = ServerState.WARNING
            if severity is None:
                continue
            if worst is None or value > worst[1]:
                worst = (name, value, severity, unit)
        if worst:
            name, value, severity, unit = worst
            return severity, name, "{0}{1}".format(round(value), unit)
        return ServerState.HEALTHY, None, None

    def _emit_transition(self, server, track, candidate, reason, value, now, metrics=None):
        message = self._message_for(candidate, track, reason)
        trt = datetime.fromtimestamp(now, tz=timezone.utc) + timedelta(hours=3)
        self._events.append({
            "at": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
            "time_text": trt.strftime("%H:%M"),
            "server": server.hostname,
            "message": message,
            "severity": candidate.value,
        })
        self._notify_tracker(server, track, candidate, reason, value, now)
        self._mail_hook(server, track.state, candidate, reason, value, metrics, now)

    def _mail_hook(self, server, previous, candidate, reason, value, metrics, now):
        if mail_emit is None:
            return
        try:
            mail_emit(server, previous, candidate, reason, value, metrics, now)
        except Exception:
            pass

    def _message_for(self, candidate, track, reason):
        if candidate == ServerState.OFFLINE:
            return "Host became unreachable"
        if candidate == ServerState.CRITICAL:
            return "{0} entered critical state".format(reason or "Resource")
        if candidate == ServerState.WARNING:
            return "{0} entered warning state".format(reason or "Resource")
        if candidate == ServerState.NO_TELEMETRY:
            return "Exporter telemetry lost"
        if track.state == ServerState.OFFLINE:
            return "Host recovered"
        if track.state == ServerState.NO_TELEMETRY:
            return "Telemetry restored"
        return "{0} returned to normal".format(track.last_reason or "Resource")

    def _notify_tracker(self, server, track, candidate, reason, value, now):
        if self.tracker is None:
            return
        if candidate in (
            ServerState.WARNING,
            ServerState.CRITICAL,
            ServerState.OFFLINE,
            ServerState.NO_TELEMETRY,
        ):
            message = self._message_for(candidate, track, reason)
            if self.tracker.is_open(server.id):
                self.tracker.update(server, candidate.value, reason, value, message, now)
            else:
                self.tracker.open(server, candidate.value, reason, value, message, now)
        elif candidate == ServerState.HEALTHY and self.tracker.is_open(server.id):
            message = self._message_for(candidate, track, reason)
            self.tracker.close(server, message, value, now)

    def get_health(self, server_id):
        return self._health.get(server_id)

    def prune(self, valid_ids):
        for server_id in list(self._health.keys()):
            if server_id not in valid_ids:
                self._health.pop(server_id, None)
                self._tracks.pop(server_id, None)

    def recent_events(self):
        return list(self._events)
