# llm-credit-monitor

> **Claude · Gemini · OpenAI 크레딧 잔액, 오늘 사용량, TPS를 Waybar 상태바에 실시간 표시**

<p align="center">
  <img alt="Waybar 표시 예시" src="docs/preview.png" width="700"/>
</p>

<p align="center">
  <a href="../../actions/workflows/release.yml">
    <img alt="Build" src="../../actions/workflows/release.yml/badge.svg"/>
  </a>
  <a href="../../releases/latest">
    <img alt="Latest release" src="../../releases/latest/download/badge.svg" onerror="this.style.display='none'"/>
  </a>
  <a href="docs/README.en.md">English</a>
</p>

---

## 목차

1. [특징](#특징)
2. [요구 사항](#요구-사항)
3. [빠른 설치](#빠른-설치)
4. [수동 설치](#수동-설치)
5. [설정](#설정)
6. [Waybar 연동](#waybar-연동)
7. [사용법](#사용법)
8. [동작 방식](#동작-방식)
9. [TPS 측정](#tps-측정)
10. [문제 해결](#문제-해결)
11. [라이선스](#라이선스)

---

## 특징

| 항목 | 내용 |
|---|---|
| **지원 Provider** | Claude (Anthropic) · Gemini (Google AI) · OpenAI |
| **표시 정보** | 크레딧 잔액 · 오늘 사용액($) · TPS (Tokens/sec) |
| **메모리 사용량** | 상주 데몬 **10MB 이하** |
| **플랫폼** | Ubuntu 22.04+ (Wayland / X11) |
| **자동 시작** | `systemd --user` 서비스 |
| **내결함성** | API 실패 시 캐시값 유지, 데몬 무중단 |
| **의존성** | Python 3.10+, `aiohttp`, `aiosqlite` (3개 뿐) |

---

## 요구 사항

- Ubuntu 22.04 이상 (Debian 계열 권장)
- Python 3.10 이상
- [Waybar](https://github.com/Alexays/Waybar) (Wayland/X11 상태바)
- 인터넷 연결 (각 provider API 호출용)

---

## 빠른 설치

### 릴리스 tarball로 설치 (권장)

```bash
# 1. 최신 릴리스 다운로드
VERSION=$(curl -s https://api.github.com/repos/kost0806/ca-usage-indicator/releases/latest \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'][1:])")

curl -LO "https://github.com/kost0806/ca-usage-indicator/releases/latest/download/llm-credit-monitor-${VERSION}.tar.gz"

# 2. 무결성 검증 (선택사항)
curl -LO "https://github.com/kost0806/ca-usage-indicator/releases/latest/download/llm-credit-monitor-${VERSION}.tar.gz.sha256"
sha256sum -c "llm-credit-monitor-${VERSION}.tar.gz.sha256"

# 3. 압축 해제 후 설치
tar -xzf "llm-credit-monitor-${VERSION}.tar.gz"
cd "llm-credit-monitor-${VERSION}"
bash install.sh
```

### Debian 패키지(.deb)로 설치

```bash
VERSION=$(curl -s https://api.github.com/repos/kost0806/ca-usage-indicator/releases/latest \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'][1:])")

curl -LO "https://github.com/kost0806/ca-usage-indicator/releases/latest/download/llm-credit-monitor-${VERSION}.deb"
sudo dpkg -i "llm-credit-monitor-${VERSION}.deb"

# deb는 pip 의존성을 자동 설치하지 않으므로 별도 실행
pip install aiohttp aiosqlite --user
```

### 소스에서 설치

```bash
git clone https://github.com/kost0806/ca-usage-indicator.git
cd ca-usage-indicator
bash install.sh
```

---

## 수동 설치

`install.sh`가 아닌 단계별 수동 설치를 원하는 경우:

```bash
# 1. 의존성 설치
pip install aiohttp aiosqlite --user

# 2. 설정 디렉토리 생성 및 설정 파일 복사
mkdir -p ~/.config/llm-credit-monitor
cp config.example.toml ~/.config/llm-credit-monitor/config.toml
chmod 600 ~/.config/llm-credit-monitor/config.toml

# 3. 데몬 라이브러리 설치
mkdir -p ~/.local/lib/llm-credit-monitor
cp -r daemon/* ~/.local/lib/llm-credit-monitor/

# 4. 실행 wrapper 생성
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

## 설정

설정 파일 위치: `~/.config/llm-credit-monitor/config.toml`

```toml
[general]
poll_interval_credits = 300   # 크레딧 잔액 폴링 주기 (초)
poll_interval_usage   = 60    # 사용량 폴링 주기 (초)
waybar_refresh        = 30    # Waybar 갱신 주기 (초)
socket_path           = "/tmp/llm-monitor.sock"
db_path               = "~/.local/share/llm-credit-monitor/data.db"

[providers.claude]
enabled    = true
api_key    = "sk-ant-..."     # Anthropic API 키
budget_usd = 20.00            # 구매한 총 크레딧 금액

[providers.gemini]
enabled    = true
api_key    = "AIza..."        # Google AI API 키
budget_usd = 15.00

[providers.openai]
enabled    = true
api_key    = "sk-..."         # OpenAI API 키
budget_usd = 10.00            # credit_grants API가 없는 경우 사용
```

> **보안:** 설정 파일은 `chmod 600`으로 자동 생성됩니다.
> API 키는 환경변수로도 전달 가능합니다:
> `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `OPENAI_API_KEY`

설정 변경 후 데몬 재시작:

```bash
systemctl --user restart llm-credit-monitor
```

---

## Waybar 연동

### 1. Waybar 설정에 모듈 추가

`~/.config/waybar/config` 에 다음을 추가합니다:

```json
"custom/llm-monitor": {
    "exec": "~/.config/waybar/scripts/llm-monitor.sh",
    "return-type": "json",
    "interval": 30,
    "on-click": "notify-send 'LLM Credits' \"$(~/.config/waybar/scripts/llm-monitor.sh --detail)\""
}
```

모듈을 표시할 위치(`modules-left` / `modules-center` / `modules-right`)에도 추가:

```json
"modules-right": ["custom/llm-monitor", "clock", ...]
```

### 2. 스타일 커스텀 (선택사항)

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

### 데몬 상태 확인

```bash
systemctl --user status llm-credit-monitor
```

### 로그 확인

```bash
journalctl --user -u llm-credit-monitor -f
# 또는 직접 로그 파일
tail -f ~/.local/share/llm-credit-monitor/monitor.log
```

### 소켓으로 직접 조회

```bash
# 상태 조회
python3 -c "
import socket, json
with socket.socket(socket.AF_UNIX) as s:
    s.connect('/tmp/llm-monitor.sock')
    s.sendall(b'{\"cmd\":\"status\"}\n')
    print(json.dumps(json.loads(s.recv(65536)), indent=2, ensure_ascii=False))
"
```

### TPS 값 외부에서 push

LLM 요청을 직접 보내는 스크립트에서 TPS를 측정하여 데몬에 전달할 수 있습니다:

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

### 데몬 중지/재시작

```bash
systemctl --user stop llm-credit-monitor
systemctl --user restart llm-credit-monitor
```

---

## 동작 방식

```
┌─────────────────────────────────────────────┐
│              llm-credit-monitor              │
│                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │  Claude  │  │  Gemini  │  │  OpenAI  │  │  ← asyncio 병렬 폴링
│  │ Provider │  │ Provider │  │ Provider │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  │
│       │              │              │         │
│       └──────────────┴──────────────┘         │
│                      │                        │
│              ┌───────▼────────┐               │
│              │  SQLite Store  │               │  ← 스냅샷 + TPS 이벤트
│              └───────┬────────┘               │
│                      │                        │
│              ┌───────▼────────┐               │
│              │  Unix Socket   │               │  ← JSON IPC
│              │    Server      │               │
│              └───────┬────────┘               │
└──────────────────────┼────────────────────────┘
                       │
              ┌────────▼────────┐
              │  module.sh      │  ← Waybar custom/script
              │  (30초마다 실행) │
              └────────┬────────┘
                       │
              ┌────────▼────────┐
              │    Waybar       │  ← 상태바 표시
              └─────────────────┘
```

- 각 provider는 **독립적으로** 폴링 — 하나 실패해도 나머지 정상 동작
- API 실패 시 SQLite 캐시값 반환, 표시는 `--`
- 데이터는 SQLite에 7일치 보관 후 자동 삭제
- 소켓 파일 권한 `600` (소유자만 접근)

---

## TPS 측정

TPS(Tokens Per Second)는 데몬이 직접 측정할 수 없습니다.  
두 가지 방법으로 TPS를 기록합니다:

**방법 1: 외부 push (권장)**

LLM 요청 후 응답 시간과 토큰 수를 측정하여 소켓으로 전달합니다.  
예시 — Claude 요청 wrapper:

```python
import time, socket, json

def call_claude_and_record_tps(client, **kwargs):
    t0 = time.perf_counter()
    response = client.messages.create(**kwargs)
    elapsed = time.perf_counter() - t0
    tokens = response.usage.output_tokens
    tps = tokens / elapsed if elapsed > 0 else 0

    payload = json.dumps({
        "cmd": "push_tps", "provider": "claude",
        "tps": tps, "tokens": tokens
    }) + "\n"
    with socket.socket(socket.AF_UNIX) as s:
        s.connect("/tmp/llm-monitor.sock")
        s.sendall(payload.encode())

    return response
```

**방법 2: API 응답 메타데이터**

현재 지원하는 provider 중 직접 TPS를 제공하는 공식 API는 없습니다.  
방법 1을 사용하지 않으면 TPS는 `--`로 표시됩니다.

---

## 문제 해결

### 데몬이 시작되지 않는 경우

```bash
# 로그 확인
journalctl --user -u llm-credit-monitor -n 50

# 직접 실행하여 에러 확인
~/.local/bin/llm-credit-monitor
```

### Waybar에 `🤖 --`만 표시되는 경우

```bash
# 소켓 존재 확인
ls -la /tmp/llm-monitor.sock

# 데몬 상태 확인
systemctl --user status llm-credit-monitor

# 소켓 수동 테스트
python3 -c "
import socket, json
with socket.socket(socket.AF_UNIX) as s:
    s.connect('/tmp/llm-monitor.sock')
    s.sendall(b'{\"cmd\":\"status\"}\n')
    print(s.recv(65536).decode())
"
```

### API 키 오류

```bash
# 설정 파일 확인 (권한이 600인지)
ls -la ~/.config/llm-credit-monitor/config.toml
cat ~/.config/llm-credit-monitor/config.toml
```

### 크레딧이 `--`로 표시되는 경우

Claude와 Gemini는 공식 사용량 API가 없습니다.  
- **Claude:** Anthropic이 공식 usage API를 제공하지 않음 → 로컬 SQLite 추적으로 대체
- **Gemini:** Google AI Studio 사용량 API 없음 → 동일
- **OpenAI:** `/v1/dashboard/billing/credit_grants` 조회 (조직 키 필요)

크레딧을 올바르게 표시하려면 `push_tps`로 토큰 사용량을 누적 기록하거나,  
`budget_usd`와 함께 수동으로 `spent_total`을 업데이트하세요.

---

## 라이선스

MIT License — 자유롭게 사용, 수정, 배포 가능합니다.

---

[🇬🇧 English README →](docs/README.en.md)
