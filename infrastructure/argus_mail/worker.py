import threading
import time

BACKOFF_SCHEDULE = [10, 20, 40, 80, 160, 300]


class MailWorker:
    def __init__(self, store, mailer, settings, notify_engine):
        self.store = store
        self.mailer = mailer
        self.settings = settings
        self.notify_engine = notify_engine
        self._stop = threading.Event()
        self.degraded = False
        self._lock = threading.Lock()

    def start(self):
        thread = threading.Thread(target=self._loop, daemon=True)
        thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            try:
                self._drain()
            except Exception:
                pass
            self._stop.wait(2.0)

    def _drain(self):
        if self.settings.demo_mode:
            return
        settings_map = self.store.get_settings()
        if settings_map.get("email_enabled", "1") != "1":
            return

        max_per_minute = self.settings.mail_max_per_minute
        sent_this_minute = 0
        minute_start = time.time()

        while sent_this_minute < max_per_minute:
            if self._stop.is_set():
                break
            item = self.store.next_due()
            if item is None:
                break
            try:
                message_id = self.mailer.send(
                    item["recipient_email"], item["subject"],
                    item["html_body"], item["text_body"],
                )
                self.store.mark_sent(item["id"], message_id)
            except Exception as exc:
                max_attempts = self.settings.smtp_retry_limit
                backoff = BACKOFF_SCHEDULE[min(item["attempts"], len(BACKOFF_SCHEDULE) - 1)]
                self.store.mark_failed(item["id"], exc, backoff, max_attempts)
                if item["attempts"] + 1 >= max_attempts:
                    pass
                self._set_degraded(True)
            sent_this_minute += 1
            elapsed = time.time() - minute_start
            if elapsed >= 60.0 and sent_this_minute < max_per_minute:
                minute_start = time.time()
                sent_this_minute = 0
            elif elapsed < 60.0 and sent_this_minute >= max_per_minute:
                time.sleep(max(0.0, 60.0 - elapsed))
                minute_start = time.time()
                sent_this_minute = 0

        queue_size = self.store.queue_size()
        self._set_degraded(queue_size >= self.settings.mail_queue_limit)

    def _set_degraded(self, value):
        with self._lock:
            self.degraded = value

    def queue_health(self):
        return {
            "pending": self.store.queue_size(),
            "degraded": self.degraded,
            "limit": self.settings.mail_queue_limit,
        }
