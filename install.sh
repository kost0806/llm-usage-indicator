#!/usr/bin/env bash
# install.sh — Install llm-credit-monitor daemon, systemd service, and Waybar script.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

info()    { printf "${GREEN}[INFO]${NC} %s\n" "$*"; }
warn()    { printf "${YELLOW}[WARN]${NC} %s\n" "$*"; }
error()   { printf "${RED}[ERROR]${NC} %s\n" "$*"; exit 1; }

# ── Step 1: Python version check ─────────────────────────────────────────────
info "Checking Python version..."
PYTHON=$(command -v python3 || true)
if [ -z "$PYTHON" ]; then
    error "python3 not found. Please install Python 3.10 or newer."
fi

PY_VER=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$("$PYTHON" -c "import sys; print(sys.version_info.major)")
PY_MINOR=$("$PYTHON" -c "import sys; print(sys.version_info.minor)")

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    error "Python 3.10+ required, found $PY_VER. Please upgrade Python."
fi
info "Python $PY_VER — OK"

# ── Step 2: Install dependencies ─────────────────────────────────────────────
info "Installing Python dependencies..."
"$PYTHON" -m pip install -r "$SCRIPT_DIR/requirements.txt" --user -q
info "Dependencies installed."

# ── Step 3: Create config directory ──────────────────────────────────────────
CONFIG_DIR="$HOME/.config/llm-credit-monitor"
info "Creating config directory: $CONFIG_DIR"
mkdir -p "$CONFIG_DIR"
chmod 700 "$CONFIG_DIR"

# ── Step 4: Copy example config (skip if exists) ─────────────────────────────
CONFIG_FILE="$CONFIG_DIR/config.toml"
if [ -f "$CONFIG_FILE" ]; then
    warn "Config file already exists, skipping: $CONFIG_FILE"
else
    cp "$SCRIPT_DIR/config.example.toml" "$CONFIG_FILE"
    chmod 600 "$CONFIG_FILE"
    info "Created config: $CONFIG_FILE"
    info "→ Edit $CONFIG_FILE to add your API keys before starting the daemon."
fi

# ── Step 5: Copy daemon library ───────────────────────────────────────────────
LIB_DIR="$HOME/.local/lib/llm-credit-monitor"
info "Installing daemon to: $LIB_DIR"
mkdir -p "$LIB_DIR"
cp -r "$SCRIPT_DIR/daemon/"* "$LIB_DIR/"
info "Daemon library installed."

# ── Step 6: Create wrapper script ────────────────────────────────────────────
BIN_DIR="$HOME/.local/bin"
mkdir -p "$BIN_DIR"
WRAPPER="$BIN_DIR/llm-credit-monitor"

cat > "$WRAPPER" << 'WRAPPER_EOF'
#!/usr/bin/env bash
# llm-credit-monitor launcher wrapper
PYTHONPATH="$HOME/.local/lib" exec python3 -m llm-credit-monitor "$@"
WRAPPER_EOF

# The module name uses a hyphen which Python can't import directly.
# Use the full path approach instead.
cat > "$WRAPPER" << WRAPPER_EOF
#!/usr/bin/env bash
PYTHONPATH="\$HOME/.local/lib" exec python3 -c "
import sys
sys.path.insert(0, '\$HOME/.local/lib/llm-credit-monitor')
from main import main
main()
" "\$@"
WRAPPER_EOF

chmod +x "$WRAPPER"
info "Wrapper installed: $WRAPPER"

# ── Step 7: Install and enable systemd service ───────────────────────────────
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
info "Installing systemd user service..."
mkdir -p "$SYSTEMD_USER_DIR"
cp "$SCRIPT_DIR/systemd/llm-credit-monitor.service" "$SYSTEMD_USER_DIR/"

systemctl --user daemon-reload
systemctl --user enable --now llm-credit-monitor
info "Service enabled and started."

# ── Step 8: Install Waybar script ────────────────────────────────────────────
WAYBAR_SCRIPTS="$HOME/.config/waybar/scripts"
info "Installing Waybar script..."
mkdir -p "$WAYBAR_SCRIPTS"
cp "$SCRIPT_DIR/waybar/module.sh" "$WAYBAR_SCRIPTS/llm-monitor.sh"
chmod +x "$WAYBAR_SCRIPTS/llm-monitor.sh"
info "Waybar script installed: $WAYBAR_SCRIPTS/llm-monitor.sh"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
info "Installation complete!"
echo ""
echo "Next steps:"
echo "  1. Edit your API keys:"
echo "       $CONFIG_FILE"
echo ""
echo "  2. Restart the daemon after editing config:"
echo "       systemctl --user restart llm-credit-monitor"
echo ""
echo "  3. Check daemon status:"
echo "       systemctl --user status llm-credit-monitor"
echo ""
echo "  4. Add to Waybar config (see waybar/config-example.json):"
echo "       Add the 'custom/llm-monitor' module to your Waybar config."
echo ""
echo "  5. Test the socket:"
echo "       echo '{\"cmd\":\"status\"}' | socat - UNIX-CONNECT:/tmp/llm-monitor.sock"
echo ""
echo "  6. Test the Waybar script:"
echo "       $WAYBAR_SCRIPTS/llm-monitor.sh"
