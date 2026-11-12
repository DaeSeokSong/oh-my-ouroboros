#!/usr/bin/env bash
# Tavily MCP 런처 — API 키를 .claude 로컬 secrets 파일(mcp-secrets.env, 600)에서만 읽어 주입한다.
# settings.json·전역 셸 env에 평문 키를 두지 않기 위한 래퍼.
set -euo pipefail

SECRETS_FILE="$HOME/.claude/mcp-secrets.env"
if [[ -f "$SECRETS_FILE" ]]; then
  set -a                 # 이후 source되는 변수를 export 형식 무관하게 자동 export
  # shellcheck disable=SC1090
  source "$SECRETS_FILE"
  set +a
else
  echo "[launch-tavily] $SECRETS_FILE 없음 — TAVILY_API_KEY 미설정" >&2
fi

# npx 경로는 머신마다 다름(서버마다 nvm 또는 system) → 동적 해석: nvm(최신) → PATH → 절대경로 폴백
_resolve() {
  local b="$1" c
  # The glob lists only existing files (like ls did); with no match it stays literal and fails the -x test below.
  c="$(printf '%s\n' "$HOME"/.nvm/versions/node/*/bin/"$b" | sort -V | tail -1 || true)"
  [[ -n "$c" && -x "$c" ]] && { printf '%s\n' "$c"; return 0; }
  c="$(command -v "$b" 2>/dev/null || true)"
  [[ -n "$c" ]] && { printf '%s\n' "$c"; return 0; }
  for c in /usr/local/bin/"$b" /usr/bin/"$b" "$HOME/.local/bin/$b" "$HOME/anaconda3/bin/$b"; do
    [[ -x "$c" ]] && { printf '%s\n' "$c"; return 0; }
  done
  return 1
}
NPX="$(_resolve npx)" || { echo "[launch-tavily] npx not found" >&2; exit 127; }
exec "$NPX" -y tavily-mcp@latest
