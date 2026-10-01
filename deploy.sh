#!/usr/bin/env bash
#
# 一键部署脚本 —— 把计算器后端装到一台全新的 Linux 服务器上。
#
# 用法（在服务器上执行，需要有 sudo 权限）：
#
#     chmod +x deploy.sh
#     ./deploy.sh
#
# 或者指定端口：
#
#     PORT=8000 ./deploy.sh
#
# ------------------------------------------------------------------
# 这个脚本会做什么
# ------------------------------------------------------------------
#
#   1. 检查 Python 版本（需要 3.10+，本项目用了 X | None 的类型标注写法）
#   2. 把后端代码复制到 /opt/calculator-backend
#   3. 创建一个专用系统用户（不让服务以 root 身份跑）
#   4. 注册为 systemd 服务 —— ★ 关键：开机自启 + 崩溃自动重启
#   5. 开放防火墙端口
#   6. 启动服务并做健康检查
#
# ------------------------------------------------------------------
# 为什么必须用 systemd 而不是 nohup / screen
# ------------------------------------------------------------------
#
#   作业要求「后端服务应在评测期内保持可访问」。
#   如果用 nohup 或 screen 启动，服务器一重启（云厂商偶尔会维护重启）
#   服务就没了，而助教随时可能来访问 —— 那就直接看到"服务不可用"。
#
#   systemd 的两个配置解决这件事：
#     Restart=always      进程崩了自动拉起来
#     WantedBy=multi-user  开机自动启动
#
# ------------------------------------------------------------------
# 为什么不用 Docker
# ------------------------------------------------------------------
#
#   本项目零第三方依赖（纯标准库），不需要镜像来隔离环境。
#   直接跑 Python 更少的层、更好排查，也省得服务器上再装 Docker。

set -euo pipefail

# ---------------------------------------------------------------- 配置
PORT="${PORT:-8000}"
APP_DIR="/opt/calculator-backend"
APP_USER="calcapp"
SERVICE_NAME="calculator-backend"
DATA_DIR="/var/lib/calculator-backend"

# 脚本所在目录（也就是后端代码所在的位置）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 输出用的颜色（终端不支持时也不报错）
info()  { printf '\033[36m[信息]\033[0m %s\n' "$*"; }
ok()    { printf '\033[32m[成功]\033[0m %s\n' "$*"; }
warn()  { printf '\033[33m[警告]\033[0m %s\n' "$*"; }
error() { printf '\033[31m[错误]\033[0m %s\n' "$*" >&2; }

echo "=============================================================="
echo "  前后端分离计算器 —— 后端部署脚本"
echo "=============================================================="
echo

# ---------------------------------------------------------------- 0. 前置检查
if [[ "$(id -u)" -ne 0 ]]; then
  error "请用 sudo 运行：sudo ./deploy.sh"
  exit 1
fi

if [[ ! -f "$SCRIPT_DIR/run.py" ]]; then
  error "在当前目录找不到 run.py。请把部署脚本放在后端代码根目录下再运行。"
  error "当前目录：$SCRIPT_DIR"
  exit 1
fi

info "检查 Python 版本 ..."
PYTHON_BIN=""
for candidate in python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    version="$("$candidate" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
    major="${version%%.*}"
    minor="${version##*.}"
    if [[ "$major" -eq 3 && "$minor" -ge 10 ]]; then
      PYTHON_BIN="$candidate"
      break
    fi
  fi
done

if [[ -z "$PYTHON_BIN" ]]; then
  error "找不到 Python 3.10 或更高版本。"
  echo
  echo "请先安装。常见系统的命令："
  echo "  Ubuntu/Debian : sudo apt update && sudo apt install -y python3"
  echo "  CentOS/RHEL   : sudo yum install -y python3"
  echo "  （项目用到 X | None 的类型标注，需要 3.10+）"
  exit 1
fi
ok "使用 $PYTHON_BIN（版本 $("$PYTHON_BIN" -V 2>&1)）"

# ---------------------------------------------------------------- 1. 复制代码
info "复制代码到 $APP_DIR ..."
mkdir -p "$APP_DIR"
# 用 rsync 更好，但有些精简系统没装，所以退回 cp
if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete \
    --exclude '.git' --exclude '__pycache__' --exclude 'data' --exclude '.venv' \
    "$SCRIPT_DIR"/ "$APP_DIR"/
else
  rm -rf "${APP_DIR:?}"/*
  cp -r "$SCRIPT_DIR"/. "$APP_DIR"/
  rm -rf "$APP_DIR/.git" "$APP_DIR/__pycache__" "$APP_DIR/data"
fi
# 清理可能带过来的字节码（换机器后没意义，反而可能版本不匹配）
find "$APP_DIR" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
ok "代码已就位"

# ---------------------------------------------------------------- 2. 专用用户
if id "$APP_USER" >/dev/null 2>&1; then
  info "系统用户 $APP_USER 已存在，跳过创建"
else
  info "创建专用系统用户 $APP_USER ..."
  # --system：系统用户，不创建家目录、不能登录
  # 为什么不让服务以 root 跑：万一服务被攻破，攻击者拿到的权限会小很多
  useradd --system --no-create-home --shell /usr/sbin/nologin "$APP_USER" 2>/dev/null \
    || useradd --system --no-create-home --shell /sbin/nologin "$APP_USER"
  ok "用户已创建"
fi

# 数据目录（数据库文件放这里，和代码分开 —— 更新代码时不会动到数据）
mkdir -p "$DATA_DIR"
chown -R "$APP_USER:$APP_USER" "$DATA_DIR"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"
ok "数据目录：$DATA_DIR"

# ---------------------------------------------------------------- 3. 建库
info "初始化数据库 ..."
# 用服务用户身份建库，保证文件属主正确（否则服务可能没权限写）
sudo -u "$APP_USER" "$PYTHON_BIN" "$APP_DIR/init_db.py" --db "$DATA_DIR/calculator.db" >/dev/null
ok "数据库已初始化"

# ---------------------------------------------------------------- 4. systemd 服务
info "注册 systemd 服务 ..."
cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=前后端分离计算器 - 后端服务
Documentation=file://${APP_DIR}/README.md
After=network.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
# 绑定 0.0.0.0 才能被外部访问（只绑 127.0.0.1 的话外面连不上）
ExecStart=${PYTHON_BIN} ${APP_DIR}/run.py --host 0.0.0.0 --port ${PORT} --db ${DATA_DIR}/calculator.db

# ★ 崩溃后自动重启 —— 评测期内服务必须一直活着
Restart=always
RestartSec=3

# 日志进 journald，用 journalctl -u ${SERVICE_NAME} 查看
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SERVICE_NAME}

# 一点基本的加固：只允许写数据目录和临时目录
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=${DATA_DIR}

[Install]
# ★ 开机自启
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME" >/dev/null 2>&1
ok "服务已注册并设为开机自启"

# ---------------------------------------------------------------- 5. 防火墙
info "检查防火墙 ..."
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
  ufw allow "${PORT}/tcp" >/dev/null 2>&1 && ok "ufw 已放行 ${PORT}/tcp" || warn "ufw 放行失败，请手动检查"
elif command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld; then
  firewall-cmd --permanent --add-port="${PORT}/tcp" >/dev/null 2>&1
  firewall-cmd --reload >/dev/null 2>&1 && ok "firewalld 已放行 ${PORT}/tcp" || warn "firewalld 放行失败"
else
  info "没有检测到启用的本机防火墙（云服务器还要另配安全组，见下方提示）"
fi

# ---------------------------------------------------------------- 6. 启动并检查
info "启动服务 ..."
systemctl restart "$SERVICE_NAME"
sleep 2

if systemctl is-active --quiet "$SERVICE_NAME"; then
  ok "服务已启动"
else
  error "服务启动失败。最近的日志："
  journalctl -u "$SERVICE_NAME" -n 30 --no-pager || true
  exit 1
fi

info "健康检查 ..."
HEALTH_OK=0
for _ in $(seq 1 15); do
  if curl -fsS "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
    HEALTH_OK=1
    break
  fi
  sleep 1
done

echo
if [[ "$HEALTH_OK" -eq 1 ]]; then
  ok "健康检查通过"
  echo
  echo "本地健康检查返回："
  curl -fsS "http://127.0.0.1:${PORT}/api/health" || true
  echo
else
  warn "健康检查没通过。请查看日志：journalctl -u ${SERVICE_NAME} -n 50"
fi

# ---------------------------------------------------------------- 收尾提示
# 取公网 IP（几个来源依次试，都不通就让用户自己看控制台）
PUBLIC_IP=""
for url in "https://api.ipify.org" "https://ifconfig.me/ip" "https://ipinfo.io/ip"; do
  PUBLIC_IP="$(curl -fsS --max-time 5 "$url" 2>/dev/null || true)"
  [[ -n "$PUBLIC_IP" ]] && break
done

echo "=============================================================="
echo "  部署完成"
echo "=============================================================="
echo
if [[ -n "$PUBLIC_IP" ]]; then
  echo "  后端地址（本机看到的公网 IP）：http://${PUBLIC_IP}:${PORT}"
else
  echo "  后端地址：http://<你的服务器公网IP>:${PORT}"
fi
echo "  健康检查：/api/health"
echo
echo "  ⚠️ 还差一步：到**云厂商控制台**的安全组里放行 ${PORT} 端口"
echo "     （本机防火墙已经放行了，但云服务器外面还有一层安全组，
echo "       不放行的话外面访问不到 —— 这是最常见的\"部署好了但打不开\"的原因）"
echo
echo "  常用命令："
echo "    systemctl status  ${SERVICE_NAME}     查看状态"
echo "    systemctl restart ${SERVICE_NAME}     重启"
echo "    systemctl stop    ${SERVICE_NAME}     停止"
echo "    journalctl -u ${SERVICE_NAME} -f      实时看日志"
echo
echo "  验证方法（在你自己电脑上执行）："
echo "    curl http://${PUBLIC_IP:-<公网IP>}:${PORT}/api/health"
echo
echo "  接下来要做的："
echo "    1. 把上面的地址填进前端的 src/js/config.js（API_BASE_URL）"
echo "    2. 重新打包并发布前端：node tools/build-bundle.mjs && py -3.12 tools/deploy_pages.py"
echo "    3. 把地址写进博客的「部署与访问方式」一节"
echo
