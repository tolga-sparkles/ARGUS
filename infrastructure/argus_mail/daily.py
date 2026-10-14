import threading
import time
from datetime import datetime, timedelta, timezone

from infrastructure.argus_mail.events import fmt_duration, trt_text
from infrastructure.argus_mail.mailer import render


def _trt_now():
    return datetime.now(timezone.utc) + timedelta(hours=3)


class DailyReportService:
    def __init__(self, store, settings, tracker, collector=None, virt_store=None, incident_store=None):
        self.store = store
        self.settings = settings
        self.tracker = tracker
        self.collector = collector
        self.virt_store = virt_store
        self.incident_store = incident_store
        self._stop = threading.Event()
        self._last_sent_date = None

    def start(self):
        thread = threading.Thread(target=self._loop, daemon=True)
        thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:
                pass
            self._stop.wait(30.0)

    def _tick(self):
        config = self.store.get_daily_report_config()
        if config is None or not config["enabled"]:
            return
        if self.settings.demo_mode:
            return
        now = _trt_now()
        today = now.strftime("%Y-%m-%d")
        if self._last_sent_date == today:
            return
        scheduled = now.replace(hour=config["hour"], minute=config["minute"], second=0, microsecond=0)
        if now >= scheduled:
            self._last_sent_date = today
            self.send_now()

    def send_now(self):
        config = self.store.get_daily_report_config()
        if config is None:
            return False, "Daily report config not found"
        settings_map = self.store.get_settings()
        if settings_map.get("email_enabled", "1") != "1":
            return False, "Email notifications disabled"
        if self.settings.demo_mode:
            return True, "Demo mode: daily report simulated"

        recipients = []
        if config.get("recipient_group_id"):
            recipients = self.store.group_recipient_emails(config["recipient_group_id"])
        if not recipients:
            return False, "No recipients configured"
        return self._build_and_send(config, recipients)

    def send_to(self, email):
        config = self.store.get_daily_report_config()
        if config is None:
            return False, "Daily report config not found"
        if self.settings.demo_mode:
            return True, "Demo mode: daily report simulated"
        return self._build_and_send(config, [email])

    def _build_and_send(self, config, recipients):
        report = self._build_report(config)
        template = self.store.get_template(template_type="daily_report")
        if template is None:
            return False, "Daily report template not found"
        payload = {
            "report_date": _trt_now().strftime("%d %B %Y"),
            "report_time": _trt_now().strftime("%H:%M"),
            "report_body": report["text"],
            "report_html": report["html"],
            "started_at": trt_text(time.time()),
        }
        subject = render(template["subject_template"], payload)
        html_body = render(template["html_body"], payload)
        text_body = render(template["text_body"], payload)

        event_id, _ = self.store.add_event(
            event_type="DAILY_REPORT", severity="info",
            dedup_key="daily:{0}:{1}".format(
                _trt_now().strftime("%Y-%m-%d"), int(time.time() * 1000)),
            payload=payload, server_id=None,
        )
        for email in recipients:
            self.store.enqueue(event_id, email, subject, html_body, text_body)
        return True, "Daily report queued for {0} recipients".format(len(recipients))

    def _build_report(self, config):
        total = healthy = warning = critical = offline = 0
        summary = {}
        if self.collector is not None:
            snapshot = self.collector.get_snapshot()
            if isinstance(snapshot, dict):
                summary = snapshot.get("summary", {}) or {}
        if summary:
            total = summary.get("total", 0)
            healthy = summary.get("healthy", 0)
            warning = summary.get("warning", 0)
            critical = summary.get("critical", 0)
            offline = summary.get("offline", 0)
        availability = round(100.0 * healthy / total, 2) if total else 0.0

        open_issues = []
        if self.tracker is not None:
            open_issues = self.tracker.active_records()
        closed_today = []
        if self.incident_store is not None:
            day_start = time.time() - (time.time() % 86400)
            closed_today = self.incident_store.list_closed(since=day_start, limit=500)

        sev_count = {"critical": 0, "warning": 0, "offline": 0}
        for record in open_issues:
            sev = record.get("severity")
            if sev in sev_count:
                sev_count[sev] += 1

        pressure = []
        if config.get("include_resources") and self.collector is not None:
            snapshot = self.collector.get_snapshot()
            rp = (snapshot or {}).get("resource_pressure", {}) if isinstance(snapshot, dict) else {}
            for key, label in (("highest_cpu", "En Yüksek CPU"), ("highest_memory", "En Yüksek Memory")):
                entry = rp.get(key)
                if entry and entry.get("hostname"):
                    pressure.append({
                        "label": label,
                        "hostname": entry.get("hostname", ""),
                        "value": entry.get("value_text", "—"),
                    })

        virt = None
        if config.get("include_virtualization") and self.virt_store is not None:
            try:
                vsummary = self.virt_store.overview().get("summary", {})
                virt = {
                    "hosts": vsummary.get("hosts", 0),
                    "vms": vsummary.get("vms", 0),
                    "warnings": vsummary.get("vms_warning", 0) + vsummary.get("hosts_warning", 0),
                    "criticals": vsummary.get("vms_critical", 0) + vsummary.get("hosts_critical", 0),
                }
            except Exception:
                virt = None

        offline_list = []
        warning_list = []
        critical_list = []
        if self.collector is not None:
            inventory = self.collector.inventory or []
            for server in inventory:
                health = self.collector.engine.get_health(server.id) if self.collector.engine else None
                if health is None:
                    continue
                state = health.state.value if hasattr(health.state, "value") else str(health.state)
                if state == "offline":
                    offline_list.append(server)
                elif state == "warning":
                    warning_list.append(server)
                elif state == "critical":
                    critical_list.append(server)

        return {
            "text": self._text_body(config, total, healthy, warning, critical, offline,
                                    availability, open_issues, closed_today, sev_count,
                                    pressure, virt, offline_list, warning_list, critical_list),
            "html": self._html_body(config, total, healthy, warning, critical, offline,
                                    availability, open_issues, closed_today, sev_count,
                                    pressure, virt, offline_list, warning_list, critical_list),
        }

    def _text_body(self, config, total, healthy, warning, critical, offline, availability,
                   open_issues, closed_today, sev_count, pressure, virt,
                   offline_list, warning_list, critical_list):
        lines = []
        if config.get("include_summary"):
            lines.append("GENEL DURUM")
            lines.append("-------------")
            lines.append("{0} izlenen sunucu".format(total))
            lines.append("{0} Healthy · {1} Warning · {2} Critical · {3} Offline".format(
                healthy, warning, critical, offline))
        if config.get("include_availability"):
            lines.append("Availability: {0:.2f}%".format(availability))
        if config.get("include_incidents"):
            lines.append("")
            lines.append("İNCİDENT ÖZETİ")
            lines.append("-------------")
            lines.append("Bugün: {0} incident · {1} açık · {2} çözüldü".format(
                len(open_issues) + len(closed_today), len(open_issues), len(closed_today)))
            lines.append("Açık: {0} Critical · {1} Warning · {2} Offline".format(
                sev_count["critical"], sev_count["warning"], sev_count["offline"]))
        if open_issues and (config.get("include_criticals") or config.get("include_offline")
                            or config.get("include_warnings")):
            lines.append("")
            lines.append("AÇIK SORUNLAR")
            lines.append("-------------")
            for record in open_issues:
                lines.append("{0} ({1}) · {2} · {3}".format(
                    record.get("hostname", ""), record.get("ip", ""),
                    record.get("severity", "").upper(), record.get("peak_value") or "—"))
        if pressure:
            lines.append("")
            lines.append("KAYNAK BASKISI")
            lines.append("--------------")
            for entry in pressure:
                lines.append("{0}: {1} ({2})".format(entry["label"], entry["hostname"], entry["value"]))
        if config.get("include_offline") and offline_list:
            lines.append("")
            lines.append("OFFLINE SUNUCULAR")
            lines.append("-----------------")
            for server in offline_list:
                lines.append("{0} ({1})".format(server.hostname, server.ip or "—"))
        if config.get("include_warnings") and warning_list:
            lines.append("")
            lines.append("WARNING SUNUCULAR")
            lines.append("-----------------")
            for server in warning_list:
                lines.append(server.hostname)
        if config.get("include_criticals") and critical_list:
            lines.append("")
            lines.append("CRITICAL SUNUCULAR")
            lines.append("------------------")
            for server in critical_list:
                lines.append(server.hostname)
        if virt is not None:
            lines.append("")
            lines.append("SANALLAŞTIRMA")
            lines.append("-------------")
            lines.append("{0} Host · {1} VM · {2} Warning · {3} Critical".format(
                virt["hosts"], virt["vms"], virt["warnings"], virt["criticals"]))
        return "\n".join(lines)

    def _html_body(self, config, total, healthy, warning, critical, offline, availability,
                   open_issues, closed_today, sev_count, pressure, virt,
                   offline_list, warning_list, critical_list):
        GREEN = "#3fb950"
        AMBER = "#d29922"
        RED = "#f85149"
        MUTED = "#98a1ad"
        DIM = "#767f8a"
        TEXT = "#e1e4e8"
        STRONG = "#f0f6fc"

        def sec(title, rows):
            html = ('<h3 style="color:#58a6ff;font-size:13px;letter-spacing:1px;margin:22px 0 8px;text-transform:uppercase">{0}</h3>'
                    '<table style="width:100%;border-collapse:collapse;font-size:13px">').format(title)
            for cells in rows:
                html += "<tr>" + "".join(
                    '<td style="padding:5px 0;color:{0};border-bottom:1px solid rgba(255,255,255,0.06)">{1}</td>'.format(
                        MUTED if idx % 2 == 0 else STRONG, str(cells[idx]))
                    for idx in range(len(cells))) + "</tr>"
            html += "</table>"
            return html

        parts = []
        if config.get("include_summary"):
            parts.append(sec("GENEL DURUM", [
                ("İzlenen sunucu", '<b style="color:{0}">{1}</b>'.format(STRONG, total)),
                ("Durum", '{0} <span style="color:{1}">Healthy</span> · {2} <span style="color:{3}">Warning</span> · {4} <span style="color:{5}">Critical</span> · {6} <span style="color:{7}">Offline</span>'.format(
                    healthy, GREEN, warning, AMBER, critical, RED, offline, RED)),
            ]))
        if config.get("include_availability"):
            parts.append(('<p style="margin:10px 0 0;font-size:15px">Availability: <b style="color:{0}">{1:.2f}%</b></p>').format(
                GREEN if availability >= 99 else AMBER if availability >= 95 else RED, availability))
        if config.get("include_incidents"):
            parts.append(sec("İNCİDENT ÖZETİ", [
                ("Bugün", "{0} incident · {1} açık · {2} çözüldü".format(
                    len(open_issues) + len(closed_today), len(open_issues), len(closed_today))),
                ("Açık", '{0} <span style="color:{1}">Critical</span> · {2} <span style="color:{3}">Warning</span> · {4} <span style="color:{5}">Offline</span>'.format(
                    sev_count["critical"], RED, sev_count["warning"], AMBER, sev_count["offline"], RED)),
            ]))
        if open_issues and (config.get("include_criticals") or config.get("include_offline")
                            or config.get("include_warnings")):
            rows = []
            for record in open_issues:
                sev = record.get("severity", "")
                color = {"critical": RED, "offline": RED, "warning": AMBER}.get(sev, TEXT)
                rows.append((
                    '<b>{0}</b><br><span style="color:{1};font-size:11px">{2}</span>'.format(
                        record.get("hostname", ""), DIM, record.get("ip", "")),
                    '<span style="color:{0};font-weight:700">{1}</span>'.format(color, sev.upper()),
                    str(record.get("peak_value") or "—"),
                ))
            parts.append(sec("AÇIK SORUNLAR", rows))
        if pressure:
            parts.append(sec("KAYNAK BASKISI", [
                (entry["label"], entry["hostname"], '<b style="color:{0}">{1}</b>'.format(STRONG, entry["value"]))
                for entry in pressure
            ]))
        if config.get("include_offline") and offline_list:
            parts.append(sec("OFFLINE SUNUCULAR", [
                ("{0} ({1})".format(server.hostname, server.ip or "—"),) for server in offline_list
            ]))
        if config.get("include_warnings") and warning_list:
            parts.append(sec("WARNING SUNUCULAR", [(server.hostname,) for server in warning_list]))
        if config.get("include_criticals") and critical_list:
            parts.append(sec("CRITICAL SUNUCULAR", [(server.hostname,) for server in critical_list]))
        if virt is not None:
            parts.append(sec("SANALLAŞTIRMA", [
                ("Host", virt["hosts"]),
                ("VM", virt["vms"]),
                ("Warning", '<span style="color:{0}">{1}</span>'.format(AMBER, virt["warnings"])),
                ("Critical", '<span style="color:{0}">{1}</span>'.format(RED, virt["criticals"])),
            ]))
        if not parts:
            return '<p style="color:{0}">Raporlanacak veri yok.</p>'.format(DIM)
        return "".join(parts)
