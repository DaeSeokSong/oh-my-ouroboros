# Claude Code 환경 설치 가이드

이 저장소를 새 서버에 복원하고 MCP 서버를 자동으로 설치하는 방법입니다.

## 사전 요구사항

| 패키지 | 설치 명령 |
|--------|---------|
| `git` | `sudo apt install git` |
| `curl` | `sudo apt install curl` |
| `node` + `npm` | `nvm install --lts` 권장 |
| `uv` / `uvx` | `curl -Ls https://astral.sh/uv/install.sh \| sh` |
| `claude` (Claude Code CLI) | [설치 가이드](https://docs.anthropic.com/ko/docs/claude-code) |

---

## 빠른 설치

```bash
# HTTPS 방식 (권장 — SSH 키 설정 불필요)
git clone https://github.com/DaeSeokSong/.claude.git ~/.claude
bash ~/.claude/scripts/bootstrap.sh --https

# SSH 방식 (SSH 키가 GitHub에 등록된 경우 — SSH 실패 시 HTTPS 자동 폴백)
git clone git@github.com:DaeSeokSong/.claude.git ~/.claude
bash ~/.claude/scripts/bootstrap.sh
```

> `bootstrap.sh`는 idempotent — 여러 번 실행해도 안전합니다.

```bash
# bootstrap 후 머신-로컬 셋업 (플러그인 설치 + statusline 배선 — bootstrap이 안 하는 부분)
bash ~/.claude/scripts/setup-harness.sh
```

> `setup-harness.sh`도 idempotent — bootstrap(클론·settings)과 기능 분담이라 둘 다 실행 필요.

---

## bootstrap.sh 옵션

```
bash bootstrap.sh                  # 전체 설치 (SSH 시도 → 실패 시 HTTPS 폴백)
bash bootstrap.sh --https          # HTTPS 방식으로 클론 (SSH 키 없을 때)
bash bootstrap.sh --skip-mcp       # MCP 설치 건너뜀
bash bootstrap.sh --skip-plugins   # 플러그인 안내 건너뜀
```

---

## env-config (bootstrap 자동 생성)

`bootstrap.sh` STEP 0에서 선택한 환경 설정이 `~/.claude/env-config`에 저장됩니다.

| 키 | 값 | 영향 |
|----|-----|------|
| `CONFLUENCE_MCP` | `true`/`false` | `false` 시 커밋 스킬에서 Jira 이슈 연결 질문 생략 |
| `BIO_PLAUSIBILITY` | `true`/`false` | `false` 시 생물학적 타당성 검증 규칙 비활성화 |
| `DEFAULT_MODEL` | `sonnet`/`opus` (별칭 — 특정 버전 하드코딩 금지) | settings.json의 기본 모델 설정 |

수동으로 변경하려면 파일을 직접 편집하세요:
```bash
vi ~/.claude/env-config
```

---

## bootstrap.sh가 자동으로 처리하는 항목

| 단계 | 내용 |
|------|------|
| **0. MCP 사전 선택 + 환경 설정** | Atlassian·Notion 등 MCP 사전 선택 + 생물학적 타당성 검토 여부 → `env-config` 저장 |
| **1. 사전 요구사항** | git, curl, node, npm, npx, uvx, claude 설치 확인 |
| **2. 저장소 동기화** | SSH 클론 시도 → 실패 시 HTTPS 자동 폴백 (또는 `git pull`) |
| **3. 디렉토리 초기화** | `projects/` 디렉토리 생성 (`.gitignore` 제외 항목) |
| **4. MCP 설치** | context7, sentry, playwright 자동 설치 / Atlassian·Notion STEP 0 선택분 설치 |
| **5. 플러그인 확인** | settings.json의 7개 플러그인 목록 안내 |
| **6. ntfy 안내** | NTFY_TOPIC 설정 방법 안내 |

---

## 자동으로 설치되는 MCP 서버

| MCP | 용도 | 설치 방식 |
|-----|------|-----------|
| `context7` | 라이브러리 최신 문서 실시간 주입 | 자동 |
| `sentry` | 에러 트래킹 연동 | 자동 |
| `playwright` | 헤드리스 브라우저 자동화 (SSH 서버 지원) | 자동 |
| `confluence` | Confluence/Jira 연동 — **문서 자동화 추천** | STEP 0 선택 시 |
| `notion` | Notion 연동 — **문서 자동화 추천** | STEP 0 선택 시 |

> 💡 **문서 자동화 추천**: Atlassian과 Notion은 Claude Code와 연결 시 페이지 생성·수정·검색을 자동화할 수 있습니다. bootstrap 실행 시 STEP 0에서 선택하거나 아래 수동 설치 방법을 참고하세요.

---

## Confluence MCP 설정

bootstrap.sh 실행 중 confluence 설정 여부를 묻습니다. `y` 입력 시 API 키를 대화형으로 입력받아 즉시 등록합니다.

나중에 수동으로 등록하려면:

```bash
claude mcp add confluence \
  --env CONFLUENCE_URL="https://<your-domain>.atlassian.net/wiki" \
  --env CONFLUENCE_USERNAME="<your-email>" \
  --env CONFLUENCE_API_TOKEN="<your-api-token>" \
  --env JIRA_URL="https://<your-domain>.atlassian.net" \
  --env JIRA_USERNAME="<your-email>" \
  --env JIRA_API_TOKEN="<your-api-token>" \
  -- uvx mcp-atlassian
```

API 토큰 발급: https://id.atlassian.com/manage-profile/security/api-tokens

---

## Notion MCP 설정

bootstrap.sh STEP 0에서 Notion을 선택하면 자동 설정됩니다.

나중에 수동으로 등록하려면:

```bash
claude mcp add notion \
  --env NOTION_API_KEY="<your-api-key>" \
  -- npx -y @notionhq/notion-mcp-server
```

API 키 발급: https://www.notion.so/profile/integrations (새 통합 → 내부 통합 → API Key 복사)

---

## Claude Code 플러그인

`settings.json`에 등록된 7개 플러그인은 **git 저장소에 포함**되어 Claude Code 첫 실행 시 자동 활성화됩니다.

| 플러그인 | 용도 |
|---------|------|
| `example-skills@anthropic-agent-skills` | 예제 스킬 모음 |
| `superpowers@superpowers-marketplace` | 고급 워크플로우 스킬 |
| `ralph-loop@claude-plugins-official` | 테스트 반복 루프 |
| `code-simplifier@claude-plugins-official` | 코드 간소화 |
| `claude-md-management@claude-plugins-official` | CLAUDE.md 관리 |
| `claudenews@claudenews` | 개발 뉴스 statusline (coralline 체인) |
| `codex@openai-codex` | Codex CLI 연동 (rescue·second-opinion) |

네트워크 없는 환경에서 수동 설치:
```bash
claude plugin install example-skills@anthropic-agent-skills
claude plugin install superpowers@superpowers-marketplace
claude plugin install ralph-loop@claude-plugins-official
claude plugin install code-simplifier@claude-plugins-official
claude plugin install claude-md-management@claude-plugins-official
claude plugin install claudenews@claudenews
claude plugin install codex@openai-codex
```

---

## ntfy 알림 설정

```bash
# 고유 topic 이름으로 교체
sed -i 's/NTFY_TOPIC=".*"/NTFY_TOPIC="<your-unique-topic>"/' ~/.claude/scripts/claude-notify.sh
```

ntfy 앱(iOS/Android)에서 같은 topic 구독 → 완료.

---

## long-term 메모리 경로 설정

`memory-write.md`의 long-term 메모리는 `LONG_TERM_ROOT` 경로(기본값은 memory-write.md 내 명시된 canonical 경로)를 사용합니다.
새 서버에서 경로가 다를 경우 아래 중 하나를 선택하세요:

```bash
# A. memory-write.md에 명시된 canonical 경로 확인 후 디렉토리 생성
grep 'LONG_TERM_ROOT' ~/.claude/rules-lazy/memory-write.md

# B. 다른 경로 사용 시 — memory-write.md의 LONG_TERM_ROOT 기본값 직접 수정
#    (⚠️ ~/.claude/long-term 은 gitignore 처리 — 생성 금지)
```

---

## 설치 확인

```bash
claude mcp list              # MCP 서버 목록
cat ~/.claude/settings.json  # 전역 설정
ls ~/.claude/skills/         # 스킬 목록 (스킬이 /name 슬래시 진입점 제공)
ls ~/.claude/commands/       # command 전용 슬래시 (goal/loop/parallel-dispatch/ralph-loop)
ls ~/.claude/agents/         # 에이전트 목록
ls ~/.claude/rules/          # 규칙 목록
```

---

## 저장소 업데이트

```bash
cd ~/.claude && git pull
```
