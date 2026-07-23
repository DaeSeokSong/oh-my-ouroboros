#!/usr/bin/env bash
# Mem0 MCP 런처 — API 키를 .claude 로컬 secrets 파일(mcp-secrets.env, 600)에서만 읽어 주입한다.
# MEM0_DEFAULT_USER_ID(비밀 아님)는 settings.json env 블록에서 상속된다.
set -euo pipefail

SECRETS_FILE="$HOME/.claude/mcp-secrets.env"
if [[ -f "$SECRETS_FILE" ]]; then
  set -a                 # 이후 source되는 변수를 export 형식 무관하게 자동 export
  # shellcheck disable=SC1090
  source "$SECRETS_FILE"
  set +a
else
  echo "[launch-mem0] $SECRETS_FILE 없음 — MEM0_API_KEY 미설정" >&2
fi

exec "$HOME/.local/bin/uvx" mem0-mcp-server
