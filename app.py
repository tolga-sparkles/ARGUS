import os
import sys

from flask import Flask, jsonify, redirect, render_template, request, session
from werkzeug.security import check_password_hash

from infrastructure import auth
from infrastructure.api import register_api
from infrastructure.api_virt import register_virt_api
from infrastructure.collector import Collector
from infrastructure.config import load_settings
from infrastructure.demo import DemoProvider, demo_inventory
from infrastructure.health import HealthEngine
from infrastructure.incidents import IncidentStore, IncidentTracker
from infrastructure.inventory import load_inventory, write_exporter_targets, write_ping_targets
from infrastructure.prometheus import PrometheusProvider
from infrastructure.virtualization import VirtualizationStore

try:
    from infrastructure.argus_mail import init_argus_mail
    from infrastructure.argus_mail.api import bp as mail_api_bp
except Exception:
    init_argus_mail = None
    mail_api_bp = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

HELP_PAGES = [
    {"path": "/", "description": "Overview dashboard — fleet summary, servers requiring attention, resource pressure, fleet health, active alerts, collector health, recent events."},
    {"path": "/overview", "description": "Redirects to /."},
    {"path": "/servers", "description": "Server inventory / fleet page — compact table with search, status/site/role/OS filters, sorting, pagination and server detail drawer."},
    {"path": "/alerts", "description": "Active infrastructure alerts — normalized conditions requiring attention, clickable to server detail."},
    {"path": "/history", "description": "Incident and state change history — persisted incidents with timeline, filters and detail drawer."},
    {"path": "/wall", "description": "Wall Mode — NOC/TV display without sidebar, role-grouped server matrix and active issues, auto refresh."},
    {"path": "/wall2 · /wallmode2", "description": "Wall Mode 2 — second NOC/TV layout: status banner, KPI row, active alerts panel, fleet status matrix (auto-rotating pages), network throughput and global CPU charts. Same data source, separate screen."},
    {"path": "/virtualization", "description": "Sanallaştırma ortamları sayfası. Datacenter → Cluster → Host → VM ağacında sunucuların CPU/RAM/disk kullanımını ve durumlarını gösterir; node'a tıklayınca detay paneli açılır."},
    {"path": "/admin", "description": "Sanallaştırma modülünün yönetim paneli. Host, VM, datacenter ve cluster ekleme / düzenleme / silme. Sekmeler: /admin/hosts, /admin/vms, /admin/groups, /admin/settings."},
    {"path": "/?demo=manager", "description": "Management Demo Mode — deterministic presentation dataset with 16 servers (12 healthy, 2 warning, 1 critical, 1 offline). Fully isolated from production telemetry, incident DB and notifications; shows a permanent 'DEMO · SIMULATED DATA' badge."},
    {"path": "/servers?demo=manager /alerts?demo=manager /history?demo=manager /wall?demo=manager", "description": "Management Demo Mode on the other pages. The demo=manager parameter is preserved automatically across sidebar navigation and API calls."},
    {"path": "/help", "description": "This page — pages and API endpoint reference."},
]

HELP_ENDPOINTS = [
    {"method": "GET", "path": "/api/health", "description": "Application health, Prometheus connection state, inventory count, demo mode."},
    {"method": "GET", "path": "/api/overview", "description": "Normalized overview snapshot: summary, attention, resource_pressure, groups, collector_health, recent_events."},
    {"method": "GET", "path": "/api/servers/<server_id>", "description": "Server detail. Accepts only stable inventory IDs — IP, hostname or PromQL are rejected with 404."},
    {"method": "GET/POST", "path": "/api/servers/export", "description": "Server report export (Excel/CSV/PDF). GET: same filters as /api/servers (pagination does not limit export). POST: scope (filtered/selected/all), server_ids, columns, report_type presets. Formats/columns/server_ids are whitelisted.", "params": "format, q, status, site, role, os, datacenter, host, sort"},
    {"method": "GET", "path": "/api/servers", "description": "Fleet list with current state only (no historical data).", "params": "q, status, site, role, os, datacenter, host, sort, page, per_page"},
    {"method": "GET", "path": "/api/alerts", "description": "Active alerts, normalized (severity, metric, value, started_at, duration, message).", "params": "severity, q, site, role"},
    {"method": "GET", "path": "/api/history", "description": "Incident history from SQLite persistence with per-incident timeline.", "params": "q, status, severity, range, page, per_page"},
    {"method": "GET", "path": "/api/*?demo=manager", "description": "All API endpoints accept demo=manager to serve the isolated Management Demo dataset instead of real telemetry. Demo requests never touch Prometheus, the Health Engine, incident persistence or any notification pipeline.", "params": "demo=manager"},
    {"method": "GET", "path": "/api/virtualization/overview", "description": "Sanallaştırma ağacını hazır halde döner: datacenter'lar, cluster'lar, host'lar ve VM'ler durum ve kullanım değerleriyle birlikte. Sayfadaki tree ve KPI kartları bu veriyi kullanır."},
    {"method": "GET", "path": "/api/datacenters · /api/clusters", "description": "Datacenter ve cluster listesi (içlerindeki host/VM sayılarıyla)."},
    {"method": "GET/POST/PUT/DELETE", "path": "/api/hosts( /<id>)", "description": "Host yönetimi: listeleme, ekleme, düzenleme, silme. Alanlar: ad, IP, cluster, durum, CPU/RAM/disk kullanımı, kapasiteler, not, sıra, aktiflik."},
    {"method": "GET/POST/PUT/DELETE", "path": "/api/vms( /<id>)", "description": "VM yönetimi: listeleme, ekleme, düzenleme, silme. Alanlar: ad, bağlı olduğu host, IP, işletim sistemi, rol, durum, CPU/RAM/disk kullanımı, uptime, not, sıra, aktiflik."},
    {"method": "POST", "path": "/api/virtualization/reseed", "description": "Sanallaştırma verisini demo seed verisine döndürür (1 datacenter, 1 cluster, 2 host, 10 VM)."},
]


def create_app():
    settings = load_settings(BASE_DIR)
    inventory = load_inventory(settings.inventory_path)
    if settings.demo_mode and not inventory:
        inventory = demo_inventory()
    if not settings.demo_mode:
        write_ping_targets(settings.inventory_path, inventory)
        write_exporter_targets(settings.inventory_path, inventory)

    if settings.demo_mode:
        provider = DemoProvider(settings)
    else:
        provider = PrometheusProvider(settings)

    incident_store = IncidentStore(settings.db_path)
    tracker = IncidentTracker(incident_store)
    engine = HealthEngine(settings, tracker)
    collector = Collector(provider, engine, inventory, settings)
    virt_store = VirtualizationStore(settings.virt_db_path, seed_if_empty=False)

    app = Flask(__name__)
    app.secret_key = settings.secret_key
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = settings.session_cookie_secure
    app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 8
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

    if not (settings.admin_username and settings.admin_password_hash):
        print(
            "WARNING: ADMIN_USERNAME / ADMIN_PASSWORD_HASH not configured; "
            "admin authentication is disabled for login attempts.",
            file=sys.stderr,
        )

    @app.after_request
    def add_no_cache_headers(response):
        if response.content_type and response.content_type.startswith("text/html"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        return response

    def _safe_next(value):
        if value and value.startswith("/admin") and not value.startswith("//") and "\\" not in value:
            return value
        return None

    @app.route("/admin/login", methods=["GET", "POST"])
    def admin_login():
        next_url = _safe_next(request.args.get("next") or request.form.get("next"))
        if session.get("admin_authenticated"):
            return redirect(next_url or "/admin")
        error = None
        if request.method == "POST":
            if not (settings.admin_username and settings.admin_password_hash):
                error = "Authentication is not configured."
            elif auth.is_blocked():
                error = "Too many failed attempts. Please wait a moment."
            else:
                username = (request.form.get("username") or "").strip()
                password = request.form.get("password") or ""
                if username == settings.admin_username and check_password_hash(settings.admin_password_hash, password):
                    auth.clear_failures()
                    session.clear()
                    session["admin_authenticated"] = True
                    session["admin_username"] = username
                    return redirect(next_url or "/admin")
                auth.record_failure()
                error = "Invalid username or password."
        return render_template(
            "admin_login.html",
            error=error,
            next_url=next_url,
            auth_configured=bool(settings.admin_username and settings.admin_password_hash),
        )

    @app.route("/admin/logout")
    def admin_logout():
        session.clear()
        return redirect("/admin/login")

    @app.route("/")
    def overview_page():
        return render_template("overview.html")

    @app.route("/overview")
    def overview_redirect():
        return redirect("/")

    @app.route("/servers")
    def servers_page():
        return render_template("servers.html")

    @app.route("/alerts")
    def alerts_page():
        return render_template("alerts.html")

    @app.route("/history")
    def history_page():
        return render_template("history.html")

    @app.route("/wall")
    def wall_page():
        return render_template("wall.html")

    @app.route("/wall2")
    @app.route("/wallmode2")
    def wallmode2_page():
        return render_template("wall2.html")

    @app.route("/virtualization")
    def virtualization_page():
        return render_template("virtualization.html")

    @app.route("/admin")
    @app.route("/admin/<tab>")
    @auth.admin_login_required
    def admin_page(tab="dashboard"):
        if tab not in ("dashboard", "servers", "scan", "notifications", "hosts", "vms", "groups", "settings"):
            tab = "dashboard"
        return render_template("admin.html", admin_tab=tab)

    @app.route("/help")
    def help_page():
        return render_template(
            "help.html",
            pages=HELP_PAGES,
            endpoints=HELP_ENDPOINTS,
        )

    @app.route("/help.json")
    def help_json():
        return jsonify({
            "service": "ARGUS",
            "pages": {entry["path"]: entry["description"] for entry in HELP_PAGES},
            "api": {entry["path"]: entry["description"] for entry in HELP_ENDPOINTS},
        })

    @app.context_processor
    def inject_globals():
        path = request.path.strip("/")
        section = path.split("/")[0] if path else ""
        active = section if section in ("servers", "alerts", "history", "wall", "help", "virtualization", "admin") else "overview"
        demo_manager = settings.demo_manager or request.args.get("demo") == "manager"
        return {
            "active_page": active,
            "demo_mode": settings.demo_mode,
            "demo_manager": demo_manager,
            "demo_qs": "?demo=manager" if demo_manager else "",
            "admin_user": session.get("admin_username") if session.get("admin_authenticated") else None,
        }

    register_api(app, collector, settings, incident_store, tracker)
    register_virt_api(app, virt_store)

    if mail_api_bp is not None:
        app.register_blueprint(mail_api_bp)
    if init_argus_mail is not None:
        try:
            init_argus_mail(settings, tracker, collector, virt_store, incident_store)
        except Exception as exc:
            print("WARNING: argus_mail init failed: {0}".format(exc), file=sys.stderr)

    return app, collector


app, collector = create_app()

if __name__ == "__main__":
    settings = load_settings(BASE_DIR)
    collector.start()
    app.run(host=settings.host, port=settings.port, debug=False)
