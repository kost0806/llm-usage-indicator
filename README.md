# llm-usage-indicator

> **API 키 없이** Claude · Gemini · OpenAI 오늘 사용액과 잔여 크레딧을 Waybar 상태바 · 시스템 트레이에 표시

<p align="center">
  <a href="../../actions/workflows/release.yml">
    <img alt="Build" src="../../actions/workflows/release.yml/badge.svg"/>
  </a>
  &nbsp;
  <a href="docs/README.en.md">English</a>
</p>

---

## 특징

| | |
|---|---|
| **API 키 불필요** | 웹 로그인(`claude login` 등)만으로 동작 |
| **지원 Provider** | Claude · Gemini · OpenAI · Copilot (모델 이름으로 자동 감지) |
| **표시 정보** | 오늘 사용액($) · 잔여 크레딧($) · 툴팁에 상세 내역 |
| **데이터 소스** | 로컬 JSONL 대화 기록 직접 파싱 (외부 도구 불필요) |
| **플랫폼** | Ubuntu 22.04+ (Wayland / X11) · Windows 10+ · macOS 12+ |
| **자동 시작** | `systemd --user` 서비스 (Linux) / 시스템 트레이 자동 시작 |
| **의존성** | Python 3.10+ |

### 동작 방식

로컬에 저장된 CLI 대화 기록(`~/.claude/projects/**/*.jsonl`)을 직접 읽어 사용량을 집계합니다.  
**외부 API 호출 없음 — 인터넷 불필요, API 키 불필요.**

```
~/.claude/projects/**/*.jsonl   ← Claude Code 대화 기록 (로컬)
           │
           ▼
  JsonlProvider (Python)         ← 60초마다 파싱, 모델명으로 provider 자동 분류
           │
           ▼
     SQLite Store                ← 7일치 스냅샷 보관
           │
           ▼
   TCP Socket Server             ← JSON IPC (127.0.0.1:37891)
           │
           ▼
      module.sh                  ← Waybar custom/script (30초마다)
           │
           ▼
       Waybar 상태바              ← 🤖 C:$13.50 ↑$1.50  O:$7.70 ↑$0.30
```

---

## 요구 사항

- Ubuntu 22.04+ (Debian 계열 권장) · Windows 10+ · macOS 12+
- Python 3.10 이상
- `python3-tk` — Settings GUI 사용 시 필요 (Ubuntu/Debian: `sudo apt install python3-tk`)
- [Waybar](https://github.com/Alexays/Waybar) (Linux Waybar 연동 시)
- Claude Code CLI (`claude login`으로 로그인된 상태)

---

## 설치

### 방법 1 — 항상 최신 버전 설치

새 릴리스가 나올 때마다 자동으로 최신 버전을 받습니다.

**Linux / macOS**

```bash
curl -fsSL https://raw.githubusercontent.com/kost0806/llm-usage-indicator/main/install.sh | bash
```

**Windows (PowerShell — 관리자 권한 불필요)**

```powershell
irm https://raw.githubusercontent.com/kost0806/llm-usage-indicator/main/install.ps1 | iex
```

---

### 방법 2 — 특정 버전 고정 설치

버전을 고정하거나 재현 가능한 배포가 필요할 때 사용합니다.  
[Releases 페이지](../../releases)에서 원하는 버전 태그(예: `v1.2.3`)를 확인하세요.

**Linux / macOS**

```bash
# v1.2.3 자리에 원하는 버전 태그를 입력하세요
curl -fsSL https://github.com/kost0806/llm-usage-indicator/releases/download/v1.2.3/install.sh | bash
```

**Windows (PowerShell)**

```powershell
# v1.2.3 자리에 원하는 버전 태그를 입력하세요
irm https://github.com/kost0806/llm-usage-indicator/releases/download/v1.2.3/install.ps1 | iex
```

**tarball로 직접 설치 (Linux / macOS)**

```bash
VERSION=1.2.3
curl -LO "https://github.com/kost0806/llm-usage-indicator/releases/download/v${VERSION}/llm-usage-indicator-${VERSION}.tar.gz"
tar -xzf "llm-usage-indicator-${VERSION}.tar.gz"
cd "llm-usage-indicator-${VERSION}"
bash install.sh
```

체크섬 검증(선택):

```bash
curl -LO "https://github.com/kost0806/llm-usage-indicator/releases/download/v${VERSION}/llm-usage-indicator-${VERSION}.tar.gz.sha256"
sha256sum -c "llm-usage-indicator-${VERSION}.tar.gz.sha256"
```

---

### 방법 3 — 소스에서 설치

```bash
git clone https://github.com/kost0806/llm-usage-indicator.git
cd llm-usage-indicator
bash install.sh
```

---

## 설정

설정 파일 위치: `~/.config/llm-usage-indicator/config.toml`

```toml
[general]
poll_interval = 60          # JSONL 파싱 주기 (초)
ipc_host      = "127.0.0.1"
ipc_port      = 37891
db_path       = ""          # 비워두면 플랫폼 기본 경로 사용

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
systemctl --user restart llm-usage-indicator
```

---

## Waybar 연동 (Linux)

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
systemctl --user status llm-usage-indicator   # 상태 확인
systemctl --user restart llm-usage-indicator  # 재시작
systemctl --user stop llm-usage-indicator     # 중지
```

### 로그 확인

```bash
journalctl --user -u llm-usage-indicator -f
```

### TCP 소켓으로 직접 조회

```bash
python3 -c "
import socket, json
s = socket.create_connection(('127.0.0.1', 37891))
s.sendall(b'{\"cmd\":\"status\"}\n')
print(json.dumps(json.loads(s.recv(65536)), indent=2, ensure_ascii=False))
s.close()
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

---

## 문제 해결

### Waybar에 `🤖 --`만 표시되는 경우

```bash
systemctl --user status llm-usage-indicator
journalctl --user -u llm-usage-indicator -n 30
```

### 데이터가 0으로 표시되는 경우

Claude Code로 대화한 기록이 없으면 사용량이 0으로 표시됩니다.

```bash
ls ~/.claude/projects/
```

### 데몬이 시작되지 않는 경우

```bash
~/.local/bin/llm-usage-indicator
```

---

## 라이선스

MIT License

---

[🇬🇧 English README →](docs/README.en.md)
