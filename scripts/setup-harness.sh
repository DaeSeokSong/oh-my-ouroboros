#!/usr/bin/env bash
# setup-harness.sh — ~/.claude 하네스 머신-로컬 셋업 (멱등)
# 새 서버에서 git pull 후 1회 실행으로 플러그인 설치 + statusline 배선 완료.
# MCP·settings.json·시크릿은 건드리지 않음.
#
# 사용법: bash ~/.claude/scripts/setup-harness.sh
# REF: knowledge/harness/code-history/scripts__setup-harness.sh.md
set -euo pipefail

SETTINGS_FILE="${HOME}/.claude/settings.json"
HUD_DIR="${HOME}/.claude/hud"
HUD_LAUNCHER="${HUD_DIR}/claudenews-hud.mjs"
CLAUDENEWS_DIR="${HOME}/.claudenews"
CLAUDENEWS_CONFIG="${CLAUDENEWS_DIR}/config.json"
CORALLINE_SCRIPT="${HOME}/.claude/coralline/statusline.sh"
STATUSLINE_CMD="bash ~/.claude/coralline/statusline.sh"
CANDIDATES_TSV="${HOME}/.claude/_evolve/candidates.tsv"

ok()   { echo "[OK]   $*"; }
skip() { echo "[SKIP] $*"; }
warn() { echo "[WARN] $*" >&2; }
info() { echo "       $*"; }

echo "========================================================"
echo " ~/.claude harness setup"
echo "========================================================"
echo ""

echo "── 섹션 1: 의존성 감지 ─────────────────────────────────"

HAS_CLAUDE=0

if command -v node >/dev/null 2>&1; then
  NODE_VER="$(node --version 2>/dev/null || echo 'unknown')"
  ok "node 발견: ${NODE_VER}"
else
  warn "node 없음 — 섹션 3(HUD 런처 실행)은 배선만 하고 실행 검증은 skip"
fi

if command -v claude >/dev/null 2>&1; then
  CLAUDE_VER="$(claude --version 2>/dev/null || echo 'unknown')"
  ok "claude CLI 발견: ${CLAUDE_VER}"
  HAS_CLAUDE=1
else
  warn "claude CLI 없음 — 섹션 2(plugin 설치)는 skip"
fi

if command -v git >/dev/null 2>&1; then
  GIT_VER="$(git --version 2>/dev/null || echo 'unknown')"
  ok "git 발견: ${GIT_VER}"
else
  warn "git 없음 — git 관련 단계 skip"
fi

echo ""

echo "── 섹션 2: 플러그인 설치 ───────────────────────────────"

if [[ "${HAS_CLAUDE}" -eq 0 ]]; then
  warn "claude CLI 없어 섹션 2 전체 skip"
elif [[ ! -f "${SETTINGS_FILE}" ]]; then
  warn "settings.json 없음 (${SETTINGS_FILE}) — 섹션 2 skip"
else
  PARSE_OK=0
  PLUGIN_DATA=""
  PLUGIN_DATA="$(SETTINGS_FILE="${SETTINGS_FILE}" python3 - <<'PYEOF'
import json, sys, os

try:
    with open(os.environ["SETTINGS_FILE"]) as f:
        cfg = json.load(f)
except Exception as e:
    print(f"ERROR: {e}", file=sys.stderr)
    sys.exit(1)

marketplaces = cfg.get("extraKnownMarketplaces", {})
enabled = cfg.get("enabledPlugins", {})

# 출력: "marketplace_name|owner/repo"  한 줄씩
for name, meta in marketplaces.items():
    try:
        repo = meta["source"]["repo"]
    except (KeyError, TypeError):
        repo = ""
    print(f"MARKET|{name}|{repo}")

# 출력: "plugin@marketplace"  한 줄씩 (값이 true인 것만)
for key, val in enabled.items():
    if val:
        print(f"PLUGIN|{key}")
PYEOF
  )" && PARSE_OK=1 || true

  if [[ "${PARSE_OK}" -eq 0 ]] || [[ -z "${PLUGIN_DATA}" ]]; then
    warn "settings.json 파싱 실패 — 섹션 2 skip"
  else
    echo "  [2-a] 마켓플레이스 등록"

    MARKET_LIST=""
    MARKET_LIST="$(claude plugin marketplace list 2>/dev/null || true)"

    while IFS='|' read -r kind name repo; do
      [[ "${kind}" != "MARKET" ]] && continue
      if [[ -z "${repo}" ]]; then
        warn "마켓플레이스 '${name}' repo 정보 없음 — skip"
        continue
      fi
      if echo "${MARKET_LIST}" | grep -qF "${name}" 2>/dev/null; then
        skip "marketplace '${name}' 이미 등록됨"
      else
        echo "  → claude plugin marketplace add ${repo}  (${name})"
        if ! { claude plugin marketplace add "${repo}" 2>/dev/null \
          && ok "marketplace '${name}' 등록 완료"; }; then
          warn "marketplace '${name}' 등록 실패 (이미 있거나 네트워크 오류 가능) — 계속 진행"
        fi
      fi
    done <<< "${PLUGIN_DATA}"

    echo "  [2-b] 플러그인 설치"

    PLUGIN_LIST=""
    PLUGIN_LIST="$(claude plugin list 2>/dev/null || true)"

    while IFS='|' read -r kind spec; do
      [[ "${kind}" != "PLUGIN" ]] && continue
      PNAME="${spec%%@*}"
      if echo "${PLUGIN_LIST}" | grep -qF "${PNAME}" 2>/dev/null; then
        skip "plugin '${spec}' 이미 설치됨"
      else
        echo "  → claude plugin install ${spec} --scope user"
        if ! { claude plugin install "${spec}" --scope user 2>/dev/null \
          && ok "plugin '${spec}' 설치 완료"; }; then
          warn "plugin '${spec}' 설치 실패 — 계속 진행"
        fi
      fi
    done <<< "${PLUGIN_DATA}"
  fi
fi

echo ""

echo "── 섹션 3: HUD/statusline 배선 ─────────────────────────"

mkdir -p "${HUD_DIR}"
ok "디렉토리 확보: ${HUD_DIR}"

if [[ -f "${HUD_LAUNCHER}" ]]; then
  skip "HUD 런처 이미 존재: ${HUD_LAUNCHER}"
else
  cat > "${HUD_LAUNCHER}" <<'HUDEOF'
#!/usr/bin/env node
/**
 * Thin status-line launcher. setup installs THIS at
 * ~/.claude/hud/claudenews-hud.mjs once; it then locates the newest
 * installed plugin version's real hud and delegates to it. So plugin
 * updates take effect with no /claudenews:setup re-run — the launcher
 * never needs to change.
 *
 * Fails safe: if no cached hud is found it prints a blank line so the
 * status line is never broken.
 */
import { readdirSync, existsSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { homedir } from "node:os";
import { join } from "node:path";

const base = join(homedir(), ".claude/plugins/cache/claudenews/claudenews");

let target = null;
try {
  const vers = readdirSync(base)
    .filter((v) => /^\d+\.\d+\.\d+/.test(v))
    .sort((a, b) => {
      const A = a.split(".").map(Number);
      const B = b.split(".").map(Number);
      return B[0] - A[0] || B[1] - A[1] || B[2] - A[2];
    });
  for (const v of vers) {
    const p = join(base, v, "hud/claudenews-hud.mjs");
    if (existsSync(p)) {
      target = p;
      break;
    }
  }
} catch {}

if (target) {
  const r = spawnSync("node", [target], {
    stdio: ["inherit", "inherit", "inherit"],
  });
  process.exit(r.status ?? 0);
}

process.stdout.write("\n");
HUDEOF
  chmod +x "${HUD_LAUNCHER}"
  ok "HUD 런처 생성 완료: ${HUD_LAUNCHER}"
fi

mkdir -p "${CLAUDENEWS_DIR}"

python3 - <<PYEOF
import json, uuid, os, sys

config_path = os.path.expanduser("${CLAUDENEWS_CONFIG}")
statusline_cmd = "${STATUSLINE_CMD}"

if os.path.exists(config_path):
    try:
        with open(config_path) as f:
            cfg = json.load(f)
    except Exception as e:
        print(f"[WARN] config.json 읽기 실패: {e}", file=sys.stderr)
        sys.exit(0)

    old_val = cfg.get("parentStatusLine", "")
    cfg["parentStatusLine"] = statusline_cmd

    with open(config_path, "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")

    if old_val == statusline_cmd:
        print(f"[SKIP] config.json parentStatusLine 이미 올바름")
    else:
        print(f"[OK]   config.json parentStatusLine 업데이트: '{old_val}' → '{statusline_cmd}'")
else:
    cfg = {
        "parentStatusLine": statusline_cmd,
        "installId": str(uuid.uuid4()),
        "sources": {"hn": True, "github": True}
    }
    with open(config_path, "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    print(f"[OK]   config.json 신규 생성: {config_path}")
PYEOF

if [[ -f "${CORALLINE_SCRIPT}" ]]; then
  ok "coralline statusline.sh 존재 확인: ${CORALLINE_SCRIPT}"
else
  warn "coralline/statusline.sh 없음 (${CORALLINE_SCRIPT}) — git pull로 하네스를 최신화하세요"
fi

if [[ -f "${CANDIDATES_TSV}" ]]; then
  skip "candidates.tsv 이미 존재: ${CANDIDATES_TSV}"
else
  mkdir -p "$(dirname "${CANDIDATES_TSV}")"
  printf 'id\tsource\t생성일\tbench_id\tstatus\t요약\n' > "${CANDIDATES_TSV}"
  ok "candidates.tsv 헤더 생성: ${CANDIDATES_TSV}"
fi

echo ""

# WHY: /model 명령이 "새 세션 기본값"을 추적되는 settings.json 에 직접 써 git status/diff 소음이 된다(2026-09-28).
# 실제 유효 모델은 settings.local.json pin(있으면)이 재시작 시 이기므로(rules/model-assignment.md) settings.json 의
# "model" 키는 버려도 실제 동작이 바뀌지 않는다. .git/config 는 clone 마다 새로 설정해야 하는 로컬 배선이라 여기서 건다.
echo "── 섹션 3.5: git model-키 필터 배선 ────────────────────"
if git -C "${HOME}/.claude" rev-parse --git-dir >/dev/null 2>&1; then
  git -C "${HOME}/.claude" config filter.nomodel.clean "python3 ${HOME}/.claude/scripts/git-filter-nomodel-clean.py"
  git -C "${HOME}/.claude" config filter.nomodel.smudge cat
  if ! grep -qE '^settings\.json filter=nomodel$' "${HOME}/.claude/.gitattributes" 2>/dev/null; then
    echo "settings.json filter=nomodel" >> "${HOME}/.claude/.gitattributes"
    ok ".gitattributes 에 settings.json filter=nomodel 추가"
  else
    skip ".gitattributes 에 이미 등록됨"
  fi
  ok "git config filter.nomodel.{clean,smudge} 등록 (settings.json 의 model 키를 diff 계산에서 제외)"
else
  # shellcheck disable=SC2088
  warn "~/.claude 가 git 저장소가 아님 — 필터 배선 건너뜀"
fi

echo ""

echo "── 섹션 4: 검증 ────────────────────────────────────────"

if [[ "${HAS_CLAUDE}" -eq 1 ]]; then
  echo "  [설치된 플러그인]"
  claude plugin list 2>/dev/null | sed 's/^/    /' || warn "claude plugin list 실패"
else
  warn "claude CLI 없어 plugin list 출력 skip"
fi

echo ""

echo "  [파일 존재 체크리스트]"
check_file() {
  local label="$1" path="$2"
  if [[ -f "${path}" ]]; then
    ok "  ${label}: ${path}"
  else
    warn "  ${label} 없음: ${path}"
  fi
}
check_file "HUD 런처         " "${HUD_LAUNCHER}"
check_file "claudenews config" "${CLAUDENEWS_CONFIG}"
check_file "coralline script " "${CORALLINE_SCRIPT}"

echo ""

if [[ -f "${SETTINGS_FILE}" ]]; then
  echo "  [settings.json statusLine 확인]"
  SETTINGS_FILE="${SETTINGS_FILE}" HUD_LAUNCHER="${HUD_LAUNCHER}" python3 - <<'PYEOF'
import json, sys, os

settings_path = os.environ["SETTINGS_FILE"]
hud_launcher = os.environ["HUD_LAUNCHER"]

try:
    with open(settings_path) as f:
        cfg = json.load(f)
except Exception as e:
    print(f"[WARN] settings.json 읽기 실패: {e}", file=sys.stderr)
    sys.exit(0)

sl = cfg.get("statusLine", {})
cmd = sl.get("command", "")
if ".claude/hud/claudenews-hud.mjs" in cmd:
    print(f"[OK]   statusLine.command → '{cmd}'")
else:
    print(f"[WARN] statusLine.command가 claudenews HUD 런처를 가리키지 않음: '{cmd}'")
    print(f'       권장: "node $HOME/.claude/hud/claudenews-hud.mjs"')
PYEOF
else
  warn "settings.json 없음 — statusLine 확인 skip"
fi

echo ""

if [[ -d "${HOME}/.claude/.git" ]]; then
  ln -sf "${HOME}/.claude/scripts/ci-gate-commit.sh" "${HOME}/.claude/.git/hooks/pre-commit"
  echo "  [OK]   git pre-commit hook → scripts/ci-gate-commit.sh (symlink)"
  ln -sf "${HOME}/.claude/scripts/ci-gate-commit-msg.sh" "${HOME}/.claude/.git/hooks/commit-msg"
  echo "  [OK]   git commit-msg hook → scripts/ci-gate-commit-msg.sh (symlink — feat: 커밋의 Intent 줄 검사, 2026-09-06)"
  chmod +x "${HOME}/.claude/scripts/ci-gate-post-commit.sh"   # NEVER: 이 chmod 를 빼지 않는다. git 은 실행 비트 없는 훅을 무시한다
  ln -sf "${HOME}/.claude/scripts/ci-gate-post-commit.sh" "${HOME}/.claude/.git/hooks/post-commit"
  echo "  [OK]   git post-commit hook → scripts/ci-gate-post-commit.sh (symlink — Candidate: 트레일러 커밋을 학습 후보 대장에 연결, 2026-10-17)"
else
  # shellcheck disable=SC2088
  warn "~/.claude가 git repo가 아님 — pre-commit hook 설치 skip"
fi

# WHY: 머신 로컬 의존물은 clone 으로 전파되지 않는다(2026-08-19 검수 발견으로 편입).
if command -v pdf-inspector >/dev/null 2>&1; then
  echo "  [OK]   pdf-inspector CLI 존재 ($(pdf-inspector --version 2>/dev/null | head -1))"
elif command -v npm >/dev/null 2>&1; then
  if ! { npm install -g @firecrawl/pdf-inspector >/dev/null 2>&1 \
    && echo "  [OK]   pdf-inspector CLI 설치 완료 (npm, paper-read PDF 폴백)"; }; then
    warn "pdf-inspector 설치 실패 — 수동: npm install -g @firecrawl/pdf-inspector"
  fi
else
  warn "npm 부재 — pdf-inspector 미설치 (paper-read PDF 폴백용, 수동: npm install -g @firecrawl/pdf-inspector)"
fi
if ! crontab -l 2>/dev/null | grep -q mem-watch.sh; then
  warn "mem-watch cron 미등록 (학습 서버라면 권장): crontab -e 후"
  echo "         * * * * * /usr/bin/bash \$HOME/.claude/tools/mem-guard/mem-watch.sh   (알림 주제는 env-config 의 USER_NTFY_TOPIC — 추적 파일에 쓰지 마십시오)"
else
  echo "  [OK]   mem-watch cron 등록됨"
fi

echo ""

echo "========================================================"
echo " 설정 완료"
echo "========================================================"
echo ""
echo " ※ Claude Code 재시작 필요."
echo "   뉴스 첫 fetch는 비동기라 시작 직후 잠깐 안 보일 수 있음 (고장 아님)."
echo ""
echo " ※ claude plugin 명령이 처음이면 인증(GitHub OAuth 등) 창이 뜰 수 있음."
echo "   그 경우 섹션 2를 건너뛰고 수동으로 다시 실행하세요:"
echo "     claude plugin marketplace add <owner/repo>"
echo "     claude plugin install <plugin@marketplace> --scope user"
echo ""
