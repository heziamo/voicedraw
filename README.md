# 声笔 VoiceDraw

纯语音控制的绘图工具（前后端分离版）。不用鼠标、不用键盘，说出指令即可创作。

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
bash deploy/deploy.sh   # rsync 到服务器 + venv + 自签名证书 + systemd
```

详细架构与指令能力见 [DESIGN.md](DESIGN.md)。
