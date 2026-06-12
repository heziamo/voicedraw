"""声笔 VoiceDraw 后端：会话管理 + 指令执行 API + 前端静态托管。"""
import os
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import store
from .nlu import LOGICAL_H, LOGICAL_W, handle_utterance, new_state

VERSION = '1.0.0'

app = FastAPI(title='VoiceDraw API', version=VERSION)
app.add_middleware(
    CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])

store.init_db()


class CommandIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)


def _session_payload(session_id, state, results=None):
    return {
        'session_id': session_id,
        'scene': state['scene'],
        'selected': state['selected'],
        'flags': {
            'muted': state['muted'], 'tts_on': state['tts_on'],
            'can_undo': len(state['history']) > 0, 'can_redo': len(state['redo']) > 0,
        },
        'logical': {'w': LOGICAL_W, 'h': LOGICAL_H},
        'results': results or [],
    }


@app.get('/api/healthz')
def healthz():
    return {'status': 'ok', 'version': VERSION, 'store': store.BACKEND_NAME}


@app.post('/api/sessions', status_code=201)
def create_session():
    session_id = uuid.uuid4().hex[:12]
    state = new_state()
    store.create_session(session_id, state)
    return _session_payload(session_id, state)


@app.get('/api/sessions/{session_id}')
def get_session(session_id: str):
    state = store.load_session(session_id)
    if state is None:
        raise HTTPException(404, '会话不存在')
    return _session_payload(session_id, state)


@app.post('/api/sessions/{session_id}/commands')
def run_command(session_id: str, cmd: CommandIn):
    state = store.load_session(session_id)
    if state is None:
        raise HTTPException(404, '会话不存在')
    results = handle_utterance(state, cmd.text)
    store.save_session(session_id, state)
    store.log_commands(session_id, cmd.text, results)
    return _session_payload(session_id, state, results)


@app.get('/api/sessions/{session_id}/commands')
def get_commands(session_id: str, limit: int = 50):
    if store.load_session(session_id) is None:
        raise HTTPException(404, '会话不存在')
    return {'commands': store.list_commands(session_id, min(limit, 200))}


# 前端静态文件（放在 API 路由之后注册，避免吞掉 /api/*）
_FRONTEND_DIR = os.path.join(os.path.dirname(__file__), '..', 'frontend')
app.mount('/', StaticFiles(directory=_FRONTEND_DIR, html=True), name='frontend')
