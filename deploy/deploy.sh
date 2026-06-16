#!/usr/bin/env bash
# 一键部署到云服务器：rsync 代码 → venv(清华源) → TLS 证书 → systemd
# 用法：bash deploy/deploy.sh
set -euo pipefail

SERVER="${VOICEDRAW_SERVER:-root@117.50.181.92}"
REMOTE_DIR="/opt/voicedraw"
PORT=8443
DOMAIN="${VOICEDRAW_DOMAIN:-voicedraw.duckdns.org}"  # Let's Encrypt 证书绑定的域名
PUBLIC_IP="$(echo "$SERVER" | sed 's/.*@//')"
PYPI="https://pypi.tuna.tsinghua.edu.cn/simple"  # CentOS7 在国内，走清华镜像
HERE="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> [1/6] 同步代码到 ${SERVER}:${REMOTE_DIR}"
ssh "$SERVER" "mkdir -p ${REMOTE_DIR}"
rsync -az --delete \
  --exclude venv --exclude __pycache__ --exclude '*.db' \
  --exclude certs --exclude .git --exclude .pytest_cache \
  --exclude data --exclude .env \
  "$HERE"/ "$SERVER":"$REMOTE_DIR"/

echo "==> [2/6] 创建 venv 并安装依赖（清华源，urllib3 兼容老 OpenSSL）"
ssh "$SERVER" "cd ${REMOTE_DIR} && \
  (python3.8 -m venv venv || python3 -m venv venv) && \
  ./venv/bin/pip install -q --upgrade pip -i ${PYPI} && \
  ./venv/bin/pip install -q -r requirements.txt -i ${PYPI}"

# 已有证书则保留（生产用 acme.sh 签的 Let's Encrypt 证书；rsync 已排除 certs/ 不覆盖）。
# 仅在全新机器、尚无任何证书时，生成自签名占位以保证 https 能起来。
echo "==> [3/6] TLS 证书（已有则保留，首次无证书才生成自签名占位）"
ssh "$SERVER" "cd ${REMOTE_DIR} && mkdir -p certs && \
  if [ ! -f certs/cert.pem ]; then \
    openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
      -keyout certs/key.pem -out certs/cert.pem \
      -subj '/CN=${PUBLIC_IP}' \
      -addext 'subjectAltName=IP:${PUBLIC_IP}' 2>/dev/null || \
    openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
      -keyout certs/key.pem -out certs/cert.pem -subj '/CN=${PUBLIC_IP}'; \
    echo '已生成自签名占位证书'; else echo '证书已存在，跳过（保留 Let'\''s Encrypt 证书）'; fi"

echo "==> [4/6] 安装 systemd 服务"
ssh "$SERVER" "cp ${REMOTE_DIR}/deploy/voicedraw.service /etc/systemd/system/ && \
  systemctl daemon-reload && systemctl enable voicedraw >/dev/null 2>&1"

echo "==> [5/6] 重启服务"
ssh "$SERVER" "systemctl restart voicedraw && sleep 2 && systemctl is-active voicedraw"

echo "==> [6/6] 健康检查"
ssh "$SERVER" "curl -sk https://127.0.0.1:${PORT}/api/healthz && echo"

echo ""
echo "✅ 部署完成：https://${DOMAIN}:${PORT}/  （Let's Encrypt 证书，绿锁无警告）"
echo "   证书由 acme.sh 走 DNS-01(DuckDNS) 自动续期；rsync 已排除 certs/，部署不会覆盖。"
echo "   注意：用域名访问才是受信任证书；用 IP(https://${PUBLIC_IP}:${PORT}/) 访问会因名称不符报警告。"
echo "   若外网打不开，请在云服务器安全组放行 TCP ${PORT}"
