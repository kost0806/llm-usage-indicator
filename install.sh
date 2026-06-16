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

# ── Step 2: Install Python dependencies ──────────────────────────────────────
info "Installing Python dependencies..."

# Resolve pip: prefer python3 -m pip (guaranteed same interpreter), then PATH fallback.
PIP_RUN=""
if "$PYTHON" -m pip --version >/dev/null 2>&1; then
    PIP_RUN="$PYTHON -m pip"
else
    for _candidate in pip3 pip; do
        if command -v "$_candidate" >/dev/null 2>&1; then
            warn "pip not found via '$PYTHON -m pip'; using $(command -v "$_candidate") from PATH."
            PIP_RUN="$_candidate"
            break
        fi
    done
fi

if [ -z "$PIP_RUN" ]; then
    warn "No pip found in PATH. Attempting to bootstrap with ensurepip..."
    if "$PYTHON" -m ensurepip --upgrade 2>/dev/null; then
        PIP_RUN="$PYTHON -m pip"
        info "pip bootstrapped via ensurepip."
    else
        error "pip is not available.\n       On Ubuntu/Debian:   sudo apt install python3-pip\n       On Anaconda/Miniconda: conda install pip"
    fi
fi

$PIP_RUN install -r "$SCRIPT_DIR/requirements.txt" --user -q
info "Dependencies installed."

# ── Step 3: Create config directory ──────────────────────────────────────────
CONFIG_DIR="$HOME/.config/llm-usage-indicator"
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
    info "→ Edit $CONFIG_FILE to set your monthly budgets."
fi

# ── Step 5: Copy daemon library ───────────────────────────────────────────────
LIB_DIR="$HOME/.local/lib/llm_usage_indicator"
info "Installing daemon to: $LIB_DIR"
mkdir -p "$LIB_DIR"
cp -r "$SCRIPT_DIR/daemon/"* "$LIB_DIR/"
info "Daemon library installed."

# ── Step 6: Create wrapper script ────────────────────────────────────────────
BIN_DIR="$HOME/.local/bin"
mkdir -p "$BIN_DIR"
WRAPPER="$BIN_DIR/llm-usage-indicator"

cat > "$WRAPPER" << WRAPPER_EOF
#!/usr/bin/env bash
PYTHONPATH="\$HOME/.local/lib" exec python3 -m llm_usage_indicator.main "\$@"
WRAPPER_EOF

chmod +x "$WRAPPER"
info "Wrapper installed: $WRAPPER"

# ── Step 7: Migrate old service if present ───────────────────────────────────
OLD_SERVICE="$HOME/.config/systemd/user/llm-credit-monitor.service"
if [ -f "$OLD_SERVICE" ]; then
    systemctl --user disable --now llm-credit-monitor 2>/dev/null || true
    rm -f "$OLD_SERVICE"
    info "Removed old llm-credit-monitor service."
fi

# ── Step 8: Install and enable systemd service ───────────────────────────────
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
info "Installing systemd user service..."
mkdir -p "$SYSTEMD_USER_DIR"
cp "$SCRIPT_DIR/systemd/llm-usage-indicator.service" "$SYSTEMD_USER_DIR/"

if systemctl --user daemon-reload 2>/dev/null; then
    systemctl --user enable --now llm-usage-indicator 2>/dev/null \
        && info "Service enabled and started." \
        || warn "Could not start service — run after login: systemctl --user enable --now llm-usage-indicator"
else
    warn "No active user session — daemon service will activate at next login."
    warn "Run after login: systemctl --user enable --now llm-usage-indicator"
fi

# ── Step 9: Install Waybar script ────────────────────────────────────────────
WAYBAR_SCRIPTS="$HOME/.config/waybar/scripts"
info "Installing Waybar script..."
mkdir -p "$WAYBAR_SCRIPTS"
cp "$SCRIPT_DIR/waybar/module.sh" "$WAYBAR_SCRIPTS/llm-monitor.sh"
chmod +x "$WAYBAR_SCRIPTS/llm-monitor.sh"
info "Waybar script installed: $WAYBAR_SCRIPTS/llm-monitor.sh"

# ── Step 10: Install GUI settings app ────────────────────────────────────────
info "Installing settings GUI..."

cp "$SCRIPT_DIR/gui/settings.py" "$LIB_DIR/settings_gui.py"

SETTINGS_BIN="$BIN_DIR/llm-usage-indicator-settings"
cat > "$SETTINGS_BIN" << SETTINGS_EOF
#!/usr/bin/env bash
PYTHONPATH="\$HOME/.local/lib" exec python3 -m llm_usage_indicator.settings_gui "\$@"
SETTINGS_EOF
chmod +x "$SETTINGS_BIN"
info "Settings launcher installed: $SETTINGS_BIN"

APPS_DIR="$HOME/.local/share/applications"
mkdir -p "$APPS_DIR"
cp "$SCRIPT_DIR/gui/llm-usage-indicator-settings.desktop" "$APPS_DIR/"
sed -i "s|^Exec=.*|Exec=$SETTINGS_BIN|" "$APPS_DIR/llm-usage-indicator-settings.desktop"
update-desktop-database "$APPS_DIR" 2>/dev/null || true
info "Desktop entry installed: $APPS_DIR/llm-usage-indicator-settings.desktop"

# ── Step 11: Install tray indicator ──────────────────────────────────────────
info "Installing tray indicator..."

cp "$SCRIPT_DIR/gui/tray.py" "$LIB_DIR/tray.py"

TRAY_BIN="$BIN_DIR/llm-usage-indicator-tray"
cat > "$TRAY_BIN" << TRAY_EOF
#!/usr/bin/env bash
PYTHONPATH="$HOME/.local/lib" exec python3 -m llm_usage_indicator.tray "\$@"
TRAY_EOF
chmod +x "$TRAY_BIN"
info "Tray launcher installed: $TRAY_BIN"

cp "$SCRIPT_DIR/systemd/llm-usage-indicator-tray.service" "$SYSTEMD_USER_DIR/"
systemctl --user daemon-reload 2>/dev/null || true
info "Tray service registered: llm-usage-indicator-tray"

TRAY_STARTER="$BIN_DIR/llm-usage-indicator-tray-start"
cat > "$TRAY_STARTER" << STARTER_EOF
#!/usr/bin/env bash
if command -v systemctl >/dev/null 2>&1; then
    [ -n "\${DISPLAY:-}" ]         && systemctl --user import-environment DISPLAY XAUTHORITY 2>/dev/null || true
    [ -n "\${WAYLAND_DISPLAY:-}" ] && systemctl --user import-environment WAYLAND_DISPLAY    2>/dev/null || true
    systemctl --user start llm-usage-indicator-tray 2>/dev/null && exit 0
fi
exec "$TRAY_BIN"
STARTER_EOF
chmod +x "$TRAY_STARTER"
info "Tray starter installed: $TRAY_STARTER"

AUTOSTART_DIR="$HOME/.config/autostart"
mkdir -p "$AUTOSTART_DIR"
cp "$SCRIPT_DIR/gui/llm-usage-indicator-tray.desktop" "$AUTOSTART_DIR/"
sed -i "s|^Exec=.*|Exec=$TRAY_STARTER|" "$AUTOSTART_DIR/llm-usage-indicator-tray.desktop"
info "Autostart entry installed: $AUTOSTART_DIR/llm-usage-indicator-tray.desktop"

if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
    pkill -f "llm_usage_indicator.tray" 2>/dev/null || true
    systemctl --user stop llm-usage-indicator-tray 2>/dev/null || true
    [ -n "${DISPLAY:-}" ]         && systemctl --user import-environment DISPLAY XAUTHORITY 2>/dev/null || true
    [ -n "${WAYLAND_DISPLAY:-}" ] && systemctl --user import-environment WAYLAND_DISPLAY    2>/dev/null || true
    systemctl --user start llm-usage-indicator-tray 2>/dev/null \
        || { nohup "$TRAY_BIN" >/dev/null 2>&1 & }
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
echo "  5. Check service status:"
echo "       systemctl --user status llm-usage-indicator        # daemon"
echo "       systemctl --user status llm-usage-indicator-tray   # tray"
echo ""
echo "  6. View logs:"
echo "       journalctl --user -u llm-usage-indicator -f"
echo ""
echo "  7. Restart the daemon after editing config:"
echo "       systemctl --user restart llm-usage-indicator"
