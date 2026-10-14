"""SQLite record of what has been processed, the running to-do list, and the last run time."""
import sqlite3
from datetime import datetime

from .classify import UNCLASSIFIED

SCHEMA = """
CREATE TABLE IF NOT EXISTS processed (
    id TEXT PRIMARY KEY,
    received_at INTEGER,
    sender TEXT,
    subject TEXT,
    category TEXT,
    why TEXT,
    summary TEXT,
    model TEXT,
    error TEXT,
    processed_at TEXT
);
CREATE TABLE IF NOT EXISTS todos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT,
    task TEXT,
    due TEXT,
    subject TEXT,
    done INTEGER NOT NULL DEFAULT 0,
    created_at TEXT,
    UNIQUE (message_id, task)
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


class State:
    def __init__(self, path):
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def done_ids(self) -> set[str]:
        # Unclassified rows are not "done": they get retried on the next run.
        rows = self.db.execute("SELECT id FROM processed WHERE category != ?", (UNCLASSIFIED,))
        return {r["id"] for r in rows}

    def retry_ids(self) -> list[str]:
        rows = self.db.execute(
            "SELECT id FROM processed WHERE category = ? ORDER BY received_at DESC", (UNCLASSIFIED,)
        )
        return [r["id"] for r in rows]

    def save(self, email: dict, result, model: str) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        self.db.execute(
            "INSERT OR REPLACE INTO processed VALUES (?,?,?,?,?,?,?,?,?,?)",
            (email["id"], email["received_at"], email["from"], email["subject"], result.category,
             result.why, result.summary, model, result.error, now),
        )
        for todo in result.todos:
            self.db.execute(
                "INSERT OR IGNORE INTO todos (message_id, task, due, subject, created_at) VALUES (?,?,?,?,?)",
                (email["id"], todo.task, todo.due, email["subject"], now),
            )
        self.db.commit()  # per email, so Ctrl+C or a crash keeps everything finished so far

    def open_todos(self) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM todos WHERE done = 0 ORDER BY due IS NULL, due, id"
        ).fetchall()

    def mark_done(self, ids: list[int]) -> int:
        cur = self.db.executemany("UPDATE todos SET done = 1 WHERE id = ?", [(i,) for i in ids])
        self.db.commit()
        return cur.rowcount

    def get(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set(self, key: str, value: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))
        self.db.commit()
