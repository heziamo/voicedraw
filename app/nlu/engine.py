"""NLU 引擎：意图解析 + 指代消解 + 场景执行。

场景使用逻辑坐标系（1200×750），前端按窗口大小等比缩放渲染，
这样服务端无需知道客户端画布的实际像素尺寸。

图形对象字段：
  id type x y size color rot style(fill|stroke)
  opacity(0-1) flipX flipY weight(描边粗细倍率) group(可选) name(可选) text(仅文字)
"""
import json
import math
import random
import re

from .lexicon import (NUM_CLASS, SHAPE_LABEL, cn2num, find_color, find_position,
                      find_shape, find_size, find_template)
from .normalizer import normalize, split_clauses

LOGICAL_W = 1200
LOGICAL_H = 750
MAX_SHAPES_PER_DRAW = 40
MAX_HISTORY = 60


def new_state():
    return {
        'scene': {'shapes': [], 'bg': '#fafafa'},
        'history': [], 'redo': [],
        'selected': [], 'cascade': 0, 'uid': 1,
        'muted': False, 'tts_on': True,
    }


def _snapshot(state):
    state['history'].append(json.dumps(state['scene'], ensure_ascii=False))
    if len(state['history']) > MAX_HISTORY:
        state['history'].pop(0)
    state['redo'] = []


def _restore(state, payload):
    state['scene'] = json.loads(payload)
    state['selected'] = []


def _ok(msg, action=None):
    r = {'ok': True, 'msg': msg}
    if action:
        r['action'] = action
    return r


def _err(msg):
    return {'ok': False, 'msg': msg}


def _new_shape(state, **kw):
    sp = {'id': state['uid'], 'rot': 0, 'style': 'fill', 'opacity': 1,
          'flipX': False, 'flipY': False, 'weight': 1}
    sp.update(kw)
    state['uid'] += 1
    return sp


def _cascade_pos(state):
    i = state['cascade']
    state['cascade'] += 1
    return {'fx': .5 + ((i % 5) - 2) * .09, 'fy': .5 + ((i // 5 % 3) - 1) * .13}


# 各图形相对中心的半宽/半高近似（用于对齐/分布），与前端 bbox 保持一致
def _extent(s):
    r = s['size']
    t = s['type']
    if t in ('circle', 'triangle', 'star', 'pentagon', 'hexagon', 'diamond',
             'moon', 'cross', 'ring', 'lightning'):
        return r, r
    if t == 'ellipse':
        return r * 1.3, r * .8
    if t == 'square':
        return r * .85, r * .85
    if t == 'rect':
        return r * 1.2, r * .7
    if t == 'heart':
        return r * 1.1, r
    if t == 'cloud':
        return r * 1.3, r * .8
    if t == 'speech':
        return r * 1.2, r
    if t == 'line':
        return r * 1.5, max(4, r * .12)
    if t == 'vline':
        return max(4, r * .12), r * 1.5
    if t == 'arrow':
        return r * 1.5, r * .4
    if t == 'text':
        return max(20, len(s.get('text', '')) * r * .62), r * .6
    return r, r


def _centroid(shapes):
    n = len(shapes)
    return sum(s['x'] for s in shapes) / n, sum(s['y'] for s in shapes) / n


_TARGET_HEAD = re.compile(r'^(把|将|让|给|对)')
_NTH_RE = re.compile('第(' + NUM_CLASS + ')个')


def resolve_targets(state, seg):
    """「它 / 第N个X / 所有X / 最后一个 / 这组」→ 具体图形列表。"""
    seg = _TARGET_HEAD.sub('', seg or '')
    shapes = state['scene']['shapes']
    if not shapes:
        return {'list': [], 'desc': '', 'empty': True}
    sh = find_shape(seg)
    if re.search(r'全部|所有|每个|每一个|都', seg):
        lst = [s for s in shapes if s['type'] == sh['type']] if sh else list(shapes)
        return {'list': lst, 'desc': ('所有' + sh['label']) if sh else '全部图形'}
    m = _NTH_RE.search(seg)
    if m:
        n = cn2num(m.group(1))
        pool = [s for s in shapes if s['type'] == sh['type']] if sh else shapes
        item = pool[n - 1] if 0 < n <= len(pool) else None
        return {'list': [item] if item else [],
                'desc': '第%d个%s' % (n, sh['label'] if sh else '图形')}
    if re.search(r'最后|最近|刚才|刚刚|它|这个|那个|上一个|这组|那组', seg):
        last = shapes[-1]
        # 若最近的图形属于某个组（复合模板），整组一起作为目标
        if last.get('group'):
            grp = [s for s in shapes if s.get('group') == last['group']]
            return {'list': grp, 'desc': '最近的图形'}
        return {'list': [last], 'desc': '最近的图形'}
    if sh:
        return {'list': [s for s in shapes if s['type'] == sh['type']], 'desc': '所有' + sh['label']}
    sel = [s for s in shapes if s['id'] in state['selected']]
    if sel:
        return {'list': sel, 'desc': '选中的图形'}
    return {'list': [shapes[-1]], 'desc': '最近的图形'}


# ---------------- 系统类意图 ----------------

def _i_help_close(state, t):
    return _ok('已关闭帮助', action='help_close')


def _i_help_open(state, t):
    return _ok('已打开指令手册，说「关闭帮助」返回', action='help_open')


def _i_tts_off(state, t):
    state['tts_on'] = False
    return _ok('语音播报已关闭', action='tts_off')


def _i_tts_on(state, t):
    state['tts_on'] = True
    return _ok('语音播报已打开', action='tts_on')


def _i_mute(state, t):
    state['muted'] = True
    return _ok('聆听已暂停，说「继续聆听」恢复', action='mute')


def _i_save(state, t):
    return _ok('已导出 PNG 图片', action='export')


def _i_zoom(state, t):
    if re.search(r'适应|铺满|填满窗口|看全部|全部显示', t):
        return _ok('画布已适应窗口', action='zoom_fit')
    if re.search(r'实际大小|原始大小|100|一比一|还原缩放', t):
        return _ok('画布缩放已还原', action='zoom_reset')
    if re.search(r'放大画布|画布放大|视图放大|拉近', t):
        return _ok('画布已放大', action='zoom_in')
    return _ok('画布已缩小', action='zoom_out')


def _i_grid(state, t):
    on = not re.search(r'关闭|隐藏|去掉|取消|不要', t)
    return _ok('网格已' + ('显示' if on else '隐藏'), action='grid_on' if on else 'grid_off')


def _i_undo(state, t):
    if not state['history']:
        return _err('没有可撤销的操作')
    state['redo'].append(json.dumps(state['scene'], ensure_ascii=False))
    _restore(state, state['history'].pop())
    return _ok('已撤销')


def _i_redo(state, t):
    if not state['redo']:
        return _err('没有可重做的操作')
    state['history'].append(json.dumps(state['scene'], ensure_ascii=False))
    _restore(state, state['redo'].pop())
    return _ok('已重做')


def _i_clear(state, t):
    if not state['scene']['shapes'] and state['scene']['bg'] == '#fafafa':
        return _err('画布已经是空的')
    _snapshot(state)
    state['scene'] = {'shapes': [], 'bg': '#fafafa'}
    state['selected'] = []
    state['cascade'] = 0
    return _ok('已清空画布')


def _i_background(state, t):
    c = find_color(t)
    _snapshot(state)
    state['scene']['bg'] = c['hex']
    return _ok('背景已换成' + c['label'])


# ---------------- 复合模板 ----------------

def _build_template(state, kind, cx, cy, r, group):
    """返回组成模板的图形列表（围绕 cx,cy，半径量级 r）。"""
    out = []

    def add(typ, dx, dy, sz, color, **extra):
        kw = dict(type=typ, x=cx + dx, y=cy + dy, size=sz, color=color, group=group)
        kw.update(extra)
        out.append(_new_shape(state, **kw))

    if kind == 'smiley':
        add('circle', 0, 0, r, '#fbbf24')
        add('circle', -r * .38, -r * .28, r * .12, '#111113')
        add('circle', r * .38, -r * .28, r * .12, '#111113')
        add('smile', 0, r * .1, r * .5, '#111113', weight=1.8)  # 下弯笑弧
    elif kind == 'house':
        add('square', 0, r * .35, r * .72, '#f59e0b')        # 墙身
        add('triangle', 0, -r * .55, r * .9, '#dc2626')       # 屋顶
        add('rect', 0, r * .62, r * .16, '#7c3aed')           # 门
    elif kind == 'sun':
        for i in range(8):
            add('line', 0, 0, r * .9, '#f59e0b', rot=(i * 45) % 180)  # 光芒
        add('circle', 0, 0, r * .55, '#fbbf24')               # 日轮
    elif kind == 'tree':
        add('rect', 0, r * .72, r * .3, '#92400e')            # 树干
        add('circle', 0, -r * .2, r * .65, '#16a34a')         # 树冠
        add('circle', -r * .45, r * .15, r * .42, '#16a34a')
        add('circle', r * .45, r * .15, r * .42, '#16a34a')
    elif kind == 'flower':
        for i in range(6):
            a = i * math.pi / 3
            add('circle', math.cos(a) * r * .6, math.sin(a) * r * .6, r * .35, '#ec4899')
        add('circle', 0, 0, r * .3, '#fbbf24')                # 花蕊
    elif kind == 'snowman':
        add('circle', 0, r * .7, r * .6, '#f8fafc')
        add('circle', 0, -r * .1, r * .45, '#f8fafc')
        add('circle', 0, -r * .75, r * .32, '#f8fafc')
        add('circle', -r * .1, -r * .8, r * .05, '#111113')
        add('circle', r * .1, -r * .8, r * .05, '#111113')
    return out


def _i_template(state, t):
    tpl = find_template(t)
    size = find_size(t) or {'size': 120, 'label': ''}
    r = max(40, size['size'])
    pos = find_position(t) or {'fx': .5, 'fy': .5, 'label': ''}
    group = 'g%d' % state['uid']
    _snapshot(state)
    cx, cy = pos['fx'] * LOGICAL_W, pos['fy'] * LOGICAL_H
    parts = _build_template(state, tpl['type'], cx, cy, r, group)
    for p in parts:
        p.setdefault('name', tpl['label'])
        state['scene']['shapes'].append(p)
    state['selected'] = [p['id'] for p in parts]
    return _ok('已画一个%s（%d 个部件）%s' % (
        tpl['label'], len(parts), ('（%s）' % pos['label']) if pos['label'] else ''))


# ---------------- 文字 ----------------

_TEXT_VERB_RE = re.compile(r'^(写上|写下|写|添加文字|加文字|输入文字|输入)[:：]?')
_TEXT_COLOR_RE = re.compile(r'^(.{1,4}色)的')


def _i_text(state, t):
    content = _TEXT_VERB_RE.sub('', t)
    content = re.sub(r'^(一个|个)', '', content)
    color = {'hex': '#18191a', 'label': ''}
    cm = _TEXT_COLOR_RE.match(content)
    if cm:
        cc = find_color(cm.group(1))
        if cc:
            color = cc
            content = content[len(cm.group(0)):]
    content = content.strip()[:30]
    if not content:
        return _err('没听到要写的内容，试试「写上你好」')
    pos = find_position(t) or _cascade_pos(state)
    size = (find_size(t) or {'size': 40})['size']
    _snapshot(state)
    sp = _new_shape(state, type='text', text=content,
                    x=pos['fx'] * LOGICAL_W, y=pos['fy'] * LOGICAL_H,
                    size=size, color=color['hex'])
    state['scene']['shapes'].append(sp)
    state['selected'] = [sp['id']]
    return _ok('已写下「%s」' % content)


# ---------------- 选择 / 删除 / 复制 ----------------

_SELECT_RE = re.compile(r'^(选中|选择|选取|选)')


def _i_select(state, t):
    tg = resolve_targets(state, _SELECT_RE.sub('', t))
    if tg.get('empty'):
        return _err('画布上还没有图形')
    if not tg['list']:
        return _err('没有找到' + tg['desc'])
    state['selected'] = [s['id'] for s in tg['list']]
    return _ok('已选中%s（%d 个）' % (tg['desc'], len(tg['list'])))


_DELETE_RE = re.compile(r'删除|删掉|移除|去掉|擦掉')


def _i_delete(state, t):
    tg = resolve_targets(state, _DELETE_RE.sub('', t))
    if tg.get('empty'):
        return _err('画布上还没有图形')
    if not tg['list']:
        return _err('没有找到' + tg['desc'])
    _snapshot(state)
    ids = {s['id'] for s in tg['list']}
    state['scene']['shapes'] = [s for s in state['scene']['shapes'] if s['id'] not in ids]
    state['selected'] = [i for i in state['selected'] if i not in ids]
    return _ok('已删除%s（%d 个）' % (tg['desc'], len(tg['list'])))


def _i_duplicate(state, t):
    seg = re.sub(r'复制|拷贝|克隆|再复制', '', t)
    tg = resolve_targets(state, seg)
    if tg.get('empty') or not tg['list']:
        return _err('画布上没有可复制的图形')
    _snapshot(state)
    created = []
    for s in tg['list']:
        sp = dict(s)
        sp['id'] = state['uid']
        state['uid'] += 1
        sp['x'] += 40
        sp['y'] += 32
        sp.pop('group', None)
        state['scene']['shapes'].append(sp)
        created.append(sp['id'])
    state['selected'] = created
    return _ok('已复制%s（%d 个）' % (tg['desc'], len(created)))


def _i_repeat(state, t):
    shapes = state['scene']['shapes']
    if not shapes:
        return _err('还没有可以重复的图形')
    _snapshot(state)
    sp = dict(shapes[-1])
    sp['id'] = state['uid']
    state['uid'] += 1
    sp['x'] += 38
    sp['y'] += 30
    shapes.append(sp)
    state['selected'] = [sp['id']]
    return _ok('已再画一个' + SHAPE_LABEL.get(sp['type'], '图形'))


# ---------------- 绘制 ----------------

_DRAW_VERB_RE = re.compile(
    r'画|绘制|生成|创建|添加|加上|加一|加个|加几|来一|来个|来几|放一|放个|做一|做个|给我一|要一|要个')
_COUNT_RE = re.compile('(?<!第)(' + NUM_CLASS + r')\s*[个只条根颗枚位张朵棵]')
_HOLLOW_RE = re.compile(r'空心|镂空|描边|只要边框')


def _i_draw(state, t):
    shape = find_shape(t)
    color = find_color(t) or {'hex': '#5e6ad2', 'label': ''}
    size = find_size(t) or {'size': 55, 'label': ''}
    pos = find_position(t)
    hollow = bool(_HOLLOW_RE.search(t))
    count = 1
    cm = _COUNT_RE.search(t)
    if cm:
        count = min(MAX_SHAPES_PER_DRAW, max(1, cn2num(cm.group(1))))
    if re.search(r'竖排|一列|排成一列|纵向', t):
        layout = 'col'
    elif re.search(r'随机|散开|到处', t):
        layout = 'random'
    elif re.search(r'叠在一起|重叠', t):
        layout = 'stack'
    else:
        layout = 'row'
    _snapshot(state)
    anchor = {'fx': pos['fx'], 'fy': pos['fy']} if pos else (
        {'fx': .5, 'fy': .5} if count > 1 else _cascade_pos(state))
    gap = size['size'] * 2.4
    created = []
    for i in range(count):
        x, y = anchor['fx'] * LOGICAL_W, anchor['fy'] * LOGICAL_H
        if count > 1:
            if layout == 'row':
                x += (i - (count - 1) / 2) * gap
            elif layout == 'col':
                y += (i - (count - 1) / 2) * gap
            elif layout == 'random':
                x = (0.12 + random.random() * 0.76) * LOGICAL_W
                y = (0.12 + random.random() * 0.76) * LOGICAL_H
            else:
                x += i * 6
                y += i * 6
        sp = _new_shape(state, type=shape['type'], x=x, y=y, size=size['size'],
                        color=color['hex'], style='stroke' if hollow else 'fill')
        if shape['type'] == 'text':
            sp['text'] = '文字'
        state['scene']['shapes'].append(sp)
        created.append(sp['id'])
    state['selected'] = created
    msg = '已画%s%s%s%s%s%s' % (
        (' %d 个' % count) if count > 1 else '一个',
        '空心' if hollow else '', size['label'], color['label'], shape['label'],
        ('（%s）' % pos['label']) if pos else '')
    return _ok(msg)


# ---------------- 移动 ----------------

_MOVETO_RE = re.compile(r'^(.*?)(?:移到|移动到|放到|挪到|拖到|放在|移至)(.+)$')


def _i_move_to(state, t):
    m = _MOVETO_RE.match(t)
    if not m:
        return _err('没听清要移到哪里')
    pos = find_position(m.group(2))
    if not pos:
        return _err('没听懂位置「%s」，试试「中间 / 左上角」' % m.group(2))
    tg = resolve_targets(state, m.group(1))
    if tg.get('empty') or not tg['list']:
        return _err('画布上没有可移动的图形')
    _snapshot(state)
    tx, ty = pos['fx'] * LOGICAL_W, pos['fy'] * LOGICAL_H
    if len(tg['list']) == 1:
        tg['list'][0]['x'], tg['list'][0]['y'] = tx, ty
    else:
        # 多个图形/组：整体平移到目标，保持相对构图
        cx, cy = _centroid(tg['list'])
        for s in tg['list']:
            s['x'] += tx - cx
            s['y'] += ty - cy
    return _ok('已把%s移到%s' % (tg['desc'], pos['label']))


_MOVE_RE = re.compile(
    r'^(.*?)(?:向|往|朝)(上|下|左|右)(?:边|面|方)?(?:移动|挪动|平移|移|挪|动)'
    '(' + NUM_CLASS + r')?(?:个像素|像素|px|点)?(一点点|一点|一些|许多|很多)?')
_MOVE_WORD_DIST = {'一点点': 12, '一点': 20, '一些': 40, '许多': 120, '很多': 120}
_DIRS = {'上': (0, -1), '下': (0, 1), '左': (-1, 0), '右': (1, 0)}


def _i_move(state, t):
    m = _MOVE_RE.match(t)
    if not m:
        return _err('没听清移动指令')
    if m.group(3):
        dist = min(2000, cn2num(m.group(3)))
    elif m.group(4):
        dist = _MOVE_WORD_DIST[m.group(4)]
    else:
        dist = 40
    tg = resolve_targets(state, m.group(1))
    if tg.get('empty') or not tg['list']:
        return _err('画布上没有可移动的图形')
    dx, dy = _DIRS[m.group(2)]
    _snapshot(state)
    for s in tg['list']:
        s['x'] += dx * dist
        s['y'] += dy * dist
    return _ok('已把%s向%s移动 %d 像素' % (tg['desc'], m.group(2), dist))


# ---------------- 缩放 ----------------

_GROW_RE = re.compile(r'放大|变大|加大|增大|调大|改大|大一点|大一些')
_RESIZE_SPLIT_RE = re.compile(r'放大|缩小|变大|变小|加大|增大|调大|调小|改大|改小|大一点|小一点|大一些|小一些')
_FACTOR_RE = re.compile('(' + NUM_CLASS + r')\s*(倍|%)')


def _i_resize(state, t):
    grow = bool(_GROW_RE.search(t))
    factor = 1.35 if grow else 0.7
    m = _FACTOR_RE.search(t)
    if m:
        n = cn2num(m.group(1))
        if m.group(2) == '倍':
            k = min(6, 2 if n <= 1 else n)  # 「放大一倍」口语含义为 2 倍
            factor = k if grow else 1 / k
        else:
            factor = min(6, max(.05, n / 100))
    elif '一点点' in t:
        factor = 1.12 if grow else 0.88
    elif re.search(r'一点|一些', t):
        factor = 1.18 if grow else 0.84
    elif re.search(r'很多|大幅', t):
        factor = 1.8 if grow else 0.55
    seg = _RESIZE_SPLIT_RE.split(t)[0]
    tg = resolve_targets(state, seg)
    if tg.get('empty') or not tg['list']:
        return _err('画布上没有可缩放的图形')
    _snapshot(state)
    if len(tg['list']) == 1:
        s = tg['list'][0]
        s['size'] = min(500, max(6, s['size'] * factor))
    else:
        # 组/多选：围绕质心整体缩放，保持构图比例
        cx, cy = _centroid(tg['list'])
        for s in tg['list']:
            s['size'] = min(500, max(6, s['size'] * factor))
            s['x'] = cx + (s['x'] - cx) * factor
            s['y'] = cy + (s['y'] - cy) * factor
    return _ok('已%s%s' % ('放大' if factor > 1 else '缩小', tg['desc']))


# ---------------- 旋转 ----------------

_DEG_RE = re.compile('(' + NUM_CLASS + r')\s*度')
_ROTATE_SPLIT_RE = re.compile(r'逆时针|顺时针|向左|向右|旋转|转动')


def _i_rotate(state, t):
    ccw = bool(re.search(r'逆时针|向左', t))
    m = _DEG_RE.search(t)
    deg = (cn2num(m.group(1)) if m else 45) * (-1 if ccw else 1)
    seg = _ROTATE_SPLIT_RE.split(t)[0]
    tg = resolve_targets(state, seg)
    if tg.get('empty') or not tg['list']:
        return _err('画布上没有可旋转的图形')
    _snapshot(state)
    for s in tg['list']:
        s['rot'] = (s.get('rot', 0) + deg) % 360
    return _ok('已把%s%s旋转 %d 度' % (tg['desc'], '逆时针' if ccw else '顺时针', abs(deg)))


# ---------------- 翻转 ----------------

def _i_flip(state, t):
    vertical = bool(re.search(r'垂直|上下', t))
    seg = re.split(r'水平翻转|左右翻转|垂直翻转|上下翻转|镜像|翻转', t)[0]
    tg = resolve_targets(state, seg)
    if tg.get('empty') or not tg['list']:
        return _err('画布上没有可翻转的图形')
    _snapshot(state)
    for s in tg['list']:
        if vertical:
            s['flipY'] = not s.get('flipY', False)
        else:
            s['flipX'] = not s.get('flipX', False)
    return _ok('已%s翻转%s' % ('垂直' if vertical else '水平', tg['desc']))


# ---------------- 透明度 ----------------

_OPACITY_RE = re.compile('透明度.*?(' + NUM_CLASS + r')\s*%?|(' + NUM_CLASS + r')\s*%')


def _i_opacity(state, t):
    if re.search(r'不透明|完全显示|恢复透明度', t):
        val = 1.0
    elif re.search(r'半透明', t):
        val = 0.5
    else:
        m = _OPACITY_RE.search(t)
        if m:
            n = cn2num(m.group(1) or m.group(2))
            val = min(1.0, max(0.05, n / 100))
        elif re.search(r'透明一点|更透明|淡一点', t):
            val = None  # 相对降低
        else:
            val = 0.5
    seg = re.split(r'透明度|半透明|透明|不透明|淡一点', t)[0]
    tg = resolve_targets(state, seg)
    if tg.get('empty') or not tg['list']:
        return _err('画布上没有图形')
    _snapshot(state)
    for s in tg['list']:
        if val is None:
            s['opacity'] = max(0.05, s.get('opacity', 1) - 0.25)
        else:
            s['opacity'] = val
    shown = tg['list'][0]['opacity']
    return _ok('已把%s透明度设为 %d%%' % (tg['desc'], round(shown * 100)))


# ---------------- 描边粗细 ----------------

def _i_strokewidth(state, t):
    thicker = bool(re.search(r'加粗|变粗|粗一点|粗一些|更粗', t))
    seg = re.split(r'加粗|变粗|粗一点|粗一些|更粗|变细|细一点|细一些|更细|描边粗细|线条粗细', t)[0]
    tg = resolve_targets(state, seg)
    if tg.get('empty') or not tg['list']:
        return _err('画布上没有图形')
    _snapshot(state)
    for s in tg['list']:
        w = s.get('weight', 1) * (1.5 if thicker else 0.67)
        s['weight'] = min(6, max(0.3, w))
        if thicker and s.get('style') == 'fill':
            s['style'] = 'stroke'  # 加粗描边时自动转空心，效果才可见
    return _ok('已把%s描边%s' % (tg['desc'], '加粗' if thicker else '变细'))


# ---------------- 层级 z-order ----------------

def _i_zorder(state, t):
    shapes = state['scene']['shapes']
    seg = re.split(r'置于顶层|置顶|移到最前|放到最前|置于底层|置底|移到最后|放到最后|上移一层|下移一层|往上一层|往下一层', t)[0]
    tg = resolve_targets(state, seg)
    if tg.get('empty') or not tg['list']:
        return _err('画布上没有图形')
    ids = [s['id'] for s in tg['list']]
    picked = [s for s in shapes if s['id'] in ids]
    rest = [s for s in shapes if s['id'] not in ids]
    _snapshot(state)
    if re.search(r'置于顶层|置顶|移到最前|放到最前|最前面?', t):
        state['scene']['shapes'] = rest + picked
        return _ok('已把%s置于顶层' % tg['desc'])
    if re.search(r'置于底层|置底|移到最后|放到最后|最后面?|最底', t):
        state['scene']['shapes'] = picked + rest
        return _ok('已把%s置于底层' % tg['desc'])
    up = bool(re.search(r'上移|往上|向上', t))
    arr = shapes[:]
    idxs = sorted([arr.index(s) for s in picked], reverse=not up)
    for i in idxs:
        j = i + 1 if up else i - 1
        if 0 <= j < len(arr):
            arr[i], arr[j] = arr[j], arr[i]
    state['scene']['shapes'] = arr
    return _ok('已把%s%s一层' % (tg['desc'], '上移' if up else '下移'))


# ---------------- 对齐 / 分布 ----------------

def _i_align(state, t):
    seg = re.split(r'左对齐|右对齐|顶部?对齐|底部?对齐|上对齐|下对齐|水平居中|垂直居中|左右居中|上下居中|居中对齐|对齐', t)[0]
    tg = resolve_targets(state, seg)
    if tg.get('empty') or len(tg['list']) < 2:
        return _err('对齐至少需要两个图形，先「选中所有X」')
    lst = tg['list']
    _snapshot(state)
    if re.search(r'左对齐|左边对齐', t):
        edge = min(s['x'] - _extent(s)[0] for s in lst)
        for s in lst:
            s['x'] = edge + _extent(s)[0]
        how = '左对齐'
    elif re.search(r'右对齐|右边对齐', t):
        edge = max(s['x'] + _extent(s)[0] for s in lst)
        for s in lst:
            s['x'] = edge - _extent(s)[0]
        how = '右对齐'
    elif re.search(r'顶部?对齐|上对齐|上边对齐', t):
        edge = min(s['y'] - _extent(s)[1] for s in lst)
        for s in lst:
            s['y'] = edge + _extent(s)[1]
        how = '顶部对齐'
    elif re.search(r'底部?对齐|下对齐|下边对齐', t):
        edge = max(s['y'] + _extent(s)[1] for s in lst)
        for s in lst:
            s['y'] = edge - _extent(s)[1]
        how = '底部对齐'
    elif re.search(r'垂直居中|上下居中', t):
        cy = _centroid(lst)[1]
        for s in lst:
            s['y'] = cy
        how = '垂直居中'
    else:  # 水平居中 / 左右居中 / 居中对齐
        cx = _centroid(lst)[0]
        for s in lst:
            s['x'] = cx
        how = '水平居中'
    return _ok('已将%d 个图形%s' % (len(lst), how))


def _i_distribute(state, t):
    vertical = bool(re.search(r'垂直|竖直|纵向|上下', t))
    seg = re.split(r'水平分布|垂直分布|竖直分布|横向分布|纵向分布|均匀分布|平均分布|分布', t)[0]
    tg = resolve_targets(state, seg)
    if tg.get('empty') or len(tg['list']) < 3:
        return _err('均匀分布至少需要三个图形')
    lst = sorted(tg['list'], key=lambda s: s['y'] if vertical else s['x'])
    _snapshot(state)
    key = 'y' if vertical else 'x'
    lo, hi = lst[0][key], lst[-1][key]
    step = (hi - lo) / (len(lst) - 1)
    for i, s in enumerate(lst):
        s[key] = lo + step * i
    return _ok('已将%d 个图形%s均匀分布' % (len(lst), '垂直' if vertical else '水平'))


# ---------------- 改颜色 ----------------

_RECOLOR_RE = re.compile(r'^(.*?)(?:变成|改成|换成|涂成|染成|刷成|填成|变为|改为|填充)(.+)$')


def _i_recolor(state, t):
    m = _RECOLOR_RE.match(t)
    c = find_color(m.group(2) if m else t)
    if not c:
        return _err('没听懂要改成什么颜色')
    tg = resolve_targets(state, m.group(1) if m else '')
    if tg.get('empty') or not tg['list']:
        return _err('画布上没有可变色的图形')
    _snapshot(state)
    for s in tg['list']:
        s['color'] = c['hex']
    return _ok('已把%s改成%s' % (tg['desc'], c['label']))


def _i_bare_color(state, t):
    c = find_color(t)
    tg = resolve_targets(state, '')
    if tg.get('empty') or not tg['list']:
        return _err('画布上没有可变色的图形')
    _snapshot(state)
    for s in tg['list']:
        s['color'] = c['hex']
    return _ok('已把%s改成%s' % (tg['desc'], c['label']))


# ---------------- 空心 / 实心 ----------------

_STYLE_SPLIT_RE = re.compile(r'变成|改成|换成|空心|镂空|实心|填满|只要边框')


def _i_style(state, t):
    stroke = bool(re.search(r'空心|镂空|只要边框', t))
    seg = _STYLE_SPLIT_RE.split(t)[0]
    tg = resolve_targets(state, seg)
    if tg.get('empty') or not tg['list']:
        return _err('画布上没有图形')
    _snapshot(state)
    for s in tg['list']:
        s['style'] = 'stroke' if stroke else 'fill'
    return _ok('已把%s改为%s' % (tg['desc'], '空心' if stroke else '实心'))


# ---------------- 意图注册表（顺序即优先级） ----------------

INTENTS = [
    ('help_close', lambda t: re.search(r'关闭帮助|收起帮助|关掉帮助|退出帮助', t), _i_help_close),
    ('help_open', lambda t: re.search(r'帮助|怎么用|指令(列表|手册|大全)?$|说明书|教程|能做什么|会什么', t), _i_help_open),
    ('tts_off', lambda t: re.search(r'(关闭|停止|关掉|静音)(语音)?(播报|朗读|反馈)', t), _i_tts_off),
    ('tts_on', lambda t: re.search(r'(打开|开启|恢复)(语音)?(播报|朗读|反馈)', t), _i_tts_on),
    ('mute', lambda t: re.search(r'暂停聆听|停止聆听|暂停识别|休息一下|别听了', t), _i_mute),
    ('save', lambda t: re.search(r'保存|下载|导出|存一?下|存起来|存图', t), _i_save),
    ('grid', lambda t: re.search(r'网格|栅格', t), _i_grid),
    ('zoom', lambda t: re.search(r'适应窗口|看全部|全部显示|实际大小|原始大小|一比一|还原缩放|放大画布|画布放大|缩小画布|画布缩小|视图放大|视图缩小|拉近|拉远', t), _i_zoom),
    ('undo', lambda t: re.search(r'撤销|撤回|回退|后退一步|取消(上一步|刚才|操作)?$', t), _i_undo),
    ('redo', lambda t: re.search(r'重做|恢复上一步|恢复操作|前进一步', t), _i_redo),
    ('clear', lambda t: re.search(r'清空|清屏|全部删除|删除全部|全部清除|清除全部|重新开始|重来', t), _i_clear),
    ('background', lambda t: re.search(r'背景|底色|整个画布|^画布', t) and find_color(t), _i_background),
    ('template', lambda t: _DRAW_VERB_RE.search(t) and find_template(t) and not find_shape(t), _i_template),
    ('text', lambda t: _TEXT_VERB_RE.match(t), _i_text),
    ('select', lambda t: _SELECT_RE.match(t), _i_select),
    ('duplicate', lambda t: re.search(r'复制|拷贝|克隆', t), _i_duplicate),
    ('delete', lambda t: _DELETE_RE.search(t), _i_delete),
    ('repeat', lambda t: re.match(
        r'^(再来|再画|再加|再要)(一个|一次|个)?$|^(来|画)(一个|个|一次)$|^重复(一次|上一个)?$', t), _i_repeat),
    ('align', lambda t: re.search(r'对齐', t), _i_align),
    ('distribute', lambda t: re.search(r'均匀分布|平均分布|水平分布|垂直分布|竖直分布|横向分布|纵向分布', t), _i_distribute),
    ('zorder', lambda t: re.search(r'置于顶层|置顶|移到最前|放到最前|最前面|置于底层|置底|移到最后|放到最后|最后面|最底|上移一层|下移一层|往上一层|往下一层', t), _i_zorder),
    ('flip', lambda t: re.search(r'翻转|镜像', t), _i_flip),
    ('opacity', lambda t: re.search(r'透明', t), _i_opacity),
    ('strokewidth', lambda t: re.search(r'加粗|变粗|粗一点|粗一些|更粗|变细|细一点|细一些|更细|描边粗细|线条粗细', t), _i_strokewidth),
    ('draw', lambda t: _DRAW_VERB_RE.search(t) and find_shape(t), _i_draw),
    ('move_to', lambda t: re.search(r'移到|移动到|放到|挪到|拖到|放在|移至', t), _i_move_to),
    ('move', lambda t: _MOVE_RE.match(t), _i_move),
    ('resize', lambda t: _RESIZE_SPLIT_RE.search(t), _i_resize),
    ('rotate', lambda t: re.search(r'旋转|转动', t), _i_rotate),
    ('style', lambda t: re.search(r'空心|镂空|实心|填满|只要边框', t), _i_style),
    ('recolor', lambda t: _RECOLOR_RE.match(t) and find_color(t), _i_recolor),
    ('bare_color', lambda t: find_color(t) and len(re.sub(r'色|的|换成|变成|改成', '', t)) <= 4,
     _i_bare_color),
]

_RESUME_RE = re.compile(r'继续聆听|开始聆听|恢复聆听|继续工作|我回来了|继续吧')


def parse_clause(state, t):
    for name, match, run in INTENTS:
        if match(t):
            result = run(state, t)
            result['intent'] = name
            result['clause'] = t
            return result
    r = _err('没听懂「%s」，说「帮助」查看支持的指令' % t)
    r['intent'] = 'fallback'
    r['clause'] = t
    return r


def handle_utterance(state, raw):
    """完整流水线：归一化 → 分句 → 逐句解析执行。返回结果列表。"""
    t = normalize(raw)
    if not t:
        return []
    if state['muted']:
        if _RESUME_RE.search(t):
            state['muted'] = False
            return [{'ok': True, 'msg': '我在听', 'action': 'unmute',
                     'intent': 'unmute', 'clause': t}]
        return []  # 静音模式下忽略其他指令
    return [parse_clause(state, c) for c in split_clauses(t)]
