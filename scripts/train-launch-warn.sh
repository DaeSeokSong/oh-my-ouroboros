#!/usr/bin/env bash
# train-launch-warn.sh — PreToolUse(Bash) 훅: 학습 발사 명령 감지 시 경고만 출력 (차단 금지)
#
# 배경 (판단 근거 이식, 2026-07-27): 같은 계보의 실패 3건 중 실비용을 낸 사고는
# 체크포인트 기준 복합 지표가 연구 대상 현상(zero-sum)에 원리적으로 무감(성분 mean 상쇄)한
# 채로 멀티-arm 캠페인(GPU ~10h)이 발사→결론→철회된 것이다.
# 판정 주체가 main 자신이었던 사고도 있어(외부 기법 오분류 건), "모델이 기억해서
# 되묻는다"는 룰 순응에만 의존하면 확률적이다 — 훅이면 결정적이다
# (config/hooks/README.md 판례 "룰 순응은 확률적, 훅은 결정적" 재사용).
#
# 동작: 학습 진입점 직접 실행 또는 tmux send-keys로 학습 스크립트를 전달하는
# 명령을 감지하면 경고 문구를 **stdout으로 출력하고 exit 0**으로 통과시킨다.
# **차단하지 않는다** — 사용자 지시는 "경고만"이다.
#
# ★경고 유지 결정 (2026-09-13 사용자 지시 — 2026-09-14 감사 때 재확인): 발사 게이트를 차단으로
# 승격하자는 제안(launch-set.sh --intent 강제)은 «규칙만 추가하고 강제 검사는 넣지 말라»는 지시에
# 막혀 보류됐다. 그래서 이 훅의 종료 코드는 앞으로도 0 이고 탐지 범위만 넓힌다. 탐지 범위를 넓히는 것은
# 경고를 못 받던 발사(train_mtl.py 류)에 같은 경고를 주는 일이라 «강제 검사 추가»에 해당하지 않는다.
#
# ★permissionDecision을 쓰지 않는 이유 (2026-07-27 main 교정): 초안은
# `permissionDecision: "allow"`를 반환했으나 allow는 경고가 아니라 **권한 부여**라,
# 학습 발사에 대한 사용자 승인 프롬프트를 우회시킬 수 있다. 지시는 "경고만"이었지
# "자동 승인"이 아니었고 GPU 발사는 사용자 주권 영역이다(rules/code-execution.md:
# 2026-09-29 부터 main 의 tmux 발사가 예외로 허용됐지만, 허가는 여전히 Claude Code 권한
# 설정의 몫이고 이 훅이 대신 내주지 않는다). 다른 PreToolUse 훅
# (bash-write-check.sh 등)의 판단과 간섭할 위험도 있다. 경고 목적엔 stdout이면
# 충분하므로 이 훅은 **권한 결정에 일절 관여하지 않는다**.
set -uo pipefail

INPUT=$(cat 2>/dev/null) || exit 0
CMD=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)
[ -z "$CMD" ] && exit 0

# 읽기 명령 오탐 제외 (2026-09-14 재감사): 탐지 범위를 넓힌 뒤 `grep train_mtl.py tools/`·
#   `cat tools/train_mtl.py` 처럼 학습 파일을 **읽기만** 하는 명령에도 발사 경고가 떴다. 경고가 흔해지면
#   진짜 발사에서도 읽히지 않는다. 첫 토큰(파이프라인 첫 단계의 명령 이름)이 읽기 명령이면 발사가 아니다 —
#   발사는 언제나 실행 형태(python·uv run·torchrun·lightning·bash·tmux send-keys)로 시작한다.
#   경로 접두(`/usr/bin/grep`)는 떼고 본다. 토큰 하나로만 판단하는 한계는 감수한다: 이 훅은 차단이 아니라 경고다.
FIRST_TOK=$(printf '%s' "$CMD" | head -1 | sed -E 's/^[[:space:]]*//; s/[[:space:]].*$//; s#.*/##')
case "$FIRST_TOK" in
  grep|rg|cat|ls|head|tail|sed|awk|wc|find|stat|file|less|diff|git) exit 0 ;;
esac

# 학습 발사 패턴 탐지.
#  ★(b)의 범위 교정(2026-07-27 main, 실측 테스트로 발견): 초안은 tmux send-keys 안에
#  `train.py`가 **직접 보일 때만** 잡았으나, 이 프로젝트의 실제 발사 관례는
#  `tmux send-keys -t bi "bash tools/<캠페인>/<...>_launch.sh <gpu> <arm> <seed>" Enter`
#  처럼 **런처 셸 스크립트를 경유**한다(train.py는 그 안에서 호출되므로 명령줄에 안 보임).
#  초안 그대로면 실제 발사를 하나도 못 잡아 훅이 무용지물이 된다 — 런처 패턴을 추가한다.
#  (false positive 가드: tmux send-keys 없이 단순히 "launch" 단어만 있는 명령은 잡지 않는다.)
#  ★범위 확장(2026-09-14 감사): 종전 정규식은 `train.py`·`run_trains?.py` **리터럴**이라
#  `train_mtl.py` 류 실제 진입점과 모듈·런처 실행(`python -m pkg.train`·`torchrun … train`·
#  `lightning … fit`)에는 경고조차 뜨지 않았다(_audit/loop-audit-20260914.md §3).
#  파일명은 토큰 앞머리가 train 인 것까지(`train[a-z_]*.py`), 나머지는 실행 형태로 넓힌다.
#  파일명 뒤 종결자는 두지 않는다 — 종전의 `([[:space:]]|$)` 는 tmux 명령의 인용 끝
#  (`… "uv run python tools/train_mtl.py" Enter`)에서 매칭이 깨졌다(실측). 앞 경계에 따옴표를 넣어
#  `pretrain.py` 같은 접두 오탐만 막는다.
LAUNCH_RX='(^|[[:space:]/"'"'"'])(train[a-z_]*|run_trains?)\.py|python[0-9.]*[[:space:]]+-m[[:space:]]+[a-z_.]*train|torchrun[[:space:]][^;&|]*train|lightning[[:space:]][^;&|]*fit'
IS_LAUNCH=false
# (a) 학습 진입점 직접 실행 (스크립트 파일·모듈·torchrun·lightning CLI)
echo "$CMD" | grep -qE "$LAUNCH_RX" && IS_LAUNCH=true
# (b) tmux send-keys + (학습 진입점 | *launch*.sh 런처)
if echo "$CMD" | grep -qE 'tmux[[:space:]]+send-keys' \
   && echo "$CMD" | grep -qE "$LAUNCH_RX"'|[A-Za-z0-9_./-]*launch[A-Za-z0-9_.-]*\.sh'; then
  IS_LAUNCH=true
fi

if $IS_LAUNCH; then
  MSG='[학습 발사 감지 — 경고만, 차단 아님] (1) 체크포인트/모듈성 지표를 신설·수정했다면: 대상 현상 반대방향으로 조작 시 값이 실제로 변하는지 합성값 스크립트로 확인했는가? (coding-conventions.md § 지표 감도 검증) (2) 이번 arm이 대조군과 수식상 완전히 소거되지 않는지 수치로 반증했는가? (agent-routing.md § 구현 후 계획-대비 검수 게이트) (3) 이 실험의 의뢰서 intent.md 가 커밋돼 있고 명령서가 launch-set.sh --intent 로 그 경로를 가리키는가? (skills/intent) 셋 중 하나라도 아니면 발사 전 검수 게이트를 거치세요.'
  # 권한 결정(permissionDecision)은 내지 않는다(위 근거) — additionalContext 만 낸다.
  # 2026-10-01 감사: PreToolUse 의 exit 0 평문 stdout 은 모델에 전달되지 않는다(공식 문서). 경고가 닿으려면
  # hookSpecificOutput.additionalContext JSON 이어야 한다. 차단이 아니라 «닿게» 하는 수정이다(D2).
  jq -nc --arg m "$MSG" '{hookSpecificOutput: {hookEventName: "PreToolUse", additionalContext: $m}}'
fi

exit 0
