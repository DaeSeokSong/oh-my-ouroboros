#!/usr/bin/env bash
# claude-cli-stale-check.sh: PATH 의 claude 판이 설치된 최신 판보다 낮으면 경보 한 줄을 출력한다.
# 부르는 곳: SessionStart(harness-usage-check.sh).
#
# 판정 규칙:
#   PATH 판: `command -v claude`(또는 CLAUDE_BIN) → readlink -f. 해석 경로가 */versions/<X.Y.Z> 면 그 X.Y.Z,
#            아니면 실행 파일 폴더부터 위로 최대 3단계에서 package.json 의 "version" 을 읽는다.
#   설치 최신: ${CLAUDE_VERSIONS_DIR:-$HOME/.local/share/claude/versions} 안의 X.Y.Z 이름 중 sort -V 최댓값.
#   PATH 판 < 최신 판이면 한 줄 출력, 같거나 높으면 조용. 하나라도 못 구하면 조용히 exit 0(다른 서버 대비).
#   systemd 판: `systemctl --user show-environment` 의 PATH= 에서 찾은 claude 를 같은 방식으로 점검.
#            세션 PATH 쪽과 같은 실행 파일이면 한 줄만 낸다.
#
# 함수 분리 근거: ontology-refresh.sh 가 이 파일을 source 해 claude_pick_newest 를 쓴다.
#   판 구하기 로직이 두 벌이면 한쪽만 고쳐져 어긋나므로 한 파일에 둔다(직접 실행일 때만 claude_main 이 돈다).
#   claude_pick_newest: $HOME/.npm-global/bin/claude 와 versions 최고판 중 판이 높은 쪽(동률은 npm)을
#   "<경로>\t<판>" 으로 출력한다. 둘 다 없으면 rc 1(호출자가 기존 폴백).
#
# 제약: claude 를 실행하지 않는다(`claude --version`·`daemon status` 는 임시 데몬을 띄울 수 있음). 파일만 읽고
#   bash·coreutils 만 쓴다(python·node·jq 금지, SessionStart 경로). systemctl 은 `--user show-environment` 만.
# 시험용 덮어쓰기: CLAUDE_BIN, CLAUDE_VERSIONS_DIR, CLAUDE_SYSTEMD_PATH(빈 값이면 systemd 점검 생략).
# REF: knowledge/harness/code-history/scripts__claude-cli-stale-check.sh.md

VER_RE='^[0-9]+\.[0-9]+\.[0-9]+$'

claude_bin_version() {
    local real base d v="" _
    real=$(readlink -f -- "$1" 2>/dev/null) || return 1
    [ -e "$real" ] || return 1
    base=$(basename -- "$real")
    if [[ "$base" =~ $VER_RE && "$(basename -- "$(dirname -- "$real")")" == "versions" ]]; then
        v="$base"
    else
        d=$(dirname -- "$real")
        for _ in 1 2 3; do
            if [ -f "$d/package.json" ]; then
                v=$(grep -m1 -E '"version"[[:space:]]*:' "$d/package.json" 2>/dev/null \
                    | sed -E 's/.*"version"[[:space:]]*:[[:space:]]*"([^"]*)".*/\1/')
                break
            fi
            d=$(dirname -- "$d")
        done
    fi
    [[ "$v" =~ $VER_RE ]] || return 1
    printf '%s\t%s\n' "$v" "$real"
}

claude_latest_installed() {
    local vdir="${CLAUDE_VERSIONS_DIR:-$HOME/.local/share/claude/versions}" f n latest
    [ -d "$vdir" ] || return 1
    latest=$(for f in "$vdir"/*; do n=$(basename -- "$f"); [[ "$n" =~ $VER_RE ]] && echo "$n"; done | sort -V | tail -1)
    [[ "$latest" =~ $VER_RE ]] || return 1
    echo "$latest"
}

claude_pick_newest() {
    local npm_bin="$HOME/.npm-global/bin/claude" vdir="${CLAUDE_VERSIONS_DIR:-$HOME/.local/share/claude/versions}"
    local npm_ver="" vers_ver="" out
    if [ -x "$npm_bin" ] && out=$(claude_bin_version "$npm_bin"); then npm_ver="${out%%$'\t'*}"; fi
    if vers_ver=$(claude_latest_installed) && [ -x "$vdir/$vers_ver" ]; then :; else vers_ver=""; fi
    if [ -n "$npm_ver" ] && { [ -z "$vers_ver" ] || [ "$(printf '%s\n%s\n' "$npm_ver" "$vers_ver" | sort -V | tail -1)" = "$npm_ver" ]; }; then
        printf '%s\t%s\n' "$npm_bin" "$npm_ver"
    elif [ -n "$vers_ver" ]; then
        printf '%s\t%s\n' "$vdir/$vers_ver" "$vers_ver"
    else
        return 1
    fi
}

claude_systemd_bin() {
    local p d
    if [ -n "${CLAUDE_SYSTEMD_PATH+x}" ]; then
        p="$CLAUDE_SYSTEMD_PATH"
    else
        command -v systemctl >/dev/null 2>&1 || return 1
        p=$(timeout 1 systemctl --user show-environment 2>/dev/null | sed -n 's/^PATH=//p' | head -1)
    fi
    [ -n "$p" ] || return 1
    local IFS=:
    for d in $p; do
        [ -n "$d" ] && [ -x "$d/claude" ] && [ ! -d "$d/claude" ] && { echo "$d/claude"; return 0; }
    done
    return 1
}

claude_main() {
    local latest sess_real="" sys_bin out v real
    latest=$(claude_latest_installed) || return 0

    local bin="${CLAUDE_BIN:-$(command -v claude 2>/dev/null)}"
    if [ -n "$bin" ] && out=$(claude_bin_version "$bin"); then
        v="${out%%$'\t'*}"; real="${out#*$'\t'}"; sess_real="$real"
        if [ "$v" != "$latest" ] && [ "$(printf '%s\n%s\n' "$v" "$latest" | sort -V | head -1)" = "$v" ]; then
            echo "CLAUDE_CLI_STALE: PATH 의 claude ${v}(${real}) < 설치판 ${latest} → 임시 데몬·새 세션이 낡은 판으로 떠 상태창·최신 모델이 사라질 수 있음. 사용자 확인 뒤 claude update (메모리 host-B-claude-daemon-stale-npm-binary-1113)"
        fi
    fi

    sys_bin=$(claude_systemd_bin) || return 0
    out=$(claude_bin_version "$sys_bin") || return 0
    v="${out%%$'\t'*}"; real="${out#*$'\t'}"
    [ "$real" = "$sess_real" ] && return 0
    if [ "$v" != "$latest" ] && [ "$(printf '%s\n%s\n' "$v" "$latest" | sort -V | head -1)" = "$v" ]; then
        echo "CLAUDE_CLI_STALE: systemd PATH 의 claude ${v}(${real}) < 설치판 ${latest} → systemd 작업이 낡은 판을 집을 수 있음. 지우려면 사용자 확인 뒤 sudo npm uninstall -g @anthropic-ai/claude-code"
    fi
    return 0
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    claude_main
    exit 0
fi
