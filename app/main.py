"""声笔 VoiceDraw 后端：会话管理 + 指令执行 API + 前端静态托管。"""
import os
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import imagegen, llm, store
from .nlu import LOGICAL_H, LOGICAL_W, handle_utterance, new_state
from .nlu.engine import add_image

VERSION = '1.2.0'

app = FastAPI(title='VoiceDraw API', version=VERSION)
app.add_middleware(
    CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])

store.init_db()
imagegen.init()


class CommandIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class GenerateIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=400)


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
    return {'status': 'ok', 'version': VERSION, 'store': store.BACKEND_NAME,
            'image': imagegen.status(),
            'llm': {'provider': llm.PROVIDER, 'model': llm.MODEL, 'configured': llm.available()}}


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


@app.post('/api/sessions/{session_id}/generate')
def generate_image(session_id: str, body: GenerateIn):
    """文生图：调用大模型（或占位），把结果作为图片对象加入场景。耗时数秒。"""
    state = store.load_session(session_id)
    if state is None:
        raise HTTPException(404, '会话不存在')
    res = imagegen.generate(body.prompt)
    result = [{'ok': bool(res.get('ok')), 'msg': res['msg'],
               'intent': 'generate', 'clause': body.prompt}]
    if res.get('ok'):
        add_image(state, res['src'], res['w'], res['h'], body.prompt)
        store.save_session(session_id, state)
    store.log_commands(session_id, body.prompt, result)
    return _session_payload(session_id, state, result)


# 生成图片的静态目录（注册在前端 catch-all 之前）
app.mount('/media', StaticFiles(directory=imagegen.IMG_DIR), name='media')
# 前端静态文件（放在最后注册，避免吞掉 /api/* 与 /media/*）
_FRONTEND_DIR = os.path.join(os.path.dirname(__file__), '..', 'frontend')
app.mount('/', StaticFiles(directory=_FRONTEND_DIR, html=True), name='frontend')
