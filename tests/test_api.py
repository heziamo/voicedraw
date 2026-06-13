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
    import app.imagegen
    importlib.reload(app.store_sqlite)
    importlib.reload(app.store_json)
    importlib.reload(app.imagegen)   # 拾取临时 data 目录 + 无 Key（走占位）
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


def test_healthz_reports_image_config(client):
    img = client.get('/api/healthz').json()['image']
    assert img['provider'] == 'zhipu' and img['configured'] is False  # 测试环境无 Key


def test_generate_image_placeholder_flow(client):
    """无 API Key 时，/generate 走占位图，但整条链路（入场景 + 媒体可访问）应完整。"""
    sid = client.post('/api/sessions').json()['session_id']
    r = client.post(f'/api/sessions/{sid}/generate', json={'prompt': '星空下的城堡'})
    body = r.json()
    assert r.status_code == 200 and body['results'][0]['ok']
    imgs = [s for s in body['scene']['shapes'] if s['type'] == 'image']
    assert len(imgs) == 1 and imgs[0]['src'].startswith('/media/')
    assert imgs[0]['prompt'] == '星空下的城堡'
    # 生成的占位图可经 /media 访问
    assert client.get(imgs[0]['src']).status_code == 200
    # 审计日志记录了这次生成
    assert any(c['intent'] == 'generate' for c in client.get(f'/api/sessions/{sid}/commands').json()['commands'])


def test_image_ext_sniffed_from_bytes():
    """扩展名按真实文件头判断，而非信任响应头（CogView 实测返回 jpeg）。"""
    from app import imagegen
    assert imagegen._sniff_ext(b'\xff\xd8\xff\xe0\x00\x10JFIF') == 'jpg'
    assert imagegen._sniff_ext(b'\x89PNG\r\n\x1a\n' + b'\x00' * 8) == 'png'
    assert imagegen._sniff_ext(b'RIFF\x00\x00\x00\x00WEBP') == 'webp'


def test_generate_image_persists(client):
    sid = client.post('/api/sessions').json()['session_id']
    client.post(f'/api/sessions/{sid}/generate', json={'prompt': '一只猫'})
    again = client.get(f'/api/sessions/{sid}').json()
    assert any(s['type'] == 'image' for s in again['scene']['shapes'])
