#!/usr/bin/env bash
# ci-gate-commit-msg.sh — commit-msg 훅: 하네스 `feat:` 커밋은 intent.md 를 가리켜야 한다 (2026-09-06)
#
# ■ 왜 훅인가 (판단 근거 이식)
#   intent.md 체인(skills/intent/SKILL.md)은 «착수 전에 무엇을·왜·어떤 제약으로를 사용자가 교정해 커밋한다»는
#   규칙인데, 문구만 두면 2026-09-01 컨버터 실사고(기획과 다른 baseline 을 말없이 상속)처럼 «썼다고 치고» 지나간다.
#   pre-commit(ci-gate-commit.sh)은 커밋 메시지를 볼 수 없어(메시지는 pre-commit 뒤에 확정) commit-msg 단계에 둔다.
#   사용자 결정(2026-09-06): 하네스 변경은 차단, 학습 발사는 경고(launch-set.sh --intent).
#
# ■ 판정
#   제목이 `feat:` 이고 stage 에 하네스 핵심 경로(CLAUDE.md·rules·rules-lazy·skills·agents·scripts·tools·config·settings.json)가
#   하나라도 있으면, 본문에 `Intent: intent/<파일>.md` 줄이 있어야 하고 그 파일이 stage 되었거나 추적 중이어야 한다.
#   `fix:`·`refactor:` 는 **새 파일**(name-status 의 A)이 rules·rules-lazy·agents·skills·scripts·tools·config 에 있을 때만 대상이다
#   (2026-09-14: 타입 이름만 바꿔 구조를 신설하던 우회를 닫는다). `docs:`·`chore:`·`test:`·`style:` 은 대상이 아니고
#   온톨로지 커밋(`chore(ontology)`)도 아니다.
#   jq 불필요. git 이 없거나 stage 목록을 못 읽으면 fail-closed(차단).
#
# ■ 우회 차단 2건 (2026-09-06 추가)
#   1) intent 파일의 `- 상태:` 값이 «초안» 으로 시작하면 차단. intent.md 의 값은 «사용자가 교정했다»는 데 있는데,
#      초안 그대로 커밋하면 파일만 남고 교정 단계가 빈다. 승인·위임·교정됨은 통과, 상태 줄이 아예 없으면 통과(옛 형식 보호).
#   2) `Intent:` 줄이 있는 커밋에 `graphify-out/` 이 stage 되면 차단. 온톨로지 산출물은 `chore(ontology)` 별도 커밋이다.
#      실측: 11a644c4c 에 온톨로지 3파일이 섞여 들어가 커밋을 분할해 다시 만들었다.
#
# ■ 우회 차단 3건 (2026-09-08 security 재현)
#   3) `feat!:`·`feat(scope)!:` 제목이 대상에서 빠졌다. breaking change 표시가 붙은 feat 는 더 큰 변경인데
#      느낌표 하나로 게이트를 벗어났다. 제목 앞 공백(` feat: …`)도 마찬가지였다. git 은 메시지 정리를
#      훅 뒤에 하므로 훅이 보는 제목에는 공백이 남아 있다. 그래서 앞뒤 공백을 떼고 판정한다.
#   4) 테스트 seam 이 실제 커밋에서도 먹었다. 환경변수로 stage 목록을 위조하면 게이트가 통과됐다.
#      이제 seam 은 CI_GATE_MSG_TEST=1 이 함께 있고 메시지 파일이 .git/ 아래가 아닐 때만 인정한다.
#      실제 커밋의 메시지 파일은 언제나 `.git/COMMIT_EDITMSG` 라 이 두 조건을 동시에 만족할 수 없다.
#
# ■ 선택 트레일러 `Candidate: <id>|none` (2026-10-17 G2·결정 A1): 학습 후보 대장과 커밋을 잇는다. 타입과 무관하게 검사하되
#   **실패해도 막지 않고 경고만** 낸다(id 없음·상태가 미결 3종 아님·stage 에 agents/rules/rules-lazy/skills/CLAUDE.md 변경 없음).
#   검증 본체는 ci-gate-post-commit.sh --check 와 공유하고, 해시가 생기는 연결(set accepted --note commit=<해시>)은 그 스크립트의 post-commit 몫이다.
#   id 는 사용자가 «커밋해» 지시에 적었을 때만 main 이 넣는다(skills/commit/SKILL.md).
# ■ 설치: .git/hooks/commit-msg → 이 파일 (scripts/setup-harness.sh 4-c2 가 심볼릭 링크를 만든다)
# ■ 회귀 테스트: python3 ~/.claude/scripts/tests/test_ci_gate_commit_msg.py
#   (테스트 전용 seam, CI_GATE_MSG_TEST=1 과 함께 줄 때만 인정: CI_GATE_MSG_TEST_STAGED 에 stage 목록을
#    개행 구분으로 주면 git 대신 그것을 쓴다. CI_GATE_MSG_TEST_STAGED_STATUS 는 같은 방식의 name-status 목록
#    (`A<탭>경로`)이다. CI_GATE_MSG_TEST_INTENT_BODY 를 주면 intent 파일 본문을 git·워킹트리 대신 그 값으로 읽는다)
set -uo pipefail
export LC_ALL=C

MSG_FILE="${1:-}"
[ -n "$MSG_FILE" ] && [ -r "$MSG_FILE" ] || { echo "❌ ci-gate-commit-msg FAILED — 메시지 파일을 읽을 수 없음 (fail-closed)"; exit 1; }

SUBJECT="$(grep -v '^#' "$MSG_FILE" | grep -m1 -v '^[[:space:]]*$' || true)"
SUBJECT="$(printf '%s' "$SUBJECT" | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//')"   # git 의 메시지 정리는 훅 뒤라 앞 공백이 남는다
# Jira 접두 우회 (2026-09-14 재감사): `PROJ-1 feat: …` 는 제목이 `feat:` 로 시작하지 않아 타입 판정을
#   통째로 벗어났다. 이 저장소의 651 커밋에는 아직 그 형태가 없지만 Jira 연동 커밋에서 흔한 관례라
#   한 번 쓰이면 조용히 열린다. 그래서 타입 판정 전에 티켓 접두(대괄호 형태 `[PROJ-1] ` 포함, 여러 개 가능)만 벗긴다.
SUBJECT_TYPE="$(printf '%s' "$SUBJECT" | sed -E 's/^(\[?[A-Z][A-Z0-9]+-[0-9]+\]?[[:space:]]+)+//')"

# 테스트 seam 인정 조건 — 실제 커밋에 환경변수를 붙여 stage 목록을 위조하던 우회를 닫는다.
# (2026-10-17: Candidate 트레일러 검사가 타입 판정보다 앞서 seam 여부를 알아야 해서 이 블록만 타입 case 위로 옮겼다)
SEAM_OK=false
case "$MSG_FILE" in
    .git/*|*/.git/*) ;;                      # 실제 커밋의 COMMIT_EDITMSG 는 .git/ 아래다
    *) [ "${CI_GATE_MSG_TEST:-}" = "1" ] && SEAM_OK=true ;;
esac

# Candidate 트레일러 (2026-10-17 G2·결정 A1) — 타입과 무관하게 **경고만** 한다(어떤 경우에도 커밋을 막지 않는다).
#   `Candidate: <id>` 는 학습 후보(_evolve/candidates.tsv)를 이 커밋으로 반영했다는 표시이고, 실제 연결(accepted + 해시 note)은
#   해시가 생기는 post-commit(ci-gate-post-commit.sh)이 한다. 여기서는 같은 검증(id 존재·미결 상태·agents/rules 계열 변경)을
#   미리 돌려 잘못된 트레일러를 커밋 전에 알려 준다. `Candidate: none` 은 «후보와 무관» 표시라 검사하지 않는다.
#   stage 목록은 아래 게이트(fail-closed)와 별개로 여기서 따로 읽는다 — 이 검사의 실패가 다른 타입의 커밋을 막지 않게 한다.
CAND_ID="$(grep -v '^#' "$MSG_FILE" | grep -E '^Candidate:[[:space:]]*[^[:space:]]+[[:space:]]*$' | head -n1 | sed -E 's/^Candidate:[[:space:]]*//; s/[[:space:]]*$//')"
if [ -n "$CAND_ID" ] && [ "$CAND_ID" != "none" ]; then
    CAND_CHECKER="$(dirname "$(readlink -f "$0" 2>/dev/null || echo "$0")")/ci-gate-post-commit.sh"
    if [ "$SEAM_OK" = true ] && [ -n "${CI_GATE_MSG_TEST_STAGED:-}" ]; then
        CAND_STAGED="$CI_GATE_MSG_TEST_STAGED"
    else
        # D 포함: post-commit 이 삭제도 반영 커밋으로 세므로(diff-tree) 삭제만 있는 커밋이 «스테이징 비어 있음» 으로 빠져 직전 커밋 파일을 검사하지 않게 한다(2026-10-17 검수팀)
        CAND_STAGED="$(git diff --cached -z --name-only --diff-filter=ACMRD 2>/dev/null | tr '\0' '\n' || true)"
    fi
    # `git commit --amend` 로 트레일러만 넣으면 스테이징이 0 이라 «변경 없음» 거짓 경고가 난다(2026-10-17 researcher 3차).
    # 스테이징이 비고 HEAD 가 있으면 amend 대상 커밋(HEAD)의 변경 파일로 대신 검사한다(머지는 -m 으로 부모별 diff 를 합침).
    if [ -z "$CAND_STAGED" ] && git rev-parse -q --verify HEAD >/dev/null 2>&1; then
        CAND_STAGED="$(git diff-tree --no-commit-id --name-only -r -m -z --root HEAD 2>/dev/null | tr '\0' '\n' | sort -u || true)"
    fi
    if [ -f "$CAND_CHECKER" ]; then
        CAND_WHY="$(printf '%s\n' "$CAND_STAGED" | bash "$CAND_CHECKER" --check "$CAND_ID" 2>&1)" \
            || echo "⚠ ci-gate-commit-msg: Candidate: $CAND_ID 는 연결되지 않습니다 — $CAND_WHY (경고만, 커밋은 막지 않음)" >&2
    fi
fi

KIND=""
case "$SUBJECT_TYPE" in
    feat:*|feat!:*|feat\(*) KIND=feat ;;     # 대상 (`feat(scope):`·`feat(scope)!:` 는 마지막 패턴이 함께 잡는다)
    fix:*|fix!:*|fix\(*|refactor:*|refactor!:*|refactor\(*) KIND=struct ;;   # 새 파일이 있을 때만 대상 (아래 NEW_RX)
    *) exit 0 ;;                             # 그 외 타입은 통과
esac

if [ "$SEAM_OK" = true ] && [ -n "${CI_GATE_MSG_TEST_STAGED:-}" ]; then
    STAGED="$CI_GATE_MSG_TEST_STAGED"
else
    # -z: 비ASCII·특수문자 새 경로가 인용형(`"\355…"`)으로 나와 아래 `^(rules/…)`·`^graphify-out/` 정규식을 빠져나가던 구멍(2026-10-01 감사)
    STAGED="$(git diff --cached -z --name-only --diff-filter=ACMR 2>/dev/null | tr '\0' '\n')" || { echo "❌ ci-gate-commit-msg FAILED — stage 목록을 읽을 수 없음 (fail-closed)"; exit 1; }
fi

# fix:·refactor: 로 구조를 신설하던 우회 (2026-09-06 미결 → 2026-09-14 마감).
#   타입 이름만 바꾸면 게이트를 벗어났다. 다만 두 타입의 본래 쓰임(기존 파일 수정)까지 막으면
#   일상 커밋이 전부 intent.md 를 요구하게 된다. 그래서 **새 파일**(name-status 의 A)이
#   구조 경로에 들어올 때만 대상으로 삼는다 — 규칙·에이전트·스킬·스크립트의 신설이 곧 구조 변경이다.
# 2026-09-14 재감사: `tools/`·`config/` 가 빠져 있어 CORE_RX 와 범위가 어긋났다 — 학습 발사 세트·훅 설정이
#   사는 자리라 여기 파일을 신설하는 것도 구조 변경이다. 아래 CORE_RX 에도 `config/` 를 넣어 두 범위를 맞췄다.
NEW_RX='^(rules/|rules-lazy/|agents/|skills/|scripts/|tools/|config/)'
if [ "$KIND" = struct ]; then
    if [ "$SEAM_OK" = true ] && [ -n "${CI_GATE_MSG_TEST_STAGED_STATUS:-}" ]; then
        STATUS_LIST="$CI_GATE_MSG_TEST_STAGED_STATUS"
    else
        # -z name-status 는 `상태 NUL 경로 NUL`(R·C 는 경로 2개) — 개행으로 바꾼 뒤 `상태<탭>경로…` 한 줄로 되묶는다(위 -z 와 같은 이유)
        STATUS_LIST="$(git diff --cached -z --name-status 2>/dev/null | tr '\0' '\n' | awk 'n==0{l=$0; n=($0 ~ /^[RC]/)?2:1; next} {l=l "\t" $0; if(--n==0) print l}')" || { echo "❌ ci-gate-commit-msg FAILED — stage 상태를 읽을 수 없음 (fail-closed)"; exit 1; }
    fi
    NEW_CORE="$(printf '%s\n' "$STATUS_LIST" | grep '^A' | sed -E 's/^[A-Z][0-9]*[[:space:]]+//' | grep -E "$NEW_RX" || true)"
    [ -n "$NEW_CORE" ] || exit 0           # 새 파일이 없으면 평범한 수정 커밋 — 대상 밖
fi

# `intent/../x.md` 처럼 `..` 성분이 든 경로는 intent 폴더 밖을 가리키므로 Intent 줄로 인정하지 않는다(2026-10-01 감사)
INTENT_LINE="$(grep -v '^#' "$MSG_FILE" | grep -E '^Intent:[[:space:]]*intent/[^[:space:]]+\.md[[:space:]]*$' | grep -vE '/\.\./' | head -n1 || true)"

# 온톨로지 산출물 혼입 차단 — 핵심 경로 판정보다 먼저 (Intent 커밋이면 경로 구성과 무관하게 분리한다)
if [ -n "$INTENT_LINE" ] && printf '%s\n' "$STAGED" | grep -qE '^graphify-out/'; then
    echo "❌ ci-gate-commit-msg FAILED — Intent 커밋에 온톨로지 산출물이 섞임 (commit blocked)"
    echo "  stage 에 graphify-out/ 경로가 있다. 온톨로지 산출물은 chore(ontology) 로 따로 커밋한다."
    echo "  실측 근거: 11a644c4c 에 온톨로지 3파일이 섞여 들어가 커밋을 분할해 다시 만들었다."
    echo "  git restore --staged graphify-out/ 로 뺀 뒤 이 커밋을 마치고, 온톨로지는 별도 커밋한다."
    exit 1
fi

# `config/` 포함 (2026-09-14 재감사 후 사용자 결정): systemd 유닛·scope-allow 목록처럼 게이트의 동작을
#   정하는 파일이 사는 자리라 하네스 핵심 경로와 같은 급이다. NEW_RX 와 범위를 맞춰 `config/` 만 신설한
#   fix:·refactor: 커밋이 이 검사에서 빠져나가던 사문 조항도 함께 닫힌다.
CORE_RX='^(CLAUDE\.md|settings\.json|rules/|rules-lazy/|skills/|agents/|scripts/|tools/|config/)'
if ! printf '%s\n' "$STAGED" | grep -qE "$CORE_RX"; then
    exit 0                                   # 하네스 핵심 경로가 없는 feat 는 대상 밖(예: 문서만)
fi

if [ -z "$INTENT_LINE" ] && [ "$KIND" = struct ]; then
    echo "❌ ci-gate-commit-msg FAILED — 구조 신설 커밋에 Intent 줄이 없음 (commit blocked)"
    echo "  이 커밋이 새로 만드는 파일:"
    printf '%s\n' "$NEW_CORE" | sed 's/^/    /'
    echo "  rules·rules-lazy·agents·skills·scripts·tools·config 에 파일을 **신설**하면 타입이 fix:·refactor: 라도 구조 변경이다."
    echo "  본문에  Intent: intent/YYYY-MM-DD-<slug>.md  줄을 넣어라(skills/intent/SKILL.md)."
    echo "  기존 파일만 고치는 커밋이면 이 게이트는 열리지 않는다 — 새 파일을 이 커밋에서 빼거나 /intent 로 의뢰서를 쓴다."
    exit 1
fi
if [ -z "$INTENT_LINE" ]; then
    cat <<'EOF'
❌ ci-gate-commit-msg FAILED — feat: 커밋에 Intent 줄이 없음 (commit blocked)
  하네스 핵심 경로(CLAUDE.md·rules·rules-lazy·skills·agents·scripts·tools·config·settings.json)를 바꾸는 feat: 커밋은
  본문에  Intent: intent/YYYY-MM-DD-<slug>.md  줄이 있어야 한다(skills/intent/SKILL.md).
  intent.md 가 아직 없으면 /intent 로 작성·교정·커밋한 뒤 다시 커밋하고, 작은 수정이면 fix:·refactor:·chore: 타입을 쓴다.
EOF
    exit 1
fi

INTENT_PATH="$(printf '%s' "$INTENT_LINE" | sed -E 's/^Intent:[[:space:]]*//; s/[[:space:]]*$//')"
if printf '%s\n' "$STAGED" | grep -qxF "$INTENT_PATH"; then
    :                                        # 이번 커밋에 함께 stage 됨
elif [ "$SEAM_OK" = true ] && [ -n "${CI_GATE_MSG_TEST_STAGED:-}" ]; then
    echo "❌ ci-gate-commit-msg FAILED — Intent 파일이 stage 에 없음: $INTENT_PATH (commit blocked)"; exit 1
elif git ls-files --error-unmatch -- "$INTENT_PATH" >/dev/null 2>&1; then
    :                                        # 이미 추적 중(앞서 커밋된 intent)
else
    echo "❌ ci-gate-commit-msg FAILED — Intent 파일이 추적·stage 어디에도 없음: $INTENT_PATH (commit blocked)"; exit 1
fi

# intent 파일 상태 — 「초안」 그대로 커밋하면 사용자 교정 단계가 빈다 (index → HEAD → 워킹트리 순으로 읽는다)
if [ "$SEAM_OK" = true ] && [ -n "${CI_GATE_MSG_TEST_INTENT_BODY+x}" ]; then
    INTENT_BODY="$CI_GATE_MSG_TEST_INTENT_BODY"
else
    INTENT_BODY="$(git show ":$INTENT_PATH" 2>/dev/null || git show "HEAD:$INTENT_PATH" 2>/dev/null || cat "$INTENT_PATH" 2>/dev/null || true)"
fi
STATUS_LINE="$(printf '%s\n' "$INTENT_BODY" | grep -m1 -E '^[-*][[:space:]]*상태:' || true)"
if [ -n "$STATUS_LINE" ]; then
    STATUS_VAL="$(printf '%s' "$STATUS_LINE" | sed -E 's/^[-*][[:space:]]*상태:[[:space:]]*//')"
    case "$STATUS_VAL" in
        초안*)
            echo "❌ ci-gate-commit-msg FAILED — Intent 파일이 아직 「초안」 상태 (commit blocked): $INTENT_PATH"
            echo "  intent.md 는 사용자 교정을 거친 뒤 커밋한다(skills/intent/SKILL.md)."
            echo "  상태 줄을 「승인」 또는 「위임」 으로 바꾼 뒤 다시 커밋하라. 「교정됨」 도 통과한다."
            exit 1
            ;;
    esac
fi
echo "✅ ci-gate-commit-msg PASSED (Intent: $INTENT_PATH)"
exit 0
