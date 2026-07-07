#!/usr/bin/env bash
# ============================================================================
# Lattica — Setup Script
#
# Usage:
#   ./setup.sh              # Backend only (required for both paths)
#   ./setup.sh --dashboard  # Backend + React frontend
#   ./setup.sh --agent      # Backend + Claude Code agent install
#   ./setup.sh --all        # Everything
#
# Prerequisites:
#   - Python 3.11+
#   - bun (for --dashboard or --all)
#   - Claude Code (for --agent or --all)
# ============================================================================

set -euo pipefail

# --- Colors for output ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# --- Helper functions ---
info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC}   $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERR]${NC}  $1"; exit 1; }

# --- Parse flags ---
INSTALL_DASHBOARD=false
INSTALL_AGENT=false

for arg in "$@"; do
  case "$arg" in
    --dashboard) INSTALL_DASHBOARD=true ;;
    --agent)     INSTALL_AGENT=true ;;
    --all)       INSTALL_DASHBOARD=true; INSTALL_AGENT=true ;;
    --help|-h)
      echo "Usage: ./setup.sh [--dashboard] [--agent] [--all]"
      echo ""
      echo "  (no flags)    Backend only (required for both paths)"
      echo "  --dashboard   Backend + React frontend (for API key users)"
      echo "  --agent       Backend + Claude Code agent install (for subscription users)"
      echo "  --all         Everything"
      exit 0
      ;;
    *) error "Unknown flag: $arg. Run ./setup.sh --help for usage." ;;
  esac
done

# --- Resolve project root (directory containing this script) ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "============================================"
echo "  Lattica — PQC Readiness Tool Setup"
echo "============================================"
echo ""

# =========================================================================
# 1. BACKEND (always installed)
# =========================================================================
info "Setting up backend..."

# Check Python is available
if ! command -v python3 &> /dev/null; then
  error "Python 3 is required but not found. Install Python 3.11+ and retry."
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
info "Found Python $PYTHON_VERSION"

cd "$SCRIPT_DIR/backend"

# Create virtual environment if it doesn't exist
if [ ! -d ".venv" ]; then
  info "Creating virtual environment..."
  python3 -m venv .venv
  success "Virtual environment created"
else
  success "Virtual environment already exists"
fi

# Install dependencies
info "Installing Python dependencies (this may take a minute)..."
.venv/bin/pip install -q -r requirements.txt
success "Dependencies installed"

# Copy .env.example → .env if .env doesn't exist
if [ ! -f ".env" ]; then
  cp .env.example .env
  success "Created .env from .env.example"
  warn "Edit backend/.env to add your API keys (optional — needed for AI Deep Dive)"
else
  success ".env already exists"
fi

success "Backend ready"
echo ""

# =========================================================================
# 2. DASHBOARD (--dashboard or --all)
# =========================================================================
if [ "$INSTALL_DASHBOARD" = true ]; then
  info "Setting up frontend dashboard..."

  # Check bun is available
  if ! command -v bun &> /dev/null; then
    error "bun is required for the dashboard but not found. Install from https://bun.sh and retry."
  fi

  cd "$SCRIPT_DIR/frontend"

  info "Installing frontend dependencies..."
  bun install
  success "Frontend dependencies installed"

  success "Dashboard ready"
  echo ""
fi

# =========================================================================
# 3. AGENT (--agent or --all)
# =========================================================================
if [ "$INSTALL_AGENT" = true ]; then
  info "Setting up Claude Code agent..."

  # Check Claude Code is available
  if ! command -v claude &> /dev/null; then
    warn "Claude Code CLI not found — agent files will be copied but you'll need Claude Code to use them."
    warn "Install from: https://docs.anthropic.com/en/docs/claude-code"
  fi

  # Create Claude Code directories if they don't exist
  mkdir -p "$HOME/.claude/agents"
  mkdir -p "$HOME/.claude/skills/Agents"

  # Copy agent definition
  cp "$SCRIPT_DIR/agent/lattica-pqc-advisor.md" "$HOME/.claude/agents/lattica-pqc-advisor.md"
  success "Agent definition installed → ~/.claude/agents/lattica-pqc-advisor.md"

  # Copy context file
  cp "$SCRIPT_DIR/agent/LatticaContext.md" "$HOME/.claude/skills/Agents/LatticaContext.md"
  success "Context file installed → ~/.claude/skills/Agents/LatticaContext.md"

  # Slash commands are project-level (.claude/commands/) — they work automatically
  success "Slash commands (/scan, /remediate, /report) are project-level — no install needed"

  success "Agent ready"
  echo ""
fi

# =========================================================================
# Summary
# =========================================================================
echo "============================================"
echo "  Setup Complete"
echo "============================================"
echo ""
echo "  Start the backend:"
echo "    cd backend && .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
echo ""

if [ "$INSTALL_DASHBOARD" = true ]; then
  echo "  Start the dashboard:"
  echo "    cd frontend && bun run dev"
  echo "    Then open http://localhost:5173"
  echo ""
fi

if [ "$INSTALL_AGENT" = true ]; then
  echo "  Start the agent:"
  echo "    cd $(basename "$SCRIPT_DIR") && claude --agent lattica-pqc-advisor"
  echo "    Or use slash commands: /scan, /remediate, /report"
  echo ""
fi

echo "  Docs: see README.md for full usage guide"
echo ""
