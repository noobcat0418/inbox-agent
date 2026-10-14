"""Gmail access: sign-in, listing message ids, and turning a message into plain text.

The scope is gmail.modify so labels can be added. Everything that writes is in labels.py,
which only ever touches labels under "AI/".
"""
import base64
import html
import json
import re

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def _granted_scopes(token_file) -> set[str]:
    try:
        return set(json.loads(token_file.read_text(encoding="utf-8")).get("scopes") or [])
    except (OSError, ValueError):
        return set()


def connect(cfg):
    """Return an authorised Gmail service. Opens a browser for consent the first time."""
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    # A token from an older, narrower scope (e.g. read-only) means signing in again once.
    if cfg.token_file.exists() and set(SCOPES) <= _granted_scopes(cfg.token_file):
        creds = Credentials.from_authorized_user_file(str(cfg.token_file), SCOPES)
    if creds and not creds.valid and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError:
            creds = None  # revoked or expired refresh token: sign in again
    if not creds or not creds.valid:
        if not cfg.credentials_file.exists():
            raise SystemExit(
                f"{cfg.credentials_file.name} not found. Follow README step 0 to create it."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(cfg.credentials_file), SCOPES)
        creds = flow.run_local_server(port=0)
    cfg.token_file.write_text(creds.to_json(), encoding="utf-8")
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def build_query(*, after_epoch=None, newer_than_days=None, all_categories=False) -> str:
    # Mail Mike sent himself is never triaged. Spam and Trash are excluded by the API already.
    parts = ["-from:me"]
    if after_epoch is not None:
        parts.append(f"after:{int(after_epoch)}")
    if newer_than_days is not None:
        parts.append(f"newer_than:{int(newer_than_days)}d")
    if not all_categories:
        parts += ["-category:promotions", "-category:social"]
    return " ".join(parts)


def iter_message_ids(service, query: str):
    """Yield message ids newest-first, one page at a time, so callers can stop early."""
    page_token = None
    while True:
        resp = service.users().messages().list(
            userId="me", q=query, maxResults=100, pageToken=page_token
        ).execute()
        for m in resp.get("messages", []):
            yield m["id"]
        page_token = resp.get("nextPageToken")
        if not page_token:
            return


def fetch(service, msg_id: str, body_chars: int) -> dict:
    msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
    return parse_message(msg, body_chars)


def fetch_headers(service, msg_id: str) -> dict:
    msg = service.users().messages().get(
        userId="me", id=msg_id, format="metadata", metadataHeaders=["From", "Subject", "Date"]
    ).execute()
    return parse_message(msg, 0)


def profile(service) -> dict:
    return service.users().getProfile(userId="me").execute()


def parse_message(msg: dict, body_chars: int) -> dict:
    payload = msg.get("payload", {})
    headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
    body = extract_text(payload)[:body_chars] if body_chars else ""
    return {
        "id": msg["id"],
        "received_at": int(msg.get("internalDate", "0")) // 1000,
        "from": headers.get("from", ""),
        "subject": headers.get("subject", "") or "(no subject)",
        "snippet": html.unescape(msg.get("snippet", "")),
        "labels": msg.get("labelIds", []),
        "body": body,
    }


def extract_text(payload: dict) -> str:
    """Prefer text/plain parts; fall back to stripped HTML. Attachments are ignored."""
    plain, html_parts = [], []
    _walk(payload, plain, html_parts)
    if plain:
        text = "\n".join(plain)
    elif html_parts:
        text = html_to_text("\n".join(html_parts))
    else:
        text = ""
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _walk(part: dict, plain: list, html_parts: list) -> None:
    data = part.get("body", {}).get("data")
    if data and not part.get("filename"):
        mime = part.get("mimeType", "")
        if mime == "text/plain":
            plain.append(_decode(data))
        elif mime == "text/html":
            html_parts.append(_decode(data))
    for sub in part.get("parts") or []:
        _walk(sub, plain, html_parts)


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


def html_to_text(s: str) -> str:
    s = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>|</h\d>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t\r\f\v ]+", " ", s)
    return re.sub(r" *\n *", "\n", s)
