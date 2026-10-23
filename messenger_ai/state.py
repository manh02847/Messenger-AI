from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from .context import recent_history


class State:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.parent.chmod(0o700)
        self.db = sqlite3.connect(path)
        path.chmod(0o600)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS seen (
                thread TEXT NOT NULL, id TEXT NOT NULL, at REAL NOT NULL,
                PRIMARY KEY(thread, id)
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY, thread TEXT NOT NULL, role TEXT NOT NULL,
                content TEXT NOT NULL, at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS outbox (
                id INTEGER PRIMARY KEY, thread TEXT NOT NULL, hash TEXT NOT NULL,
                message_id TEXT, status TEXT NOT NULL, at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pauses (thread TEXT PRIMARY KEY, until_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS ai_calls (id INTEGER PRIMARY KEY, day TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS messages_thread ON messages(thread, id);
            CREATE INDEX IF NOT EXISTS outbox_thread ON outbox(thread, at);
        """)
        self.db.commit()

    def claim(self, thread: str, message_id: str, now: float) -> bool:
        with self.db:
            cursor = self.db.execute(
                "INSERT OR IGNORE INTO seen VALUES (?, ?, ?)", (thread, message_id, now)
            )
        return cursor.rowcount == 1

    def remember(
        self, thread: str, role: str, content: str, now: float, keep: int
    ) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO messages(thread,role,content,at) VALUES (?,?,?,?)",
                (thread, role, content, now),
            )
            self.db.execute(
                "DELETE FROM messages WHERE thread=? AND id NOT IN (SELECT id FROM messages WHERE thread=? ORDER BY id DESC LIMIT ?)",
                (thread, thread, keep),
            )

    def history(
        self, thread: str, count: int, char_limit: int, *, idle_seconds: float = 0
    ) -> list[dict[str, str]]:
        rows = self.db.execute(
            "SELECT role,content,at FROM messages WHERE thread=? ORDER BY id DESC LIMIT ?",
            (thread, count),
        ).fetchall()
        history: list[dict[str, str]] = []
        newer_at = None
        for role, content, at in rows:
            if idle_seconds and newer_at is not None and newer_at - at >= idle_seconds:
                break
            history.append({"role": role, "content": content})
            newer_at = at
        return recent_history(list(reversed(history)), count, char_limit)

    def clear_history(self, thread: str) -> int:
        with self.db:
            cursor = self.db.execute("DELETE FROM messages WHERE thread=?", (thread,))
        return cursor.rowcount

    def pause(self, thread: str, until: float) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO pauses VALUES (?,?) ON CONFLICT(thread) DO UPDATE SET until_at=MAX(until_at,excluded.until_at)",
                (thread, until),
            )

    def paused(self, thread: str, now: float) -> bool:
        row = self.db.execute(
            "SELECT until_at FROM pauses WHERE thread=?", (thread,)
        ).fetchone()
        return bool(row and row[0] > now)

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def begin_send(self, thread: str, text: str, now: float) -> int:
        with self.db:
            cursor = self.db.execute(
                "INSERT INTO outbox(thread,hash,status,at) VALUES (?,?,'pending',?)",
                (thread, self._hash(text), now),
            )
        return int(cursor.lastrowid)

    def finish_send(
        self, outbox_id: int, status: str, message_id: str | None = None
    ) -> None:
        with self.db:
            self.db.execute(
                "UPDATE outbox SET status=?, message_id=? WHERE id=?",
                (status, message_id, outbox_id),
            )

    def bot_echo(self, thread: str, message_id: str, text: str, now: float) -> bool:
        row = self.db.execute(
            """
            SELECT 1 FROM outbox WHERE thread=? AND (
                message_id=? OR (status IN ('pending','unknown') AND hash=? AND at>=?)
            ) LIMIT 1
        """,
            (thread, message_id, self._hash(text), now - 120),
        ).fetchone()
        return row is not None

    def sends_since(self, thread: str, since: float) -> int:
        return int(
            self.db.execute(
                "SELECT COUNT(*) FROM outbox WHERE thread=? AND at>=?", (thread, since)
            ).fetchone()[0]
        )

    def last_send(self, thread: str) -> float:
        return float(
            self.db.execute(
                "SELECT COALESCE(MAX(at),0) FROM outbox WHERE thread=?", (thread,)
            ).fetchone()[0]
        )

    def reserve_ai(self, day: str, limit: int) -> bool:
        with self.db:
            count = self.db.execute(
                "SELECT COUNT(*) FROM ai_calls WHERE day=?", (day,)
            ).fetchone()[0]
            if count >= limit:
                return False
            self.db.execute("INSERT INTO ai_calls(day) VALUES (?)", (day,))
        return True

    def prune(self, now: float, retention_days: int) -> None:
        cutoff = now - retention_days * 86400
        with self.db:
            for table in ("seen", "messages", "outbox"):
                self.db.execute(f"DELETE FROM {table} WHERE at<?", (cutoff,))
            self.db.execute("DELETE FROM pauses WHERE until_at<?", (now,))
            self.db.execute("DELETE FROM ai_calls WHERE day < date('now', '-30 days')")

    def close(self) -> None:
        self.db.close()
