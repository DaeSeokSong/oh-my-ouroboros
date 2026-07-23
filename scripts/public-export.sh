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
#
# 사용:
#   bash scripts/public-export.sh                      # dry-run: 스테이징+게이트+변경 요약만
#   bash scripts/public-export.sh --publish [대상경로]  # 미러 갱신+커밋 (push는 사용자 직접)
# 기본 대상: ~/workspace/oh-my-ouroboros (인자로 변경 가능 — repo 이름 비종속)
set -euo pipefail

HARNESS="$HOME/.claude"
RULES="$HARNESS/config/public-export-rules.txt"
MODE="${1:-dry-run}"
TARGET="${2:-$HOME/workspace/oh-my-ouroboros}"
NOREPLY="DaeSeokSong@users.noreply.github.com"

[ -f "$RULES" ] || { echo "ERROR: 규칙 파일 없음: $RULES" >&2; exit 2; }

STAGE=$(mktemp -d "${TMPDIR:-/tmp}/pubexport.XXXXXX")
trap 'rm -rf "$STAGE"' EXIT

# ── 규칙 파싱 ──
ALLOW=(); EXCLUDE=(); SEDS=(); FORBID=()
while IFS= read -r line; do
  case "$line" in
    a\|*) ALLOW+=("${line#a|}") ;;
    x\|*) EXCLUDE+=("${line#x|}") ;;
    s\|*) SEDS+=("${line#s|}") ;;
    f\|*) FORBID+=("${line#f|}") ;;
  esac
done < "$RULES"

# ── 1) 스테이징: git 추적 파일만, allowlist 교집합 − exclude ──
cd "$HARNESS"
COPIED=0
while IFS= read -r f; do
  skip=0
  for x in "${EXCLUDE[@]:-}"; do [ -n "$x" ] && [[ "$f" == "$x" || "$f" == "$x"/* ]] && skip=1 && break; done
  [ "$skip" = 1 ] && continue
  mkdir -p "$STAGE/$(dirname "$f")"
  cp "$f" "$STAGE/$f"
  COPIED=$((COPIED+1))
done < <(git ls-files -- "${ALLOW[@]}")

# 공개 전용 파일 (public/ → 루트로)
for pf in README.md LICENSE CONTRIBUTING.md; do
  [ -f "$HARNESS/public/$pf" ] && cp "$HARNESS/public/$pf" "$STAGE/$pf"
done

# ── 2) sanitize 치환 ──
for expr in "${SEDS[@]:-}"; do
  [ -n "$expr" ] && find "$STAGE" -type f -exec sed -i -E "$expr" {} +
done

# ── 3) fail-closed 금지 게이트 (내용 미출력 — 파일:라인만) ──
VIOL=0
for pat in "${FORBID[@]:-}"; do
  [ -z "$pat" ] && continue
  hits=$(grep -RInE "$pat" "$STAGE" 2>/dev/null | cut -d: -f1,2 | sed "s|$STAGE/||") || true
  if [ -n "$hits" ]; then
    VIOL=1
    echo "⛔ 금지 패턴 [$pat]:"
    echo "$hits" | sed 's/^/    /'
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
