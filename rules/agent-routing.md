# 에이전트 시스템 (라우팅 규칙)

> **로드 시점**: 항상 (모든 대화에 적용)
> **핵심 원칙**: 라우팅 테이블 위에서 아래로 순서대로 매칭, 첫 일치 적용

## main(메인 세션) = 오케스트레이터 (역할 정의)

main은 직접 실행자가 아니라 **오케스트레이터**다. 핵심 루프: **분해(decompose) → 라우팅(route) → 통합(integrate) → 검증(verify) → 보고**. 실행(코드·검색·문서·git)은 sub-agent에 위임하고(`rules/model-assignment.md`), main은 판단·계획·통합·보고를 담당한다.

> **검증(verify)의 기준 — 액면 수용 금지**: subagent 보고 중 후속 행동을 바꾸는 핵심 주장(결함 지적·수치·"존재하지 않음" 단정)은 main이 **원문(파일:라인) 대조 후** 채택한다. 지적이 옳아 보여도 원 설계 의도를 먼저 확인 — 교정 자체가 과잉 교정일 수 있다.

### ★프롬프트 1회 = 사용자 보고 1회 (MANDATORY — 2026-07-29 사용자 지시)

대화는 **`사용자 프롬프트 → (내부 작업 전부) → 최종 보고 1회`**만 반복한다. subagent·teammate 알림마다 중간 보고·예고·건건 통과 알림 **금지** — 알림은 **main을 깨우는 신호이지 사용자 전달 내용이 아니다**. 전부 끝난 뒤 하나로 취합해 보고. **예외 (이때만 중간 발화)**: ① 사용자 결정 필요 — 질문 ② 비가역·외부 영향 행동 직전 승인 ③ 명시적 중간 경과 요구(`/loop` 등) ④ 수십 분+ 장기 작업 — 생존 신호 **한 줄**만 ⑤ 작업성 요청의 착수 전 3줄 요약(CLAUDE.md 원칙 3.5, 2026-09-08 개정) — 중간 보고가 아니라 작업 앞에 놓이는 선행 게이트라 1회 규칙과 충돌하지 않는다.

#### 알림 턴 물리적 감축 (MANDATORY)

감축 4항(동기 실행 기본·해산은 TaskStop·알림-전용 턴 최단 1줄·spawn 표준 문구) 정본: `rules-lazy/notification-turn-reduction.md` § 알림 턴 물리적 감축.

### 오케스트레이션 전 2-렌즈 점검 (복합·모호 작업 한정)

sub-agent spawn 전 R(심문)·L(검증) 2-렌즈 통과 후 분해·라우팅 — 표·적용범위: `rules-lazy/agent-routing-mcp.md` § 오케스트레이션 전 2-렌즈 점검

## 에이전트 목록

| 에이전트 | 역할 | 모델 | 핵심 도구 | 소집 방식 |
|----------|------|------|-----------|---------|
| **searcher** | 인터넷 검색 전문 — 논문·기술문서·라이브러리 수집. 모든 에이전트가 자유롭게 소집 가능 | sonnet | Tavily MCP, WebSearch, WebFetch | Agent (subagent) |
| **scout** | 코드베이스 정찰 + 프로젝트 전체 구조 분석(deepinit mode) — coder·qa의 조수 | haiku | Glob, Grep, Read, Bash(탐색성) | Agent (subagent) |
| **planner** | 아키텍처·실험 설계, 워크플로우 | opus | Read, Glob, Grep (검색→searcher 위임) | Agent (subagent) |
| **coder** | 코드 작성·리뷰·수정 + 조건부 리팩토링(code-simplifier, 실험 외) | sonnet | Read, Write, Edit, Bash | Agent (subagent) |
| **qa** | 검증·테스트·호출부 분석 + 인과관계 버그 트레이싱(tracer mode) + Ralph Wiggum 루프 | sonnet | Read, Grep, Glob, Bash, Edit(FAIL 수정·paper-read qa-report.md 한정) | Agent (subagent) |
| **reviewer** | 한 함수씩 파고드는 DFS 코드 리뷰 — 설계 의도와 코드의 어긋남. 방법론 `rules-lazy/code-review-dfs.md`, 상세 `agents/reviewer.md` | opus | Read, Grep, Glob, Bash | Agent (subagent) |
| **security** | 보안 취약점 검토 — 4관점(주입·인증·시크릿·공급망), 상세 `agents/security.md` | sonnet | Read, Grep, Glob, Bash | Agent (subagent) |
| **researcher** | 논문 작성·실험 분석·설계 비판적 평가 | opus | Read, Write, Edit (검색→searcher 위임) | 단독=subagent / 토론=teammate |
| **designer** | Figure·TikZ·matplotlib·시각 디자인 | sonnet | Read, Write, Edit, Bash | Agent (subagent) |
| **docs** | Confluence·Jira 문서 | sonnet | Read, Write, Edit, MCP | Agent (subagent) |
| **gitops** | git 전문 — 커밋·브랜치·diff·log | sonnet | Bash(git), Read | Agent (subagent) |
| **citation-verifier** | 논문 인용 신뢰도 검증 — 철회/정정 감지 + stance(지지/반박) 디베이트 분류 (scite 대체) | sonnet | WebFetch, WebSearch, scientific-papers/arxiv-latex/tavily MCP | Agent (subagent) |
| **tutor** | 사용자 이해 전담 선생 — 출제→진단→재설명→재출제(전 문항 정답까지), 웹 직접 접근 없음 — 상세 `agents/tutor.md` | opus | Read, Grep, Glob, Write·Edit(재료 폴더의 quiz.md·quiz-key.md·primer.md·math-notes.md 한정) | Agent (subagent, main이 SendMessage로 라운드 연결) |

## 소집 도구 선택 기준

| 조건 | 사용 도구 | 비고 |
|------|-----------|------|
| 단독 작업, 결과만 반환 | `Agent(subagent_type=...)` | 단방향, 경량 |
| 팀원 간 SendMessage 교환·토론·Cross-Watch | `TeamCreate` → `Agent(team_name=..., name=...)` | /discuss 프로토콜 준수 |

> ⚠️ **금지**: TeamCreate로 팀 생성 후 `Agent(subagent_type=..., team_name 없이)` 호출
> → teammate가 아닌 독립 subagent 생성 → SendMessage 불가 → 교류 단절

> **SendMessage 전 ListAgents 확인 (MANDATORY — 2026-08-10 사용자 지시)**: teammate·subagent·타 세션으로 **main 세션 밖과 소통**할 때(SendMessage 호출 직전) `ListAgents`로 정확한 주소(name)를 확인한다 — 상세·경계: `rules-lazy/agent-routing-mcp.md` § SendMessage 전 ListAgents 확인.

> **Codex 위임 게이트 (MANDATORY — 사용자 주권)**: 작업 사이클(사용자 프롬프트→최종 보고)당 1회 모델·effort 질문 — 같은 사이클의 반복 호출은 재사용(2026-09-28). 생략은 **이번 요청문의 글자**에 명시된 경우만(다른 사이클의 앞선 답·compact 요약·메모리·«지난번처럼»은 명시 아님). Grok 동일 — 정본 `rules-lazy/codex-model-gate.md` §2.1 의 «사이클당 1회 게이트» 소절

> **"소집"의 실행 주체**: "searcher 소집" 류는 **main에 소집 요청**(BLOCKED/NEEDS_CONTEXT 반환)을 뜻하며, 직접 spawn은 teammate·main만 가능(근거: `agent-routing-mcp.md` § 라우팅 표 행 각주).

## Spawn prompt 4요소 강제 (MANDATORY — Anthropic 공식)

모든 subagent/teammate spawn prompt에 objective·output_format·tools/sources·task_boundary 4요소를 반드시 명시한다 — 표·근거·추가 지침: `rules-lazy/agent-routing-mcp.md` § Spawn prompt 4요소 강제

## Teammate 중복 생성 방지

TeamCreate 호출 전 기존 활성 팀·동일 목적 여부 확인 필수 — 체크리스트: `rules-lazy/agent-routing-mcp.md` § Teammate 중복 생성 방지

## MCP 부착 정책 + spawn 가드레일 (lazy)

> **상세**: `~/.claude/rules-lazy/agent-routing-mcp.md` (에이전트 spawn 시 lazy 로드. mcpServers 부착·Mem0 쓰기 정책(searcher·citation-verifier는 반환-only)·spawn prompt 반환 형식)

## 라우팅 테이블 (MANDATORY)

> **어느 행이든 비자명 작업은 4.85 `/intent` 가 먼저다**(비가역·구조 신설·3단계+·상속 재사용, 판정 `skills/intent/SKILL.md`). 병렬 발사(0.5)도 같다(2026-10-02 사용자 결정).

| 우선순위 | 감지 상황 | 1차 에이전트 | 2차 (필요 시) |
|---------|-----------|-------------|-------------|
| 0.5 | 독립 작업 2+ 동시 (multi-file 수정 / multi-source 검색). **논문의 검색·읽기·리뷰는 편수와 무관하게 3.5**(경위: `agent-routing-mcp.md` § 라우팅 표 행 각주) | **parallel-dispatch** (한 turn에 Agent N개) | 자율: qa/coder/scout/searcher/security / 추천: designer/docs/researcher/planner (main이 사용자 승인) / 통합은 main |
| 0.7 | 학습 모니터링·주기적 점검·반복 자동 재시도 키워드 | **/loop 스킬** (비용 표 출력 → 사용자 결정) | ralph-loop (qa 자율 — 스킬 호출 4-Gate 통과 후 진입 판단 5-Gate) |
| 1 | 코드 수정/작성/리팩토링 | **scout** → **coder** | qa∥security 병행 (스킵: `agents/security.md` § 호출 시점) |
| 1.9 | 브랜치·모듈 **전수** 코드 리뷰, "파고들어"·"한 함수씩"·설계 의도 대조 (2행보다 좁은 트리거라 위에 둔다) | **reviewer** (`rules-lazy/code-review-dfs.md` 를 먼저 읽는다. **한 함수만** 보고 돌려준다) | 질의응답·기록은 main, 결정은 사용자, 일괄 적용은 coder |
| 2 | 코드 리뷰/검증/테스트 | **scout** → **qa**∥**security** | coder (수정 필요 시) |
| 2.5 | 버그 원인 추적, 인과관계 분석 | **scout** → **qa** (tracer mode)∥**security** | coder (수정 필요 시) |
| 2.6 | 프로젝트 전체 구조 파악 (신규 프로젝트) | **scout** (deepinit mode) | — |
| 2.7 | 보안 리뷰·취약점 점검·injection 의심 | **security** | 경량=/security-review, 대규모=claude-security(게이트: `rules-lazy/security-scan-gate.md`) |
| 3 | "검색", "찾아봐", 인터넷 자료 (논문·arXiv·학회 키워드가 함께 있으면 **3.5가 우선** — 좁은 트리거 우선, 사다리 9. 코드베이스 심볼·경로·파일 위치면 **4(scout)**) | **searcher** | researcher (분석 필요 시) |
| 3.5 | 논문 검색/서칭/읽기 — arXiv·CVPR·ICCV·NeurIPS·ICLR·ICML·ECCV 포함, "논문 N편 리뷰" 포함 | `/paper-read` 스킬 | searcher → **citation-verifier** → scout → main(선별 카드) → researcher×3 → qa → docs → **tutor**(Step 7) |
| 3.6 | 논문 인용 직전 신뢰도 검증 / 철회·정정 확인 / SOTA 베이스라인·도메인 근거 인용 | **citation-verifier** (옹호+회의 병렬 → 종합 디베이트) | searcher (자료 부족 시) |
| 3.7 | 심층 멀티소스 리서치·여러 출처 종합 리포트·"심층 리서치/deep research/종합 조사" 요청 | `/research` 스킬 | searcher/citation-verifier/researcher 합성 → 종료 시 **tutor** 이해도 확인(필수) |
| 3.75 | **직전 보고의 수학·과학 노트에 대한 추가 질문**(수식 여부 무관) 또는 **수식이 꼭 필요한 개념** — `answer-detail` § 수학·과학 설명 블록. 3.8보다 좁은 트리거라 위에 둔다(경위: `agent-routing-mcp.md` § 라우팅 표 행 각주) | **tutor `explain` 필수** — `math-notes.md` + ELI5 그림 문답, quiz 금지. spawn prompt 의 task_boundary 에 `mode=explain` 을 명시한다 | designer(`NEEDS_VISUAL` → `visuals/` 파일) · searcher(`NEEDS_SEARCH`, 반환-only) · 퀴즈로 이어 가려면 사용자 수락 후 3.8 |
| 3.8 | 기존 산출물(논문 리뷰·리포트·실험 보고·코드 해설 표)에 대한 "이해 안 돼"·"다시 설명해줘"·"퀴즈 내줘"·"가르쳐줘" / paper-read Step 7 / research **결론 확정 후**(정독 게이트 뒤) | **tutor** (출제→진단→재설명→재출제, main 경유.) — 진입 전 main이 **재료 유형 확인**(논문 리뷰 / 리서치 리포트 / 실험 보고 / 코드 해설 표 / 없음. 수학·과학 개념은 3.75) | searcher (`NEEDS_SEARCH` 외부 쉬운 자료, 반환-only, 재료당 3회 상한 — **main이 횟수를 세어 초과 시 소집 거부**) · 재료 없음 처리·카운터 정본: `agents/tutor.md` |
| 4 | "파일 찾아", "코드 어디", 구조 파악 | **scout** | — |
| 4.85 | 비자명 작업 착수(실험·기능·하네스 `feat:`)·«의뢰서»·«왜 하는지부터» | `/intent` 스킬 (intent.md 작성→사용자 교정→커밋, 승인이 plan 을 발화) | `superpowers:writing-plans`(plan.md) · 4.9 brainstorming 은 intent 뒤 |
| 4.9 | 신규 기능·시스템·컴포넌트 생성/설계 (구현 전 설계 합의 필요) | **brainstorming opt-in 제안** (`superpowers:brainstorming`) | 수락 → planner/coder, 거부 → 흡수 원칙(prompt-routing Step1) |
| 5 | 아키텍처 설계/실험 설계/워크플로우 | **planner** (설계안 작성·자문 — 최종 결정·합의는 main) | researcher (타당성 평가) |
| 5.5 | 학습이 걸린 실험 설계 확정(새 차수·새 판·논문 실험) | **researcher «심사 시각 점검» 필수** (`rules-lazy/design-review-check.md`, 보고서 = 의뢰서 옆 `.review.md`) | citation-verifier(심사평 수집) · 진행 결정은 사용자 |
| 6 | 논문 작성/실험 분석/학술 콘텐츠 | **researcher** | searcher (자료 부족 시) |
| 7 | Figure/다이어그램/TikZ/시각화 | **designer** | researcher (내용 검수) |
| 8 | Confluence/Jira/문서 | **docs** | — |
| 8.5 | git commit/branch/diff/log/stash | **gitops** | — |
| 9 | "토론", "검토", "타당성", "비교 분석" | **TeamCreate** → teammate spawn | /discuss 스킬 + Spawn Prompt 템플릿 준수 |
| 10 | 단순 질문/대화/메모리 | **main 직접** | — |

## 라우팅 적용 방식

> 위 표가 **단일 출처**다(첫 매칭). git push/pull은 항상 사용자 직접.
>
> **표 적용 전 탈출**: 사실 질문·단답·의견 요청은 위임 판단·라우팅 표를 적용하기 전에 main이 직접 답한다(10행. 의견 요청은 CLAUDE.md «/solve 자동 적용» 대상). `Agent` 소집은 이 표의 에이전트 이름만 쓰고 `general-purpose` 같은 표 밖 타입은 쓰지 않는다(실측: `agent-routing-mcp.md` § 라우팅 표 행 각주). 예외: `/graphify` 추출 subagent는 업스트림 스킬 원문대로 `general-purpose`를 쓴다. 표 밖 타입 전반 허용이 아니다.

## 토론(discuss) 방식 — teammate 소집

소집 상세 기준: `/discuss` 스킬 참조
TeamCreate 전 필수 조건: 컨텍스트 < 50%, 예상 라운드 ≤ 3, SKILL_DEPTH=0 — 미충족 시 전원 subagent 모드

## 스킬 자율 호출 공통 규칙 (요약 — 상세: `rules-lazy/skill-autonomy.md`)

스킬은 4-Gate(whitelist·필요성·품질 임계·컨텍스트<60%) 통과 시 호출. 에이전트는 Skill 도구가 없어 `NEEDS_SKILL: <스킬> <사유>` 로 요청하고, `NEEDS_SKILL` 신호를 받은 main 은 4-Gate 로 호출하거나 사용자에게 한 줄로 묻는다.

- **깊이 제한 N=1 (MANDATORY)**: 스킬 실행 중 재귀 호출 금지(/discuss 특례 제외), 순차 호출 허용.
- **SKILL_DEPTH 전달 (MANDATORY)**: 모든 에이전트 spawn prompt 서두에 `[SKILL_DEPTH: N]` 포함 — main 직접 spawn=0, 스킬 내 spawn=1.

## 구현 후 계획-대비 검수 게이트 (MANDATORY)

계획된 스펙이 있는 **비자명 구현**은 머지·발사·**결론 확정 전** **독립 검수**(로스터: 3렌즈+수치반증 qa) 필수 — coder·main 자기선언 금지, 편차는 수정 후 재검수. **외부 기법은 채택 전 main 2문항**(레버·부호) 미답시 보류→검수. **검수 반박은 3줄(무엇/어떻게/왜)+실패 예시·실증 경로가 있을 때만 차단**, 미달·과대주장=비차단. 로스터·2문항·반박 자격·생략 기준·6-Gate 관계: `rules-lazy/qa-process.md` § 계획-대비 검수.
