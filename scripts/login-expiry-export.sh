#!/usr/bin/env bash
# Claude 로그인 만료 시각(밀리초) 숫자 한 값만 뽑아 _usage/login-expiry 에 한 줄로 쓴다(intent/2026-11-16-login-expiry-band-warning.md 성공 기준 1).
# 띠는 이 숫자 파일만 읽는다.
# 토큰을 남기지 않는다: grep -o 로 «refreshTokenExpiresAt: 숫자» 조각만 뽑고 파일 전체를 변수 · 출력 · 로그에 담지 않는다. stdout 출력 없음.
# 13자리 안팎(12~14자리) 숫자가 아니면 아무것도 쓰지 않고 exit 0(API 키 환경 · 다른 서버에서 조용).
# 환경 변수 CLAUDE_CREDENTIALS · CLAUDE_LOGIN_EXPIRY_FILE 은 시험용 경로 지정이다.
# REF: knowledge/harness/code-history/scripts__login-expiry-export.sh.md
set -u
SRC="${CLAUDE_CREDENTIALS:-$HOME/.claude/.credentials.json}"
DST="${CLAUDE_LOGIN_EXPIRY_FILE:-$HOME/.claude/_usage/login-expiry}"
[ -r "$SRC" ] || exit 0
VAL=$(grep -o '"refreshTokenExpiresAt" *: *[0-9]\{1,20\}' "$SRC" 2>/dev/null | head -n 1 | sed 's/.*: *//')
[[ "$VAL" =~ ^[0-9]{12,14}$ ]] || exit 0
[ "$(cat "$DST" 2>/dev/null)" = "$VAL" ] && exit 0
mkdir -p "$(dirname "$DST")" 2>/dev/null || exit 0
# WHY: 임시 파일은 mktemp 로 같은 폴더에 만든다(이름 예측 · 미리 심은 링크 따라 쓰기 방지, 2026-11-16 security 참고 반영).
TMP=$(mktemp "$DST.tmp.XXXXXX" 2>/dev/null) || exit 0
if printf '%s\n' "$VAL" > "$TMP" 2>/dev/null; then mv -f "$TMP" "$DST" 2>/dev/null || rm -f "$TMP"; else rm -f "$TMP"; fi
exit 0
