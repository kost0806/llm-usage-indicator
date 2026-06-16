#!/usr/bin/env bash
# install.sh — Install llm-usage-indicator daemon, systemd service, and Waybar script.
#
# One-liner install (Linux / macOS):
#   curl -fsSL https://raw.githubusercontent.com/kost0806/llm-usage-indicator/main/install.sh | bash

# ── Bootstrap ──────────────────────────────────────────────────────────────────
# When piped through bash (curl … | bash), BASH_SOURCE[0] is empty and the
# source tree is not present locally.  Download the release tarball and re-exec.
#
# _RELEASE_VERSION is empty in the main-branch copy; release.yml injects the
# exact version string (e.g. "1.2.3") into release assets so they always
# download the matching tarball instead of querying for the latest.
_RELEASE_VERSION=""  # @RELEASE_VERSION@

_BS_SELF="${BASH_SOURCE[0]:-}"
if [[ -z "$_BS_SELF" ]] || [[ ! -f "$_BS_SELF" ]] || [[ ! -d "$(dirname "$_BS_SELF")/daemon" ]]; then
    _BS_TMP=$(mktemp -d) || { printf '\033[0;31m[ERROR]\033[0m mktemp failed\n' >&2; exit 1; }

    if [[ -n "$_RELEASE_VERSION" ]]; then
        # Running from a versioned release asset — download the exact tarball.
        _BS_TAG="v${_RELEASE_VERSION}"
        _BS_URL="https://github.com/kost0806/llm-usage-indicator/releases/download/${_BS_TAG}/llm-usage-indicator-${_RELEASE_VERSION}.tar.gz"
        printf '\033[0;32m[INFO]\033[0m Downloading llm-usage-indicator %s...\n' "$_BS_TAG"
    else
        # Running from the main branch — resolve the latest release.
        printf '\033[0;32m[INFO]\033[0m Bootstrapping — fetching latest release...\n'
        _BS_TAG=$(curl -fsSL \
            'https://api.github.com/repos/kost0806/llm-usage-indicator/releases/latest' \
            2>/dev/null | grep -o '"tag_name":"[^"]*"' | head -1 | cut -d'"' -f4 || true)
        if [[ -n "$_BS_TAG" ]]; then
            _BS_URL="https://github.com/kost0806/llm-usage-indicator/releases/download/${_BS_TAG}/llm-usage-indicator-${_BS_TAG#v}.tar.gz"
            printf '\033[0;32m[INFO]\033[0m Downloading llm-usage-indicator %s...\n' "$_BS_TAG"
        else
            printf '\033[1;33m[WARN]\033[0m No release found — using main branch source.\n'
            _BS_URL='https://github.com/kost0806/llm-usage-indicator/archive/refs/heads/main.tar.gz'
        fi
    fi

    if ! curl -fsSL "$_BS_URL" | tar -xz -C "$_BS_TMP" --strip-components=1; then
        printf '\033[0;31m[ERROR]\033[0m Download failed. Check your network.\n' >&2
        rm -rf "$_BS_TMP"
        exit 1
    fi

    LLM_BOOTSTRAP_TMP="$_BS_TMP" exec bash "$_BS_TMP/install.sh" "$@"
    exit 1
fi
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

info()    { printf "${GREEN}[INFO]${NC} %s\n" "$*"; }
warn()    { printf "${YELLOW}[WARN]${NC} %s\n" "$*"; }
error()   { printf "${RED}[ERROR]${NC} %s\n" "$*"; exit 1; }

# ── Rollback tracking ─────────────────────────────────────────────────────────
# Files to remove (rm -f) and directories to remove (rm -rf) on failure.
# Directories are stored in creation order; rollback removes them in reverse.
_RB_FILES=()
_RB_DIRS=()
_INSTALL_OK=0

rollback() {
    [ "$_INSTALL_OK" = "1" ] && return
    warn "Installation failed — rolling back..."

    # Stop and disable any services we may have enabled.
    systemctl --user disable --now llm-usage-indicator      2>/dev/null || true
    systemctl --user disable --now llm-usage-indicator-tray 2>/dev/null || true
    systemctl --user daemon-reload                          2>/dev/null || true

    # Remove individual tracked files.
    for f in "${_RB_FILES[@]+"${_RB_FILES[@]}"}"; do
        rm -f "$f"
    done

    # Remove tracked directories in reverse creation order.
    local i
    for (( i=${#_RB_DIRS[@]}-1; i>=0; i-- )); do
        rm -rf "${_RB_DIRS[$i]}"
    done

    warn "Rollback complete. Fix the issue above, then re-run: bash $0"
}
trap rollback EXIT

# Create a directory only if it does not already exist; track new ones for rollback.
ensure_dir() {
    local dir="$1"
    if [ ! -d "$dir" ]; then
        mkdir -p "$dir"
        _RB_DIRS+=("$dir")
    fi
}

# Copy a file and register the destination for rollback.
install_file() {
    local src="$1" dst="$2"
    cp "$src" "$dst"
    _RB_FILES+=("$dst")
}

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

# ── Step 1b: Check and auto-install tkinter ──────────────────────────────────
if ! "$PYTHON" -c "import tkinter" 2>/dev/null; then
    warn "tkinter not found — the Settings GUI requires it."
    _TK_OK=0
    if command -v apt-get >/dev/null 2>&1; then
        info "Trying: sudo apt-get install -y python3-tk"
        sudo apt-get install -y python3-tk && _TK_OK=1 || true
    elif command -v pacman >/dev/null 2>&1; then
        info "Trying: sudo pacman -S --noconfirm tk"
        sudo pacman -S --noconfirm tk && _TK_OK=1 || true
    elif command -v dnf >/dev/null 2>&1; then
        info "Trying: sudo dnf install -y python3-tkinter"
        sudo dnf install -y python3-tkinter && _TK_OK=1 || true
    elif command -v brew >/dev/null 2>&1; then
        info "Trying: brew install python-tk"
        brew install python-tk && _TK_OK=1 || true
    fi
    if [ "$_TK_OK" = "1" ]; then
        info "tkinter installed successfully."
    else
        warn "Could not auto-install tkinter. Settings GUI will not work until you install it:"
        warn "  Ubuntu/Debian : sudo apt install python3-tk"
        warn "  Arch Linux    : sudo pacman -S tk"
        warn "  Fedora/RHEL   : sudo dnf install python3-tkinter"
        warn "  macOS (brew)  : brew install python-tk"
    fi
else
    info "tkinter — OK"
fi

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

if ! $PIP_RUN install -r "$SCRIPT_DIR/requirements.txt" --user -q; then
    error "Failed to install Python dependencies.\n       Check your network connection, then retry:\n         $PIP_RUN install -r /usr/share/llm-usage-indicator/requirements.txt --user"
fi
info "Dependencies installed."

# ── Step 3: Create config directory ──────────────────────────────────────────
CONFIG_DIR="$HOME/.config/llm-usage-indicator"
info "Creating config directory: $CONFIG_DIR"
ensure_dir "$CONFIG_DIR"
chmod 700 "$CONFIG_DIR"

# ── Step 4: Copy example config (skip if exists) ─────────────────────────────
CONFIG_FILE="$CONFIG_DIR/config.toml"
if [ -f "$CONFIG_FILE" ]; then
    warn "Config file already exists, skipping: $CONFIG_FILE"
else
    install_file "$SCRIPT_DIR/config.example.toml" "$CONFIG_FILE"
    chmod 600 "$CONFIG_FILE"
    info "Created config: $CONFIG_FILE"
    info "→ Edit $CONFIG_FILE to set your monthly budgets."
fi

# ── Step 5: Copy daemon library ───────────────────────────────────────────────
LIB_DIR="$HOME/.local/lib/llm_usage_indicator"
info "Installing daemon to: $LIB_DIR"
# LIB_DIR is package-specific; always track for full removal on rollback.
_RB_DIRS+=("$LIB_DIR")
mkdir -p "$LIB_DIR"
cp -r "$SCRIPT_DIR/daemon/"* "$LIB_DIR/"
info "Daemon library installed."

# ── Step 6: Create wrapper script ────────────────────────────────────────────
BIN_DIR="$HOME/.local/bin"
ensure_dir "$BIN_DIR"
WRAPPER="$BIN_DIR/llm-usage-indicator"
_RB_FILES+=("$WRAPPER")

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
ensure_dir "$SYSTEMD_USER_DIR"
install_file "$SCRIPT_DIR/systemd/llm-usage-indicator.service" "$SYSTEMD_USER_DIR/llm-usage-indicator.service"

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
ensure_dir "$WAYBAR_SCRIPTS"
install_file "$SCRIPT_DIR/waybar/module.sh" "$WAYBAR_SCRIPTS/llm-monitor.sh"
chmod +x "$WAYBAR_SCRIPTS/llm-monitor.sh"
info "Waybar script installed: $WAYBAR_SCRIPTS/llm-monitor.sh"

# ── Step 10: Install GUI settings app ────────────────────────────────────────
info "Installing settings GUI..."

install_file "$SCRIPT_DIR/gui/settings.py" "$LIB_DIR/settings_gui.py"

SETTINGS_BIN="$BIN_DIR/llm-usage-indicator-settings"
_RB_FILES+=("$SETTINGS_BIN")
cat > "$SETTINGS_BIN" << SETTINGS_EOF
#!/usr/bin/env bash
PYTHONPATH="\$HOME/.local/lib" exec python3 -m llm_usage_indicator.settings_gui "\$@"
SETTINGS_EOF
chmod +x "$SETTINGS_BIN"
info "Settings launcher installed: $SETTINGS_BIN"

APPS_DIR="$HOME/.local/share/applications"
ensure_dir "$APPS_DIR"
install_file "$SCRIPT_DIR/gui/llm-usage-indicator-settings.desktop" "$APPS_DIR/llm-usage-indicator-settings.desktop"
sed -i "s|^Exec=.*|Exec=$SETTINGS_BIN|" "$APPS_DIR/llm-usage-indicator-settings.desktop"
update-desktop-database "$APPS_DIR" 2>/dev/null || true
info "Desktop entry installed: $APPS_DIR/llm-usage-indicator-settings.desktop"

# ── Step 11: Install tray indicator ──────────────────────────────────────────
info "Installing tray indicator..."

install_file "$SCRIPT_DIR/gui/tray.py" "$LIB_DIR/tray.py"

TRAY_BIN="$BIN_DIR/llm-usage-indicator-tray"
_RB_FILES+=("$TRAY_BIN")
cat > "$TRAY_BIN" << TRAY_EOF
#!/usr/bin/env bash
PYTHONPATH="$HOME/.local/lib" exec python3 -m llm_usage_indicator.tray "\$@"
TRAY_EOF
chmod +x "$TRAY_BIN"
info "Tray launcher installed: $TRAY_BIN"

install_file "$SCRIPT_DIR/systemd/llm-usage-indicator-tray.service" "$SYSTEMD_USER_DIR/llm-usage-indicator-tray.service"
systemctl --user daemon-reload 2>/dev/null || true
info "Tray service registered: llm-usage-indicator-tray"

TRAY_STARTER="$BIN_DIR/llm-usage-indicator-tray-start"
_RB_FILES+=("$TRAY_STARTER")
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
ensure_dir "$AUTOSTART_DIR"
install_file "$SCRIPT_DIR/gui/llm-usage-indicator-tray.desktop" "$AUTOSTART_DIR/llm-usage-indicator-tray.desktop"
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
_INSTALL_OK=1   # disarm rollback trap
# Clean up bootstrap temp dir when install.sh was fetched and re-exec'd
[ -n "${LLM_BOOTSTRAP_TMP:-}" ] && rm -rf "${LLM_BOOTSTRAP_TMP}" || true
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
