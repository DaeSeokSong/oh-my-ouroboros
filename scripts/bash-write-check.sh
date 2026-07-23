#!/bin/bash
# bash-write-check.sh — Bash 명령어 읽기/쓰기 분류 게이트
#
# 구조: settings.json에서 "Bash(*)" 전체 허용 → 이 hook이 유일한 쓰기 차단 게이트
#
# 출력 형식 (2026-07-15 교정 — GPT 교차감사 FINDING 4.2):
#   읽기 전용 판단 → 무출력 exit 0 (별도 승인 의미 없음 — 정상 permission flow에 위임.
#     구형 {"decision":"allow"}는 유효 스키마가 아니라서 매 benign 호출마다 validation
#     오류를 내고 무시되던 것을 제거 — 구형 유효값은 approve/block뿐)
#   쓰기 작업 감지 → 신형 hookSpecificOutput.permissionDecision: "deny" (차단)
#
# 차단 대상 (파일시스템/환경을 변경하는 쓰기 작업):
#   - 파일 쓰기 리다이렉션 (> file, >> file)
#   - 파일 삭제·이동·복사 (rm, rmdir, mv, cp, dd, truncate, shred)
#   - 권한·소유권 변경 (chmod, chown)
#   - 패키지 설치 (pip/uv/conda/apt/yum/brew/npm/yarn/cargo install)
#   - 리다이렉션 없는 파일 쓰기 (tee / sed -i / curl -o·-O / wget -O·-P)
#   - 중첩 실행 컨텍스트 내부의 쓰기 명령 ($(...) / `...` / sh -c / | bash)
#   - eval 및 명령 위치 변수 참조 ($VAR 형태)
#
# 설계 방침: 중첩 실행 컨텍스트가 보이면 fail-closed(원문 그대로 재검사).
#   드문 오탐(예: echo "$(grep -c foo f)")은 첫 줄 "# APPROVED" 마커로 통과. (미탐 < 오탐 우선)
# 한계: 키워드 뒤 변수 실행·heredoc 내부·다중 인코딩은 완전 탐지 못 함 (~95% 커버).
# git 쓰기(commit 등)는 이 hook이 아니라 commit 규칙이 제어 — git 토큰은 검사에서만 중화.

INPUT=$(cat)
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)

[ -z "$CMD" ] && exit 0

# ── 0. 사용자 승인 마커 ────────────────────────────────────────
# 첫 줄이 "# APPROVED" 이면 사용자가 명시적으로 승인한 명령 → 무조건 허용 (무출력 통과)
# 정확 매칭 (2026-07-18 Codex): '^# APPROVED' prefix는 '# APPROVED_X' 류를 오승인 →
# 뒤에 공백 또는 줄끝만 허용(`# APPROVED`·`# APPROVED 사유`는 통과, `# APPROVED_X`는 불통).
echo "$CMD" | head -1 | grep -qE '^# APPROVED([[:space:]]|$)' && exit 0

BLOCK=false
REASON=""

# 무해한 리다이렉션 제거 (stdin → stdout)
strip_harmless() {
    sed -e 's|[12]*>/dev/null||g' -e 's|2>&1||g' -e 's|1>&2||g' -e 's|>&[012]||g' -e 's|&>[ ]*/dev/null||g'
}
# git 서브명령 토큰 중화 — 오탐(git rm 등)만 제거, 나머지 검사는 계속 (조기 허용 금지)
neutralize_git() {
    sed -E 's/(^|[;&|(][[:space:]]*|^[[:space:]]*)git[[:space:]]+[[:alnum:]._-]+/\1__git__/g'
}
# 쓰기 패턴 검사 — $1: 검사 대상, $2: 컨텍스트 라벨
# 경계 클래스에 따옴표 포함 — 원문 재검사 시 인용부호 직후 명령까지 탐지
check_write_patterns() {
    local T="$1" CTX="$2"
    local B="[[:space:];&|(\"']"
    echo "$T" | grep -qE '>{1,2}' && BLOCK=true && REASON="파일 쓰기 리다이렉션 (> 또는 >>)${CTX}"
    # 경로 접두(/bin/rm 등)·추가 writer(touch) 탐지 강화 (2026-07-18 Codex). mkdir는 제외 —
    # 벤치·스테이징에서 mkdir -p가 상시 사용되는 benign 디렉토리 생성이라 차단 시 워크플로 파손.
    echo "$T" | grep -qE "(^|$B|/)(rm|rmdir|mv|cp|dd|truncate|shred|touch)[[:space:]]" \
        && BLOCK=true && REASON="파일 조작 명령 (rm/mv/cp/dd/touch 등)${CTX}"
    echo "$T" | grep -qE "(^|$B|/)(chmod|chown)[[:space:]]" \
        && BLOCK=true && REASON="권한/소유권 변경 (chmod/chown)${CTX}"
    # 패키지 설치: 좌측 경계 추가 (2026-07-18 Codex): 'notpip install' 오탐 방지
    echo "$T" | grep -qE "(^|$B)(pip|uv|conda|apt(-get)?|yum|brew|npm|yarn|cargo)[[:space:]]+install" \
        && BLOCK=true && REASON="패키지 설치${CTX}"
    # 리다이렉션 없는 파일 쓰기 명령 (tee / sed -i / curl -o / wget -O) — 탐지 추가 2026-07-06
    echo "$T" | grep -qE "(^|$B)tee[[:space:]]" \
        && BLOCK=true && REASON="파일 쓰기 (tee)${CTX}"
    echo "$T" | grep -qE "(^|$B)sed[[:space:]]([^;&|]*[[:space:]])?(-[A-Za-z]*i|--in-place)" \
        && BLOCK=true && REASON="파일 내 수정 (sed -i)${CTX}"
    echo "$T" | grep -qE "(^|$B)curl[^;&|]*[[:space:]](-o|--output|-O)([[:space:]]|$)" \
        && BLOCK=true && REASON="파일 다운로드 저장 (curl -o/-O)${CTX}"
    echo "$T" | grep -qE "(^|$B)wget[^;&|]*[[:space:]](-O|-P|--output-document)" \
        && BLOCK=true && REASON="파일 다운로드 저장 (wget -O)${CTX}"
}

# ── 1. 표준 검사: 따옴표 제거(오탐 방지) → git 중화 → 무해 리다이렉션 제거 → 패턴 검사
S=$(echo "$CMD" | sed "s/'[^']*'//g" | sed 's/"[^"]*"//g' | neutralize_git | strip_harmless)
check_write_patterns "$S" ""

# ── 2. 중첩 실행 컨텍스트 검사 — $(...) / `...` / sh -c / 파이프-투-셸 존재 시 원문 그대로 재검사
if echo "$CMD" | grep -qE '\$\(|`|(^|[[:space:];&|(])(bash|sh|zsh|dash|ksh)[[:space:]]+([^;&|]*[[:space:]])?-c([[:space:]]|$)|(^|[|;&][[:space:]]*)(bash|sh|zsh|dash|ksh)([[:space:]]|$)'; then
    S_RAW=$(echo "$CMD" | neutralize_git | strip_harmless)
    check_write_patterns "$S_RAW" " — 실행 컨텍스트(\$()/backtick/sh -c) 내부"
fi

# ── 3. 간접 실행 검사 (eval / 명령 위치 변수)
echo "$S" | grep -qE '(^|[[:space:];&|(])eval[[:space:]]' \
    && BLOCK=true && REASON="eval 간접 실행"
echo "$S" | grep -qE '(^[[:space:]]*|[;&|][[:space:]]*)\$[A-Za-z_{]' \
    && BLOCK=true && REASON="명령 위치 변수 간접 실행 (\$VAR ...)"

# ── 결과 출력 ─────────────────────────────────────────────────
# 허용 = 무출력 exit 0 (정상 permission flow에 위임), 차단 = 신형 deny 스키마 (jq로 안전 생성)
if $BLOCK; then
    jq -cn --arg r "[쓰기 차단] $REASON — 필요하면 터미널에서 직접 실행하세요." \
        '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: $r}}'
fi
exit 0
