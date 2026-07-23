#!/usr/bin/env bash
# OpenReview MCP 런처 — 자격증명을 .claude 로컬 secrets 파일에서만 읽어 이 프로세스에만 주입한다.
# 비밀값을 MCP 설정(~/.claude.json)·전역 셸 env 어디에도 두지 않기 위한 래퍼.
# secrets 파일은 .gitignore(mcp-secrets.env) + chmod 600 으로 보호한다.
set -euo pipefail

SECRETS_FILE="$HOME/.claude/mcp-secrets.env"
if [[ -f "$SECRETS_FILE" ]]; then
  set -a                 # 이후 source되는 변수를 export 형식 무관하게 자동 export
  # shellcheck disable=SC1090
  source "$SECRETS_FILE"
  set +a
else
  echo "[launch-openreview] $SECRETS_FILE 없음 — OPENREVIEW_USERNAME/PASSWORD 미설정" >&2
fi

# 서버 디렉토리로 이동 (export dir 등 상대경로 + 모듈 해석 안정화)
cd "$HOME/.claude/mcp-servers/openreview-mcp-server"
exec "$HOME/.claude/mcp-servers/openreview-mcp-server/venv/bin/python" -m openreview_mcp_server
