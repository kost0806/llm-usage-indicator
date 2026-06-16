#Requires -Version 5.1
<#
.SYNOPSIS
    LLM Usage Indicator — Windows installer.

.DESCRIPTION
    One-liner (run in PowerShell as your normal user — no admin required):

        irm https://raw.githubusercontent.com/kost0806/llm-usage-indicator/main/install.ps1 | iex

    Installs to  %LOCALAPPDATA%\LLM Usage Indicator\
    Config lives in  %APPDATA%\LLM Usage Indicator\config.toml
    Autostart via HKCU Run registry key (daemon + tray on every login).
#>

# ── Bootstrap ──────────────────────────────────────────────────────────────────
# When run via irm|iex, $PSScriptRoot is empty and no local source files exist.
# Download the release tarball and re-exec from there.
#
# $_RELEASE_VERSION is empty in the main-branch copy; release.yml injects the
# exact version string (e.g. "1.2.3") into release assets so they always
# download the matching tarball instead of querying for the latest.
$_RELEASE_VERSION = ''  # @RELEASE_VERSION@

$_local = $PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot 'requirements.txt'))
if (-not $_local) {
    $ErrorActionPreference = 'Stop'
    $tmp = Join-Path $env:TEMP "llm-usage-indicator-$(Get-Random)"
    New-Item -ItemType Directory -Path $tmp | Out-Null
    try {
        if ($_RELEASE_VERSION) {
            # Running from a versioned release asset — download the exact tarball.
            $tag = "v$_RELEASE_VERSION"
            $url = "https://github.com/kost0806/llm-usage-indicator/releases/download/$tag/llm-usage-indicator-$_RELEASE_VERSION.tar.gz"
            Write-Host "[INFO] Downloading llm-usage-indicator $tag..." -ForegroundColor Green
        } else {
            # Running from the main branch — resolve the latest release.
            Write-Host '[INFO] Bootstrapping — fetching latest release...' -ForegroundColor Green
            try {
                $rel = Invoke-RestMethod 'https://api.github.com/repos/kost0806/llm-usage-indicator/releases/latest'
                $tag = $rel.tag_name
            } catch { $tag = $null }

            if ($tag) {
                $ver = $tag -replace '^v', ''
                $url = "https://github.com/kost0806/llm-usage-indicator/releases/download/$tag/llm-usage-indicator-$ver.tar.gz"
                Write-Host "[INFO] Downloading llm-usage-indicator $tag..." -ForegroundColor Green
            } else {
                Write-Host '[WARN] No release found — using main branch.' -ForegroundColor Yellow
                $url = 'https://github.com/kost0806/llm-usage-indicator/archive/refs/heads/main.tar.gz'
            }
        }

        $archive = Join-Path $tmp 'pkg.tar.gz'
        Invoke-WebRequest -Uri $url -OutFile $archive -UseBasicParsing
        & tar.exe -xzf $archive -C $tmp --strip-components=1
        if ($LASTEXITCODE -ne 0) { throw "tar extraction failed (exit $LASTEXITCODE)" }

        & powershell.exe -ExecutionPolicy Bypass -File (Join-Path $tmp 'install.ps1')
    } finally {
        Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
    }
    return
}
# ──────────────────────────────────────────────────────────────────────────────

$ErrorActionPreference = 'Stop'
$ScriptRoot = $PSScriptRoot

$APP_NAME   = 'LLM Usage Indicator'
$INSTALL    = Join-Path $env:LOCALAPPDATA $APP_NAME
$LIB_DIR    = Join-Path $INSTALL 'lib'
$PKG_DIR    = Join-Path $LIB_DIR 'llm_usage_indicator'
$BIN_DIR    = Join-Path $INSTALL 'bin'
$CONFIG_DIR = Join-Path $env:APPDATA $APP_NAME

function Write-Info ($msg) { Write-Host "[INFO]  $msg" -ForegroundColor Green }
function Write-Warn ($msg) { Write-Host "[WARN]  $msg" -ForegroundColor Yellow }
function Write-Err  ($msg) { Write-Host "[ERROR] $msg" -ForegroundColor Red; throw $msg }

# ── Rollback tracking ──────────────────────────────────────────────────────────
$_dirs  = [System.Collections.Generic.List[string]]::new()
$_files = [System.Collections.Generic.List[string]]::new()
$_ok    = $false

function Invoke-Rollback {
    if ($_ok) { return }
    Write-Warn 'Installation failed — rolling back...'
    foreach ($f in $_files)  { Remove-Item -Force $f -ErrorAction SilentlyContinue }
    $arr = $_dirs.ToArray(); [array]::Reverse($arr)
    foreach ($d in $arr)     { Remove-Item -Recurse -Force $d -ErrorAction SilentlyContinue }
    Write-Warn 'Rollback complete. Fix the issue above and re-run.'
}

function Ensure-Dir ($path) {
    if (-not (Test-Path $path)) {
        New-Item -ItemType Directory -Path $path -Force | Out-Null
        $_dirs.Add($path)
    }
}

# ── Step 1: Python 3.10+ ───────────────────────────────────────────────────────
Write-Info 'Checking Python version...'
$py = $null
foreach ($cmd in @('python', 'python3')) {
    $py = Get-Command $cmd -ErrorAction SilentlyContinue
    if ($py) { break }
}
if (-not $py) {
    Write-Err 'python not found. Install Python 3.10+ from https://python.org and add it to PATH.'
}

$pyVer = (& $py.Source --version 2>&1) -replace 'Python ', ''
$major, $minor = ($pyVer -split '\.')[0..1]
if ([int]$major -lt 3 -or ([int]$major -eq 3 -and [int]$minor -lt 10)) {
    Write-Err "Python 3.10+ required (found $pyVer). Please upgrade."
}
Write-Info "Python $pyVer — OK"

# ── Step 1b: Check for tkinter ────────────────────────────────────────────────
Write-Info 'Checking for tkinter...'
& $py.Source -c 'import tkinter' 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    # Microsoft Store Python ships without tkinter.
    if ($py.Source -like '*WindowsApps*') {
        Write-Host ''
        Write-Warn 'Python from the Microsoft Store does not include tkinter.'
        Write-Warn 'The Settings GUI requires tkinter. To fix this:'
        Write-Warn '  1. Uninstall Python from the Microsoft Store.'
        Write-Warn '  2. Install Python 3.10+ from https://python.org'
        Write-Warn '     (keep "tcl/tk and IDLE" checked — it is on by default).'
        Write-Warn '  3. Re-run this installer.'
        Write-Host ''
        Write-Warn 'Continuing installation — Settings GUI will not work until you switch to python.org Python.'
    } else {
        Write-Host ''
        Write-Warn 'tkinter is not available with your Python installation.'
        Write-Warn 'Reinstall Python 3.10+ from https://python.org'
        Write-Warn 'During install, ensure "tcl/tk and IDLE" is checked (it is on by default).'
        Write-Host ''
        Write-Warn 'Continuing installation — Settings GUI will not work until tkinter is available.'
    }
} else {
    Write-Info 'tkinter — OK'
}

# Prefer pythonw.exe (no console window) for background daemon/tray.
$pythonw = Join-Path (Split-Path $py.Source) 'pythonw.exe'
if (-not (Test-Path $pythonw)) { $pythonw = $py.Source }

# ── Step 2: Install Python dependencies ────────────────────────────────────────
Write-Info 'Installing Python dependencies...'
try {
    & $py.Source -m pip install -r "$ScriptRoot\requirements.txt" --user -q
    if ($LASTEXITCODE -ne 0) { throw "pip exited with $LASTEXITCODE" }
} catch {
    Invoke-Rollback
    Write-Err "pip install failed: $_"
}
Write-Info 'Dependencies installed.'

# ── Step 3: Copy daemon library ────────────────────────────────────────────────
Write-Info "Installing daemon to: $PKG_DIR"
try {
    Ensure-Dir $LIB_DIR
    Ensure-Dir $PKG_DIR
    Copy-Item -Recurse -Force "$ScriptRoot\daemon\*" $PKG_DIR
} catch {
    Invoke-Rollback
    Write-Err "Failed to copy daemon files: $_"
}
Write-Info 'Daemon library installed.'

# ── Step 4: Copy GUI modules ───────────────────────────────────────────────────
Copy-Item "$ScriptRoot\gui\settings.py" (Join-Path $PKG_DIR 'settings_gui.py') -Force
Copy-Item "$ScriptRoot\gui\tray.py"     (Join-Path $PKG_DIR 'tray.py')         -Force

# ── Step 5: Copy example config ────────────────────────────────────────────────
Ensure-Dir $CONFIG_DIR
$cfgFile = Join-Path $CONFIG_DIR 'config.toml'
if (-not (Test-Path $cfgFile)) {
    Copy-Item "$ScriptRoot\config.example.toml" $cfgFile
    $_files.Add($cfgFile)
    Write-Info "Created config: $cfgFile"
    Write-Info "  Edit $cfgFile to set your monthly budgets."
} else {
    Write-Warn "Config already exists, skipping: $cfgFile"
}

# ── Step 6: Create launcher scripts ────────────────────────────────────────────
Write-Info "Creating launchers in: $BIN_DIR"
Ensure-Dir $BIN_DIR

# Daemon — hidden background process via pythonw.exe
$daemonBat = Join-Path $BIN_DIR 'llm-usage-indicator.bat'
"@echo off`r`nset `"PYTHONPATH=$LIB_DIR`"`r`nstart `"`" /b `"$pythonw`" -m llm_usage_indicator.main %*`r`n" |
    Set-Content $daemonBat -Encoding ASCII
$_files.Add($daemonBat)

# Tray — hidden background process
$trayBat = Join-Path $BIN_DIR 'llm-usage-indicator-tray.bat'
"@echo off`r`nset `"PYTHONPATH=$LIB_DIR`"`r`nstart `"`" /b `"$pythonw`" -m llm_usage_indicator.tray %*`r`n" |
    Set-Content $trayBat -Encoding ASCII
$_files.Add($trayBat)

# Settings — normal console / GUI window
$settingsBat = Join-Path $BIN_DIR 'llm-usage-indicator-settings.bat'
"@echo off`r`nset `"PYTHONPATH=$LIB_DIR`"`r`n`"$($py.Source)`" -m llm_usage_indicator.settings_gui %*`r`n" |
    Set-Content $settingsBat -Encoding ASCII
$_files.Add($settingsBat)

Write-Info 'Launchers created.'

# ── Step 7: Add bin dir to user PATH (persistent) ──────────────────────────────
$userPath = [Environment]::GetEnvironmentVariable('PATH', 'User') ?? ''
if ($userPath -notlike "*$BIN_DIR*") {
    [Environment]::SetEnvironmentVariable('PATH', "$userPath;$BIN_DIR", 'User')
    $env:PATH += ";$BIN_DIR"
    Write-Info "Added $BIN_DIR to your PATH."
}

# ── Step 8: Register autostart via HKCU Run ────────────────────────────────────
$runKey = 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run'
Set-ItemProperty -Path $runKey -Name "$APP_NAME Daemon" -Value "`"$daemonBat`""
Set-ItemProperty -Path $runKey -Name "$APP_NAME Tray"   -Value "`"$trayBat`""
Write-Info 'Autostart registered (daemon + tray start at every login).'

# ── Step 9: Start daemon now ───────────────────────────────────────────────────
Write-Info 'Starting daemon...'
try {
    $env:PYTHONPATH = $LIB_DIR
    $proc = Start-Process -FilePath $pythonw `
        -ArgumentList '-m', 'llm_usage_indicator.main' `
        -WindowStyle Hidden -PassThru
    Write-Info "Daemon started (PID $($proc.Id))."
} catch {
    Write-Warn "Could not auto-start daemon. Run manually: $daemonBat"
}

# ── Done ──────────────────────────────────────────────────────────────────────
$_ok = $true
Write-Host ''
Write-Info 'Installation complete!'
Write-Host ''
Write-Host 'Next steps:'
Write-Host "  1. Edit your monthly budgets:"
Write-Host "       $cfgFile"
Write-Host ''
Write-Host '  2. Log in with Claude Code (no API key needed):'
Write-Host '       claude login'
Write-Host ''
Write-Host '  3. The tray icon starts automatically at next login.'
Write-Host "     To start it now:  $trayBat"
Write-Host ''
Write-Host "  4. Open settings:   $settingsBat"
Write-Host ''
Write-Host '  5. To uninstall, delete the Run registry entries and the folder:'
Write-Host "       $INSTALL"
Write-Host ''
