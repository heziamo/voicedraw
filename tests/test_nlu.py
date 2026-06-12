"""NLU 引擎测试：指令理解准确性、容错性、复杂指令拆解。"""
import pytest

from app.nlu import handle_utterance, new_state
from app.nlu.lexicon import cn2num
from app.nlu.normalizer import normalize, split_clauses


@pytest.fixture
def state():
    return new_state()


def run(state, text):
    return handle_utterance(state, text)


def shapes(state):
    return state['scene']['shapes']


# ---------- 中文数字 ----------

@pytest.mark.parametrize('s,n', [
    ('三', 3), ('两', 2), ('十', 10), ('十五', 15), ('二十三', 23),
    ('三百二十', 320), ('5', 5), ('50', 50),
])
def test_cn2num(s, n):
    assert cn2num(s) == n


# ---------- 归一化与容错 ----------

def test_homophone_fix():
    assert normalize('花一个园形') == '画一个圆形'
    assert normalize('画一个长方型') == '画一个长方形'
    assert normalize('请帮我画一个圆吧') == '画一个圆'


def test_split_clauses():
    assert split_clauses(normalize('画一个圆然后画一个方块')) == ['画一个圆', '画一个方块']
    assert split_clauses(normalize('画一个圆，再画一个方块')) == ['画一个圆', '画一个方块']


# ---------- 绘制 ----------

def test_draw_full_slots(state):
    r = run(state, '请帮我画一个红色的大圆在左上角')
    assert r[0]['ok'] and r[0]['intent'] == 'draw'
    s = shapes(state)[0]
    assert s['type'] == 'circle' and s['color'] == '#e5484d' and s['size'] == 80
    assert s['x'] == pytest.approx(240) and s['y'] == pytest.approx(150)


def test_draw_count_row(state):
    run(state, '画三个并排的蓝色方块')
    sq = [s for s in shapes(state) if s['type'] == 'square']
    assert len(sq) == 3
    assert sq[0]['y'] == sq[1]['y'] == sq[2]['y']
    assert sq[0]['x'] < sq[1]['x'] < sq[2]['x']


def test_draw_hollow(state):
    run(state, '画一个空心的绿色三角形')
    assert shapes(state)[0]['style'] == 'stroke'


def test_draw_default_color_is_brand(state):
    run(state, '画一个圆')
    assert shapes(state)[0]['color'] == '#5e6ad2'


def test_text_with_color_prefix(state):
    r = run(state, '写上红色的你好世界')
    assert r[0]['ok']
    s = shapes(state)[0]
    assert s['type'] == 'text' and s['text'] == '你好世界' and s['color'] == '#e5484d'


# ---------- 指代消解与修改 ----------

def test_pronoun_recolor(state):
    run(state, '画一个圆')
    r = run(state, '把它变成绿色')
    assert r[0]['ok'] and shapes(state)[0]['color'] == '#22c55e'


def test_nth_of_type(state):
    run(state, '画三个并排的蓝色方块')
    r = run(state, '第二个方块变成黄色')
    assert r[0]['ok']
    sq = [s for s in shapes(state) if s['type'] == 'square']
    assert sq[1]['color'] == '#eab308'
    assert sq[0]['color'] == sq[2]['color'] == '#3b82f6'


def test_all_of_type_delete(state):
    run(state, '画一个圆')
    run(state, '画三个并排的方块')
    r = run(state, '删除所有方块')
    assert r[0]['ok']
    assert [s['type'] for s in shapes(state)] == ['circle']


def test_move_pixels(state):
    run(state, '画一个圆')
    x0 = shapes(state)[0]['x']
    run(state, '向左移动50像素')
    assert shapes(state)[0]['x'] == x0 - 50


def test_move_to_anchor(state):
    run(state, '画一个圆')
    run(state, '把它移到中间')
    s = shapes(state)[0]
    assert s['x'] == pytest.approx(600) and s['y'] == pytest.approx(375)


def test_resize_double_means_2x(state):
    """「放大一倍」按口语习惯应为 2 倍（JS 版曾在此踩坑）。"""
    run(state, '画一个圆')
    run(state, '放大一倍')
    assert shapes(state)[0]['size'] == 110


def test_resize_percent(state):
    run(state, '画一个圆')
    run(state, '缩小到50%')
    assert shapes(state)[0]['size'] == pytest.approx(27.5)


def test_rotate_ccw(state):
    run(state, '画一个箭头')
    r = run(state, '逆时针旋转30度')
    assert r[0]['ok'] and shapes(state)[0]['rot'] == 330


def test_background(state):
    r = run(state, '把背景换成黑色')
    assert r[0]['ok'] and state['scene']['bg'] == '#111113'
    assert shapes(state) == []  # 背景指令不应误伤图形


# ---------- 撤销 / 重做 / 重复 ----------

def test_undo_redo(state):
    run(state, '画一个圆')
    run(state, '画一个方块')
    run(state, '撤销')
    assert len(shapes(state)) == 1
    run(state, '重做')
    assert len(shapes(state)) == 2


def test_repeat_survives_clause_split(state):
    """「再来一个」会被分句器切成「来一个」，意图仍需命中（JS 版曾在此踩坑）。"""
    run(state, '画一个圆')
    r = run(state, '再来一个')
    assert r[0]['ok'] and r[0]['intent'] == 'repeat'
    assert len(shapes(state)) == 2


def test_clear(state):
    run(state, '画一个圆')
    r = run(state, '清空画布')
    assert r[0]['ok'] and shapes(state) == []


# ---------- 复杂指令拆解 ----------

def test_compound_command(state):
    rs = run(state, '画一个方块然后把背景换成黑色')
    assert [r['intent'] for r in rs] == ['draw', 'background']
    assert all(r['ok'] for r in rs)


def test_cross_clause_target(state):
    rs = run(state, '在右下角画一个空心的五角星然后逆时针旋转30度')
    assert all(r['ok'] for r in rs)
    star = shapes(state)[0]
    assert star['type'] == 'star' and star['style'] == 'stroke' and star['rot'] == 330


# ---------- 系统指令与静音 ----------

def test_save_action(state):
    r = run(state, '保存图片')
    assert r[0]['action'] == 'export'


def test_mute_gating(state):
    run(state, '暂停聆听')
    assert state['muted']
    assert run(state, '画一个圆') == []     # 静音期间忽略
    assert shapes(state) == []
    r = run(state, '继续聆听')
    assert r[0]['action'] == 'unmute' and not state['muted']


def test_unknown_command_rejected(state):
    r = run(state, '跳个舞')
    assert not r[0]['ok'] and r[0]['intent'] == 'fallback'
