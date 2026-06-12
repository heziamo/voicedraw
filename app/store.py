"""SQLite 持久化：会话状态 + 指令审计日志。

会话状态整体存为 JSON（场景/历史栈/选中集是强耦合的一致性单元，
拆表无收益）；指令日志单独成表便于按时间审计查询。
"""
import json
import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.environ.get('VOICEDRAW_DB', os.path.join(os.path.dirname(__file__), '..', 'voicedraw.db'))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id         TEXT PRIMARY KEY,
    state      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS commands (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    raw_text   TEXT NOT NULL,
    clause     TEXT NOT NULL,
    intent     TEXT NOT NULL,
    ok         INTEGER NOT NULL,
    message    TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_commands_session ON commands(session_id, id DESC);
"""


def _now():
    return datetime.now(timezone.utc).isoformat()


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = _connect()
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def create_session(session_id, state):
    conn = _connect()
    try:
        now = _now()
        conn.execute('INSERT INTO sessions (id, state, created_at, updated_at) VALUES (?,?,?,?)',
                     (session_id, json.dumps(state, ensure_ascii=False), now, now))
        conn.commit()
    finally:
        conn.close()


def load_session(session_id):
    conn = _connect()
    try:
        row = conn.execute('SELECT state FROM sessions WHERE id=?', (session_id,)).fetchone()
        return json.loads(row['state']) if row else None
    finally:
        conn.close()


def save_session(session_id, state):
    conn = _connect()
    try:
        conn.execute('UPDATE sessions SET state=?, updated_at=? WHERE id=?',
                     (json.dumps(state, ensure_ascii=False), _now(), session_id))
        conn.commit()
    finally:
        conn.close()


def log_commands(session_id, raw_text, results):
    if not results:
        return
    conn = _connect()
    try:
        now = _now()
        conn.executemany(
            'INSERT INTO commands (session_id, raw_text, clause, intent, ok, message, created_at) '
            'VALUES (?,?,?,?,?,?,?)',
            [(session_id, raw_text, r.get('clause', ''), r.get('intent', ''),
              1 if r['ok'] else 0, r['msg'], now) for r in results])
        conn.commit()
    finally:
        conn.close()


def list_commands(session_id, limit=50):
    conn = _connect()
    try:
        rows = conn.execute(
            'SELECT raw_text, clause, intent, ok, message, created_at FROM commands '
            'WHERE session_id=? ORDER BY id DESC LIMIT ?', (session_id, limit)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
