import base64

from agent.gmail import build_query, html_to_text, parse_message


def b64(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


def message(parts):
    return {
        "id": "x", "internalDate": "1760400000000", "snippet": "hi &amp; bye", "labelIds": ["INBOX"],
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [{"name": "From", "value": "A <a@x.com>"}, {"name": "Subject", "value": "Hello"}],
            "parts": parts,
        },
    }


def test_prefers_plain_text_over_html():
    e = parse_message(message([
        {"mimeType": "text/plain", "body": {"data": b64("plain body")}},
        {"mimeType": "text/html", "body": {"data": b64("<p>html body</p>")}},
    ]), 2000)
    assert e["body"] == "plain body"
    assert e["subject"] == "Hello" and e["snippet"] == "hi & bye" and e["received_at"] == 1760400000


def test_falls_back_to_html_and_ignores_attachments():
    e = parse_message(message([
        {"mimeType": "text/html", "body": {"data": b64("<p>Hi&nbsp;there</p>")}},
        {"mimeType": "text/plain", "filename": "notes.txt", "body": {"data": b64("attachment text")}},
    ]), 2000)
    assert e["body"] == "Hi there"


def test_body_is_truncated():
    e = parse_message(message([{"mimeType": "text/plain", "body": {"data": b64("x" * 5000)}}]), 2000)
    assert len(e["body"]) == 2000


def test_html_strips_scripts_and_styles():
    assert html_to_text("<style>p{}</style><p>Keep</p><script>bad()</script>").strip() == "Keep"


def test_default_query_skips_own_mail_and_noisy_tabs():
    q = build_query(newer_than_days=90)
    assert q.split() == ["-from:me", "newer_than:90d", "-category:promotions", "-category:social"]


def test_all_categories_query():
    assert build_query(after_epoch=5, all_categories=True) == "-from:me after:5"
