; NSIS installer script for LLM Usage Indicator
; Requires NSIS 3.x (https://nsis.sourceforge.io)
;
; Per-user install — no admin rights required.
; Install location: %LOCALAPPDATA%\LLM Usage Indicator\
; Auto-start via: HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Run

!define APP_NAME    "LLM Usage Indicator"
!define APP_EXE_D   "llm-monitor-daemon.exe"
!define APP_EXE_T   "llm-monitor-tray.exe"
!define APP_EXE_S   "llm-monitor-settings.exe"
!define REGKEY      "SOFTWARE\LLM Usage Indicator"
!define UNINSTKEY   "SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\LLMUsageIndicator"
!define RUNKEY      "SOFTWARE\Microsoft\Windows\CurrentVersion\Run"

; Read VERSION from environment (set by CI) or default to "dev"
!ifndef VERSION
  !define VERSION "dev"
!endif

Name "${APP_NAME} ${VERSION}"
OutFile "..\LLM-Usage-Indicator-Setup-${VERSION}.exe"
Unicode True

; Per-user install — no UAC elevation needed
RequestExecutionLevel user
InstallDir "$LOCALAPPDATA\${APP_NAME}"

; Use Modern UI
!include "MUI2.nsh"
!define MUI_ABORTWARNING
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Korean"
!insertmacro MUI_LANGUAGE "English"

; ── Main install section ───────────────────────────────────────────────────────
Section "Install" SEC_MAIN
  SetOutPath "$INSTDIR"

  ; Copy all PyInstaller-bundled files
  File /r "..\dist\llm-usage-indicator\*"

  ; Copy default config (skip if already exists to preserve user settings)
  SetOutPath "$APPDATA\${APP_NAME}"
  IfFileExists "$APPDATA\${APP_NAME}\config.toml" config_exists 0
    File /oname=config.toml "..\config.example.toml"
  config_exists:

  ; Register auto-start for tray (runs on every Windows login, no UAC)
  WriteRegStr HKCU "${RUNKEY}" "${APP_NAME} Tray" \
    '"$INSTDIR\${APP_EXE_T}"'

  ; Register auto-start for daemon
  WriteRegStr HKCU "${RUNKEY}" "${APP_NAME} Daemon" \
    '"$INSTDIR\${APP_EXE_D}"'

  ; Start Menu shortcut
  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortCut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" \
    "$INSTDIR\${APP_EXE_T}" "" "$INSTDIR\${APP_EXE_T}" 0
  CreateShortCut "$SMPROGRAMS\${APP_NAME}\Settings.lnk" \
    "$INSTDIR\${APP_EXE_S}" "" "$INSTDIR\${APP_EXE_S}" 0
  CreateShortCut "$SMPROGRAMS\${APP_NAME}\Uninstall.lnk" \
    "$INSTDIR\Uninstall.exe"

  ; Registry: store install path and version for uninstaller
  WriteRegStr   HKCU "${REGKEY}" "InstallDir" "$INSTDIR"
  WriteRegStr   HKCU "${REGKEY}" "Version"    "${VERSION}"

  ; Add/Remove Programs entry
  WriteRegStr   HKCU "${UNINSTKEY}" "DisplayName"          "${APP_NAME}"
  WriteRegStr   HKCU "${UNINSTKEY}" "DisplayVersion"       "${VERSION}"
  WriteRegStr   HKCU "${UNINSTKEY}" "Publisher"            "llm-usage-indicator contributors"
  WriteRegStr   HKCU "${UNINSTKEY}" "InstallLocation"      "$INSTDIR"
  WriteRegStr   HKCU "${UNINSTKEY}" "UninstallString"      '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKCU "${UNINSTKEY}" "NoModify"             1
  WriteRegDWORD HKCU "${UNINSTKEY}" "NoRepair"             1

  WriteUninstaller "$INSTDIR\Uninstall.exe"

  ; Launch daemon and tray immediately after install
  Exec '"$INSTDIR\${APP_EXE_D}"'
  Exec '"$INSTDIR\${APP_EXE_T}"'
SectionEnd

; ── Uninstall section ─────────────────────────────────────────────────────────
Section "Uninstall"
  ; Stop running processes
  ExecWait 'taskkill /F /IM "${APP_EXE_D}" /T' $0
  ExecWait 'taskkill /F /IM "${APP_EXE_T}" /T' $0

  ; Remove auto-start registry entries
  DeleteRegValue HKCU "${RUNKEY}" "${APP_NAME} Tray"
  DeleteRegValue HKCU "${RUNKEY}" "${APP_NAME} Daemon"

  ; Remove application registry keys
  DeleteRegKey HKCU "${REGKEY}"
  DeleteRegKey HKCU "${UNINSTKEY}"

  ; Remove Start Menu shortcuts
  RMDir /r "$SMPROGRAMS\${APP_NAME}"

  ; Remove application files (leave user data in %APPDATA% intact)
  RMDir /r "$INSTDIR"
SectionEnd
