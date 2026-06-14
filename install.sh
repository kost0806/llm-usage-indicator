#!/usr/bin/env bash
# install.sh — Install llm-usage-indicator daemon, systemd service, and Waybar script.
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

PY_VER=$("$PYTHON" --version 2>&1 | awk '{print $2}')
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    error "Python 3.10+ required, found $PY_VER. Please upgrade Python."
fi
info "Python $PY_VER — OK"

# ── Step 2: Node.js / npx check ──────────────────────────────────────────────
info "Checking Node.js / npx..."
NPX=$(command -v npx || true)
if [ -z "$NPX" ]; then
    warn "npx not found — ccusage CLI requires Node.js 18+."
    warn "Install Node.js from https://nodejs.org/ or via your package manager:"
    warn "  Ubuntu/Debian: sudo apt install nodejs npm"
    warn "  Arch:          sudo pacman -S nodejs npm"
    warn "The daemon will show zero usage until Node.js is installed."
else
    NODE_VER=$(node --version 2>/dev/null || echo "unknown")
    info "Node.js $NODE_VER / npx — OK"
fi

# ── Step 3: Install Python dependencies ──────────────────────────────────────
info "Installing Python dependencies..."
"$PYTHON" -m pip install -r "$SCRIPT_DIR/requirements.txt" --user -q
info "Dependencies installed."

# ── Step 4: Create config directory ──────────────────────────────────────────
CONFIG_DIR="$HOME/.config/llm-usage-indicator"
info "Creating config directory: $CONFIG_DIR"
mkdir -p "$CONFIG_DIR"
chmod 700 "$CONFIG_DIR"

# ── Step 5: Copy example config (skip if exists) ─────────────────────────────
CONFIG_FILE="$CONFIG_DIR/config.toml"
if [ -f "$CONFIG_FILE" ]; then
    warn "Config file already exists, skipping: $CONFIG_FILE"
else
    cp "$SCRIPT_DIR/config.example.toml" "$CONFIG_FILE"
    chmod 600 "$CONFIG_FILE"
    info "Created config: $CONFIG_FILE"
    info "→ Edit $CONFIG_FILE to set your monthly budgets."
fi

# ── Step 6: Copy daemon library ───────────────────────────────────────────────
LIB_DIR="$HOME/.local/lib/llm_usage_indicator"
info "Installing daemon to: $LIB_DIR"
mkdir -p "$LIB_DIR"
cp -r "$SCRIPT_DIR/daemon/"* "$LIB_DIR/"
info "Daemon library installed."

# ── Step 7: Create wrapper script ────────────────────────────────────────────
BIN_DIR="$HOME/.local/bin"
mkdir -p "$BIN_DIR"
WRAPPER="$BIN_DIR/llm-usage-indicator"

cat > "$WRAPPER" << WRAPPER_EOF
#!/usr/bin/env bash
PYTHONPATH="\$HOME/.local/lib" exec python3 -m llm_usage_indicator.main "\$@"
WRAPPER_EOF

chmod +x "$WRAPPER"
info "Wrapper installed: $WRAPPER"

# ── Step 8: Migrate old service if present ───────────────────────────────────
OLD_SERVICE="$HOME/.config/systemd/user/llm-credit-monitor.service"
if [ -f "$OLD_SERVICE" ]; then
    systemctl --user disable --now llm-credit-monitor 2>/dev/null || true
    rm -f "$OLD_SERVICE"
    info "Removed old llm-credit-monitor service."
fi

# ── Step 9: Install and enable systemd service ───────────────────────────────
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
info "Installing systemd user service..."
mkdir -p "$SYSTEMD_USER_DIR"
cp "$SCRIPT_DIR/systemd/llm-usage-indicator.service" "$SYSTEMD_USER_DIR/"

systemctl --user daemon-reload
systemctl --user enable --now llm-usage-indicator
info "Service enabled and started."

# ── Step 10: Install Waybar script ───────────────────────────────────────────
WAYBAR_SCRIPTS="$HOME/.config/waybar/scripts"
info "Installing Waybar script..."
mkdir -p "$WAYBAR_SCRIPTS"
cp "$SCRIPT_DIR/waybar/module.sh" "$WAYBAR_SCRIPTS/llm-monitor.sh"
chmod +x "$WAYBAR_SCRIPTS/llm-monitor.sh"
info "Waybar script installed: $WAYBAR_SCRIPTS/llm-monitor.sh"

# ── Step 11: Install GUI settings app ────────────────────────────────────────
info "Installing settings GUI..."

# Check for PyGObject (python3-gi)
if ! "$PYTHON" -c "import gi" 2>/dev/null; then
    warn "python3-gi not found — settings GUI will not work."
    warn "Install with: sudo apt install python3-gi gir1.2-gtk-3.0"
else
    info "python3-gi — OK"
fi

# Copy GUI script to lib dir
cp "$SCRIPT_DIR/gui/settings.py" "$LIB_DIR/settings_gui.py"

# Create settings launcher wrapper
SETTINGS_BIN="$BIN_DIR/llm-usage-indicator-settings"
cat > "$SETTINGS_BIN" << SETTINGS_EOF
#!/usr/bin/env bash
PYTHONPATH="\$HOME/.local/lib" exec python3 -m llm_usage_indicator.settings_gui "\$@"
SETTINGS_EOF
chmod +x "$SETTINGS_BIN"
info "Settings launcher installed: $SETTINGS_BIN"

# Install .desktop entry so it appears in app launchers
APPS_DIR="$HOME/.local/share/applications"
mkdir -p "$APPS_DIR"
cp "$SCRIPT_DIR/gui/llm-usage-indicator-settings.desktop" "$APPS_DIR/"
sed -i "s|^Exec=.*|Exec=$SETTINGS_BIN|" "$APPS_DIR/llm-usage-indicator-settings.desktop"
update-desktop-database "$APPS_DIR" 2>/dev/null || true
info "Desktop entry installed: $APPS_DIR/llm-usage-indicator-settings.desktop"

# ── Step 12: Install tray indicator ──────────────────────────────────────────
info "Installing GNOME tray indicator..."

# Check for AppIndicator3
if ! "$PYTHON" -c "
import gi
gi.require_version('AppIndicator3', '0.1')
from gi.repository import AppIndicator3
" 2>/dev/null; then
    warn "AppIndicator3 not found — tray indicator will not work."
    warn "Install with: sudo apt install gir1.2-appindicator3-0.1 gnome-shell-extension-appindicator"
else
    info "AppIndicator3 — OK"
fi

# Copy tray script to lib dir
cp "$SCRIPT_DIR/gui/tray.py" "$LIB_DIR/tray.py"

# Create tray launcher wrapper
TRAY_BIN="$BIN_DIR/llm-usage-indicator-tray"
cat > "$TRAY_BIN" << TRAY_EOF
#!/usr/bin/env bash
PYTHONPATH="\$HOME/.local/lib" exec python3 -m llm_usage_indicator.tray "\$@"
TRAY_EOF
chmod +x "$TRAY_BIN"
info "Tray launcher installed: $TRAY_BIN"

# XDG autostart: launch tray on login
AUTOSTART_DIR="$HOME/.config/autostart"
mkdir -p "$AUTOSTART_DIR"
cp "$SCRIPT_DIR/gui/llm-usage-indicator-tray.desktop" "$AUTOSTART_DIR/"
sed -i "s|^Exec=.*|Exec=$TRAY_BIN|" "$AUTOSTART_DIR/llm-usage-indicator-tray.desktop"
info "Autostart entry installed: $AUTOSTART_DIR/llm-usage-indicator-tray.desktop"

# Start tray now if a display is available
if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
    pkill -f "llm_usage_indicator.tray" 2>/dev/null || true
    nohup "$TRAY_BIN" >/dev/null 2>&1 &
    info "Tray indicator started."
else
    info "No display detected — tray will start at next login."
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
info "Installation complete!"
echo ""
echo "Next steps:"
echo "  1. Edit your monthly budgets (or use the settings GUI):"
echo "       $CONFIG_FILE"
echo ""
echo "  2. Log in with Claude Code CLI (no API key needed):"
echo "       claude login"
echo ""
echo "  3. The tray icon should already be visible in the top bar."
echo "     If not, log out and back in, or run manually:"
echo "       $TRAY_BIN"
echo ""
echo "  4. Open settings:"
echo "       $SETTINGS_BIN"
echo "       (or right-click the tray icon → Settings…)"
echo ""
echo "  5. Restart the daemon after editing config:"
echo "       systemctl --user restart llm-usage-indicator"
