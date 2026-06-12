"""无依赖的 JSON 文件持久化后端。

用于服务器 Python 缺少 `_sqlite3` C 扩展时的兜底（源码编译时未带 sqlite-devel）。
- 每个会话状态存为独立文件 sessions/<id>.json（避免单文件全量重写）
- 指令日志按会话 append 到 sessions/<id>.log.jsonl（追加写，便于审计）
接口与 store_sqlite 完全一致，可热替换。
"""
import json
import os
import threading
from datetime import datetime, timezone

DATA_DIR = os.environ.get(
    'VOICEDRAW_DATA_DIR', os.path.join(os.path.dirname(__file__), '..', 'data'))
_SESS_DIR = os.path.join(DATA_DIR, 'sessions')
_lock = threading.Lock()


def _now():
    return datetime.now(timezone.utc).isoformat()


def _state_path(sid):
    return os.path.join(_SESS_DIR, sid + '.json')


def _log_path(sid):
    return os.path.join(_SESS_DIR, sid + '.log.jsonl')


def init_db():
    os.makedirs(_SESS_DIR, exist_ok=True)


def create_session(session_id, state):
    init_db()
    with _lock:
        with open(_state_path(session_id), 'w', encoding='utf-8') as f:
            json.dump({'state': state, 'created_at': _now()}, f, ensure_ascii=False)


def load_session(session_id):
    path = _state_path(session_id)
    if not os.path.exists(path):
        return None
    with _lock:
        with open(path, encoding='utf-8') as f:
            return json.load(f)['state']


def save_session(session_id, state):
    path = _state_path(session_id)
    with _lock:
        created = _now()
        if os.path.exists(path):
            try:
                with open(path, encoding='utf-8') as f:
                    created = json.load(f).get('created_at', created)
            except (ValueError, OSError):
                pass
        # 写临时文件再原子替换，避免写一半进程被杀导致损坏
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'state': state, 'created_at': created, 'updated_at': _now()},
                      f, ensure_ascii=False)
        os.replace(tmp, path)


def log_commands(session_id, raw_text, results):
    if not results:
        return
    with _lock:
        now = _now()
        with open(_log_path(session_id), 'a', encoding='utf-8') as f:
            for r in results:
                f.write(json.dumps({
                    'raw_text': raw_text, 'clause': r.get('clause', ''),
                    'intent': r.get('intent', ''), 'ok': 1 if r['ok'] else 0,
                    'message': r['msg'], 'created_at': now,
                }, ensure_ascii=False) + '\n')


def list_commands(session_id, limit=50):
    path = _log_path(session_id)
    if not os.path.exists(path):
        return []
    with _lock:
        with open(path, encoding='utf-8') as f:
            lines = f.readlines()
    rows = [json.loads(ln) for ln in lines if ln.strip()]
    rows.reverse()  # 最新在前
    return rows[:limit]
