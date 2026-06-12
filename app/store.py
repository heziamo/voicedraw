"""持久化层调度器。

按 VOICEDRAW_STORE 选择后端：
- "sqlite"：强制用 SQLite（缺 _sqlite3 会报错）
- "json"：强制用 JSON 文件
- "auto"（默认）：能 import sqlite3 就用 SQLite，否则回退 JSON 文件

服务器的源码编译版 Python 3.8 没带 _sqlite3 扩展，auto 会自动落到 JSON 后端，
因此无需在服务器上重编译 Python。
"""
import importlib
import os

_MODE = os.environ.get('VOICEDRAW_STORE', 'auto').lower()


def _select_backend():
    if _MODE == 'json':
        return importlib.import_module('app.store_json'), 'json'
    if _MODE == 'sqlite':
        return importlib.import_module('app.store_sqlite'), 'sqlite'
    # auto
    try:
        import sqlite3  # noqa: F401
        return importlib.import_module('app.store_sqlite'), 'sqlite'
    except ImportError:
        return importlib.import_module('app.store_json'), 'json'


_backend, BACKEND_NAME = _select_backend()

init_db = _backend.init_db
create_session = _backend.create_session
load_session = _backend.load_session
save_session = _backend.save_session
log_commands = _backend.log_commands
list_commands = _backend.list_commands
