# 비밀 정보 관리 규칙

> **로드 시점**: 커밋·푸시·파일 작성·settings.json 수정 시 (lazy load)

---

## §1 비밀 파일 패턴 (탐지 대상)

### 파일명 패턴

| 패턴 | 설명 |
|------|------|
| `.env`, `.env.*` | 환경 변수 파일 |
| `*.key` | 개인키·API 키 파일 |
| `credentials.json` | 자격증명 파일 (GCP, AWS 등) |
| `id_rsa`, `id_ed25519`, `*.pem` | SSH·TLS 개인키 |
| `secrets.yaml`, `secrets.json` | 비밀 설정 파일 |
| `*.p12`, `*.pfx` | 인증서 파일 |
| `token.json`, `auth.json` | 토큰 저장 파일 |
| `serviceAccountKey.json` | GCP 서비스 계정 키 |
| `.npmrc`, `.pypirc` | 패키지 레지스트리 자격증명 포함 가능 |

### 텍스트 내 API 키 패턴 (정규식)

```
# 범용 API 키 패턴
[A-Z_]*_API_KEY\s*[:=]\s*['"][\w\-]{20,}['"]
[A-Z_]*_SECRET\s*[:=]\s*['"][\w\-]{20,}['"]
[A-Z_]*_TOKEN\s*[:=]\s*['"][\w\-]{20,}['"]

# AWS
AKIA[0-9A-Z]{16}                          # AWS Access Key ID
[0-9a-zA-Z/+]{40}                         # AWS Secret Access Key (context 필요)

# OpenAI
sk-[a-zA-Z0-9]{20,}                       # OpenAI API Key

# Anthropic
sk-ant-[a-zA-Z0-9\-_]{40,}               # Anthropic API Key

# Mem0
m0-[a-zA-Z0-9]{20,}                      # Mem0 API Key

# Tavily
tvly-[a-zA-Z0-9]{20,}                    # Tavily API Key

# GitHub
ghp_[a-zA-Z0-9]{36}                      # GitHub Personal Access Token
github_pat_[a-zA-Z0-9_]{82}              # GitHub Fine-grained PAT

# Google
AIza[0-9A-Za-z\-_]{35}                   # Google API Key

# Slack
xoxb-[0-9]{11}-[0-9]{11}-[a-zA-Z0-9]{24} # Slack Bot Token
xoxp-[0-9]{11}-[0-9]{11}-[0-9]{12}-[a-zA-Z0-9]{32} # Slack User Token
```

---

## §2 git commit 전 강제 스캔 절차

### 스캔 순서 (MANDATORY — commit 전 항상 실행)

```
1. 스테이징 파일 목록 확인
   → git diff --cached --name-only

2. 비밀 파일 패턴 매칭 (§1 파일명 패턴)
   → 매칭 파일 발견 시 → §3 즉시 처리 절차

3. 텍스트 내용 스캔 (§1 정규식 패턴)
   → git diff --cached | grep -E "{패턴}"
   → 매칭 내용 발견 시 → §3 즉시 처리 절차

4. gitleaks / trufflehog 사용 가능 시 (권장)
   → gitleaks detect --staged
   → trufflehog git file://. --since-commit HEAD --only-verified   # git 서브커맨드는 repo URI 필수 (file://. = 현재 repo)
   → 결과 이상 없으면 commit 진행

5. 스캔 통과 → commit 진행
```

### 도구별 실행 명령

```bash
# gitleaks (설치된 경우)
gitleaks detect --staged --no-git

# trufflehog (설치된 경우)
trufflehog git file://. --since-commit HEAD --only-verified --fail

# 수동 grep (도구 미설치 시 fallback)
git diff --cached | grep -iE \
  '(api_key|secret|password|token|private_key)\s*[:=]\s*["\047][a-zA-Z0-9\-_]{10,}'
```

---

## §3 비밀 정보 발견 시 처리 절차

### 즉시 처리 (MANDATORY)

```
1. commit / push / Write 즉시 중단
2. 사용자에게 아래 형식으로 즉시 알림:

   ⚠ 비밀 정보 감지
   파일: {파일 경로}
   패턴: {감지된 패턴 유형 — 값 자체는 출력 금지}
   위치: {줄 번호}
   조치 필요:
     1. {파일명}을 .gitignore에 추가
     2. 값을 환경 변수 또는 env-config로 분리
     3. git 이력에 이미 포함된 경우 → git filter-repo 사용 필요

3. 사용자 조치 완료 후에만 commit 재시도 허용
```

### settings.json 내 API 키 발견 시

> 유출 시크릿 제거는 **즉시 조치 예외** — CLAUDE.md 계획-승인 게이트에 우선한다(노출 시간 최소화가 보안상 우선, 값은 env-config로 이전되고 원값은 사용자가 직접 재입력하므로 가역·저위험).

```
발견 즉시:
1. commit 중단
2. settings.json에서 해당 키 값 제거 (Edit 도구 사용)
3. ~/.claude/env-config 파일에 환경 변수로 분리:
   export {KEY_NAME}="{값}" (← 사용자가 직접 입력)
4. .gitignore에 settings.json 추가 확인
5. 사용자에게 env-config에 직접 값 기입 요청
```

---

## §4 .gitignore 필수 항목

프로젝트 초기화 시 또는 비밀 파일 발견 시 .gitignore에 아래 항목 포함 여부 확인:

```gitignore
# 환경 변수 / 비밀
.env
.env.*
!.env.example

# 자격증명
credentials.json
serviceAccountKey.json
*.key
*.pem
*.p12
*.pfx
id_rsa
id_ed25519
secrets.yaml
secrets.json
token.json
auth.json

# 패키지 레지스트리 자격증명
.npmrc
.pypirc

# Claude 설정 (API 키 포함 가능)
# settings.json → 프로젝트별 판단 후 추가 여부 결정
```

---

## §5 환경 변수 분리 패턴

> **MCP 비밀 표준 (현행, 2026-06-09 결정)**: MCP 서버 비밀은 `~/.claude/mcp-secrets.env`(chmod 600) + 래퍼 스크립트(`scripts/launch-*.sh`)의 자기 프로세스 주입이 단일 표준. 아래 `env-config`는 MCP 외 일반 프로젝트 키용 legacy 패턴.

### env-config 구조 (`~/.claude/env-config`)

```bash
# Claude 에이전트 시스템 환경 변수
export MEM0_API_KEY=""
export TAVILY_API_KEY=""
export ANTHROPIC_API_KEY=""
# 프로젝트별 키는 아래에 추가
```

### 코드 내 올바른 참조 패턴

```python
# ❌ 금지: 하드코딩
API_KEY = "sk-ant-abc123..."

# ✅ 올바른 방법: 환경 변수 참조
import os
API_KEY = os.environ.get("ANTHROPIC_API_KEY")
if not API_KEY:
    raise ValueError("ANTHROPIC_API_KEY 환경 변수가 설정되지 않았습니다.")
```

```yaml
# ❌ 금지: YAML 하드코딩
api_key: "tvly-abc123..."

# ✅ 올바른 방법: 환경 변수 참조
api_key: ${TAVILY_API_KEY}
```

---

## §6 이미 커밋된 비밀 정보 처리

### 발견 시 처리 순서

```
1. 즉시 해당 API 키/비밀 무효화 (플랫폼에서 키 재발급)
2. git 이력 정리 (사용자 직접 수행 — AI 실행 금지):
   git filter-repo --path {파일명} --invert-paths
   또는
   git filter-repo --replace-text <(echo "{키 값}==>REDACTED")
3. 원격 저장소 force push (사용자 직접 + 팀 협의 후):
   git push --force --all origin
4. 팀원 전체에게 알림 + 로컬 재클론 요청
5. .gitignore 업데이트 후 재커밋
```

**AI가 직접 실행 금지**: `git filter-repo`, `git push --force` — 반드시 사용자 직접 수행

---

## §7 절대 금지 사항 (MANDATORY)

| 금지 행위 | 이유 |
|----------|------|
| 비밀 정보 포함 파일 commit | 공개 저장소 노출 위험 |
| API 키 평문 settings.json 저장 | git 이력에 영구 기록 |
| 비밀 정보 포함 파일 push (private 포함) | 내부 유출 위험 |
| 감지된 키 값 로그/보고서에 출력 | 노출 증폭 |
| 스캔 생략 후 commit | 탐지 우회 |
| AI가 실제 키 값을 생성·제안 | 가짜 키 혼용 위험 |
| git filter-repo / force push AI 직접 실행 | 되돌릴 수 없는 git 이력 파괴 |

---

## §8 연관 규칙

| 상황 | 참조 파일 |
|------|---------|
| git commit 절차 전체 | `~/.claude/rules/agent-routing.md` § gitops |
| 비밀 관련 에러 처리 | `~/.claude/rules-lazy/error-handling.md` § (e) CONSENT_NEEDED |
| git 롤백 필요 시 | `~/.claude/rules-lazy/rollback-procedure.md` § Git 상태 |
| 환경 설정 파일 구조 | `~/.claude/env-config` |
