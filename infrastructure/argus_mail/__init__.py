import threading

from infrastructure.argus_mail.daily import DailyReportService
from infrastructure.argus_mail.engine import NotificationEngine
from infrastructure.argus_mail.mailer import Mailer
from infrastructure.argus_mail.store import MailStore
from infrastructure.argus_mail.worker import MailWorker

_lock = threading.Lock()
_runtime = None


class ArgusMailRuntime:
    def __init__(self, store, mailer, engine, worker, daily):
        self.store = store
        self.mailer = mailer
        self.engine = engine
        self.worker = worker
        self.daily = daily


def init_argus_mail(settings, tracker, collector=None, virt_store=None, incident_store=None):
    global _runtime
    with _lock:
        store = MailStore(settings.mail_db_path)
        mailer = Mailer(settings)
        engine = NotificationEngine(store, settings, tracker, collector, virt_store)
        worker = MailWorker(store, mailer, settings, engine)
        daily = DailyReportService(store, settings, tracker, collector, virt_store, incident_store)
        worker.start()
        daily.start()
        _runtime = ArgusMailRuntime(store, mailer, engine, worker, daily)
        return _runtime


def get_runtime():
    return _runtime


def emit(server, previous_state, new_state, reason, value, metrics, now):
    runtime = get_runtime()
    if runtime is None:
        return
    runtime.engine.emit_transition(server, previous_state, new_state, reason, value, metrics, now)
