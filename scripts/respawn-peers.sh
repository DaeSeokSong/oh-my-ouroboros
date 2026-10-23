#!/usr/bin/env bash
# respawn-peers.sh — 하네스 갱신 뒤 같은 서버의 다른 백그라운드 세션을 다시 띄우는 명령을 «출력만» 한다(실행하지 않는다).
#
# ■ 왜(2026-10-22 사용자 지시): «하네스 갱신되면 하네스 매니저가 해당 서버의 클로드 코드 세션들에게 내용 전파 후 자신은 각 세션을
#   리스폰 시키는 명령어를 출력하여 필요시 진행하도록 보고해». 규칙·스킬 파일은 다음 읽기 때 반영되지만 mod·훅·플러그인 경로처럼
#   세션 시작 때 읽히는 것은 다시 띄워야 반영된다. 다시 띄우기는 하던 턴을 끊으므로 실행은 사용자 몫이다(rules-lazy/peer-session-messages.md).
# ■ 출력: 이 세션을 뺀 kind=background 세션마다 `claude respawn <id>` 한 줄과 이름·상태. 작업 중(busy)인 세션은 «쉴 때 실행» 표시.
#   `claude respawn --all` 은 이 세션까지 다시 띄우므로 쓰지 말라는 안내를 붙인다.
# ■ 출력은 사용자가 복사해 붙이는 명령이라 주입을 막는다(qa 2026-10-22): id 는 정확히 8자리 16진(끝 줄바꿈 불가), 이름은 C0·C1 제어 문자와
#   방향·폭 없는 문자(U+200B~200F · U+2028~202E · U+2060~2069 · U+FEFF)를 지우고 60자로 자른다. 줄은 jq 안에서 바로 만든다(탭 분리 없음).
# ■ 이 세션 id($CLAUDE_CODE_SESSION_ID)가 없으면 자기 자신을 뺄 수 없으므로 출력하지 않고 끝낸다.
# ■ 시험: $RESPAWN_AGENTS_JSON 에 `claude agents --json` 꼴 파일을 주면 그것을 읽는다(scripts/tests/test_respawn_peers.py).
set -uo pipefail

SELF="${CLAUDE_CODE_SESSION_ID:-}"
if [ -z "$SELF" ]; then
    echo "이 세션 id(CLAUDE_CODE_SESSION_ID)를 몰라 자기 자신을 뺄 수 없습니다. 출력하지 않습니다." >&2
    exit 1
fi
if [ -n "${RESPAWN_AGENTS_JSON:-}" ]; then
    AGENTS=$(cat "$RESPAWN_AGENTS_JSON" 2>/dev/null) || { echo "세션 목록 파일을 읽지 못했습니다" >&2; exit 1; }
else
    AGENTS=$(timeout 6 claude agents --json 2>/dev/null) || { echo "세션 목록(claude agents --json)을 읽지 못했습니다" >&2; exit 1; }
fi

OUT=$(printf '%s' "$AGENTS" | jq -r --arg s "$SELF" '
  def bad: (. < 32) or (. >= 127 and . <= 159) or (. >= 8203 and . <= 8207) or (. >= 8232 and . <= 8238)
           or (. >= 8288 and . <= 8297) or . == 65279;
  def clean: (if type == "string" then . else "" end) | explode | map(select(bad | not)) | implode | .[0:60];
  .[] | select(.kind == "background" and .sessionId != $s)
  | (.id // "") as $id | select(($id | type) == "string" and ($id | length) == 8 and ($id | test("^[0-9a-f]{8}$")))
  | (.name | clean) as $n | (.status | clean) as $st
  | "claude respawn \($id)   # \(if $n == "" then "이름 없음" else $n end) (\(if $st == "busy" then "작업 중 · 쉴 때 실행" elif $st == "" then "?" else $st end))"
' 2>/dev/null) || { echo "세션 목록을 해석하지 못했습니다" >&2; exit 1; }

if [ -z "$OUT" ]; then
    echo "다시 띄울 다른 백그라운드 세션이 없습니다."
    exit 0
fi
echo "# 하네스 갱신 반영용 다시 띄우기(필요할 때만, 사용자 직접 실행). 작업 중인 세션은 쉴 때 실행하십시오."
echo "# claude respawn --all 은 이 세션까지 다시 띄우므로 쓰지 않습니다."
printf '%s\n' "$OUT"
