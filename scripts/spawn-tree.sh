#!/usr/bin/env bash
# spawn-tree.sh — Write/Edit 보유 spawn(researcher·qa·docs·tutor)의 쓰기 경계 검사 정본 (paper-read Step 4 / Phase 1.5 / Write 보유 spawn 공통)
#
# 면제 범위(2026-10-01 감사): 런타임 면제(RUNTIME_EXEMPT)는 하네스 홈 고정 접두 아래만이다. 임의 깊이의 같은 이름 폴더는 면제되지 않는다(RUNTIME_EXEMPT 정의 위 주석).
#
# 사용:
#   snapshot <tree파일> <root>...
#       main 이 spawn 직전 실행. 1행 `# roots:`, 2행 `# format:<TAB>2`, 그 뒤 root 전체를 `path \t size \t 해시칸` 으로 저장. 해시칸은 append-only 기대 파일이면
#       `head -c size | sha256sum`(접두 해시, 그 자리가 심볼릭 링크면 `link`), 내용 비교 폴더(아래 ③)의 일반 파일이면 `c:<sha256>:<권한 8진수 1~4자리>`, 나머지 `-`.
#       내용 해시를 못 구한 파일이 있으면 FAIL 줄을 찍고 exit 1 — 그 tree 는 버리고 새 이름으로 다시 뜬다.
#       tree 파일 자신이 마커(ctime 기준) — 별도 .spawn-marker 불필요. 출력의 `--expect-marker <inode>:<ctime>` 값을 check 에 그대로 붙이고, qa 가 check 하는 창이면 qa spawn prompt 에 실어 보낸다.
#       tree 파일은 spawn 의 허용 경로 **밖**에 두고 spawn 마다 새 이름(`.spawn-tree-{논문명}`) — 이미 있으면 거부.
#   check <tree파일> --expect-marker <inode>:<ctime> [--allow <절대경로접두>]... [--main-only <절대경로>]... [--allow-mcp <mcp__접두>]...
#       spawn 종료 직후 검사자가 실행(주체 규칙은 아래). 파이프나 리다이렉션을 붙이지 않고 단독으로 실행한다(끝의 ` 2>&1` 하나만 ④ 예외에 든다).
#       절대 경로 접두만 받는다(`*/notes/*` 같은 접미 광역 금지). ④ 는 subagent 의 `mcp__*` 호출 중 `--allow-mcp` 접두에
#       맞지 않는 것을 FAIL 로 본다 — 15라운드 Grok: 전면 스위치는 qa·tutor 의 내부 기억(mem0)과 docs 의 외부 발신(Confluence)을 한 스위치로 묶었다. 예: `--allow-mcp mcp__mem0__`.
#       `--expect-marker` 는 필수다(없으면 exit 2). tree 파일의 현재 `stat -c '%i:%Z'` 와 대조해 다르면 FAIL — 창 안에서 tree 를 touch 하거나 다시 쓰면
#       ctime 기준이 밀려 그 사이의 쓰기가 ③ · ④ 에서 사라지기 때문이다(2026-11-24 W13 2차 선택 → 3차 필수, security N3).
#       주체 규칙: 검사자 ≠ 피검사자 — researcher 창은 qa 가, qa·docs·tutor 창은 main 이 실행한다(15라운드 렌즈3).
#       ④ 는 창 안의 **모든** subagent transcript 를 본다(검사자 자신 포함) — 검사자 qa 는 check 를 마치기 전에 어떤 MCP 도구도 호출하지 않는다(T05 검색은 check 뒤, 16라운드 Grok).
#       `--allow-mcp` 접두는 서버 단위 `mcp__<서버>__` 만 받는다(`mcp__` 단독 거부).
#       ① 사라진 파일(드롭퍼 자기삭제) — 심볼릭 링크도 파일로 센다(`-type l`, 14라운드 Grok 낮음: 링크 신설로 스캔을 비켜가던 경로)
#       ② append-only 기대 파일: 크기 감소 / 마커 시점 접두 해시 불일치 / 추가 줄이 아래 형식 표 밖(끝 줄에 개행이 없어도 검사) / 그 자리가 심볼릭 링크(따라가지 않고 FAIL)
#       ③ tree 보다 ctime 이 새로운 파일 중 허용 접두 밖(gitignored·`.git/` 포함). 제외는 **이번 tree 파일 자신(정확 경로)** 과 하네스 홈 고정 접두의 런타임 목록뿐이다
#          (정본은 아래 RUNTIME_EXEMPT · W13_EXEMPT 두 배열과 그 항목별 주석). W13_EXEMPT(2026-11-24, 실행 중 저절로 바뀌는 기록 파일류)는 **일반 파일에만** 적용하고
#          심볼릭 링크는 빼지 않으며, 쓰는 코드와 실제 폴더 목록으로 확인한 정확한 이름 · 깊이만 뺀다(이름 glob 이 `/` 를 넘지 않게 «그 아래 경로» 를 다시 막는다).
#          WHY: W14(2026-11-24) 상세 기록 `_usage/{hook-runs,tool-use,rule-reads,agent-runs,session-events}/YYYY-MM-DD.tsv` 와 정리 표지 `_usage/.harness-logs-pruned` 도 이 방식(바로 아래 날짜 이름 일반 파일만)으로 뺀다.
#          13라운드 Grok: 이름 glob `.spawn-tree-*` 제외는 드롭퍼가 그 이름으로 파일을 만들면 ①③ 에서 사라지게 했다. 다른 spawn 의 tree 가 같은 창에 있으면 `--allow` 로 그 경로를 준다.
#          `jobs/*/tmp/*` — 하네스가 지정한 에이전트 스크래치이며 2026-08-30 실측으로 전체 143,262 개 중 118,604 개(45GB)가 이 아래였다.
#          그대로 두면 snapshot 이 2분을 넘고 트리 파일이 20MB 라 도구가 통째로 건너뛰어진다. 대가(정직 표기): 스크래치에 숨긴 파일은 ①③ 이 못 본다.
#          숨긴 파일은 실행돼야 해를 끼치고 그 실행 경로는 bash-write-check 가 막는다는 전제로 감수했다.
#          내용 비교(2026-11-24 W13): 하네스 홈의 `plugins/store/`·`skills/synced/` 아래 일반 파일은 제외하지 않고, 스냅숏에 있던 파일의 내용 해시와 권한이 같으면 통과시킨다
#          (실행기가 같은 내용으로 다시 써서 ctime 만 바뀌는 것만 봐준다). 새 파일·내용 변경·권한 변경·심볼릭 링크(따라가지 않고 해시하지 않음)·형식 밖 해시(빈 해시 포함)·
#          해시 없는 옛 형식 tree 는 FAIL 이다. 이 폴더 판정은 append-only 분류보다 먼저 한다(`skills/synced/projects/x.jsonl` 이 줄 형식 검사로 빠지지 않게).
#          통째로 빼지 않는 까닭: 스킬·플러그인 본문이라 빼면 Bash 를 가진 검수 에이전트가 거기 써도 안 잡힌다(의뢰서 2026-11-24 개정 1 전제 표).
#       `--allow` 접두 매칭: 접두가 `/` 로 끝나면 디렉터리 접두, 아니면 그 경로와 정확히 같거나 그 아래(`…/review.md` 가 `review.mdx` 를 허용하지 않도록 — 13라운드 Grok 낮음).
#       ④ 의 timestamp 비교는 transcript 의 `Z`(UTC) ISO 문자열과 tree ctime 을 UTC 로 바꾼 문자열의 사전순 비교 — Claude Code transcript 는 항상 `Z` 표기(오프셋 표기가 섞이면 초 단위가 어긋날 수 있음, 알려진 한계).
#       ④ tree 이후 갱신된 subagent transcript(`projects/*/*/subagents/*.jsonl`) 안, tree ctime 이후 timestamp 의 Write/Edit/MultiEdit/NotebookEdit tool_use 중
#          file_path 가 `--allow` 접두 밖 — 형식 적합 위조 줄·같은 크기 덮어쓰기도 도구 호출 자체가 증거로 남아 잡힌다. 같은 창의 `mcp__*` tool_use 는 격리 spawn 의 외부 발신이라 FAIL.
#          `--main-only` 경로는 ③ 에서는 허용(main 이 라운드 사이에 append — tutor 의 quiz-search.log)하되 ④ 에서는 subagent 가 건드리면 FAIL.
#          명령 tool_use(2026-11-24 W13 2차 · 3차): `input.command` 가 있는 모든 tool_use(Bash 등)의 명령에 BASH_WATCH 배열의 파일 이름이나
#          `--main-only` 경로(받은 꼴 · 링크 푼 꼴)가 들어 있으면 FAIL. 예외는 셸 메타문자(`;` `|` `&` `<` `>` `$` 백틱 · 개행) 없는
#          `~/.claude/scripts/spawn-tree.sh snapshot|check` 한 번 호출뿐이고 끝의 ` 2>&1` 하나만 봐준다. snapshot 은 tree 파일 이름이 `.spawn-tree-` 로 시작할 때만 예외다.
#       ③ · ④ 에서 경로에 개행 · 제어 문자가 들어 있으면 허용 폴더 안이어도 바로 FAIL 이다(조각으로 갈려 허용 경로처럼 보이지 않게, 3차 T5).
#       작업 현황 파일(`<프로젝트 뿌리>/.scratch/handoff/`)은 제외하지 않는다. 다음 세션이 이 파일부터 읽으므로 에이전트가 쓴 것이 안 잡히면 지시를 심을 수 있다.
#          main 이 창 사이에 고치므로 호출 쪽이 `--main-only` 로 넘긴다(2026-11-24 W13). 예: `check <tree> --allow <산출물> --main-only "$(git rev-parse --show-toplevel)/.scratch/handoff/"`
#       출력: `FAIL …` 줄들 + 마지막 줄 `RESULT: PASS` 또는 `RESULT: FAIL n`. exit 0=PASS, 1=FAIL, 2=사용 오류. qa 는 이 출력 원문을 보고에 인용한다(자기선언 무효).
#          FAIL · INFO 줄에 찍는 경로 · 값의 제어 문자는 `?` 로 바꾼다(개행 든 이름으로 `RESULT: PASS` 줄을 심지 못하게).
#
# append-only 기대 파일과 줄 형식 (정본 — 룰·스킬 산문은 이 표를 복제하지 않는다. 실제 파일 형식 실측 기준):
#   */_audit/agent-spawn.log        ^[^\t]+\t(pre|post)\t
#   */_audit/approved-commands.log  ^[^\t]+\t[0-9a-f]{64}\t[0-9]+\t
#   */_audit/history.md             ^(#{2,3} 20YY-MM-DD 헤더 | "- " | "  " | "|" | "**" | "T41: " | "> " | 빈 줄)
#   */_evolve/crosscheck.tsv        ^[^\t]+\t[^\t]+\t[0-9]+\t[0-9]+\t
#   $HOME/.claude/projects/<프로젝트>/<세션>.jsonl · $HOME/.claude/projects/<프로젝트>/<세션>/subagents/<이름>.jsonl   ^\{.*"type":
#                                   (이 두 깊이만 transcript 다. 그 밖의 `projects/…jsonl` 은 일반 파일 — 3차 보완)
#   아래는 하네스 홈 정확 경로만(런타임 기록). tree 에 없던 이 파일이 창 안에 새로 생기면 허용 접두 대신 형식 검사만 한다(INFO, 기록기가 처음 쓰는 경우):
#   $HOME/.claude/_evolve/prompts.jsonl            키가 ts · cwd · prompt 뿐인 한 줄 JSON(scripts/prompt-log.sh:53 의 jq 키 순서). 5000줄 넘으면 3000줄로 회전 → 크기 감소 FAIL(회전 안내 붙임)
#   $HOME/.claude/_usage/propagate/pending.jsonl   키가 ts(숫자, 초 · 현재 시각 이하) · hash(9~40자) · subject · author(빈 값 또는 UUID) 뿐인 JSON + hash 가 하네스 저장소 HEAD 의 조상인 커밋
#                                                  + subject 가 그 커밋 제목 앞 200자와 같음(scripts/propagate-queue.sh:85,104). git 이 없거나 저장소가 아니면 FAIL. 500줄 넘으면 회전
#   $HOME/.claude/_usage/propagate/held.jsonl      pending 과 같은 줄 검사(커밋 훅의 보류, 2026-11-24 개정 3). main 의 release 가 비우면 크기 감소 FAIL(안내 붙임)
#   $HOME/.claude/_audit/plan-confirm-gate.tsv     ISO 시각 \t 세션 \t 도구 \t `등록 전 시작 세션이라 막지 않음: …`(scripts/plan-confirm-gate.py:389)
#   $HOME/.claude/_audit/ntfy-send.tsv             `YYYY-MM-DDTHH:MM:SSZ` + 탭 칸 5개(scripts/claude-notify.sh:255-258)
#   $HOME/.claude/_audit/agent-prompt-gate.tsv     ISO 시각 + 탭 칸 6개(scripts/agent-prompt-gate.py:102). 2MB 넘으면 앞 절반을 잘라 회전
#   $HOME/.claude/_audit/hook-deny.tsv             머리줄 `time\tsession\tcaller\thook\ttool\tstreak` 또는 `%Y-%m-%dT%H:%M:%S%z` + 탭 칸 4개 + 숫자(scripts/hook-deny-wrap.sh). 2MB 넘으면 회전
#   $HOME/.claude/_audit/oversight.tsv             `YYYY-MM-DD HH:MM` \t 프로젝트 \t 게이트(허용 어휘) \t 대상 \t 근거 \t 행위자(scripts/oversight-append.sh:12,48)
# 한계(정직 표기): 형식·해시·transcript 는 모두 "쓰기 흔적" 검사다. subagent 의 Bash 경유 쓰기는 bash-write-check 훅이 막고, 훅이 놓친 경로는 ③ 이 잡되
#   같은 크기 덮어쓰기는 ctime 으로만 보인다(내용 비교는 `plugins/store/`·`skills/synced/` 만). 내용 비교는 창 끝의 상태만 보므로 창 안에서 바꿨다 되돌린 변경은 못 본다.
#   형식을 맞춘 위조 줄(prompts · pending 등)은 줄 검사로 못 가른다. 명령 낱말 대조와 Write/Edit 도구 쓰기 검사가 보완할 뿐이다.
#   ④ 의 Write/Edit 검사는 tool_use 만 보고, 명령 검사는 파일 이름 문자열 대조라 글롭(`prompt*.jsonl`) · 인코딩 · 변수 결합 · 다른 스크립트 경유는 못 잡는다(13라운드 렌즈2, W13 2차 · 3차).
#   snapshot 이 FAIL 로 끝나면 그 tree 는 버리고 새 이름으로 다시 뜬다. 서브 에이전트의 커밋(전파 알림 심기)은 이 검사가 아니라 scripts/git-guardrails.sh 가 막는다(2026-11-24).
#   ④ 예외로 통과하는 `snapshot` 은 `.spawn-tree-` 이름이면 어느 폴더에나 새 파일을 만들 수 있다(이미 있으면 거부하므로 덮어쓰기는 못 한다).
#   추가된 줄마다 jq · git 을 띄우므로 줄이 수만 개면 check 가 오래 걸린다. 호출 쪽은 출력에 `RESULT:` 줄이 없으면(중단 · 시간 초과) FAIL 로 본다.
#   SPAWN_TREE_HOME 은 자체 테스트용 오버라이드 — 실운용 spawn prompt 에 env 를 넣지 않는다.
# REF: knowledge/harness/code-history/scripts__spawn-tree.sh.md
set -uf
export LC_ALL=C
# WHY: 심볼릭 링크 root 는 반드시 풀어서 쓴다 (2026-08-30 실사고): `~/.claude` 는 `~/workspace/.claude`
# 링크라 `find ~/.claude -type f` 가 링크 자신 1건만 반환하고 트리로 내려가지 않는다. 그대로 두면
# snapshot 이 "1 files" 로 만들어지고 check 가 사실상 아무것도 안 보면서 RESULT: PASS 를 낸다.
# 같은 날 온톨로지 파이프라인에서 확인된 것과 같은 계열의 결함이다.
resolve_root() { readlink -f -- "$1" 2>/dev/null || printf '%s' "$1"; }
HOMEC=$(resolve_root "${SPAWN_TREE_HOME:-$HOME/.claude}")
MODE="${1:-}"; [ $# -gt 0 ] && shift
TREE="${1:-}"; [ $# -gt 0 ] && shift
# NEVER: TREE 를 상대 경로로 두지 않는다. find 출력(절대)과 형태가 달라 자기 제외가 걸리지 않는다
[ -n "$TREE" ] && TREE=$(resolve_root "$TREE")
usage() { echo "usage: spawn-tree.sh snapshot <tree> <root>... | check <tree> --expect-marker <inode>:<ctime> [--allow <abs-prefix>]... [--main-only <abs-path>]... [--allow-mcp <mcp__prefix>]..."; exit 2; }
[ -n "$MODE" ] && [ -n "$TREE" ] || usage
clean() { local s="$*"; printf '%s' "${s//[[:cntrl:]]/?}"; }

# WHY: 내용 비교 폴더(2026-11-24 W13, 헤더 ③): 하네스 홈 고정 접두만 — 이름 glob 금지 원칙은 면제와 같다. ao_kind 보다 먼저 판정한다
content_dir() { case "$1" in "$HOMEC/plugins/store/"*|"$HOMEC/skills/synced/"*) return 0 ;; esac; return 1; }
content_sig() { local h m; h=$(sha256sum < "$1" 2>/dev/null | cut -c1-64); m=$(stat -c %a -- "$1" 2>/dev/null); printf '%s:%s' "$h" "$m"; }   # NEVER: `-f && ! -L` 확인 없이 부르지 않는다(링크는 따라가지 않는다)
SIG_RX='^[0-9a-f]{64}:[0-7]{1,4}$'
RT_KINDS=" prompts pending held plancg ntfysend apgate hookdeny oversight "   # REF: 머리 주석의 append-only 형식 표(하네스 홈 정확 경로의 런타임 기록)
ao_kind() {
    content_dir "$1" && { echo ""; return; }
    # WHY: transcript 는 하네스 홈의 실제 세션 기록 두 깊이만(3차 보완): 모든 깊이 `*/projects/*.jsonl` 은 저장소 안 시험 사본의 링크까지 append-only 로 잡아 창마다 FAIL 을 냈다
    if [[ "$1" =~ ^"$HOMEC"/projects/[^/]+/[^/]+\.jsonl$ || "$1" =~ ^"$HOMEC"/projects/[^/]+/[^/]+/subagents/[^/]+\.jsonl$ ]]; then echo transcript; return; fi
    case "$1" in
        "$HOMEC/_evolve/prompts.jsonl") echo prompts ;;
        "$HOMEC/_usage/propagate/pending.jsonl") echo pending ;;
        "$HOMEC/_usage/propagate/held.jsonl") echo held ;;
        "$HOMEC/_audit/plan-confirm-gate.tsv") echo plancg ;;
        "$HOMEC/_audit/ntfy-send.tsv") echo ntfysend ;;
        "$HOMEC/_audit/agent-prompt-gate.tsv") echo apgate ;;
        "$HOMEC/_audit/hook-deny.tsv") echo hookdeny ;;
        "$HOMEC/_audit/oversight.tsv") echo oversight ;;
        */_audit/agent-spawn.log) echo spawnlog ;;
        */_audit/approved-commands.log) echo approved ;;
        */_audit/history.md) echo history ;;
        */_evolve/crosscheck.tsv) echo crosscheck ;;
        *) echo "" ;;
    esac
}
LINE_WHY=""
pending_line_ok() {
    local h s g
    command -v jq >/dev/null 2>&1 || { LINE_WHY="jq 없음"; return 1; }
    command -v git >/dev/null 2>&1 || { LINE_WHY="git 없음"; return 1; }
    printf '%s' "$1" | jq -e 'type=="object" and keys_unsorted==["ts","hash","subject","author"] and (.ts|type)=="number" and (.hash|type)=="string"
        and (.subject|type)=="string" and (.author|type)=="string" and (.author=="" or (.author|test("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")))' >/dev/null 2>&1 \
        || { LINE_WHY="JSON 형식 밖(키는 ts · hash · subject · author 뿐)"; return 1; }
    printf '%s' "$1" | jq -e '.ts <= now' >/dev/null 2>&1 || { LINE_WHY="ts 가 현재 시각보다 미래(기록기는 date +%s 초)"; return 1; }
    h=$(printf '%s' "$1" | jq -r '.hash' 2>/dev/null)
    s=$(printf '%s' "$1" | jq -r '.subject' 2>/dev/null)
    [[ "$h" =~ ^[0-9a-f]{9,40}$ ]] || { LINE_WHY="hash 형식 밖(기록기는 --short=9)"; return 1; }
    git -C "$HOMEC" cat-file -e "$h^{commit}" 2>/dev/null || { LINE_WHY="하네스 저장소에 없는 커밋(또는 저장소 아님)"; return 1; }
    # WHY: dangling(commit-tree) · 다른 브랜치 커밋으로 제목을 맞춘 위조 줄을 막는다(W13 3차 보안 검토)
    git -C "$HOMEC" merge-base --is-ancestor "$h" HEAD 2>/dev/null || { LINE_WHY="HEAD 의 조상이 아닌 커밋"; return 1; }
    g=$(git -C "$HOMEC" log -1 --format=%s "$h" 2>/dev/null) || { LINE_WHY="커밋 제목을 못 읽음"; return 1; }
    jq -en --arg g "$g" --arg s "$s" '$g[0:200] == $s' >/dev/null 2>&1 || { LINE_WHY="subject 가 커밋 제목과 다름"; return 1; }
}
line_ok() {
    case "$1" in
        spawnlog)   printf '%s\n' "$2" | grep -qE $'^[^\t]+\t(pre|post)\t' ;;
        approved)   printf '%s\n' "$2" | grep -qE $'^[^\t]+\t[0-9a-f]{64}\t[0-9]+\t' ;;
        history)    printf '%s\n' "$2" | grep -qE '^(#{2,3} 20[0-9]{2}-[0-9]{2}-[0-9]{2}|- |  |\||\*\*|T41: |> |$)' ;;
        crosscheck) printf '%s\n' "$2" | grep -qE $'^[^\t]+\t[^\t]+\t[0-9]+\t[0-9]+\t' ;;
        transcript) printf '%s\n' "$2" | grep -qE '^\{.*"type":' ;;
        prompts)    printf '%s\n' "$2" | grep -qE '^\{"ts":"[^"]*","cwd":"([^"\\]|\\.)*","prompt":"([^"\\]|\\.)*"\}$' ;;
        pending|held) pending_line_ok "$2" ;;
        plancg)     printf '%s\n' "$2" | grep -qE $'^[0-9]{4}-[0-9]{2}-[0-9]{2}T[^\t]+\t[^\t]*\t[^\t]*\t등록 전 시작 세션이라 막지 않음: [^\t]*$' ;;
        ntfysend)   printf '%s\n' "$2" | grep -qE $'^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z(\t[^\t]*){5}$' ;;
        apgate)     printf '%s\n' "$2" | grep -qE $'^[0-9]{4}-[0-9]{2}-[0-9]{2}T[^\t]+(\t[^\t]*){6}$' ;;
        hookdeny)   printf '%s\n' "$2" | grep -qE $'^(time\tsession\tcaller\thook\ttool\tstreak|[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}[+-][0-9]{4}(\t[^\t]*){4}\t[0-9]+)$' ;;
        oversight)  printf '%s\n' "$2" | grep -qE $'^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}\t[^\t]*\t(commit|launch|external-send|publish|data-change|deploy|audit|approve|delete|other)(\t[^\t]*){3}$' ;;
        *) return 0 ;;
    esac
}
rot_hint() {
    case "$1" in
        prompts) printf ' — prompt-log 회전일 수 있음, 스냅숏을 다시 뜬다' ;;
        pending) printf ' — propagate-queue 회전(500줄 초과)일 수 있음, 스냅숏을 다시 뜬다' ;;
        held)    printf ' — propagate-queue release(보류 비움) 또는 회전(500줄 초과)일 수 있음, 스냅숏을 다시 뜬다' ;;
        apgate)  printf ' — agent-prompt-gate 회전(2MB 초과)일 수 있음, 스냅숏을 다시 뜬다' ;;
        hookdeny) printf ' — hook-deny-wrap 회전(2MB 초과)일 수 있음, 스냅숏을 다시 뜬다' ;;
    esac
}
prefix_sha() { head -c "$2" -- "$1" 2>/dev/null | sha256sum | cut -c1-64; }
# WHY: 런타임이 창 안에서 스스로 쓰는 경로 (2026-08-30 실측으로 확정 — 첫 실사용에서 16건이 전부 이것이었다).
# 검사 대상 spawn 이 만지는 파일이 아니라 하네스·git·에이전트 런타임이 항상 건드리는 것들이라 남겨 두면
# 정상 쓰기가 FAIL 로 잡히고, 그러면 스캔 자체를 무시하게 된다(8라운드 Grok 이 지적한 실패 모드).
# `.git` 은 통째로 빼지 않는다 — `hooks/`·`config` 는 지속형 백도어 자리라 계속 본다(6라운드 렌즈2). 내용 주소 저장소와 ref 만 뺀다.
# 2026-10-01 감사: 면제는 «하네스 홈($HOMEC) 고정 접두»다. 맨 앞 `*/` 로 쓰면 어느 깊이에든 그 이름의 폴더만 만들면
# 거기 아래 쓰기가 ①③ 에서 빠졌다(위 «이름 glob 금지» 원칙과 반대였다).
RUNTIME_EXEMPT=(
    -not -path "$HOMEC/_usage/*-last"
    -not -path "$HOMEC/.git/index" -not -path "$HOMEC/.git/objects/*" -not -path "$HOMEC/.git/refs/*"
    -not -path "$HOMEC/.git/logs/*" -not -path "$HOMEC/.git/COMMIT_EDITMSG" -not -path "$HOMEC/.git/ORIG_HEAD"
    -not -path "$HOMEC/jobs/*/tmp/*" -not -path "$HOMEC/jobs/*/state.json" -not -path "$HOMEC/jobs/*/timeline.jsonl"
    -not -path "$HOMEC/_cache/read-once/*"
    -not -path "$HOMEC/projects/*/*.meta.json" -not -path "$HOMEC/projects/*/*/subagents/*.meta.json"
    -not -path "$HOMEC/teams/*"
    -not -path "$HOMEC/tools/mem-guard/mem-watch.log" -not -path "$HOMEC/tools/mem-guard/mem-watch.state"
)
# WHY: 2026-11-24 W13: 실행 중 저절로 바뀌어 창마다 FAIL(79·39·21건)을 낸 기록 파일류. 일반 파일에만 적용한다(아래 FIND_EXEMPT 의 `-type f`).
# 이름은 쓰는 코드와 실제 폴더 목록으로 정했다. 이 밖은 더하지 않는다(제외는 숨을 자리가 된다). 2차(보안 검토)에서
# `_evolve/prompts.jsonl` · `_usage/propagate/pending.jsonl` 은 제외를 거두고 append-only 기대 파일(ao_kind)로 옮겼다.
# 폴더 묶음은 `-path X/*` 와 `-not -path X/*/*` 로 깊이를 한 단계로 묶고 `-name` 으로 이름을 고른다(`-path` 의 `*` 는 `/` 를 넘는다).
H='[0-9a-f]'
UUID_GLOB="$H$H$H$H$H$H$H$H-$H$H$H$H-$H$H$H$H-$H$H$H$H-$H$H$H$H$H$H$H$H$H$H$H$H"
D8='[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'
D10='[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'   # REF: scripts/usage-log.sh:50 · scripts/hook-deny-wrap.sh:275-276 의 YYYY-MM-DD 파일 이름(글자 하나짜리 괄호뿐이라 `/` 를 넘지 않는다)
W13_EXEMPT=(
    \( -path "$HOMEC/backups/*" -not -path "$HOMEC/backups/*/*" -name '.claude.json.backup.[0-9]*' \)   # WHY: 실행기(Claude Code)의 설정 백업(~/.claude/backups/)
    # WHY: 감사 기록 plan-confirm-gate.tsv · ntfy-send.tsv · agent-prompt-gate.tsv · hook-deny.tsv · oversight.tsv 는 3차(security N4)에서 append-only(ao_kind)로 옮겼다
    -o -path "$HOMEC/_audit/agent-prompts/.last-prune"    # REF: scripts/agent-spawn-log.sh:93
    -o \( -path "$HOMEC/_audit/agent-prompts/$D8/*" -not -path "$HOMEC/_audit/agent-prompts/*/*/*" -name '*.txt' \)   # REF: scripts/agent-spawn-log.sh:110 (<날짜>/<시각>.<PID>-<세션>-<타입>.txt)
    -o -path "$HOMEC/_audit/hook-deny.tsv.lock"           # REF: scripts/hook-deny-wrap.sh 의 "$log.lock" (잠금. 그 파일은 다른 작업이 고치는 중이라 줄 번호 생략)
    -o \( -path "$HOMEC/_audit/*" -not -path "$HOMEC/_audit/*/*" -name '.hook-deny.??????' \)   # REF: scripts/hook-deny-wrap.sh 의 mktemp "$audit/.hook-deny.XXXXXX" (회전 임시 파일)
    -o \( -path "$HOMEC/_cache/hook-deny/*" -not -path "$HOMEC/_cache/hook-deny/*/*" \( -name '*.*.*' -o -name .pruned -o -name '.tmp.??????' \) \)   # REF: scripts/hook-deny-wrap.sh 의 cf="$cdir/<세션>.<호출 주체>.<훅>" · mark .pruned · mktemp "$cdir/.tmp.XXXXXX"
    -o \( -path "$HOMEC/_cache/band/*" -not -path "$HOMEC/_cache/band/*/*" \( -name server.json -o -name server.lock -o -name server.attempt -o -name server.inflight -o -name server.watched \
          -o -name work_ps.inflight -o -name 'server.json.????????' -o -name 'server.attempt.????????' -o -name 'server.inflight.????????' -o -name 'server.watched.????????' \
          -o -name 'work_ps.inflight.????????' \) \)   # REF: scripts/band_server_collect.py:92,109,1049,1068-1074 · scripts/band_work_collect.py:283,304 (mkstemp 임시 이름 포함)
    -o \( -path "$HOMEC/_usage/*" -not -path "$HOMEC/_usage/*/*" \( -name "ntfy-$D8.count" -o -name "ntfy-$D8.halt" -o -name "ntfy-$D8.failopen" -o -name ntfy-cap -o -name ntfy-queue.tsv \
          -o -name ntfy-queue.tsv.spill -o -name 'ntfy-queue.tsv.spill.[0-9]*' -o -name ntfy-budget.lock -o -name ntfy-flush.lock -o -name ntfy-flush.backoff \
          -o -name '.ntfy-queue.??????' -o -name '.ntfy-body.??????' \) \)   # REF: scripts/claude-notify.sh:229-245,310,331,607 · scripts/ntfy-flush.sh:35,64,77,86
    -o -path "$HOMEC/_usage/skill-usage.tsv" -o -path "$HOMEC/_usage/skill-usage.tsv.lock"   # REF: scripts/skill-usage-log.sh:21,28 (W10 스킬 계측 · flock 잠금)
    -o -path "$HOMEC/tools/mem-guard/oom-watch.state"     # REF: tools/mem-guard/oom-watch.py:243
    -o \( -path "$HOMEC/projects/*/$UUID_GLOB/tool-results/*" -not -path "$HOMEC/projects/*/*/*/tool-results/*" \)   # WHY: 실행기(세션 폴더의 긴 도구 결과 ~/.claude/projects/*/<세션>/tool-results/, 세션 폴더가 UUID 꼴일 때만)
    -o \( -path "$HOMEC/_usage/articles-watch/*" -not -path "$HOMEC/_usage/articles-watch/*/*" \( -name ledger.tsv -o -name last-check.json -o -name check-attempt -o -name .lock \
          -o -name '.ledger.tsv.????????' -o -name '.last-check.json.????????' \) \)   # REF: scripts/articles_watch.py:202,219,255,266 · scripts/harness-usage-check.sh:808
    -o -path "$HOMEC/_usage/propagate/.lock" -o -path "$HOMEC/_usage/propagate/pending.jsonl.tmp"   # REF: scripts/propagate-queue.sh:28,104 (잠금 · 회전 임시 파일)
    -o -path "$HOMEC/_usage/propagate/held.jsonl.tmp"     # REF: scripts/propagate-queue.sh cmd_enqueue (held.jsonl 회전 임시 파일)
    -o -path "$HOMEC/_usage/propagate/ack/$UUID_GLOB"     # REF: scripts/propagate-queue.sh:116 · mods/harness-mod/hooks/band/propagate.js:2-3 (받음 기록)
    -o -path "$HOMEC/_usage/propagate/asleep/$UUID_GLOB"  # REF: mods/harness-mod/hooks/register.js:179,185 (첫 지시 전 표지)
    -o -path "$HOMEC/_usage/propagate/blocked/$UUID_GLOB" # REF: scripts/propagate-gate.sh:39,90 (막힘 기록)
    -o -path "$HOMEC/file-history/*"                      # WHY: 실행기(편집 전 사본 ~/.claude/file-history/, 그 아래 모든 깊이)
    -o \( -path "$HOMEC/sessions/*" -not -path "$HOMEC/sessions/*/*" -name '*.json' \)   # WHY: 실행기(세션 메타, ~/.claude/sessions/ 바로 아래 .json 만)
    # WHY: 3차 T8: 쓰는 곳과 읽는 곳을 둘 다 보고, 저절로 쓰이고 읽는 쪽이 모델 맥락 · 차단 판정에 쓰지 않는 것만
    -o -path "$HOMEC/_usage/candidates-attach-retry.lock" # REF: scripts/candidates-append.sh:429 · scripts/harness-usage-check.sh:339 (flock 잠금, 내용을 읽지 않음)
    -o -path "$HOMEC/tools/mem-guard/memguard.log"        # REF: tools/mem-guard/memguard-run.sh:74 (읽는 코드 없음)
    -o -path "$HOMEC/_usage/band-diag-$UUID_GLOB.json"    # REF: mods/harness-mod/hooks/register.js:227 (띠 상한 진단, 읽는 코드 없음)
    -o -path "$HOMEC/_usage/login-expiry" -o \( -path "$HOMEC/_usage/*" -not -path "$HOMEC/_usage/*/*" -name 'login-expiry.tmp.??????' \)   # REF: scripts/login-expiry-export.sh:10-11 · 띠 표시만(register.js:459)
    -o -path "$HOMEC/_usage/crosscheck-auto-attempt"      # REF: scripts/harness-usage-check.sh:310 (mtime 으로 재시도 간격만 봄. -last 는 위 `_usage/*-last`)
    # WHY: W14(2026-11-24) 상세 기록은 훅 · 도구 호출마다 한 줄씩 늘어 모든 검사 창에서 헛 FAIL 을 냈다(qa 실측 `_usage/hook-runs/2026-11-24.tsv`). 폴더 바로 아래 날짜 이름 일반 파일만 뺀다.
    # 이름 칸은 기록기가 [A-Za-z0-9_.:-] 로 거른다(scripts/hook-deny-wrap.sh:255-260 · scripts/usage-log.sh:40 · scripts/usage_log_agent.py:29-35).
    # 읽는 쪽 scripts/harness-usage-check.sh:876-893(HOOK_ERRORS_24H)은 훅 이름을 다시 걸러 «이름=건수» 경보 한 줄로 세션 시작 맥락에 싣고 차단 판정에는 쓰지 않는다.
    # scripts/harness_log_report.py:35-47 은 사람이 부르는 보고라 칸을 다시 거르지 않는다(기록기를 거치지 않은 위조 줄이면 표 칸에 그대로 찍힌다).
    -o -path "$HOMEC/_usage/hook-runs/$D10.tsv"           # REF: scripts/hook-deny-wrap.sh:270-283 · scripts/usage-log.sh:174
    -o -path "$HOMEC/_usage/tool-use/$D10.tsv"            # REF: scripts/usage-log.sh:110
    -o -path "$HOMEC/_usage/rule-reads/$D10.tsv"          # REF: scripts/usage-log.sh:85
    -o -path "$HOMEC/_usage/agent-runs/$D10.tsv"          # REF: scripts/usage-log.sh:98 · scripts/usage_log_agent.py:83
    -o -path "$HOMEC/_usage/session-events/$D10.tsv"      # REF: scripts/usage-log.sh:128
    -o -path "$HOMEC/_usage/.harness-logs-pruned"         # REF: scripts/harness-usage-check.sh:897,912 (180일 정리 표지, 같은 파일 899 가 날짜만 읽음)
)
FIND_EXEMPT=("${RUNTIME_EXEMPT[@]}" -not \( -type f \( "${W13_EXEMPT[@]}" \) \))
# WHY: ④ 명령 문자열 대조 목록(W13 2차 · 3차): 지시를 심거나 승인 인용을 위조할 수 있는 실행 기록과 그 기록기의 파일 이름만(경로 꼴은 상대 경로 · 변수 결합으로 비켜 간다, security N2)
BASH_WATCH=("prompts.jsonl" "pending.jsonl" "held.jsonl" "prompt-log" "propagate-queue" "ntfy-queue" "ledger.tsv"
            # WHY: 3차에서 append-only 로 옮긴 감사 기록과 정식 기록기 — 기록기를 직접 부르면 형식이 맞는 줄이 append-only 검사를 통과하므로 이름 대조로 막는다
            "oversight-append" "oversight.tsv" "claude-notify" "ntfy-send" "ntfy-flush" "plan-confirm-gate" "agent-prompt-gate" "hook-deny")
list_files() {  # NEVER: 이름 glob 제외를 넣지 않는다(13라운드 Grok). 제외는 이번 tree 파일 자신(정확 경로)과 위 런타임 목록뿐
    find "$@" \( -type f -o -type l \) -not -path "$TREE" "${FIND_EXEMPT[@]}" -printf '%p\t%s\n' 2>/dev/null | sort
}

if [ "$MODE" = snapshot ]; then
    [ $# -ge 1 ] || { echo "snapshot: root 1개 이상 필요"; usage; }
    [ -e "$TREE" ] && { echo "이미 존재: $TREE — spawn 마다 새 이름을 쓴다"; exit 2; }
    # NEVER: root 를 링크 그대로 헤더에 적지 않는다(링크를 푼 형태로 고정) — check 가 같은 형태로 다시 걷도록(위 resolve_root 주석)
    ROOTS_R=()
    for r in "$@"; do
        [ -d "$r" ] || { echo "root 아님: $r"; exit 2; }
        ROOTS_R+=("$(resolve_root "$r")")
    done
    set -- "${ROOTS_R[@]}"
    {
        printf '# roots:'; for r in "$@"; do printf '\t%s' "$r"; done; printf '\n'
        printf '# format:\t2\n'
        list_files "$@" | while IFS=$'\t' read -r p s; do
            if content_dir "$p"; then
                if [ -f "$p" ] && [ ! -L "$p" ]; then h="c:$(content_sig "$p")"; else h=-; fi
            else
                k=$(ao_kind "$p")
                if [ -z "$k" ]; then h=-; elif [ -L "$p" ]; then h="link"; else h=$(prefix_sha "$p" "$s"); fi   # NEVER: append-only 자리의 링크는 따라가지 않는다(② 에서 FAIL)
            fi
            printf '%s\t%s\t%s\n' "$p" "$s" "$h"
        done
    } > "$TREE"
    N=$(grep -vc '^#' "$TREE")
    echo "snapshot: ${N} files → $TREE  (마커=이 파일: $(stat -c 'inode=%i ctime=%Z' "$TREE"))"
    echo "  check 에 붙일 값: --expect-marker $(stat -c '%i:%Z' "$TREE")"
    BAD=$(awk -F'\t' '$3 ~ /^c:/ { print $3 "\t" $1 }' "$TREE" | grep -vE $'^c:[0-9a-f]{64}:[0-7]{1,4}\t' | cut -f2-)
    if [ -n "$BAD" ]; then
        while IFS= read -r p; do echo "FAIL 내용 해시 계산 실패(읽기 불가 등): $(clean "$p")"; done <<< "$BAD"
        echo "snapshot: FAIL — 이 tree 로 check 하면 그 파일은 FAIL 이다. 원인을 고친 뒤 새 이름으로 다시 뜬다"
        exit 1
    fi
    sleep 1   # WHY: ctime 은 정수 초 — 같은 초 안의 쓰기가 "더 새롭지 않다"로 판정되는 경합을 닫는다(15라운드 렌즈2 낮음)
    exit 0
fi

[ "$MODE" = check ] || usage
[ -s "$TREE" ] || { echo "tree 없음/비어 있음: $TREE"; exit 2; }
ALLOW=(); MAINONLY=(); MAINONLY_RAW=(); ALLOW_MCP=(); EXPECT=""
# NEVER: 허용 접두를 root 와 다른 형태로 두지 않는다(링크 푼 절대 경로로 맞춘다) — 형태가 다르면 정상 쓰기가 "허용 밖"으로 잡힌다.
# 끝의 `/`는 디렉터리 접두를 뜻하므로 resolve 뒤에 되붙인다(under 의 판정 규칙).
norm_prefix() {
    local p="$1" tail="" r
    case "$p" in */) tail="/" ;; esac
    r=$(readlink -f -- "$p" 2>/dev/null) || r=""
    [ -n "$r" ] || r="${p%/}"
    printf '%s%s' "$r" "$tail"
}
while [ $# -gt 0 ]; do
    case "$1" in
        --allow)     [ $# -ge 2 ] || usage; case "$2" in /*) ALLOW+=("$(norm_prefix "$2")") ;; *) echo "--allow 는 절대 경로 접두만: $2"; exit 2 ;; esac; shift 2 ;;
        --main-only) [ $# -ge 2 ] || usage; case "$2" in /*) MAINONLY+=("$(norm_prefix "$2")"); MAINONLY_RAW+=("$2") ;; *) echo "--main-only 는 절대 경로만: $2"; exit 2 ;; esac; shift 2 ;;
        --allow-mcp) [ $# -ge 2 ] || usage
                     # WHY: 서버 단위 접두(`mcp__<서버>__`)만 — `mcp__` 단독은 전면 스위치로 되돌아가므로 거부 (16라운드 Grok)
                     if [[ "$2" =~ ^mcp__[A-Za-z0-9_-]+__$ ]]; then ALLOW_MCP+=("$2"); else echo "--allow-mcp 는 서버 접두 mcp__<서버>__ 형식만(예: mcp__mem0__): $2"; exit 2; fi; shift 2 ;;
        --expect-marker) [ $# -ge 2 ] || usage
                     if [[ "$2" =~ ^[0-9]+:[0-9]+$ ]]; then EXPECT="$2"; else echo "--expect-marker 는 <inode>:<ctime> 숫자 꼴만(snapshot 출력값): $2"; exit 2; fi; shift 2 ;;
        *) echo "알 수 없는 인자: $1"; usage ;;
    esac
done
[ -n "$EXPECT" ] || { echo "--expect-marker 는 필수다(snapshot 출력의 «check 에 붙일 값» 을 그대로 붙인다)"; usage; }
mcp_allowed() { local n="$1" a; for a in ${ALLOW_MCP[@]+"${ALLOW_MCP[@]}"}; do case "$n" in "$a"*) return 0 ;; esac; done; return 1; }
IFS=$'\t' read -r -a HDR < "$TREE"
[ "${HDR[0]}" = "# roots:" ] && [ ${#HDR[@]} -ge 2 ] || { echo "tree 헤더 손상(# roots: 없음): $TREE"; exit 2; }
ROOTS=("${HDR[@]:1}")
FAIL=0
fail() { printf 'FAIL %s\n' "$(clean "$*")"; FAIL=$((FAIL + 1)); }
under() {
    case "$2" in
        */) case "$1" in "$2"*) return 0 ;; esac ;;
        *)  [ "$1" = "$2" ] && return 0; case "$1" in "$2"/*) return 0 ;; esac ;;
    esac
    return 1
}
allowed_file() { local p="$1" a; for a in ${ALLOW[@]+"${ALLOW[@]}"} ${MAINONLY[@]+"${MAINONLY[@]}"}; do under "$p" "$a" && return 0; done; return 1; }
allowed_sub()  { local p="$1" a; for a in ${ALLOW[@]+"${ALLOW[@]}"}; do under "$p" "$a" && return 0; done; return 1; }

CUR_MARK=$(stat -c '%i:%Z' -- "$TREE")
[ "$CUR_MARK" = "$EXPECT" ] || fail "마커 불일치(tree 가 바뀌었거나 다른 tree): 기대 $EXPECT · 현재 $CUR_MARK"
grep -qx $'# format:\t2' "$TREE" || echo "WARN 옛 형식 tree(format 표지 없음): 내용 비교 폴더와 prompts · pending 기록은 비교할 해시가 없어 바뀌면 FAIL 로 본다 — 새 스크립트로 snapshot 을 다시 뜬다"

NOW=$(mktemp); OLDP=$(mktemp); NEWP=$(mktemp); TB=$(mktemp)
trap 'rm -f "$NOW" "$OLDP" "$NEWP" "$TB"' EXIT
grep -v '^#' "$TREE" > "$TB"
list_files "${ROOTS[@]}" > "$NOW"
cut -f1 "$TB" | sort > "$OLDP"
cut -f1 "$NOW" | sort > "$NEWP"
# NEVER: 형식 밖 `c:` 내용 해시를 통과시키지 않는다(바로 FAIL). 빈 해시끼리 같다고 통과하지 않게 한다. 그 밖의 해시칸은 append-only 접두 해시
declare -A CHASH=() AOH=()
while IFS=$'\t' read -r p _ h; do
    case "$h" in
        -) ;;
        c:*) v="${h#c:}"; if [[ "$v" =~ $SIG_RX ]]; then CHASH["$p"]="$v"; else fail "tree 의 내용 해시 형식 밖(빈 해시 등): $p"; fi ;;
        *) AOH["$p"]="$h" ;;
    esac
done < "$TB"

while IFS= read -r p; do [ -n "$p" ] && fail "사라진 파일: $p"; done < <(comm -23 "$OLDP" "$NEWP")

while IFS=$'\t' read -r p s h; do
    case "$h" in -|c:*) continue ;; esac
    if [ -L "$p" ] || [ "$h" = link ]; then fail "append-only 기대 파일 자리가 심볼릭 링크(따라가지 않음): $p"; continue; fi
    [ -f "$p" ] || continue
    k=$(ao_kind "$p")
    ns=$(stat -c %s -- "$p")
    if [ "$ns" -lt "$s" ]; then fail "append-only 크기 감소: $p ${s}→${ns}$(rot_hint "$k")"; continue; fi
    nh=$(prefix_sha "$p" "$s")
    [ "$nh" = "$h" ] || fail "append-only 접두 변경: $p (마커 시점 ${s}B 의 sha256 불일치 — 기존 줄이 바뀌었거나 재작성됨)$(rot_hint "$k")"
    if [ "$ns" -gt "$s" ]; then
        n=0; skip=0
        # NEVER: 접두 마지막 바이트가 개행이 아닐 때 추가분 첫 조각을 형식 판정하지 않는다. 기존 줄의 꼬리다
        [ "$s" -gt 0 ] && [ "$(head -c "$s" -- "$p" | tail -c 1 | od -An -tx1 | tr -d ' \n')" != "0a" ] && skip=1
        while IFS= read -r line || [ -n "$line" ]; do   # WHY: 끝 줄에 개행이 없어도 검사한다(3차 T4)
            if [ "$skip" -eq 1 ]; then skip=0; continue; fi
            LINE_WHY=""
            line_ok "$k" "$line" || { n=$((n + 1)); [ "$n" -le 3 ] && fail "append-only 형식 밖 줄: $p: ${line:0:100}${LINE_WHY:+ ($LINE_WHY)}"; }
        done < <(tail -c +$((s + 1)) -- "$p")
        [ "$n" -gt 3 ] && echo "  (형식 밖 줄 ${n}건 중 3건만 표시)"
    fi
done < "$TB"

while IFS= read -r -d '' p; do
    [ -n "$p" ] || continue
    # WHY: 개행 · 제어 문자가 든 경로는 허용 폴더 안이어도 바로 FAIL(조각으로 갈려 허용 경로처럼 보이지 않게, 3차 T5)
    case "$p" in *[[:cntrl:]]*) fail "경로에 제어 문자(개행 등) — 바로 FAIL: $p"; continue ;; esac
    if content_dir "$p"; then
        allowed_file "$p" && continue
        if [ -L "$p" ] || [ ! -f "$p" ]; then fail "내용 비교 폴더의 링크·비정규 파일 변경(따라가지 않음): $p"
        elif [ -z "${CHASH[$p]+x}" ]; then
            if grep -qxF -- "$p" "$OLDP"; then fail "내용 비교 폴더 변경, 스냅숏에 내용 해시 없음(옛 형식 tree 또는 스냅숏 때 링크): $p"
            else fail "내용 비교 폴더의 새 파일: $p"; fi
        else
            cur=$(content_sig "$p")
            if ! [[ "$cur" =~ $SIG_RX ]]; then fail "내용 비교 폴더의 현재 해시 계산 실패: $p"
            elif [ "$cur" != "${CHASH[$p]}" ]; then fail "내용 비교 폴더의 내용 또는 권한 변경: $p"; fi
        fi
        continue
    fi
    k=$(ao_kind "$p")
    if [ -n "$k" ]; then
        if ! grep -qxF -- "$p" "$OLDP"; then
            # WHY: 신규 append-only 형식 파일: 형식 검사는 **추가** 조건이지 허용 접두의 대체가 아니다 (13라운드 렌즈2: 형식만 맞춘 `…/z/_audit/history.md` 신설이 통과했다).
            # 예외는 런타임이 스스로 만드는 transcript 의 **실제 깊이**만 — `projects/<proj>/<session>.jsonl`·`projects/<proj>/<session>/subagents/<agent>.jsonl`
            # (14라운드 렌즈2: case 의 `*` 는 `/` 를 넘어가 임의 깊이의 위조 .jsonl 도 면제됐다). 예외 파일도 INFO 로 남겨 창 안 신설을 보이게 한다.
            # 하네스 홈 정확 경로의 런타임 기록(RT_KINDS)도 기록기가 처음 쓸 때 생기므로 같은 예외로 둔다(3차, 형식 검사만).
            if [ -L "$p" ]; then fail "append-only 기대 파일 자리가 심볼릭 링크(따라가지 않음): $p"; continue; fi
            if [[ "$p" =~ ^"$HOMEC"/projects/[^/]+/[^/]+\.jsonl$ || "$p" =~ ^"$HOMEC"/projects/[^/]+/[^/]+/subagents/[^/]+\.jsonl$ ]]; then
                echo "INFO 런타임 transcript 신설(형식 검사만): $(clean "$p")"
            elif [[ "$RT_KINDS" == *" $k "* ]]; then
                echo "INFO 런타임 기록 신설(형식 검사만): $(clean "$p")"
            else
                allowed_file "$p" || fail "허용 밖 신규 append-only 형식 파일: $p"
            fi
            n=0
            while IFS= read -r line || [ -n "$line" ]; do
                LINE_WHY=""
                line_ok "$k" "$line" || { n=$((n + 1)); [ "$n" -le 3 ] && fail "신규 append-only 파일 형식 밖 줄: $p: ${line:0:100}${LINE_WHY:+ ($LINE_WHY)}"; }
            done < "$p"
        elif [ -z "${AOH[$p]+x}" ]; then
            fail "append-only 기대 파일인데 스냅숏에 접두 해시 없음(옛 형식 tree): $p"
        fi
        continue
    fi
    allowed_file "$p" || fail "허용 밖 변경(ctime>마커): $p"
done < <(find "${ROOTS[@]}" \( -type f -o -type l \) -cnewer "$TREE" -not -path "$TREE" "${FIND_EXEMPT[@]}" -print0 2>/dev/null | sort -zu)

# WHY: ④ subagent transcript 의 Write/Edit tool_use 경로 + Bash 명령 문자열 + MCP 호출 (tree ctime 이후 timestamp 만)
#    MCP: 이 검사가 쓰이는 spawn(paper-read researcher·qa·docs·tutor)은 `rules-lazy/untrusted-quarantine.md` §4 로 외부 발신·MCP 가 금지된 격리 spawn 이다.
#    도구 권한을 spawn 단위로 뗄 수 없으므로 transcript 의 `mcp__*` tool_use 를 FAIL 로 잡는다(14라운드 렌즈2: 파일시스템 감사만으로는 Confluence 생성 같은 발신을 못 봤다). `--allow-mcp` 로만 해제.
NEEDLES=("${BASH_WATCH[@]}")
for x in ${MAINONLY_RAW[@]+"${MAINONLY_RAW[@]}"} ${MAINONLY[@]+"${MAINONLY[@]}"}; do x="${x%/}"; [ -n "$x" ] && NEEDLES+=("$x"); done
spawn_tree_only() {
    local -a w; local i=0 c="$1"
    [[ "$c" =~ ^(.*[^[:space:]])[[:space:]]+2\>\&1[[:space:]]*$ ]] && c="${BASH_REMATCH[1]}"
    case "$c" in *[\;\|\&\<\>\$\`]*|*$'\n'*|*$'\r'*) return 1 ;; esac
    read -r -a w <<< "$c"
    [ "${w[0]:-}" = bash ] && i=1
    # shellcheck disable=SC2088  # 문서의 호출 꼴 `~/.claude/...` 를 글자 그대로 대조한다(펼치지 않음)
    case "${w[$i]:-}" in "~/.claude/scripts/spawn-tree.sh"|"$HOMEC/scripts/spawn-tree.sh"|"$HOME/.claude/scripts/spawn-tree.sh") ;; *) return 1 ;; esac
    case "${w[$((i + 1))]:-}" in
        check) return 0 ;;
        snapshot) [[ "${w[$((i + 2))]:-}" =~ (^|/)\.spawn-tree-[^/]*$ ]] && return 0 ;;   # WHY: tree 이름이 `.spawn-tree-` 로 시작할 때만(3차 T7)
    esac
    return 1
}
if command -v jq >/dev/null 2>&1; then
    D=$(date -u -d "@$(stat -c %Z -- "$TREE")" +%Y-%m-%dT%H:%M:%S)
    while IFS= read -r t; do
        [ -n "$t" ] || continue
        while IFS= read -r -d '' fp; do
            [ -n "$fp" ] || continue
            case "$fp" in *[[:cntrl:]]*) fail "subagent 도구 쓰기 경로에 제어 문자(개행 등) — 바로 FAIL: $(basename -- "$t"): $fp"; continue ;; esac
            # WHY: transcript 의 경로도 허용 접두와 같은 형태로 푼다 — 링크 낀 표기 차이로 정상 쓰기가 FAIL 되던 것을 막는다(2026-08-30)
            fp_r=$(readlink -f -- "$fp" 2>/dev/null) || fp_r=""
            [ -n "$fp_r" ] || fp_r="$fp"
            allowed_sub "$fp_r" || fail "subagent 도구 쓰기 허용 밖: $(basename -- "$t"): $fp"
        done < <(jq -jR --arg d "$D" 'fromjson? | select(.type=="assistant" and ((.timestamp // "") >= $d)) | .message.content[]? | select(.type=="tool_use") | select(.name=="Write" or .name=="Edit" or .name=="MultiEdit" or .name=="NotebookEdit") | ((.input.file_path // .input.notebook_path // empty) | tostring) + "\u0000"' -- "$t" 2>/dev/null | sort -zu)
        declare -A HIT=()
        while IFS= read -r -d '' cmd; do
            spawn_tree_only "$cmd" && continue
            for nd in "${NEEDLES[@]}"; do
                case "$cmd" in *"$nd"*) HIT["$nd"]=1 ;; esac
            done
        done < <(jq -jR --arg d "$D" 'fromjson? | select(.type=="assistant" and ((.timestamp // "") >= $d)) | .message.content[]? | select(.type=="tool_use") | select(.input.command? != null) | ((.input.command) | tostring) + "\u0000"' -- "$t" 2>/dev/null)
        for nd in ${HIT[@]+"${!HIT[@]}"}; do
            fail "subagent 명령이 감시 이름을 언급(문자열 대조): $(basename -- "$t"): $nd"
        done
        unset HIT
        while IFS= read -r mn; do
            [ -n "$mn" ] || continue
            mcp_allowed "$mn" || fail "subagent MCP 호출(격리 spawn 에서 외부 발신 금지, 허용은 --allow-mcp 접두만): $(basename -- "$t"): $mn"
        done < <(jq -rR --arg d "$D" 'fromjson? | select(.type=="assistant" and ((.timestamp // "") >= $d)) | .message.content[]? | select(.type=="tool_use") | select(.name | startswith("mcp__")) | .name' -- "$t" 2>/dev/null | sort -u)
    done < <(find "$HOMEC/projects" -path '*/subagents/*.jsonl' \( -type f -o -type l \) -cnewer "$TREE" 2>/dev/null | sort)
else
    fail "jq 없음 — ④ transcript 검사 불가(fail-closed)"
fi

if [ "$FAIL" -eq 0 ]; then echo "RESULT: PASS"; exit 0; else echo "RESULT: FAIL $FAIL"; exit 1; fi
