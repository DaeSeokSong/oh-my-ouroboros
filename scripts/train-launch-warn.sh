#!/usr/bin/env bash
# train-launch-warn.sh — PreToolUse(Bash) 훅: 학습 발사 명령 감지 시 경고만 출력 (차단 금지)
#   학습 진입점 직접 실행(스크립트 파일·모듈·torchrun·lightning CLI) 또는 tmux send-keys 로 학습 진입점 · *launch*.sh 런처를 전달하는
#   명령을 감지하면 hookSpecificOutput.additionalContext 로 경고를 내고 exit 0 으로 통과시킨다. 첫 토큰이 읽기 명령이면 발사로 보지 않는다.
# NEVER: 종료 코드를 0 밖으로 바꾸지 않는다. 경고만 내는 것은 사용자 지시다(2026-09-13, 2026-09-14 감사 때 재확인).
# NEVER: permissionDecision 을 내지 않는다. allow 는 경고가 아니라 권한 부여라 학습 발사에 대한 사용자 승인 프롬프트를 우회시킬 수 있다(2026-07-27 main 교정).
# REF: knowledge/harness/code-history/scripts__train-launch-warn.sh.md
set -uo pipefail

INPUT=$(cat 2>/dev/null) || exit 0
CMD=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)
[ -z "$CMD" ] && exit 0

# WHY: 학습 파일을 읽기만 하는 명령(`grep train_demo.py tools/`)에도 발사 경고가 떴다(2026-09-14 재감사). 경고가 흔해지면
# 진짜 발사에서도 읽히지 않는다. 발사는 언제나 실행 형태(python·uv run·torchrun·lightning·bash·tmux send-keys)로 시작한다.
FIRST_TOK=$(printf '%s' "$CMD" | head -1 | sed -E 's/^[[:space:]]*//; s/[[:space:]].*$//; s#.*/##')
case "$FIRST_TOK" in
  grep|rg|cat|ls|head|tail|sed|awk|wc|find|stat|file|less|diff|git) exit 0 ;;
esac

# WHY: 실제 발사 관례는 tmux send-keys 로 런처 셸 스크립트(*_launch.sh)를 거쳐 train.py 가 명령줄에 안 보인다(2026-07-27 실측 테스트).
# NEVER: 파일명 뒤에 종결자 `([[:space:]]|$)` 를 두지 않는다. tmux 명령의 인용 끝에서 매칭이 깨졌다(실측, 2026-09-14 감사). 앞 경계의 따옴표는 `pretrain.py` 같은 접두 오탐만 막는다.
LAUNCH_RX='(^|[[:space:]/"'"'"'])(train[a-z_]*|run_trains?)\.py|python[0-9.]*[[:space:]]+-m[[:space:]]+[a-z_.]*train|torchrun[[:space:]][^;&|]*train|lightning[[:space:]][^;&|]*fit'
IS_LAUNCH=false
echo "$CMD" | grep -qE "$LAUNCH_RX" && IS_LAUNCH=true
if echo "$CMD" | grep -qE 'tmux[[:space:]]+send-keys' \
   && echo "$CMD" | grep -qE "$LAUNCH_RX"'|[A-Za-z0-9_./-]*launch[A-Za-z0-9_.-]*\.sh'; then
  IS_LAUNCH=true
fi

if $IS_LAUNCH; then
  MSG='[학습 발사 감지 — 경고만, 차단 아님] (1) 체크포인트/모듈성 지표를 신설·수정했다면: 대상 현상 반대방향으로 조작 시 값이 실제로 변하는지 합성값 스크립트로 확인했는가? (coding-conventions.md § 지표 감도 검증) (2) 이번 arm이 대조군과 수식상 완전히 소거되지 않는지 수치로 반증했는가? (agent-routing.md § 구현 후 계획-대비 검수 게이트) (3) 이 실험의 의뢰서 intent.md 가 커밋돼 있고 명령서가 launch-set.sh --intent 로 그 경로를 가리키는가? (skills/intent) 셋 중 하나라도 아니면 발사 전 검수 게이트를 거치세요.'
  # WHY: PreToolUse 의 exit 0 평문 stdout 은 모델에 전달되지 않는다(공식 문서, 2026-10-01 감사).
  jq -nc --arg m "$MSG" '{hookSpecificOutput: {hookEventName: "PreToolUse", additionalContext: $m}}'
fi

exit 0
