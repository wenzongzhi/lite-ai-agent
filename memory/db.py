import sqlite3
from pathlib import Path
from threading import RLock


class Database:
    """One serialized SQLite connection shared by the CLI and async runtime."""

    def __init__(self, path: str, enable_fts: bool = True):
        if path != ":memory:":
            Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()
        self.connection = sqlite3.connect(str(Path(path).expanduser()) if path != ":memory:" else path,
                                          check_same_thread=False, timeout=10)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))
        self.fts_enabled = False
        if enable_fts:
            try:
                self.connection.executescript("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(content, content='memories', content_rowid='id');
                    CREATE TRIGGER IF NOT EXISTS memories_insert AFTER INSERT ON memories BEGIN
                        INSERT INTO memories_fts(rowid, content) VALUES (new.id, new.content);
                    END;
                    CREATE TRIGGER IF NOT EXISTS memories_delete AFTER DELETE ON memories BEGIN
                        INSERT INTO memories_fts(memories_fts, rowid, content) VALUES ('delete', old.id, old.content);
                    END;
                    CREATE TRIGGER IF NOT EXISTS memories_update AFTER UPDATE ON memories BEGIN
                        INSERT INTO memories_fts(memories_fts, rowid, content) VALUES ('delete', old.id, old.content);
                        INSERT INTO memories_fts(rowid, content) VALUES (new.id, new.content);
                    END;
                    INSERT INTO memories_fts(memories_fts) VALUES ('rebuild');
                """)
                self.fts_enabled = True
            except sqlite3.OperationalError:
                pass
        self.connection.commit()

    def close(self):
        with self.lock:
            self.connection.close()
