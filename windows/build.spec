# PyInstaller spec for llm-usage-indicator Windows build.
# Produces two standalone executables bundled in a single COLLECT output:
#   llm-monitor-daemon.exe  — background daemon (no console window)
#   llm-monitor-tray.exe    — system tray GUI   (no console window)
#   llm-monitor-settings.exe — settings GUI     (no console window)

import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent  # repo root

# ── Daemon ─────────────────────────────────────────────────────────────────────
a_daemon = Analysis(
    [str(ROOT / "daemon" / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=["aiosqlite", "platformdirs", "tomllib"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pystray", "PIL"],
    noarchive=False,
)
pyz_daemon = PYZ(a_daemon.pure)
exe_daemon = EXE(
    pyz_daemon,
    a_daemon.scripts,
    [],
    exclude_binaries=True,
    name="llm-monitor-daemon",
    console=False,
    icon=str(ROOT / "windows" / "icon.ico") if (ROOT / "windows" / "icon.ico").exists() else None,
)

# ── Tray ───────────────────────────────────────────────────────────────────────
a_tray = Analysis(
    [str(ROOT / "gui" / "tray.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=["pystray._win32", "PIL._imaging", "PIL.Image", "PIL.ImageDraw"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz_tray = PYZ(a_tray.pure)
exe_tray = EXE(
    pyz_tray,
    a_tray.scripts,
    [],
    exclude_binaries=True,
    name="llm-monitor-tray",
    console=False,
    icon=str(ROOT / "windows" / "icon.ico") if (ROOT / "windows" / "icon.ico").exists() else None,
)

# ── Settings ───────────────────────────────────────────────────────────────────
a_settings = Analysis(
    [str(ROOT / "gui" / "settings.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=["platformdirs", "tomllib", "tkinter", "tkinter.ttk"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["pystray", "PIL"],
    noarchive=False,
)
pyz_settings = PYZ(a_settings.pure)
exe_settings = EXE(
    pyz_settings,
    a_settings.scripts,
    [],
    exclude_binaries=True,
    name="llm-monitor-settings",
    console=False,
    icon=str(ROOT / "windows" / "icon.ico") if (ROOT / "windows" / "icon.ico").exists() else None,
)

# ── Collect all into a single dist/ directory ──────────────────────────────────
coll = COLLECT(
    exe_daemon,
    a_daemon.binaries,
    a_daemon.zipfiles,
    a_daemon.datas,
    exe_tray,
    a_tray.binaries,
    a_tray.zipfiles,
    a_tray.datas,
    exe_settings,
    a_settings.binaries,
    a_settings.zipfiles,
    a_settings.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="llm-usage-indicator",
)
