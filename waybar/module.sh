#!/usr/bin/env bash
# Waybar custom/script module for llm-usage-indicator.
# Connects to the daemon's TCP server and formats provider status as JSON.
#
# Usage (normal):  called by Waybar every `interval` seconds
#         --detail: emit plain-text detail for notify-send

IPC_HOST="${LLM_MONITOR_HOST:-127.0.0.1}"
IPC_PORT="${LLM_MONITOR_PORT:-37891}"
TIMEOUT=3
TMPFILE=$(mktemp /tmp/llm-monitor-XXXXXX.json)
trap 'rm -f "$TMPFILE"' EXIT

error_output() {
    printf '{"text":"🤖 --","class":"llm-monitor-error"}\n'
    exit 0
}

# Query daemon via TCP
python3 -c "
import socket, sys
try:
    with socket.create_connection(('$IPC_HOST', int('$IPC_PORT')), timeout=$TIMEOUT) as s:
        s.sendall(b'{\"cmd\":\"status\"}\n')
        buf = b''
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
            if b'\n' in buf:
                break
    with open('$TMPFILE', 'wb') as f:
        f.write(buf.strip())
except Exception:
    sys.exit(1)
" 2>/dev/null || error_output

[ ! -s "$TMPFILE" ] && error_output

# ── --detail mode (for notify-send on-click) ──────────────────────────────────
if [ "${1:-}" = "--detail" ]; then
    python3 -c "
import json
with open('$TMPFILE') as f:
    data = json.load(f)
for p in data.get('providers', []):
    budget = p['budget_usd']
    cred = '\$%.2f' % p['remaining'] if budget > 0 else '--'
    print('%s: %s remaining (%.0f%%)' % (p['name'], cred, p['remaining_pct']))
    print('  Today: \$%.4f' % p['spent_today'])
    print()
print('Total remaining: \$%.2f' % data.get('total_remaining', 0))
print('Total today: \$%.4f' % data.get('total_spent_today', 0))
" 2>/dev/null
    exit 0
fi

# ── format output JSON for Waybar ─────────────────────────────────────────────
python3 -c "
import json
try:
    with open('$TMPFILE') as f:
        data = json.load(f)
except Exception:
    print('{\"text\":\"🤖 --\",\"class\":\"llm-monitor-error\"}')
    raise SystemExit(0)

providers = data.get('providers', [])
total_remaining = data.get('total_remaining', 0.0)
total_today = data.get('total_spent_today', 0.0)

text_parts = []
tooltip_parts = []
for p in providers:
    budget = p['budget_usd']
    cred = '\$%.2f' % p['remaining'] if budget > 0 else '--'
    today = '\$%.2f' % p['spent_today']
    text_parts.append('%s:%s ↑%s' % (p['name'][0], cred, today))
    tooltip_parts.append('%s: %s remaining (%.0f%%)\nToday: %s' % (
        p['name'], cred, p['remaining_pct'], today))

text = '🤖 ' + '  '.join(text_parts) if text_parts else '🤖 --'
tooltip_parts.append('\nTotal remaining: \$%.2f' % total_remaining)
tooltip_parts.append('Total today: \$%.2f' % total_today)

print(json.dumps({'text': text, 'tooltip': '\n'.join(tooltip_parts), 'class': 'llm-monitor'}))
" 2>/dev/null
