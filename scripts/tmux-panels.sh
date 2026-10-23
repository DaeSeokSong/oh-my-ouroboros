#!/bin/bash
# ============================================================================
# tmux-panels.sh v2.1 — Teammate Panel Manager
# ============================================================================
# 배치 정책 (Layout Policy)
# ─────────────────────────────────────────────────────────────────
#  팀원 수  │  전략              │  메인 윈도우          │  오버플로우
# ─────────┼───────────────────┼─────────────────────┼───────────
#  1~4     │ 1행               │ Main(65%) + 1행(35%)│  없음
#  5~8     │ 2행               │ Main(55%) + 2행(45%)│  없음
#  9~12    │ 3행               │ Main(50%) + 3행(50%)│  없음
#  13~N    │ 3행 + overflow    │ Main + 최대 12명     │ [tm-1]...
# ─────────────────────────────────────────────────────────────────
# * overflow: 같은 세션 내 새 윈도우(탭). Ctrl+b n/p로 이동.
# * cleanup 시 overflow 윈도우도 함께 제거.
# ============================================================================
set -euo pipefail

MAX_PER_ROW=4
MAIN_MIN_HEIGHT=15
MIN_PANE_HEIGHT=4
OVERFLOW_PREFIX="tm"

# ============================================================================
# _place_row: 한 행에 N개 패널을 가로 균등 배치
#   인자: base_pane_id, row_height, "name1:role1" "name2:role2" ...
#   반환: 없음 (패널 생성 + 라벨 + 배너)
# ============================================================================
_place_row() {
    local base_pane="$1"
    local row_h="$2"
    shift 2
    local entries=("$@")
    local n=${#entries[@]}

    [ "$n" -eq 0 ] && return

    local total_w
    total_w=$(tmux display-message -p '#{window_width}')

    # 1) 수직 분할로 행 생성 — -P 플래그로 새 pane_id를 정확히 포착
    local first_pid
    first_pid=$(tmux split-window -v -l "$row_h" -t "$base_pane" \
        -P -F '#{pane_id}' "bash --norc --noprofile")

    local name="${entries[0]%%:*}"
    local role="${entries[0]#*:}"
    tmux select-pane -t "$first_pid" -T "$name [$role]"
    _show_banner "$first_pid" "$name" "$role"

    local pids=("$first_pid")

    # 2) 가로 분할로 나머지 패널 생성
    for (( i=1; i<n; i++ )); do
        local new_pid
        new_pid=$(tmux split-window -h -t "${pids[$((i-1))]}" \
            -P -F '#{pane_id}' "bash --norc --noprofile")

        name="${entries[$i]%%:*}"
        role="${entries[$i]#*:}"
        tmux select-pane -t "$new_pid" -T "$name [$role]"
        _show_banner "$new_pid" "$name" "$role"
        pids+=("$new_pid")
    done

    # 3) 폭 균등화
    local pane_w=$(( total_w / n ))
    for pid in "${pids[@]}"; do
        tmux resize-pane -t "$pid" -x "$pane_w" 2>/dev/null || true
    done
}

# ============================================================================
# _place_panes: 메인 윈도우에 N명 배치 (다행 지원)
#   인자: main_pane_id, "name1:role1" ...
# ============================================================================
_place_panes() {
    local base_pane="$1"
    shift
    local entries=("$@")
    local count=${#entries[@]}
    [ "$count" -eq 0 ] && return

    local total_h
    total_h=$(tmux display-message -p '#{window_height}')

    local rows=$(( (count + MAX_PER_ROW - 1) / MAX_PER_ROW ))

    # 하단 영역 비율
    local bottom_pct
    case $rows in
        1) bottom_pct=35 ;;
        2) bottom_pct=45 ;;
        *) bottom_pct=50 ;;
    esac
    local bottom_h=$(( total_h * bottom_pct / 100 ))
    local row_h=$(( bottom_h / rows ))
    [ "$row_h" -lt "$MIN_PANE_HEIGHT" ] && row_h=$MIN_PANE_HEIGHT

    local placed=0
    for (( r=0; r<rows; r++ )); do
        local in_row
        if [ $r -lt $(( rows - 1 )) ]; then
            in_row=$MAX_PER_ROW
        else
            in_row=$(( count - placed ))
            [ "$in_row" -gt "$MAX_PER_ROW" ] && in_row=$MAX_PER_ROW
        fi

        _place_row "$base_pane" "$row_h" "${entries[@]:$placed:$in_row}"
        placed=$(( placed + in_row ))
    done
}

# ============================================================================
# _place_overflow: 오버플로우 윈도우에 배치 (메인 패널 없음, 전체 높이 사용)
#   인자: window_name, "name1:role1" ...
# ============================================================================
_place_overflow() {
    local win_name="$1"
    shift
    local entries=("$@")
    local count=${#entries[@]}
    [ "$count" -eq 0 ] && return

    # 새 윈도우 생성
    tmux new-window -n "$win_name" "bash --norc --noprofile"
    tmux set-option -w pane-border-status top 2>/dev/null || true
    tmux set-option -w pane-border-format " #{pane_title} " 2>/dev/null || true

    # 첫 번째 패널은 new-window가 생성한 것
    local base_pid
    base_pid=$(tmux display-message -p '#{pane_id}')

    local name="${entries[0]%%:*}"
    local role="${entries[0]#*:}"
    tmux select-pane -t "$base_pid" -T "$name [$role]"
    _show_banner "$base_pid" "$name" "$role"

    if [ "$count" -eq 1 ]; then return; fi

    local total_h
    total_h=$(tmux display-message -p '#{window_height}')

    local rows=$(( (count + MAX_PER_ROW - 1) / MAX_PER_ROW ))
    local row_h=$(( total_h / rows ))
    [ "$row_h" -lt "$MIN_PANE_HEIGHT" ] && row_h=$MIN_PANE_HEIGHT

    # 첫 번째 행의 나머지 가로 분할
    local in_first_row=$MAX_PER_ROW
    [ "$count" -lt "$MAX_PER_ROW" ] && in_first_row=$count

    local total_w
    total_w=$(tmux display-message -p '#{window_width}')
    local pids=("$base_pid")

    for (( i=1; i<in_first_row; i++ )); do
        local new_pid
        new_pid=$(tmux split-window -h -t "${pids[$((i-1))]}" \
            -P -F '#{pane_id}' "bash --norc --noprofile")

        name="${entries[$i]%%:*}"
        role="${entries[$i]#*:}"
        tmux select-pane -t "$new_pid" -T "$name [$role]"
        _show_banner "$new_pid" "$name" "$role"
        pids+=("$new_pid")
    done

    # 첫 행 폭 균등화
    local pane_w=$(( total_w / in_first_row ))
    for pid in "${pids[@]}"; do
        tmux resize-pane -t "$pid" -x "$pane_w" 2>/dev/null || true
    done

    # 나머지 행
    local placed=$in_first_row
    for (( r=1; r<rows; r++ )); do
        local in_row=$MAX_PER_ROW
        local remaining=$(( count - placed ))
        [ "$remaining" -lt "$MAX_PER_ROW" ] && in_row=$remaining

        _place_row "$base_pid" "$row_h" "${entries[@]:$placed:$in_row}"
        placed=$(( placed + in_row ))
    done
}

# ============================================================================
# cleanup
# ============================================================================
# ----------------------------------------------------------------------------
# 파괴 전 자기 대상 확인 (2026-10-01 감사 — purge·cleanup 이 제목 규칙만으로 pane 을 지우고
# main 을 «창의 첫 pane» 으로 가정해, 첫 pane 이 아닌 곳에서 돌리면 자기 pane 을 죽였다)
#   · 자기 pane($TMUX_PANE)과 그 창은 절대 지우지 않는다.
#   · 지울 대상은 자동 생성 pane(✳ 제목)과, cleanup 에서만 setup 이 만든 "name [role]" pane.
#   · 학습 세션(프로젝트 .claude/train.env 의 TRAIN_TMUX_PREFIX 로 시작하는 세션·창)은 대상에서 뺀다.
#   · 지우기 전에 대상 목록을 먼저 출력한다.
# ----------------------------------------------------------------------------
_train_prefixes() {
    local d="$PWD"
    if [ -n "${CLAUDE_PROJECT_DIR:-}" ] && [ -f "$CLAUDE_PROJECT_DIR/.claude/train.env" ]; then
        sed -n 's/^TRAIN_TMUX_PREFIX=//p' "$CLAUDE_PROJECT_DIR/.claude/train.env" | tr -d "\"'"
    fi
    while :; do
        if [ -f "$d/.claude/train.env" ]; then
            sed -n 's/^TRAIN_TMUX_PREFIX=//p' "$d/.claude/train.env" | tr -d "\"'"
        fi
        [ "$d" = "/" ] && break
        d=$(dirname "$d")
    done
}

_is_train_name() {
    local n="$1" p
    [ -n "$n" ] || return 1
    for p in $(_train_prefixes); do
        [ -n "$p" ] && [[ "$n" == "$p"* ]] && return 0
    done
    return 1
}

_self_pane() { printf '%s' "${TMUX_PANE:-$(tmux list-panes -F '#{pane_id}' | head -1)}"; }

# 지울 pane 을 "pane_id<TAB>title" 줄로 낸다. $1 = purge | cleanup
# (제목이 비어도 필드가 밀리지 않게 제목을 마지막 필드로 둔다)
_pane_targets() {
    local mode="$1" self pid sess win title
    self=$(_self_pane)
    while IFS=$'\t' read -r pid sess win title; do
        [[ "$pid" == "$self" ]] && continue
        _is_train_name "$sess" && continue
        _is_train_name "$win" && continue
        if [[ "$title" =~ ^✳ ]]; then :
        elif [[ "$mode" == cleanup && "$title" =~ \[.*\] ]]; then :
        else continue; fi
        printf '%s\t%s\n' "$pid" "$title"
    done < <(tmux list-panes -F $'#{pane_id}\t#{session_name}\t#{window_name}\t#{pane_title}')
}

cmd_cleanup() {
    local self line idx wname sess n
    # 2026-10-01 P6 검수: tmux 밖($TMUX_PANE 없음)에서는 «내 pane» 을 알 수 없다 — 첫 pane 을 자기로 가정해 지우거나(set -e 로) exit 127 로 죽지 않고 안내 후 정상 종료한다.
    if [ -z "${TMUX_PANE:-}" ]; then
        echo "tmux 밖에서 실행됐습니다(TMUX_PANE 없음). 자기 pane 을 알 수 없어 아무것도 지우지 않습니다. tmux 창 안에서 다시 실행하십시오."
        return 0
    fi
    self=$(_self_pane)

    # 1) 오버플로우 윈도우 제거 (자기 pane 이 든 창·학습 세션 창 제외)
    local wins=()
    while IFS=$'\t' read -r idx sess wname; do
        [[ "$wname" == "${OVERFLOW_PREFIX}-"* ]] || continue
        _is_train_name "$sess" && continue
        _is_train_name "$wname" && continue
        tmux list-panes -t ":${idx}" -F '#{pane_id}' | grep -qx "$self" && continue
        wins+=("$idx")
    done < <(tmux list-windows -F $'#{window_index}\t#{session_name}\t#{window_name}')

    # 2) 자동 생성·setup 패널 제거 (자기 pane 제외)
    local targets=()
    while IFS= read -r line; do
        if [ -n "$line" ]; then targets+=("$line"); fi
    done < <(_pane_targets cleanup)

    echo "삭제 대상: 오버플로우 윈도우 ${#wins[@]}개, pane ${#targets[@]}개"
    for (( n=0; n<${#wins[@]}; n++ )); do echo "  - window :${wins[$n]}"; done
    for (( n=0; n<${#targets[@]}; n++ )); do
        line="${targets[$n]}"
        echo "  - pane ${line%%$'\t'*} [${line#*$'\t'}]"
    done

    for (( n=${#wins[@]}-1; n>=0; n-- )); do   # 큰 번호부터 지워 인덱스가 밀리지 않게
        tmux kill-window -t ":${wins[$n]}" 2>/dev/null || true
    done
    for (( n=0; n<${#targets[@]}; n++ )); do
        line="${targets[$n]}"
        tmux kill-pane -t "${line%%$'\t'*}" 2>/dev/null || true
    done

    tmux select-pane -t "$self"
    echo "✅ Cleanup complete."
}

# ============================================================================
# setup
# ============================================================================
cmd_setup() {
    local args=("$@")
    local count=${#args[@]}
    [ "$count" -eq 0 ] && { echo "❌ Usage: $0 setup 'n1:r1' 'n2:r2' ..."; return 1; }

    cmd_cleanup

    # 패널 테두리 활성화
    tmux set-option -w pane-border-status top 2>/dev/null || true
    tmux set-option -w pane-border-format " #{pane_title} " 2>/dev/null || true

    local main_id
    main_id=$(_self_pane)   # 창의 첫 pane 이 아니라 이 스크립트를 돌리는 pane 이 main
    tmux select-pane -t "$main_id" -T "Main (Team Lead)"

    local main_win_idx
    main_win_idx=$(tmux display-message -p '#{window_index}')

    # 수용량 계산
    local total_h
    total_h=$(tmux display-message -p '#{window_height}')
    local available_h=$(( total_h - MAIN_MIN_HEIGHT ))
    [ "$available_h" -lt "$MIN_PANE_HEIGHT" ] && available_h=$MIN_PANE_HEIGHT
    local max_rows=$(( available_h / MIN_PANE_HEIGHT ))
    [ "$max_rows" -gt 3 ] && max_rows=3
    [ "$max_rows" -lt 1 ] && max_rows=1
    local capacity=$(( max_rows * MAX_PER_ROW ))

    local in_main=$count
    [ "$in_main" -gt "$capacity" ] && in_main=$capacity
    local overflow_total=$(( count - in_main ))

    # 메인 윈도우 배치
    _place_panes "$main_id" "${args[@]:0:$in_main}"

    # 오버플로우 처리
    if [ "$overflow_total" -gt 0 ]; then
        # 오버플로우 윈도우 수용량 (메인 패널 없음 → 전체 높이 사용)
        local ov_max_rows=$(( total_h / MIN_PANE_HEIGHT ))
        [ "$ov_max_rows" -gt 6 ] && ov_max_rows=6
        [ "$ov_max_rows" -lt 1 ] && ov_max_rows=1
        local ov_cap=$(( ov_max_rows * MAX_PER_ROW ))
        [ "$ov_cap" -lt 4 ] && ov_cap=4

        local placed=$in_main
        local win_num=1
        while [ "$placed" -lt "$count" ]; do
            local batch=$ov_cap
            local remaining=$(( count - placed ))
            [ "$remaining" -lt "$batch" ] && batch=$remaining

            _place_overflow "${OVERFLOW_PREFIX}-${win_num}" "${args[@]:$placed:$batch}"
            placed=$(( placed + batch ))
            win_num=$(( win_num + 1 ))
        done

        tmux select-window -t ":${main_win_idx}"
    fi

    tmux select-pane -t "$main_id"

    if [ "$overflow_total" -gt 0 ]; then
        echo "✅ Setup: ${count} teammates — ${in_main} in main, ${overflow_total} in overflow (Ctrl+b n/p)."
    else
        local rows=$(( (in_main + MAX_PER_ROW - 1) / MAX_PER_ROW ))
        echo "✅ Setup: ${count} teammate(s), ${rows} row(s)."
    fi
}

# ============================================================================
# monitor: 특정 패널에서 출력 파일 모니터링
# ============================================================================
cmd_monitor() {
    local target_name="$1"
    local output_file="$2"

    local pane_id=""
    for win_idx in $(tmux list-windows -F '#{window_index}'); do
        local found
        found=$(tmux list-panes -t ":${win_idx}" -F '#{pane_id} #{pane_title}' \
            | grep "$target_name" | head -1 | awk '{print $1}' || true)
        if [ -n "$found" ]; then
            pane_id="$found"
            tmux select-window -t ":${win_idx}"
            break
        fi
    done

    [ -z "$pane_id" ] && { echo "❌ '$target_name' not found."; return 1; }

    tmux send-keys -t "$pane_id" C-c
    if [ -f "$output_file" ]; then
        tmux send-keys -t "$pane_id" "tail -f '$output_file'" Enter
    else
        tmux send-keys -t "$pane_id" \
            "echo 'Waiting: $output_file' && while [ ! -f '$output_file' ]; do sleep 1; done && tail -f '$output_file'" Enter
    fi
    echo "✅ Monitoring '$output_file' → '$target_name'."
}

# ============================================================================
# label / status
# ============================================================================
cmd_label() {
    tmux select-pane -t "$1" -T "$2"
    echo "✅ '$1' → '$2'"
}

cmd_status() {
    echo "╔════════════════════════════════════════════════════════╗"
    echo "║              tmux Panel Status (all windows)          ║"
    echo "╠════════════════════════════════════════════════════════╣"
    for win_idx in $(tmux list-windows -F '#{window_index}'); do
        local win_name
        win_name=$(tmux display-message -t ":${win_idx}" -p '#{window_name}')
        local is_active
        is_active=$(tmux list-windows -F '#{window_index} #{window_active}' \
            | grep "^${win_idx} " | awk '{print $2}')
        local marker=""
        [ "$is_active" = "1" ] && marker=" ◀"
        echo "║ ── Window ${win_idx}: ${win_name}${marker}"
        tmux list-panes -t ":${win_idx}" \
            -F '║    Pane #{pane_index} │ #{pane_width}x#{pane_height} │ #{pane_title}'
    done
    echo "╚════════════════════════════════════════════════════════╝"
}

_show_banner() {
    local pid="$1" name="$2" role="$3"
    # send-keys 문자열은 대상 셸이 그대로 해석한다. 작은따옴표로만 감싸면 name·role 안의 `'; …; #`
    # 로 임의 명령이 실행된다. printf %q 로 셸 인용을 붙여 넣는다(한글 role 도 그대로 통과한다).
    local q_name q_role
    q_name=$(printf '%q' "$name")
    q_role=$(printf '%q' "$role")
    tmux send-keys -t "$pid" \
        "clear && printf '\\n  \\033[1;36m%s\\033[0m\\n  Role: %s\\n  Status: Waiting...\\n' $q_name $q_role" Enter
}

# ============================================================================
# purge: Task 도구가 자동 생성한 불필요 pane만 선별 제거
#   - Main pane($TMUX_PANE) 보존
#   - setup으로 생성한 패널 ("name [role]" 형식 타이틀) 보존
#   - "✳" 접두사 등 Claude Code 자동 생성 pane만 제거 (그 밖의 pane 은 지우지 않는다)
#   - 학습 세션(train.env 접두) 보존, 지우기 전에 대상 목록 출력
# ============================================================================
cmd_purge() {
    local line n killed=0
    local targets=()
    while IFS= read -r line; do
        if [ -n "$line" ]; then targets+=("$line"); fi
    done < <(_pane_targets purge)

    echo "삭제 대상: pane ${#targets[@]}개"
    for (( n=0; n<${#targets[@]}; n++ )); do
        line="${targets[$n]}"
        echo "  - pane ${line%%$'\t'*} [${line#*$'\t'}]"
    done

    for (( n=0; n<${#targets[@]}; n++ )); do
        line="${targets[$n]}"
        tmux kill-pane -t "${line%%$'\t'*}" 2>/dev/null && killed=$((killed + 1))
    done

    if [ "$killed" -gt 0 ]; then
        echo "✅ Purged $killed extra pane(s). Setup panels preserved."
    else
        echo "✅ No extra panes found."
    fi
}

# ============================================================================
# Dispatcher
# ============================================================================
case "${1:-help}" in
    cleanup)  cmd_cleanup ;;
    setup)    shift; cmd_setup "$@" ;;
    purge)    cmd_purge ;;
    monitor)  shift; cmd_monitor "$@" ;;
    label)    shift; cmd_label "$@" ;;
    status)   cmd_status ;;
    *)
        cat << 'USAGE'
tmux-panels.sh v2.2 — Teammate Panel Manager

  cleanup                              Remove all panels + overflow windows
  setup "n1:r1" "n2:r2" ...           Create panels (auto-layout)
  purge                                Remove only auto-created extra panes
  monitor "name" <file>               Tail file in teammate's panel
  label "pane_id" "title"             Change panel title
  status                              Show layout (all windows)

Policy:  1~4→1row  5~8→2rows  9~12→3rows  13+→overflow windows

⚠️  Correct order: spawn teammates → purge → setup → monitor
    (NEVER: setup → spawn — this destroys panel layout!)
USAGE
        ;;
esac
