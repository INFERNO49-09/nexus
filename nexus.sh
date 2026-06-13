#!/usr/bin/env bash
# ===================================================================
#  Nexus - Local LLM Interface
#  One-command installer and launcher
# ===================================================================
set -e

NEXUS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$NEXUS_DIR/.venv"
ENV_FILE="$NEXUS_DIR/.env"
PID_FILE="$NEXUS_DIR/.nexus.pid"
FRONTEND_PID_FILE="$NEXUS_DIR/.nexus-frontend.pid"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; RESET='\033[0m'

banner(){
  echo -e "${BLUE}${BOLD}"
  echo "  ###+   ##+######+##+  ##+##+   ##+######+"
  echo "  ###+  ##|##+====++##+##++##|   ##|##+====+"
  echo "  ##+##+ ##|#####+   +###++ ##|   ##|######+"
  echo "  ##|+##+##|##+==+   ##+##+ ##|   ##|+====##|"
  echo "  ##| +###|######+##++ ##++######++######|"
  echo "  +=+  +===++======++=+  +=+ +=====+ +======+"
  echo -e "${RESET}  Local LLM Interface - v1.0.0"
  echo ""
}

info()    { echo -e "${GREEN}[[OK]]${RESET} $1"; }
warn()    { echo -e "${YELLOW}[!]${RESET} $1"; }
error()   { echo -e "${RED}[[FAIL]]${RESET} $1"; exit 1; }
section() { echo -e "\n${BOLD}-- $1 --${RESET}"; }

# -- Commands ------------------------------------------------------------------
cmd_install(){
  banner
  section "Checking requirements"

  command -v python3 >/dev/null 2>&1 || error "Python 3.10+ required. Install: sudo apt install python3 python3-pip"
  PYVER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
  info "Python $PYVER"

  command -v npm >/dev/null 2>&1 || error "npm required for the Vite frontend. Install Node.js/npm first."
  info "npm found: $(npm --version)"

  command -v ollama >/dev/null 2>&1 || {
    warn "Ollama not found. Installing..."
    curl -fsSL https://ollama.com/install.sh | sh
  }
  info "Ollama found: $(ollama --version 2>/dev/null | head -1)"

  section "Creating virtual environment"
  if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    info "Created .venv"
  else
    info ".venv already exists"
  fi

  section "Installing Python dependencies"
  "$VENV_DIR/bin/pip" install --upgrade pip -q
  "$VENV_DIR/bin/pip" install -r "$NEXUS_DIR/requirements.txt" -q
  info "All dependencies installed"

  section "Installing frontend dependencies"
  cd "$NEXUS_DIR"
  npm install
  info "Frontend dependencies installed"

  section "Configuration"
  if [ ! -f "$ENV_FILE" ]; then
    cp "$NEXUS_DIR/.env.example" "$ENV_FILE"
    info "Created .env from template"
    warn "Edit $ENV_FILE to customize (BRAVE_API_KEY, SEARX_URL, etc.)"
  else
    info ".env already exists"
  fi

  section "Ollama model"
  if ! ollama list 2>/dev/null | grep -q "mistral"; then
    warn "Mistral not found. Downloading (4.1GB)..."
    ollama pull mistral
  fi
  info "Model ready"

  section "Building frontend"
  cd "$NEXUS_DIR"
  npm run build
  info "Frontend build ready"

  echo ""
  echo -e "${GREEN}${BOLD}Installation complete!${RESET}"
  echo ""
  echo -e "  Start Nexus:   ${BOLD}./nexus.sh start${RESET}"
  echo -e "  Open browser:  ${BOLD}http://localhost:8000${RESET}"
  echo ""
}

cmd_start(){
  banner
  section "Starting Nexus"

  # Check if already running
  if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    warn "Nexus is already running (PID $(cat "$PID_FILE"))"
    echo -e "  Open: ${BOLD}http://localhost:8000${RESET}"
    return
  fi

  # Check venv
  [ -d "$VENV_DIR" ] || error "Not installed. Run: ./nexus.sh install"

  command -v npm >/dev/null 2>&1 || error "npm required for the Vite frontend. Install Node.js/npm first."
  [ -d "$NEXUS_DIR/node_modules" ] || error "Frontend dependencies missing. Run: ./nexus.sh install"

  # Start Ollama if not running
  if ! pgrep -x ollama >/dev/null 2>&1; then
    info "Starting Ollama..."
    ollama serve > "$NEXUS_DIR/logs/ollama.log" 2>&1 &
    sleep 2
  fi
  info "Ollama running"

  # Create logs dir
  mkdir -p "$NEXUS_DIR/logs"

  # Build frontend
  info "Building frontend..."
  cd "$NEXUS_DIR"
  npm run build > "$NEXUS_DIR/logs/frontend-build.log" 2>&1
  info "Frontend built"

  # Start backend
  info "Starting backend on :8000..."
  cd "$NEXUS_DIR/backend"
  "$VENV_DIR/bin/python" -m uvicorn main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 1 \
    --log-level info \
    > "$NEXUS_DIR/logs/nexus.log" 2>&1 &
  echo $! > "$PID_FILE"
  sleep 2

  # Verify it started
  if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    info "Nexus running (PID $(cat "$PID_FILE"))"
    echo ""
    echo -e "${GREEN}${BOLD}Nexus is ready!${RESET}"
    echo -e "  UI:      ${BOLD}http://localhost:8000${RESET}"
    echo -e "  API:     ${BOLD}http://localhost:8000/docs${RESET}"
    echo -e "  Logs:    ${BOLD}./logs/nexus.log${RESET}"
    echo ""
    # Try to open browser
    xdg-open http://localhost:8000 2>/dev/null &
    disown
  else
    error "Failed to start. Check logs: cat $NEXUS_DIR/logs/nexus.log"
  fi
}

cmd_stop(){
  section "Stopping Nexus"
  if [ -f "$FRONTEND_PID_FILE" ]; then
    FRONTEND_PID=$(cat "$FRONTEND_PID_FILE")
    if kill -0 "$FRONTEND_PID" 2>/dev/null; then
      kill "$FRONTEND_PID"
      info "Frontend dev server stopped (PID $FRONTEND_PID)"
    fi
    rm -f "$FRONTEND_PID_FILE"
  fi

  if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
      kill "$PID"
      rm -f "$PID_FILE"
      info "Nexus stopped (PID $PID)"
    else
      warn "Process $PID not running"
      rm -f "$PID_FILE"
    fi
  else
    warn "No PID file found"
  fi
}

cmd_restart(){
  cmd_stop
  sleep 1
  cmd_start
}

cmd_logs(){
  tail -f "$NEXUS_DIR/logs/nexus.log" 2>/dev/null || echo "No logs yet"
}

cmd_status(){
  banner
  echo -e "${BOLD}Service Status${RESET}"
  echo ""
  if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo -e "  Nexus:   ${GREEN}* Running${RESET} (PID $(cat "$PID_FILE"))"
  else
    echo -e "  Nexus:   ${RED}* Stopped${RESET}"
  fi
  if pgrep -x ollama >/dev/null 2>&1; then
    echo -e "  Ollama:  ${GREEN}* Running${RESET}"
  else
    echo -e "  Ollama:  ${RED}* Stopped${RESET}"
  fi
  echo ""
  echo -e "${BOLD}Models${RESET}"
  ollama list 2>/dev/null || echo "  Ollama not running"
  echo ""
}

cmd_dev(){
  banner
  section "Starting in development mode (auto-reload)"
  [ -d "$VENV_DIR" ] || error "Not installed. Run: ./nexus.sh install"
  command -v npm >/dev/null 2>&1 || error "npm required for the Vite frontend. Install Node.js/npm first."
  [ -d "$NEXUS_DIR/node_modules" ] || error "Frontend dependencies missing. Run: ./nexus.sh install"
  # Start Ollama
  pgrep -x ollama >/dev/null 2>&1 || { ollama serve &>/dev/null & sleep 2; }
  info "Ollama running"

  mkdir -p "$NEXUS_DIR/logs"

  cd "$NEXUS_DIR"
  info "Starting Vite frontend on :5173"
  npm run dev > "$NEXUS_DIR/logs/frontend-dev.log" 2>&1 &
  echo $! > "$FRONTEND_PID_FILE"

  cleanup_dev(){
    if [ -f "$FRONTEND_PID_FILE" ]; then
      FRONTEND_PID=$(cat "$FRONTEND_PID_FILE")
      kill "$FRONTEND_PID" 2>/dev/null || true
      rm -f "$FRONTEND_PID_FILE"
    fi
  }
  trap cleanup_dev EXIT INT TERM

  cd "$NEXUS_DIR/backend"
  info "Starting with --reload on :8000"
  echo -e "  UI:      ${BOLD}http://localhost:5173${RESET}"
  echo -e "  API:     ${BOLD}http://localhost:8000/docs${RESET}"
  "$VENV_DIR/bin/python" -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload --log-level debug
}

cmd_update(){
  section "Updating dependencies"
  "$VENV_DIR/bin/pip" install -r "$NEXUS_DIR/requirements.txt" --upgrade -q
  cd "$NEXUS_DIR"
  npm install
  info "Updated"
}

# -- Entry point ---------------------------------------------------------------
case "${1:-help}" in
  install)  cmd_install ;;
  start)    cmd_start ;;
  stop)     cmd_stop ;;
  restart)  cmd_restart ;;
  logs)     cmd_logs ;;
  status)   cmd_status ;;
  dev)      cmd_dev ;;
  update)   cmd_update ;;
  *)
    banner
    echo -e "${BOLD}Usage:${RESET} ./nexus.sh <command>"
    echo ""
    echo -e "  ${BOLD}install${RESET}    Install dependencies and set up Nexus"
    echo -e "  ${BOLD}start${RESET}      Start Nexus (background)"
    echo -e "  ${BOLD}stop${RESET}       Stop Nexus"
    echo -e "  ${BOLD}restart${RESET}    Restart Nexus"
    echo -e "  ${BOLD}status${RESET}     Show service status and installed models"
    echo -e "  ${BOLD}logs${RESET}       Tail the log file"
    echo -e "  ${BOLD}dev${RESET}        Run in dev mode with auto-reload"
    echo -e "  ${BOLD}update${RESET}     Update Python dependencies"
    echo ""
    ;;
esac
