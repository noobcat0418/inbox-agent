"""Ask the model to triage one email, and reject anything outside the allowed shape."""
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

CATEGORIES = ("important", "todo", "fyi", "noise")
UNCLASSIFIED = "unclassified"
PROMPT_FILE = Path(__file__).resolve().parent.parent / "prompts" / "classify.md"
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_CLOSE_TAG = re.compile(r"(?i)<\s*/\s*email\s*>")


@dataclass
class Todo:
    task: str
    due: str | None = None


@dataclass
class Result:
    category: str  # one of CATEGORIES, or UNCLASSIFIED when the model never gave a valid answer
    why: str = ""
    summary: str = ""
    todos: list[Todo] = field(default_factory=list)
    error: str = ""


def system_prompt() -> str:
    return PROMPT_FILE.read_text(encoding="utf-8")


def user_message(email: dict) -> str:
    # Sender, subject and body are all untrusted, so all of them go inside the tags.
    # A forged closing tag in the email can't end the block early.
    received = datetime.fromtimestamp(email["received_at"]).strftime("%Y-%m-%d (%A)")
    inner = (
        f"From: {email['from']}\n"
        f"Subject: {email['subject']}\n\n"
        f"{email['body'] or email['snippet']}"
    )
    inner = _CLOSE_TAG.sub("[/email]", inner)
    return f"Received: {received}\n<email>\n{inner}\n</email>"


def _clip(value, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def parse(raw: str) -> Result:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("model reply is not a JSON object")
    category = str(data.get("category", "")).strip().lower()
    if category not in CATEGORIES:
        raise ValueError(f"category {category!r} is not allowed")
    todos = []
    for item in data.get("todos") or []:
        if not isinstance(item, dict) or not str(item.get("task", "")).strip():
            continue
        due = item.get("due")
        due = due.strip() if isinstance(due, str) and _DATE.fullmatch(due.strip()) else None
        todos.append(Todo(task=_clip(item["task"], 120), due=due))
    return Result(
        category=category,
        why=_clip(data.get("why"), 160),
        summary=_clip(data.get("summary"), 300),
        todos=todos[:5],
    )


def classify(llm, email: dict, system: str | None = None, attempts: int = 2) -> Result:
    system = system or system_prompt()
    user = user_message(email)
    last_error = ""
    for _ in range(attempts):
        try:
            return parse(llm.complete_json(system, user))
        except Exception as e:  # bad JSON, a category outside the allow-list, or a server error
            last_error = f"{type(e).__name__}: {e}"
    return Result(category=UNCLASSIFIED, error=_clip(last_error, 300))
