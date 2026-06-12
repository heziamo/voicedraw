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
fix(store):     可插拔持久化后端，兼容缺少 _sqlite3 的服务器 Python
feat(frontend): 瘦客户端对接后端 API + 会话持久化
feat(api):      FastAPI 后端 — 会话管理/指令执行/SQLite 持久化/审计日志
feat(nlu):      中文指令 NLU 引擎 + 32 个 pytest 用例
chore:          项目脚手架
```

详细架构、指令能力清单与未完成项说明见 [DESIGN.md](DESIGN.md)。
