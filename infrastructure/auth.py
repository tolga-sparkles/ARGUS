import functools
import threading
import time

from flask import jsonify, redirect, request, session, url_for

MAX_ATTEMPTS = 5
WINDOW_SECONDS = 60
BLOCK_SECONDS = 30

_failures = {}
_failures_lock = threading.Lock()


def _client_key():
    return request.remote_addr or "unknown"


def is_blocked():
    key = _client_key()
    with _failures_lock:
        attempts = _failures.get(key, [])
        now = time.time()
        attempts = [ts for ts in attempts if now - ts < WINDOW_SECONDS]
        _failures[key] = attempts
        if len(attempts) >= MAX_ATTEMPTS:
            newest = max(attempts)
            if now - newest < BLOCK_SECONDS:
                return True
        return False


def record_failure():
    key = _client_key()
    with _failures_lock:
        _failures.setdefault(key, []).append(time.time())


def clear_failures():
    key = _client_key()
    with _failures_lock:
        _failures.pop(key, None)


def admin_login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_authenticated"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Authentication required"}), 401
            next_url = request.path if request.path.startswith("/admin") else None
            target = url_for("admin_login")
            if next_url:
                target = target + "?next=" + next_url
            return redirect(target)
        return view(*args, **kwargs)
    return wrapped
