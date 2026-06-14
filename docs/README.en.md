# llm-credit-monitor

> Show Claude · Gemini · OpenAI today's spend and remaining credits in your Waybar status bar — **no API keys required**

<p align="center">
  <a href="../../../actions/workflows/release.yml">
    <img alt="Build" src="../../../actions/workflows/release.yml/badge.svg"/>
  </a>
  <a href="../README.md">한국어</a>
</p>

---

## Features

| | |
|---|---|
| **No API keys** | Works with web login only (e.g. `claude login`) |
| **Providers** | Claude · Gemini · OpenAI · Copilot (auto-detected from model name) |
| **Displays** | Today's spend ($) · remaining credits ($) · detailed tooltip |
| **Data source** | [ccusage](https://github.com/ryoppippi/ccusage) — reads local JSONL conversation logs |
| **Platform** | Ubuntu 22.04+ (Wayland & X11) |
| **Auto-start** | `systemd --user` service |
| **Dependencies** | Python 3.10+, Node.js 18+, `aiosqlite` |

### How it works

ccusage reads conversation logs stored locally at `~/.claude/projects/**/*.jsonl` and similar paths, then aggregates cost by model.  
**No outbound API calls. No internet required. No API keys.**

```
~/.claude/projects/**/*.jsonl   ← Claude Code conversation logs (local)
           │
           ▼
  npx ccusage@latest daily      ← runs every 60 seconds
           │
           ▼
    CcusageProvider              ← groups models by provider prefix
           │
           ▼
     SQLite Store                ← 7-day snapshot history
           │
           ▼
   Unix Socket Server            ← JSON IPC (/tmp/llm-monitor.sock)
           │
           ▼
      module.sh                  ← Waybar custom/script (every 30s)
           │
           ▼
      Waybar status bar          ← 🤖 C:$13.50 ↑$1.50  O:$7.70 ↑$0.30
```

---

## Requirements

- Ubuntu 22.04+ (any Debian-based distro should work)
- Python 3.10+ (for `aiosqlite`)
- Node.js 18+ with npx (for `ccusage`)
- [Waybar](https://github.com/Alexays/Waybar)
- Claude Code CLI logged in via `claude login`

---

## Quick Install

### From release tarball (recommended)

```bash
VERSION=$(curl -s https://api.github.com/repos/kost0806/llm-usage-indicator/releases/latest \
  | grep -oP '"tag_name":\s*"v\K[^"]+')

curl -LO "https://github.com/kost0806/llm-usage-indicator/releases/latest/download/llm-credit-monitor-${VERSION}.tar.gz"
tar -xzf "llm-credit-monitor-${VERSION}.tar.gz"
cd "llm-credit-monitor-${VERSION}"
bash install.sh
```

### Debian package (.deb)

```bash
VERSION=$(curl -s https://api.github.com/repos/kost0806/llm-usage-indicator/releases/latest \
  | grep -oP '"tag_name":\s*"v\K[^"]+')

curl -LO "https://github.com/kost0806/llm-usage-indicator/releases/latest/download/llm-credit-monitor-${VERSION}.deb"
sudo dpkg -i "llm-credit-monitor-${VERSION}.deb"
pip install aiosqlite --user
```

### From source

```bash
git clone https://github.com/kost0806/llm-usage-indicator.git
cd llm-usage-indicator
bash install.sh
```

---

## Configuration

Config file: `~/.config/llm-credit-monitor/config.toml`

```toml
[general]
poll_interval = 60                       # how often to run ccusage (seconds)
socket_path   = "/tmp/llm-monitor.sock"
db_path       = "~/.local/share/llm-credit-monitor/data.db"
ccusage_cmd   = "npx ccusage@latest"     # ccusage command (override if needed)

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
systemctl --user restart llm-credit-monitor
```

---

## Manual Install

```bash
# 1. Install Python dependency
pip install aiosqlite --user

# 2. Copy config
mkdir -p ~/.config/llm-credit-monitor
cp config.example.toml ~/.config/llm-credit-monitor/config.toml
chmod 600 ~/.config/llm-credit-monitor/config.toml

# 3. Install daemon library
mkdir -p ~/.local/lib/llm-credit-monitor
cp -r daemon/* ~/.local/lib/llm-credit-monitor/

# 4. Create launcher wrapper
mkdir -p ~/.local/bin
cat > ~/.local/bin/llm-credit-monitor << 'WRAP'
#!/usr/bin/env bash
PYTHONPATH="$HOME/.local/lib/llm-credit-monitor" exec python3 -c "
import sys; sys.path.insert(0, '$HOME/.local/lib/llm-credit-monitor')
from main import main; main()
" "$@"
WRAP
chmod +x ~/.local/bin/llm-credit-monitor

# 5. Register systemd user service
mkdir -p ~/.config/systemd/user
cp systemd/llm-credit-monitor.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now llm-credit-monitor

# 6. Install Waybar script
mkdir -p ~/.config/waybar/scripts
cp waybar/module.sh ~/.config/waybar/scripts/llm-monitor.sh
chmod +x ~/.config/waybar/scripts/llm-monitor.sh
```

---

## Waybar Integration

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
systemctl --user status llm-credit-monitor   # check status
systemctl --user restart llm-credit-monitor  # restart
systemctl --user stop llm-credit-monitor     # stop
```

### View logs

```bash
journalctl --user -u llm-credit-monitor -f
# or directly:
tail -f ~/.local/share/llm-credit-monitor/monitor.log
```

### Query the socket directly

```bash
python3 -c "
import socket, json
with socket.socket(socket.AF_UNIX) as s:
    s.connect('/tmp/llm-monitor.sock')
    s.sendall(b'{\"cmd\":\"status\"}\n')
    print(json.dumps(json.loads(s.recv(65536)), indent=2))
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

### Debug ccusage directly

```bash
npx ccusage@latest daily --json | python3 -m json.tool
```

---

## Troubleshooting

### Waybar shows `🤖 --`

```bash
# Is the daemon running?
systemctl --user status llm-credit-monitor

# Does the socket exist?
ls -la /tmp/llm-monitor.sock

# Check logs for errors
journalctl --user -u llm-credit-monitor -n 30
```

### ccusage shows no data

```bash
# Run ccusage directly
npx ccusage@latest daily

# Check that conversation logs exist
ls ~/.claude/projects/
```

Usage will be zero if you haven't had any Claude Code conversations yet.

### Node.js / npx not found

```bash
# Ubuntu/Debian
sudo apt install nodejs npm

# Or via nvm
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
nvm install 22
```

If npx is installed at a non-standard path, set the full path in config:

```toml
ccusage_cmd = "/usr/local/bin/npx ccusage@latest"
```

### Daemon won't start

```bash
# Run directly to see the error
~/.local/bin/llm-credit-monitor
```

---

## License

MIT License — free to use, modify, and distribute.

---

[🇰🇷 한국어 README →](../README.md)
