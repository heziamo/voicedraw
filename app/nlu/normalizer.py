"""归一化与分句：标点统一 → 谐音矫正 → 礼貌语剥离 → 按连接词切分。"""
import re

from .lexicon import FILLER_HEAD, FILLER_TAIL, HOMOPHONES

_PUNCT_RE = re.compile(r'[。！？!?.;；]')
_SPACE_RE = re.compile(r'\s+')
_FW_DIGIT = {ord(c): ord(c) - 0xFEE0 for c in '０１２３４５６７８９'}
_SPLIT_RE = re.compile(
    r'然后|接着|之后|，|,|再(?=画|加|来|写|添|删|清|撤|放|缩|移|旋|选|换|改|保|生成|创建|导出|下载)')

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
