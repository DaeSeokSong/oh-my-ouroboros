#!/usr/bin/env bash
# public-export.sh — ~/.claude 하네스의 sanitized 공개 미러 생성 (일방향 발행)
#
# 설계 근거 (판단 근거 이식 — 2026-07-23 합의):
#  - 공개 repo는 "빌드 산출물": 직접 편집 금지, 매 발행 시 통째로 재생성 → 별도 repo의
#    관리 부담을 0으로 만드는 핵심. private(~/.claude)만 source of truth.
#  - allowlist 방식: 목록에 없으면 "공개 안 됨"으로 실패 (blocklist는 누락=유출이라 기각).
#  - fail-closed 게이트: sanitize 후에도 금지 패턴이 남으면 발행 자체를 중단 —
#    유출이 아니라 차단이 실패 모드가 되게 한다. 게이트 출력은 파일·라인번호만
#    (내용 미출력 — 시크릿을 로그에 재노출하지 않는다).
#  - private 히스토리는 시크릿 미스크럽(2026-06-19 결정) → 히스토리 공유 절대 금지.
#    공개 repo는 발행 시점마다 sync 커밋 1개, author는 GitHub noreply.
#  - 내부 프로젝트 언급은 가명 치환이 아니라 «삭제» (2026-10-23 사용자 결정). 규칙 종류:
#      a|경로(허용) x|경로(제외) s|sed식(전역 치환) f|ERE(금지 패턴 게이트)
#      d|glob|ERE(glob 에 맞는 파일에서 ERE 에 맞는 줄 삭제) r|glob|sed식(glob 범위 한정 치환, 구절 삭제=빈 치환)
#      j|문자열(settings.json 의 hooks 중 command 에 문자열이 든 항목 삭제, jq 필요 — 없으면 exit 2)
#    d|·r| 이 아무 파일도 못 바꾸면 «⚠ 미적중 규칙» 경고(비공개 원문이 바뀌어 규칙이 낡았다는 신호, 막지는 않음).
#    줄 삭제가 코드를 깨면 정제 뒤 문법 게이트(.py/.sh/.json)가 exit 3 으로 막는다(fail-closed).
#
# 사용:
#   bash scripts/public-export.sh                      # dry-run: 스테이징+게이트+변경 요약만
#   bash scripts/public-export.sh --publish [대상경로]  # 미러 갱신+커밋 (push는 사용자 직접)
#   bash scripts/public-export.sh --stage-out <폴더>    # 정제본을 <폴더>(없거나 빈 폴더)에 남기고 게이트 결과로 끝낸다
#                                                       # (공개 전 범주 검사 scripts/public-export-scan.py 용, 발행 없음 — 2026-10-23)
# 기본 대상: ~/workspace/oh-my-ouroboros (인자로 변경 가능 — repo 이름 비종속)
set -euo pipefail

HARNESS="$HOME/.claude"
RULES="$HARNESS/config/public-export-rules.txt"
MODE="${1:-dry-run}"
TARGET="${2:-$HOME/workspace/oh-my-ouroboros}"
STAGE_OUT=""
if [ "$MODE" = "--stage-out" ]; then
  [ -n "${2:-}" ] || { echo "ERROR: --stage-out 에는 출력 폴더가 필요합니다" >&2; exit 2; }
  # 아래에서 하네스로 cd 하므로 상대 경로는 지금 절대 경로로 고정한다(qa 2026-10-23: 상대 경로가 하네스 안에 생겼다).
  STAGE_OUT=$(realpath -m -- "$2")
  [ -L "$2" ] && { echo "ERROR: 출력 폴더가 심볼릭 링크입니다: $2" >&2; exit 2; }
  [ -e "$STAGE_OUT" ] && [ -n "$(ls -A "$STAGE_OUT" 2>/dev/null)" ] && { echo "ERROR: 출력 폴더가 비어 있지 않습니다: $STAGE_OUT" >&2; exit 2; }
  # 하네스 안이면 git 무시 폴더(.scratch)만 허용한다. 게이트 전 사본이 추적 경로에 남아 커밋되지 않게(security 2026-10-23).
  case "$STAGE_OUT/" in
    "$(realpath -m "$HARNESS")/.scratch/"*) ;;
    "$(realpath -m "$HARNESS")"/*) echo "ERROR: 하네스 안에는 .scratch/ 아래만 출력 폴더로 쓸 수 있습니다: $STAGE_OUT" >&2; exit 2 ;;
  esac
fi
NOREPLY="DaeSeokSong@users.noreply.github.com"

[ -f "$RULES" ] || { echo "ERROR: 규칙 파일 없음: $RULES" >&2; exit 2; }

STAGE=$(mktemp -d "${TMPDIR:-/tmp}/pubexport.XXXXXX")
trap 'rm -rf "$STAGE"' EXIT

# ── 규칙 파싱 ──
ALLOW=(); EXCLUDE=(); SEDS=(); FORBID=(); DELS=(); RSUBS=(); JDELS=()
while IFS= read -r line; do
  case "$line" in
    d\|*) DELS+=("${line#d|}") ;;
    r\|*) RSUBS+=("${line#r|}") ;;
    j\|*) JDELS+=("${line#j|}") ;;
    a\|*) ALLOW+=("${line#a|}") ;;
    x\|*) EXCLUDE+=("${line#x|}") ;;
    s\|*) SEDS+=("${line#s|}") ;;
    f\|*) FORBID+=("${line#f|}") ;;
  esac
done < "$RULES"

# ── 1) 스테이징: git 추적 파일만, allowlist 교집합 − exclude ──
cd "$HARNESS"
# allowlist 가 비면 git ls-files -- (경로 없음) 이 추적 파일 전부를 내놓아 전체가 공개 대상이 된다(2026-10-01 감사).
[ "${#ALLOW[@]}" -gt 0 ] || { echo "ERROR: allowlist(a|) 가 0줄입니다 — 비면 전부가 공개 대상이 되므로 발행하지 않습니다: $RULES" >&2; exit 2; }
COPIED=0
while IFS= read -r f; do
  skip=0
  for x in "${EXCLUDE[@]:-}"; do [ -n "$x" ] && [[ "$f" == "$x" || "$f" == "$x"/* ]] && skip=1 && break; done
  [ "$skip" = 1 ] && continue
  mkdir -p "$STAGE/$(dirname "$f")"
  cp "$f" "$STAGE/$f"
  COPIED=$((COPIED+1))
done < <(git ls-files -- "${ALLOW[@]}")

# 공개 전용 파일 (public/ 전체 → 루트로: README·LICENSE·assets/ 등) — 추적 파일만(미추적 잔재가 미러로 새지 않게)
while IFS= read -r f; do
  mkdir -p "$STAGE/$(dirname "${f#public/}")"
  cp "$f" "$STAGE/${f#public/}"
done < <(git ls-files -- public)
# 미러 표식 — --publish 가 «이 폴더는 미러다» 를 확인하는 근거(아래 발행 대상 확인)
printf '%s\n' 'public-export mirror: scripts/public-export.sh 가 통째로 재생성합니다. 직접 편집 금지.' > "$STAGE/.public-export-mirror"

# ── 2) sanitize: d| 줄 삭제 → r| 범위 치환 → j| 훅 삭제 → s| 전역 치환 ──
# 파일 범위 규칙 하나를 스테이징 사본에 적용하고, 바뀐 파일이 0개면 미적중 경고를 낸다(식 내용은 찍지 않는다).
# 구분자는 제어 문자 \x01 — ERE 에 / 나 # 가 들어가도 된다.
SEP=$'\001'
apply_scoped() {  # $1=d|r  $2=경로 glob  $3=ERE 또는 sed 식
  local kind=$1 glob=$2 expr=$3 changed=0 p rel before after
  local -a sedargs
  if [ "$kind" = d ]; then sedargs=(-E "\\${SEP}${expr}${SEP}d"); else sedargs=(-E "$expr"); fi
  while IFS= read -r -d '' p; do
    rel=${p#"$STAGE"/}
    # shellcheck disable=SC2053  # glob 은 의도적으로 패턴 매칭
    [[ $rel == $glob ]] || continue
    before=$(cksum < "$p")
    # 바이트 단위(LC_ALL=C)로 돈다: UTF-8 로캘의 GNU sed 는 긴 한글 줄에서 `.*` 가 줄 끝까지 못 가 규칙이 조용히 빗나갔다(2026-10-23 실측).
    LC_ALL=C sed -i "${sedargs[@]}" "$p"
    after=$(cksum < "$p")
    [ "$before" = "$after" ] || changed=$((changed+1))
  done < <(find "$STAGE" -type f -print0)
  [ "$changed" -gt 0 ] || echo "⚠ 미적중 규칙: $kind|$glob"
}
for kind in d r; do
  if [ "$kind" = d ]; then rules=("${DELS[@]:-}"); else rules=("${RSUBS[@]:-}"); fi
  for v in "${rules[@]}"; do
    [ -n "$v" ] || continue
    g=${v%%|*}; e=${v#*|}
    { [ "$g" != "$v" ] && [ -n "$g" ] && [ -n "$e" ]; } \
      || { echo "ERROR: $kind| 규칙 형식은 $kind|<glob>|<식> 입니다: $kind|$g" >&2; exit 2; }
    apply_scoped "$kind" "$g" "$e"
  done
done
for s in "${JDELS[@]:-}"; do
  [ -n "$s" ] || continue
  command -v jq >/dev/null 2>&1 || { echo "ERROR: j| 규칙이 있는데 jq 가 없습니다 — fail-closed" >&2; exit 2; }
  if [ -f "$STAGE/settings.json" ]; then
    jq --arg s "$s" '
      if has("hooks") then .hooks |= (
        map_values(map(if has("hooks") then .hooks |= map(select((.command // "") | contains($s) | not)) else . end)
                   | map(select((has("hooks") | not) or (.hooks | length > 0))))
        | with_entries(select(.value | length > 0))
      ) else . end' "$STAGE/settings.json" > "$STAGE/settings.json.tmp" \
      && mv "$STAGE/settings.json.tmp" "$STAGE/settings.json"
  fi
done
for expr in "${SEDS[@]:-}"; do
  [ -n "$expr" ] && find "$STAGE" -type f -exec sed -i -E "$expr" {} +
done

# ── 2.5) 정제본 남기기(--stage-out): 게이트 전에 복사해 두어, 게이트가 막아도 막힌 자리를 검사할 수 있게 한다 ──
if [ "$MODE" = "--stage-out" ]; then
  mkdir -p "$STAGE_OUT"
  chmod 700 "$STAGE_OUT"   # 게이트가 막아도 남는 사본이라 본인만 읽게 한다(security 2026-10-23)
  cp -a "$STAGE/." "$STAGE_OUT/"
  echo "정제본: $STAGE_OUT ($(find "$STAGE_OUT" -type f | wc -l)파일) — 아래 게이트 결과로 끝납니다(발행 없음)."
fi

# ── 2.8) 정제 뒤 문법 게이트: 줄 삭제·치환이 코드를 깨면 막는다 (내용 미출력 — 경로만) ──
SYNTAX_BAD=0
while IFS= read -r -d '' p; do
  rel=${p#"$STAGE"/}
  ok=1
  case "$p" in
    *.py) python3 -I -c 'import ast,sys; ast.parse(open(sys.argv[1],encoding="utf-8").read())' "$p" >/dev/null 2>&1 || ok=0 ;;
    *.sh) bash -n "$p" >/dev/null 2>&1 || ok=0 ;;
    *.json)
      if command -v jq >/dev/null 2>&1; then jq empty "$p" >/dev/null 2>&1 || ok=0
      else python3 -I -c 'import json,sys; json.load(open(sys.argv[1],encoding="utf-8"))' "$p" >/dev/null 2>&1 || ok=0; fi ;;
  esac
  [ "$ok" = 1 ] || { echo "⛔ 정제 뒤 문법 깨짐: $rel"; SYNTAX_BAD=1; }
done < <(find "$STAGE" -type f -print0)
[ "$SYNTAX_BAD" = 0 ] || { echo "발행 차단 — d|·r|·j| 규칙이 코드를 깼습니다. 규칙을 고친 뒤 재실행."; exit 3; }

# ── 3) fail-closed 금지 게이트 (내용 미출력 — 파일:라인만) ──
VIOL=0
for pat in "${FORBID[@]:-}"; do
  [ -z "$pat" ] && continue
  # 패턴은 -e 로 못박는다. `-----BEGIN … PRIVATE` 처럼 `-` 로 시작하는 규칙이 grep 옵션으로 먹히면
  # rc=2 로 죽고 hits 가 비어 게이트가 조용히 통과했다(2026-09-08 검수). rc>=2 는 규칙이 깨진 것이므로
  # 통과가 아니라 즉시 차단한다(fail-closed).
  rc=0
  # -I 는 이진·잘못된 UTF-8 파일을 통째로 건너뛰어 그 안의 금지 패턴을 못 봤다(2026-10-01 감사) → -a 로 전부 본다.
  # LC_ALL=C: UTF-8 로캘에서는 한글이 낱말 글자라 `\b<이름>\b` 가 «<이름>에서» 를 못 잡아 게이트를 빠져나갔다(2026-10-23 security 실측).
  # 바이트 단위면 한글 바이트가 낱말 밖이라 영문 낱말 경계가 ASCII 기준이 된다.
  raw=$(LC_ALL=C grep -RInaE -e "$pat" "$STAGE" 2>/dev/null) || rc=$?
  if [ "$rc" -ge 2 ]; then
    echo "⛔ 금지 규칙 검사 실패 [$pat] — grep 종료코드 $rc (정규식이 깨졌거나 읽을 수 없는 파일)."
    echo "발행 차단 — 규칙을 고친 뒤 재실행. 이 상태로는 게이트가 무엇도 검사하지 못한다."
    exit 3
  fi
  hits=$(printf '%s' "$raw" | cut -d: -f1,2 | sed "s|$STAGE/||")
  if [ -n "$hits" ]; then
    VIOL=1
    echo "⛔ 금지 패턴 [$pat]:"
    while IFS= read -r l; do printf '    %s\n' "$l"; done <<< "$hits"
  fi
  # 파일 경로 이름도 같은 패턴으로 대조한다 — sed 치환은 본문만 고치므로 경로에 든 식별자는 그대로 미러에 실린다.
  rc=0
  phits=$(cd "$STAGE" && find . -mindepth 1 | sed 's|^\./||' | LC_ALL=C grep -nE -e "$pat" | cut -d: -f2-) || rc=$?
  if [ "$rc" -ge 2 ]; then
    echo "⛔ 금지 규칙 검사 실패(경로 이름) [$pat] — grep 종료코드 $rc"; exit 3
  fi
  if [ -n "$phits" ]; then
    VIOL=1
    echo "⛔ 금지 패턴이 든 파일 경로 이름 [$pat]:"
    while IFS= read -r l; do printf '    %s\n' "$l"; done <<< "$phits"
  fi
done
if [ "$VIOL" = 1 ]; then
  echo ""
  echo "발행 차단 — 위 파일을 수정하거나 규칙 파일에 x| 제외를 추가한 뒤 재실행."
  exit 3
fi

# ── 3.5) gitleaks (있으면 2차 스캔) ──
if command -v gitleaks >/dev/null 2>&1; then
  gitleaks detect --no-git -s "$STAGE" --redact -v >/dev/null 2>&1 \
    || { echo "⛔ gitleaks 검출 — 발행 차단 (gitleaks detect --no-git -s <stage>로 확인)"; exit 3; }
  GITLEAKS=OK
else
  GITLEAKS="미설치(내부 게이트만 통과)"
fi
if [ "$MODE" = "--stage-out" ]; then
  echo "✅ 게이트 통과(gitleaks: $GITLEAKS) — 정제본만 남기고 끝냅니다."
  exit 0
fi

# ── 4) 변경 요약 (수정 계획 트리 — answer-detail.md § 형식) ──
if [ -d "$TARGET" ]; then
  SUMMARY=$(rsync -rcn --delete --exclude='.git' --out-format='%o %n' "$STAGE/" "$TARGET/" \
    | awk '$1=="send"{print $2}' | sort)
  NEW=0; MOD=0
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    if [ -f "$TARGET/$f" ]; then MOD=$((MOD+1)); else NEW=$((NEW+1)); fi
  done <<< "$SUMMARY"
  DEL=$(rsync -rcn --delete --exclude='.git' --out-format='%o %n' "$STAGE/" "$TARGET/" | grep -c '^del\.' || true)
else
  SUMMARY=$(cd "$STAGE" && find . -type f | sed 's|^\./||' | sort)
  NEW=$COPIED; MOD=0; DEL=0
fi

echo "📋 공개 미러 발행 계획 — $TARGET (수정 $MOD · 신규 $NEW · 삭제 $DEL / 총 $COPIED파일, gitleaks: $GITLEAKS)"
echo "$SUMMARY" | head -20 | sed 's/^/  /'
[ "$(echo "$SUMMARY" | wc -l)" -gt 20 ] && echo "  ... ($(echo "$SUMMARY" | wc -l)개 중 20개 표시)"

# ── 5) 발행 ──
if [ "$MODE" != "--publish" ]; then
  echo ""
  echo "(dry-run — 발행하려면: bash scripts/public-export.sh --publish [대상경로])"
  exit 0
fi

# ── 5.0) 발행 대상 확인 (2026-10-01 감사) ──
# 아래 rsync 는 --delete 라 대상에 없는 파일을 지운다. 인자 오타·엉뚱한 경로가 «비어 있지 않은 일반 폴더»면
# 그 폴더가 통째로 지워지므로, 미러 표식이 없는 비어 있지 않은 폴더는 거부한다.
# 표식 = .public-export-mirror 파일(발행이 매번 써 둔다) 또는 .git 의 origin 이 공개 미러 주소.
# 기존 미러를 처음 잇는 경우엔 대상 폴더에 표식 파일을 직접 만들어 둔다(사용자 몫).
if [ -e "$TARGET" ]; then
  case "$(realpath -m "$TARGET")/" in
    "$(realpath -m "$HARNESS")"/*) echo "ERROR: 발행 대상이 하네스 자신 안입니다: $TARGET" >&2; exit 2 ;;
  esac
  if [ -n "$(ls -A "$TARGET" 2>/dev/null)" ]; then
    MIRROR_RE="${PUBLIC_MIRROR_ORIGIN_RE:-[:/]oh-my-ouroboros(\\.git)?\$}"
    origin=""
    [ -e "$TARGET/.git" ] && origin=$(git -C "$TARGET" config --get remote.origin.url 2>/dev/null || true)
    if [ ! -f "$TARGET/.public-export-mirror" ] && ! [[ "$origin" =~ $MIRROR_RE ]]; then
      echo "ERROR: $TARGET 는 비어 있지 않은데 공개 미러 표식이 없습니다 — --delete 동기화를 하면 기존 파일이 지워지므로 거부합니다." >&2
      echo "  미러가 맞다면 그 폴더에 .public-export-mirror 파일을 만들거나(.git origin 이 공개 미러 주소여도 됨) 다시 실행하십시오." >&2
      exit 2
    fi
  fi
fi

rsync -rc --delete --exclude='.git' "$STAGE/" "$TARGET/"
cd "$TARGET"
[ -d .git ] || git init -q -b main
git config user.name "DaeSeokSong"
git config user.email "$NOREPLY"
git add -A
if git diff --cached --quiet; then
  echo "변경 없음 — 커밋 생략."
else
  git commit -q -m "sync: $(date +%F) harness mirror update"
  echo "✅ 커밋 완료: $(git log --oneline -1)"
fi
echo "push는 직접 실행하세요: git -C $TARGET push"
