#!/bin/bash
# =============================================================
# Claude Code Environment Bootstrap Script
# ~/.claude 저장소를 새 서버에 복원하고 MCP 서버를 재설치한다.
#
# Usage:
#   bash bootstrap.sh
#   bash bootstrap.sh --https           # HTTPS 방식으로 클론 (SSH 키 없을 때)
#   bash bootstrap.sh --skip-mcp        # MCP 설치 건너뜀
#   bash bootstrap.sh --skip-plugins    # 플러그인 안내 건너뜀
#
# Idempotent: 여러 번 실행해도 안전하다.
# =============================================================

set -euo pipefail

# ── 색상 출력 ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'  # No Color

log_info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
log_ok()      { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $*"; }
log_step()    { echo -e "\n${CYAN}══════════════════════════════════════════════${NC}"; \
                echo -e "${CYAN}  STEP: $*${NC}"; \
                echo -e "${CYAN}══════════════════════════════════════════════${NC}"; }

# ── 인자 파싱 ──
SKIP_MCP=false
SKIP_PLUGINS=false
USE_HTTPS=false
for arg in "$@"; do
    case "$arg" in
        --skip-mcp)     SKIP_MCP=true ;;
        --skip-plugins) SKIP_PLUGINS=true ;;
        --https)        USE_HTTPS=true ;;
        --help|-h)
            echo "Usage: bash bootstrap.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --https           HTTPS 방식으로 클론 (SSH 키 없을 때)"
            echo "  --skip-mcp        MCP 설치 건너뜀"
            echo "  --skip-plugins    플러그인 안내 건너뜀"
            exit 0 ;;
        *)
            log_warn "Unknown argument: $arg (ignored)" ;;
    esac
done

# ── 상수 ──
REPO_SSH="git@github.com:DaeSeokSong/.claude.git"
REPO_HTTPS="https://github.com/DaeSeokSong/.claude.git"
CLAUDE_DIR="$HOME/.claude"
FAILED_STEPS=()

# ── 실패 추적 래퍼 ──
step_failed() {
    local step="$1"
    log_error "FAILED: $step"
    FAILED_STEPS+=("$step")
}

# =============================================================
# STEP 0: MCP 연결 사전 확인
# =============================================================
log_step "0/6  MCP 연결 사전 확인"

echo ""
echo -e "${CYAN}  📄 문서 자동화 MCP 추천${NC}"
echo "  ┌──────────────────────────────────────────────────────────┐"
echo "  │  Atlassian (Confluence/Jira) — 기술 문서·이슈 관리 자동화  │"
echo "  │  Notion                      — 팀 위키·노트 자동화          │"
echo "  │  두 MCP를 함께 사용하면 연구·개발 문서 파이프라인을         │"
echo "  │  Claude Code와 직접 연결할 수 있어 강력히 추천합니다.       │"
echo "  └──────────────────────────────────────────────────────────┘"
echo ""
log_info "지금 연결할 MCP를 선택하세요 (쉼표로 복수 선택 가능):"
echo "  1) Atlassian (Confluence + Jira)"
echo "  2) Notion"
echo "  3) 기타 MCP 직접 입력"
echo "  0) 건너뜀 (나중에 수동 설치)"
echo ""
echo -n "  선택 [예: 1,2 또는 1,2,3 또는 0]: "
read -r MCP_CHOICE </dev/tty || MCP_CHOICE="0"
echo ""

SETUP_ATLASSIAN=false
SETUP_NOTION=false
SETUP_OTHER=false
if [[ "$MCP_CHOICE" == *"1"* ]]; then SETUP_ATLASSIAN=true; fi
if [[ "$MCP_CHOICE" == *"2"* ]]; then SETUP_NOTION=true; fi
if [[ "$MCP_CHOICE" == *"3"* ]]; then SETUP_OTHER=true; fi

if $SETUP_ATLASSIAN; then log_ok "Atlassian MCP 설치 예약됨 (STEP 4에서 설치)"; fi
if $SETUP_NOTION;    then log_ok "Notion MCP 설치 예약됨 (STEP 4에서 설치)"; fi
if $SETUP_OTHER;     then log_ok "기타 MCP 설치 예약됨 (STEP 4에서 설치)"; fi
if ! $SETUP_ATLASSIAN && ! $SETUP_NOTION && ! $SETUP_OTHER; then
    log_info "MCP 연결 건너뜀. 나중에 설치하려면 INSTALL.md 참고."
fi

# ── 프로젝트 환경 설정 ──
echo ""
log_info "프로젝트 환경 설정:"
echo ""
echo -n "  생물학적 타당성 검토가 필요한 프로젝트인가요? (y/N): "
read -r BIO_CHOICE </dev/tty || BIO_CHOICE="n"
if [[ "$BIO_CHOICE" =~ ^[Yy]$ ]]; then
    BIO_PLAUSIBILITY=true
    log_ok "생물학적 타당성 검토 활성화"
else
    BIO_PLAUSIBILITY=false
    log_ok "생물학적 타당성 검토 비활성화"
fi

echo ""
echo -e "${CYAN}  🤖 기본 모델 선택${NC}"
echo "  ┌──────────────────────────────────────────────────────────┐"
echo "  │  1) Sonnet (기본값) — 빠르고 토큰 효율적, 대부분 작업에 적합  │"
echo "  │  2) Opus            — 수식·아키텍처·복합 추론에 최적          │"
echo "  └──────────────────────────────────────────────────────────┘"
echo ""
echo -n "  기본 모델 선택 [1/2, 기본값: 1]: "
read -r MODEL_CHOICE </dev/tty || MODEL_CHOICE="1"
if [[ "$MODEL_CHOICE" == "2" ]]; then
    DEFAULT_MODEL="opus"
    log_ok "기본 모델: Opus (opus)"
else
    DEFAULT_MODEL="sonnet"
    log_ok "기본 모델: Sonnet (sonnet)"
fi

# ── env-config 저장 ──
ENV_CONFIG="$CLAUDE_DIR/env-config"
log_info "환경 설정 저장: $ENV_CONFIG"
cat > "$ENV_CONFIG" <<ENVEOF
# Claude Code 환경 설정 (bootstrap.sh가 자동 생성)
CONFLUENCE_MCP=$( $SETUP_ATLASSIAN && echo "true" || echo "false" )
BIO_PLAUSIBILITY=$BIO_PLAUSIBILITY
DEFAULT_MODEL=$DEFAULT_MODEL
ENVEOF
log_ok "env-config 저장 완료"

# ── model pin 반영 (2026-07-15 개정 — GPT P1-6): 추적 settings.json에는 model 키를 두지
# 않는다(머신별 사용자 영역, 과거 2회 의도 제거 이력). 선택값은 gitignored settings.local.json에
# 기록. 주의: ~/.claude/settings.local.json의 전역 인식은 공식 문서에 명시돼 있지 않으므로,
# 새 세션에서 /status로 적용 여부를 확인하고 미적용이면 셸에 ANTHROPIC_MODEL export를 권장.
LOCAL_SETTINGS="$CLAUDE_DIR/settings.local.json"
if command -v jq >/dev/null 2>&1 && [ -f "$LOCAL_SETTINGS" ]; then
    TMP_LS=$(mktemp)
    jq --arg m "$DEFAULT_MODEL" '.model = $m' "$LOCAL_SETTINGS" > "$TMP_LS" && mv "$TMP_LS" "$LOCAL_SETTINGS"
    log_ok "settings.local.json model → $DEFAULT_MODEL (gitignored 로컬 pin)"
else
    printf '{\n  "model": "%s"\n}\n' "$DEFAULT_MODEL" > "$LOCAL_SETTINGS"
    log_ok "settings.local.json 생성 — model=$DEFAULT_MODEL (gitignored 로컬 pin)"
fi
log_info "적용 검증: 새 세션에서 /status 확인 — 미적용 시 셸에 export ANTHROPIC_MODEL=$DEFAULT_MODEL 추가"

# =============================================================
# STEP 1: 사전 요구사항 확인
# =============================================================
log_step "1/6  사전 요구사항 확인"

check_cmd() {
    local cmd="$1"
    local install_hint="${2:-}"
    if command -v "$cmd" &>/dev/null; then
        log_ok "$cmd 설치 확인됨 ($(command -v "$cmd"))"
    else
        if [ -n "$install_hint" ]; then
            log_error "$cmd 없음 → 설치 필요: $install_hint"
        else
            log_error "$cmd 없음"
        fi
        step_failed "prerequisite:$cmd"
    fi
}

check_cmd git    "sudo apt install git"
check_cmd curl   "sudo apt install curl"
check_cmd node   "sudo apt install nodejs  OR  nvm install --lts"
check_cmd npm    "sudo apt install npm     OR  nvm install --lts"
check_cmd npx    "(npm과 함께 설치됨)"
check_cmd uvx    "curl -Ls https://astral.sh/uv/install.sh | sh  (uv 설치)"
check_cmd claude "https://docs.anthropic.com/ko/docs/claude-code 참고"

if [ ${#FAILED_STEPS[@]} -gt 0 ]; then
    log_error "사전 요구사항 누락으로 진행 불가. 위 패키지를 먼저 설치하세요."
    exit 1
fi
log_ok "모든 사전 요구사항 충족"

# =============================================================
# STEP 2: ~/.claude 저장소 클론 또는 업데이트
# =============================================================
log_step "2/6  ~/.claude 저장소 동기화"

clone_repo() {
    local url="$1"
    local label="$2"
    log_info "git clone ($label): $url"
    if git clone "$url" "$CLAUDE_DIR" 2>&1; then
        log_ok "~/.claude 클론 완료 ($label)"
        return 0
    else
        return 1
    fi
}

if [ -d "$CLAUDE_DIR/.git" ]; then
    log_info "~/.claude 이미 git 저장소로 존재 → git pull"
    if git -C "$CLAUDE_DIR" pull --ff-only 2>&1; then
        log_ok "~/.claude git pull 완료"
    else
        log_warn "git pull 실패 (로컬 변경사항 충돌 가능). 현재 파일을 유지합니다."
        step_failed "git-pull"
    fi
elif [ -d "$CLAUDE_DIR" ]; then
    log_warn "~/.claude 존재하지만 git 저장소가 아님"
    log_info "기존 디렉토리를 ~/.claude.bak 으로 백업 후 클론합니다."
    BACKUP_DIR="${CLAUDE_DIR}.bak.$(date +%Y%m%d_%H%M%S)"
    mv "$CLAUDE_DIR" "$BACKUP_DIR"
    log_ok "백업 완료: $BACKUP_DIR"

    if $USE_HTTPS; then
        clone_repo "$REPO_HTTPS" "HTTPS" || { step_failed "git-clone"; exit 1; }
    else
        if ! clone_repo "$REPO_SSH" "SSH"; then
            log_warn "SSH 클론 실패 → HTTPS 방식으로 재시도합니다."
            clone_repo "$REPO_HTTPS" "HTTPS" || { step_failed "git-clone"; exit 1; }
        fi
    fi
else
    log_info "~/.claude 없음 → git clone"
    if $USE_HTTPS; then
        clone_repo "$REPO_HTTPS" "HTTPS" || { step_failed "git-clone"; exit 1; }
    else
        if ! clone_repo "$REPO_SSH" "SSH"; then
            log_warn "SSH 클론 실패 → HTTPS 방식으로 재시도합니다."
            log_info "SSH 키를 나중에 설정하려면: ssh-keygen -t ed25519 && cat ~/.ssh/id_ed25519.pub"
            clone_repo "$REPO_HTTPS" "HTTPS" || { step_failed "git-clone"; exit 1; }
        fi
    fi
fi

# 스크립트 실행 권한 복원
chmod +x "$CLAUDE_DIR/scripts/"*.sh 2>/dev/null && log_ok "scripts/*.sh 실행 권한 설정 완료"

# =============================================================
# STEP 3: 디렉토리 구조 초기화 (.gitignore 제외 항목)
# =============================================================
log_step "3/6  디렉토리 구조 초기화"

# projects/ 는 .gitignore에 있어 git pull 시 생성되지 않음
# Claude Code가 사용하는 메모리 디렉토리를 미리 생성
if [ ! -d "$CLAUDE_DIR/projects" ]; then
    mkdir -p "$CLAUDE_DIR/projects"
    log_ok "projects/ 디렉토리 생성 완료 (Claude Code 메모리용)"
else
    log_ok "projects/ 디렉토리 이미 존재"
fi

# long-term 메모리 디렉토리 안내
log_warn "long-term 메모리 경로를 확인하세요."
log_info "  memory-write.md에 설정된 경로: /data/\$(whoami)/.claude/long-term/"
log_info "  해당 경로가 없으면: mkdir -p /data/\$(whoami)/.claude/long-term/"
log_info "  또는 memory-write.md의 경로를 현재 서버에 맞게 수정하세요."

# =============================================================
# STEP 4: MCP 서버 설치
# =============================================================
log_step "4/6  MCP 서버 설치"

if $SKIP_MCP; then
    log_warn "--skip-mcp 옵션 감지 → MCP 설치 건너뜀"
else

    # ── MCP 이미 등록 여부 확인 헬퍼 ──
    mcp_exists() {
        local name="$1"
        claude mcp list 2>/dev/null | grep -q "^$name " || \
        claude mcp list 2>/dev/null | grep -q "^$name$"
    }

    # ── 4-1: context7 ──
    log_info "context7 MCP 설치 확인 중..."
    if mcp_exists "context7"; then
        log_ok "context7 이미 등록됨 → 건너뜀"
    else
        log_info "context7 설치: npx -y @upstash/context7-mcp@latest"
        if claude mcp add context7 -- npx -y @upstash/context7-mcp@latest 2>&1; then
            log_ok "context7 설치 완료"
        else
            log_warn "context7 설치 실패 (나중에 수동 설치 가능)"
            step_failed "mcp:context7"
        fi
    fi

    # ── 4-2: sentry (HTTP transport) ──
    log_info "sentry MCP 설치 확인 중..."
    if mcp_exists "sentry"; then
        log_ok "sentry 이미 등록됨 → 건너뜀"
    else
        log_info "sentry 설치: HTTP transport"
        if claude mcp add --transport http sentry https://mcp.sentry.dev/mcp 2>&1; then
            log_ok "sentry 설치 완료"
        else
            log_warn "sentry 설치 실패 (나중에 수동 설치 가능)"
            step_failed "mcp:sentry"
        fi
    fi

    # ── 4-3: playwright (headless) ──
    log_info "playwright MCP 설치 확인 중..."
    if mcp_exists "playwright"; then
        log_ok "playwright 이미 등록됨 → 건너뜀"
    else
        log_info "playwright 설치: npx -y @playwright/mcp@latest --headless"
        if claude mcp add playwright npx -- -y @playwright/mcp@latest --headless 2>&1; then
            log_ok "playwright 설치 완료"
        else
            log_warn "playwright 설치 실패 (나중에 수동 설치 가능)"
            step_failed "mcp:playwright"
        fi
    fi

    # ── 4-4: Atlassian / confluence (STEP 0에서 선택한 경우) ──
    log_info "confluence MCP 설치 확인 중..."
    if mcp_exists "confluence"; then
        log_ok "confluence 이미 등록됨 → 건너뜀"
    elif $SETUP_ATLASSIAN; then
        echo ""
        log_info "Atlassian API 토큰 발급: https://id.atlassian.com/manage-profile/security/api-tokens"
        echo -n "  CONFLUENCE_URL (예: https://yourco.atlassian.net/wiki): "
        read -r CONFLUENCE_URL </dev/tty
        echo -n "  CONFLUENCE_USERNAME (이메일): "
        read -r CONFLUENCE_USERNAME </dev/tty
        echo -n "  CONFLUENCE_API_TOKEN: "
        read -rs CONFLUENCE_API_TOKEN </dev/tty
        echo ""
        echo -n "  JIRA_URL (예: https://yourco.atlassian.net): "
        read -r JIRA_URL </dev/tty
        echo -n "  JIRA_USERNAME (이메일, 보통 위와 동일): "
        read -r JIRA_USERNAME </dev/tty
        echo -n "  JIRA_API_TOKEN (보통 위와 동일): "
        read -rs JIRA_API_TOKEN </dev/tty
        echo ""

        log_info "confluence MCP 등록 중..."
        if claude mcp add confluence \
            --env CONFLUENCE_URL="$CONFLUENCE_URL" \
            --env CONFLUENCE_USERNAME="$CONFLUENCE_USERNAME" \
            --env CONFLUENCE_API_TOKEN="$CONFLUENCE_API_TOKEN" \
            --env JIRA_URL="$JIRA_URL" \
            --env JIRA_USERNAME="$JIRA_USERNAME" \
            --env JIRA_API_TOKEN="$JIRA_API_TOKEN" \
            -- uvx mcp-atlassian 2>&1; then
            log_ok "confluence MCP 설치 완료"
        else
            log_warn "confluence MCP 설치 실패. 수동으로 다시 시도하세요 (INSTALL.md 참고)"
            step_failed "mcp:confluence"
        fi
    else
        log_info "Atlassian MCP 건너뜀. 나중에 설치하려면 INSTALL.md 참고."
    fi

    # ── 4-5: Notion (STEP 0에서 선택한 경우) ──
    log_info "notion MCP 설치 확인 중..."
    if mcp_exists "notion"; then
        log_ok "notion 이미 등록됨 → 건너뜀"
    elif $SETUP_NOTION; then
        echo ""
        log_info "Notion API 키 발급: https://www.notion.so/profile/integrations"
        echo -n "  NOTION_API_KEY: "
        read -rs NOTION_API_KEY </dev/tty
        echo ""

        log_info "notion MCP 등록 중..."
        if claude mcp add notion \
            --env NOTION_API_KEY="$NOTION_API_KEY" \
            -- npx -y @notionhq/notion-mcp-server 2>&1; then
            log_ok "notion MCP 설치 완료"
        else
            log_warn "notion MCP 설치 실패. 수동으로 다시 시도하세요 (INSTALL.md 참고)"
            step_failed "mcp:notion"
        fi
    else
        log_info "Notion MCP 건너뜀. 나중에 설치하려면 INSTALL.md 참고."
    fi

    # ── 4-6: 기타 MCP (STEP 0에서 선택한 경우) ──
    if $SETUP_OTHER; then
        echo ""
        log_info "기타 MCP를 직접 입력합니다. 여러 개 추가 가능 (빈 줄 입력 시 종료)."
        while true; do
            echo ""
            echo -n "  MCP 이름 (예: github) [빈 줄 입력 시 종료]: "
            read -r OTHER_MCP_NAME </dev/tty || break
            [[ -z "$OTHER_MCP_NAME" ]] && break

            echo -n "  설치 명령 (예: npx -y @modelcontextprotocol/server-github): "
            read -r OTHER_MCP_CMD </dev/tty || break
            [[ -z "$OTHER_MCP_CMD" ]] && break

            echo -n "  환경변수 (예: GITHUB_TOKEN=xxx, 없으면 빈 줄): "
            read -r OTHER_MCP_ENV </dev/tty || OTHER_MCP_ENV=""

            if mcp_exists "$OTHER_MCP_NAME"; then
                log_ok "$OTHER_MCP_NAME 이미 등록됨 → 건너뜀"
                continue
            fi

            log_info "$OTHER_MCP_NAME MCP 등록 중..."
            if [[ -n "$OTHER_MCP_ENV" ]]; then
                # 환경변수 파싱: KEY=VALUE 형식을 --env KEY=VALUE 로 변환
                ENV_ARGS=()
                IFS=',' read -ra ENV_PAIRS <<< "$OTHER_MCP_ENV"
                for pair in "${ENV_PAIRS[@]}"; do
                    pair=$(echo "$pair" | xargs)  # trim whitespace
                    [[ -n "$pair" ]] && ENV_ARGS+=(--env "$pair")
                done
                if claude mcp add "$OTHER_MCP_NAME" "${ENV_ARGS[@]}" -- $OTHER_MCP_CMD 2>&1; then
                    log_ok "$OTHER_MCP_NAME MCP 설치 완료"
                else
                    log_warn "$OTHER_MCP_NAME MCP 설치 실패 (나중에 수동 설치 가능)"
                    step_failed "mcp:$OTHER_MCP_NAME"
                fi
            else
                if claude mcp add "$OTHER_MCP_NAME" -- $OTHER_MCP_CMD 2>&1; then
                    log_ok "$OTHER_MCP_NAME MCP 설치 완료"
                else
                    log_warn "$OTHER_MCP_NAME MCP 설치 실패 (나중에 수동 설치 가능)"
                    step_failed "mcp:$OTHER_MCP_NAME"
                fi
            fi
        done
        log_info "기타 MCP 입력 완료."
    fi

fi  # end SKIP_MCP

# =============================================================
# STEP 5: Claude Code 플러그인 확인 및 ntfy 안내
# =============================================================
log_step "5/6  플러그인 확인 및 ntfy 안내"

if ! $SKIP_PLUGINS; then
    log_info "settings.json에 등록된 플러그인 7개 (git 복원 후 Claude Code 첫 실행 시 자동 활성화):"
    echo "  1. example-skills@anthropic-agent-skills"
    echo "  2. superpowers@superpowers-marketplace"
    echo "  3. ralph-loop@claude-plugins-official"
    echo "  4. code-simplifier@claude-plugins-official"
    echo "  5. claude-md-management@claude-plugins-official"
    echo "  6. claudenews@claudenews"
    echo "  7. codex@openai-codex"
fi

NOTIFY_SCRIPT="$CLAUDE_DIR/scripts/claude-notify.sh"
if [ -f "$NOTIFY_SCRIPT" ]; then
    CURRENT_TOPIC=$(grep -m1 'NTFY_TOPIC=' "$NOTIFY_SCRIPT" | cut -d'"' -f2 2>/dev/null || echo "")
    if [ -n "$CURRENT_TOPIC" ] && [ "$CURRENT_TOPIC" != "your-topic-name" ]; then
        log_ok "ntfy NTFY_TOPIC: $CURRENT_TOPIC"
        log_info "다른 topic 사용 시: sed -i 's/NTFY_TOPIC=\".*\"/NTFY_TOPIC=\"<new-topic>\"/' $NOTIFY_SCRIPT"
    else
        log_warn "NTFY_TOPIC 미설정. 알림을 받으려면:"
        echo "  sed -i 's/NTFY_TOPIC=\".*\"/NTFY_TOPIC=\"<your-unique-topic>\"/' $NOTIFY_SCRIPT"
    fi
fi

# =============================================================
# 최종 결과 요약
# =============================================================
echo ""
echo -e "${CYAN}══════════════════════════════════════════════${NC}"
echo -e "${CYAN}  Bootstrap 완료 요약${NC}"
echo -e "${CYAN}══════════════════════════════════════════════${NC}"

if [ ${#FAILED_STEPS[@]} -eq 0 ]; then
    log_ok "모든 단계 성공적으로 완료!"
else
    log_warn "아래 항목은 수동 조치가 필요합니다:"
    for s in "${FAILED_STEPS[@]}"; do
        echo -e "  ${RED}✗${NC}  $s"
    done
fi

echo ""
echo "다음 단계:"
echo "  1. 새 터미널을 열거나 'source ~/.bashrc' 실행"
echo "  2. 'claude mcp list' 로 MCP 서버 등록 확인"
echo "  3. 'claude' 로 Claude Code 실행"
echo ""
