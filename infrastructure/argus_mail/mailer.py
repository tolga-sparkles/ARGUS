import os
import re
import smtplib
import socket
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

PLACEHOLDER_RE = re.compile(r"\{\{([a-zA-Z0-9_]+)\}\}")


def render(template_text, payload):
    payload = payload or {}

    def replace(match):
        key = match.group(1)
        value = payload.get(key)
        if value is None:
            return ""
        return str(value)

    return PLACEHOLDER_RE.sub(replace, template_text)


def logo_bytes(settings, size="small"):
    filename = "argus_banner.png" if size == "banner" else "argus_small.png"
    path = os.path.join(settings.base_dir, "static", "img", filename)
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except Exception:
        return None


FOOTER_HTML = (
    '<br>'
    '<div style="font-family:Arial,Helvetica,sans-serif;max-width:640px;margin:16px auto 0;'
    'text-align:center;border-top:1px solid #21262d;padding-top:16px">'
    '<img src="cid:argus-logo" alt="ARGUS" style="width:520px;max-width:100%;height:auto;opacity:0.95">'
    '<div style="color:#767f8a;font-size:11px;margin-top:8px">'
    'ARGUS Operations Center · Example Organization</div></div>'
)

FOOTER_HTML_NO_LOGO = (
    '<br>'
    '<div style="font-family:Arial,Helvetica,sans-serif;max-width:640px;margin:16px auto 0;'
    'text-align:center;border-top:1px solid #21262d;padding-top:14px">'
    '<div style="color:#767f8a;font-size:11px">'
    'ARGUS Operations Center · Example Organization</div></div>'
)

FOOTER_TEXT = "\n\n--\nARGUS Operations Center · Example Organization\n"


class Mailer:
    def __init__(self, settings):
        self.settings = settings
        self.host = settings.smtp_host
        self.port = settings.smtp_port
        self.username = settings.smtp_username
        self.password = settings.smtp_password
        self.from_address = settings.smtp_from
        self.use_tls = settings.smtp_tls
        self.timeout = settings.smtp_timeout
        self._logo_cache = {}

    def configured(self):
        return bool(self.host)

    def _logo_bytes(self, size="small"):
        if size not in self._logo_cache:
            self._logo_cache[size] = logo_bytes(self.settings, size)
        return self._logo_cache[size]

    @staticmethod
    def _inline_image(data, content_id):
        image = MIMEImage(data, _subtype="png")
        image.add_header("Content-ID", "<{0}>".format(content_id))
        image.add_header("Content-Disposition", "inline")
        return image

    def send(self, recipient_email, subject, html_body, text_body):
        if not self.configured():
            raise ValueError("SMTP not configured")

        body = (html_body or "").rstrip()
        has_banner = "cid:argus-banner" in body
        if has_banner:
            footer = FOOTER_HTML_NO_LOGO
        elif self._logo_bytes("small"):
            footer = FOOTER_HTML
        else:
            footer = FOOTER_HTML_NO_LOGO

        message = MIMEMultipart("related")
        message["Subject"] = subject
        message["From"] = self.from_address or "argus@localhost"
        message["To"] = recipient_email

        alternative = MIMEMultipart("alternative")
        alternative.attach(MIMEText((text_body or "").rstrip() + FOOTER_TEXT, "plain", "utf-8"))
        alternative.attach(MIMEText(body + footer, "html", "utf-8"))
        message.attach(alternative)

        if has_banner:
            banner = self._logo_bytes("banner")
            if banner:
                message.attach(self._inline_image(banner, "argus-banner"))
        elif "cid:argus-logo" in footer:
            small = self._logo_bytes("small")
            if small:
                message.attach(self._inline_image(small, "argus-logo"))

        with smtplib.SMTP(self.host, int(self.port), timeout=self.timeout) as smtp:
            if self.use_tls:
                smtp.starttls()
            if self.username:
                smtp.login(self.username, self.password or "")
            refused = smtp.sendmail(message["From"], [recipient_email], message.as_string())
        if refused:
            raise ValueError("SMTP refused recipient: {0}".format(list(refused.keys())))
        return message["Message-ID"] if message.get("Message-ID") else None

    def test_connection(self):
        if not self.configured():
            return {"ok": False, "error": "SMTP not configured"}
        try:
            with smtplib.SMTP(self.host, int(self.port), timeout=self.timeout) as smtp:
                if self.use_tls:
                    smtp.starttls()
                if self.username:
                    smtp.login(self.username, self.password or "")
                smtp.noop()
            return {"ok": True, "error": ""}
        except (smtplib.SMTPException, socket.error, ValueError) as exc:
            return {"ok": False, "error": str(exc)[:200]}
