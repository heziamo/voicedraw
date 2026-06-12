"""API 集成测试：会话生命周期 + 指令执行 + 持久化 + 审计日志。"""
import importlib

import pytest
from fastapi.testclient import TestClient


# 两个后端都跑一遍：sqlite（本地默认）+ json（服务器缺 _sqlite3 时的兜底）
@pytest.fixture(params=['sqlite', 'json'])
def client(tmp_path, monkeypatch, request):
    monkeypatch.setenv('VOICEDRAW_STORE', request.param)
    monkeypatch.setenv('VOICEDRAW_DB', str(tmp_path / 'test.db'))
    monkeypatch.setenv('VOICEDRAW_DATA_DIR', str(tmp_path / 'data'))
    import app.store_sqlite
    import app.store_json
    importlib.reload(app.store_sqlite)
    importlib.reload(app.store_json)
    from app import store
    importlib.reload(store)
    assert store.BACKEND_NAME == request.param
    from app import main
    importlib.reload(main)
    return TestClient(main.app)


def test_healthz(client):
    r = client.get('/api/healthz')
    body = r.json()
    assert r.status_code == 200 and body['status'] == 'ok'
    assert body['store'] in ('sqlite', 'json')


def test_session_lifecycle(client):
    sid = client.post('/api/sessions').json()['session_id']

    r = client.post(f'/api/sessions/{sid}/commands', json={'text': '画一个红色的圆'})
    body = r.json()
    assert r.status_code == 200
    assert body['results'][0]['ok']
    assert len(body['scene']['shapes']) == 1
    assert body['scene']['shapes'][0]['color'] == '#e5484d'
    assert body['selected'] == [body['scene']['shapes'][0]['id']]

    # 状态持久化：重新 GET 会话仍能拿到场景
    r2 = client.get(f'/api/sessions/{sid}')
    assert len(r2.json()['scene']['shapes']) == 1

    # 指令审计日志
    logs = client.get(f'/api/sessions/{sid}/commands').json()['commands']
    assert logs[0]['raw_text'] == '画一个红色的圆' and logs[0]['ok'] == 1


def test_compound_command_via_api(client):
    sid = client.post('/api/sessions').json()['session_id']
    r = client.post(f'/api/sessions/{sid}/commands',
                    json={'text': '画三个并排的蓝色方块然后把背景换成黑色'})
    body = r.json()
    assert [x['intent'] for x in body['results']] == ['draw', 'background']
    assert len(body['scene']['shapes']) == 3
    assert body['scene']['bg'] == '#111113'


def test_unknown_session_404(client):
    assert client.get('/api/sessions/nonexistent').status_code == 404
    assert client.post('/api/sessions/nonexistent/commands',
                       json={'text': '画一个圆'}).status_code == 404


def test_empty_text_rejected(client):
    sid = client.post('/api/sessions').json()['session_id']
    assert client.post(f'/api/sessions/{sid}/commands', json={'text': ''}).status_code == 422
