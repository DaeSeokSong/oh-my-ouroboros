#!/usr/bin/env bash
# CI Gate: pre-commit 종합 검증
# git stage 파일들에 대한 lint + secret 패턴 검출
# 출력: stdout (사용자가 commit 시점에 봄)
# 종료: 0 (PASS) / 1 (FAIL — commit 차단)
# REF: knowledge/harness/code-history/scripts__ci-gate-commit.sh.md

set -uo pipefail
export LC_ALL=C   # WHY: 바이트 단위 매칭 고정(15라운드 Grok: 로캘 의존 `.` 매칭 실측)

# WHY: -z 로 읽어 비ASCII·특수문자 이름이 인용형으로 나오지 않게 한다. 인용형은 `git cat-file -e` 가 실패해
# 시크릿·lint 검사를 건너뛴 채 통과 수에 셌다(2026-10-01 감사).
FILES=$(git diff --cached -z --name-only --diff-filter=ACMRT 2>/dev/null | tr '\0' '\n')
FAIL=0
SECRET_FAIL=0
REPORT=""

# WHY: 기록은 당시 사실이라 고쳐 쓰지 않는다. 다만 한 번도 없던 경로를 새로 적는 실수는 계속 잡는다(2026-11-10 사용자 결정).
RECORD_DIRS='_audit|intent|docs|graphify-out'

# WHY: 삭제·rename 옛 경로 역참조 검사는 조기 종료보다 먼저 돈다(5라운드 Codex: 삭제-only 커밋은 FILES 가 비어 검사 없이 통과했고 rename 옛 경로는 대상 밖이었다).
DELETED=$( { git diff --cached --name-only --diff-filter=D 2>/dev/null; git diff --cached --name-status --diff-filter=R 2>/dev/null | awk -F'\t' '{print $2}'; } | grep -E '^(rules|rules-lazy|agents|skills|commands|scripts)/.*\.(md|sh)$') || true
while IFS= read -r DEL; do
    [ -z "$DEL" ] && continue
    # WHY: 기록 폴더는 히트에서 뺀다(2026-11-10 사용자 결정). git grep 은 비ASCII 경로를 "…" 로 감싸므로 앞 따옴표 허용.
    # head -3 보다 앞에서 거른다: 기록 3건이 앞자리를 채워 살아 있는 히트를 가리지 않게.
    HITS=$(git grep --cached -l -F "$DEL" -- '*.md' 2>/dev/null | grep -vxF "$DEL" | grep -vE "^\"?($RECORD_DIRS)/" | head -3 | paste -sd, -)
    if [ -n "$HITS" ]; then
        REPORT="${REPORT}\n🔗 [BROKEN POINTER] 삭제·이동 대상 $DEL 을 아직 참조: $HITS\n"
        FAIL=1
    fi
done <<< "$DELETED"
if [ -z "$FILES" ]; then
    if [ "$FAIL" -eq 1 ]; then echo "❌ ci-gate-commit FAILED — commit blocked"; echo -e "$REPORT"; exit 1; fi
    exit 0
fi

# WHY: 검사 대상은 working tree 가 아니라 index blob 이다(2026-07-15 GPT P1-4 실증: stage 후 worktree 만 정리하면 비밀이 든 blob 이 그대로 커밋된다).
# WHY: Tier-1 고신뢰 키 포맷은 주석 예외가 없고(주석 처리돼도 만료 전 실키는 credential), Tier-2 일반 할당형은 라인 시작 주석 예외 +
# placeholder allowlist 를 둔다(2026-07-15 GPT P1-5).
# NEVER: 매치 원문을 리포트에 넣지 않는다. 위치(라인 번호/건수)만 보고한다(FINDING 4.3).
# WHY: sk- 앞 단어 경계는 «ask-xhigh-…» 가 OpenAI 키로 잡히던 오탐 때문이다(2026-09-08 실측).
SECRET_T1='((^|[^A-Za-z0-9_-])sk-[a-zA-Z0-9_-]{20,}|gh[pousr]_[a-zA-Z0-9]{20,}|github_pat_[a-zA-Z0-9_]{20,}|AIza[0-9A-Za-z_-]{30,}|xox[baprs]-[a-zA-Z0-9-]{10,}|tvly-[a-zA-Z0-9-]{20,}|m0-[a-zA-Z0-9]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----)'
# WHY: Tier-2 값 첫 문자에서 $ 를 뺀다. 셸 변수 참조는 키가 아님(bootstrap 실측 오탐). 따옴표 없는 값도 본다(4라운드 Codex 지적).
# 값은 자격증명꼴(공백 없는 8자+ 따옴표 안 / 영숫자 시작 12자+ 따옴표 없음)만 본다(산문·메시지 문자열 오탐 실측).
SECRET_T2="[A-Za-z_]*(API_KEY|APIKEY|SECRET|TOKEN|PASSWORD)[A-Za-z_]*[\"']?[[:space:]]*[=:][[:space:]]*([\"'][^\"'\$[:space:]]{8,}[\"']|[A-Za-z0-9][A-Za-z0-9_./+=-]{11,}([[:space:];&|,)]|$))"   # WHY: 후행 경계에 셸 구분자 포함(5라운드 Codex: `KEY=…; export X` 미탐)
PLACEHOLDER='(YOUR|XXXX|xxxx|<[^>]*>|\{[^}]*\}|\.\.\.|placeholder|example|dummy|FAKE|더미|예시|여기에)'
# WHY: 자기 패턴 선언 라인만 제외(4라운드: 파일 단위 제외는 훅 스크립트에 실키를 넣어도 통과시켰다)
SELF_DECL='^[0-9]*:?[[:space:]]*(SECRET_T1|SECRET_T2|PLACEHOLDER|SELF_DECL)='
while IFS= read -r FILE; do
    [ -z "$FILE" ] && continue
    # WHY: 조회 실패는 건너뛰지 않고 실패로 센다(검사 없이 통과 수에 세던 구멍, 2026-10-01 감사)
    if ! git cat-file -e ":$FILE" 2>/dev/null; then
        REPORT="${REPORT}\n🔐 [SECRET SCAN SKIPPED] index 에서 파일을 읽지 못해 검사 불가(이름에 개행·특수문자?): ${#FILE}자 이름 — 이름을 바꿔 다시 stage\n"
        FAIL=1; SECRET_FAIL=1
        continue
    fi
    # WHY: 모든 blob 을 NUL 제거 후 텍스트로 스캔한다(6라운드 렌즈2 실측: NUL 1바이트만 섞어도 file 이 binary 로 판정해 시크릿 검사를 통째로 건너뛰었다).
    case "$FILE" in
        *.json|*.yml|*.yaml|*.toml|*.env|*.env.*)
            ADDED=$(git --literal-pathspecs diff --cached --text -- "$FILE" 2>/dev/null | tr -d '\000' | grep '^+' | grep -v '^+++')   # WHY: --text: NUL 로 binary 위장 시에도 diff 를 낸다(6라운드)
            N1=$(printf '%s\n' "$ADDED" | grep -cE "$SECRET_T1")
            N2=$(printf '%s\n' "$ADDED" | grep -oiE "$SECRET_T2" | grep -icvE "$PLACEHOLDER")
            SECRET_LOC=""
            [ $((N1 + N2)) -gt 0 ] && SECRET_LOC="신규 추가 라인 중 $((N1 + N2))건 매치"
            ;;
        *)
            CONTENT=$(git show ":$FILE" 2>/dev/null | tr -d '\000')
            # WHY: SELF_DECL 제외는 이 훅 파일 자신에게만 (5라운드 Grok: 전 파일에 적용하면 notes.md 의 `SECRET_T1=sk-…` 한 줄로 우회)
            DECL_FILTER='^$'; [ "$FILE" = "scripts/ci-gate-commit.sh" ] && DECL_FILTER="$SELF_DECL"
            L1=$(printf '%s\n' "$CONTENT" | grep -nE "$SECRET_T1" | grep -vE "$DECL_FILTER" | cut -d: -f1)
            # WHY: PLACEHOLDER 는 행 전체가 아니라 매치된 값에만 (5라운드 Codex: 실키 뒤 `# example` 로 예외 위조)
            L2=$(printf '%s\n' "$CONTENT" | grep -inE "$SECRET_T2" | grep -vE '^[0-9]+:[[:space:]]*(#|//|<!--)' | grep -vE "$DECL_FILTER" \
                | while IFS= read -r LN; do
                    # 매치별 판정 — 한 줄에 자리표시자 매치가 앞서고 실제 값이 뒤따르면 첫 매치만 보던 옛 방식은 줄 전체를 제외했다(2026-10-01 감사)
                    printf '%s\n' "${LN#*:}" | grep -oiE "$SECRET_T2" | grep -qviE "$PLACEHOLDER" && printf '%s\n' "${LN%%:*}"
                  done)
            SECRET_LOC=$(printf '%s\n%s\n' "$L1" "$L2" | grep -E '^[0-9]+$' | sort -nu | head -3 | paste -sd, -)
            [ -n "$SECRET_LOC" ] && SECRET_LOC="라인 ${SECRET_LOC}"
            ;;
    esac
    if [ -n "$SECRET_LOC" ]; then
        REPORT="${REPORT}\n🔐 [SECRET DETECTED] $FILE (${SECRET_LOC} — 원문 비출력, 해당 라인을 직접 확인 후 키 회전·제거)\n"
        FAIL=1; SECRET_FAIL=1
    fi
done <<< "$FILES"

# WHY: 시크릿 탐지 시 즉시 실패 종료한다(2026-07-15 GPT 리뷰 P1 후속). 이후 단계(lint의 소스 줄
# 출력·모델 ID 라인 출력)가 시크릿이 든 라인 원문을 재노출할 수 있다.
if [ $FAIL -eq 1 ]; then
    echo ""
    if [ "$SECRET_FAIL" -eq 1 ]; then
        echo "❌ ci-gate-commit FAILED — commit blocked (secret 탐지 — 후속 검사 생략)"
        echo -e "$REPORT"
        echo ""
        echo "💡 해당 라인 확인 → 키 회전·제거 후 재커밋"
    else
        echo "❌ ci-gate-commit FAILED — commit blocked (깨진 포인터 — 후속 검사 생략)"
        echo -e "$REPORT"
        echo ""
        echo "💡 삭제·이동한 파일을 가리키는 문서가 남았다 → 포인터를 고친 뒤 재커밋"
    fi
    exit 1
fi

# WHY: lint 는 index blob을 임시 디렉터리에 materialize해 검사한다(2026-07-15 GPT P1-4:
# worktree 검사는 stage 후 worktree 수정 시 커밋될 내용과 다른 것을 검사하게 됨)
LINT_TMP=$(mktemp -d)
trap 'rm -rf "$LINT_TMP"' EXIT
ESLINT_NOCONF=0
while IFS= read -r FILE; do
    [ -z "$FILE" ] && continue
    git cat-file -e ":$FILE" 2>/dev/null || continue
    EXT="${FILE##*.}"
    LINT_OUT=""
    SNAP="$LINT_TMP/$FILE"
    mkdir -p "$(dirname "$SNAP")"
    git show ":$FILE" > "$SNAP" 2>/dev/null || continue
    # WHY: 임시 사본은 실행 권한이 없어, shebang 있는 실행 .py(mode 100755)를 ruff 가 EXE001 로 오탐해 커밋이 막혔다(2026-11-12 두 번).
    # mode 는 worktree 가 아니라 index 에서 읽는다.
    [ "$(git --literal-pathspecs ls-files -s -- "$FILE" 2>/dev/null | cut -d' ' -f1)" = "100755" ] && chmod u+x "$SNAP" 2>/dev/null

    case "$EXT" in
        py)
            command -v ruff &>/dev/null && LINT_OUT=$(ruff check "$SNAP" 2>&1 | head -10 | sed "s|$LINT_TMP/||g")
            ;;
        ts|tsx|js|jsx)
            if command -v eslint &>/dev/null; then
                ES_RAW=$(eslint "$SNAP" 2>&1); ES_RC=$?
                # WHY: ESLint 설정 파일이 없을 때 실패로 세면 설정이 없는 서버에서 JS·TS 를 만지는 커밋이 전부 막힌다(2026-10-27 실사고).
                # 판별은 종료 코드 2(ESLint 가 설정·내부 오류에 쓰는 값, 린트 오류는 1)와 문구가 둘 다 맞을 때만이다.
                # 문구만 보면 소스에 같은 문구를 심어 진짜 오류를 가릴 수 있다(qa 2026-10-27 지적).
                ES_NOCONF=0
                if [ "$ES_RC" -eq 2 ]; then
                    case "$ES_RAW" in
                        *"ESLint couldn't find a configuration file"*|*"ESLint couldn't find an eslint.config"*) ES_NOCONF=1 ;;
                    esac
                fi
                if [ "$ES_NOCONF" -eq 1 ]; then
                    ESLINT_NOCONF=$((ESLINT_NOCONF + 1))
                else
                    LINT_OUT=$(printf '%s\n' "$ES_RAW" | head -10 | sed "s|$LINT_TMP/||g")
                fi
            fi
            ;;
        sh|bash)
            command -v shellcheck &>/dev/null && LINT_OUT=$(shellcheck "$SNAP" 2>&1 | head -10 | sed "s|$LINT_TMP/||g")
            ;;
        md|markdown)
            if command -v markdownlint &>/dev/null; then
                LINT_OUT=$(markdownlint "$SNAP" 2>&1 | head -10 | sed "s|$LINT_TMP/||g")
            else
                FENCE_COUNT=$(grep -c '^```' "$SNAP" 2>/dev/null) || FENCE_COUNT=0
                if [ $((FENCE_COUNT % 2)) -ne 0 ]; then
                    LINT_OUT="Code fence imbalance (count: $FENCE_COUNT)"
                fi
            fi
            ;;
    esac

    if [ -n "$LINT_OUT" ] && [ "$LINT_OUT" != "All checks passed!" ]; then
        REPORT="${REPORT}\n📝 [LINT FAIL] $FILE:\n$LINT_OUT\n"
        FAIL=1
    fi
done <<< "$FILES"
if [ "$ESLINT_NOCONF" -gt 0 ]; then
    echo "⚠️  [ESLINT NO CONFIG] ESLint 설정 파일이 없어 JS·TS ${ESLINT_NOCONF}개의 린트(문법 오류 검사 포함)를 건너뜀 (실패 아님) — 이 서버에서 린트하려면 ESLint 설정이 필요"
fi

# WHY: 주석 규칙(rules-lazy/coding-conventions.md § 주석 규칙)의 차단 자리로 2026-11-24 intent W17 이 정했다. 위 시크릿 단계가
# 먼저 끝나야 위반 목록이 시크릿 줄 원문을 다시 찍지 않는다. 검사기 · python3 가 없거나 exit 1 에 `RESULT: FAIL` 이 없으면
# (import 실패 · 트레이스백도 exit 1) 검사를 못 한 것이라 경고만 낸다. graphify-out/ 은 생성물이라 뺀다.
# WHY: 검사기는 이번 커밋의 index(`git commit -- 경로` 면 임시 index) 사본을 쓰고, index 에 없으면 HEAD 사본을 쓴다. 둘 다 없으면
# 조용히 건너뛴다. 작업 트리에만 있는 검사기는 돌지 않고 같은 커밋에서 검사기를 지워도 HEAD 사본이 돈다(2026-11-24 main 지시 · security D2).
# 같은 커밋에서 고친 검사기는 그 index 사본이 돌므로 검사기 변경은 검수가 본다. stdout 만 받아 파이썬 경고가 보고에 섞이지 않게 한다(security N7).
CC_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || CC_ROOT=""
CC_SRC=""
if [ -n "$CC_ROOT" ]; then
    if git -C "$CC_ROOT" ls-files --error-unmatch -- scripts/comment_check.py >/dev/null 2>&1; then
        CC_SRC=":scripts/comment_check.py"
    elif git -C "$CC_ROOT" cat-file -e HEAD:scripts/comment_check.py 2>/dev/null; then
        CC_SRC="HEAD:scripts/comment_check.py"
    fi
fi
if [ -n "$CC_SRC" ] \
    && [ "$(git -C "$CC_ROOT" diff --cached --name-only -z --diff-filter=ACMRT -- '*.py' '*.sh' '*.js' ':(exclude)graphify-out' 2>/dev/null | head -c1 | wc -c)" -gt 0 ]; then
    # WHY: the lint loop above unpacks every staged path under $LINT_TMP, so a staged ".comment_check.py/x.txt" could turn the
    # copy's path into a folder (2026-11-24 security review). The copy lives in its own mktemp folder, removed by the same trap.
    CC_TMP=$(mktemp -d 2>/dev/null) && trap 'rm -rf "$LINT_TMP" "$CC_TMP"' EXIT
    if [ -z "$CC_TMP" ] || ! command -v python3 &>/dev/null || ! git -C "$CC_ROOT" cat-file blob "$CC_SRC" > "$CC_TMP/comment_check.py" 2>/dev/null; then
        echo "⚠️  [COMMENT CHECK · 경고] python3 가 없거나 ${CC_SRC} 를 읽지 못해 주석 검사를 건너뜀 (커밋은 진행)"
    else
        CC_OUT=$(cd "$CC_ROOT" && python3 -I "$CC_TMP/comment_check.py" --staged -- ':(exclude)graphify-out' 2>/dev/null </dev/null); CC_RC=$?
        if [ "$CC_RC" -eq 1 ] && [[ $'\n'"$CC_OUT" == *$'\nRESULT: FAIL ('* ]]; then
            REPORT="${REPORT}\n💬 [COMMENT RULE] 새로 더한 주석이 규칙(rules-lazy/coding-conventions.md § 주석 규칙)에 어긋남:\n${CC_OUT//\\/\\\\}\n"
            FAIL=1
        elif [ "$CC_RC" -ne 0 ]; then
            echo "⚠️  [COMMENT CHECK · 경고] 주석 검사기 오류(exit $CC_RC) — 주석 검사 생략 (커밋은 진행)"
        fi
    fi
fi

MD_FILES=$(echo "$FILES" | grep -E '\.md$') || true
if [ -n "$MD_FILES" ]; then
    POINTER_PATTERN='(rules|rules-lazy|agents|skills|commands|scripts)/[A-Za-z0-9_/.-]+\.(md|sh)'
    while IFS= read -r FILE; do
        [ -z "$FILE" ] && continue
        git cat-file -e ":$FILE" 2>/dev/null || continue
        REFS=$(git show ":$FILE" 2>/dev/null | grep -oE "$POINTER_PATTERN" | sort -u) || true
        [ -z "$REFS" ] && continue
        while IFS= read -r REF; do
            [ -z "$REF" ] && continue
            case "$REF" in
                *'{'*|*'['*|*'*'*|*'$'*|*'('*)
                    continue
                    ;;
            esac
            case "$REF" in
                rules/A.md|rules/B.md|commands/C.md|*/my-*)
                    continue
                    ;;
            esac
            # WHY: 대상 존재도 index 기준 (4라운드 Codex 지적: 워킹트리 확인은 "포인터만 stage + 대상 untracked" 를 통과시켰다)
            if ! git cat-file -e ":$REF" 2>/dev/null; then
                if [[ "$FILE" =~ ^($RECORD_DIRS)/ ]] && [ -n "$(git --literal-pathspecs log -1 --format=%H HEAD -- "$REF" 2>/dev/null)" ]; then
                    continue
                fi
                REPORT="${REPORT}\n🔗 [BROKEN POINTER] $FILE: $REF (index 에 없음 — untracked 대상이면 함께 stage)\n"
                FAIL=1
            fi
        done <<< "$REFS"
    done <<< "$MD_FILES"

fi

MODEL_SCAN_FILES=$(echo "$FILES" | grep -E '\.(md|sh|py)$') || true
if [ -n "$MODEL_SCAN_FILES" ]; then
    MODEL_ID_PATTERN='claude-(opus|sonnet|haiku|fable)-[0-9][0-9a-z.-]*'
    while IFS= read -r FILE; do
        [ -z "$FILE" ] && continue
        [ ! -f "$FILE" ] && continue
        # NEVER: 라인 원문을 출력하지 않는다. 같은 줄에 시크릿이 공존하면 재노출된다(2026-07-15 GPT 리뷰 P1 후속).
        MODEL_HITS=$(git diff --cached "$FILE" 2>/dev/null | grep '^+' | grep -v '^+++' | grep -ioE "$MODEL_ID_PATTERN" | sort -u) || true
        [ -z "$MODEL_HITS" ] && continue
        HIT_IDS=$(echo "$MODEL_HITS" | paste -sd', ' -)
        echo "⚠️  [HARDCODED MODEL ID] $FILE: ${HIT_IDS} — 별칭(opus/sonnet/haiku) 권장 (라인 원문 비출력)"
    done <<< "$MODEL_SCAN_FILES"
fi

# WHY: 예산 75000B = 2026-08-10 사용자 결정 B(70,000B 3주 연속 초과 후 상향, harness-audit Step 1.5).
AO_TOUCHED=$(echo "$FILES" | grep -E '^(CLAUDE\.md|rules/.*\.md)$') || true
if [ -n "$AO_TOUCHED" ]; then
    # WHY: index blob 기준 합산(2026-08-25 3라운드 검수: 워킹트리 cat 은 stage 후 되돌리기로 우회 가능했음)
    AO_TOTAL=0
    while IFS= read -r AO_F; do
        [ -z "$AO_F" ] && continue
        AO_SZ=$(git show ":$AO_F" 2>/dev/null | wc -c)
        AO_TOTAL=$((AO_TOTAL + AO_SZ))
    done < <( { echo CLAUDE.md; git ls-files -- 'rules/*.md' 2>/dev/null; } )
    AO_BUDGET=75000
    # WHY: 초과는 커밋을 막지 않고 경고만 낸다(2026-10-01 사용자 지시로 FAIL→WARN). 한도에 맞추려고 필수 규칙 문장을 깎다가
    # 핵심 어구가 빠지는 쪽이 더 큰 손해라는 판단이다.
    if [ "$AO_TOTAL" -gt "$AO_BUDGET" ]; then
        echo "📏 [ALWAYS-ON BUDGET · 경고] ${AO_TOTAL}B > ${AO_BUDGET}B — 상시 로드 한도 초과(커밋은 진행). 다이어트 사이클로 줄일 것 (harness-audit Step 1.5, knowledge/harness/constitution-diet-rules.md)"
    fi
fi

# WHY: 판정 신호는 "코드 노드 존재"(정본에도 있음 — 오탐)가 아니라 노드 수 급변(±30%+)과 훅 빌드 마커 잔존이다
# (2026-07-31 실사고: 나이틀리 외 경로의 graphify update 가 md semantic 노드를 중복 병합(1,122→2,775)).
# REF: knowledge/harness/path-guard-symlink-bypass.md
if echo "$FILES" | grep -qx 'graphify-out/graph.json'; then
    OG_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || OG_ROOT="$HOME/.claude"
    OG_NEW=$(git show :graphify-out/graph.json 2>/dev/null | python3 -c "import json,sys;print(len(json.load(sys.stdin).get('nodes',[])))" 2>/dev/null) || OG_NEW=""
    OG_OLD=$(git show HEAD:graphify-out/graph.json 2>/dev/null | python3 -c "import json,sys;print(len(json.load(sys.stdin).get('nodes',[])))" 2>/dev/null) || OG_OLD=""
    if [ -n "$OG_NEW" ] && [ -n "$OG_OLD" ] && [ "$OG_OLD" -gt 0 ]; then
        OG_DELTA=$(( (OG_NEW - OG_OLD) * 100 / OG_OLD ))
        OG_ABS=${OG_DELTA#-}
        [ "$OG_ABS" -gt 30 ] && echo "⚠️  [ONTOLOGY SURGE] graph.json 노드 ${OG_OLD}→${OG_NEW} (${OG_DELTA}%) — 나이틀리 외 경로 빌드 오염 의심. 의도적 재빌드가 아니면 폐기(git checkout) 권장"
    fi
    if [ -e "$OG_ROOT/graphify-out/.autoindex-updated" ] || [ -e "$OG_ROOT/graphify-out/.autoindex-last" ]; then
        echo "⚠️  [ONTOLOGY SURGE] graphify-out에 훅 빌드 마커 잔존 — 나이틀리 외 빌드 흔적, graph.json 오염 여부 확인 권장"
    fi
fi

# WHY: lazy 폴더는 한도가 없어 조용히 불어난다(2026-09-06 실측: rules-lazy 454,394B · skills 386,865B · agents 129,226B).
# 차단은 하지 않는다. lazy 는 필요할 때만 읽히므로 상시 토큰이 아니고, 한도를 잘못 잡으면 정당한 문서화를 막는다.
LAZY_RX='^(rules-lazy|skills|agents)/'
LAZY_ADD=$(echo "$FILES" | grep -E "$LAZY_RX") || true
LAZY_GONE=$( { git diff --cached --name-only --diff-filter=D 2>/dev/null; git diff --cached --name-status --diff-filter=R 2>/dev/null | awk -F'\t' '{print $2}'; } | grep -E "$LAZY_RX") || true
if [ -n "$LAZY_ADD" ] || [ -n "$LAZY_GONE" ]; then
    LAZY_DELTA=0
    while IFS= read -r LZ_F; do
        [ -z "$LZ_F" ] && continue
        LZ_NEW=$(git show ":$LZ_F" 2>/dev/null | wc -c)
        LZ_OLD=$(git show "HEAD:$LZ_F" 2>/dev/null | wc -c)
        LAZY_DELTA=$((LAZY_DELTA + LZ_NEW - LZ_OLD))
    done <<< "$LAZY_ADD"
    while IFS= read -r LZ_F; do
        [ -z "$LZ_F" ] && continue
        LZ_OLD=$(git show "HEAD:$LZ_F" 2>/dev/null | wc -c)
        LAZY_DELTA=$((LAZY_DELTA - LZ_OLD))
    done <<< "$LAZY_GONE"
    LAZY_BUDGET=5000
    if [ "$LAZY_DELTA" -gt "$LAZY_BUDGET" ]; then
        echo "⚠️  [LAZY GROWTH] rules-lazy·skills·agents 순증가 ${LAZY_DELTA}B (기준 ${LAZY_BUDGET}B, 근사) — 덜어낼 곳이 있는지 한 번 보고 진행 (차단 아님)"
    fi
fi

# WHY: 수정(M)된 옛 의뢰서는 «범위 밖» 소절이 없는 것이 정상이라 새로 추가(A)된 intent/*.md 만 본다(2026-11-24 intent W1).
# WHY: git 은 -C 저장소 뿌리 기준으로 부른다. 하위 폴더에서 훅을 직접 돌리면 pathspec 이 cwd 기준이라 의뢰서를 놓쳤다(2026-11-24 시험).
IC_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || IC_ROOT=""
if [ -n "$IC_ROOT" ] && [ -f "$IC_ROOT/scripts/intent_check.py" ] && command -v uv &>/dev/null; then
    while IFS= read -r -d '' IC_F; do
        case "$IC_F" in intent/*/*|*/README.md) continue ;; esac
        git -C "$IC_ROOT" show ":$IC_F" > "$LINT_TMP/.intent-check.md" 2>/dev/null || continue
        IC_OUT=$(uv run --offline --no-project python3 "$IC_ROOT/scripts/intent_check.py" "$LINT_TMP/.intent-check.md" 2>/dev/null </dev/null); IC_RC=$?
        if [ "$IC_RC" -eq 1 ] && [[ $'\n'"$IC_OUT"$'\n' == *$'\nRESULT: FAIL\n'* ]]; then
            echo "⚠️  [INTENT CHECK · 경고] $IC_F: 의뢰서 양식 검사 FAIL(커밋은 진행) — 템플릿 skills/intent/templates/intent.md 대조"
            printf '%s\n' "$IC_OUT" | grep -F '[FAIL]' | sed 's/^/      /'
        fi
    done < <(git -C "$IC_ROOT" diff --cached --name-only --diff-filter=A -z -- 'intent/*.md' 2>/dev/null)
fi

if [ $FAIL -eq 1 ]; then
    echo ""
    echo "❌ ci-gate-commit FAILED — commit blocked"
    echo -e "$REPORT"
    echo ""
    echo "💡 FAIL 항목을 고친 뒤 다시 커밋한다 (우회 금지 — 예산 초과는 제거·병합, 시크릿은 회전·제거, 포인터는 경로 정정)"
    exit 1
fi

echo "✅ ci-gate-commit PASSED ($(echo "$FILES" | wc -l) files)"
exit 0
