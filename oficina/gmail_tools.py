import base64
import re
from email.mime.text import MIMEText
from html.parser import HTMLParser

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def _service():
    creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    return build("gmail", "v1", credentials=creds)


def list_unprocessed(max_results=20):
    """Correos de la bandeja de entrada sin nuestra etiqueta 'oficina'."""
    svc = _service()
    res = svc.users().messages().list(
        userId="me", q="in:inbox -label:oficina newer_than:2d", maxResults=max_results
    ).execute()
    return res.get("messages", [])


def get_message(msg_id):
    svc = _service()
    m = svc.users().messages().get(
        userId="me", id=msg_id, format="metadata",
        metadataHeaders=["From", "Subject", "Date"]
    ).execute()
    headers = {h["name"]: h["value"] for h in m["payload"]["headers"]}
    return {
        "id": m["id"], "thread_id": m["threadId"],
        "sender": headers.get("From", ""), "subject": headers.get("Subject", ""),
        "snippet": m.get("snippet", ""),
    }


# ---------- lectura del cuerpo ----------
class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in ("br", "p", "div", "tr", "li"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def _html_to_text(html: str) -> str:
    p = _HTMLText()
    p.feed(html)
    text = "".join(p.parts)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def _decode(data: str) -> str:
    data += "=" * (-len(data) % 4)   # Gmail a veces omite el relleno base64
    return base64.urlsafe_b64decode(data).decode("utf-8", "ignore")


def _find(part, mime):
    if part.get("mimeType") == mime and part.get("body", {}).get("data"):
        return _decode(part["body"]["data"])
    for p in part.get("parts") or []:
        t = _find(p, mime)
        if t:
            return t
    return ""


def get_body_text(msg_id, max_chars=4000):
    """Cuerpo del correo como texto. Prefiere text/plain; si no hay, convierte el HTML."""
    svc = _service()
    m = svc.users().messages().get(userId="me", id=msg_id, format="full").execute()
    payload = m["payload"]
    text = _find(payload, "text/plain")
    if not text.strip():
        html = _find(payload, "text/html")
        text = _html_to_text(html) if html else ""
    return text.strip()[:max_chars]


# ---------- etiquetas y borradores (no existe función de envío ni de borrado) ----------
def ensure_label(name):
    svc = _service()
    labels = svc.users().labels().list(userId="me").execute()["labels"]
    for l in labels:
        if l["name"] == name:
            return l["id"]
    return svc.users().labels().create(userId="me", body={"name": name}).execute()["id"]


def apply_labels(msg_id, label_names):
    svc = _service()
    ids = [ensure_label(n) for n in label_names]
    svc.users().messages().modify(
        userId="me", id=msg_id, body={"addLabelIds": ids}
    ).execute()


def create_draft(thread_id, to, subject, body):
    svc = _service()
    msg = MIMEText(body)
    msg["to"], msg["subject"] = to, subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return svc.users().drafts().create(
        userId="me", body={"message": {"raw": raw, "threadId": thread_id}}
    ).execute()
