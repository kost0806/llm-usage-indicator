# llm-credit-monitor

> **API 키 없이** Claude · Gemini · OpenAI 오늘 사용액과 잔여 크레딧을 Waybar 상태바에 표시

<p align="center">
  <a href="../../actions/workflows/release.yml">
    <img alt="Build" src="../../actions/workflows/release.yml/badge.svg"/>
  </a>
  <a href="docs/README.en.md">English</a>
</p>

---

## 특징

| | |
|---|---|
| **API 키 불필요** | 웹 로그인(claude login 등)만으로 동작 |
| **지원 Provider** | Claude · Gemini · OpenAI · Copilot (모델 이름으로 자동 감지) |
| **표시 정보** | 오늘 사용액($) · 잔여 크레딧($) · 툴팁에 상세 내역 |
| **데이터 소스** | [ccusage](https://github.com/ryoppippi/ccusage) — 로컬 JSONL 대화 기록 집계 |
| **플랫폼** | Ubuntu 22.04+ (Wayland / X11) |
| **자동 시작** | `systemd --user` 서비스 |
| **의존성** | Python 3.10+, Node.js 18+, `aiosqlite` |

### 동작 방식

ccusage가 `~/.claude/projects/**/*.jsonl` 등 로컬에 저장된 CLI 대화 기록을 읽어 사용량을 집계합니다.  
**외부 API 호출 없음 — 인터넷 불필요, API 키 불필요.**

```
~/.claude/projects/**/*.jsonl   ← Claude Code 대화 기록 (로컬)
           │
           ▼
  npx ccusage@latest daily      ← 60초마다 실행
           │
           ▼
    CcusageProvider              ← 모델명으로 provider 자동 분류
           │
           ▼
     SQLite Store                ← 7일치 스냅샷 보관
           │
           ▼
   Unix Socket Server            ← JSON IPC (/tmp/llm-monitor.sock)
           │
           ▼
      module.sh                  ← Waybar custom/script (30초마다)
           │
           ▼
       Waybar 상태바              ← 🤖 C:$13.50 ↑$1.50  O:$7.70 ↑$0.30
```

---

## 요구 사항

- Ubuntu 22.04+ (Debian 계열 권장)
- Python 3.10 이상 (`aiosqlite` 설치용)
- Node.js 18 이상 + npx (`ccusage` 실행용)
- [Waybar](https://github.com/Alexays/Waybar)
- Claude Code CLI (`claude login`으로 로그인된 상태)

---

## 빠른 설치

### 릴리스 tarball (권장)

```bash
VERSION=$(curl -s https://api.github.com/repos/kost0806/llm-usage-indicator/releases/latest \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'][1:])")

curl -LO "https://github.com/kost0806/llm-usage-indicator/releases/latest/download/llm-credit-monitor-${VERSION}.tar.gz"
tar -xzf "llm-credit-monitor-${VERSION}.tar.gz"
cd "llm-credit-monitor-${VERSION}"
bash install.sh
```

### Debian 패키지 (.deb)

```bash
VERSION=$(curl -s https://api.github.com/repos/kost0806/llm-usage-indicator/releases/latest \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'][1:])")

curl -LO "https://github.com/kost0806/llm-usage-indicator/releases/latest/download/llm-credit-monitor-${VERSION}.deb"
sudo dpkg -i "llm-credit-monitor-${VERSION}.deb"
pip install aiosqlite --user
```

### 소스에서 설치

```bash
git clone https://github.com/kost0806/llm-usage-indicator.git
cd llm-usage-indicator
bash install.sh
```

---

## 설정

설정 파일 위치: `~/.config/llm-credit-monitor/config.toml`

```toml
[general]
poll_interval = 60                       # ccusage 실행 주기 (초)
socket_path   = "/tmp/llm-monitor.sock"
db_path       = "~/.local/share/llm-credit-monitor/data.db"
ccusage_cmd   = "npx ccusage@latest"     # ccusage 실행 명령

# 월별 크레딧 예산 (USD) — 잔여 크레딧 계산에 사용
[budgets]
claude = 20.00
gemini = 15.00
openai = 10.00
```

**provider는 모델 이름 prefix로 자동 감지됩니다:**

| 모델 prefix | 분류 |
|---|---|
| `claude-*` | Claude |
| `gemini-*` | Gemini |
| `gpt-*`, `o1-*`, `o3-*`, `o4-*` | OpenAI |
| `copilot-*` | Copilot |

설정 변경 후 데몬 재시작:

```bash
systemctl --user restart llm-credit-monitor
```

---

## 수동 설치

```bash
# 1. 의존성 설치
pip install aiosqlite --user

# 2. 설정 파일 복사
mkdir -p ~/.config/llm-credit-monitor
cp config.example.toml ~/.config/llm-credit-monitor/config.toml
chmod 600 ~/.config/llm-credit-monitor/config.toml

# 3. 데몬 라이브러리 설치
mkdir -p ~/.local/lib/llm-credit-monitor
cp -r daemon/* ~/.local/lib/llm-credit-monitor/

# 4. 실행 wrapper 생성
mkdir -p ~/.local/bin
cat > ~/.local/bin/llm-credit-monitor << 'WRAP'
#!/usr/bin/env bash
PYTHONPATH="$HOME/.local/lib/llm-credit-monitor" exec python3 -c "
import sys; sys.path.insert(0, '$HOME/.local/lib/llm-credit-monitor')
from main import main; main()
" "$@"
WRAP
chmod +x ~/.local/bin/llm-credit-monitor

# 5. systemd 서비스 등록
mkdir -p ~/.config/systemd/user
cp systemd/llm-credit-monitor.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now llm-credit-monitor

# 6. Waybar 스크립트 설치
mkdir -p ~/.config/waybar/scripts
cp waybar/module.sh ~/.config/waybar/scripts/llm-monitor.sh
chmod +x ~/.config/waybar/scripts/llm-monitor.sh
```

---

## Waybar 연동

### 1. 모듈 설정 추가

`~/.config/waybar/config`:

```json
"custom/llm-monitor": {
    "exec": "~/.config/waybar/scripts/llm-monitor.sh",
    "return-type": "json",
    "interval": 30,
    "on-click": "notify-send 'LLM Credits' \"$(~/.config/waybar/scripts/llm-monitor.sh --detail)\""
}
```

표시 위치에도 추가:

```json
"modules-right": ["custom/llm-monitor", "clock"]
```

### 2. CSS 스타일 (선택)

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

### 3. Waybar 재시작

```bash
pkill waybar && waybar &
```

---

## 사용법

### 데몬 관리

```bash
systemctl --user status llm-credit-monitor   # 상태 확인
systemctl --user restart llm-credit-monitor  # 재시작
systemctl --user stop llm-credit-monitor     # 중지
```

### 로그 확인

```bash
journalctl --user -u llm-credit-monitor -f
# 또는
tail -f ~/.local/share/llm-credit-monitor/monitor.log
```

### 소켓으로 직접 조회

```bash
python3 -c "
import socket, json
with socket.socket(socket.AF_UNIX) as s:
    s.connect('/tmp/llm-monitor.sock')
    s.sendall(b'{\"cmd\":\"status\"}\n')
    print(json.dumps(json.loads(s.recv(65536)), indent=2, ensure_ascii=False))
"
```

응답 예시:

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

### ccusage 직접 실행 (디버그)

```bash
npx ccusage@latest daily --json | python3 -m json.tool
```

---

## 문제 해결

### Waybar에 `🤖 --`만 표시되는 경우

```bash
# 데몬 실행 중인지 확인
systemctl --user status llm-credit-monitor

# 소켓 존재 확인
ls -la /tmp/llm-monitor.sock

# 로그에서 에러 확인
journalctl --user -u llm-credit-monitor -n 30
```

### ccusage가 데이터를 반환하지 않는 경우

```bash
# ccusage 직접 실행해서 확인
npx ccusage@latest daily

# Claude Code 대화 기록이 있는지 확인
ls ~/.claude/projects/
```

Claude Code로 대화한 기록이 없으면 사용량이 0으로 표시됩니다.

### Node.js / npx가 없는 경우

```bash
# Ubuntu/Debian
sudo apt install nodejs npm

# 또는 nvm 사용
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
nvm install 22
```

Node.js 설치 후 config의 `ccusage_cmd` 경로를 npx 전체 경로로 지정할 수도 있습니다:

```toml
ccusage_cmd = "/usr/bin/npx ccusage@latest"
```

### 데몬이 시작되지 않는 경우

```bash
# 직접 실행하여 에러 확인
~/.local/bin/llm-credit-monitor
```

---

## 라이선스

MIT License

---

[🇬🇧 English README →](docs/README.en.md)
