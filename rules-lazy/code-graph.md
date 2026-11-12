# Code Graph (Graphify) — 프로젝트별 코드 지식그래프 (CLI-first, opt-in)

> **로드 시점**: scout/coder/qa가 **대형 프로젝트**에서 정찰·변경영향·호출부 분석 시 lazy 로드 (always-on 아님).
> **핵심**: Graphify로 각 프로젝트 폴더에 **독립** 코드 지식그래프(`graphify-out/graph.json`) 생성 → 에이전트가 read-only로 조회해 대형 repo 토큰 절감. **하네스(`~/.claude`)가 아니라 작업 중인 프로젝트 cwd에서 동작**.
> **성격**: 시범 도입(2026-07, 신생 툴) — opt-in·완전 제거 가능. 첫 프로젝트에서 harness-bench 실측 후 확대 결정.

---

## §0 무엇 / 언제 (게이트)

- Graphify(safishamsi/graphify, MIT) = tree-sitter AST → NetworkX 그래프 → Leiden 클러스터. **코드 전용 모드는 로컬 파싱(API 토큰 0, 외부 콘텐츠 없음)**. 산출물: `graphify-out/graph.json` + `GRAPH_REPORT.md` + `graph.html`.
- **사용 게이트 (모두 충족 시만)**:
  1. **repo 규모** — 코드 파일 **100개 초과** 시 적용 후보 → **적용 여부를 사용자에게 질문** (2026-07-06 기준 완화: 300→100. `graphify-out` 미존재 시 §3 3택 게이트가 질문 채널, 존재 시 = 이미 사용 합의로 간주하고 질문 생략). **100개 이하는 사용 금지** — Grep이 더 경량
     > **예외 (2026-07-09 사용자 결정)**: `/project-init` 경유 **신규 프로젝트는 게이트 없이 기본 활성화** — 근거: 신규는 코드가 적어 AST-only 인덱싱 비용≈0이고, 처음부터 그래프와 함께 성장하면 100파일 도달 시점에 재도입 비용이 없다. 이 예외는 신규 생성에만 적용 — **기존 프로젝트 도입은 게이트 유지**.
  2. 해당 프로젝트에 `graphify-out/graph.json` **존재** (없으면 §3 설치·인덱싱 게이트)
  3. 작업이 **구조·의존성·호출경로·변경영향** 파악 (단순 단일 파일 읽기엔 불필요)
- 미충족 → 기존 Grep/Glob 정찰 유지. (게이트는 over-application 방지 — 작은 repo·단순 탐색엔 Grep이 이김)
- ⚠️ **100~300 구간 주의**: 절감 효과가 작을 수 있음(실측 6~15x는 100~500 기준, <100은 무의미) → 이 구간 도입 시 **§5 효율 점검 필수** — Grep 우세 확인 시 비활성 권고.

## §1 프로젝트별 독립 동작 (MANDATORY)

- **실행 위치 = 작업 중인 프로젝트 cwd**. `~/.claude` 하네스는 **autoindex 훅 대상에서 제외**(§6 가드) — 단, 하네스 온톨로지는 별도 관리 경로로 존재한다(§7. 2026-07-09 사용자 결정으로 구 "하네스 인덱싱 금지"를 대체).
- `graphify .` → 그 폴더에 `graphify-out/` 생성. 프로젝트마다 **독립 그래프**(전역 상태·전역 DB 없음, 캐시도 `graphify-out/cache/` 로컬 — SHA-256 증분).
- 여러 프로젝트 각각 인덱싱해도 서로 간섭 없음 (검증됨: README 근거).

## §2 소비 (read-only — 자동 허용)

게이트 충족 시 **그래프 소비 주체 전원(main·scout·coder·qa)** 은 Grep 남발 대신 그래프 우선. (main도 직접 `graphify query`/`jq` 소비자다 — CLAUDE.md § graphify. planner·researcher 등은 원본 파일만 읽어 그래프 stale 무관.)
- **구조 개관**: `graphify-out/GRAPH_REPORT.md` Read (god node·클러스터·추천 질문).
- **심볼·의존성·경로 쿼리**: `graph.json`을 `jq`/`graphify query`로 조회 (read-only, 자동 허용). 예) 특정 심볼 노드/엣지, 두 심볼 간 경로, 클러스터 소속.
- **advisory 원칙**: 그래프에 없거나 최신성 의심 → Grep으로 보완·교차확인. 그래프 stale 의심 시 **현재 코드 우선**(mem0 §1.5 동일 원칙).
- **용도별**: scout=구조 정찰, coder=변경 영향 범위, qa=호출부·영향 분석.
- **세션 시작 리마인더 (2026-07-31)**: SessionStart 훅 `scripts/graphify-session-note.sh`가 graphify-out 보유 프로젝트에서 "query 우선" 1줄 + stale 경고를 주입 — §2 발동율 보강 (실측: 리마인더 이전 사용률 세션 1/182). 하네스에선 update 권고 대신 "나이틀리 전용" 경고로 대체(오염 방지).

### §2.1 소비 전 freshness 자가검사 (MANDATORY — 2026-07-19)

> 배경: §2 advisory의 "stale 의심 시 Grep 보완"은 **의심할 트리거가 없어 사실상 무력**했다 — 소비자는 그래프가 낡았는지 알 방법이 없어 낡은 그래프를 그냥 신뢰했다. 이 검사가 그 트리거를 공급한다. §7(하네스 온톨로지)의 freshness fallback 아이디어를 §2(프로젝트 코드 그래프)로 가져오되, **신호는 mtime 비교로 교정**(2026-07-19 dogfooding — 아래 ⚠️: graphify는 디스크를 인덱싱하므로 git-dirty는 오판).

그래프 조회 **직전**(main 자기 조회 전 / main이 graph-소비 subagent 디스패치 전), 아래 싼 검사(밀리초)를 수행:

1. **stale 판정 = mtime 비교 (주 신호)**: `graph.json`의 mtime vs **코퍼스 소스 파일의 최신 mtime**(`graphify-out/`·`outputs/`·`logs/`·`lightning_logs/`·`.git/` 등 비코퍼스 제외). **최신 소스 mtime > graph.json mtime → stale**(그래프 빌드 후 편집됨). graphify는 워킹트리(디스크)를 인덱싱하므로 "디스크가 빌드보다 새로운가"가 정확한 신호다.
   > ⚠️ **git dirty/커밋 비교를 stale 신호로 쓰지 말 것** (2026-07-19 dogfooding 확정 함정): graphify는 커밋 상태가 아니라 **디스크(워킹트리)를 인덱싱**하므로 `graphify update .` 직후 미커밋 편집이 남아 있어도 그래프는 이미 그걸 포함한다. 그런데 `git status --porcelain`(dirty) 판정은 이때 **STALE 오판** → 미커밋 편집이 흔한 활성 개발 내내 불필요 재빌드. 실측: 한 프로젝트에서 graph 21:41 빌드가 최신 편집(20:12)을 포함해 mtime상 FRESH인데, 미커밋 `.py` 4개 때문에 dirty-check는 stale로 오판했다.
   > **§7과 신호가 다른 이유 (통일 금지 — 2026-07-19)**: §7(하네스 온톨로지)은 정반대 맥락이라 **git-diff가 올바른 신호**다 — 1) `graphify-out`이 **git 추적 + 서버 동기화**인데 git은 `pull` 시 mtime을 리셋하므로 mtime을 쓰면 **매 pull마다 stale 오판** (git-diff `built..HEAD`는 커밋 기준이라 pull 후에도 정확), 2) 재빌드가 나이틀리(LLM)뿐이라 미커밋 편집은 실제로 stale(dirty→stale이 대개 참), 3) stale 대응이 재빌드가 아니라 **Grep 교차확인**이라 드문 dirty 오판도 싸게 흡수. **§2=mtime(gitignore·편집훅 즉시빌드·디스크인덱싱) / §7=git-diff(추적·크로스서버·나이틀리)는 맥락 차이에 따른 각자 정답 — 한쪽으로 통일하지 말 것.**
2. stale이면:
   - **main(또는 쓰기권한 컨텍스트)**: `graphify update .` 1회 실행(증분·AST·API 0) 후 조회. 1줄 보고(`[graphify] stale 감지 → 갱신`). SHA 캐시로 no-op이면 즉시 통과 — 파생 인덱스(gitignore) 갱신이라 autoindex 훅과 동일 계열의 자동 허용.
   - **subagent(scout/coder/qa)**: §3 쓰기경계상 **self-rebuild 금지** → Grep 교차확인으로 폴백하거나 `NEEDS_CONTEXT`로 main에 반환(“그래프 stale, 갱신 후 재디스패치 요청”). **권장: main이 graph-소비 subagent를 spawn하기 전에 이 검사를 먼저 수행**해 항상 신선한 그래프를 넘긴다.
3. fresh면 그대로 조회.

> 커밋 baseline(§6 커밋 트리거 훅)이 대부분의 stale을 미리 해소하므로 이 검사는 보통 통과한다 — 외부 터미널 직접 커밋·미커밋 외부 편집 같은 훅 사각지대의 **correctness 최후 보루**다.

## §3 설치·인덱싱 게이트 (쓰기·환경변경 = 사용자 직접 — MANDATORY)

인덱싱(`graphify .`)·설치는 **파일 쓰기 + 환경변경** → code-execution 규칙상 **AI 자동 실행 금지**.

> **공식 `/graphify` 스킬 예외**: 사용자가 `/graphify`를 직접 호출한 경우 = 실행 승인으로 간주 — 스킬 내 인덱싱·그래프 갱신 실행 허용. 아래 3택 게이트는 **에이전트가 자발적으로 도입을 판단**할 때 적용.

### 미설치 감지 시 사용자 3택 (MANDATORY)

에이전트(scout/coder/qa)가 Graphify 사용을 결정했으나 **미설치**(`command -v graphify` 부재) 감지 시 → **작업 진행 전 중단** → **main 경유로 사용자에게 3택 질문**(subagent는 직접 질의 불가 → BLOCKED/NEEDS_CONTEXT로 main 반환 → main이 AskUserQuestion). 무단 설치·진행 **절대 금지**.

| 선택지 | 처리 |
|--------|------|
| **A) 향후도 사용 안 함** | code-graph 비활성 — Grep 유지. **mem0 저장(feedback)** → 이후 **재질문 안 함** |
| **B) 사용함 → 지금 설치·환경설정** | **위임**(사용자 승인 = 이 선택 → 에이전트가 설치 명령 실행 가능, `# APPROVED «사용자 발화 8자 이상»`) / **직접**(실행 명령서 출력 → 사용자 실행). 이후 `graphify .` 인덱싱 + `graphify-out/` gitignore 추가. **mem0 저장(decision = 사용)** |
| **C) 보류** | 이번 작업 Grep 진행. **mem0 미저장**(다음에 재판단) |

- 미설치인데 A/B/C 확인 없이 설치·진행 **금지**.
- **재질문 방지**: 세션 시작(T03)·사용 판단 전 mem0 search로 A(미사용)/B(사용) 선호 확인 → 있으면 질문 스킵.

### 설치·인덱싱 실행 명령서 (프로젝트 cwd에서 — B 선택 시)

```
# 1. 설치 (최초 1회) — PyPI 임시명 graphifyy(y 2개), CLI는 graphify
uv tool install graphifyy      # 또는 pipx install graphifyy
graphify install

# 2. 인덱싱 (프로젝트 루트에서 — 하네스 아님)
cd <프로젝트 루트>
graphify .                     # 코드 전용(로컬 AST, 0토큰)

# 3. 자동 재인덱싱 — PostToolUse hook이 기본 (아래 §6, 별도 조치 불필요).
#    편집(Write|Edit)은 autoindex 훅, git commit은 commit-refresh 훅이 자동 갱신.

# 4. 산출물 gitignore (전체 무시 — 파생 인덱스·로컬 캐시)
echo "graphify-out/" >> .gitignore
```

> 패키지명 `graphifyy`는 임시(공식 `graphify`명 확보 중 — README 명시). 설치 실패 시 최신 패키지명 재확인. Python 3.10+ 필요.

## §4 가드

- **시범·제거성**: 신생 툴(2026-04·YC S26·자가측정 71x·임시 패키지명). 첫 프로젝트 harness-bench 실측 후 확대. `graphify-out/` 삭제 + `.gitignore` 원복이면 완전 제거.
- **코드 전용 모드만**: 멀티모달(문서·이미지 LLM 경유)은 토큰·untrusted 유입 → 기본 회피. 코드 그래프만 사용.
- **drift**: 코드 변경 시 그래프 stale 가능 → autoindex/commit-refresh 훅(§6)이 자동 재인덱싱, 소비 직전엔 §2.1 freshness 검사가 최후 보루. 충돌 시 **현재 코드 우선**(advisory).
- **하네스 격리(훅 한정)**: `~/.claude`는 autoindex 훅 제외 유지 — 하네스 온톨로지 갱신은 §7 경로만 사용.

## §5 Grep 대비 효율 점검 (opt-in: 2026-10-17 MANDATORY에서 변경, harness-bench 연계)

> Graphify가 항상 이긴다고 가정하지 않는다 — **Grep 베이스라인과 실측 비교**해 프로젝트별 유지/비활성을 판단할 수 있다. 자동 주기 점검은 하지 않고 아래 시점에만 한다.

- **측정 시점 (opt-in)**: 1) 프로젝트 첫 도입 직후(Before/After 필수) 2) 사용자가 요청할 때, 또는 graph 결과가 Grep 보다 못하다는 신호(누락·오답)를 본 때. 「5회마다·주 1회」 자동 점검은 폐지했다(측정 자체가 토큰 비용이고 사용 횟수를 세는 기록이 없어 지켜지지 않았다)
- **방법**: 동일 정찰 과제 1건을 Grep 체인(Before) vs graph 조회(After)로 수행 — 토큰·시도 횟수·누락 여부 비교 (`/harness-bench`, 3사이클 원칙은 첫 도입 시만)
- **판정(이진)**: graph가 토큰 또는 정확도에서 우세 → 유지. **Grep이 연속 2회 우세** → 해당 프로젝트 graphify 비활성 권고(사용자 확인) + mem0 기록(category=code_pattern, source=code-graph)
- **기록**: 매 점검 결과를 mem0에 1줄 저장 → 다음 세션 게이트 판단에 재사용 (소형 repo 재도입 방지)

## §6 자동 재인덱싱 (PostToolUse hook — 자동·견고)

> 코드 수정/추가/삭제 시마다 그래프가 자동 갱신되어 stale drift를 제거한다. LLM 개입 없음(토큰 0).

- **메커니즘 (편집)**: 전역 PostToolUse(Write|Edit) hook → `scripts/graphify-autoindex.sh` — 수정된 파일에서 상위로 `graphify-out/` 탐색 → 발견 시 해당 프로젝트 루트에서 `graphify update .`(**코드 전용**) **백그라운드 증분** 재실행. ⚠️ `graphify .`(전체)로 바꾸지 말 것 — pending 문서가 1건이라도 있으면 LLM 키를 요구하며 exit 1 전체 중단 (2026-07-31 한 프로젝트의 8일 침묵 정체 실증, 훅은 무키 headless)
- **메커니즘 (커밋 — 2026-07-19 신설, 사용자 결정 B-i)**: 전역 PostToolUse(Bash) hook → `scripts/graphify-commit-refresh.sh` — `git commit` 감지 시 동일 방식으로 `graphify update .`(코드 전용, 위와 동일 이유) 백그라운드 재인덱싱. autoindex(Write|Edit)가 못 잡는 **외부 에디터/스크립트 편집분을 커밋 시점에 보완**. 락·debounce 마커를 autoindex와 **공유**해 편집 직후(≤120s) 커밋은 스킵(이중 빌드 방지). 하네스(`~/.claude`)는 제외(§7 경로만). ⚠️ 외부 터미널 직접 커밋(Claude Code 밖)은 미포착 → §2.1 소비-직전 검사가 correctness 보루.
- **완료 한 줄 보고 (2026-07-10 사용자 요청)**: 백그라운드 빌드 성공 시 `.autoindex-updated` 플래그를 남기고, **다음 Write/Edit 훅 호출**이 그것을 읽어 `[graphify] {시각} {프로젝트} — 코드 그래프 자동 갱신 완료` 1줄을 세션에 출력 후 플래그 제거. 비동기 빌드라 완료 순간엔 보고 채널이 없어 "한 편집 늦은 보고"가 유일하게 진실한 시점 — 시작 시점 보고는 완료를 보장하지 못해 배제.
- **견고성 가드**: 1) debounce 120초(연속 Edit 폭주 방지) 2) lock 파일(동시 실행 방지) 3) graphify 미설치·graphify-out 없음·`~/.claude`(하네스)·graphify-out 내부 변경 → 즉시 무시 4) **항상 exit 0** — 인덱싱 실패가 사용자 편집을 절대 차단하지 않음
- **수동/네이티브 훅**: native `graphify hook install`(git post-commit·post-checkout)은 설치 CLI 0.9.52 에 있다(2026-10-17 실측: `graphify --help` 에 `hook install·uninstall·status` 있음. 구 서술 «v0.9.7 에 부재» 는 폐기). 다만 이 하네스 저장소에는 설치돼 있지 않다(`graphify hook status` 가 미설치 응답이다. 프로젝트 그래프 자동 갱신은 위 settings.json 훅 2종이 맡는다). 훅 미배선 환경에선 수동 `graphify update .`(증분·API 0) 또는 `graphify .`(전체·삭제 반영).
- 공식 `/graphify` 스킬 설치 시(CLAUDE.md § graphify) 쿼리·인덱싱을 스킬 경유로도 수행 가능 — 본 룰의 게이트·격리 원칙은 동일 적용.

## §7 하네스 온톨로지 (`~/.claude/graphify-out/` — 2026-07-09 도입)

> **목적**: 하네스 자체(rules·agents·skills·commands·scripts·문서)의 개념·판단근거·상호연결을 그래프/Obsidian vault로 유지 — 지식 이식의 **온톨로지 층**. 파일 단위 정독 없이도 "이 원칙이 어디와 연결되는가"를 구조로 소비할 수 있게 한다 (모델이 바뀌어도 연결 관계가 파일로 남는 것이 핵심).

- **산출물**: `graph.json`(노드·커뮤니티 수는 나이틀리 갱신 값, `graphify-out/GRAPH_REPORT.md` 통계 참조) + `obsidian/`(노드당 1노트, Obsidian vault) + `GRAPH_REPORT.md` + `graph.html`. git 추적(이식 가능), 머신 종속 파일만 gitignore.
- **코퍼스 (2026-07-13 확장 — 대화 지식 편입)**: 하네스 파일에 더해 **`knowledge/`**(대화에서 추출한 지식 노트 — 프로젝트별 하위 폴더 `harness/` 등으로 관리(2026-07-14), detect가 재귀 수집하므로 폴더 추가에 파이프라인 변경 불요. 작성 규약 `rules-lazy/knowledge-capture.md`, 트리거 CLAUDE.md 10.5)와 **`_audit/history.md`**(감사 이력·기준선)가 코퍼스에 포함된다 (detect 실측 142→148 파일). 대화→온톨로지 경로: 대화 중 main이 노트 즉시 작성 → 일간 타이머가 시맨틱 추출해 그래프·vault 편입.
- **소비 (read-only, 자동 허용)**: 하네스 구조·규칙 간 연관 질문("X 원칙이 어디서 참조되나", "이 룰과 충돌하는 곳") 시 **`graphify query` 우선** → Grep 보완. God node·hyperedge는 `GRAPH_REPORT.md`에서 확인. advisory 원칙 동일 — 그래프와 현재 파일 충돌 시 **현재 파일 우선**. **freshness fallback (2026-07-15, 07-15 GPT P2-1 보정)**: `built_at_commit ≠ HEAD` 단순 비교는 그래프 산출물 커밋 자체가 HEAD를 전진시켜 **정상 빌드 직후에도 항상 stale 판정**이 나는 함정 — 대신 `git diff --name-only <built_at_commit>..HEAD -- ':!graphify-out'` 이 비어 있지 않거나(그 사이 코퍼스 변경) 코퍼스 파일이 dirty일 때만 원본 Grep/Read 교차 확인 후 채택.
- **갱신 경로 (훅 아님 — 2경로)**: 1) 일간 무인 타이머(§8 — 기본, 2026-07-13 주간→일간) 2) `/harness-audit` Step 6.5 (`graphify ~/.claude --update --obsidian`, 수동 정밀 — 대규모 룰 변경 직후). autoindex 훅이 하네스를 제외하는 이유: 마크다운 semantic 추출은 LLM 세션(서브에이전트 dispatch)이 필요해 순수 bash 훅으로는 AST-only 부분 그래프만 나온다 (shrink-guard가 축소는 막지만 semantic 노드가 stale로 남음).
- **재추출 시 read-once 주의**: main이 같은 세션에서 이미 Read한 파일은 추출 서브에이전트의 전체 Read가 read-once 훅에 막혀 **스텁 추출**이 된다 → spawn prompt에 "차단 시 offset/limit 부분 읽기로 우회" 명시 (실측: 2026-07-09 초기 빌드에서 4개 파일 스텁 발생, --update에서 보정).
- **알려진 한계**: 청크 병렬 추출 특성상 dangling 엣지 일부 존재(초기 빌드 118개) — 결함 아닌 정상 한계, --update 누적 시 점진 해소.
- **shrink-guard 자동 검증 (2026-07-15)**: 파일 이동/삭제는 동명 노드 dedup 순감소를 만들어 shrink-guard(#479)에 걸리고, 가드 기준선이 자연히 낮아지지 않아 **무인 갱신이 매일 실패 반복**된다 (실측: knowledge/ 폴더 전환 -20). 파이프라인이 거부 시 2조건(1) 소실 소스 전부 디스크에서도 이동/삭제됨 2) 축소율 ≤10%)을 자동 검증해 통과 시에만 force 기록 — 실패 시 종전대로 중단+ntfy (대량 소실·추출 누락은 여전히 수동: harness-audit Step 6.5).
- **사용 피드백 (루프 완성 — 구축→사용→피드백→진화)**: 온톨로지 query 결과가 **stale**(현재 파일과 불일치)하거나 **불충분**(있어야 할 개념이 그래프에 없음)하면 mem0 1줄 기록(`category: code_pattern`, `source: code-graph`, 내용: 어느 영역이 왜 부족했나) → 다음 Step 6.5 갱신 시 해당 영역 재추출 우선 + 반복되면 harness-audit이 추출 프롬프트 자체를 개선(진화). 프로젝트 코드 그래프의 피드백은 §5 효율 점검이 담당 — 이 항목은 하네스 온톨로지 전용.

### §7.1 멀티서버 동시 갱신 충돌 (MANDATORY — 2026-07-09)

> **위험**: `graph.json`·`obsidian/*.md`는 LLM 추출 산출물이라 **비결정적**(같은 입력도 서버마다 다른 텍스트가 나올 수 있음) — git이 텍스트 자동병합 불가, 두 서버가 동시에 빌드 후 각자 push하면 **수동 conflict 해결 필요**.

- **빌더 구성 (07-10 결정 유지)**: 주력 1서버(서버 등록부 `graphify.builder` 가 true 인 서버)에만 설치하는 단일 빌더 원칙(§7.1 상단, 비결정적 산출물의 무가치한 중복 생성 회피) — 요일 슬롯 분산은 없다. 아래 가드는 그 단일 빌더가 push-pull 겹침을 만들지 않도록 하는 안전장치다. 커밋·push는 사용자 몫이고, ff-only pull은 무인 파이프라인(systemd, 세션 훅 관할 밖)이 한다.
- **자동 커밋 폐지 (2026-08-05 사용자 결정 — 멀티서버 충돌 실사고 재발)**: 나이틀리는 빌드 → export → **`git add graphify-out/` 스테이징 + `.commit-msg`(gitignored) 준비 + ntfy 알림**까지만. 커밋은 사용자가 pull로 순서를 잡은 뒤 `git commit -F graphify-out/.commit-msg -- graphify-out/ && git push`. 근거: 커밋 시점을 기계가 정하면 사용자가 pull 순서를 통제할 수 없고, 무인증 서버는 behind 가드도 무력해 낡은 베이스 위 커밋이 충돌을 만든다 — 스테이징뿐이면 커밋 드랍 수술 없이 `git restore`로 폐기 가능(파생물).
- **가드 (`scripts/ontology-pipeline.sh` — 2026-08-03 1)·3) 신설, 3) 은 08-05부터 스테이징 보류로 동작)**:
  1) **behind 빌드 금지 (detect)**: fetch 성공 시 ff-pull 필수 — ff 불가(발산·로컬 충돌)면 **skip**. 종전 "pull 실패=로컬 상태로 빌드"가 낡은 상태 위 커밋을 쌓아 발산을 만들던 발생원이었다. fetch 자체 불가(무인증 서버)만 로컬 빌드 허용.
  2) **미push 가드 (detect, 기존)**: 이 서버의 미push 온톨로지 커밋(사용자 수동 커밋 후 미push 포함)이 남아 있으면 새 빌드 skip — 서버당 발산 상한 1커밋.
  3) **스테이징 직전 재확인 (finalize)**: 빌드 수십 분 사이 타서버가 먼저 push했을 수 있음 — fetch 가능 + behind면 보류(산출물은 워킹트리 보존, 다음 주기에 pull 후 재빌드).
- **발산이 이미 난 경우 복구**: vault는 파생물 — 지켜낼 이유가 없다. 미커밋 산출물은 `git restore --staged --worktree graphify-out/` 후 pull, 이미 커밋했으면 로컬 온톨로지 커밋 drop 후 pull(충돌 중이면 `git merge --abort` 선행) — 다음 주기가 자동 복원.
- **md-AST 오염 사건 종결 (2026-08-07 원인 규명 — ad45edfc)**: 08-03·08-05·08-07 세 차례 타 서버발 오염 커밋(그래프 ~2배 팽창)의 원인은 graphify 차이가 아니라 **$HOME/.claude가 심링크인 서버(주력 빌더 서버)에서 autoindex 훅의 하네스 격리 가드가 편측 물리화로 무력화**된 것 — git commit마다 AST-only `graphify update`가 하네스에 실행돼 md 파일에 `_origin: ast` 노드 ~1,800개를 주입했다. 3겹 종결: 1) 발생원 수정(autoindex·commit-refresh·scope-gate 양측 물리화 — `knowledge/harness/path-guard-symlink-bypass.md`) 2) 파이프라인 오염 시그니처 가드(ast-on-md ≥1이면 빌드 거부 — 미지 발생원 대비 존치) 3) 커밋 메시지 서버 태그(`[호스트 | graphify 버전 | 노드 수]`)로 발생원 이력 추적. 오염 그래프 판별은 노드 수보다 **ast-on-md 카운트**가 정확하다(정상=0).
- **갱신 발생 → 권장 메시지**: 1) **커밋 대기 (2026-08-05)**: finalize가 ntfy 즉시 알림 + 세션 시작 usage-check `ONTOLOGY_COMMIT_PENDING`(`.commit-msg` 존재 + HEAD 대비 변경) 이중 채널 2) push 권장: 미push 온톨로지 커밋 감지 3) pull 권장: **원격 실비교 우선**(best-effort fetch, 비대화형 5초 제한), 자격증명 없는 서버는 로컬 휴리스틱(vault 이력 8일 초과)으로 자동 강등. (종전 "ntfy는 실패 전용" 2026-07-10 결정은 커밋 대기 알림에 한해 08-05 결정으로 대체.)
- **수동 갱신(harness-audit Step 6.5)을 타서버에서 실행할 땐** 사용자가 먼저 pull —드문 이벤트라 이 정도로 충분. 충돌이 나더라도 vault는 파생물: `git checkout --theirs graphify-out/` 후 재빌드로 복구 (소스 .md가 진실).
- **완전 자동화는 §8로 구현됨** (2026-07-09 사용자 승인, 2026-07-10 단일 빌더로 재설계).

## §8 온톨로지 무인 자동 갱신 (systemd 타이머 — 2026-07-09 사용자 승인)

> **권한 설계 근거 (판단 근거 이식)**: `bash-write-check.sh` 훅은 Claude의 Bash **도구 호출**만 가드한다 — systemd가 직접 실행하는 스크립트는 애초에 훅 관할 밖이다(선례: `restore-bg-sessions.sh`). 따라서 오케스트레이션 bash(pull·빌드·스테이징)는 systemd 소유로 두고, Claude는 시맨틱 추출 단계만 헤드리스(`claude -p --permission-mode acceptEdits`)로 참여시키면 **훅 수정 0·settings 상시 예외 0**으로 무인화가 성립한다. 상시 예외 룰보다 좁은 권한: 편집 허용이 그 호출의 플래그에만 존재한다. (설계 과정에서 "훅 패턴을 피해가는 스크립트 래핑" 안이 auto-mode 분류기에 2회 차단됨 — 그 우회 접근을 버리고 실행 주체를 옮긴 것이 본 설계.) **스테이징 cwd 보완 (2026-07-13 실측)**: acceptEdits의 자동 승인은 세션 cwd 범위이고 `~/.claude`는 내장 민감 가드가 별도 승인을 요구하므로, 헤드리스 추출은 cwd를 `~/.cache/claude-ontology/chunks`(스테이징)로 두고 청크를 받은 뒤 systemd bash가 graphify-out으로 이동한다 — settings 완화 0으로 성립.

- **구성**: `scripts/ontology-refresh.sh`(진입점: detect → 헤드리스 추출 → finalize) + `scripts/ontology-pipeline.sh`(bash 단계) + `scripts/ontology-extract-prompt.md`(헤드리스 프롬프트 — Bash 금지·graphify-out/ 밖 쓰기 금지 명시) + `config/systemd/user/claude-ontology-refresh.{service,timer}`(매일 03:17 — 2026-07-13 주간→일간, 변경 없으면 LLM 비용 0·미push면 skip이라 실효 주기는 min(1일, push 주기)).
- **설치·검증**: `config/systemd/user/README.md` §1 — 사용자 직접. 주력 1서버(서버 등록부 `graphify.builder`)에만 설치, 요일 슬롯 없음(§7.1).
- **미활성 감지 게이트 (T03 연동)**: 세션 시작 시 mem0에 타이머 결정이 없고 `systemctl --user is-enabled claude-ontology-refresh.timer`가 미활성이면 사용자에게 3택 — **활성화 위임**(승인 시 `# APPROVED «사용자 발화 8자 이상»`로 설치 실행) / **활성화 수동**(README §1 명령서 출력) / **비활성화**(이 서버는 pull 소비 전용). 선택은 mem0(`decision` 또는 `feedback`)에 저장해 재질문 방지 — `rules/mem0-auto.md` T03.
- **안전 불변식**: git push 전 구간 부재 / 커밋은 `graphify-out/` 경로만 add / pull 실패·청크 0개·빈 그래프·shrink-guard 거부 시 즉시 중단(부분 빌드 커밋 방지) / 신규 커뮤니티 라벨은 휴리스틱 — 정밀 라벨은 harness-audit Step 6.5 대화형 실행에서 보정.
- **수동 경로와의 관계**: Step 6.5(30일 감사)는 유지 — 타이머가 일간 신선도를, 감사가 라벨 curation·건강 점검·피드백 반영을 담당.
