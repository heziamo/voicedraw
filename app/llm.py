"""LLM 兜底理解：规则没听懂时，让大模型把（可能识别错的）口语还原成标准指令。

- 用智谱 GLM 对话模型（默认 glm-4-flash，免费、快）。
- 复用文生图那把智谱 Key（VOICEDRAW_LLM_API_KEY 优先，回退 VOICEDRAW_IMAGE_API_KEY）。
- 仅标准库 urllib，规避服务器老 OpenSSL 上 requests/urllib3 的兼容问题。
- 思路：不让 LLM 直接画，而是把用户原话「翻译/纠正」成本工具能解析的标准指令字符串，
  再交给既有规则引擎执行——既得到 LLM 的鲁棒理解，又复用全部已测过的执行逻辑。
"""
import json
import os
import ssl
import urllib.request
from urllib.error import HTTPError, URLError

PROVIDER = os.environ.get('VOICEDRAW_LLM_PROVIDER', 'zhipu').lower()
API_KEY = (os.environ.get('VOICEDRAW_LLM_API_KEY')
           or os.environ.get('VOICEDRAW_IMAGE_API_KEY') or '').strip()
MODEL = os.environ.get('VOICEDRAW_LLM_MODEL', 'glm-4-flash')
TIMEOUT = int(os.environ.get('VOICEDRAW_LLM_TIMEOUT', '15'))
ZHIPU_URL = 'https://open.bigmodel.cn/api/paas/v4/chat/completions'

SYSTEM_PROMPT = """你是一个纯语音绘图工具的「指令理解器」。用户的话来自语音识别，可能有同音错字、口语化、省略。\
你的唯一任务：把用户这句话改写成本工具能执行的【标准指令】，然后原样输出，不要解释、不要加引号。

可用的标准指令（只能用这些动作和词汇）：
- 绘制：画一个/画N个 [颜色][大小][空心] <图形> [在<位置>] [并排/竖排]
  图形：圆 椭圆 正方形 长方形 三角形 五角星 六边形 五边形 菱形 心形 圆环 月亮 云朵 闪电 十字 对话气泡 直线 竖线 箭头
  颜色：红 橙 黄 绿 青 蓝 紫 粉 黑 白 灰 棕 金 深蓝 天蓝 深绿 等
  大小：大 小 巨大 迷你 / 也可「80像素」
  位置：左上角 右上角 左下角 右下角 中间 上面 下面 左边 右边
- 复合模板：画一个 笑脸 / 房子 / 太阳 / 树 / 花 / 雪人
- 写字：写上<内容>
- AI 文生图：生成一张<描述>的图片
- 改样式：把<目标>变成<颜色>；把<目标>改成空心/实心；把<目标>描边加粗/变细；把<目标>透明度设为N%
- 变换：把<目标>放大/缩小；把<目标>旋转N度；把<目标>水平翻转/垂直翻转；向左/右/上/下移动N像素；把<目标>移到<位置>；复制<目标>；删除<目标>
- 排列：选中<目标>；把它们左对齐/右对齐/顶部对齐/底部对齐/水平居中/垂直居中；水平均匀分布/垂直均匀分布；把<目标>置于顶层/底层/上移一层/下移一层
- 目标<目标>可写：它 / 第N个 / 所有<图形> / 选中的
- 画布：背景换成<颜色>；显示网格/隐藏网格；撤销；重做；清空画布；保存图片；适应窗口
- 系统：帮助；暂停聆听；继续聆听；关闭播报；打开播报
- 多个动作用「然后」连接。

规则：
1. 优先纠正同音错字（如 缘→圆、篮/兰→蓝、园→圆、星形→五角星）。
2. 把口语化说法映射到最接近的标准指令（如「弄大点」→放大，「搞个红色圆球」→画一个红色的圆）。
3. 如果用户明显不是在下绘图/编辑指令（闲聊、无意义词、问候、与画图无关），只输出：NONE
4. 只输出标准指令本身，一行，不要任何多余文字。"""

FEWSHOT = [
    ('画一个红色的缘', '画一个红色的圆'),
    ('花三个篮色的方快', '画三个蓝色的正方形'),
    ('搞个大一点的星星放右上角', '画一个大的五角星在右上角'),
    ('把它弄成蓝色的', '把它变成蓝色'),
    ('那个圆能不能大一点', '把圆放大'),
    ('生成一只戴帽子的猫', '生成一张戴帽子的猫的图片'),
    ('全部排整齐左边对齐', '选中所有图形然后左对齐'),
    ('明天天气怎么样', 'NONE'),
    ('嗯那个', 'NONE'),
]


def available():
    return bool(API_KEY)


def interpret(text, scene_summary=''):
    """把一句可能识别错的话还原为标准指令字符串；非指令返回 'NONE'；失败返回 None。"""
    if not API_KEY or not text:
        return None
    messages = [{'role': 'system', 'content': SYSTEM_PROMPT}]
    for u, a in FEWSHOT:
        messages.append({'role': 'user', 'content': u})
        messages.append({'role': 'assistant', 'content': a})
    ctx = ('（%s）' % scene_summary) if scene_summary else ''
    messages.append({'role': 'user', 'content': ctx + text})
    try:
        if PROVIDER == 'zhipu':
            return _zhipu(messages)
    except (HTTPError, URLError, OSError, KeyError, ValueError, IndexError):
        return None
    return None


def _zhipu(messages):
    body = json.dumps({'model': MODEL, 'messages': messages,
                       'temperature': 0.1, 'max_tokens': 120}).encode('utf-8')
    req = urllib.request.Request(ZHIPU_URL, data=body, method='POST', headers={
        'Authorization': 'Bearer ' + API_KEY, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=ssl.create_default_context()) as r:
        payload = json.loads(r.read().decode('utf-8'))
    out = payload['choices'][0]['message']['content'].strip()
    # 去掉可能的引号/前后缀
    out = out.strip('「」"\'` \n')
    return out
