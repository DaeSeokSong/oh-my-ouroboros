#!/usr/bin/env bash
# SessionStart 훅용. /clear로 새 세션이 시작될 때(source=="clear")만 비차단 리마인더를
# stdout으로 출력한다 → SessionStart stdout은 새 세션 컨텍스트(additionalContext)로 주입되어
# Claude가 사용자에게 전달 가능. (훅은 인터랙티브 선택지 불가 — 공식 문서 확인. 그래서
# "선택지" 대신 정보 주입 + /cost-reset 스킬로 사용자 제어.)
# 서버 누적 cost는 clear에 영향받지 않음(coralline ledger가 세션별 파일 보존).
input=$(cat)
PY=$(command -v python3 || command -v python)
[ -z "$PY" ] && exit 0
src=$(printf '%s' "$input" | "$PY" -c "import sys,json;print(json.load(sys.stdin).get('source',''))" 2>/dev/null)
if [ "$src" = "clear" ]; then
  printf '[cost] 직전 세션이 /clear로 종료됨 — 서버 누적 cost는 그대로 보존됩니다(이 새 세션만 0부터). 확인: /cost 또는 /cost all. 전체 누적을 0부터 새로 시작하려면: /cost-reset\n'
fi
exit 0
