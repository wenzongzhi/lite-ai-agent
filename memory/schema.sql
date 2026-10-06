CREATE TABLE IF NOT EXISTS users (
    openid TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    agent_enabled INTEGER NOT NULL DEFAULT 0 CHECK(agent_enabled IN (0, 1))
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    openid TEXT NOT NULL REFERENCES users(openid),
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'tool', 'system')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_user_id ON messages(openid, id);
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    openid TEXT NOT NULL REFERENCES users(openid),
    memory_type TEXT NOT NULL,
    content TEXT NOT NULL,
    importance REAL NOT NULL DEFAULT 0.5,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS memories_user ON memories(openid);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    openid TEXT NOT NULL REFERENCES users(openid),
    mode TEXT NOT NULL CHECK(mode IN ('ai-answer', 'ai-agent')),
    status TEXT NOT NULL CHECK(status IN ('processing', 'done', 'error')),
    question TEXT NOT NULL,
    answer TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS jobs_user ON jobs(openid, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_job_per_user ON jobs(openid) WHERE status = 'processing';
