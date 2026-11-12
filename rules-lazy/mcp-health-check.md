# MCP 연결 상태 사전 점검 규칙 (MANDATORY)

> **로드 시점**: OAuth 기반 MCP 도구 호출 직전 (lazy)
> **배경**: Claude Code v2.1.x(확인일 2026-10-17, 기준 Claude Code 2.1.301) [#52565](https://github.com/anthropics/claude-code/issues/52565) 버그로 OAuth MCP는 `.credentials.json`에 accessToken이 빈 문자열로 저장됨 → 매 세션 재인증 필요

---

## 적용 대상 (OAuth 기반 MCP만)

| MCP | 적용 | 인증 방식 |
|-----|------|----------|
| `sentry` | ✅ | OAuth (HTTP) |
| `claude_ai_Atlassian` | ✅ | OAuth |
| `claude_ai_Notion` | ✅ | OAuth |
| `claude_ai_Google_Drive` | ✅ | OAuth |
| `claude_ai_YouTube_smithery` | ✅ | OAuth |
| `mem0` | ❌ | API key (env) |
| `tavily` | ❌ | API key (env) |
| `context7` | ❌ | API key |
| `scientific-papers`, `arxiv-latex-mcp` | ❌ | stdio |
| `playwright` | ❌ | local |

> API key·stdio·local 기반 MCP는 안정적이므로 점검 생략. OAuth 기반만 점검.

---

## 점검 절차 (MCP 호출 직전 — MANDATORY)

### Step 1: ToolSearch로 도구 가용성 확인

호출하려는 MCP 도구가 현재 세션에 로드 가능한지 확인:

```
ToolSearch(query="select:mcp__<server>__<tool>", max_results=1)
```

### Step 2: 결과 분류

| 결과 | 의미 | 다음 단계 |
|------|------|---------|
| 도구 정의 정상 반환 | 연결 OK | 호출 진행 |
| "no longer available" 메시지 | DISCONNECTED | Step 3 경고 |
| 빈 결과 / 미매칭 | 서버 미연결 또는 비등록 | Step 3 경고 |

### Step 3: system-reminder 보조 신호 확인

직전 system-reminder에서 다음 패턴 감지 시 즉시 DISCONNECTED 처리:
- `The following MCP servers have disconnected`
- `<server> server disconnected`
- `mcp__<server>__authenticate` 만 가용하고 일반 도구 부재

---

## 경고 형식 (DISCONNECTED 감지 시 — MANDATORY)

사용자에게 즉시 아래 형식으로 보고. 절대 우회 금지:

```
⚠️ **{MCP_NAME} MCP 연결 끊김 — 재인증 필요**

원인: Claude Code v2.1.x(확인일 2026-10-17) OAuth 영속 저장 버그 (#52565)
영향: {호출하려던 도구} 사용 불가

조치 옵션:
1. `/mcp` 명령으로 {server} 재인증 → 인증 완료 후 작업 재시도
2. 대체 도구로 우회 진행 — {대체 도구 또는 방법 명시}
3. 작업 보류

어떤 옵션으로 진행할까요?
```

### 대체 도구 매핑 (옵션 2 안내용)

| 끊긴 MCP | 대체 |
|---------|------|
| sentry | Sentry web UI 직접 확인 |
| Atlassian (Confluence/Jira) | 웹 UI 직접 작업 |
| Notion | 웹 UI 직접 작업 |
| Google Drive | 웹 UI 또는 로컬 파일 사용 |

---

## 자동 진행 금지 (MANDATORY)

- 경고 표시 없이 DISCONNECTED 상태에서 MCP 호출 시도 **금지**
- 사용자 명시적 응답(1/2/3) 후만 진행
- 옵션 2 선택 시에도 대체 도구 사용 결과 명시

---

## 점검 비용 (참고)

ToolSearch 호출 1회 = 토큰 ~200~500 (작음). 매 MCP 호출 직전 1회 추가 — 사용자 경험 향상 효과가 비용을 크게 상회.

세션당 동일 MCP 첫 호출 시만 점검, 이후는 캐싱 (직전 점검에서 OK 받은 MCP는 같은 세션 내 재점검 생략).

---

## 트러블슈팅

| 증상 | 원인 | 조치 |
|------|------|------|
| /mcp 재인증 후에도 즉시 끊김 | #52565 영속 저장 실패 | 정상 — 세션 동안만 작동, 다음 세션 재인증 필요 |
| 인증 팝업 안 뜸 | 브라우저 차단 / redirect URI 충돌 | `~/.claude/.credentials.json`에서 해당 항목 삭제 후 재시도 |
| ToolSearch에서 도구 정의는 반환되는데 호출 시 fail | 캐시된 도구 정의 (서버는 disconnected) | system-reminder 신호로 판정 우선 |

---

## 참고

- Claude Code 이슈: [#52565](https://github.com/anthropics/claude-code/issues/52565) (OAuth 토큰 미지속), [#48670](https://github.com/anthropics/claude-code/issues/48670) (auth cache 무효화)
- 영구 해결: Bearer header (API key 필요)
