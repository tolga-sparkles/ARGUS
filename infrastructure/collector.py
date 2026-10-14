import threading
import time

from infrastructure.inventory import enabled_servers, load_inventory
from infrastructure.models import ServerMetrics
from infrastructure.snapshot import build_empty_overview, build_overview


class Collector:
    def __init__(self, provider, engine, inventory, settings):
        self.provider = provider
        self.engine = engine
        self.inventory = inventory
        self.settings = settings
        self.snapshot = None
        self.last_result = None
        self.started_at = time.time()
        self._lock = threading.Lock()

    def start(self):
        thread = threading.Thread(target=self._loop, daemon=True)
        thread.start()

    def _loop(self):
        while True:
            try:
                self.collect_once()
            except Exception:
                pass
            time.sleep(max(1, self.settings.collect_interval))

    def collect_once(self):
        servers = enabled_servers(self.inventory)
        result = self.provider.collect(servers)
        if result.ok:
            for server in servers:
                metrics = result.metrics.get(server.id) or ServerMetrics(server_id=server.id)
                self.engine.evaluate(server, metrics)
        snapshot = build_overview(self.engine, servers, self.settings, result)
        with self._lock:
            self.snapshot = snapshot
            self.last_result = result
        return snapshot

    def get_snapshot(self):
        with self._lock:
            if self.snapshot is not None:
                return self.snapshot
        return build_empty_overview(enabled_servers(self.inventory), self.settings)

    def inventory_count(self):
        return len(enabled_servers(self.inventory))

    def get_last_result(self):
        with self._lock:
            return self.last_result

    def reload_inventory(self):
        inventory = load_inventory(self.settings.inventory_path)
        with self._lock:
            self.inventory = inventory
        self.engine.prune({server.id for server in inventory})
        return inventory
