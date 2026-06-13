# 声笔 VoiceDraw

纯语音控制的绘图工具（前后端分离版）。不用鼠标、不用键盘，说出指令即可创作。

**线上**：https://117.50.181.92:8443/ （自签名证书，首次访问点「高级 → 继续前往」；用 Chrome/Edge 并允许麦克风）

- **前端**：原生 HTML/CSS/JS（Linear 设计系统）。浏览器负责麦克风采集、Web Speech API 语音识别、Canvas 渲染、TTS 播报。
- **后端**：Python FastAPI。负责中文指令 NLU 解析（词典 + 规则，零外部依赖）、场景状态管理、撤销/重做、SQLite 持久化与指令审计日志。
- **部署**：CentOS 7 + systemd + 自签名 TLS（Web Speech API 要求 https 安全上下文）。

## 快速开始（本地）

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
# 打开 http://127.0.0.1:8000 ，点击「开始语音创作」并允许麦克风
```

## 运行测试

```bash
pip install -r requirements-dev.txt
pytest
```

## 部署

```bash
bash deploy/deploy.sh   # rsync 到服务器 + venv(清华源) + 自签名证书 + systemd
```

部署目标 CentOS 7 / Python 3.8 / 2GB。uvicorn 内置 TLS（Web Speech API 要求 https），
存储自动回退到 JSON 文件后端（服务器 Python 缺 `_sqlite3` 扩展）。
若外网打不开，在云服务器安全组放行 TCP 8443。

## 提交记录

按里程碑分阶段提交，每阶段测试通过后 push：

```
feat(frontend): 重做为专业创作工具 UI（图层面板 + 属性检查器 + 画布工具栏）
feat(nlu):      大幅扩展指令能力 — 新图形/复合模板/高级编辑
fix(store):     可插拔持久化后端，兼容缺少 _sqlite3 的服务器 Python
feat(frontend): 瘦客户端对接后端 API + 会话持久化
feat(api):      FastAPI 后端 — 会话管理/指令执行/SQLite 持久化/审计日志
feat(nlu):      中文指令 NLU 引擎 + pytest
chore:          项目脚手架
```

## 启用 AI 文生图

说「生成一张星空下的城堡的图片」即调用大模型出图，图片作为可编辑对象进画布。
默认智谱 CogView；**未配置 Key 时回退占位图**，流程照常跑通。配置真实 Key：

```bash
ssh root@117.50.181.92
echo 'VOICEDRAW_IMAGE_API_KEY=你的智谱key' > /opt/voicedraw/.env
systemctl restart voicedraw    # 重启即启用真实生成，无需改代码
```

`.env` 不进 git、不被部署覆盖。换服务商改 `VOICEDRAW_IMAGE_PROVIDER`/`VOICEDRAW_IMAGE_MODEL`。

## 能力概览（v2）

20 种图形（圆/方/三角/五角星/六边形/五边形/菱形/心形/圆环/月亮/云朵/闪电/十字/对话气泡/椭圆/长方/直线/竖线/箭头/文字）·
6 套复合模板（笑脸/房子/太阳/树/花/雪人）·
编辑变换（改色/移动/缩放/旋转/透明度/翻转/描边粗细/复制/空心实心）·
排列层级（左右上下居中对齐/水平垂直均匀分布/置顶置底/上移下移一层）·
画布（背景/网格/缩放/撤销重做/导出 PNG）。共 30 个意图，72 个 pytest。

详细架构、指令能力清单与未完成项说明见 [DESIGN.md](DESIGN.md)。
