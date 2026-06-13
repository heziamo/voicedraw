"""文生图：调用大模型生成图片，图片作为画布对象。

- provider 经 VOICEDRAW_IMAGE_PROVIDER 选择，目前实现 zhipu（智谱 CogView）。
- 未配置 API Key 时回退到 SVG 占位图，整条生成链路（解析→生成→入画布→渲染→编辑）
  依然完整可跑；配置 Key 后自动切换为真实生成，无需改代码。
- 仅用标准库 urllib，规避服务器老 OpenSSL 上 requests/urllib3 v2 的兼容问题。
"""
import json
import os
import ssl
import time
import urllib.request
from urllib.error import HTTPError, URLError

DATA_DIR = os.environ.get(
    'VOICEDRAW_DATA_DIR', os.path.join(os.path.dirname(__file__), '..', 'data'))
IMG_DIR = os.path.join(DATA_DIR, 'images')

PROVIDER = os.environ.get('VOICEDRAW_IMAGE_PROVIDER', 'zhipu').lower()
API_KEY = os.environ.get('VOICEDRAW_IMAGE_API_KEY', '').strip()
MODEL = os.environ.get('VOICEDRAW_IMAGE_MODEL', 'cogview-3-flash')
TIMEOUT = int(os.environ.get('VOICEDRAW_IMAGE_TIMEOUT', '60'))

ZHIPU_URL = 'https://open.bigmodel.cn/api/paas/v4/images/generations'
_counter = 0


def init():
    os.makedirs(IMG_DIR, exist_ok=True)


def configured():
    return bool(API_KEY)


def status():
    return {'provider': PROVIDER, 'model': MODEL, 'configured': configured()}


def _short(s):
    s = s.strip()
    return s if len(s) <= 18 else s[:17] + '…'


def _save(data, ext, mode='wb'):
    global _counter
    init()
    _counter += 1
    name = 'img_%d_%d.%s' % (int(time.time()), _counter, ext)
    with open(os.path.join(IMG_DIR, name), mode, **({} if 'b' in mode else {'encoding': 'utf-8'})) as f:
        f.write(data)
    return '/media/' + name


def generate(prompt):
    """返回 {ok, src, w, h, mock, msg}。失败返回 {ok:False, msg}。"""
    prompt = (prompt or '').strip()
    if not prompt:
        return {'ok': False, 'msg': '没听清要生成什么图片'}
    if not API_KEY:
        return _placeholder(prompt)
    try:
        if PROVIDER == 'zhipu':
            url, w, h = _zhipu(prompt)
        else:
            return {'ok': False, 'msg': '未知的图片服务商：%s' % PROVIDER}
        data, ext = _download(url)
        src = _save(data, ext)
        return {'ok': True, 'src': src, 'w': w, 'h': h, 'mock': False,
                'msg': '已生成「%s」' % _short(prompt)}
    except HTTPError as e:
        detail = '认证失败，请检查 API Key' if e.code in (401, 403) else '服务返回 %d' % e.code
        return {'ok': False, 'msg': '生成失败：%s' % detail}
    except (URLError, OSError) as e:
        return {'ok': False, 'msg': '生成失败：网络错误（%s）' % (getattr(e, 'reason', None) or e)}
    except (KeyError, ValueError, IndexError):
        return {'ok': False, 'msg': '生成失败：服务返回格式异常'}


def _zhipu(prompt):
    body = json.dumps({'model': MODEL, 'prompt': prompt, 'size': '1024x1024'}).encode('utf-8')
    req = urllib.request.Request(ZHIPU_URL, data=body, method='POST', headers={
        'Authorization': 'Bearer ' + API_KEY, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=ssl.create_default_context()) as r:
        payload = json.loads(r.read().decode('utf-8'))
    return payload['data'][0]['url'], 1024, 1024


def _download(url):
    with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
        ct = (r.headers.get('Content-Type') or 'image/png').lower()
        ext = 'jpg' if ('jpeg' in ct or 'jpg' in ct) else 'webp' if 'webp' in ct else 'png'
        return r.read(), ext


# ---------------- 占位图（无 Key 时） ----------------

def _esc(s):
    return (s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('"', '&quot;'))


def _placeholder(prompt):
    lines = [prompt[i:i + 11] for i in range(0, len(prompt), 11)][:4]
    if len(prompt) > 44:
        lines[-1] = lines[-1][:10] + '…'
    tspans = ''.join(
        '<tspan x="512" dy="%d">%s</tspan>' % (0 if i == 0 else 78, _esc(ln))
        for i, ln in enumerate(lines))
    y0 = 470 - (len(lines) - 1) * 39
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">'
        '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#191b3a"/><stop offset="1" stop-color="#0a0a14"/>'
        '</linearGradient></defs>'
        '<rect width="1024" height="1024" fill="url(#g)"/>'
        '<rect x="44" y="44" width="936" height="936" rx="28" fill="none" '
        'stroke="#5e6ad2" stroke-opacity="0.4" stroke-width="2"/>'
        '<text x="512" y="150" text-anchor="middle" fill="#828fff" '
        'font-family="Inter,sans-serif" font-size="30" letter-spacing="3">VOICEDRAW · AI 生成</text>'
        '<text x="512" y="' + str(y0) + '" text-anchor="middle" fill="#f7f8f8" '
        'font-family="Inter,PingFang SC,sans-serif" font-size="58" font-weight="600">'
        + tspans + '</text>'
        '<text x="512" y="900" text-anchor="middle" fill="#8a8f98" '
        'font-family="Inter,sans-serif" font-size="28">占位图 · 在服务器配置智谱 CogView Key 后生成真实图片</text>'
        '</svg>')
    src = _save(svg, 'svg', mode='w')
    return {'ok': True, 'src': src, 'w': 1024, 'h': 1024, 'mock': True,
            'msg': '已生成占位图「%s」（配置 Key 后出真实图）' % _short(prompt)}
