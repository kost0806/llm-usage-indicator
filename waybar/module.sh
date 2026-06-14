#!/usr/bin/env bash
# Waybar custom/script module for llm-credit-monitor.
# Connects to the daemon's Unix socket and formats provider status as JSON.
#
# Usage (normal):  called by Waybar every `interval` seconds
#         --detail: emit plain-text detail for notify-send

SOCKET_PATH="${LLM_MONITOR_SOCK:-/tmp/llm-monitor.sock}"
TIMEOUT=3  # seconds to wait for daemon response

# ── helpers ───────────────────────────────────────────────────────────────────

error_output() {
    printf '{"text":"🤖 --","class":"llm-monitor-error"}\n'
    exit 0
}

# Query daemon via Python (always available).
# Falls back to socat if python3 is somehow missing.
query_daemon() {
    if command -v python3 &>/dev/null; then
        python3 -c "
import socket, json, sys

sock_path = sys.argv[1]
timeout = float(sys.argv[2])

try:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect(sock_path)
        s.sendall(b'{\"cmd\":\"status\"}\n')
        buf = b''
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
            if b'\n' in buf:
                break
        print(buf.decode().strip())
except Exception as e:
    sys.exit(1)
" "$SOCKET_PATH" "$TIMEOUT" 2>/dev/null
    elif command -v socat &>/dev/null; then
        echo '{"cmd":"status"}' | timeout "$TIMEOUT" \
            socat - "UNIX-CONNECT:${SOCKET_PATH}" 2>/dev/null
    else
        return 1
    fi
}

# ── main ─────────────────────────────────────────────────────────────────────

response=$(query_daemon) || error_output

if [ -z "$response" ]; then
    error_output
fi

# ── --detail mode (for notify-send on-click) ──────────────────────────────────
if [ "${1:-}" = "--detail" ]; then
    python3 - "$response" << 'PYEOF'
import sys, json

try:
    data = json.loads(sys.argv[1])
except Exception:
    print('llm-monitor: daemon unavailable')
    sys.exit(0)

for p in data.get('providers', []):
    remaining = p['remaining']
    pct = p['remaining_pct']
    budget = p['budget_usd']
    cred_str = f"${remaining:.2f}" if budget > 0 else '--'
    print(f"{p['name']}: {cred_str} remaining ({pct:.0f}%)")
    print(f"  Today: ${p['spent_today']:.4f}")
    tps = p['last_tps']
    tps_str = f'{tps:.1f} tps' if tps > 0 else '-- tps'
    print(f'  TPS: {tps_str}')
    print()

print(f"Total remaining: ${data.get('total_remaining', 0):.2f}")
print(f"Total today: ${data.get('total_spent_today', 0):.4f}")
PYEOF
    exit 0
fi

# ── format output JSON ────────────────────────────────────────────────────────
python3 - "$response" << 'PYEOF'
import sys, json

try:
    data = json.loads(sys.argv[1])
except Exception:
    print('{"text":"🤖 --","class":"llm-monitor-error"}')
    sys.exit(0)

providers = data.get('providers', [])
total_remaining = data.get('total_remaining', 0.0)
total_today = data.get('total_spent_today', 0.0)

text_parts = []
tooltip_parts = []

for p in providers:
    name = p['name']
    short = name[0]  # C, G, O
    remaining = p['remaining']
    remaining_pct = p['remaining_pct']
    today = p['spent_today']
    tps = p['last_tps']
    budget = p['budget_usd']

    tps_str = f'~{round(tps)}tps' if tps > 0 else '~--tps'
    cred_str = f'${remaining:.2f}' if budget > 0 else '--'
    today_str = f'${today:.2f}'

    text_parts.append(f'{short}:{cred_str} ↑{today_str} {tps_str}')
    tooltip_parts.append(
        f'{name}: {cred_str} remaining ({remaining_pct:.0f}%)\nToday: {today_str}'
    )

text = '🤖 ' + '  '.join(text_parts) if text_parts else '🤖 --'
tooltip_parts.append(f'\nTotal remaining: ${total_remaining:.2f}')
tooltip_parts.append(f'Total today: ${total_today:.2f}')
tooltip = '\n'.join(tooltip_parts)

print(json.dumps({'text': text, 'tooltip': tooltip, 'class': 'llm-monitor'}))
PYEOF
