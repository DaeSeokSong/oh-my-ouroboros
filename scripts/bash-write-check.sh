#!/bin/bash
# shellcheck disable=SC2016  # 정규식·jq 본문의 $ 는 전개 대상이 아님
# bash-write-check.sh — Bash 명령어 읽기/쓰기 분류 게이트
#
# 구조: settings.json에서 "Bash(*)" 전체 허용 → 이 hook이 유일한 쓰기 차단 게이트
#
# 출력 형식 (2026-07-15 교정 — GPT 교차감사 FINDING 4.2):
#   읽기 전용 판단 → 무출력 exit 0 (별도 승인 의미 없음 — 정상 permission flow에 위임.
#     구형 {"decision":"allow"}는 유효 스키마가 아니라서 매 benign 호출마다 validation
#     오류를 내고 무시되던 것을 제거 — 구형 유효값은 approve/block뿐)
#   쓰기 작업 감지 → 신형 hookSpecificOutput.permissionDecision: "deny" (차단)
#
# 차단 대상 (파일시스템/환경을 변경하는 쓰기 작업):
#   - 파일 쓰기 리다이렉션 (> file, >> file)
#   - 파일 삭제·이동·복사 (rm, rmdir, mv, cp, dd, truncate, shred)
#   - 권한·소유권 변경 (chmod, chown)
#   - 패키지 설치 (pip/uv/conda/apt/yum/brew/npm/yarn/cargo install)
#   - 패키지·환경 변경 확장 (2026-09-08 main 검토: pip3·pip3.11 이 `pip` 뒤 공백 조건에 안 걸렸고 uv add·uv sync·npm i·python3 -m venv 는 열거에 아예 없었다)
#   - 아카이브·패치 생성 (patch / zip / 7z a·d·u·x·e / tar 생성 모드 -c…f — 2026-09-08 main 검토: 추출만 막고 생성은 열려 있었다)
#   - wget 은 기본 동작이 cwd 저장 (2026-09-08 main 검토: `-O/-P` 가 있을 때만 막아 `wget URL` 이 그대로 통과했다. 이제 `-O -`·`-O-`·`--output-document=-`·`--spider` 만 통과)
#   - 원격·컨테이너 실행 컨텍스트 (ssh / docker·podman exec·run / kubectl exec — 2026-09-08 main 검토: 따옴표 제거 단계에서 페이로드가 사라져 `ssh host "rm -rf x"` 가 무검사 통과했다. 규칙 2 트리거에 편입)
#   - 환경 상태 변경 (pkill·killall / tmux kill-* / mount·umount / systemctl 상태 전환 / crontab -e·-r / sysctl -w — 2026-09-05 실사고: `pkill -f 평가스크립트명` 이 같은 이름을 argv 에 가진 학습 와쳐를 죽였다. 사용자 지시 «pid 로만 kill»)
#   - 리다이렉션 없는 파일 쓰기 (tee / sed -i / perl·ruby -i / awk -i inplace / find -delete·-fprint·-fls / curl -o·-O / wget)
#   - 중첩 실행 컨텍스트 내부의 쓰기 명령 ($(...) / `...` / sh -c / | bash)
#   - eval (3) / 명령 위치 변수 참조 ($VAR 형태, 따옴표 감싼 "$VAR"·exec/env 등 래퍼 뒤 포함 — 0.5)
#   - 디코더/파이프→셸·인터프리터 (… | bash/sh, 파일·모듈 피연산자가 없거나(`-`·`--`·플래그만) stdin 별칭(/dev/stdin·/dev/fd/N·/proc/*/fd/N)을 받는 … | python3 …,
#     bash < <(…)·python3 <(…) 프로세스 치환 입력, |&·sudo/xargs/경로 접두·따옴표·뒤따르는 >/dev/null 2>&1 무관 — 0.4, APPROVED 검사보다 앞이라 승인 여부 무관 무조건 차단)
#   - 명령 위치 토큰의 브레이스·글롭 전개 ({r,}m · r[m] — 0.7, fail-closed)
#   - 인라인·heredoc·here-string 인터프리터 코드의 쓰기·실행 (python -c / <<EOF / <<< — 3.5. 파이프·프로세스 치환으로 들어오는 stdin 코드는 0.4)
#   - # APPROVED 는 리터럴 경로의 단순 셸 명령에만 (원장 경로 언급·인터프리터·디코더·find -delete·치환 섞이면 거부)
#   - # APPROVED 첫 줄은 승인한 사용자 발화를 «…»·"…" 로 인용해야 하고, 그 인용이 8자 이상이며 프롬프트 로그에 실재해야 한다 (2026-09-14)
#
# 설계 방침: 중첩 실행 컨텍스트가 보이면 fail-closed(원문 그대로 재검사).
#   드문 오탐(예: echo "$(grep -c foo f)")은 첫 줄 "# APPROVED" 마커로 통과. (미탐 < 오탐 우선)
# 한계: 키워드 뒤 변수 실행·heredoc 내부·다중 인코딩은 완전 탐지 못 함 (~95% 커버).
# git 쓰기(commit 등)는 이 hook이 아니라 commit 규칙이 제어 — git 토큰은 검사에서만 중화.
#
# 2026-09-08 검수 교정 (훅을 실제로 실행해 재현한 오탐 실측). 규칙이 자기 주석에 선언한 범위 밖에서 잡던 두 갈래만 좁혔다.
#   ① 0.5 는 따옴표 **안**의 `(`·`;` 뒤 `$` 까지 명령 위치로 봐 `awk '{print substr($0,1,60)}'`·`echo "a; $2"` 를 차단했다.
#   ② 0.5·0.7 은 실행 래퍼 뒤 **인자**를 명령 위치로 봐 `env cat "$PWD/x"`·`env ls scripts/*.sh` 를 차단했다.
#   회귀 테스트: scripts/tests/test_bash_write_check.py (차단 케이스가 하나라도 통과로 바뀌면 그 수정안은 기각)
#
# 2026-09-08 미탐 보강 (main 검토 — 훅을 실제로 실행해 미탐을 재현한 뒤 갈래별로 넓혔다). 기존 규칙(0.4·DYN·XARGS·APPROVED·0.5·0.7·3.5)의 로직은 그대로 두고 check_write_patterns 와 규칙 2 트리거만 손댔다.
#   ① wget 기본 저장 ② 패키지·환경 변경 열거 확장 ③ patch·zip·7z·tar 생성 ④ tar 추출 오탐 축소 ⑤ 원격·컨테이너 실행 ⑥ 환경 상태 변경.
#   ④ 종전 `-?[A-Za-z]*x` 는 **파일명 토큰** 속 x 도 추출로 봐 `tar tf index.tar`·`tar -tf xz-backup.tar` 를 차단했다 → 모드 토큰(단일 대시 묶음·tar 뒤 첫 bare 토큰·`--extract/--get`)만 본다.
#   ⑤ **`tmux send-keys` 는 일부러 넣지 않는다**: 학습 발사는 `tmux send-keys -t <접두>N` 으로만 한다(2026-09-07 사용자 규칙)이고 그 명령서엔 `> log 2>&1` 이 들어 있어
#      원문 재검사를 열면 공식 발사 통로가 통째로 막힌다. 발사 게이트는 이 훅이 아니라 train-launch-warn.sh 가 맡는다.
#
# 2026-10-06 오탐 완화는 «읽기 전용 허용 목록» 방식으로만 한다 (0.46 allowlist_scan).
#   지난 두 차례는 따옴표 안을 검사에서 빼고 위험한 운반자(sh -c·watch·trap…)를 열거해 예외로 두었는데, 독립 검수마다 목록 밖 운반자
#   (entr·sem·git -c·PS4=·let·[[ ]]·case 패턴의 `)` 등)가 새 미탐으로 나왔다. 위험을 열거하는 쪽은 끝이 없다.
#   그래서 반대로, 명령 전체를 실제 셸 따옴표 규칙으로 파싱해 «인자를 셸 코드로 실행하지 않는 읽기 전용 명령»(grep·cat·sed 의 좁은 형태·
#   git 읽기 하위명령·bash x.sh 등)과 for·if·파이프·안전한 리다이렉션만으로 이루어졌다고 증명될 때만 완화한다.
#   완화는 네 곳(0.5 S_CMDPOS · 규칙 2 의 `$(`/백틱 트리거 · 규칙 2 의 S_RAW · WORDGEN_RE2 의 S_UQ)에서 원문 대신 «정리본»을 보는 것뿐이다.
#   정리본 = 작은따옴표 안을 비워 `''` 만 남김 · 큰따옴표 글자 텍스트의 `<>();&|` 를 `_` 로 · `<` 피연산자의 `$` 를 `_` 로.
#   증명이 안 되면(목록 밖 명령·위험 플래그·대입 접두·파싱 불가) 정리본 = 원문이라 원본과 바이트 단위로 같은 판정이다. 조기 통과는 없다.

# 바이트 단위 매칭 고정 (14라운드 실측: en_US.UTF-8 에서 grep 의 `.` 이 한글 다바이트를 못 넘어 `.*`·`\\.` 기반 패턴이 다국어 삽입으로 비껴갈 수 있었다 — C 로캘에선 모든 바이트가 `.`·`[^…]` 에 잡힌다)
export LC_ALL=C
INPUT=$(cat)
# jq 부재 시 CMD 가 공란이 돼 훅 전체가 통과되던 결함 → fail-closed (11라운드 Grok 낮음)
if ! command -v jq >/dev/null 2>&1; then
    printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"[쓰기 차단] jq 부재 — 훅이 명령을 해석할 수 없어 fail-closed. jq 설치 후 재시도"}}'
    exit 0
fi
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)

[ -z "$CMD" ] && exit 0

# 이스케이프 정규화 (6·7라운드): ① ANSI-C `$'\x72\x6d'`·`\162` 를 printf %b 로 디코드한 사본을 원문 뒤에 이어 붙이고
# ② 백슬래시 단일문자(`r\m`) 를 지운다. 검사는 "원문+디코드본" 결합 문자열에 대해 수행(탐지 전용 — 실행되는 명령은 원문).
# APPROVED 검사를 포함한 모든 후속 검사가 이 결합본을 본다. `\n`·`\t` 가 개행·'t' 로 바뀌는 부작용은 탐지에 무해.
FIRST=$(printf '%s\n' "$CMD" | head -1)   # APPROVED 마커 판정은 원문 첫 줄로
DECODED=$(printf '%b' "$CMD" 2>/dev/null | sed -E "s/\\\$'([^']*)'/\1/g")   # $'…' 껍질도 벗겨 rm 이 단어로 드러나게
# 개행은 공백으로 접는다 (9라운드 Grok: `base64 -d |⏎bash` 처럼 줄을 나누면 줄 단위 grep 인 0.5/0.6/2/3.5 가 전부 무력)
# 2026-10-01 P6 검수: 개행은 «명령 경계»이기도 하다 — 단순히 공백으로 접으면 둘째 줄의 `pkill`·`wget`·패키지 관리자가 명령 위치로 안 보인다.
#   앞줄이 연결자(`|`·`&`·`;`·`(`·`\`)로 끝나지 않으면 개행을 ` ; ` 로, 끝나면 공백으로 접는다(위 9라운드 `|⏎bash` 파이프 판정은 그대로).
#   heredoc 본문(`<<TAG`~`TAG`)은 데이터라 공백으로만 접는다 — 아니면 커밋 메시지 `$(cat <<'EOF' …)` 의 줄머리 `pip install` 이 명령으로 오인된다.
#   2026-10-01 P6 보안 재검수 H: ① 종료 표지 줄 **뒤**도 명령 경계다(종전엔 표지 줄을 공백으로만 접어 `EOF⏎pkill -f y` 의 pkill 이 경계 밖) ② 표지는 식별자가 아니라
#   **낱말 전체**(`<<'E-F'`·`<<"E F"`)로 읽고 정규식이 아닌 문자열로 대조 ③ 작은따옴표 속 `<<` 는 heredoc 이 아니다(큰따옴표 속 `$(cat <<'EOF'` 는 실제 heredoc 이라 허용)
#   ④ 종료 표지를 끝까지 못 찾으면 heredoc 제외를 적용하지 않는다(전부 명령으로 검사 — 이를 위해 입력을 전부 읽은 뒤 판정) ⑤ 받는 명령이 bash·sh·zsh·dash·ksh 이면
#   본문은 셸이 실행하는 명령이므로 제외하지 않고 줄마다 명령 경계로 본다(`cat` 처럼 본문을 실행하지 않는 명령만 데이터로 접는다).
#   2026-10-02 보안 재검수 I: ⑥ 인용 밖 `#` 주석 구간(`echo a # <<EOF`)과 산술 `$((…))` 안(`$((1<<2))` 의 `<<2`)은 heredoc 시작이 아니다 — 데이터로 접혀
#   뒤따르는 `pkill -f y` 가 검사 밖으로 숨던 구멍. 주석 오판은 «heredoc 아님» 쪽(본문까지 명령으로 검사)으로만 틀리므로 닫힘 방향이다.
#   ⑦ 받는 명령이 ssh·source·`.` 이거나 heredoc 뒤에 `| bash` 류 파이프가 이어지면 ⑤ 와 같이 본문을 명령으로 본다(원격·스트림 셸이 본문을 실행한다).
#   한계: 큰따옴표 속 `echo "<<EOF"` 는 heredoc 으로 보되 표지가 없으면 ④ 로 전부 검사된다. 한 줄 안 둘째 heredoc(`cat <<A <<B`)은 첫째만 본다(종전과 같다).
fold_newlines() {
    awk -v q="'" '
    function find_tag(line,    n, i, c, sq, dq, j, w, e, d) {
        PRE = ""; POST = ""; n = length(line); sq = 0; dq = 0
        for (i = 1; i <= n; i++) { c = substr(line, i, 1)
            if (sq) { if (c == q) sq = 0; continue }
            if (c == "\\") { i++; continue }
            if (c == "\"") { dq = !dq; continue }
            if (c == q && !dq) { sq = 1; continue }
            if (!dq && c == "#" && (i == 1 || substr(line, i - 1, 1) ~ /[ \t;&|(]/)) return ""
            if (c == "$" && substr(line, i + 1, 2) == "((") { d = 2; for (j = i + 3; j <= n && d > 0; j++) { e = substr(line, j, 1); if (e == "(") d++; else if (e == ")") d-- }
                i = j - 1; continue }
            if (c == "<" && substr(line, i + 1, 1) == "<") {
                if (substr(line, i + 2, 1) == "<") { i += 2; continue }
                j = i + 2; if (substr(line, j, 1) == "-") j++
                while (substr(line, j, 1) ~ /[ \t]/) j++
                c = substr(line, j, 1)
                if (c == "\"" || c == q) { e = index(substr(line, j + 1), c); if (e == 0) return ""; w = substr(line, j + 1, e - 1) }
                else { w = substr(line, j); sub(/[ \t;&|()<>].*$/, "", w) }
                gsub(/["\047\\]/, "", w)
                PRE = substr(line, 1, i - 1); sub(/.*[;&|(]/, "", PRE); POST = substr(line, i)
                return w } }
        return "" }
    { L[NR] = $0 }
    END { for (i = 1; i <= NR; i++) { line = L[i]; tag = find_tag(line)
            if (tag != "") {
                for (j = i + 1; j <= NR; j++) { t = L[j]; gsub(/^[ \t]+|[ \t]+$/, "", t); if (t == tag) break }
                if (j <= NR) {
                    if (PRE ~ /(^|[ \t\/])((ba|z|da|k)?sh|ssh|source)([ \t]|$)|(^|[ \t])\.([ \t]|$)/ || POST ~ /\|&?[ \t]*((sudo|doas|env|nohup|nice|timeout|exec|command|xargs)[ \t]+)*([^ \t|]*\/)?(ba|z|da|k)?sh([ \t;&)]|$)/) { out = out line " ; "; for (k = i + 1; k <= j; k++) out = out L[k] " ; " }
                    else { out = out line " "; for (k = i + 1; k < j; k++) out = out L[k] " "; out = out L[j] " ; " }
                    i = j; continue } }
            if (line ~ /[|&;(\\][ \t]*$/) out = out line " "; else out = out line " ; " }
      printf "%s", out }'
}
CMD_RAW=$CMD   # 0.46 허용 목록 판정은 실제로 실행되는 원문도 본다
CMD=$(printf '%s\n%s' "$CMD" "$DECODED" | fold_newlines | sed -E 's/\\([A-Za-z])/\1/g' | sed -E 's/\$\{IFS\}|\$IFS/ /g')   # ${IFS} 는 실행 시 공백 — 정적 검사에도 공백으로 (10라운드 렌즈2)

# ── 0.4 파이프-투-셸은 APPROVED 보다 **앞**에서 한 번만 (10라운드 Grok: APPROVED 복제본엔 래퍼가 없고 0.6 은 조기 exit 0 뒤라 헤더 "APPROVED 무관" 과 어긋났다)
#    `|&` 허용, 래퍼 목록은 0.5 와 공유(xargs·builtin 포함), 셸명 경로 접두 허용. 스트림 실행은 검사 불가 → 파일로 저장 후 검토.
#    인터프리터(python/perl/node/ruby/php)로의 파이프도 같은 원리로 무조건 차단 (11라운드 렌즈2: `curl … | python3` 는 정적 텍스트에 페이로드가 없다)
#    허용은 **`.` 또는 `/` 를 포함한 파일·모듈 피연산자가 있을 때만**(`| python3 -m json.tool`·`| python3 script.py`·`| python3 -W ignore x.py`).
#    12라운드(Grok·렌즈2): 종전 "bare 또는 `-`" 규칙은 `python3 - --config`(`-` 뒤 인자)·`python3 -u`(플래그만)·`python3 /dev/stdin`·`/dev/fd/0`·`/proc/self/fd/0` 을 놓쳤다.
#    두 갈래로 차단: ① 피연산자가 플래그·점/슬래시 없는 단어뿐(`-u`·`-W ignore`·`--no-warnings`·`-`) — 코드 운반 플래그(`-c/-e/-E/-m/-r`·`--eval/--print`)가 나오면
#       코드가 명령문 안에 있으므로 ① 은 멈추고 3.5 가 정적 검사한다(`| python3 -c "import sys; …"` 의 `;` 가 ① 을 끊던 과차단 교정) ② 피연산자 어디든 `-`·stdin 별칭 토큰.
#    알려진 한계(열거 변형): `perl -p`·`node --preserve-symlinks` 처럼 코드 플래그 글자로 시작하는 비코드 플래그만 단 경우는 ① 이 멈춘다.
#    13라운드 Grok: `| python3 >/dev/null`·`| python3 -u >/dev/null 2>&1` 처럼 뒤에 리다이렉션 접미가 붙으면 종결자(`;&|)`·끝) 매칭이 깨졌고 POSIX `--` 를 피연산자로 못 봤다
#    → 무해 리다이렉션(`[n]>/dev/null`·`n>&m`·`&>/dev/null`)을 지운 사본(S_RD)에도 매칭, `--` 는 `-` 와 같은 stdin 토큰으로 취급(`python3 -- x.py` 는 파일 피연산자라 허용).
PIPE_SH='\|&?[[:space:]]*(([^[:space:]|]*/)?(sudo|doas|env|nohup|nice|timeout|exec|command|builtin|xargs)[[:space:]]+([^[:space:]|"'"'"']+[[:space:]]+)*)?([^[:space:]|]*/)?((ba|z|da|k)?sh([[:space:])]|$)|(python[0-9.]*|perl|node|ruby|php)(([[:space:]]+([^[:space:];&|./-][^[:space:];&|./]*|-[^cemEpr-][^[:space:];&|./]*|--(e[^v]|p[^r]|[^ep])[^[:space:];&|./]*|--?))*[[:space:]]*([;&|)]|$)|([[:space:]]+[^[:space:];&|]+)*[[:space:]]+(-([[:space:];&|)]|$)|--[[:space:]]*([;&|)]|$)|(/dev/stdin|/dev/fd/[0-9]+|/proc/(self|[0-9]+)/fd/[0-9]+)([[:space:];&|)]|$))))'
#    따옴표로 감싼 셸명(`| "bash"`)과 프로세스 치환 입력(`bash <(curl …)`)도 같은 스트림 실행 (11라운드 Grok) — 따옴표 문자를 제거한 사본에도 적용
S_UQ=$(printf '%s' "$CMD" | tr -d '"'"'")
S_RD=$(printf '%s' "$S_UQ" | sed -E 's/[0-9]*>>?[[:space:]]*\/dev\/null//g; s/[0-9]*>&[0-9]//g; s/&>[[:space:]]*\/dev\/null//g')
#    `bash < <(curl u)`·`python3 - < <(…)`·`bash -s x < <(…)` 도 같은 경로 (12라운드 Grok): 셸·인터프리터 뒤 임의 토큰 + `[fd]< <(` 까지 트리거.
#    `diff <(a) <(b)`·`done < <(ls)` 는 명령 위치가 셸·인터프리터가 아니라 무관. `python3 x.py < <(cat data)` 같은 데이터 stdin 은 과차단 — 파일로 저장 후 `< file` (fail-closed 수용).
PROCSUB_SH='(^|[[:space:];&|(])(([^[:space:]]*/)?((ba|z|da|k)?sh|python[0-9.]*|perl|node|ruby|php))[[:space:]]+([^[:space:]<]+[[:space:]]+)*([0-9]*<[[:space:]]*)?<\('
if echo "$CMD" | grep -qE "$PIPE_SH" || echo "$S_UQ" | grep -qE "$PIPE_SH" || echo "$S_RD" | grep -qE "$PIPE_SH" || echo "$S_UQ" | grep -qE "$PROCSUB_SH" || echo "$S_RD" | grep -qE "$PROCSUB_SH"; then
    jq -cn --arg r "[쓰기 차단] 파이프-투-셸/인터프리터 (… | bash/sh/python3 …, \"bash\"·<(…) 포함) — # APPROVED 로도 허용되지 않음, 파일로 저장 후 검토" \
        '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: $r}}'
    exit 0
fi
#    제3의 벡터 — 코드가 **인자로 치환**되는 실행 (13라운드 렌즈2): `| xargs python3 -c`(stdin 이 -c 값이 됨)·`xargs -I{} perl -e {}`·`python3 -c "$(curl …)"`·`node -e "$CODE"`·
#    `python3 -c "print('$X')"`(따옴표 접합·변수 삽입). 코드 텍스트가 명령문에 없거나 실행 시점에 바뀌므로 3.5 정적 검사가 원천 불가 → 파이프·APPROVED 무관 무조건 차단.
#    `find … | xargs python3 lint.py`(파일 인자)·`python3 -c 'print(1)'`(리터럴 코드)·`python3 script.py "$f"`(코드 밖 인자) 는 무관.
#    14라운드 Grok: 코드플래그에 **붙여 쓴** 치환(`-c{}`)·빈 따옴표 접합(`-c ""$CODE`)이 종결자 조건 밖이었다 → xargs 문맥은 코드플래그 뒤에 무엇이 오든 deny, DYN 은 `{`·빈 `""`/`''` 접합도 동적 값으로 본다.
#    14라운드 렌즈2: 셸 자신의 `-c` 도 같은 클래스 — `bash -c "$(cat payload)"`·`sh -c "$V"` 는 2단계 재검사가 리터럴만 보므로 페이로드가 안 보인다 → DYN 의 인터프리터 목록에 셸 포함.
#    (`-m` 은 XARGS 에서 제외: `xargs -n1 python3 -m json.tool` 은 모듈 인자이지 코드가 아니다. DYN 의 `-m "$MOD"` 는 여전히 deny)
#    15라운드 Grok: `xargs bash -c < payload`(파이프 없음) 는 XARGS 목록에 셸이 없어 통과 → 셸 포함. 15라운드 렌즈2: `find … -exec sh -c '{}' \;`·`-exec python3 -c '{}'` 는
#    따옴표로 감싼 `{}` 자리표시자 — DYN 에 `'{}'`·`"{}"` 형도 동적 값으로 포함(코드는 실행 시점에 파일명에서 온다).
XARGS_CODE='xargs[[:space:]]+([^[:space:]|]+[[:space:]]+)*([^[:space:]|]*/)?((ba|z|da|k)?sh|python[0-9.]*|perl|node|ruby|php)[[:space:]]+(-[^[:space:]]+[[:space:]]+)*(-[a-zA-Z]*[ceEr]|--eval|--print|-p)'
DYN_CODE='(^|[[:space:];&|(`"'"'"'/])((ba|z|da|k)?sh|python[0-9.]*|perl|node|ruby|php)[[:space:]]+(-[^[:space:]]+[[:space:]]+)*(-[a-zA-Z]*[cemEr]|--eval|--print|-p)[=[:space:]]*(""|'"'"''"'"')*[[:space:]]*(\\["'"'"'])?(\{|["'"'"']\{\}["'"'"']|\$\(|`|\$[A-Za-z_{@*!#?0-9-]|"([^"\\]|\\.)*(\$\(|\$[A-Za-z_{@*!#?0-9-]|`|"[^[:space:];&|)])|'"'"'[^'"'"']*'"'"'[^[:space:];&|)])'
if echo "$S_UQ" | grep -qE "$XARGS_CODE" || echo "$S_RD" | grep -qE "$XARGS_CODE" || echo "$CMD" | grep -qE "$DYN_CODE"; then
    jq -cn --arg r "[쓰기 차단] 인터프리터 코드가 인자로 치환·확장됨 (xargs … python3 -c / -c \"\$(…)\" / -e \"\$VAR\" / 따옴표 접합) — 정적 검사 불가, # APPROVED 로도 허용되지 않음. 코드를 파일로 저장 후 실행" \
        '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: $r}}'
    exit 0
fi

# ── 0.45 명령 위치 판정 공통 재료 (2026-09-08 검수 교정) ────────
# 따옴표 **안**은 셸 문법이 아니다. 인용 문자열을 불투명 토큰 QQ 로 접되 `"$x"` 처럼 변수로 시작하는 것만
# `$x` 로 남겨 7라운드 사례(`x=rm; "$x" -rf …`)가 계속 명령 위치 변수로 보이게 한다.
collapse_quotes() {
    sed -E "s/'\\\$([A-Za-z_{(@*!#?0-9-])[^']*'/\$\1/g; s/'[^']*'/QQ/g" \
        | sed -E 's/"\$([A-Za-z_{(@*!#?0-9-])[^"]*"/$\1/g; s/"[^"]*"/QQ/g'
}
# ── 0.46 읽기 전용 허용 목록 판정 (2026-10-06, 머리 주석 참조) ────────
# 입력 두 줄: 1행 = 실행되는 원문(판정만), 2행 = 접힌 검사 문자열 CMD(판정 + 정리본). 둘 다 통과해야 "OK<정리본>" 을 낸다.
# 토크나이저는 실제 셸 따옴표 규칙대로 읽는다: 작은따옴표 안은 불투명, 큰따옴표 안은 글자·$이름·${이름}·$(…)(같은 규칙으로 재귀)만.
# 애매하면 전부 거짓(FAIL): 따옴표 밖 백슬래시·백틱·<<·<(·>(·$((·{ }·( ·& 단독·# 주석·! · case/while 등 키워드 · 대문자 이름 대입 · 대입 접두.
# 조건부 명령(printf·date·sort·rg·sed·git·test·[)은 인자에 $ 전개가 있으면 거짓이다(단어 분리로 위험 플래그가 생길 수 있다).
# GNU getopt 는 옵션을 뒤로도 받고 긴 옵션 약어(`sort --out=f`)도 받으므로, 위험 옵션은 위치 무관·약어 포함으로 본다(badlong).
# test/[ 의 -v·-R 은 배열 첨자 산술(`a[$(…)]`)을 실행하므로 거짓. rg --hostname-bin 은 명령을 실행하므로 --pre 와 같이 거짓.
allowlist_scan() {
    awk -v q="'" '
    function fail() { FAIL = 1; return 0 }
    function ch(k) { return substr(S, k, 1) }
    function isdelim(c) { return c == "" || c == " " || c == "\t" || c == ";" || c == "&" || c == "|" || c == ")" }
    function push(t, v) { TT[NT] = t; TV[NT] = v; TPL[NT] = 0; TG[NT] = 0; TD[NT] = 0; TSQ[NT] = 0; TAS[NT] = ""; NT++ }
    function lex_list(depth,    base, c, c2) {
        base = NT
        while (!FAIL) {
            while (ch(I) == " " || ch(I) == "\t") { OUT = OUT ch(I); I++ }
            if (I > N) { if (depth > 0) fail(); break }
            c = ch(I); c2 = ch(I + 1)
            if (c == ")") { if (depth == 0) fail(); break }
            if (c == ";") { if (c2 == ";" || c2 == "&") fail(); else { push("OP", ";"); OUT = OUT c; I++ } continue }
            if (c == "&") { if (c2 != "&") fail(); else { push("OP", "&&"); OUT = OUT "&&"; I += 2 } continue }
            if (c == "|") { if (c2 == "&") fail(); else if (c2 == "|") { push("OP", "||"); OUT = OUT "||"; I += 2 } else { push("OP", "|"); OUT = OUT c; I++ } continue }
            if (c == "<") { lex_rin(); continue }
            if (c == ">") { if (substr(S, I, 10) == ">/dev/null" && isdelim(ch(I + 10))) { push("RO", ""); OUT = OUT ">/dev/null"; I += 10 } else fail(); continue }
            lex_word(depth)
        }
        if (!FAIL) { P = base; E = NT; if (parse_list("") != "EOF") fail() }
        NT = base
        return !FAIL
    }
    function lex_rin(    c2, rest, t, len) {
        c2 = ch(I + 1)
        if (c2 == "<" || c2 == "(" || c2 == "&" || c2 == ">") return fail()
        OUT = OUT "<"; I++
        while (ch(I) == " " || ch(I) == "\t") { OUT = OUT ch(I); I++ }
        rest = substr(S, I)
        if (match(rest, /^"[$][{][A-Za-z_][A-Za-z0-9_]*[}]"/) || match(rest, /^"[$][A-Za-z_][A-Za-z0-9_]*"/) || match(rest, /^[$][{][A-Za-z_][A-Za-z0-9_]*[}]/) || match(rest, /^[$][A-Za-z_][A-Za-z0-9_]*/) || match(rest, /^[A-Za-z0-9_.\/~+,:=%@-]+/)) len = RLENGTH
        else return fail()
        t = substr(rest, 1, len)
        if (!isdelim(ch(I + len)) || t ~ /[$][{]?IFS([}"]|$)/) return fail()
        sub(/[$]/, "_", t)
        OUT = OUT t; I += len; push("RI", t)
        return 1
    }
    function lex_word(depth,    start, c, j, val, plain, glob, dyn, nsq, nlit, lead, ld, w) {
        start = I; plain = 1
        while (!FAIL) {
            c = ch(I)
            if (isdelim(c)) break
            w = substr(S, start, I - start)
            if (c == "<") { if (w ~ /^[0-9]+$/) return fail(); break }
            if (c == ">") {
                if (w == "2" && substr(S, I, 10) == ">/dev/null" && isdelim(ch(I + 10))) { OUT = OUT ">/dev/null"; I += 10; push("RO", ""); return 1 }
                if (w == "2" && substr(S, I, 3) == ">&1" && isdelim(ch(I + 3))) { OUT = OUT ">&1"; I += 3; push("RO", ""); return 1 }
                return fail()
            }
            if (c == q) { j = index(substr(S, I + 1), q); if (!j) return fail(); val = val substr(S, I + 1, j - 1); OUT = OUT q q; I += j + 1; plain = 0; nsq++; ld = 1; continue }
            if (c == "\"") { if (!lex_dq(depth)) return 0; val = val RETV; if (RETD) dyn = 1; plain = 0; nlit++; ld = 1; continue }
            if (c == "$") { if (!lex_dollar(depth)) return 0; val = val "$"; dyn = 1; plain = 0; nlit++; ld = 1; continue }
            if (c == "(" || c == "\\" || c == "`" || c == "{" || c == "}" || c == "!" || (c == "#" && I == start) || c ~ /[[:cntrl:]]/) return fail()
            if (c == "*" || c == "?" || c == "[") glob = 1
            val = val c; OUT = OUT c; nlit++; if (!ld) lead = lead c; I++
        }
        if (FAIL) return 0
        push("W", val); TPL[NT - 1] = plain; TG[NT - 1] = glob; TD[NT - 1] = dyn; TSQ[NT - 1] = (nsq == 1 && nlit == 0)
        if (match(lead, /^[A-Za-z_][A-Za-z0-9_]*=/)) TAS[NT - 1] = substr(lead, 1, RLENGTH - 1)
        return 1
    }
    function lex_dq(depth,    c, v, d) {
        OUT = OUT "\""; I++
        while (1) {
            c = ch(I)
            if (c == "") return fail()
            if (c == "\"") { OUT = OUT c; I++; break }
            if (c == "\\" || c == "`") return fail()
            if (c == "$") { if (!lex_dollar(depth)) return 0; v = v "$"; d = 1; continue }
            v = v c; OUT = OUT ((c ~ /[<>();&|]/) ? "_" : c); I++
        }
        RETV = v; RETD = d; return 1
    }
    function lex_dollar(depth,    c2, rest, name) {
        c2 = ch(I + 1)
        if (c2 == "(") {
            if (ch(I + 2) == "(" || depth >= 3) return fail()
            OUT = OUT "$("; I += 2
            if (!lex_list(depth + 1)) return 0
            if (ch(I) != ")") return fail()
            OUT = OUT ")"; I++; return 1
        }
        rest = substr(S, I + 1)
        if (c2 == "{") { if (!match(rest, /^[{][A-Za-z_][A-Za-z0-9_]*[}]/)) return fail() }
        else if (!match(rest, /^[A-Za-z_][A-Za-z0-9_]*/)) return fail()
        name = substr(rest, 1, RLENGTH)
        if (name == "IFS" || name == "{IFS}") return fail()
        OUT = OUT "$" name; I += 1 + RLENGTH; return 1
    }
    function is_kw(k, set) { return k < E && TT[k] == "W" && TPL[k] && index(set, " " TV[k] " ") > 0 }
    function parse_list(terms,    st) {
        st = "A"
        while (!FAIL) {
            if (P >= E) { if (terms == "" && st == "B") return "EOF"; return fail() }
            if (terms != "" && is_kw(P, terms)) { if (st == "B") return TV[P]; return fail() }
            if (!parse_pipeline()) return fail()
            if (P >= E) { if (terms == "") return "EOF"; return fail() }
            if (TT[P] != "OP") return fail()
            st = (TV[P] == ";") ? "B" : "A"; P++
        }
        return fail()
    }
    function parse_pipeline() {
        if (!parse_command()) return 0
        while (P < E && TT[P] == "OP" && TV[P] == "|") { P++; if (!parse_command()) return 0 }
        return 1
    }
    function parse_command(    v, r) {
        if (P >= E || TT[P] != "W") return fail()
        if (TPL[P] && (TV[P] in RESERVED)) {
            v = TV[P]
            if (v == "for") r = parse_for(); else if (v == "if") r = parse_if(); else return fail()
            if (!r) return 0
            while (P < E && (TT[P] == "RO" || TT[P] == "RI")) P++
            return 1
        }
        return parse_simple()
    }
    function parse_for() {
        P++
        if (!(P < E && TT[P] == "W" && TPL[P] && TV[P] ~ /^[a-z_][a-z0-9_]*$/)) return fail()
        P++
        if (!is_kw(P, " in ")) return fail()
        P++
        while (P < E && TT[P] == "W") P++
        if (!(P < E && TT[P] == "OP" && TV[P] == ";")) return fail()
        P++
        if (!is_kw(P, " do ")) return fail()
        P++
        if (parse_list(" done ") != "done") return fail()
        P++
        return 1
    }
    function parse_if(    r) {
        P++
        if (parse_list(" then ") != "then") return fail()
        P++
        r = parse_list(" elif else fi ")
        while (r == "elif") {
            P++
            if (parse_list(" then ") != "then") return fail()
            P++
            r = parse_list(" elif else fi ")
        }
        if (r == "else") { P++; r = parse_list(" fi ") }
        if (r != "fi") return fail()
        P++
        return 1
    }
    function parse_simple(    nw, k, i, na) {
        nw = 0
        while (P < E && TT[P] != "OP") { if (TT[P] == "W") W_[++nw] = P; P++ }
        if (nw == 0) return fail()
        k = W_[1]
        if (TAS[k] != "") { if (nw > 1 || TAS[k] !~ /^[a-z_][a-z0-9_]*$/) return fail(); return 1 }
        if (!TPL[k] || (TG[k] && TV[k] != "[")) return fail()
        na = 0
        for (i = 2; i <= nw; i++) { na++; A[na] = TV[W_[i]]; AD[na] = TD[W_[i]]; ASQ[na] = TSQ[W_[i]]; APL[na] = TPL[W_[i]] && !TG[W_[i]] }
        if (!check_cmd(TV[k], na)) return fail()
        return 1
    }
    function badlong(v, list,    nm, n, i, L) {
        nm = substr(v, 3); sub(/=.*/, "", nm)
        if (nm == "") return 1
        n = split(list, L, " ")
        for (i = 1; i <= n; i++) if (index(L[i], nm) == 1 || index(nm, L[i]) == 1) return 1
        return 0
    }
    function sed_form(v,    d, j, n, c, cnt, last) {
        if (index(v, "$")) return 0
        if (v ~ /^[0-9]+p$/ || v ~ /^[0-9]+,[0-9]+p$/ || v ~ /^\/([^\/\\]|\\.)*\/p$/) return 1
        if (substr(v, 1, 1) != "s") return 0
        d = substr(v, 2, 1)
        if (d == "" || d ~ /[A-Za-z0-9\\]/ || d ~ /[[:space:][:cntrl:]]/) return 0
        n = length(v); cnt = 0
        for (j = 2; j <= n; j++) { c = substr(v, j, 1); if (c == "\\") { j++; continue } if (c == d) { cnt++; last = j } }
        return cnt == 3 && substr(v, last + 1) ~ /^[gpI0-9]*$/
    }
    function check_cmd(cmd, na,    i, v, script) {
        if (cmd in BASE) return 1
        if (cmd == "bash" || cmd == "sh") return na >= 1 && APL[1] && A[1] !~ /^-/ && A[1] ~ /[.]sh$/
        if (cmd == "python3") return na >= 1 && APL[1] && A[1] !~ /^-/ && A[1] ~ /[.]py$/
        if (cmd == "uv") return na >= 3 && APL[1] && A[1] == "run" && APL[2] && (A[2] == "python" || A[2] == "python3") && APL[3] && A[3] !~ /^-/ && A[3] ~ /[.]py$/
        for (i = 1; i <= na; i++) if (AD[i]) return 0
        if (cmd == "printf") { for (i = 1; i <= na; i++) if (A[i] ~ /^-v/) return 0; return 1 }
        if (cmd == "test" || cmd == "[") { for (i = 1; i <= na; i++) if (A[i] == "-v" || A[i] == "-R") return 0; return 1 }
        if (cmd == "date") {   # 피연산자가 + 형식이 아니면 GNU date 는 시계를 설정하려 한다(MMDDhhmm) — 옵션 값(-d·-f·-r 다음 낱말)만 건너뛴다
            for (i = 1; i <= na; i++) {
                v = A[i]
                if (v == "-d" || v == "-f" || v == "-r" || v == "--date" || v == "--file" || v == "--reference") { i++; continue }
                if (v ~ /^--/) { if (badlong(v, "set")) return 0 }
                else if (v ~ /^-/) { if (v ~ /s/) return 0 }
                else if (v !~ /^[+]/) return 0
            }
            return 1
        }
        if (cmd == "sort") { for (i = 1; i <= na; i++) { v = A[i]; if (v ~ /^--/) { if (badlong(v, "output compress-program")) return 0 } else if (v ~ /^-.*o/) return 0 } return 1 }
        if (cmd == "rg") { for (i = 1; i <= na; i++) if (A[i] ~ /^--/ && badlong(A[i], "pre hostname-bin")) return 0; return 1 }
        if (cmd == "sed") {
            for (i = 1; i <= na; i++) {
                v = A[i]
                if (v ~ /^-./) { if (v !~ /^-[nErsuz]+$/) return 0; continue }
                if (!script) { if (!ASQ[i] || !sed_form(v)) return 0; script = 1 }
            }
            return script
        }
        if (cmd == "git") {
            if (na < 1 || !APL[1] || !(A[1] in GITSUB)) return 0
            for (i = 2; i <= na; i++) {
                v = A[i]
                if (v == "--") continue
                if (v ~ /^--/) { if (badlong(v, "output open-files-in-pager ext-diff exec")) return 0 }
                else if (v == "-c" || v ~ /^-[^-]*O/) return 0
            }
            return 1
        }
        return 0
    }
    BEGIN {
        split("grep egrep fgrep wc cut head tail tr cat ls echo true false basename dirname realpath readlink stat du df nl column comm diff cmp md5sum sha256sum jq pwd cd", t, " ")
        for (k in t) BASE[t[k]] = 1
        split("for if then elif else fi do done case esac while until select function in time coproc { } ! [[ ]]", t, " ")
        for (k in t) RESERVED[t[k]] = 1
        split("log show diff status rev-parse ls-files blame grep cat-file describe shortlog ls-tree", t, " ")
        for (k in t) GITSUB[t[k]] = 1
    }
    { S = $0; N = length(S); I = 1; OUT = ""; FAIL = 0; NT = 0
      if (N == 0) FAIL = 1; else lex_list(0)
      if (FAIL) BAD = 1
      if (NR == 2 && !BAD) print "OK" OUT }'
}
SAN=$CMD   # 정리본. 허용 목록을 통과하지 못하면 원문 그대로다(원본과 같은 판정)
case $CMD_RAW in
    *$'\n'*|*$'\r'*) ;;
    *"'"*|*'"'*|*'<'*|*'`'*|*'$('*)
        if [ "${#CMD_RAW}" -le 2000 ]; then
            SCAN=$(printf '%s\n%s\n' "$CMD_RAW" "$CMD" | allowlist_scan)
            case $SCAN in OK*) SAN=${SCAN#OK} ;; esac
        fi ;;
esac
S_CMDPOS=$(printf '%s' "$SAN" | collapse_quotes)
# 실행 래퍼 뒤에서 건너뛰는 것은 옵션·대입·수치 피연산자뿐이다(`timeout 5`·`env A=B`·`sudo -n`).
# 종전엔 따옴표 없는 토큰을 무제한 건너뛰어 `env cat "$PWD/x"` 의 `cat` 다음 인자가 명령 위치로 오인됐다.
# 인자를 받는 짧은 옵션(`sudo -u u`·`exec -a n`)만 그 값까지 한 쌍으로 건너뛴다.
# 한계: 옵션 값이 아닌 임의 피연산자 뒤의 변수(`sudo x "$v"`)는 명령 위치로 보지 않는다. 오탐 제거를 택한 지점이다.
WRAP_SKIP='(([^[:space:]]*/)?(exec|command|builtin|env|nohup|nice|timeout|xargs|sudo|doas)[[:space:]]+(-[uagCDhpri][[:space:]]+[^-[:space:]][^[:space:]]*[[:space:]]+|-[^[:space:]]*[[:space:]]+|[A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+|[0-9][^[:space:]]*[[:space:]]+)*)?'
# 명령 위치 경계 (2026-10-01 감사): `;&|(` 와 줄 시작뿐 아니라 셸 예약어(do·then·else·elif·if·while·until) 뒤도 명령 위치다.
#   `for f in a; do pkill -f x; done`·`if …; then $x; fi` 의 첫 명령이 경계 밖이라 아래 검사들이 빠지던 구멍을 닫는다.
#   예약어 뒤 공백을 요구하므로 `--if`·`endif` 같은 낱말 속 글자는 걸리지 않는다. 한계: `echo then $x` 처럼 예약어 낱말이 인자 앞에 놓인 문장은 오탐한다(드묾).
RW='(do|then|else|elif|if|while|until)'
CMDLEAD='(^[[:space:]]*|[;&|(][[:space:]]*|(^|[[:space:];&|(])'"$RW"'[[:space:]]+)'
CMDPOS_VAR="$CMDLEAD""$WRAP_SKIP"'\$([A-Za-z_{(@*!#?-]|[0-9])'

# ── 0. 사용자 승인 마커 ────────────────────────────────────────
# 첫 줄이 "# APPROVED" 이면 사용자가 명시적으로 승인한 명령 → 무조건 허용 (무출력 통과)
# 정확 매칭 (2026-07-18 Codex): '^# APPROVED' prefix는 '# APPROVED_X' 류를 오승인 →
# 뒤에 공백 또는 줄끝만 허용(`# APPROVED`·`# APPROVED 사유`는 통과, `# APPROVED_X`는 불통).
# 승인 출처 검증 (2026-09-14 개정): 종전엔 «훅이 검증할 수 없다»(5라운드 Codex)며 감사 로그 사후 대조에만 맡겼는데,
# 그 사후 대조가 실제로 우회를 잡아냈다 — 파괴 명령 30건 중 6건이 승인 없이 붙었고 09-11 18:18 건은 주석이 인용한
# 사용자 발화가 prompts.jsonl 에 아예 없었다(_audit/loop-audit-20260914.md §3). 그래서 검증을 사전으로 올린다(아래 인용 검사).
# 감사 로그는 그대로 남긴다 — 인용 검사를 통과한 사용까지 포함해 harness-audit·사용자가 사후 대조한다.
if printf '%s\n' "$FIRST" | grep -qE '^# APPROVED([[:space:]]|$)'; then
    # 감사 원장 자체를 겨누는 명령은 APPROVED 로도 통과 불가 (6라운드 Grok: `# APPROVED` + `rm _audit/approved-commands.log` 로 원장 소거)
    # 동사 무관 (7라운드 Grok: cp /dev/null·python -c open('w')·ln 으로 우회) — 원장 경로를 언급하는 APPROVED 명령은 전부 거부(읽기는 APPROVED 없이 하면 된다)
    if echo "$CMD" | grep -qE '_audit/|approved-commands\.log|agent-spawn\.log|_audit/history\.md|history\.md'; then
        jq -cn --arg r "[쓰기 차단] 감사 원장(_audit/) 경로가 든 명령은 # APPROVED 로 실행할 수 없음(읽기는 APPROVED 없이, 정리는 사용자가 터미널에서 직접)" \
            '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: $r}}'
        exit 0
    fi
    # APPROVED 는 **리터럴 경로의 평범한 셸 쓰기**에만 (8라운드 Grok: find -delete·chr() 조립·디코더 파이프로 원장 경로를 숨기면 조기 exit 0 이 전 검사를 건너뛴다)
    # 9라운드 Grok: find | xargs rm·-execdir·명령 위치 브레이스/글롭·래퍼 뒤 변수도 "단순 리터럴" 이 아니다
    # 2026-09-08 검수: ① 래퍼 뒤 인자를 명령 위치로 보던 오탐을 WRAP_SKIP 으로 좁히고
    #   ② 마커를 뗀 사본(S_APPR_POS)과 원문($CMD)을 뒤섞어 보던 것을 정리했다. `^` 앵커가 걸린 명령 위치 변수 검사는
    #   마커가 접두로 남은 원문에선 발화하지 못했다(헤더 27줄의 탈출구 약속과 어긋난 지점).
    # ③ awk 는 순수 텍스트 처리 용도가 대부분이라 인터프리터 거부 목록에서 뺐다. 대신 awk 자신의 쓰기·실행 형태만 남긴다.
    S_APPR_POS=$(printf '%s' "${CMD#"$FIRST"}" | collapse_quotes)   # 마커 줄을 떼어 다음 토큰이 명령 위치가 되게(접힌 CMD 는 마커가 접두)
    if echo "$S_APPR_POS" | grep -qE '(^[[:space:]]*|[;&|(][[:space:]]*)'"$WRAP_SKIP"'[^[:space:];&|(]*(\{[^{}[:space:]]*,[^{}[:space:]]*\}|\[[^][[:space:]]+\]|[*?])[^[:space:];&|]*' \
       || echo "$S_APPR_POS" | grep -qE "$CMDPOS_VAR" \
       || echo "$CMD" | grep -qE -- '-delete|-exec(dir)?[[:space:]]|(^|[[:space:];&|(`/])(xargs|python[0-9.]*|perl|node|ruby|php|base64|xxd|openssl|uudecode)([[:space:]]|$)|\|[[:space:]]*([^[:space:]|]*/)?(ba|z|da|k)?sh([[:space:]]|$)|\$\(|`|<\(|\\x[0-9A-Fa-f]|\$'"'"'|(^|[[:space:];&|(])(eval|source|\.)[[:space:]]' \
       || echo "$CMD" | grep -qE '(^|[[:space:];&|(]|/)(g|m|n)?awk[[:space:]][^;&|]*(print(f)?[^;|&]*[[:space:]]>>?|system[[:space:]]*\()'; then
        jq -cn --arg r "[쓰기 차단] # APPROVED 는 리터럴 경로의 단순 셸 명령에만 허용 — 인터프리터·디코더·find -delete/-exec·치환·변수·이스케이프가 섞인 명령은 사용자가 터미널에서 직접" \
            '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: $r}}'
        exit 0
    fi
    # 인용 실재 검사 (2026-09-14) — 승인의 **출처**를 훅이 직접 본다.
    #   첫 줄 주석이 사용자 발화를 «…» 또는 "…" 로 인용해야 하고, 그 인용이 최근 프롬프트 로그 400줄 안에
    #   부분 문자열로 실재해야 통과한다. 에이전트가 스스로 붙인 승인은 인용할 사용자 말이 없어 여기서 막힌다.
    #   부분 문자열로 비교하는 이유: 로그는 프롬프트 앞 2000자만 보관한다(prompt-log.sh, 2026-09-14 에 200→2000). 긴 인용은 앞 40자로 자르는 것은 그대로다(부분 문자열 대조 안전폭).
    #   추출·절단을 jq 로 하는 이유: 이 훅은 LC_ALL=C 라 셸 정규식이 «»(다바이트)를 문자로 다루지 못한다. jq 는 UTF-8 문자 단위다.
    #   APPROVED_PROMPT_LOG 는 회귀 테스트가 실제 로그 대신 시험용 로그를 물리는 seam 이다.
    #   최소 길이 8자 (2026-09-14 재감사 B5): 길이 하한이 없어 «지» 한 글자 인용이 아무 프롬프트에나
    #   부분 문자열로 맞아떨어졌다(`# APPROVED 사용자 «지»` + `git push origin main` 이 두 훅 모두 통과).
    #   한두 글자는 «사용자가 그 명령을 승인했다»는 증거가 되지 못한다. 길이는 바이트가 아니라 문자로 센다 —
    #   이 훅은 LC_ALL=C 라 셸이 한글을 3바이트로 보므로 jq(UTF-8 문자 단위)로 재는 것이다.
    APPROVED_QUOTE=$(jq -rn --arg s "$FIRST" '
        ((($s | capture("«(?<q>[^»]*)»").q) // ($s | capture("\"(?<q>[^\"]*)\"").q)) // "")
        | gsub("^\\s+|\\s+$"; "") | gsub("\\s+"; " ")
        | if length >= 20 then .[0:40] else . end' 2>/dev/null)
    APPROVED_QLEN=$(jq -rn --arg q "$APPROVED_QUOTE" '$q | length' 2>/dev/null)
    if [ -n "$APPROVED_QUOTE" ] && [ "${APPROVED_QLEN:-0}" -lt 8 ]; then
        jq -cn --arg r "[쓰기 차단] APPROVED 인용이 너무 짧음(8자 미만) — 짧은 인용은 아무 프롬프트에나 맞아 승인 증거가 되지 못합니다. 사용자 승인 발화를 8자 이상 그대로 인용하세요" \
            '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: $r}}'
        exit 0
    fi
    # 말맛 검사 (2026-09-14 재감사 D1) — 길이만 재면 «/home/ds»·«────────» 같은 경로·기호 조각이
    #   8자를 채워 통과했다. 프롬프트에는 경로도 구분선도 실재하므로 로그 대조도 함께 뚫린다.
    #   승인 발화라면 말이 들어 있어야 한다: 한글 음절 2연속 또는 영문 단어 3자 이상.
    #   경로 조각은 «home» 처럼 영문 단어를 품어 첫 조건을 통과하므로, 공백 없는 슬래시 경로 모양은
    #   따로 배제한다. 판정을 jq 로 하는 이유는 위와 같다(LC_ALL=C 셸 정규식은 한글을 문자로 못 셈).
    APPROVED_QWORDY=$(jq -rn --arg q "$APPROVED_QUOTE" '
        (($q | test("[가-힣]{2,}")) or ($q | test("[A-Za-z]{3,}")))
        and (($q | test("^[A-Za-z0-9/._~-]*/[A-Za-z0-9/._~-]*$")) | not)' 2>/dev/null)
    if [ -n "$APPROVED_QUOTE" ] && [ "$APPROVED_QWORDY" != "true" ]; then
        jq -cn --arg r "[쓰기 차단] APPROVED 인용이 승인 발화가 아님(경로·기호·숫자 조각) — 한글 2자 이상 또는 영문 단어가 든 사용자 승인 발화를 그대로 인용하세요" \
            '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: $r}}'
        exit 0
    fi
    if [ -z "$APPROVED_QUOTE" ] || ! tail -n 400 "${APPROVED_PROMPT_LOG:-$HOME/.claude/_evolve/prompts.jsonl}" 2>/dev/null \
        | jq -rR 'fromjson? | .prompt // empty' 2>/dev/null | grep -qF -- "$APPROVED_QUOTE"; then
        jq -cn --arg r "[쓰기 차단] APPROVED 인용이 사용자 프롬프트 로그에 없음 — 첫 줄을 '# APPROVED 사용자 «승인 발화 그대로»' 형태로 다시 쓰세요(인용 없는 APPROVED 는 통과하지 않습니다)" \
            '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: $r}}'
        exit 0
    fi
    mkdir -p "$HOME/.claude/_audit" 2>/dev/null
    # 원문 전체 sha256·바이트 수 + 앞 300자 (잘림으로 대조 불가하던 결함 교정)
    printf '%s\t%s\t%s\t%s\n' "$(date -Iseconds)" "$(printf '%s' "$CMD" | sha256sum | cut -c1-64)" "$(printf '%s' "$CMD" | wc -c)" "$(echo "$CMD" | tr '\n\t' '  ' | cut -c1-300)" >> "$HOME/.claude/_audit/approved-commands.log" 2>/dev/null
    exit 0
fi

BLOCK=false
REASON=""

# 무해한 리다이렉션 제거 (stdin → stdout)
strip_harmless() {
    sed -e 's|[12]*>/dev/null||g' -e 's|2>&1||g' -e 's|1>&2||g' -e 's|>&[012]||g' -e 's|&>[ ]*/dev/null||g'
}
# git 서브명령 토큰 중화 — 오탐(git rm 등)만 제거, 나머지 검사는 계속 (조기 허용 금지)
neutralize_git() {
    sed -E 's/(^|[;&|(][[:space:]]*|^[[:space:]]*)git[[:space:]]+[[:alnum:]._-]+/\1__git__/g'
}
# `-K`/`--config`(약어 `--conf`)는 설정 파일·stdin 안의 `output=` 으로 파일을 쓰는데 내용을 검사할 수 없어 무조건 차단한다 (2026-10-17 Codex 5차). 소문자 `-k`(인증서 무시)는 별개라 통과.
# curl 이 파일을 쓰는 옵션 (짧은 묶음·`=` 형·긴 옵션 접두 약어). check_write_patterns 와 따옴표 제거본 검사가 함께 쓴다.
CURL_OPT_RX='[[:space:]](-[sSLfkvinNqgZ46JRaBGIlMpVj#0-9]*[oOcDK]|--(output|out|remote-n|cookie-j|dump-h|stderr|trace|etag-s|libcurl|hsts|alt-svc|conf)[a-z-]*([[:space:]=]|$))'
# 쓰기 패턴 검사 — $1: 검사 대상, $2: 컨텍스트 라벨
# 경계 클래스에 따옴표 포함 — 원문 재검사 시 인용부호 직후 명령까지 탐지
check_write_patterns() {
    local T="$1" CTX="$2"
    local B="[[:space:];&|(\"'\`]"   # 백틱 포함 — `rm x` 직후 명령 경계 누락 교정 (2026-08-15 감사 회귀 테스트 발견)
    # 명령 위치 경계 (2026-09-08 qa 독립 검수) — 아래 «신규» 토큰(patch/zip/7z/wget/패키지 관리자/원격 복사/환경 상태)에만 쓴다.
    #   $B 는 앞이 공백이기만 하면 잡아 `grep -rn patch rules/`·`wc -l wget notes` 같은 **낱말**까지 쓰기로 봤다.
    #   그래서 셋을 결합한다: ① 시작·구분자(`;&|(`)·따옴표 직후 ② 실행 래퍼 건너뛰기(WRAP_SKIP — env·nohup·timeout·xargs·sudo…)
    #   ③ 경로 접두(`/usr/bin/wget`). 래퍼·경로로 감싼 우회(`nohup wget URL`·`echo x | xargs pkill -f`)가 ②③ 으로 닫힌다.
    #   기존 rm/mv/cp 류의 $B 경계는 그대로 둔다 — 오래된 규칙의 판정을 바꾸지 않기 위해서다.
    local EB="(^[[:space:]]*|[;&|(\"'\`][[:space:]]*|(^|[[:space:];&|(\"'\`])${RW}[[:space:]]+)$WRAP_SKIP([^[:space:]]*/)?"   # 예약어 뒤(do·then·else…)도 명령 위치 — CMDLEAD 주석 참조
    echo "$T" | grep -qE '>{1,2}' && BLOCK=true && REASON="파일 쓰기 리다이렉션 (> 또는 >>)${CTX}"
    # 경로 접두(/bin/rm 등)·추가 writer(touch) 탐지 강화 (2026-07-18 Codex). mkdir는 제외 —
    # 벤치·스테이징에서 mkdir -p가 상시 사용되는 benign 디렉토리 생성이라 차단 시 워크플로 파손.
    echo "$T" | grep -qE "(^|$B|/)(rm|rmdir|mv|cp|dd|truncate|shred|touch|ln|install|rsync|unzip|unrar|gunzip|bunzip2|unxz|xz|gzip|bzip2)[[:space:]]" \
        && BLOCK=true && REASON="파일 조작 명령 (rm/mv/cp/dd/touch/ln/rsync/압축해제 등)${CTX}"
    # 외부 검수 폴더로 «고른 소스만» 뽑는 추출은 예외다 (2026-09-08 사용자 지시).
    #   왜 여는가: codex·grok 에 저장소를 통째로 겨누면 그 도구가 .env·가중치·민감 자료까지
    #     닿는다(2026-08-25 실사고). 정해진 절차는 «추적 파일 중 검토에
    #     필요한 소스만 교환 폴더로 뽑고 그쪽을 작업 루트로 못박기» 이고(codex-model-gate §0-3),
    #     그 절차에서 파일을 만드는 동작은 이 추출 하나뿐이다. 막아 두면 절차를 못 지켜
    #     오히려 저장소를 직접 겨누는 쪽으로 몰린다.
    #   좁히는 조건 셋을 모두 만족할 때만 통과시킨다. 하나라도 어긋나면 종전대로 차단이다.
    #     ① 입력이 git archive 다 — 임의 tarball 을 푸는 길은 열리지 않는다
    #     ② 푸는 자리가 ~/codex-exchange 또는 ~/grok-exchange 아래다
    #     ③ 이 함수의 나머지 검사(rm·cp·ln·리다이렉션 등)는 그대로 돈다
    #   ★검사 대상은 $T 가 아니라 원문 $CMD 다. $T 는 neutralize_git 을 거쳐 «git archive» 가
    #     «__git__» 으로 바뀐 뒤라 여기서는 git 여부를 알 수 없다(2026-09-08 실측으로 확인).
    # 2026-10-01 감사: 종전엔 «git archive 가 명령 어디든 있고 tar … -C <교환폴더>/ 가 어디든 있으면» 이 검사 전체를 껐다.
    #   접두 일치라 `-C ~/codex-exchange/../etc` 가 통과했고, `…; tar xf evil.tar -C /` 처럼 뒤따르는 **별도 추출**도 검사받지 못했다.
    #   그래서 예외를 `git archive … | tar … -C <교환폴더>/…` **한 구문**으로 좁힌다: ① 그 구문에 `..` 가 없고 ② `-C` 가 하나뿐이며
    #   ③ 그 구문을 떼어낸 나머지에 다른 tar 추출이 없을 때만 통과한다(③ 은 따옴표 속 페이로드까지 보려고 따옴표 내용 제거본·따옴표 문자 제거본 둘 다 검사 — fail-closed).
    TAR_X_RE="(^|$B|/)tar[[:space:]]+([A-Za-z]*x[A-Za-z]*([[:space:]]|$)|([^;&|]*[[:space:]])?(-[A-Za-z]*x[A-Za-z]*([[:space:]]|$)|--(extract|get)([[:space:]=]|$)))"
    SAFE_RX="(^|[[:space:];&|(])git[[:space:]]+archive[[:space:]][^;&|]*\|[[:space:]]*tar[[:space:]][^;&|]*-C[[:space:]]+[\"']?(~|$HOME)/(codex|grok)-exchange/[^[:space:];&|\"']*"   # 경로 토큰에서 멈춘다: 검사 문자열은 «원문 + 디코드본» 이어붙임이라 뒤따르는 `[^;&|]*` 는 다음 복제본의 git archive 까지 삼킨다
    SAFE_ARCHIVE_EXTRACT=false
    SAFE_STMTS=$(echo "$CMD" | grep -oE "$SAFE_RX")
    #   2026-10-01 P6 검수: 경로를 바꾸는 tar 옵션(`--transform`·`-P`·`--absolute-names`·`--one-top-level`, GNU 는 고유 접두 약어도 받는다)이
    #   명령 어디든 있으면 «..» 없는 -C 경로 검사가 무의미해지므로 예외를 거둔다(일반 tar 추출 차단으로 되돌아간다. 명령 전체를 보는 보수 판정).
    TAR_PATHOPT_RE='(^|[[:space:]])(--(tr|xf|ab|on)[a-z-]*([=[:space:]]|$)|-[A-Za-z]*P[A-Za-z]*([[:space:]]|$)|tar[[:space:]]+[A-Za-z]*P[A-Za-z]*([[:space:]]|$))'
    if [ -n "$SAFE_STMTS" ] && ! echo "$SAFE_STMTS" | grep -qF -- '..' \
        && ! echo "$CMD" | grep -qE "$TAR_PATHOPT_RE" \
        && [ "$(echo "$SAFE_STMTS" | grep -oE -- '[[:space:]]-C[[:space:]]' | wc -l)" -eq "$(echo "$SAFE_STMTS" | grep -c .)" ]; then
        REST=$(echo "$CMD" | sed -E "s#$SAFE_RX# __SAFE__ #g")
        #   경로 뒤에 `-C` 가 더 붙은 형태(`… -C ~/codex-exchange/x -C /etc`)는 구문에서 떼어낸 나머지에 `-C` 가 남아 여기서 걸린다.
        if ! { echo "$REST" | tr '\n' ' ' | sed "s/'[^']*'//g" | sed 's/"[^"]*"//g' | grep -qE "$TAR_X_RE" \
            || echo "$REST" | tr -d "\"'" | grep -qE "$TAR_X_RE" \
            || echo "$REST" | grep -qE '[[:space:]]-C[[:space:]]'; }; then
            SAFE_ARCHIVE_EXTRACT=true
        fi
    fi
    # 2026-09-08: 모드 토큰만 본다 — ① 단일 대시 옵션 묶음(`-xf`·`-xzf`) ② tar 바로 뒤 첫 bare 토큰(`xf`·`xvzf`) ③ `--extract`·`--get`.
    #   종전 `-?[A-Za-z]*x` 는 파일명(`index.tar`·`xz-backup.tar`)의 x 까지 추출로 봤다. 이중 대시(`--exclude=x`)는 모드가 아니다.
    if [ "$SAFE_ARCHIVE_EXTRACT" = false ]; then
        echo "$T" | grep -qE "$TAR_X_RE" \
            && BLOCK=true && REASON="tar 추출 (파일 생성)${CTX}"   # ln 추가: 하드링크로 교환 디렉터리에 하네스 원문 끌어오기 차단 (5라운드)
    fi
    # 아카이브·패치 **생성** (2026-09-08 신설): 추출만 막고 있어 `tar -czf`·`zip -r`·`7z a`·`patch -p1 < d.diff` 가 전부 통과했다.
    #   tar 생성 모드는 추출과 같은 자리(대시 묶음·첫 bare 토큰·`--create`)에서만 c 를 본다. `-C`(대문자 디렉터리 이동)는 모드가 아니다.
    echo "$T" | grep -qE "(^|$B|/)tar[[:space:]]+([A-Za-z]*c[A-Za-z]*([[:space:]]|$)|([^;&|]*[[:space:]])?(-[A-Za-z]*c[A-Za-z]*([[:space:]]|$)|--create([[:space:]=]|$)))" \
        && BLOCK=true && REASON="아카이브 생성 (tar -c)${CTX}"
    echo "$T" | grep -qE "$EB(patch|zip)[[:space:]]|$EB"'7za?[[:space:]]+(a|d|u|x|e)([[:space:]]|$)' \
        && BLOCK=true && REASON="파일 생성 도구 (patch/zip/7z)${CTX}"
    # 원격 복사도 파일을 쓴다 (2026-09-08 qa 독립 검수: HEAD 부터 통과했다). `grep -rn scp scripts/` 는 명령 위치가 아니라 통과.
    echo "$T" | grep -qE "$EB"'scp[[:space:]]'"|$EB"'(docker|podman|kubectl)[[:space:]]+cp[[:space:]]' \
        && BLOCK=true && REASON="원격 파일 복사 (scp/docker cp/kubectl cp)${CTX}"
    echo "$T" | grep -qE "(^|$B|/)(chmod|chown)[[:space:]]" \
        && BLOCK=true && REASON="권한/소유권 변경 (chmod/chown)${CTX}"
    # 패키지 설치: 좌측 경계 추가 (2026-07-18 Codex): 'notpip install' 오탐 방지
    echo "$T" | grep -qE "(^|$B)(pip|uv|conda|apt(-get)?|yum|brew|npm|yarn|cargo)[[:space:]]+install" \
        && BLOCK=true && REASON="패키지 설치${CTX}"
    # 2026-09-08 확장: 위 한 줄은 `pip` 뒤 공백만 봐 `pip3 install`·`pip3.11 install` 을 놓쳤고(버전 접미),
    #   설치 아닌 환경 변경 하위명령(uv add·uv sync·npm i·conda create·python3 -m venv)은 열거에 아예 없었다.
    echo "$T" | grep -qE "$EB(pip[0-9.]*[[:space:]]+(install|uninstall|download)|pipx[[:space:]]+(install|uninstall|inject|upgrade)|uv[[:space:]]+(add|remove|sync|lock|venv)|uv[[:space:]]+(tool|python)[[:space:]]+install|(conda|mamba)[[:space:]]+(install|create|remove|update|env)|npm[[:space:]]+(install|i|ci|add|uninstall|update|link)|pnpm[[:space:]]+(add|install|i|remove)|yarn[[:space:]]+(add|install|remove)|poetry[[:space:]]+(add|install|remove|update)|cargo[[:space:]]+(install|add)|python[0-9.]*[[:space:]]+-m[[:space:]]+venv|virtualenv)([[:space:]]|$)" \
        && BLOCK=true && REASON="패키지·환경 변경 (설치·제거·동기화)${CTX}"
    #   `uv pip` 은 하위명령이 읽기(list/freeze/show/tree/check)일 때만 통과 — 열거 누락 시 fail-closed
    if echo "$T" | grep -qE "$EB"'uv[[:space:]]+pip([[:space:]]|$)'; then
        echo "$T" | grep -qE "$EB"'uv[[:space:]]+pip[[:space:]]+(list|freeze|show|tree|check)([[:space:]]|$)' \
            || { BLOCK=true; REASON="패키지·환경 변경 (uv pip)${CTX}"; }
    fi
    #   `python -m pip` 도 `uv pip` 과 같은 기준 (2026-09-08 후속): 종전엔 `-m (venv|pip)` 로 뭉뚱그려 `python3 -m pip list` 까지 막았다.
    #   install·uninstall·download 는 위 두 줄(`pip … install`·`pip[0-9.]* …`)이 이미 막으므로 여기서는 읽기 하위명령만 연다.
    if echo "$T" | grep -qE "$EB"'python[0-9.]*[[:space:]]+-m[[:space:]]+pip([[:space:]]|$)'; then
        echo "$T" | grep -qE "$EB"'python[0-9.]*[[:space:]]+-m[[:space:]]+pip[[:space:]]+(list|show|freeze|check|debug|inspect|--version|(cache|config)[[:space:]]+list)([[:space:]]|$)' \
            || { BLOCK=true; REASON="패키지·환경 변경 (python -m pip)${CTX}"; }
    fi
    # 리다이렉션 없는 파일 쓰기 명령 (tee / sed -i / curl -o / wget -O) — 탐지 추가 2026-07-06
    echo "$T" | grep -qE "(^|$B)tee[[:space:]]" \
        && BLOCK=true && REASON="파일 쓰기 (tee)${CTX}"
    echo "$T" | grep -qE "(^|$B)sed[[:space:]]([^;&|]*[[:space:]])?(-[A-Za-z]*i|--in-place)" \
        && BLOCK=true && REASON="파일 내 수정 (sed -i)${CTX}"
    # 15라운드 렌즈2: 같은 "파일 내용 재작성" 능력의 다른 도구명 — perl/ruby -i(-pi·-i.bak 포함), gawk -i inplace / --inplace
    # 종결자는 공백·구분자(`;&|)`)·끝 (16라운드 Grok: `perl -i.bak;`·`find . -delete; echo x`·무경로 `find -delete` 가 공백·EOS 종결만으로 비껴갔다)
    echo "$T" | grep -qE "(^|$B|/)(perl|ruby)[[:space:]]+([^;&|]*[[:space:]])?-[a-zA-Z]*i[^[:space:];&|)]*([[:space:];&|)]|$)|(^|$B|/)(g|m|n)?awk[[:space:]]+([^;&|]*[[:space:]])?(-i[[:space:]]*inplace|--inplace)" \
        && BLOCK=true && REASON="파일 내 수정 (perl/ruby -i · awk -i inplace)${CTX}"
    # 15라운드 렌즈2: find 자체의 쓰기·실행 액션 — -delete 는 rm 없이 지우고, -fprint/-fls 는 파일을 쓴다. -exec 의 인터프리터 '{}' 주입은 0.4 DYN_CODE 가, -exec rm 류는 위 writer 토큰이 잡는다
    echo "$T" | grep -qE "(^|$B|/)find([[:space:]]+[^;&|[:space:]]+)*[[:space:]]+(-delete|-fprint0?|-fprintf|-fls)([[:space:];&|)]|$)" \
        && BLOCK=true && REASON="find 쓰기 액션 (-delete/-fprint/-fls)${CTX}"
    # 긴 옵션은 curl 이 고유 접두 약어를 받으므로(`--cookie-j`·`--dump-h`) 접두로 잡는다 (2026-10-17 security 재검수). 짧은 묶음 앞 글자는 값을 받지 않는 플래그(#·숫자 포함)만.
    # curl 파일 저장: 짧은 옵션 묶음(-sSo·-Lo·-o./x·-O)·`=` 형(--output=x)·쿠키 저장(-c/--cookie-jar)·헤더 저장(-D/--dump-header) 포함 (2026-10-17 Codex·Grok 반례)
    # 경로 접두(`/usr/bin/curl`)는 다른 writer 와 같이 `/` 를 경계에 넣어 잡는다 (2026-10-17 Codex 2차). CURL_OPT_RX 는 아래 따옴표 제거본 검사와 공유한다.
    echo "$T" | grep -qE "(^|$B|/)curl[^;&|]*${CURL_OPT_RX}" \
        && BLOCK=true && REASON="파일 다운로드·저장 (curl -o/-O/--output/-c/-D) 또는 curl 설정 입력(-K/--config)은 내용을 검사할 수 없어 차단${CTX}"
    # wget 은 옵션이 없어도 cwd 에 파일을 쓴다 (2026-09-08: 종전 `-O|-P|--output-document` 열거는 `wget URL` 을 그대로 통과시켰다).
    #   stdout 로 흘리거나(`-O -`·`-O-`·`--output-document=-`) 존재 확인만 하는(`--spider`) 형태만 통과, 그 외는 전부 차단.
    if echo "$T" | grep -qE "$EB"'wget([[:space:]]|$)'; then
        echo "$T" | grep -qE "$EB"'wget([[:space:]][^;&|]*)?[[:space:]](-O[[:space:]]*-|--output-document[[:space:]]*=?[[:space:]]*-|--spider)([[:space:]]|$)' \
            || { BLOCK=true; REASON="파일 다운로드 저장 (wget — 옵션 없이도 cwd 에 저장)${CTX}"; }
    fi
    # 환경 상태 변경 (2026-09-08 신설) — 파일이 아니라 실행 중인 프로세스·세션·시스템 상태를 바꾼다.
    #   2026-09-05 실사고: `pkill -f 평가스크립트명` 이 같은 이름을 argv 에 가진 학습 와쳐까지 죽였다 → 사용자 지시 «pid 로만 kill».
    #   경계는 위 EB — 따옴표를 포함해 원격 페이로드(`ssh h "pkill -f x"`)도 규칙 2 재검사에서 잡히고, 공백만 앞선 단어(`grep pkill f`)는 통과한다.
    #   2026-09-08 qa 독립 검수: 종전 경계는 sudo·doas 만 건너뛰어 `env pkill`·`timeout 5 pkill`·`xargs pkill`·`/usr/bin/pkill` 이 새어 나갔다 → WRAP_SKIP+경로 접두로 닫았다.
    #   읽기·pid 단위는 허용: kill <pid>·kill -0·pgrep·tmux ls·tmux send-keys·systemctl status·crontab -l·인자 없는 mount·sysctl <key>.
    #   mount 는 «인자 유무»·«피연산자 개수» 로 못 가른다 — 검사 문자열이 원문+디코드본이라 인자 없는 `mount` 도 뒤에 복제 토큰이 붙는다(실측).
    #   그래서 개수 대신 **마운트 지정의 모양**을 본다 (2026-09-08 후속): 경로 피연산자(`/dev/sda1`·`/mnt`)·원격 지정(`a:/b`)·
    #   `-o`·`--bind|rbind|move`·`UUID=|LABEL=` 이면 차단, 조회(`mount`·`mount -l`·`mount -t nfs`)는 통과. umount 는 인자가 붙으면 차단.
    #   한계: 슬래시 없는 두 피연산자(`mount mylabel mnt`)는 놓친다.
    echo "$T" | grep -qE "$EB((pkill|killall)([[:space:]]|$)|tmux[[:space:]]+([^;&|]*[[:space:]])?kill-(session|server|window|pane)([[:space:]]|$)|umount[[:space:]]+[^;&|[:space:]]|mount[[:space:]]+([^;&|]*[[:space:]])?(/|-o([[:space:]=]|$)|--(bind|rbind|move)([[:space:]]|$)|(UUID|LABEL)=|[^;&|[:space:]]*:/)|systemctl[[:space:]]+([^;&|]*[[:space:]])?(start|stop|restart|reload|enable|disable|daemon-reload|mask)([[:space:]]|$)|crontab[[:space:]]+(([^;&|]*[[:space:]])?-[A-Za-z]*[er]([[:space:]]|$)|[^-;&|[:space:]])|sysctl[[:space:]]+([^;&|]*[[:space:]])?-[A-Za-z]*w([[:space:]]|$))" \
        && BLOCK=true && REASON="환경 상태 변경 (pkill/killall/tmux kill/mount/systemctl/crontab) — pid 단위 kill·읽기 명령은 허용${CTX}"
}

# ── 0.5 따옴표로 감싼 명령 위치 변수 (7라운드 렌즈2: `x=rm; "$x" -rf …` 는 quote-strip 이 "$x" 를 통째로 지워 무탐)
#    명령 위치 토큰이 `"$…`/`$…` 이면 차단 (assignment 뒤 `;`/`&&` 다음도 명령 위치).
#    실행 래퍼(exec/command/builtin/env/nohup/nice/timeout/xargs/sudo) 뒤 토큰도 명령 위치다 (8라운드 Grok: `exec "$x" -rf …`)
#    2026-09-08 검수: 검사 대상을 원문에서 S_CMDPOS(따옴표 접은 사본)로 바꾸고 래퍼 뒤 건너뛰기를 WRAP_SKIP 으로 좁혔다.
#    종전엔 따옴표 안의 `(`·`;` 뒤 `$` 도(`awk '{print substr($0,1,60)}'`), 래퍼 뒤 인자도(`env cat "$PWD/x"`) 명령 위치로 봤다.
echo "$S_CMDPOS" | grep -qE "$CMDPOS_VAR" \
    && BLOCK=true && REASON="명령 위치 변수·치환 간접 실행 (\"\$VAR\" …, 래퍼 뒤 포함)"
# (구 0.6 파이프-투-셸 검사는 0.4 로 이동·상위집합화돼 제거 — 11라운드 렌즈1: 0.4 통과분은 구 0.6 에 매치될 수 없는 dead code 였다)
# ── 0.7 명령 위치 토큰의 셸 워드 생성 (8라운드 렌즈2: `{r,}m -rf x` → 브레이스 전개로 rm, `r[m]` → 글롭으로 rm — 어느 사본에도 'rm' 리터럴이 없다)
#    정규화로 해소 불가능한 클래스이므로 판별 대신 fail-closed: 명령 위치 토큰에 `{a,b}`·`[..]`·`*`·`?` 가 섞이면 차단
#    따옴표 안(인터프리터 코드의 `;` 뒤 `x[1]`)은 셸 워드 생성 대상이 아니므로 quote-strip 본에서 본다(실측 오탐 교정)
#    16라운드 렌즈1: `bash -c '{r,}m -rf /'` 는 quote-strip 본에서 페이로드가 통째로 사라져 0.7 이 못 봤고 2단계 재검사는 리터럴 토큰만 봤다
#    → 2단계가 열리면 따옴표 문자만 뗀 사본(S_UQ)에도 같은 검사를 돌린다. 셸(`sh -c`)도 래퍼로 보아 `-c` 뒤 첫 토큰을 명령 위치로 본다.
#    기본(S_PRE, 따옴표 내용 제거본): 래퍼 뒤 건너뛰기는 WRAP_SKIP(옵션·대입·수치 피연산자)만이다.
#    2026-09-08 검수: 종전의 무제한 토큰 건너뛰기는 래퍼 뒤 **인자**를 명령 위치로 봐 `env ls scripts/*.sh`·`timeout 5 ls *.sh` 를 차단했다(`ls scripts/*.sh` 는 통과).
#    2단계(S_UQ, 따옴표 문자만 제거본): 래퍼 뒤에는 옵션(`-…`)·대입(`A=B`)만 건너뛴다 — 무제한 루프는 `xargs python3 lint.py … "*.py"` 의 인용 글롭까지 명령 위치로 봤다(실측 오탐).
WORDGEN_RE="$CMDLEAD""$WRAP_SKIP"'[^[:space:];&|(=]*(\{[^{}[:space:]]*,[^{}[:space:]]*\}|\[[^][[:space:]]+\]|[*?]|\$([A-Za-z_{(@*!#?-]|[0-9]))[^[:space:];&|]*'
WORDGEN_RE2="$CMDLEAD"'(([^[:space:]]*/)?(exec|command|builtin|env|nohup|nice|timeout|xargs|sudo|doas|(ba|z|da|k)?sh)[[:space:]]+((-[^[:space:]]*|[A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*)[[:space:]]+)*)?[^[:space:];&|(=]*(\{[^{}[:space:]]*,[^{}[:space:]]*\}|\[[^][[:space:]]+\]|[*?]|\$([A-Za-z_{(@*!#?-]|[0-9]))[^[:space:];&|]*'
S_PRE=$(echo "$CMD" | tr '\n' ' ' | sed "s/'[^']*'//g" | sed 's/"[^"]*"//g')
echo "$S_PRE" | grep -qE "$WORDGEN_RE" \
    && BLOCK=true && REASON="명령 위치 토큰에 셸 전개 문자(브레이스·글롭·변수 결합)가 섞임 — 명령명은 리터럴로"

# ── 1. 표준 검사: 따옴표 제거(오탐 방지) → git 중화 → 무해 리다이렉션 제거 → 패턴 검사
# 개행을 공백으로 접고 나서 따옴표 제거 — sed는 줄 단위라 여러 줄 인용 쌍을 못 접어
# 여러 줄 커밋 메시지의 ">="가 리다이렉션으로 오탐됐다 (2026-08-13·08-15 실사고).
S=$(echo "$CMD" | tr '\n' ' ' | sed "s/'[^']*'//g" | sed 's/"[^"]*"//g' | neutralize_git | strip_harmless)
check_write_patterns "$S" ""
# 따옴표로 감싼 curl 옵션(`curl "--output=./x"`·`curl '-o' x`)은 위 S 에서 내용째 지워져 통과한다 (2026-10-17 Codex 2차).
# 따옴표 «문자만» 뗀 사본에서 curl 검사만 다시 한다. 인용문 속 낱말(`echo "curl -o x"`)의 오탐을 피하려고 명령 위치(줄머리·구분자·예약어·래퍼 뒤)의 curl 만 본다.
# (변수 이름은 위 0.4 의 S_UQ 와 겹치지 않게 S_CURL_UQ — 개행을 공백으로 접은 사본이라 내용도 다르다.)
# 4차(Codex): 따옴표를 그냥 지우면 `X="a b" curl "--output=x"` 의 대입 값 공백이 드러나 명령 위치 판정이 깨진다 → 따옴표 구간 안의 공백·탭은 `_` 로 바꾼 뒤 따옴표를 뗀다.
S_CURL_UQ=$(printf '%s' "$CMD" | tr '\n' ' ' | awk '{ n = length($0); out = ""; q = ""
    for (i = 1; i <= n; i++) { c = substr($0, i, 1)
        if (q == "") { if (c == "\"" || c == "\047") { q = c; continue } out = out c }
        else { if (c == q) { q = ""; continue } if (c == " " || c == "\t") c = "_"; out = out c } }
    print out }')
CURL_CMDPOS="(^[[:space:]]*|[;&|(\`][[:space:]]*|(^|[[:space:];&|(\`])${RW}[[:space:]]+)([A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+)*${WRAP_SKIP}([^[:space:]]*/)?curl[^;&|]*"   # 환경 대입 접두(X=1 curl …) 허용 (2026-10-17 Codex 3차)
echo "$S_CURL_UQ" | grep -qE "${CURL_CMDPOS}${CURL_OPT_RX}" \
    && BLOCK=true && REASON="파일 다운로드·저장 (curl -o/-O/--output/-c/-D — 따옴표로 감싼 옵션)"
# `-w`/`--write-out` 의 형식 문자열에 `%output{파일}` 이 있으면 curl 이 그 파일에 쓴다 (2026-10-17 security 3차). 따옴표 속 값이라 위 S 에서는 지워진다.
echo "$S_CURL_UQ" | grep -qE "${CURL_CMDPOS}[[:space:]](-[a-zA-Z]*w|--write-out)[^;&|]*%output\{" \
    && BLOCK=true && REASON="파일 다운로드·저장 (curl -w %output{…} — 쓰기 형식 문자열)"

# ── 2. 중첩 실행 컨텍스트 검사 — $(...) / `...` / sh -c / 파이프-투-셸 존재 시 원문 그대로 재검사
#    프로세스 치환 `<(`·`source`/`.`·here-string `<<<` 도 중첩 실행 (8라운드 Grok: `source <(printf 'rm …')` 는 인용 페이로드가 quote-strip 으로 사라졌다)
#    셸명 앞 경로 접두(`/bin/bash -c …`)도 트리거 (9라운드 렌즈2: `/` 가 경계에 없어 원문 재검사가 열리지 않았다)
#    2026-09-08: 원격·컨테이너 실행도 같은 클래스 — `ssh host "rm -rf x"`·`docker exec c "…"` 는 따옴표 제거 단계에서 페이로드가 통째로 사라져 무검사 통과했다(실측).
#      `tmux send-keys` 는 제외한다: 학습 발사 공식 통로가 `tmux send-keys -t <접두>N "… > log 2>&1" Enter` 라 재검사를 열면 발사가 막힌다(발사 게이트는 train-launch-warn.sh).
#    2026-10-06: `$(`·백틱 트리거·S_RAW·WORDGEN_RE2 사본은 0.46 정리본(SAN)에서 본다. 허용 목록을 통과하지 못하면 SAN = CMD 라 종전과 같다.
if echo "$SAN" | grep -qE '\$\(|`' || echo "$CMD" | grep -qE '<\(|<<<|(^|[[:space:];&|(])(source|\.)[[:space:]]|(^|[[:space:];&|(/])(bash|sh|zsh|dash|ksh)[[:space:]]+([^;&|]*[[:space:]])?-c([[:space:]]|$)|(^|[|;&][[:space:]]*)([^[:space:]]*/)?(bash|sh|zsh|dash|ksh)([[:space:]]|$)|(^|[[:space:];&|(])(ssh|docker[[:space:]]+(exec|run)|podman[[:space:]]+(exec|run)|kubectl[[:space:]]+exec)([[:space:]]|$)'; then
    S_RAW=$(echo "$SAN" | neutralize_git | strip_harmless)
    check_write_patterns "$S_RAW" " — 실행 컨텍스트(\$()/backtick/sh -c) 내부"
    # 재검사 범위: check_write_patterns(리터럴 writer 토큰) + 0.7 워드 생성(따옴표만 뗀 사본) — 16라운드 렌즈1: 종전엔 전자만 재실행돼 주석("원문 그대로 재검사")과 구현이 어긋났다
    S_UQ_WG=$(printf '%s' "$SAN" | tr -d '"'"'")
    echo "$S_UQ_WG" | grep -qE "$WORDGEN_RE2" \
        && BLOCK=true && REASON="실행 컨텍스트 내부 명령 위치 토큰에 셸 전개 문자(브레이스·글롭·변수 결합)가 섞임"
fi

# ── 3. 간접 실행 검사 (eval / 명령 위치 변수)
echo "$S" | grep -qE '(^|[[:space:];&|(])eval[[:space:]]' \
    && BLOCK=true && REASON="eval 간접 실행"
echo "$S" | grep -qE '(^[[:space:]]*|[;&|][[:space:]]*|(^|[[:space:];&|])'"$RW"'[[:space:]]+)\$([A-Za-z_{(@*!#?-]|[0-9])' \
    && BLOCK=true && REASON="명령 위치 변수 간접 실행 (\$VAR ...)"

# ── 3.5 인라인 인터프리터 코드의 파일 쓰기 (2026-08-25 4라운드 검수: python3 -c "open(f,'w')" / awk 'print > f' 가
#    따옴표 제거 단계에서 코드가 통째로 사라져 무검사 통과했다). 원문(CMD)을 본다. 인터프리터는 무한하므로 완전 방어가
#    아니라 문턱 상향이며, 감사 로그·state 파일 무결성은 이 훅이 아니라 사후 결박(git blob·hash-object)으로 주장한다.
#    오탐(예: 'a.txt' 읽기 모드 파일명이 [wax]로 시작)은 # APPROVED 로 통과 — 미탐 < 오탐 우선.
BI="[[:space:];&|(\"'\`]"
#    heredoc(`python3 <<'EOF' … EOF`)도 인라인 코드다 — `-c` 가 없어 검사가 안 열리던 우회(5라운드 렌즈2)를 트리거에 포함.
#    파이프 heredoc(`cat <<PY | python3`)도 인터프리터 stdin 코드 — 명령에 heredoc 과 인터프리터가 함께 있으면 연다 (6라운드 Grok).
#    코드플래그에 붙여 쓴 코드(`python3 -cimport os;…`·`-c(…)`)도 연다 — 종결자에 글자·`(` 포함 (14라운드 Grok: 붙여 쓴 치환 `-c{}` 는 0.4 DYN_CODE 가 막고, 붙여 쓴 리터럴은 여기서 정적 검사)
if echo "$CMD" | grep -qE "(^|$BI|/)(python[0-9.]*|perl|node|ruby|php)[[:space:]]+([^;&|]*[[:space:]])?(-[a-zA-Z]*[cerE]|--eval|--print|-p)([=[:space:]'\"(A-Za-z_]|$)|(^|$BI|/)(python[0-9.]*|perl|node|ruby|php)[^;&|]*<<[-~]?[[:space:]]*['\"]?[A-Za-z_]+" \
   || { echo "$CMD" | grep -qE "<<[-~]?[[:space:]]*['\"]?[A-Za-z_]+|<<<|\|[[:space:]]*(python[0-9.]*|perl|node|ruby|php)([[:space:]]|$)|(python[0-9.]*|perl|node|ruby|php)[[:space:]]+-([[:space:]]|$)|/dev/stdin|/dev/fd/|/proc/[^/[:space:]]+/fd/" && echo "$CMD" | grep -qE "(^|$BI|/)(python[0-9.]*|perl|node|ruby|php)([[:space:]]|$)"; }; then
    # 열리면 CMD 원문에도 셸 쓰기 패턴을 한 번 더 돌린다 — API 열거를 늘리는 대신 페이로드 안의 `rm -rf` 류를 셸 검사로 잡는다 (8라운드 Grok: `from os import system as s; s("rm …")`)
    check_write_patterns "$(echo "$CMD" | neutralize_git | strip_harmless)" " — 인터프리터 인라인/stdin 페이로드"
    # stdin 파이프(`printf … | python3`, `python3 -`, /dev/stdin)도 연다 (7라운드 Grok). 언어 무관 실행 원시함수 system/exec/popen/child_process/%x/backtick 포함 (7라운드 렌즈2)
    echo "$CMD" | grep -qE "open\([^)]*['\"][rwaxbt+]*[wax+]|open\([^)]*,[[:space:]]*['\"]>|\.(write|write_text|write_bytes|writeFile|appendFile|unlink|rename|replace|touch|rm|rmdir|mkdir|chmod|utime|utimes|link|symlink|truncate|copyFile|cp)(Sync)?\(|os\.(remove|unlink|rename|replace|rmdir|removedirs|makedirs|system|popen|truncate|utime|link|symlink)|shutil\.|subprocess|fs\.(write|unlink|rename|rm|append|utimes|link|symlink)|File\.(open|write|delete)|unlink[[:space:](]|truncate\(|utime[[:space:](]|open[[:space:]]+[A-Z_]+,[[:space:]]*['\"]>|system[[:space:]]*\(|exec(Sync|File|Sync)?[[:space:]]*\(|spawn(Sync)?[[:space:]]*\(|popen[[:space:]]*\(|child_process|%x[\[{(]|IO\.popen|Kernel\.|\`[^\`]+\`" \
        && BLOCK=true && REASON="인라인 인터프리터 코드 내 파일 쓰기·삭제·실행 (python -c / perl -e / node -e / stdin …)"
fi
# 감사 로그 기록기 직접 호출·감사 파일 직접 지정 차단 (4라운드 Codex 지적: 파이프로 임의 post 행 위조 가능) — 훅 외 호출 용도가 없다
#   실행 형태만 (git add 등 경로 언급은 통과 — 실측 자기차단 2026-08-25)
echo "$CMD" | grep -qE "(^|[[:space:];&|(])(bash|sh|source|\.)[[:space:]]+[^[:space:]]*agent-spawn-log\.sh|agent-spawn-log\.sh[[:space:]]+(pre|post)([[:space:]]|$)" \
    && BLOCK=true && REASON="감사 로그 기록기 직접 호출 (훅 전용 — 로그 읽기는 cat/wc 로)"
if echo "$CMD" | grep -qE "(^|$BI|/)(g|m|n)?awk[[:space:]]"; then
    echo "$CMD" | grep -qE "print(f)?[^;|&]*[[:space:]]>>?[[:space:]]*[\"'A-Za-z_/\$(]|system[[:space:]]*\(" \
        && BLOCK=true && REASON="awk print 리다이렉션·system() 실행"
fi

# ── 결과 출력 ─────────────────────────────────────────────────
# 허용 = 무출력 exit 0 (정상 permission flow에 위임), 차단 = 신형 deny 스키마 (jq로 안전 생성)
if $BLOCK; then
    jq -cn --arg r "[쓰기 차단] $REASON — 필요하면 터미널에서 직접 실행하세요." \
        '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: $r}}'
fi
exit 0
