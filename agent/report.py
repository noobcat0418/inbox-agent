"""Markdown output: one summary per run, plus the running to-do list."""
from datetime import datetime

from .classify import CATEGORIES, UNCLASSIFIED


def _when(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%b %d %H:%M")


def _sender(raw: str) -> str:
    # "Jane Doe <jane@x.com>" -> "Jane Doe"
    name = raw.split("<")[0].strip().strip('"')
    return name or raw.strip("<> ")


def render_summary(items: list, *, run_label: str, mode: str, model: str, skipped: int) -> str:
    """items: list of (email, Result) in the order processed."""
    by_cat = {c: [] for c in (*CATEGORIES, UNCLASSIFIED)}
    for email, result in items:
        by_cat[result.category].append((email, result))

    classified = len(items) - len(by_cat[UNCLASSIFIED])
    lines = [
        f"# Inbox summary — {run_label}",
        "",
        f"- **Mode:** {mode}",
        f"- **Processed:** {len(items)} · already done earlier: {skipped}",
        f"- **Classified by:** {model if classified else 'nothing (every email failed; see Errors)'}",
        "",
        "| important | todo | fyi | noise | unclassified |",
        "|---|---|---|---|---|",
        "| " + " | ".join(str(len(by_cat[c])) for c in (*CATEGORIES, UNCLASSIFIED)) + " |",
    ]

    if by_cat["important"]:
        lines += ["", "## Important", ""]
        for email, r in by_cat["important"]:
            lines.append(f"- **{email['subject']}** — {_sender(email['from'])} · {_when(email['received_at'])}")
            lines.append(f"  {r.summary} _({r.why})_")

    todos = [(email, t) for email, r in items for t in r.todos]
    if todos:
        lines += ["", "## To-dos found this run", ""]
        for email, t in todos:
            due = f" (due {t.due})" if t.due else ""
            lines.append(f"- [ ] {t.task}{due} — from “{email['subject']}”")

    if by_cat["todo"]:
        lines += ["", "## Asks something of you", ""]
        for email, r in by_cat["todo"]:
            lines.append(f"- **{email['subject']}** — {_sender(email['from'])}: {r.summary}")

    if by_cat["fyi"]:
        lines += ["", "## FYI", ""]
        for email, r in by_cat["fyi"]:
            lines.append(f"- {email['subject']} — {r.summary}")

    if by_cat["noise"]:
        lines += ["", f"## Noise ({len(by_cat['noise'])})", ""]
        for email, _ in by_cat["noise"]:
            lines.append(f"- {email['subject']} — {_sender(email['from'])}")

    if by_cat[UNCLASSIFIED]:
        lines += ["", "## Errors (will be retried next run)", ""]
        for email, r in by_cat[UNCLASSIFIED]:
            lines.append(f"- {email['subject']} — `{r.error}`")

    return "\n".join(lines) + "\n"


def render_todos(rows) -> str:
    lines = ["# Open to-dos", "", "Mark one done with `python inbox.py --done <id>`.", ""]
    if not rows:
        lines.append("_Nothing open._")
    for row in rows:
        due = f" — due **{row['due']}**" if row["due"] else ""
        lines.append(f"- `{row['id']}` {row['task']}{due} — from “{row['subject']}”")
    return "\n".join(lines) + "\n"
