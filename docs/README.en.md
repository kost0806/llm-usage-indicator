# llm-credit-monitor

> **Real-time Claude · Gemini · OpenAI credit balance, daily spend, and TPS in your Waybar status bar**

<p align="center">
  <a href="../../../actions/workflows/release.yml">
    <img alt="Build" src="../../../actions/workflows/release.yml/badge.svg"/>
  </a>
  <a href="../README.md">한국어</a>
</p>

---

## Table of Contents

1. [Features](#features)
2. [Requirements](#requirements)
3. [Quick Install](#quick-install)
4. [Manual Install](#manual-install)
5. [Configuration](#configuration)
6. [Waybar Integration](#waybar-integration)
7. [Usage](#usage)
8. [How It Works](#how-it-works)
9. [TPS Measurement](#tps-measurement)
10. [Troubleshooting](#troubleshooting)
11. [License](#license)

---

## Features

| | |
|---|---|
| **Providers** | Claude (Anthropic) · Gemini (Google AI) · OpenAI |
| **Displays** | Credit balance · Today's spend ($) · TPS (tokens/sec) |
| **Memory** | Resident daemon **< 10 MB** |
| **Platform** | Ubuntu 22.04+ (Wayland & X11) |
| **Auto-start** | `systemd --user` service |
| **Resilient** | API failures use cached values; daemon never crashes |
| **Dependencies** | Python 3.10+, `aiohttp`, `aiosqlite` — nothing else |

---

## Requirements

- Ubuntu 22.04+ (any Debian-based distro should work)
- Python 3.10+
- [Waybar](https://github.com/Alexays/Waybar)
- Internet access for provider API calls

---

## Quick Install

### From release tarball (recommended)

```bash
# 1. Download latest release
VERSION=$(curl -s https://api.github.com/repos/kost0806/ca-usage-indicator/releases/latest \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'][1:])")

curl -LO "https://github.com/kost0806/ca-usage-indicator/releases/latest/download/llm-credit-monitor-${VERSION}.tar.gz"

# 2. Verify checksum (optional but recommended)
curl -LO "https://github.com/kost0806/ca-usage-indicator/releases/latest/download/llm-credit-monitor-${VERSION}.tar.gz.sha256"
sha256sum -c "llm-credit-monitor-${VERSION}.tar.gz.sha256"

# 3. Extract and install
tar -xzf "llm-credit-monitor-${VERSION}.tar.gz"
cd "llm-credit-monitor-${VERSION}"
bash install.sh
```

### Debian package (.deb)

```bash
VERSION=$(curl -s https://api.github.com/repos/kost0806/ca-usage-indicator/releases/latest \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'][1:])")

curl -LO "https://github.com/kost0806/ca-usage-indicator/releases/latest/download/llm-credit-monitor-${VERSION}.deb"
sudo dpkg -i "llm-credit-monitor-${VERSION}.deb"

# Install Python dependencies (not handled by the .deb)
pip install aiohttp aiosqlite --user
```

### From source

```bash
git clone https://github.com/kost0806/ca-usage-indicator.git
cd ca-usage-indicator
bash install.sh
```

---

## Manual Install

Step-by-step installation without `install.sh`:

```bash
# 1. Install Python dependencies
pip install aiohttp aiosqlite --user

# 2. Create config directory and copy example config
mkdir -p ~/.config/llm-credit-monitor
cp config.example.toml ~/.config/llm-credit-monitor/config.toml
chmod 600 ~/.config/llm-credit-monitor/config.toml

# 3. Install daemon library
mkdir -p ~/.local/lib/llm-credit-monitor
cp -r daemon/* ~/.local/lib/llm-credit-monitor/

# 4. Create launcher wrapper
mkdir -p ~/.local/bin
cat > ~/.local/bin/llm-credit-monitor << 'EOF'
#!/usr/bin/env bash
PYTHONPATH="$HOME/.local/lib/llm-credit-monitor" exec python3 -c "
import sys
sys.path.insert(0, '$HOME/.local/lib/llm-credit-monitor')
from main import main
main()
" "$@"
EOF
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

## Configuration

Config file: `~/.config/llm-credit-monitor/config.toml`

```toml
[general]
poll_interval_credits = 300   # Credit balance poll interval (seconds)
poll_interval_usage   = 60    # Usage poll interval (seconds)
waybar_refresh        = 30    # Waybar refresh interval (seconds)
socket_path           = "/tmp/llm-monitor.sock"
db_path               = "~/.local/share/llm-credit-monitor/data.db"

[providers.claude]
enabled    = true
api_key    = "sk-ant-..."     # Anthropic API key
budget_usd = 20.00            # Total purchased credits (manual)

[providers.gemini]
enabled    = true
api_key    = "AIza..."        # Google AI API key
budget_usd = 15.00

[providers.openai]
enabled    = true
api_key    = "sk-..."         # OpenAI API key
budget_usd = 10.00            # Used if credit_grants API is unavailable
```

> **Security:** The config file is created with `chmod 600` automatically.  
> API keys can also be passed via environment variables:  
> `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `OPENAI_API_KEY`

After editing config, restart the daemon:

```bash
systemctl --user restart llm-credit-monitor
```

---

## Waybar Integration

### 1. Add the module to your Waybar config

Add to `~/.config/waybar/config`:

```json
"custom/llm-monitor": {
    "exec": "~/.config/waybar/scripts/llm-monitor.sh",
    "return-type": "json",
    "interval": 30,
    "on-click": "notify-send 'LLM Credits' \"$(~/.config/waybar/scripts/llm-monitor.sh --detail)\""
}
```

Add `"custom/llm-monitor"` to your desired position (`modules-left` / `modules-center` / `modules-right`):

```json
"modules-right": ["custom/llm-monitor", "clock", "..."]
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

### Check daemon status

```bash
systemctl --user status llm-credit-monitor
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

### Push a TPS event externally

If you call an LLM API yourself and want to record the TPS:

```bash
python3 -c "
import socket, json
payload = json.dumps({
    'cmd': 'push_tps',
    'provider': 'claude',
    'tps': 45.2,
    'tokens': 820
})
with socket.socket(socket.AF_UNIX) as s:
    s.connect('/tmp/llm-monitor.sock')
    s.sendall((payload + '\n').encode())
    print(s.recv(1024).decode())
"
```

### Stop / restart the daemon

```bash
systemctl --user stop llm-credit-monitor
systemctl --user restart llm-credit-monitor
```

---

## How It Works

```
┌──────────────────────────────────────────────┐
│              llm-credit-monitor               │
│                                               │
│  ┌──────────┐  ┌──────────┐  ┌───────────┐  │
│  │  Claude  │  │  Gemini  │  │  OpenAI   │  │  ← asyncio parallel poll
│  │ Provider │  │ Provider │  │  Provider │  │
│  └────┬─────┘  └────┬─────┘  └─────┬─────┘  │
│       │              │               │        │
│       └──────────────┴───────────────┘        │
│                      │                        │
│             ┌────────▼────────┐               │
│             │  SQLite Store   │               │  ← snapshots + TPS events
│             └────────┬────────┘               │
│                      │                        │
│             ┌────────▼────────┐               │
│             │  Unix Socket    │               │  ← JSON IPC
│             │    Server       │               │
│             └────────┬────────┘               │
└──────────────────────┼────────────────────────┘
                       │
              ┌────────▼────────┐
              │   module.sh     │  ← Waybar custom/script
              │  (every 30s)    │
              └────────┬────────┘
                       │
              ┌────────▼────────┐
              │    Waybar       │  ← status bar display
              └─────────────────┘
```

**Key design points:**

- Each provider is polled **independently** via `asyncio.gather` — one failure doesn't affect others
- On API failure: logs a `WARNING` and returns the last cached SQLite value; displays `--`
- SQLite stores 7 days of snapshots (auto-pruned) and TPS events
- Unix socket uses `chmod 600` — owner-only access
- The `aiohttp` session is reused across all requests (not recreated per request)
- SIGTERM / SIGINT triggers a graceful shutdown: socket closed, DB flushed, session closed

---

## TPS Measurement

The daemon cannot directly measure TPS because it does not intercept real LLM requests.  
Two mechanisms are supported:

**Method 1 — External push (recommended)**

Wrap your LLM calls to measure and push TPS after each response.  
Example for Claude:

```python
import time, socket, json
import anthropic

client = anthropic.Anthropic()

def call_with_tps(model: str, messages: list, **kwargs):
    t0 = time.perf_counter()
    response = client.messages.create(model=model, messages=messages, **kwargs)
    elapsed = time.perf_counter() - t0
    tokens = response.usage.output_tokens
    tps = tokens / elapsed if elapsed > 0 else 0.0

    payload = json.dumps({
        "cmd": "push_tps", "provider": "claude",
        "tps": tps, "tokens": tokens
    }) + "\n"
    try:
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(1)
            s.connect("/tmp/llm-monitor.sock")
            s.sendall(payload.encode())
    except OSError:
        pass  # daemon not running — ignore silently

    return response
```

**Method 2 — API response metadata**

No provider currently exposes per-request TPS through a polling API.  
Without method 1, TPS displays as `--`.

---

## Troubleshooting

### Daemon won't start

```bash
journalctl --user -u llm-credit-monitor -n 50
# Or run directly to see the error:
~/.local/bin/llm-credit-monitor
```

### Waybar shows `🤖 --`

```bash
# Is the socket there?
ls -la /tmp/llm-monitor.sock

# Is the daemon running?
systemctl --user status llm-credit-monitor

# Manual socket test
python3 -c "
import socket, json
with socket.socket(socket.AF_UNIX) as s:
    s.connect('/tmp/llm-monitor.sock')
    s.sendall(b'{\"cmd\":\"status\"}\n')
    print(s.recv(65536).decode())
"
```

### Credits show `--`

Claude and Gemini do not provide official usage APIs:

- **Claude:** No public Anthropic usage endpoint → falls back to local SQLite tracking
- **Gemini:** No Google AI Studio usage API → same fallback
- **OpenAI:** Queries `/v1/dashboard/billing/credit_grants` (requires org-level API key)

Use the `push_tps` socket command to accumulate token counts, or set `budget_usd` and track spend externally.

### API key errors

```bash
# Check config file exists and has correct permissions
ls -la ~/.config/llm-credit-monitor/config.toml
# Should show: -rw------- (600)
```

---

## License

MIT License — free to use, modify, and distribute.

---

[🇰🇷 한국어 README →](../README.md)
