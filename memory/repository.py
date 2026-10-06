import math
import sqlite3
import uuid
from datetime import datetime, timezone

from memory.db import Database


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobAlreadyRunning(Exception):
    pass


class Repository:
    def __init__(self, db: Database):
        self.db = db

    def _write(self, sql, params=()):
        with self.db.lock, self.db.connection:
            return self.db.connection.execute(sql, params).lastrowid

    def _rows(self, sql, params=()):
        with self.db.lock:
            return [dict(row) for row in self.db.connection.execute(sql, params).fetchall()]

    def ensure_user(self, openid: str):
        if not openid:
            raise ValueError("OpenID is required")
        timestamp = now()
        self._write("""INSERT INTO users(openid, created_at, last_seen_at) VALUES (?, ?, ?)
            ON CONFLICT(openid) DO UPDATE SET last_seen_at=excluded.last_seen_at""", (openid, timestamp, timestamp))
        return self.get_user(openid)

    def get_user(self, openid):
        rows = self._rows("SELECT * FROM users WHERE openid=?", (openid,))
        return rows[0] if rows else None

    def set_agent_enabled(self, openid, enabled: bool):
        self.ensure_user(openid)
        self._write("UPDATE users SET agent_enabled=? WHERE openid=?", (int(enabled), openid))

    def list_users(self):
        return self._rows("SELECT * FROM users ORDER BY last_seen_at DESC LIMIT 100")

    def add_message(self, openid, role, content):
        self._write("INSERT INTO messages(openid, role, content, created_at) VALUES (?, ?, ?, ?)",
                    (openid, role, content, now()))

    def recent_messages(self, openid, limit=12):
        rows = self._rows("SELECT role, content FROM messages WHERE openid=? AND role IN ('user', 'assistant') ORDER BY id DESC LIMIT ?",
                          (openid, limit))
        return list(reversed(rows))

    def create_job(self, openid, mode, question):
        job_id = uuid.uuid4().hex
        try:
            self._write("INSERT INTO jobs(id, openid, mode, status, question, created_at) VALUES (?, ?, ?, 'processing', ?, ?)",
                        (job_id, openid, mode, question, now()))
        except sqlite3.IntegrityError:
            if self.active_job(openid):
                raise JobAlreadyRunning() from None
            raise
        return self.get_job(job_id)

    def get_job(self, job_id):
        rows = self._rows("SELECT * FROM jobs WHERE id=?", (job_id,))
        return rows[0] if rows else None

    def active_job(self, openid):
        rows = self._rows("SELECT * FROM jobs WHERE openid=? AND status='processing'", (openid,))
        return rows[0] if rows else None

    def latest_job(self, openid):
        rows = self._rows("SELECT * FROM jobs WHERE openid=? ORDER BY created_at DESC, rowid DESC LIMIT 1", (openid,))
        return rows[0] if rows else None

    def finish_job(self, job_id, answer=None, error=None):
        with self.db.lock, self.db.connection:
            job = self.get_job(job_id)
            if not job or job['status'] != 'processing':
                return
            self.db.connection.execute("UPDATE jobs SET status=?, answer=?, error=?, finished_at=? WHERE id=?",
                ("error" if error else "done", answer, error, now(), job_id))
            if answer:
                self.add_message(job['openid'], "assistant", answer)

    def recover_interrupted_jobs(self):
        self._write("UPDATE jobs SET status='error', error='interrupted_by_restart', finished_at=? WHERE status='processing'", (now(),))

    def list_jobs(self):
        return self._rows("SELECT id, openid, mode, status, created_at FROM jobs ORDER BY created_at DESC LIMIT 100")

    def stats(self):
        return {name: self._rows(f"SELECT COUNT(*) AS count FROM {name}")[0]['count']
                for name in ("users", "messages", "jobs", "memories")}

    def active_job_count(self):
        return self._rows("SELECT COUNT(*) AS count FROM jobs WHERE status='processing'")[0]['count']

    def save_memory(self, openid, memory_type, content, importance=0.5):
        """Explicit curated writes only; conversation sentences are never auto-saved."""
        if memory_type not in ("preference", "project", "decision", "profile", "todo", "summary"):
            raise ValueError("Unsupported memory type")
        content = content.strip()
        if not content or len(content) > 2000 or content.lower() in ("你好", "谢谢", "今天天气不错", "hello", "hi", "thanks", "thank you"):
            raise ValueError("Memory must be meaningful and at most 2000 characters")
        if isinstance(importance, bool) or not math.isfinite(importance) or not 0 <= importance <= 1:
            raise ValueError("Invalid memory importance")
        self.ensure_user(openid)
        timestamp = now()
        if memory_type == "summary":
            with self.db.lock, self.db.connection:
                existing = self._rows("SELECT id FROM memories WHERE openid=? AND memory_type='summary'", (openid,))
                if existing:
                    self._write("UPDATE memories SET content=?, importance=?, updated_at=? WHERE id=?",
                                (content, importance, timestamp, existing[0]['id']))
                    return existing[0]['id']
                return self._write("INSERT INTO memories(openid, memory_type, content, importance, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                                   (openid, memory_type, content, importance, timestamp, timestamp))
        return self._write("INSERT INTO memories(openid, memory_type, content, importance, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                           (openid, memory_type, content, importance, timestamp, timestamp))

    def summaries(self, openid):
        return self._rows("SELECT content FROM memories WHERE openid=? AND memory_type='summary' ORDER BY updated_at DESC LIMIT 3", (openid,))
