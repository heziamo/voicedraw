"""词典层：颜色 / 图形 / 复合模板 / 位置 / 大小 / 谐音矫正 / 中文数字。"""
import re

NUM_CLASS = r'[0-9一二两三四五六七八九十百零〇]+'

_CN_DIGITS = {'零': 0, '〇': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4,
              '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}


def cn2num(s):
    """中文数字转阿拉伯数字，支持到几百（'二十三'→23，'1 5'容错为15）。"""
    if not s:
        return 0
    if s.isdigit():
        return int(s)
    n, cur = 0, 0
    for ch in s:
        if ch == '百':
            cur = (cur or 1) * 100
            n += cur
            cur = 0
        elif ch == '十':
            cur = (cur or 1) * 10
            n += cur
            cur = 0
        elif ch in _CN_DIGITS:
            cur = _CN_DIGITS[ch]
        elif ch.isdigit():
            cur = cur * 10 + int(ch)
    return n + cur


# (关键词, 色值, 标准名)，长词在前避免「深蓝」被「蓝」截胡
COLORS = [
    ('薰衣草色', '#828fff', '薰衣草色'), ('淡紫色', '#828fff', '淡紫色'),
    ('深蓝色', '#1e40af', '深蓝色'), ('天蓝色', '#38bdf8', '天蓝色'), ('深绿色', '#15803d', '深绿色'),
    ('粉红色', '#f472b6', '粉红色'), ('橘黄色', '#f97316', '橘黄色'), ('咖啡色', '#a16207', '咖啡色'),
    ('薄荷绿', '#34d399', '薄荷绿'), ('珊瑚色', '#fb7185', '珊瑚色'), ('藏青色', '#1e3a8a', '藏青色'),
    ('玫红色', '#e11d48', '玫红色'), ('米色', '#e7e0cf', '米色'), ('浅蓝', '#93c5fd', '浅蓝色'),
    ('深紫', '#7c3aed', '深紫色'), ('深蓝', '#1e40af', '深蓝色'), ('天蓝', '#38bdf8', '天蓝色'),
    ('深绿', '#15803d', '深绿色'), ('深红', '#b91c1c', '深红色'), ('粉红', '#f472b6', '粉红色'),
    ('草绿', '#84cc16', '草绿色'), ('薄荷', '#34d399', '薄荷绿'), ('珊瑚', '#fb7185', '珊瑚色'),
    ('红色', '#e5484d', '红色'), ('橙色', '#f97316', '橙色'), ('橘色', '#f97316', '橘色'),
    ('黄色', '#eab308', '黄色'), ('金色', '#fbbf24', '金色'), ('绿色', '#22c55e', '绿色'),
    ('青色', '#06b6d4', '青色'), ('蓝色', '#3b82f6', '蓝色'), ('紫色', '#a855f7', '紫色'),
    ('粉色', '#f472b6', '粉色'), ('棕色', '#a16207', '棕色'), ('黑色', '#111113', '黑色'),
    ('白色', '#fafafa', '白色'), ('灰色', '#8a8f98', '灰色'), ('银色', '#cbd5e1', '银色'),
    ('红', '#e5484d', '红色'), ('橙', '#f97316', '橙色'), ('黄', '#eab308', '黄色'),
    ('绿', '#22c55e', '绿色'), ('青', '#06b6d4', '青色'), ('蓝', '#3b82f6', '蓝色'),
    ('紫', '#a855f7', '紫色'), ('粉', '#f472b6', '粉色'), ('黑', '#111113', '黑色'),
    ('白', '#fafafa', '白色'), ('灰', '#8a8f98', '灰色'), ('金', '#fbbf24', '金色'),
    ('棕', '#a16207', '棕色'),
]

# (关键词, 类型)，长词在前；新增图形放在易冲突的短词之前
SHAPES = [
    ('正方形', 'square'), ('长方形', 'rect'), ('三角形', 'triangle'), ('五角星', 'star'),
    ('六边形', 'hexagon'), ('五边形', 'pentagon'), ('对话气泡', 'speech'), ('对话框', 'speech'),
    ('椭圆形', 'ellipse'), ('椭圆', 'ellipse'),
    ('圆环', 'ring'), ('圆圈', 'circle'), ('圆形', 'circle'), ('圈圈', 'circle'),
    ('甜甜圈', 'ring'), ('环形', 'ring'),
    ('方块', 'square'), ('方形', 'square'), ('矩形', 'rect'),
    ('星星', 'star'), ('星形', 'star'), ('心形', 'heart'), ('爱心', 'heart'), ('桃心', 'heart'),
    ('菱形', 'diamond'), ('钻石', 'diamond'),
    ('月亮', 'moon'), ('月牙', 'moon'), ('云朵', 'cloud'), ('白云', 'cloud'),
    ('闪电', 'lightning'), ('十字', 'cross'), ('加号', 'cross'), ('气泡', 'speech'),
    ('竖线', 'vline'), ('直线', 'line'), ('横线', 'line'), ('线条', 'line'), ('线段', 'line'),
    ('箭头', 'arrow'), ('文字', 'text'), ('圆', 'circle'), ('云', 'cloud'),
]

SHAPE_LABEL = {
    'circle': '圆形', 'square': '正方形', 'rect': '长方形', 'triangle': '三角形',
    'star': '五角星', 'heart': '心形', 'line': '直线', 'vline': '竖线', 'arrow': '箭头',
    'ellipse': '椭圆', 'text': '文字', 'hexagon': '六边形', 'pentagon': '五边形',
    'diamond': '菱形', 'ring': '圆环', 'moon': '月亮', 'cloud': '云朵',
    'lightning': '闪电', 'cross': '十字', 'speech': '对话气泡',
}

# 复合模板：一条指令生成多个图形（关键词长在前）
TEMPLATES = [
    ('笑脸表情', 'smiley'), ('小房子', 'house'), ('房子', 'house'), ('房屋', 'house'),
    ('雪人', 'snowman'), ('笑脸', 'smiley'), ('太阳', 'sun'), ('花朵', 'flower'),
    ('小花', 'flower'), ('大树', 'tree'), ('小树', 'tree'), ('树', 'tree'), ('花', 'flower'),
]
TEMPLATE_LABEL = {'smiley': '笑脸', 'house': '房子', 'sun': '太阳',
                  'tree': '树', 'flower': '花朵', 'snowman': '雪人'}

# (关键词, fx, fy)：逻辑画布上的相对坐标
POSITIONS = [
    ('左上角', .2, .2), ('右上角', .8, .2), ('左下角', .2, .8), ('右下角', .8, .8),
    ('左上', .2, .2), ('右上', .8, .2), ('左下', .2, .8), ('右下', .8, .8),
    ('正中间', .5, .5), ('正中央', .5, .5), ('正中', .5, .5), ('中间', .5, .5),
    ('中央', .5, .5), ('中心', .5, .5),
    ('上面', .5, .18), ('上方', .5, .18), ('上边', .5, .18), ('顶部', .5, .18),
    ('下面', .5, .82), ('下方', .5, .82), ('下边', .5, .82), ('底部', .5, .82),
    ('左边', .18, .5), ('左侧', .18, .5), ('左面', .18, .5),
    ('右边', .82, .5), ('右侧', .82, .5), ('右面', .82, .5),
]

SIZE_WORDS = [
    ('超级大', 130), ('超大', 130), ('巨大', 130), ('特大', 130), ('非常大', 100), ('很大', 100),
    ('中等', 55), ('中号', 55), ('很小', 22), ('超小', 22), ('特小', 22), ('迷你', 22),
    ('大', 85), ('小', 36),
]

# 谐音 / ASR 常见误识矫正
HOMOPHONES = [
    (re.compile(r'[花话化](?=一个|两个|三个|几个|个|一只|一朵|一棵|一座)'), '画'),
    (re.compile(r'(方|角|圆|心|星|形|菱)型'), r'\1形'),
    (re.compile(r'园(?=形|圈|环)'), '圆'),
    (re.compile(r'[原元]形'), '圆形'),
    (re.compile(r'三脚形'), '三角形'),
    (re.compile(r'[兰篮]色'), '蓝色'),
    (re.compile(r'撤消'), '撤销'),
    (re.compile(r'[青情]空(?=画布)?'), '清空'),
    (re.compile(r'百分之\s*([0-9]+)'), r'\1%'),
    (re.compile(r'大概|大约'), ''),
]

FILLER_HEAD = re.compile(r'^(请|麻烦|帮我|帮忙|给我|我想要|我想|我要|能不能|可不可以|可以)+')
FILLER_TAIL = re.compile(r'(吧|啊|呀|哦|呢|哈|好吗|谢谢|了)+$')

_SIZE_PX_RE = re.compile('(' + NUM_CLASS + r')\s*(?:个像素|像素|px)')
_SIZE_RADIUS_RE = re.compile('半径\\s*(' + NUM_CLASS + ')')


def find_color(t):
    for key, hexv, label in COLORS:
        if key in t:
            return {'hex': hexv, 'label': label}
    return None


def find_shape(t):
    for key, typ in SHAPES:
        if key in t:
            return {'type': typ, 'label': SHAPE_LABEL[typ]}
    return None


def find_template(t):
    for key, typ in TEMPLATES:
        if key in t:
            return {'type': typ, 'label': TEMPLATE_LABEL[typ]}
    return None


def find_position(t):
    for key, fx, fy in POSITIONS:
        if key in t:
            return {'fx': fx, 'fy': fy, 'label': key}
    return None


def find_size(t):
    m = _SIZE_PX_RE.search(t) or _SIZE_RADIUS_RE.search(t)
    if m:
        return {'size': min(400, max(6, cn2num(m.group(1)))), 'label': ''}
    for key, size in SIZE_WORDS:
        if key in t:
            return {'size': size, 'label': key + '的'}
    return None
