"""归一化与分句：标点统一 → 谐音矫正 → 礼貌语剥离 → 按连接词切分。"""
import re

from .lexicon import FILLER_HEAD, FILLER_TAIL, HOMOPHONES

_PUNCT_RE = re.compile(r'[。！？!?.;；]')
_SPACE_RE = re.compile(r'\s+')
_FW_DIGIT = {ord(c): ord(c) - 0xFEE0 for c in '０１２３４５６７８９'}
# 「再」作连接词时后面跟一个动作/目标/排列词才切分（避免切坏「再次」等词，
# 且不切「并排」中的「并」）。字符集覆盖绘制/编辑/排列/层级/画布各类动作首字。
_SPLIT_RE = re.compile(
    r'然后|接着|之后|接下来|，|,|'
    r'再(?=画|绘|加|来|写|添|删|清|撤|重|放|缩|变|移|挪|旋|转|选|换|改|涂|填|保|存|导|下|'
    r'置|镜|翻|复|拷|对|全|把|让|给|水|垂|左|右|顶|底|居|上|网|背|透|描|生成|创建)')

MAX_CLAUSES = 6


def normalize(raw):
    t = raw.strip().translate(_FW_DIGIT)
    t = _PUNCT_RE.sub('，', t)
    t = _SPACE_RE.sub('', t)
    for pattern, repl in HOMOPHONES:
        t = pattern.sub(repl, t)
    t = FILLER_HEAD.sub('', t)
    t = FILLER_TAIL.sub('', t)
    return t


def split_clauses(t):
    clauses = []
    for c in _SPLIT_RE.split(t):
        c = FILLER_TAIL.sub('', FILLER_HEAD.sub('', c.strip()))
        if c:
            clauses.append(c)
    return clauses[:MAX_CLAUSES]
