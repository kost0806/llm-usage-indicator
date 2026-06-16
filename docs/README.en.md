# llm-usage-indicator

> Show Claude · Gemini · OpenAI today's spend and remaining credits in your Waybar status bar or system tray — **no API keys required**

<p align="center">
  <a href="../../../actions/workflows/release.yml">
    <img alt="Build" src="../../../actions/workflows/release.yml/badge.svg"/>
  </a>
  &nbsp;
  <a href="../README.md">한국어</a>
</p>

---

## Features

| | |
|---|---|
| **No API keys** | Works with web login only (e.g. `claude login`) |
| **Providers** | Claude · Gemini · OpenAI · Copilot (auto-detected from model name) |
| **Displays** | Today's spend ($) · remaining credits ($) · detailed tooltip |
| **Data source** | Reads local JSONL conversation logs directly (no external tools needed) |
| **Platform** | Ubuntu 22.04+ (Wayland & X11) · Windows 10+ · macOS 12+ |
| **Auto-start** | `systemd --user` service (Linux) / system tray autostart |
| **Dependencies** | Python 3.10+ |

### How it works

Reads conversation logs stored locally at `~/.claude/projects/**/*.jsonl` and similar paths, then aggregates cost by model.  
**No outbound API calls. No internet required. No API keys.**

```
~/.claude/projects/**/*.jsonl   ← Claude Code conversation logs (local)
           │
           ▼
  JsonlProvider (Python)         ← parses every 60 s, groups by provider prefix
           │
           ▼
     SQLite Store                ← 7-day snapshot history
           │
           ▼
   TCP Socket Server             ← JSON IPC (127.0.0.1:37891)
           │
           ▼
      module.sh                  ← Waybar custom/script (every 30 s)
           │
           ▼
      Waybar status bar          ← 🤖 C:$13.50 ↑$1.50  O:$7.70 ↑$0.30
```

---

## Requirements

- Ubuntu 22.04+ (any Debian-based distro) · Windows 10+ · macOS 12+
- Python 3.10+
- `python3-tk` — required for the Settings GUI (Ubuntu/Debian: `sudo apt install python3-tk`)
- [Waybar](https://github.com/Alexays/Waybar) (Linux Waybar integration only)
- Claude Code CLI logged in via `claude login`

---

## Installation

### Option 1 — Always install the latest version

Automatically downloads and installs the newest release every time you run this command.

**Linux / macOS**

```bash
curl -fsSL https://raw.githubusercontent.com/kost0806/llm-usage-indicator/main/install.sh | bash
```

**Windows (PowerShell — no admin required)**

```powershell
irm https://raw.githubusercontent.com/kost0806/llm-usage-indicator/main/install.ps1 | iex
```

---

### Option 2 — Install a specific version

Use this when you need to pin a version for reproducible deployments or rollbacks.  
Check the [Releases page](../../releases) for available version tags (e.g. `v1.2.3`).

**Linux / macOS**

```bash
# Replace v1.2.3 with the desired version tag
curl -fsSL https://github.com/kost0806/llm-usage-indicator/releases/download/v1.2.3/install.sh | bash
```

**Windows (PowerShell)**

```powershell
# Replace v1.2.3 with the desired version tag
irm https://github.com/kost0806/llm-usage-indicator/releases/download/v1.2.3/install.ps1 | iex
```

**Install from tarball (Linux / macOS)**

```bash
VERSION=1.2.3
curl -LO "https://github.com/kost0806/llm-usage-indicator/releases/download/v${VERSION}/llm-usage-indicator-${VERSION}.tar.gz"
tar -xzf "llm-usage-indicator-${VERSION}.tar.gz"
cd "llm-usage-indicator-${VERSION}"
bash install.sh
```

Verify checksum (optional):

```bash
curl -LO "https://github.com/kost0806/llm-usage-indicator/releases/download/v${VERSION}/llm-usage-indicator-${VERSION}.tar.gz.sha256"
sha256sum -c "llm-usage-indicator-${VERSION}.tar.gz.sha256"
```

---

### Option 3 — Install from source

```bash
git clone https://github.com/kost0806/llm-usage-indicator.git
cd llm-usage-indicator
bash install.sh
```

---

## Configuration

Config file: `~/.config/llm-usage-indicator/config.toml`

```toml
[general]
poll_interval = 60          # how often to parse JSONL logs (seconds)
ipc_host      = "127.0.0.1"
ipc_port      = 37891
db_path       = ""          # empty = platform default path

# Monthly credit budgets in USD — used to calculate remaining balance
[budgets]
claude = 20.00
gemini = 15.00
openai = 10.00
```

**Providers are detected automatically from the model name prefix:**

| Model prefix | Provider |
|---|---|
| `claude-*` | Claude |
| `gemini-*` | Gemini |
| `gpt-*`, `o1-*`, `o3-*`, `o4-*` | OpenAI |
| `copilot-*` | Copilot |

After editing the config, restart the daemon:

```bash
systemctl --user restart llm-usage-indicator
```

---

## Waybar Integration (Linux)

### 1. Add the module to your config

`~/.config/waybar/config`:

```json
"custom/llm-monitor": {
    "exec": "~/.config/waybar/scripts/llm-monitor.sh",
    "return-type": "json",
    "interval": 30,
    "on-click": "notify-send 'LLM Credits' \"$(~/.config/waybar/scripts/llm-monitor.sh --detail)\""
}
```

Add `"custom/llm-monitor"` to your module position:

```json
"modules-right": ["custom/llm-monitor", "clock"]
```

### 2. Optional CSS styling

`~/.config/waybar/style.css`:

```css
#custom-llm-monitor {
    color: #cdd6f4;
    padding: 0 8px;
}

#custom-llm-monitor.llm-monitor-error {
    color: #f38ba8;
}
```

### 3. Restart Waybar

```bash
pkill waybar && waybar &
```

---

## Usage

### Daemon management

```bash
systemctl --user status llm-usage-indicator   # check status
systemctl --user restart llm-usage-indicator  # restart
systemctl --user stop llm-usage-indicator     # stop
```

### View logs

```bash
journalctl --user -u llm-usage-indicator -f
```

### Query the socket directly

```bash
python3 -c "
import socket, json
s = socket.create_connection(('127.0.0.1', 37891))
s.sendall(b'{\"cmd\":\"status\"}\n')
print(json.dumps(json.loads(s.recv(65536)), indent=2))
s.close()
"
```

Example response:

```json
{
  "providers": [
    {
      "name": "Claude",
      "budget_usd": 20.00,
      "spent_total": 6.50,
      "spent_today": 1.50,
      "remaining": 13.50,
      "remaining_pct": 67.5,
      "updated_at": 1749888000
    }
  ],
  "total_remaining": 13.50,
  "total_spent_today": 1.50,
  "server_time": 1749888060
}
```

---

## Troubleshooting

### Waybar shows `🤖 --`

```bash
systemctl --user status llm-usage-indicator
journalctl --user -u llm-usage-indicator -n 30
```

### Usage shows zero

Usage will be zero if you haven't had any Claude Code conversations yet.

```bash
ls ~/.claude/projects/
```

### Daemon won't start

```bash
~/.local/bin/llm-usage-indicator
```

---

## License

MIT License — free to use, modify, and distribute.

---

[🇰🇷 한국어 README →](../README.md)
