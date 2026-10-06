#!/usr/bin/env bash
#
# One-shot deployment script -- installs the calculator back end on a fresh Linux server.
#
# Usage (run on the server, requires sudo):
#
#     chmod +x deploy.sh
#     ./deploy.sh
#
# Or specify the port:
#
#     PORT=8000 ./deploy.sh
#
# ------------------------------------------------------------------
# What this script does
# ------------------------------------------------------------------
#
#   1. Check the Python version (3.10+ required, the project uses X | None type annotations)
#   2. Copy the back-end code to /opt/calculator-backend
#   3. Create a dedicated system user (the service does not run as root)
#   4. Register as a systemd service -- key points: start on boot + restart on crash
#   5. Open the firewall port
#   6. Start the service and run a health check
#
# ------------------------------------------------------------------
# Why systemd instead of nohup / screen
# ------------------------------------------------------------------
#
#   The assignment requires that the back-end service stay reachable during the grading period.
#   With nohup or screen, one server reboot (cloud providers do maintenance reboots)
#   takes the service down, and the TA may visit at any moment -- they see "service unavailable".
#
#   Two systemd settings handle this:
#     Restart=always      brings the process back up if it crashes
#     WantedBy=multi-user  starts automatically on boot
#
# ------------------------------------------------------------------
# Why not Docker
# ------------------------------------------------------------------
#
#   The project has zero third-party dependencies (standard library only), so no image is needed to isolate the environment.
#   Running Python directly means fewer layers, easier debugging, and no Docker install on the server.

set -euo pipefail

# ---------------------------------------------------------------- Configuration
PORT="${PORT:-8000}"
APP_DIR="/opt/calculator-backend"
APP_USER="calcapp"
SERVICE_NAME="calculator-backend"
DATA_DIR="/var/lib/calculator-backend"

# The front-end repository and where it is kept on this machine.
#
# Why the back-end deployment also pulls the front end:
#   The latest requirement from the instructor is to attach a directly reachable project website link.
#   With the front end on GitHub Pages and the back end on the server, the TA opens two addresses,
#   and front-end calls to the back end are **cross-origin** requests (one more layer that can break).
#
#   Serving the front-end pages from the back end as well means:
#     - only one link: http://<server-IP>:8000/   <- opens straight into the calculator
#     - pages and API are **same-origin**, no cross-origin problem
#     - no dependency on whether GitHub Pages is reachable for the TA
FRONTEND_REPO="${FRONTEND_REPO:-https://github.com/qihangpeng580-ui/832401217_calculator_frontend.git}"
FRONTEND_DIR="/opt/calculator-frontend"

# Directory of this script (where the back-end code lives)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Output colors (no error when the terminal does not support them)
info()  { printf '\033[36m[info]\033[0m %s\n' "$*"; }
ok()    { printf '\033[32m[ok]\033[0m %s\n' "$*"; }
warn()  { printf '\033[33m[warn]\033[0m %s\n' "$*"; }
error() { printf '\033[31m[error]\033[0m %s\n' "$*" >&2; }

echo "=============================================================="
echo "  Front-end/back-end split calculator -- back-end deployment script"
echo "=============================================================="
echo

# ---------------------------------------------------------------- 0. Preflight checks
if [[ "$(id -u)" -ne 0 ]]; then
  error "Run with sudo: sudo ./deploy.sh"
  exit 1
fi

if [[ ! -f "$SCRIPT_DIR/run.py" ]]; then
  error "run.py not found in the current directory. Put the deployment script in the back-end code root directory and run it again."
  error "Current directory: $SCRIPT_DIR"
  exit 1
fi

info "Checking the Python version ..."
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
  error "Python 3.10 or newer not found."
  echo
  echo "Install it first. Commands for common systems:"
  echo "  Ubuntu/Debian : sudo apt update && sudo apt install -y python3"
  echo "  CentOS/RHEL   : sudo yum install -y python3"
  echo "  (the project uses X | None type annotations, so 3.10+ is required)"
  exit 1
fi
ok "Using $PYTHON_BIN (version $("$PYTHON_BIN" -V 2>&1))"

# ---------------------------------------------------------------- 1. Copy the code
info "Copying the code to $APP_DIR ..."
mkdir -p "$APP_DIR"
# rsync is better, but some minimal systems lack it, so fall back to cp
if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete \
    --exclude '.git' --exclude '__pycache__' --exclude 'data' --exclude '.venv' \
    "$SCRIPT_DIR"/ "$APP_DIR"/
else
  rm -rf "${APP_DIR:?}"/*
  cp -r "$SCRIPT_DIR"/. "$APP_DIR"/
  rm -rf "$APP_DIR/.git" "$APP_DIR/__pycache__" "$APP_DIR/data"
fi
# Clean up bytecode that may have come along (meaningless on another machine, and the version may not match)
find "$APP_DIR" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
ok "Code in place"

# ---------------------------------------------------------------- 2. Dedicated user
if id "$APP_USER" >/dev/null 2>&1; then
  info "System user $APP_USER already exists, skipping creation"
else
  info "Creating dedicated system user $APP_USER ..."
  # --system: system user, no home directory, cannot log in
  # Why the service does not run as root: if the service is compromised, the attacker gets far fewer privileges
  useradd --system --no-create-home --shell /usr/sbin/nologin "$APP_USER" 2>/dev/null \
    || useradd --system --no-create-home --shell /sbin/nologin "$APP_USER"
  ok "User created"
fi

# Data directory (the database file goes here, separate from the code -- code updates do not touch the data)
mkdir -p "$DATA_DIR"
chown -R "$APP_USER:$APP_USER" "$DATA_DIR"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"
ok "Data directory: $DATA_DIR"

# ---------------------------------------------------------------- 3. Create the database
info "Initializing the database ..."
# Create the database as the service user so file ownership is correct (otherwise the service may not have write permission)
sudo -u "$APP_USER" "$PYTHON_BIN" "$APP_DIR/init_db.py" --db "$DATA_DIR/calculator.db" >/dev/null
ok "Database initialized"

# ---------------------------------------------------------------- 3.5 Front-end pages
#
# Pull the front-end pages as well and host them from the back end -- the instructor/TA then needs only one link.
#
# The key step is setting the front-end API address to an **empty string** (same origin).
# Two files must be changed:
#   - config.js  -- the configuration source file (meant for humans)
#   - bundle.js  -- the file the page actually loads, the config is inlined at build time
# Changing only config.js does nothing; this caused a problem in the front-end project.
FRONTEND_OK=0
info "Fetching the front-end pages ..."
if ! command -v git >/dev/null 2>&1; then
  warn "No git on the server, skipping front-end page hosting."
  warn "Install it and rerun this script: apt install -y git"
elif [[ -d "$FRONTEND_DIR/.git" ]]; then
  info "Front-end directory exists, pulling the latest version ..."
  if git -C "$FRONTEND_DIR" pull --ff-only >/dev/null 2>&1; then
    FRONTEND_OK=1
  else
    warn "git pull failed (possibly local modifications), trying a fresh clone ..."
    rm -rf "$FRONTEND_DIR"
    git clone --depth 1 "$FRONTEND_REPO" "$FRONTEND_DIR" >/dev/null 2>&1 && FRONTEND_OK=1
  fi
else
  if git clone --depth 1 "$FRONTEND_REPO" "$FRONTEND_DIR" >/dev/null 2>&1; then
    FRONTEND_OK=1
  else
    warn "Cloning the front-end repository failed (network problem?), not hosting front-end pages this run."
  fi
fi

if [[ "$FRONTEND_OK" -eq 1 ]]; then
  # The front-end pages live under src/ in the repository, and that becomes the server root
  SERVE_DIR="$FRONTEND_DIR/src"

  if [[ -f "$SERVE_DIR/js/config.js" ]]; then
    # Switch to same origin: requests go to /api/... on the current page, no cross-origin needed
    sed -i "s|export const API_BASE_URL = '[^']*';|export const API_BASE_URL = '';|" \
      "$SERVE_DIR/js/config.js"
    sed -i "s|API_BASE_URL = '[^']*'|API_BASE_URL = ''|g" \
      "$SERVE_DIR/js/bundle.js"
    ok "Front-end pages in place (switched to same-origin calls): $SERVE_DIR"
  else
    warn "js/config.js not found in the front-end pages, not hosting the front end this run."
    FRONTEND_OK=0
  fi
fi

# ---------------------------------------------------------------- 4. systemd service
info "Registering the systemd service ..."

# If the front end is available, add --frontend-dir so one port serves both the pages and the API
FRONTEND_ARG=""
if [[ "$FRONTEND_OK" -eq 1 ]]; then
  FRONTEND_ARG="--frontend-dir ${FRONTEND_DIR}/src"
fi

cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=Front-end/back-end split calculator - back-end service (also hosts the front-end pages)
Documentation=file://${APP_DIR}/README.md
After=network.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
# Bind 0.0.0.0 to be reachable from outside (binding only 127.0.0.1 blocks outside access)
# --frontend-dir: serve the front-end pages from the same port, so the TA needs only one link
ExecStart=${PYTHON_BIN} ${APP_DIR}/run.py --host 0.0.0.0 --port ${PORT} --db ${DATA_DIR}/calculator.db ${FRONTEND_ARG}

# Restart automatically after a crash -- the service must stay alive through the grading period
Restart=always
RestartSec=3

# Logs go to journald, view them with journalctl -u ${SERVICE_NAME}
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SERVICE_NAME}

# A little basic hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
# Needs read access to the front-end directory (read-only is enough) and write access to the data directory
ReadWritePaths=${DATA_DIR}

[Install]
# Start on boot
WantedBy=multi-user.target
EOF

# The service user must be able to read the front-end directory
if [[ "$FRONTEND_OK" -eq 1 ]]; then
  chmod -R a+rX "$FRONTEND_DIR"
fi

systemctl daemon-reload
systemctl enable "$SERVICE_NAME" >/dev/null 2>&1
ok "Service registered and enabled at boot"

# ---------------------------------------------------------------- 5. Firewall
info "Checking the firewall ..."
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
  ufw allow "${PORT}/tcp" >/dev/null 2>&1 && ok "ufw allowed ${PORT}/tcp" || warn "ufw rule failed, check it manually"
elif command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld; then
  firewall-cmd --permanent --add-port="${PORT}/tcp" >/dev/null 2>&1
  firewall-cmd --reload >/dev/null 2>&1 && ok "firewalld allowed ${PORT}/tcp" || warn "firewalld rule failed"
else
  info "No active local firewall detected (cloud servers also need a security group rule, see below)"
fi

# ---------------------------------------------------------------- 6. Start and verify
info "Starting the service ..."
systemctl restart "$SERVICE_NAME"
sleep 2

if systemctl is-active --quiet "$SERVICE_NAME"; then
  ok "Service started"
else
  error "Service failed to start. Recent logs:"
  journalctl -u "$SERVICE_NAME" -n 30 --no-pager || true
  exit 1
fi

info "Health check ..."
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
  ok "Health check passed"
  echo
  echo "Local health check returned:"
  curl -fsS "http://127.0.0.1:${PORT}/api/health" || true
  echo
else
  warn "Health check failed. Check the logs: journalctl -u ${SERVICE_NAME} -n 50"
fi

# ---------------------------------------------------------------- Closing notes
# Fetch the public IP (try several sources in order; if all fail, the user checks the console)
PUBLIC_IP=""
for url in "https://api.ipify.org" "https://ifconfig.me/ip" "https://ipinfo.io/ip"; do
  PUBLIC_IP="$(curl -fsS --max-time 5 "$url" 2>/dev/null || true)"
  [[ -n "$PUBLIC_IP" ]] && break
done

echo "=============================================================="
echo "  Deployment complete"
echo "=============================================================="
echo
BASE_URL="http://${PUBLIC_IP:-<your-server-public-ip>}:${PORT}"

if [[ "$FRONTEND_OK" -eq 1 ]]; then
  echo "  Project website (the instructor/TA opens this):"
  echo "      ${BASE_URL}/"
  echo "      opens straight into the calculator, press = to compute -- pages and API on one address."
else
  echo "  Back-end address: ${BASE_URL}"
  echo "  (front-end pages were not hosted this run; install git and rerun this script for a single link)"
fi
echo
echo "  Health check: ${BASE_URL}/api/health"
echo
echo "  One step left: allow port ${PORT} in the security group of the **cloud provider console**"
echo "     (the local firewall already allows it, but a cloud server has a security group in front,"
echo "      and without a rule there nothing outside can reach it -- the most common cause of a deployment that will not open)"
echo
echo "  Common commands:"
echo "    systemctl status  ${SERVICE_NAME}     check status"
echo "    systemctl restart ${SERVICE_NAME}     restart"
echo "    systemctl stop    ${SERVICE_NAME}     stop"
echo "    journalctl -u ${SERVICE_NAME} -f      follow the logs live"
echo
echo "  How to verify (open these in a browser):"
echo "    ${BASE_URL}/              should show the calculator UI"
echo "    ${BASE_URL}/api/health    should return JSON with status ok"
echo
if [[ "$FRONTEND_OK" -eq 1 ]]; then
  echo "  Next steps:"
  echo "    1. Put the ${BASE_URL}/ link into the CSDN assignment post"
  echo "    2. Add the link to the Deployment and access section of the blog"
  echo "    3. Update the GitHub Pages copy of the front end (optional):"
  echo "       py -3.12 tools\\set_backend_url.py ${BASE_URL} --deploy"
else
  echo "  Next steps:"
  echo "    1. Put ${BASE_URL} into src/js/config.js of the front end (API_BASE_URL) and republish"
  echo "    2. Add the link to the CSDN assignment post and the blog"
fi
echo
