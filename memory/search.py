import sqlite3

from memory.repository import Repository


def search_memory(repository: Repository, openid: str, query: str, limit=5) -> list[dict]:
    """FTS5 ranking with a parameterized LIKE fallback, always scoped to OpenID."""
    query = query.strip()
    if not query or len(query) > 500:
        return []
    limit = max(1, min(limit, 5))
    if repository.db.fts_enabled:
        expression = " OR ".join('"' + term.replace('"', '""') + '"' for term in query.split())
        try:
            rows = repository._rows("""SELECT m.memory_type AS type, m.content FROM memories_fts
                JOIN memories m ON m.id=memories_fts.rowid WHERE memories_fts MATCH ? AND m.openid=?
                ORDER BY bm25(memories_fts), m.importance DESC LIMIT ?""", (expression, openid, limit))
            if rows:
                return rows
        except sqlite3.OperationalError:
            pass
    escaped = query.replace("!", "!!").replace("%", "!%").replace("_", "!_")
    return repository._rows("""SELECT memory_type AS type, content FROM memories
        WHERE openid=? AND content LIKE ? ESCAPE '!' ORDER BY importance DESC, updated_at DESC LIMIT ?""",
        (openid, '%' + escaped + '%', limit))
