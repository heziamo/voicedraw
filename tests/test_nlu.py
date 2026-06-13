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
    assert s['type'] == 'circle' and s['color'] == '#e5484d' and s['size'] == 85
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
    assert shapes(state)[0]['color'] == '#3b6cf6'


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


def test_compound_draw_then_align(state):
    """「画三个方块再全部左对齐」——『再』须正确切分，否则 draw 被 align 吞掉。"""
    rs = run(state, '画一个笑脸放在中间然后画三个并排的蓝色方块再全部左对齐')
    assert [r['intent'] for r in rs] == ['template', 'draw', 'align']
    sq = [s for s in shapes(state) if s['type'] == 'square']
    assert len(sq) == 3
    lefts = [s['x'] - s['size'] for s in sq]
    assert max(lefts) - min(lefts) < 0.01  # 已左对齐


def test_split_keeps_parallel_layout(state):
    """『并排』里的『并』不可被当作连接词切开。"""
    rs = run(state, '画三个并排的方块')
    assert len(rs) == 1 and rs[0]['intent'] == 'draw'


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


# ---------- 新增图形 ----------

@pytest.mark.parametrize('text,typ', [
    ('画一个六边形', 'hexagon'), ('画一个菱形', 'diamond'), ('画一个月亮', 'moon'),
    ('画一朵云', 'cloud'), ('画一个圆环', 'ring'), ('画一个闪电', 'lightning'),
    ('画一个十字', 'cross'), ('画一个对话气泡', 'speech'), ('画一个五边形', 'pentagon'),
])
def test_new_shapes(state, text, typ):
    r = run(state, text)
    assert r[0]['ok'] and shapes(state)[0]['type'] == typ


def test_ring_not_shadowed_by_circle(state):
    """「圆环」必须解析为 ring 而非被「圆」截胡成 circle。"""
    run(state, '画一个圆环')
    assert shapes(state)[0]['type'] == 'ring'


# ---------- 复合模板 ----------

def test_template_smiley_is_group(state):
    r = run(state, '画一个笑脸')
    assert r[0]['ok'] and r[0]['intent'] == 'template'
    g = shapes(state)
    assert len(g) >= 4
    assert len({s['group'] for s in g}) == 1          # 同一组
    assert state['selected'] == [s['id'] for s in g]  # 整组选中


@pytest.mark.parametrize('text,parts_min', [
    ('画一个房子', 3), ('画一个太阳', 5), ('画一棵树', 4), ('画一朵花', 6), ('画一个雪人', 5),
])
def test_templates(state, text, parts_min):
    run(state, text)
    assert len(shapes(state)) >= parts_min


def test_group_move_preserves_layout(state):
    """整组移动到新位置后，内部相对构图不变（质心平移）。"""
    run(state, '画一个笑脸')
    g = shapes(state)
    rel_before = [(s['x'] - g[0]['x'], s['y'] - g[0]['y']) for s in g]
    run(state, '把它移到右上角')
    rel_after = [(s['x'] - g[0]['x'], s['y'] - g[0]['y']) for s in g]
    assert rel_before == rel_after  # 相对布局保持


def test_group_resize_preserves_layout(state):
    run(state, '画一个笑脸')
    g = shapes(state)
    cx0 = sum(s['x'] for s in g) / len(g)
    spread0 = max(s['x'] for s in g) - min(s['x'] for s in g)
    run(state, '放大一点')
    cx1 = sum(s['x'] for s in g) / len(g)
    spread1 = max(s['x'] for s in g) - min(s['x'] for s in g)
    assert cx1 == pytest.approx(cx0)   # 质心不动
    assert spread1 > spread0           # 整体铺开（构图等比放大）


# ---------- 高级编辑 ----------

def test_opacity_percent(state):
    run(state, '画一个圆')
    r = run(state, '把它透明度设为30%')
    assert r[0]['ok'] and shapes(state)[0]['opacity'] == pytest.approx(0.3)


def test_opacity_half(state):
    run(state, '画一个圆')
    run(state, '半透明')
    assert shapes(state)[0]['opacity'] == pytest.approx(0.5)


def test_flip_horizontal(state):
    run(state, '画一个箭头')
    r = run(state, '水平翻转')
    assert r[0]['ok'] and shapes(state)[0]['flipX'] is True


def test_flip_vertical(state):
    run(state, '画一个三角形')
    run(state, '垂直翻转')
    assert shapes(state)[0]['flipY'] is True


def test_duplicate(state):
    run(state, '画一个圆')
    r = run(state, '复制一份')
    assert r[0]['ok'] and len(shapes(state)) == 2
    assert shapes(state)[1]['x'] != shapes(state)[0]['x']  # 有偏移


def test_strokewidth_thicker(state):
    run(state, '画一个圆')
    r = run(state, '描边加粗')
    assert r[0]['ok']
    s = shapes(state)[0]
    assert s['weight'] > 1 and s['style'] == 'stroke'  # 加粗自动转空心可见


def test_zorder_to_front(state):
    run(state, '画一个红色的圆')      # 第 0 个
    run(state, '画一个蓝色的方块')    # 第 1 个（顶层）
    first_id = shapes(state)[0]['id']
    r = run(state, '把第一个圆置于顶层')
    assert r[0]['ok']
    assert shapes(state)[-1]['id'] == first_id  # 圆被移到数组末尾＝顶层


def test_zorder_send_back(state):
    run(state, '画一个圆')
    run(state, '画一个方块')
    last_id = shapes(state)[-1]['id']
    run(state, '置于底层')
    assert shapes(state)[0]['id'] == last_id


def test_align_left(state):
    run(state, '画三个随机的圆')
    run(state, '选中所有圆形')
    r = run(state, '左对齐')
    assert r[0]['ok']
    lefts = [s['x'] - s['size'] for s in shapes(state)]  # 圆 extent=size
    assert max(lefts) - min(lefts) < 0.01  # 左边缘对齐


def test_align_needs_two(state):
    run(state, '画一个圆')
    r = run(state, '左对齐')
    assert not r[0]['ok']  # 单个图形无法对齐


def test_distribute_horizontal(state):
    run(state, '画三个并排的方块')
    run(state, '选中所有方块')
    r = run(state, '水平均匀分布')
    assert r[0]['ok']
    xs = sorted(s['x'] for s in shapes(state))
    gap1, gap2 = xs[1] - xs[0], xs[2] - xs[1]
    assert gap1 == pytest.approx(gap2)  # 间距相等


def test_zoom_and_grid_actions(state):
    assert run(state, '画布适应窗口')[0]['action'] == 'zoom_fit'
    assert run(state, '隐藏网格')[0]['action'] == 'grid_off'
    assert run(state, '显示网格')[0]['action'] == 'grid_on'


# ---------- 文生图（大模型） ----------

def test_generate_intent(state):
    r = run(state, '生成一张星空下的城堡的图片')
    assert r[0]['intent'] == 'generate' and r[0]['action'] == 'generate_image'
    assert '星空下的城堡' in r[0]['prompt']
    assert shapes(state) == []  # 解析阶段不改场景，真正生成在 /generate 端点


@pytest.mark.parametrize('text,expect', [
    ('生成一张可爱的小猫的图片', '可爱的小猫'),
    ('用AI画一座雪山', '雪山'),
    ('帮我生成一幅日落海滩', '日落海滩'),
    ('画一张赛博朋克城市的图片', '赛博朋克城市'),
])
def test_generate_prompt_extraction(state, text, expect):
    r = run(state, text)
    assert r[0]['intent'] == 'generate' and expect in r[0]['prompt']


def test_generate_does_not_eat_normal_draw(state):
    """「生成一个圆」仍是参数化绘制，不走文生图。"""
    r = run(state, '生成一个圆')
    assert r[0]['intent'] == 'draw' and shapes(state)[0]['type'] == 'circle'


def test_image_is_editable_target(state):
    from app.nlu.engine import add_image
    add_image(state, '/media/x.png', 1024, 1024, '一只猫')
    assert shapes(state)[0]['type'] == 'image'
    size0 = shapes(state)[0]['size']
    assert run(state, '把图片放大')[0]['ok']
    assert shapes(state)[0]['size'] > size0
    assert run(state, '删除图片')[0]['ok'] and shapes(state) == []
