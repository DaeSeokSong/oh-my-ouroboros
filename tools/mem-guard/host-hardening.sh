#!/usr/bin/env bash
# shellcheck disable=SC2329  # 항목 함수는 "${it}_${MODE}" 로 이름을 조립해 부른다
# host-hardening.sh — 서버 전체 멈춤(2026-11-09 23:04 · 11-10 05:14) 후속 시스템 설정 묶음(같은 폴더의 옛 이름 파일은 이 파일을 부르는 연결)
# 경위: 비공개 지식 노트(2026-11-10 서버 멈춤) · 서버 값: config/hosts/<hostname>.json 의 hardening.*(파일이 없으면 멈춘다)
#
# 사용 (기본은 점검만 하고 아무것도 바꾸지 않는다):
#   bash host-hardening.sh                      # 점검: 지금 값과 적용하면 바뀔 값을 보여 준다
#   sudo bash host-hardening.sh --apply all     # swap 을 뺀 전부 적용(swap 은 이름을 적어야 적용된다)
#   sudo bash host-hardening.sh --apply kernlog,hungtask   # 고른 항목만 적용
#   sudo bash host-hardening.sh --revert watchdog          # 고른 항목 되돌리기(all = swap 을 뺀 전부)
#   옵션: --user <이름>(kernlog · sesscap 대상, 기본 SUDO_USER) · --reserve-gb <N>(slicecap 이 시스템 몫으로 남길 양)
#         --swap-gb <N>(swap 항목이 더할 크기) · --watchdog-min <N>(무응답 허용 분)
#         --session-gb <N>(sesscap 의 세션당 상한, 8 이상 전체 메모리 미만). 숫자 옵션의 기본값은 서버 등록부 hardening.* 값
#
# 항목 (이름 | 무엇을 | 왜 | 되돌리기):
#   kernlog  | 사용자를 adm · systemd-journal 그룹에 넣는다             | 사고 뒤 커널 로그를 sudo 없이 읽는다(이번엔 못 읽어 원인 확정이 늦어졌다) | 그룹에서 뺀다
#   hungtask | 멈춘 작업 경고를 횟수 제한 없이 커널 로그에 남긴다       | «blocked for more than 120 seconds» 줄이 10번 뒤 끊기지 않게   | sysctl 파일 삭제
#   watchdog | BMC watchdog(ipmi_watchdog) + systemd RuntimeWatchdogSec | PID 1 이 N분 응답 못 하면 BMC 가 재부팅(이번엔 사람이 올 때까지 4시간 반 멈춤) | 유닛 · 설정 삭제
#   slicecap | user.slice 에 MemoryMax = 전체 − reserve                 | 사용자 작업이 시스템 몫(sshd · journald)까지 먹지 못하게          | drop-in 삭제
#   sesscap  | 대상 사용자의 로그인 세션 스코프(session-N.scope)마다 MemoryMax + MemorySwapMax=0 | 가드 밖 세션의 python3 하나가 113.6G 까지 자라 서버가 멈췄다(11-10). swap 을 막아 상한에 닿으면 바로 종료 | drop-in 삭제 + 열린 세션 상한 해제
#   reclaim  | vm.watermark_scale_factor · vm.min_free_kbytes 를 올린다 | 여유가 바닥나기 전에 미리 회수해 할당 정체를 줄인다(251G 에 88M 는 작다) | sysctl 파일 삭제
#   swap     | swap 파일을 더한다(기본 32G, 기존 2G 는 그대로)           | swap 2G 가 몇 시간째 99% 였다                                  | swapoff · fstab 줄 · 파일 삭제
#
# 주의 (2026-11-10 security 검수 반영):
#   - 작성한 세션이 sudo 로 실행해 보지 못했다(검증은 bash -n · shellcheck · 점검 모드까지). 먼저 점검 모드로 읽어 본다.
#   - watchdog 는 멈춤을 «재부팅» 으로 바꾼다. 돌던 학습은 모두 끊긴다. 재부팅 뒤부터 걸리며, 실제로 걸렸는지는
#     `sudo ipmitool mc watchdog get`(Timer Use · Running)과 `journalctl -b | grep -i watchdog` 로 본다.
#     `systemctl show -p RuntimeWatchdogUSec` 는 설정값만 보여 주므로 증거가 아니다. systemd 249 가 부팅 초기에 장치를 못 열면
#     걸리지 않을 수 있다(부팅 루프는 아니다). BMC 가 실제로 재부팅하는지는 시험하지 못했다.
#   - slicecap 은 user.slice 아래 프로세스만 막는다. docker 로 띄운 작업은 system.slice 라 이 상한 밖이다.
#     상한에 닿으면 사용자 작업 가운데 큰 프로세스가 OOM 종료된다(memguard 의 --max 와 별개 층).
#   - sesscap 의 drop-in(session-.scope.d)은 이름 앞부분 규칙이라 «모든 사용자의» 새 로그인 세션에 걸린다(root · 다른 사용자 포함).
#     학습 판은 user@UID.service/app.slice/memguard-*.scope 라 세션 스코프 밖이어서 이 상한과 무관하다.
#     적용 전 검사는 «모든 사용자의» 로그인 세션을 본다(daemon-reload 때 다른 사용자의 열린 세션에도 걸릴 수 있어 안전한 쪽으로).
#     한 세션이라도 memory.current + memory.swap.current 가 상한의 80% 이상이거나 값을 못 읽으면 아무것도 바꾸지 않고 실패한다
#     (상한을 사용량 아래로 걸면 즉시 OOM 종료, swap 차단을 걸면 swap 의 페이지가 돌아와 상한을 넘길 수 있다. 검사 중 끝난 세션은 건너뛴다).
#     열린 세션에 상한을 거는 일(set-property)은 대상 사용자의 세션만 한다. 적용이 중간에 실패하면 drop-in 은 남으므로 --revert sesscap 으로 지운다.
#     drop-in 이 새 세션에 실제로 걸리는지는 이 스크립트가 못 본다. 다음 로그인 뒤 `systemctl show session-<새 id>.scope -p MemoryMax -p DropInPaths` 로 확인한다.
#   - reclaim 을 걸면 MemAvailable 이 약 10G 낮게 보인다. mem-watch · memguard 임계가 그 값 기준이다.
#   - hungtask 는 커널 로그에 남길 뿐이다. 원인이 디스크 입출력 정체면 그 로그도 디스크에 못 쓸 수 있다.
#   - 원인 확정(2026-11-10 커널 로그, 위 경위 노트): 메모리 가드 밖 로그인 세션 스코프의 python3 한 개가
#     113.6GiB 까지 자라 전역 OOM 이 났고, 커널이 oom_score_adj 가 높은 작은 파드 프로세스를 6시간 동안 먼저 종료했다.
#     이 유형에 직접 걸리는 항목은 slicecap · sesscap 이다(sesscap 은 범인이 든 스코프 자체를 막는다).
#   - sesscap 은 MemorySwapMax=0 도 건다. 상한에 닿은 뒤 swap 34G 를 디스크로 밀어내는 동안 같은 스코프 다른 프로세스 메모리까지 밀려 종료가 늦어진다.
#   - swap 은 all 에 넣지 않았다. 사고 때 MemAvailable 79 · 91G 는 급증 도중의 표본이었고 swap 은 이 유형을 못 막는다(분당 24~33G
#     급증을 1~2분 늦출 뿐). 새 swap 은 / 와 같은 디스크라 입출력 정체가 원인이면 오히려 키울 수 있다. 서버에는 쓰지 않는 30G 파일 /swapfile2 · /swapfile_extra 가 이미 있다.
#   - sshd 항목은 뺐다. sshd 는 이미 oom_score_adj=-1000 · Restart=on-failure 이고, ssh.service 의 MemoryMin 은
#     system.slice 에 같은 설정이 없으면 효과가 없다.
#   - reclaim · swap 은 확정된 원인(세션 스코프의 메모리 폭주)에 직접 듣지 않는다. 회수 정체 쪽 가설을 위한 보조 항목이다.
#   - vm.overcommit_memory(지금 1)는 건드리지 않는다. 바꾸면 큰 프로세스의 fork 가 실패해 학습이 깨질 수 있다.
set -euo pipefail
# REF: knowledge/harness/code-history/tools__mem-guard__host-hardening.sh.md

MODE=check ITEMS=all TARGET_USER="${SUDO_USER:-}" RESERVE_GB='' SWAP_GB='' WD_MIN='' SESSION_GB=''
ALL_ITEMS="kernlog hungtask watchdog slicecap sesscap reclaim swap"
DEFAULT_ITEMS="kernlog hungtask watchdog slicecap sesscap reclaim"

usage() { sed -n '6,13p' "$0" | sed 's/^# \{0,1\}//'; exit 64; }
while [ $# -gt 0 ]; do
  case "$1" in
    --apply|--revert|--user|--reserve-gb|--swap-gb|--watchdog-min|--session-gb) [ $# -ge 2 ] || usage ;;
  esac
  case "$1" in
    --apply)  MODE=apply;  ITEMS="$2"; shift 2 ;;
    --revert) MODE=revert; ITEMS="$2"; shift 2 ;;
    --user) TARGET_USER="$2"; shift 2 ;;
    --reserve-gb) RESERVE_GB="$2"; shift 2 ;;
    --swap-gb) SWAP_GB="$2"; shift 2 ;;
    --watchdog-min) WD_MIN="$2"; shift 2 ;;
    --session-gb) SESSION_GB="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "모르는 인자: $1" >&2; usage ;;
  esac
done
if [ "$ITEMS" = all ]; then
  if [ "$MODE" = check ]; then ITEMS="$ALL_ITEMS"; else ITEMS="$DEFAULT_ITEMS"; fi
fi
ITEMS="${ITEMS//,/ }"
[ -n "${ITEMS// /}" ] || usage
# WHY: 앞자리 0(예: 010)은 $((…)) 가 8진수로 읽으므로 받지 않는다. 등록부를 읽기 전에 보아 어느 서버에서든 같은 판정이 나게 한다.
for n in "$RESERVE_GB" "$SWAP_GB" "$WD_MIN" "$SESSION_GB"; do
  case "$n" in '') ;; *[!0-9]*|0?*) echo "숫자가 아닌 값(앞자리 0 불가): $n" >&2; exit 64 ;; esac
done
# WHY: a missing config/hosts/<hostname>.json ("hardening") means another or a new server,
# so stop rather than reuse numbers measured elsewhere.
# NEVER: eval a registry value or use it as a command string. This runs as root, and each value must match a fixed shape before use.
REGISTRY="$(dirname "$(readlink -f "$0")")/../../scripts/harness_registry.py"
reg() {
  local v
  v=$(python3 -I "$REGISTRY" host "hardening.$1") || return 1
  [[ $v =~ $2 ]] || { echo "등록부 값 hardening.$1 = '$v' 가 허용 꼴($2)이 아닙니다" >&2; return 1; }
  printf '%s\n' "$v"
}
NUM='^(0|[1-9][0-9]{0,6})$'
[ -n "$RESERVE_GB" ] || RESERVE_GB=$(reg reserve_gb "$NUM") || exit 78
[ -n "$SWAP_GB" ] || SWAP_GB=$(reg swap_gb "$NUM") || exit 78
[ -n "$WD_MIN" ] || WD_MIN=$(reg watchdog_min "$NUM") || exit 78
[ -n "$SESSION_GB" ] || SESSION_GB=$(reg session_gb "$NUM") || exit 78
TAG=$(reg tag '^[a-z0-9][a-z0-9-]{0,30}$') || exit 78
SLICECAP_MIN_GB=$(reg slicecap_min_gb "$NUM") || exit 78
RECLAIM_WSF=$(reg reclaim_watermark_scale_factor "$NUM") || exit 78
RECLAIM_MINFREE=$(reg reclaim_min_free_kbytes "$NUM") || exit 78
REVERT_WSF=$(reg revert_watermark_scale_factor "$NUM") || exit 78
REVERT_MINFREE=$(reg revert_min_free_kbytes "$NUM") || exit 78
# WHY: sesscap 을 고른 때만 범위를 본다(작은 서버에서 기본값 64 가 다른 항목까지 막지 않게). 자릿수 제한은 산술 넘침 방지.
case " $ITEMS " in *" sesscap "*)
  [ "${#SESSION_GB}" -le 6 ] || { echo "--session-gb 가 너무 큽니다: $SESSION_GB" >&2; exit 64; }
  SESSION_GB=$((10#$SESSION_GB))
  mem_total_gb=$(awk '/^MemTotal:/{printf "%d", $2/1048576}' /proc/meminfo)
  if [ "$SESSION_GB" -lt 8 ] || [ "$SESSION_GB" -ge "$mem_total_gb" ]; then
    echo "--session-gb 는 8 이상 전체 메모리(${mem_total_gb}G) 미만이어야 합니다: $SESSION_GB" >&2; exit 64
  fi ;;
esac
for it in $ITEMS; do
  case " $ALL_ITEMS " in *" $it "*) ;; *) echo "모르는 항목: $it (가능: $ALL_ITEMS)" >&2; exit 64 ;; esac
done
if [ "$MODE" != check ] && [ "$(id -u)" -ne 0 ]; then
  echo "적용 · 되돌리기는 root 로 실행해야 합니다: sudo bash $0 --$MODE ..." >&2; exit 77
fi

SYSCTL_HUNG=/etc/sysctl.d/90-$TAG-hungtask.conf
SYSCTL_RECLAIM=/etc/sysctl.d/90-$TAG-reclaim.conf
WD_SERVICE=$TAG-watchdog-module.service
WD_UNIT=/etc/systemd/system/$WD_SERVICE
WD_CONF=/etc/systemd/system.conf.d/90-$TAG-watchdog.conf
SLICE_DROPIN=/etc/systemd/system/user.slice.d/90-$TAG-memcap.conf
SESS_DROPIN_DIR=/etc/systemd/system/session-.scope.d
SESS_DROPIN=$SESS_DROPIN_DIR/90-$TAG-sesscap.conf
SWAPFILE=/swapfile-$TAG
FSTAB_BAK=/etc/fstab.bak-$TAG

say() { printf '%s\n' "$*"; }
head_line() { say ""; say "== $1 =="; }
total_gb() { awk '/^MemTotal:/{printf "%d", $2/1048576}' /proc/meminfo; }
need_user() {
  [ -n "$TARGET_USER" ] || { echo "$1: --user <이름> 이 필요합니다" >&2; return 1; }
  case "$TARGET_USER" in -*) echo "$1: 사용자 이름이 올바르지 않습니다" >&2; return 1 ;; esac
  id -- "$TARGET_USER" >/dev/null 2>&1 || { echo "$1: 없는 사용자: $TARGET_USER" >&2; return 1; }
}

kernlog_check() {
  head_line "kernlog (커널 로그 읽기 권한)"
  if [ -z "$TARGET_USER" ]; then say "대상 사용자 미정(--user 로 지정). 지금 사용자: $(id -un)"; return 0; fi
  say "지금: $TARGET_USER 의 그룹 = $(id -nG -- "$TARGET_USER" 2>/dev/null || echo '?')"
  say "적용: adm · systemd-journal 그룹에 추가(새 로그인부터 적용. adm 은 /var/log 의 다른 로그도 읽게 한다)"
}
kernlog_apply() {
  need_user kernlog
  usermod -aG adm,systemd-journal "$TARGET_USER"
  say "kernlog: $TARGET_USER 를 adm · systemd-journal 에 넣었습니다(다시 로그인해야 적용)."
}
kernlog_revert() {
  need_user kernlog
  say "kernlog: 주의 — 적용 전부터 이 그룹에 있었는지는 기록하지 않습니다. 두 그룹에서 모두 뺍니다."
  gpasswd -d "$TARGET_USER" adm || true
  gpasswd -d "$TARGET_USER" systemd-journal || true
}

hungtask_check() {
  head_line "hungtask (멈춘 작업 커널 기록)"
  say "지금: hung_task_timeout_secs=$(cat /proc/sys/kernel/hung_task_timeout_secs) hung_task_warnings=$(cat /proc/sys/kernel/hung_task_warnings) hung_task_panic=$(cat /proc/sys/kernel/hung_task_panic)"
  say "적용: hung_task_warnings=-1(횟수 제한 없음), timeout 120 유지, panic 은 0 유지 → $SYSCTL_HUNG"
}
hungtask_apply() {
  printf '%s\n' "# host-hardening.sh hungtask" "kernel.hung_task_timeout_secs = 120" "kernel.hung_task_warnings = -1" > "$SYSCTL_HUNG"
  sysctl -q -p "$SYSCTL_HUNG"
  say "hungtask: 적용했습니다."
}
hungtask_revert() { rm -f "$SYSCTL_HUNG"; sysctl -q -w kernel.hung_task_warnings=10 || true; say "hungtask: 되돌렸습니다."; }

watchdog_check() {
  head_line "watchdog (멈추면 자동 재부팅)"
  say "지금: RuntimeWatchdogUSec(설정값)=$(systemctl show -p RuntimeWatchdogUSec --value 2>/dev/null || echo '?') · /dev/watchdog $([ -e /dev/watchdog ] && echo 있음 || echo 없음) · /dev/ipmi0 $([ -e /dev/ipmi0 ] && echo 있음 || echo 없음)"
  say "적용: 부팅 때 ipmi_watchdog 모듈을 올리는 유닛 + RuntimeWatchdogSec=${WD_MIN}min · RebootWatchdogSec=10min"
  say "      (PID 1 무응답 ${WD_MIN}분 뒤 BMC 가 재부팅. 재부팅 뒤부터 걸리며 확인은 sudo ipmitool mc watchdog get)"
}
watchdog_apply() {
  [ -e /dev/ipmi0 ] || { echo "watchdog: /dev/ipmi0 가 없어 BMC watchdog 를 쓸 수 없습니다." >&2; return 1; }
  modinfo ipmi_watchdog >/dev/null 2>&1 || { echo "watchdog: ipmi_watchdog 모듈이 없습니다." >&2; return 1; }
  printf '%s\n' "# host-hardening.sh watchdog" "[Unit]" "Description=Load BMC watchdog module ($TAG hardening)" \
    "DefaultDependencies=no" "Before=sysinit.target" "" "[Service]" "Type=oneshot" "RemainAfterExit=yes" \
    "ExecStart=/sbin/modprobe ipmi_watchdog action=reset start_now=0" "" "[Install]" "WantedBy=sysinit.target" > "$WD_UNIT"
  mkdir -p "$(dirname "$WD_CONF")"
  printf '%s\n' "# host-hardening.sh watchdog" "[Manager]" "RuntimeWatchdogSec=${WD_MIN}min" "RebootWatchdogSec=10min" > "$WD_CONF"
  systemctl daemon-reload
  systemctl enable "$WD_SERVICE"
  say "watchdog: 설정을 썼습니다. 재부팅 뒤부터 걸립니다."
  say "          재부팅 후 확인: sudo ipmitool mc watchdog get ; journalctl -b | grep -i watchdog"
  say "          Running 이 아니면 걸리지 않은 것입니다. 그때는 --revert watchdog 로 지우십시오."
}
watchdog_revert() {
  systemctl disable "$WD_SERVICE" 2>/dev/null || true
  rm -f "$WD_UNIT" "$WD_CONF"; systemctl daemon-reload
  say "watchdog: 설정을 지웠습니다. 이미 걸려 있으면 재부팅 전까지 유지됩니다(바로 풀려면 sudo systemctl daemon-reexec, 미검증)."
}

slicecap_check() {
  head_line "slicecap (사용자 작업 전체 메모리 상한)"
  say "지금: user.slice MemoryMax=$(systemctl show user.slice -p MemoryMax --value 2>/dev/null || echo '?') · 전체 $(total_gb)G"
  say "적용: MemoryMax=$(( $(total_gb) - RESERVE_GB ))G (전체 − ${RESERVE_GB}G). 넘으면 사용자 작업 안에서 OOM 종료가 나고 시스템 몫은 남습니다(docker 작업은 대상 밖)"
}
slicecap_apply() {
  local cap=$(( $(total_gb) - RESERVE_GB ))
  [ "$cap" -ge "$SLICECAP_MIN_GB" ] || { echo "slicecap: 계산된 상한 ${cap}G 가 너무 작습니다" >&2; return 1; }
  mkdir -p "$(dirname "$SLICE_DROPIN")"
  printf '%s\n' "# host-hardening.sh slicecap" "[Slice]" "MemoryMax=${cap}G" > "$SLICE_DROPIN"
  systemctl daemon-reload
  say "slicecap: drop-in 을 썼습니다. 지금 걸린 값(memory.max): $(cat /sys/fs/cgroup/user.slice/memory.max 2>/dev/null || echo '?')"
}
slicecap_revert() {
  rm -f "$SLICE_DROPIN"; systemctl daemon-reload
  say "slicecap: 되돌렸습니다. 지금 값(memory.max): $(cat /sys/fs/cgroup/user.slice/memory.max 2>/dev/null || echo '?')"
}

# NEVER: sesscap 함수에 grep 무매치 · 빈 목록으로 실패하는 꼴을 쓰지 않는다. 항목 함수는 set -e 서브셸에서 불려 그 실패가 죽음으로 번진다(awk 와 if 로 쓴다).
sesscap_ids() {
  { loginctl list-sessions --no-legend 2>/dev/null || true; } | awk -v u="$1" '$2==u && $1 ~ /^[0-9]+$/ {print $1}'
}
sesscap_all() {
  { loginctl list-sessions --no-legend 2>/dev/null || true; } | awk '$1 ~ /^[0-9]+$/ && $2 ~ /^[0-9]+$/ {print $2 ":" $1}'
}
sesscap_cg() { echo "/sys/fs/cgroup/user.slice/user-$1.slice/session-$2.scope"; }
sesscap_val() {
  local v; v=$(cat "$1" 2>/dev/null) || { printf '?'; return 0; }
  case "$v" in ''|*[!0-9]*) printf '%s' "${v:-?}" ;; *) awk -v b="$v" 'BEGIN{printf "%.1fGiB", b/1073741824}' ;; esac
}
sesscap_check() {
  head_line "sesscap (로그인 세션 스코프 메모리 상한)"
  local user="${TARGET_USER:-$(id -un)}" uid ids id cg
  [ -n "$TARGET_USER" ] || say "대상 사용자 미정(--user 로 지정). 지금 사용자 $user 의 세션을 점검만 합니다"
  uid=$(id -u -- "$user" 2>/dev/null) || { say "없는 사용자: $user"; return 1; }
  ids=$(sesscap_ids "$uid")
  if [ -z "$ids" ]; then say "지금: $user 의 열린 로그인 세션이 없습니다"; fi
  for id in $ids; do
    cg=$(sesscap_cg "$uid" "$id")
    say "지금: session-$id.scope $(systemctl show "session-$id.scope" -p MemoryMax -p DropInPaths 2>/dev/null | tr '\n' ' ')"
    say "      memory.current=$(sesscap_val "$cg/memory.current") · memory.peak=$(sesscap_val "$cg/memory.peak") · memory.max=$(sesscap_val "$cg/memory.max")"
    say "      memory.swap.current=$(sesscap_val "$cg/memory.swap.current") · memory.swap.max=$(sesscap_val "$cg/memory.swap.max")"
  done
  say "적용: 세션마다 MemoryMax=${SESSION_GB}G · MemorySwapMax=0(swap 차단, runtime) + 새 로그인 세션용 drop-in $SESS_DROPIN"
  say "      drop-in 은 모든 사용자의 새 로그인 세션에 걸립니다. 모든 사용자의 세션 가운데 하나라도 memory.current + swap.current 가 상한의 80% 이상이거나 못 읽으면 적용하지 않고 실패합니다"
}
sesscap_apply() {
  need_user sesscap
  local uid ids id cg cur sw tok unread cap_b=$(( SESSION_GB * 1073741824 )) bad=0 fail=0 now swp
  local left="sesscap: drop-in 은 남아 있습니다. --revert sesscap 으로 지우거나 원인을 고친 뒤 다시 적용하십시오."
  uid=$(id -u -- "$TARGET_USER")
  ids=$(sesscap_ids "$uid")
  for tok in $(sesscap_all); do
    cg=$(sesscap_cg "${tok%%:*}" "${tok##*:}")
    [ -d "$cg" ] || continue
    cur=$(cat "$cg/memory.current" 2>/dev/null || true)
    sw=$(cat "$cg/memory.swap.current" 2>/dev/null || true)
    unread=0
    case "$cur" in ''|*[!0-9]*) unread=1 ;; esac
    case "$sw" in ''|*[!0-9]*) unread=1 ;; esac
    if [ "$unread" -eq 1 ]; then
      [ -d "$cg" ] || continue
      echo "sesscap: session-${tok##*:}.scope(uid ${tok%%:*}) 값을 읽지 못해 적용하지 않습니다" >&2; bad=1; continue
    fi
    if [ $(( (cur + sw) * 100 )) -ge $(( cap_b * 80 )) ]; then
      echo "sesscap: session-${tok##*:}.scope(uid ${tok%%:*}) 가 memory.current + swap.current = $(( (cur + sw) / 1048576 ))MiB 로 상한 ${SESSION_GB}G 의 80% 이상입니다" >&2; bad=1
    fi
  done
  [ "$bad" -eq 0 ] || { echo "sesscap: 아무것도 바꾸지 않았습니다. --session-gb 를 올리거나 세션 안 프로세스를 줄인 뒤 다시 실행하십시오." >&2; return 1; }
  mkdir -p "$SESS_DROPIN_DIR"
  printf '%s\n' "# host-hardening.sh sesscap — 이름 앞부분(session-) drop-in 이라 모든 사용자의 새 로그인 세션에 적용된다" "[Scope]" "MemoryMax=${SESSION_GB}G" "MemorySwapMax=0" > "$SESS_DROPIN"
  systemctl daemon-reload || { echo "sesscap: daemon-reload 가 실패했습니다. $left" >&2; return 1; }
  for id in $ids; do
    if ! systemctl set-property --runtime "session-$id.scope" "MemoryMax=${SESSION_GB}G" MemorySwapMax=0; then
      echo "sesscap: session-$id.scope 에 상한을 걸지 못했습니다. $left" >&2; fail=1; continue
    fi
    now=$(cat "$(sesscap_cg "$uid" "$id")/memory.max" 2>/dev/null || echo '?')
    swp=$(cat "$(sesscap_cg "$uid" "$id")/memory.swap.max" 2>/dev/null || echo '?')
    say "sesscap: session-$id.scope memory.max=$now (기대 $cap_b) · memory.swap.max=$swp (기대 0)"
    if [ "$now" != "$cap_b" ]; then echo "sesscap: session-$id.scope 에 메모리 상한이 걸리지 않았습니다" >&2; fail=1; fi
    if [ "$swp" != "0" ]; then echo "sesscap: session-$id.scope 에 swap 차단이 걸리지 않았습니다" >&2; fail=1; fi
  done
  say "sesscap: drop-in 을 썼습니다($SESS_DROPIN). 모든 사용자의 새 로그인 세션에 적용됩니다."
  say "         새 세션에 실제로 걸리는지는 확인하지 못했습니다. 다음 로그인 뒤 systemctl show session-<새 id>.scope -p MemoryMax -p DropInPaths 로 확인하십시오."
  if [ "$fail" -ne 0 ]; then echo "$left" >&2; fi
  return "$fail"
}
sesscap_revert() {
  local uid ids id cg fail=0
  # NEVER: drop-in 삭제를 need_user 뒤로 옮기지 않는다. 사용자를 못 정해도(SUDO_USER 빈 값 등) 새 세션에 상한이 걸리는 원인은 지워져야 한다.
  rm -f "$SESS_DROPIN"
  rmdir "$SESS_DROPIN_DIR" 2>/dev/null || true
  systemctl daemon-reload || { echo "sesscap: daemon-reload 가 실패했습니다" >&2; return 1; }
  if ! need_user sesscap; then
    echo "sesscap: drop-in 은 지웠고, 열린 세션의 상한은 --user 를 주고 다시 실행하면 풉니다" >&2; return 1
  fi
  uid=$(id -u -- "$TARGET_USER")
  ids=$(sesscap_ids "$uid")
  for id in $ids; do
    cg=$(sesscap_cg "$uid" "$id")
    if ! systemctl set-property --runtime "session-$id.scope" MemoryMax=infinity MemorySwapMax=infinity; then
      echo "sesscap: session-$id.scope 상한을 풀지 못했습니다" >&2; fail=1; continue
    fi
    say "sesscap: session-$id.scope memory.max=$(sesscap_val "$cg/memory.max") · memory.swap.max=$(sesscap_val "$cg/memory.swap.max")"
    if [ "$(cat "$cg/memory.max" 2>/dev/null || echo '?')" != max ] || [ "$(cat "$cg/memory.swap.max" 2>/dev/null || echo '?')" != max ]; then
      echo "sesscap: session-$id.scope 의 상한이 max 로 돌아오지 않았습니다" >&2; fail=1
    fi
  done
  say "sesscap: drop-in 을 지웠습니다(이미 열린 세션은 위 값, 새 세션은 상한 없음)."
  return "$fail"
}

reclaim_check() {
  head_line "reclaim (미리 회수)"
  say "지금: vm.watermark_scale_factor=$(cat /proc/sys/vm/watermark_scale_factor) vm.min_free_kbytes=$(cat /proc/sys/vm/min_free_kbytes)"
  say "적용: watermark_scale_factor=$RECLAIM_WSF · min_free_kbytes=$RECLAIM_MINFREE($(( RECLAIM_MINFREE / 1048576 ))G) → $SYSCTL_RECLAIM (MemAvailable 이 약 10G 낮게 보입니다)"
}
reclaim_apply() {
  printf '%s\n' "# host-hardening.sh reclaim" "vm.watermark_scale_factor = $RECLAIM_WSF" "vm.min_free_kbytes = $RECLAIM_MINFREE" > "$SYSCTL_RECLAIM"
  sysctl -q -p "$SYSCTL_RECLAIM"
  say "reclaim: 적용했습니다."
}
reclaim_revert() {
  rm -f "$SYSCTL_RECLAIM"
  sysctl -q -w "vm.watermark_scale_factor=$REVERT_WSF" || true
  sysctl -q -w "vm.min_free_kbytes=$REVERT_MINFREE" || true
  say "reclaim: 되돌렸습니다(사고 당시 값 $REVERT_WSF · $REVERT_MINFREE)."
}

swap_check() {
  head_line "swap (swap 파일 추가 — all 에 포함되지 않음, 이름을 적어야 적용)"
  say "지금: $(swapon --noheadings --show=NAME,SIZE,USED 2>/dev/null | tr '\n' ';')"
  say "적용: $SWAPFILE ${SWAP_GB}G 를 더하고 /etc/fstab 에 한 줄 추가(/ 여유: $(df -BG --output=avail / | tail -1 | tr -d ' '))"
}
swap_apply() {
  [ ! -e "$SWAPFILE" ] || { echo "swap: $SWAPFILE 가 이미 있습니다(반쯤 만든 것이면 --revert swap 뒤 다시)." >&2; return 1; }
  local avail; avail=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')
  [ "$avail" -ge $(( SWAP_GB + 50 )) ] || { echo "swap: / 여유 ${avail}G 가 부족합니다(필요 ${SWAP_GB}G + 50G)" >&2; return 1; }
  cp -a /etc/fstab "$FSTAB_BAK"
  fallocate -l "${SWAP_GB}G" "$SWAPFILE"
  chmod 600 "$SWAPFILE"
  mkswap "$SWAPFILE" >/dev/null
  swapon "$SWAPFILE"
  grep -q "^$SWAPFILE " /etc/fstab || printf '%s\n' "$SWAPFILE none swap sw 0 0" >> /etc/fstab
  say "swap: $SWAPFILE ${SWAP_GB}G 를 켰습니다(fstab 사본: $FSTAB_BAK)."
}
swap_revert() {
  if swapon --noheadings --show=NAME 2>/dev/null | grep -qx "$SWAPFILE"; then
    local used avail
    used=$(swapon --noheadings --bytes --show=NAME,USED | awk -v f="$SWAPFILE" '$1==f{printf "%d", $2/1024}')
    avail=$(awk '/^MemAvailable:/{print $2}' /proc/meminfo)
    [ "${used:-0}" -lt "$avail" ] || { echo "swap: 쓰는 중인 swap(${used}kB)이 가용 메모리(${avail}kB)보다 큽니다. 지금 끄면 위험해 중단합니다." >&2; return 1; }
    swapoff "$SWAPFILE" || { echo "swap: swapoff 실패. fstab 과 파일은 건드리지 않았습니다." >&2; return 1; }
  fi
  cp -a /etc/fstab "$FSTAB_BAK"
  sed -i "\|^$SWAPFILE |d" /etc/fstab
  rm -f "$SWAPFILE"
  say "swap: 되돌렸습니다(fstab 사본: $FSTAB_BAK)."
}

# NEVER: 항목 함수를 `if ! f` 안에서 부르지 않는다. 그 안에서는 set -e 가 꺼져 중간 실패 뒤에도 성공 문구가 나온다.
rc=0
for it in $ITEMS; do
  set +e
  ( set -e; "${it}_${MODE}" )
  st=$?
  set -e
  if [ "$st" -ne 0 ]; then echo "[$it] $MODE 실패 또는 건너뜀(종료 코드 $st)" >&2; rc=1; fi
done
if [ "$MODE" = check ]; then say ""; say "점검만 했습니다. 적용: sudo bash $0 --apply <항목,항목|all>  (all 은 swap 제외)"; fi
exit "$rc"
