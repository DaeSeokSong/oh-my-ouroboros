#!/usr/bin/env bash
# train-launch-warn.sh — PreToolUse(Bash) 훅: 학습 발사 명령 감지 시 경고만 출력 (차단 금지)
#
# 배경 (판단 근거 이식, 2026-07-27): 같은 계보의 실패 3건 중 실비용을 낸 사고는
# 체크포인트 기준 복합 지표가 연구 대상 현상(zero-sum)에 원리적으로 무감(성분 mean 상쇄)한
# 채로 멀티-arm 캠페인(GPU ~10h)이 발사→결론→철회된 것이다 (지표·수치 상세는 공개 미러
# 비대상 위치로 분리: knowledge/project-C/ckpt-criteria-modularity.md § 지표 감도 사고).
# 판정 주체가 main 자신이었던 사고도 있어(외부 기법 오분류 건), "모델이 기억해서
# 되묻는다"는 룰 순응에만 의존하면 확률적이다 — 훅이면 결정적이다
# (config/hooks/README.md 판례 "룰 순응은 확률적, 훅은 결정적" 재사용).
#
# 동작: train.py/run_trains.py 직접 실행 또는 tmux send-keys로 학습 스크립트를 전달하는
# 명령을 감지하면 경고 문구를 **stdout으로 출력하고 exit 0**으로 통과시킨다.
# **차단하지 않는다** — 사용자 지시는 "경고만"이다.
#
# ★permissionDecision을 쓰지 않는 이유 (2026-07-27 main 교정): 초안은
# `permissionDecision: "allow"`를 반환했으나 allow는 경고가 아니라 **권한 부여**라,
# 학습 발사에 대한 사용자 승인 프롬프트를 우회시킬 수 있다. 지시는 "경고만"이었지
# "자동 승인"이 아니었고 GPU 발사는 사용자 주권 영역이다(rules/code-execution.md:
# 학습 본 실행은 항상 사용자 직접, 검증 예외에 포함되지 않음). 다른 PreToolUse 훅
# (bash-write-check.sh 등)의 판단과 간섭할 위험도 있다. 경고 목적엔 stdout이면
# 충분하므로 이 훅은 **권한 결정에 일절 관여하지 않는다**.
set -uo pipefail

INPUT=$(cat 2>/dev/null) || exit 0
CMD=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)
[ -z "$CMD" ] && exit 0

# 학습 발사 패턴 탐지.
#  ★(b)의 범위 교정(2026-07-27 main, 실측 테스트로 발견): 초안은 tmux send-keys 안에
#  `train.py`가 **직접 보일 때만** 잡았으나, 이 프로젝트의 실제 발사 관례는
#  `tmux send-keys -t bi "bash tools/<캠페인>/<...>_launch.sh <gpu> <arm> <seed>" Enter`
#  처럼 **런처 셸 스크립트를 경유**한다(train.py는 그 안에서 호출되므로 명령줄에 안 보임).
#  초안 그대로면 실제 발사를 하나도 못 잡아 훅이 무용지물이 된다 — 런처 패턴을 추가한다.
#  (false positive 가드: tmux send-keys 없이 단순히 "launch" 단어만 있는 명령은 잡지 않는다.)
IS_LAUNCH=false
# (a) train.py / run_trains(?).py 직접 실행
echo "$CMD" | grep -qE '(^|[[:space:]/])(train\.py|run_trains?\.py)([[:space:]]|$)' && IS_LAUNCH=true
# (b) tmux send-keys + (학습 스크립트 | *launch*.sh 런처)
if echo "$CMD" | grep -qE 'tmux[[:space:]]+send-keys' \
   && echo "$CMD" | grep -qE '(train\.py|run_trains?\.py|[A-Za-z0-9_./-]*launch[A-Za-z0-9_.-]*\.sh)'; then
  IS_LAUNCH=true
fi

if $IS_LAUNCH; then
  MSG='[학습 발사 감지 — 경고만, 차단 아님] (1) 체크포인트/모듈성 지표를 신설·수정했다면: 대상 현상 반대방향으로 조작 시 값이 실제로 변하는지 합성값 스크립트로 확인했는가? (coding-conventions.md § 지표 감도 검증) (2) 이번 arm이 대조군과 수식상 완전히 소거되지 않는지 수치로 반증했는가? (agent-routing.md § 구현 후 계획-대비 검수 게이트) 둘 다 확인 못 했다면 발사 전 검수 게이트를 거치세요.'
  # 권한 결정 JSON을 내지 않는다(위 근거) — 순수 stdout 경고.
  printf '%s\n' "$MSG"
fi

exit 0
