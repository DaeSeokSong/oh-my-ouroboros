# MCP Fallback 규칙 (인덱스)

> **로드 시점**: 해당 MCP 참조 시에만 개별 파일 로드
> **핵심 원칙**: MCP 불가 시 **스킵 금지** — 반드시 대체 수단으로 전환한다.

## 공통 원칙 (MANDATORY)

| 원칙 | 내용 |
|------|------|
| **스킵 금지** | "MCP가 없으니 생략" 절대 금지 — fallback 실행 필수 |
| **사용자 알림** | 첫 fallback 발생 시 1회 알림: "{MCP명} 미연결 — {대체 수단}으로 전환합니다" |
| **세션당 1회 체크** | 각 MCP 가용성은 세션당 1회 확인 (ToolSearch), 결과 캐싱. **첫 호출 실패 감지 시 1회에 한해 재체크 허용** (3팀 Round 2 합의) |
| **세션 중 재체크 허용** | 세션 중간에 MCP가 추가되면 재체크 허용 |

> 재체크 트리거: 동일 MCP 도구에서 `ToolSearch` 스키마 존재하나 호출 시 `InputValidationError`/connection error 발생

## 에이전트 spawn 시 MCP 상태 전달 (MANDATORY)

에이전트 spawn prompt 서두에 MCP 가용 상태를 포함하되, **미연결이 확인된 서버만** 표시한다(`agent-routing-mcp.md` § 에이전트 spawn prompt 서두에 포함할 2가지의 2번과 정합 — 전체 나열은 토큰 낭비, 기본값은 available 가정). 예: 특정 서버 미연결 시에만 `[MEM0: unavailable]`.

```
# 미연결 확인된 서버만 (available은 생략 — 기본 가정):
[MEM0: unavailable]   (예 — 해당 서버가 실제 미연결일 때만)
```

## MCP별 Fallback 상세

| MCP | 파일 | 주 용도 |
|-----|------|--------|
| Mem0 | `mcp-fallback-mem0.md` | 메모리 저장·검색 → 파일 기록 대체 |
| Tavily | `agents/searcher.md` § 검색 도구 Fallback 체인 (WebSearch → Tavily basic → WebFetch) + `tavily-auto.md` § 트리거 우선순위 | 웹 검색 fallback |
| Scientific Papers + arXiv LaTeX | `agents/searcher.md` § 검색 도구 Fallback 체인 — MCP 불가 시 WebFetch(arXiv API·Semantic Scholar·OpenAlex) 직접 호출 | 논문 검색 fallback |
| 논문 인용 검증 | citation-verifier 에이전트 내부에서 처리 — `agents/citation-verifier.md` (S2 429 시 OpenAlex 적극 fallback 내장) | 인용 신뢰도·철회게이트 fallback |

## 에이전트·스킬 공통 적용

- 이 규칙은 MCP를 참조하는 **모든** 규칙·스킬·에이전트에 공통 적용
- 각 규칙·스킬에서 MCP별 fallback을 별도로 정의할 필요 없음 — 개별 파일이 담당
- 에이전트 spawn 시 MCP 가용 여부를 prompt에 포함 (공통 원칙 § 에이전트 spawn 참조)
