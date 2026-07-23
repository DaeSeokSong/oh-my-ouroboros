#!/usr/bin/env bash
# CI Gate: pre-commit 종합 검증
# git stage 파일들에 대한 lint + secret 패턴 검출
# 출력: stdout (사용자가 commit 시점에 봄)
# 종료: 0 (PASS) / 1 (FAIL — commit 차단)

set -uo pipefail

# stage된 파일 목록 (R 포함 — rename+수정도 검사, 2026-07-15 GPT P1-4)
FILES=$(git diff --cached --name-only --diff-filter=ACMR 2>/dev/null)
[ -z "$FILES" ] && exit 0

FAIL=0
REPORT=""

# 검사 대상 = working tree가 아니라 index blob (2026-07-15 — GPT P1-4 실증: stage 후
# worktree만 정리하면 비밀이 든 blob이 그대로 커밋되는 우회 존재) — git show ":$FILE" 기준.
#
# Secret 패턴 2계층 (2026-07-15 — GPT P1-5):
#   Tier-1 고신뢰 키 포맷 — 주석 예외 없음 (주석 처리돼도 만료 전 실키는 credential)
#   Tier-2 일반 할당형(API_KEY/TOKEN 등) — 라인 시작 주석 예외 + placeholder allowlist (문서 예시 오탐 방지)
# redaction: 매치 원문은 절대 리포트에 넣지 않는다 — 위치(라인 번호/건수)만 보고 (FINDING 4.3).
SECRET_T1='(sk-[a-zA-Z0-9_-]{20,}|gh[pousr]_[a-zA-Z0-9]{20,}|github_pat_[a-zA-Z0-9_]{20,}|AIza[0-9A-Za-z_-]{30,}|xox[baprs]-[a-zA-Z0-9-]{10,}|tvly-[a-zA-Z0-9-]{20,}|m0-[a-zA-Z0-9]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----)'
# Tier-2 값 첫 문자에서 $ 제외 — TOKEN="$VAR" 류 셸 변수 참조는 키가 아님 (bootstrap 실측 오탐)
SECRET_T2="[A-Za-z_]*(API_KEY|APIKEY|SECRET|TOKEN|PASSWORD)[A-Za-z_]*[[:space:]]*[=:][[:space:]]*[\"'][^\"'\$][^\"']{7,}"
PLACEHOLDER='(YOUR|XXXX|xxxx|<[^>]*>|\{[^}]*\}|\.\.\.|placeholder|example|dummy|FAKE|더미|예시|여기에)'
while IFS= read -r FILE; do
    [ -z "$FILE" ] && continue
    git cat-file -e ":$FILE" 2>/dev/null || continue
    # 자기 hook 스크립트는 secret 검사 제외 (자기 자신 패턴 정의 오탐 방지)
    case "$FILE" in
        scripts/ci-gate-*.sh|scripts/read-once.sh|scripts/bash-write-check.sh|scripts/claude-notify.sh)
            continue
            ;;
    esac
    # 바이너리 파일 스킵 (index blob 기준)
    git show ":$FILE" 2>/dev/null | file --mime - 2>/dev/null | grep -q binary && continue
    case "$FILE" in
        *.json|*.yml|*.yaml|*.toml|*.env|*.env.*)
            # config 파일은 diff 기반 (새로 추가된 라인만 — 기존 노출 키 무시), 건수만 집계
            ADDED=$(git diff --cached -- "$FILE" 2>/dev/null | grep '^+' | grep -v '^+++')
            N1=$(printf '%s\n' "$ADDED" | grep -cE "$SECRET_T1")
            N2=$(printf '%s\n' "$ADDED" | grep -iE "$SECRET_T2" | grep -icvE "$PLACEHOLDER")
            SECRET_LOC=""
            [ $((N1 + N2)) -gt 0 ] && SECRET_LOC="신규 추가 라인 중 $((N1 + N2))건 매치"
            ;;
        *)
            CONTENT=$(git show ":$FILE" 2>/dev/null)
            L1=$(printf '%s\n' "$CONTENT" | grep -nE "$SECRET_T1" | cut -d: -f1)
            L2=$(printf '%s\n' "$CONTENT" | grep -inE "$SECRET_T2" | grep -vE '^[0-9]+:[[:space:]]*(#|//|<!--)' | grep -ivE "$PLACEHOLDER" | cut -d: -f1)
            SECRET_LOC=$(printf '%s\n%s\n' "$L1" "$L2" | grep -E '^[0-9]+$' | sort -nu | head -3 | paste -sd, -)
            [ -n "$SECRET_LOC" ] && SECRET_LOC="라인 ${SECRET_LOC}"
            ;;
    esac
    if [ -n "$SECRET_LOC" ]; then
        REPORT="${REPORT}\n🔐 [SECRET DETECTED] $FILE (${SECRET_LOC} — 원문 비출력, 해당 라인을 직접 확인 후 키 회전·제거)\n"
        FAIL=1
    fi
done <<< "$FILES"

# 시크릿 탐지 시 즉시 실패 종료 (2026-07-15 — GPT 리뷰 P1 후속): 이후 단계(lint의 소스 줄
# 출력·모델 ID 라인 출력)가 시크릿이 든 라인 원문을 재노출할 수 있으므로 도달 자체를 차단
if [ $FAIL -eq 1 ]; then
    echo ""
    echo "❌ ci-gate-commit FAILED — commit blocked (secret 탐지 — 후속 검사 생략)"
    echo -e "$REPORT"
    echo ""
    echo "💡 해당 라인 확인 → 키 회전·제거 후 재커밋"
    exit 1
fi

# 코드 파일별 lint — index blob을 임시 디렉터리에 materialize해 검사 (2026-07-15 GPT P1-4:
# worktree 검사는 stage 후 worktree 수정 시 커밋될 내용과 다른 것을 검사하게 됨)
LINT_TMP=$(mktemp -d)
trap 'rm -rf "$LINT_TMP"' EXIT
while IFS= read -r FILE; do
    [ -z "$FILE" ] && continue
    git cat-file -e ":$FILE" 2>/dev/null || continue
    EXT="${FILE##*.}"
    LINT_OUT=""
    SNAP="$LINT_TMP/$FILE"
    mkdir -p "$(dirname "$SNAP")"
    git show ":$FILE" > "$SNAP" 2>/dev/null || continue

    case "$EXT" in
        py)
            command -v ruff &>/dev/null && LINT_OUT=$(ruff check "$SNAP" 2>&1 | head -10 | sed "s|$LINT_TMP/||g")
            ;;
        ts|tsx|js|jsx)
            command -v eslint &>/dev/null && LINT_OUT=$(eslint "$SNAP" 2>&1 | head -10 | sed "s|$LINT_TMP/||g")
            ;;
        sh|bash)
            command -v shellcheck &>/dev/null && LINT_OUT=$(shellcheck "$SNAP" 2>&1 | head -10 | sed "s|$LINT_TMP/||g")
            ;;
        md|markdown)
            # markdownlint 또는 fence 균형 체크
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

# 하네스 .md 무결성 검사 (staged *.md만 대상 — 없으면 즉시 스킵)
MD_FILES=$(echo "$FILES" | grep -E '\.md$') || true
if [ -n "$MD_FILES" ]; then
    REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || REPO_ROOT="$HOME/.claude"

    # 1) 깨진 파일 포인터 검사 (FAIL — 커밋 차단)
    POINTER_PATTERN='(rules|rules-lazy|agents|skills|commands|scripts)/[A-Za-z0-9_/.-]+\.(md|sh)'
    while IFS= read -r FILE; do
        [ -z "$FILE" ] && continue
        git cat-file -e ":$FILE" 2>/dev/null || continue
        REFS=$(git show ":$FILE" 2>/dev/null | grep -oE "$POINTER_PATTERN" | sort -u) || true
        [ -z "$REFS" ] && continue
        while IFS= read -r REF; do
            [ -z "$REF" ] && continue
            # 플레이스홀더/템플릿 참조 스킵
            case "$REF" in
                *'{'*|*'['*|*'*'*|*'$'*|*'('*)
                    continue
                    ;;
            esac
            # allowlist 스킵 (스킬 예시 텍스트 + 문서 템플릿 플레이스홀더 my-*)
            case "$REF" in
                rules/A.md|rules/B.md|commands/C.md|*/my-*)
                    continue
                    ;;
            esac
            if [ ! -f "$REPO_ROOT/$REF" ]; then
                REPORT="${REPORT}\n🔗 [BROKEN POINTER] $FILE: $REF\n"
                FAIL=1
            fi
        done <<< "$REFS"
    done <<< "$MD_FILES"

fi

# 2) 하드코딩 모델 ID 경고 (WARN — 커밋 차단하지 않음)
# .md뿐 아니라 .sh/.py도 스캔 — 스크립트 기본값의 특정 버전 하드코딩이 감시망을 벗어나는 것 방지
MODEL_SCAN_FILES=$(echo "$FILES" | grep -E '\.(md|sh|py)$') || true
if [ -n "$MODEL_SCAN_FILES" ]; then
    MODEL_ID_PATTERN='claude-(opus|sonnet|haiku|fable)-[0-9][0-9a-z.-]*'
    while IFS= read -r FILE; do
        [ -z "$FILE" ] && continue
        [ ! -f "$FILE" ] && continue
        # 라인 원문 비출력 (2026-07-15 — GPT 리뷰 P1 후속): 같은 줄에 시크릿이 공존하면 재노출됨
        # — 매치된 모델 ID 토큰과 건수만 보고
        MODEL_HITS=$(git diff --cached "$FILE" 2>/dev/null | grep '^+' | grep -v '^+++' | grep -ioE "$MODEL_ID_PATTERN" | sort -u) || true
        [ -z "$MODEL_HITS" ] && continue
        HIT_IDS=$(echo "$MODEL_HITS" | paste -sd', ' -)
        echo "⚠️  [HARDCODED MODEL ID] $FILE: ${HIT_IDS} — 별칭(opus/sonnet/haiku) 권장 (라인 원문 비출력)"
    done <<< "$MODEL_SCAN_FILES"
fi

# 3) always-on 토큰 예산 경고 (WARN — 커밋 차단하지 않음)
# zerosum 원칙(learner.md § Zero-Sum)의 자동화 — 정의만 있고 수동 실행이 한 번도 안 되던
# harness-evolve zerosum 개념을 커밋 훅에 흡수 (2026-07-09 구축-미사용 rot 점검에서 발견).
# 예산 70000B = 2026-07-09 기준선 67,212B + ~4% 여유. 예산 갱신 시 _audit/history 기준선과 함께.
AO_TOUCHED=$(echo "$FILES" | grep -E '^(CLAUDE\.md|rules/[^/]+\.md)$') || true
if [ -n "$AO_TOUCHED" ]; then
    AO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || AO_ROOT="$HOME/.claude"
    AO_TOTAL=$(cat "$AO_ROOT/CLAUDE.md" "$AO_ROOT"/rules/*.md 2>/dev/null | wc -c)
    AO_BUDGET=70000
    if [ "$AO_TOTAL" -gt "$AO_BUDGET" ]; then
        echo "⚠️  [ALWAYS-ON BUDGET] ${AO_TOTAL}B > ${AO_BUDGET}B — zerosum 원칙: 추가한 만큼 축약 후보를 함께 제시 (learner.md § Zero-Sum)"
    fi
fi

# 보고
if [ $FAIL -eq 1 ]; then
    echo ""
    echo "❌ ci-gate-commit FAILED — commit blocked"
    echo -e "$REPORT"
    echo ""
    echo "💡 우회 방법: git commit --no-verify"
    exit 1
fi

echo "✅ ci-gate-commit PASSED ($(echo "$FILES" | wc -l) files)"
exit 0
