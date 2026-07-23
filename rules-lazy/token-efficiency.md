# 토큰 효율 규칙

> **로드 시점**: 모든 작업 시작 전 검색·읽기 전략 선택 시 (항상 적용)

## 파일 탐색 전략 (순서 준수)

1. **Glob** → 파일 위치 파악 (파일 전체 읽기 금지)
2. **Grep** → 필요 심볼/키 위치 특정 (`head_limit` 활용)
3. **Read with offset/limit** → 필요 섹션만 읽기
4. 전체 파일 읽기는 **100줄 이하** 파일에만 허용
5. 이미 읽은 파일은 동일 세션 내 재읽기 금지 → 이전 내용 재활용

## 도구 출력 최적화

| 도구 | 제한 방식 |
|------|-----------|
| Grep | `head_limit: 20` 이하, 더 필요 시 offset 페이지네이션 |
| Bash (긴 출력) | `\| head -30` 파이프 추가 |
| wandb / 학습 로그 | 전체 출력 금지 → 핵심 수치(loss, metric)만 추출 |
| Glob | 결과 50개 초과 시 패턴 좁혀서 재시도 |

## 모델 선택 기본 원칙

→ 상세: `~/.claude/rules/model-assignment.md`

절약 공식: **토큰 비용 = 모델 × 컨텍스트 크기 × 반복 횟수**
→ 세 가지를 모두 최소화

## Opus 컨텍스트 보호 (MANDATORY)

Opus 메인 세션의 컨텍스트에 대량 데이터가 로드되는 것을 방지한다.

### Opus 직접 Read 제한
- **3개+ 파일** 읽기 필요 시: Haiku scout에 위임 → 요약만 수신
- 단일 파일 Read는 Opus 직접 허용 (offset/limit 사용 필수)
- 이미 읽은 파일 재읽기 금지 (기존 규칙 유지)

### Opus 연속 탐색 제한
- **Glob/Grep 3회+** 연속 필요 시: Haiku scout에 위임
- 단발성 Glob/Grep 1~2회는 Opus 직접 허용

### Opus 응답 코드 블록 제한
- **10줄+ 코드 블록**: 응답 텍스트에 포함 금지 → subagent가 Write 도구로 저장
- diff 요약, 변경 설명만 응답에 포함
- 예외: 사용자가 "코드 보여줘" 명시 요청 시

### Opus git 출력 제한
- `git diff` / `git log` 결과를 Opus 컨텍스트에 직접 로드 금지
- Sonnet gitops에 위임하여 요약만 수신
- 예외: `git status` (짧은 출력)는 Opus 직접 허용

### Subagent 반환값 적재 최소화 (MANDATORY)

Subagent spawn은 parent context를 상속하지 않으나, **반환값은 main 컨텍스트에 그대로 적재**되어 입력 토큰을 누적시킨다. 대량 반환을 허용하면 1M 영역 진입 속도가 급격히 빨라진다.

| 반환 유형 | 규칙 (단일 기준 — `agent-routing-mcp.md § 적재 기준 강화`와 동일) |
|----------|------|
| 100자 이하 요약 | main 직접 적재 허용 (권장 기본값) |
| 100자~1500자 | `_workspace/{agent}_{주제}.md` 저장 후 경로만 반환 |
| 1500자 초과 | 위와 동일 + 반환 거부(재시도 요청) |
| raw JSON / 로그 원문 | 복사 금지 — 핵심 수치·파일 경로·결론만 추출 |

### Agent Spawn Prompt 가드레일 (MANDATORY)

모든 `Agent(subagent_type=..., prompt=...)` 호출 prompt 하단에 아래 3줄 자동 포함:

```
## 반환 형식 제약 (main 컨텍스트 보호)
- 전체 반환 1500자 이내
- 상세 데이터는 `_workspace/{agent}_{주제}.md` 저장 후 경로만 반환
  (**Write 미보유 에이전트(scout/searcher/planner/gitops/citation-verifier)는 _workspace 저장 불가 → 요약을 상한 내로 압축해 직접 반환**; 초과 시 분할 반환, 저장이 필요하면 main이 수신 후 저장)
- raw JSON/로그 원문 복사 금지, 요약만
```

### 대량 반환 도구 기본 limit 강제

| 도구 | 기본 limit | 초과 허용 조건 |
|------|---------|-------------|
| `mcp__mem0__get_memories` | limit=10 + filter 필수 | 사용자 명시적 "전체 조회" 요청 |
| `mcp__mem0__search_memories` | limit=5 | 작업 유형별 프로파일(§1.4)이 limit≥5 권장하는 경우만 |
| `mcp__tavily__tavily_search` | max_results=5 | V02/V05 SOTA·학술 검색 시 10까지 |
| Bash 명령 출력 | `\| head -30` 파이프 기본 | 사용자가 전체 출력 요청 시 |

(2026-04-19 1M 가드레일 신설)

## config 파일 관리
- Hydra config (train.yaml, task/*.yaml)는 세션 초반 **1회만 읽고** 내용 메모
- 이후 config 참조 시 재읽기 금지, 메모 내용 활용
- config 변경 발생 시에만 해당 파일 다시 읽기

## 반복 작업 패턴
- 동일 패턴이 3회 이상 반복되는 수정 → haiku subagent로 일괄 처리
- 여러 파일에 동일 변경 적용 시: 패턴 먼저 확정 후 병렬 Edit

## 응답 출력 토큰 절약 (MANDATORY — 긴 코드 생성 시)

### 코드 블록 기준 통합표 (주체별 — 혼동 방지)

| 주체·상황 | 기준 | 초과 시 |
|----------|------|--------|
| main 응답 텍스트 내 코드 블록 | **10줄** | subagent Write로 파일 저장 (§ Opus 응답 코드 블록 제한) |
| 파일로 저장하는 코드 (coder 등) | **100줄** | 예외 없이 Write 도구 (응답 텍스트 포함 금지) |
| TikZ/matplotlib/LaTeX 스크립트 | 길이 무관 | 항상 Write 도구 |

### 긴 코드는 Write 도구로 파일에 직접 저장
- **100줄 이상 코드**: 응답 텍스트에 코드 블록 포함 **금지** → Write 도구로 파일 저장 후 경로만 보고
- **TikZ / matplotlib 스크립트**: 예외 없이 Write 도구 사용 (200~400줄 이상으로 출력 토큰 초과 위험)
- **응답 텍스트에 기술할 내용**: 파일 경로, 설계 결정, 실행 명령서 **만** (코드 전체 불가)

```
# ✅ 올바른 패턴 (경로는 {name} 플레이스홀더 — ci-gate 포인터 검사가 예시를 실참조로 오인하지 않게)
Write 도구로 docs/paper/scripts/gen_{name}_tikz.py 저장
→ 응답: "파일 저장 완료: docs/paper/scripts/gen_{name}_tikz.py / 실행: uv run python ..."

# ❌ 금지 패턴
응답 텍스트에 200줄짜리 TikZ 코드 블록 직접 출력
```

### 긴 출력 생성 전 컨텍스트 사전 점검
- 긴 코드 생성(TikZ/스크립트/LaTeX) **시작 전**: 컨텍스트 50%+ 시 compact 먼저 수행
  - 사용자에게 알림: "컨텍스트가 N% 입니다. compact 후 진행하겠습니다."
  - compact 지시: `/compact 실험 config·수정 내역 보존, 도구 출력 요약`
- 응답 중간에 토큰 부족이 예상되는 경우 → 사전에 분할 계획 보고 후 진행

## 스킬 활용 우선
- 반복적인 작업(실험 설계, Figure 생성)은 해당 스킬 먼저 제안
- 스킬 사용 시 구조화된 흐름으로 불필요한 대화 왕복 감소
