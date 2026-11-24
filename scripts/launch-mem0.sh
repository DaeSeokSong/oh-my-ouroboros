#!/usr/bin/env bash
# Mem0 MCP 런처 — API 키를 .claude 로컬 secrets 파일(mcp-secrets.env, 600)에서만 읽어 주입한다.
# MEM0_DEFAULT_USER_ID(비밀 아님)는 settings.json env 블록에서 상속된다.
set -euo pipefail

SECRETS_FILE="$HOME/.claude/mcp-secrets.env"
if [[ -f "$SECRETS_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$SECRETS_FILE"
  set +a
else
  echo "[launch-mem0] $SECRETS_FILE 없음 — MEM0_API_KEY 미설정" >&2
fi

# WHY: mcp SDK 2.0.0(2026-08 릴리스)이 mcp.server.fastmcp를 제거해 mem0-mcp-server가 기동 불능
# (ModuleNotFoundError 실측 2026-08-03) — 서버가 상한 없이 의존해 uv 재해석 시마다 파손.
exec "$HOME/.local/bin/uvx" --with "mcp<2" mem0-mcp-server
