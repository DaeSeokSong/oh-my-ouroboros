#!/usr/bin/env bash
# gen_gptimg.sh — Codex 이미지 생성 그림 1장 래퍼 (OpenAI Codex CLI `codex exec` 경유, 2026-11-05 재작성)
# 의뢰서: intent/2026-11-05-gptimg-direct-generation.md · 게이트: scripts/external-model-gate.py
#
# 사용:  bash gen_gptimg.sh --model <M> --effort <E> "<그림 설명>" </절대/경로/그림.png|jpg|jpeg|webp>
#        (--model=값 · --effort=값 꼴도 허용. 모델·effort 는 둘 다 필수이고 각각 한 번만 쓴다)
#
# ⚠️ 비용: 이미지 생성은 Codex 사용 한도를 텍스트보다 3~5배 빠르게 소모한다.
# ⚠️ 실행 주체: 그릴 주체 결정 팝업에서 사용자가 Codex 이미지 생성을 고른 그림만 **main 이** 실행한다(고르는 것이 비용 승인).
#     서브에이전트는 실행하지 않는다(훅이 agent_id 가 있는 호출을 막는다). 모델·effort 는 사이클당 1회 결정 팝업으로 받는다(rules-lazy/codex-model-gate.md).
#     훅(external-model-gate.py)이 이 래퍼 호출을 외부 모델 호출로 분류해, 이번 사용자 메시지나 그 뒤 팝업 답에 모델·effort 가 없으면 막는다.
# ⚠️ 전송 3등급: 그림 설명에 등급 3(미공개 핵심 · 실측 성능 수치 · 회사 코드 원문)을 넣지 않는다(rules-lazy/untrusted-quarantine.md §6).
#
# 격리: 호출마다 mktemp 폴더($WORK, 저장소 밖)를 만들고 그 아래 빈 폴더($RUN)를 `-C` 로 못박으며 표준 입력은 닫는다.
#       `-s workspace-write` 는 기본값이 /tmp · $TMPDIR 도 쓰기 가능이라 `sandbox_workspace_write.exclude_slash_tmp` ·
#       `exclude_tmpdir_env_var` 를 true 로 꺼서 쓰기 가능 범위를 $RUN 뿐으로 좁힌다(설정 키 이름은 codex 문서 기준이며 이 설정이 실제로 먹는지는 첫 실행 때 확인한다).
#       시작 표식 · codex 출력 사본은 $RUN 이 아니라 $WORK 에 둬 Codex 가 쓸 수 없다.
#       MCP · 플러그인은 끈다(rules-lazy/codex-model-gate.md §0 — config.toml 에 MCP 서버를 새로 등록하면 아래 `-c` 줄에도 추가한다).
#       한계: workspace-write 도 읽기 범위는 막지 않으므로 절대 경로로 폴더 밖 파일을 읽을 수 있다(§0 «read-only 는 쓰기만 막는다»와 같은 사정).
#       그래서 설명문에 비밀값 · 경로 · 파일 내용을 넣지 않는다. 설명문은 external_send_preflight.py 로 한 번, 훅이 고신뢰 비밀값 패턴으로 한 번 더 거른다(걸리면 78).
# 결과: $RUN 안의 그림 파일을 찾는다. 없을 때만 폴백을 쓴다. 폴백은 codex 종료 코드가 0 이고 codex 출력 첫 `session id:` 줄에서 이번 실행의 id 를 읽어 낸 경우에만,
#       `~/.codex/generated_images/<그 id>/` 안의 시작 이후 `exec-*.{png,jpg,jpeg,webp}` 중 가장 새 하나를 쓴다(2026-11-05 실측: sandbox 가 지정 폴더 저장을 막는 경우
#       그림이 거기에만 남았다). 다른 세션 폴더는 보지 않고, id 를 못 찾으면 폴백하지 않고 75 다. auth.json 은 존재만 확인한다.
#       `file --mime-type` 으로 실제 형식을 확인해 출력 확장자와 다르면 아무것도 쓰지 않고 거부한다. 같으면 출력 경로로 **복사**하고(폴백 원본은 남긴다) `OK: <경로>` 를 낸다.
#       codex 출력은 전부 표준 오류로 내고(표준 출력은 `OK: <경로>` 한 줄) $WORK 에 사본을 남겨 id 를 읽는다. 종료 시 $WORK 는 지운다.
#       출력 경로는 절대 경로 · 부모 폴더 실재 · 대상 파일 없음.
#
# 종료 코드:  0 성공 · 64 인자 / 출력 경로 오류(옵션 중복 포함) · 65 그림 실제 형식이 출력 확장자와 다름(아무것도 쓰지 않음 — 맞는 확장자로 다시 요청)
#            69 codex 없음 또는 구독 로그인 없음(~/.codex/auth.json) · 70 내부 오류(mktemp · cp 실패) · 75 그림이 만들어지지 않음
#            78 그림 설명이 전송 전 검사에 걸림 또는 검사 스크립트 없음
#
# NOTE: `$imagegen` 의 저장 동작은 codex 버전·설정에 따라 다를 수 있다(그림이 CWD 가 아닌 곳에 생기면 지시문의 «복사» 문구와 위 폴백에 기댄다).
#       버전이 바뀌면 처음 한 번 실제로 확인한다. 이 파일을 고쳐도 실제 생성 시험은 Codex 한도를 쓰므로 사용자 요청 때만 한다.
set -euo pipefail

usage() { echo 'usage: gen_gptimg.sh --model <M> --effort <E> "<프롬프트>" </절대/경로/그림.png|jpg|jpeg|webp>' >&2; exit 64; }
dup() { echo "거부: $1 옵션이 두 번 이상 있음" >&2; exit 64; }

MODEL="" EFFORT="" HAVE_M="" HAVE_E="" POS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --model)    [[ $# -ge 2 ]] || usage; [[ -z "$HAVE_M" ]] || dup --model; HAVE_M=1; MODEL="$2"; shift 2 ;;
    --model=*)  [[ -z "$HAVE_M" ]] || dup --model; HAVE_M=1; MODEL="${1#--model=}"; shift ;;
    --effort)   [[ $# -ge 2 ]] || usage; [[ -z "$HAVE_E" ]] || dup --effort; HAVE_E=1; EFFORT="$2"; shift 2 ;;
    --effort=*) [[ -z "$HAVE_E" ]] || dup --effort; HAVE_E=1; EFFORT="${1#--effort=}"; shift ;;
    *)          POS+=("$1"); shift ;;
  esac
done
[[ -n "$MODEL" && -n "$EFFORT" && ${#POS[@]} -eq 2 && -n "${POS[0]}" ]] || usage
[[ "$MODEL" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ && "$EFFORT" =~ ^[a-z]+$ ]] || { echo "거부: --model · --effort 값 형식 이상" >&2; exit 64; }
PROMPT="${POS[0]}" OUT="${POS[1]}"

# 출력 경로: 절대 경로 · 허용 확장자 · 부모 폴더 실재 · 대상 없음
[[ "$OUT" == /* ]] || { echo "거부: 출력 경로는 절대 경로여야 함: $OUT" >&2; exit 64; }
BASE="$(basename -- "$OUT")"
[[ "$BASE" == *.* && -n "${BASE%.*}" ]] || { echo "거부: 출력 경로는 이름 + 확장자여야 함: $OUT" >&2; exit 64; }
EXT="${BASE##*.}"; EXT="${EXT,,}"
case "$EXT" in
  png) WANT=image/png ;;
  jpg|jpeg) WANT=image/jpeg ;;
  webp) WANT=image/webp ;;
  *) echo "거부: 확장자는 png · jpg · jpeg · webp 만: $OUT" >&2; exit 64 ;;
esac
[[ -d "$(dirname -- "$OUT")" ]] || { echo "거부: 출력 부모 폴더가 없음: $(dirname -- "$OUT")" >&2; exit 64; }
{ [[ -e "$OUT" ]] || [[ -L "$OUT" ]]; } && { echo "거부: 출력 경로가 이미 있음(덮어쓰지 않음): $OUT" >&2; exit 64; }

command -v codex >/dev/null 2>&1 || { echo "ERROR: codex CLI 를 찾을 수 없음 (PATH 확인 또는 npm i -g @openai/codex)" >&2; exit 69; }
command -v file >/dev/null 2>&1 || { echo "ERROR: file 명령이 없어 그림 형식을 확인할 수 없음" >&2; exit 69; }
[[ -f "$HOME/.codex/auth.json" ]] || { echo "ERROR: ~/.codex/auth.json 없음 — 'codex login' 으로 ChatGPT 구독 로그인이 필요" >&2; exit 69; }

WORK="$(mktemp -d -t gen_gptimg.XXXXXX)" || exit 70
trap 'rm -rf -- "$WORK"' EXIT
trap 'exit 130' INT TERM
RUN="$WORK/run"; mkdir "$RUN" || exit 70      # Codex 가 쓸 수 있는 유일한 폴더. 시작 표식 · 출력 사본 · 설명문 사본은 그 밖($WORK)에 둔다.
: > "$WORK/start"

# 전송 전 검사(grok-ask.sh 와 같은 방식): 그림 설명문을 같은 폴더의 external_send_preflight.py 로 한 번 훑는다. 차단·검사 불능이면 codex 를 부르지 않는다.
PREFLIGHT="$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/external_send_preflight.py"
[[ -f "$PREFLIGHT" ]] || { echo "거부: 전송 전 검사 스크립트 없음: $PREFLIGHT" >&2; exit 78; }
printf '%s\n' "$PROMPT" > "$WORK/prompt.txt"
if ! PF_OUT="$(python3 "$PREFLIGHT" "$WORK/prompt.txt" 2>&1)"; then
  echo "거부: 그림 설명이 전송 전 검사에 걸렸다 — 보내지 않는다." >&2
  printf '%s\n' "$PF_OUT" | tail -8 >&2
  exit 78
fi

INSTR="Use \$imagegen to generate exactly one image and save it (copy it if it was generated elsewhere) in the current working directory as out.${EXT}. Create no other files. Image description: ${PROMPT}. When done, reply with one short sentence describing the image."

GEN="$HOME/.codex/generated_images"
set +e
codex exec -m "$MODEL" -c model_reasoning_effort="$EFFORT" \
  -c mcp_servers.mem0.enabled=false -c mcp_servers.tavily.enabled=false -c mcp_servers.context7.enabled=false \
  --disable apps --disable plugins \
  -c sandbox_workspace_write.exclude_slash_tmp=true -c sandbox_workspace_write.exclude_tmpdir_env_var=true \
  -C "$RUN" --skip-git-repo-check -s workspace-write "$INSTR" </dev/null 2>&1 | tee "$WORK/out" >&2
rc=${PIPESTATUS[0]}
set -e

mapfile -t IMGS < <(find "$RUN" -type f \( -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.webp' \) | sort)
if [[ ${#IMGS[@]} -eq 0 && $rc -eq 0 ]]; then
  # 폴백(머리 주석 «결과»): 이번 실행의 session id 폴더 안으로만 한정한다. 줄 머리의 첫 `session id:` 줄만 읽는다
  # (그 뒤 설명문 에코의 같은 문구는 보지 않는다. 줄 머리 고정은 헤더를 안 찍는 버전에서 설명문 속 위조 id 를 막는다, 11-05 security 비차단 지적).
  SID="$(sed -nE '/^session id:/I{s/^session id:[[:space:]]*([0-9A-Fa-f]{8}(-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}).*$/\1/Ip;q}' "$WORK/out")"
  if [[ -n "$SID" && -d "$GEN/$SID" && ! -L "$GEN/$SID" ]]; then
    mapfile -t IMGS < <(find "$GEN/$SID" -maxdepth 1 -type f -newer "$WORK/start" \( -iname 'exec-*.png' -o -iname 'exec-*.jpg' -o -iname 'exec-*.jpeg' -o -iname 'exec-*.webp' \) \
      -printf '%T@ %p\n' | sort -rn | head -n 1 | cut -d' ' -f2-)
    [[ ${#IMGS[@]} -gt 0 ]] && echo "알림: 지정 폴더에는 없어 이번 세션($SID)의 generated_images 그림을 사용: ${IMGS[0]}" >&2
  fi
fi
if [[ ${#IMGS[@]} -eq 0 ]]; then
  echo "실패: 그림이 만들어지지 않음 (codex 종료 코드 $rc${SID:+, session id $SID}) — 출력 · 버전을 확인" >&2
  exit 75
fi
[[ ${#IMGS[@]} -gt 1 ]] && echo "경고: 그림이 ${#IMGS[@]}장 만들어짐 — 첫 장만 사용" >&2
SRC="${IMGS[0]}"

GOT="$(file --brief --mime-type -- "$SRC")"
if [[ "$GOT" != "$WANT" ]]; then
  echo "거부: 그림의 실제 형식($GOT)이 출력 확장자(.$EXT → $WANT)와 다름 — 아무것도 쓰지 않음. 맞는 확장자로 다시 요청" >&2
  exit 65
fi

{ cp -n -T -- "$SRC" "$OUT" && cmp -s -- "$SRC" "$OUT"; } || { echo "실패: 복사하지 못함: $OUT" >&2; exit 70; }
echo "OK: $OUT"
