#!/usr/bin/env bash
# evidence-ls.sh — 완료 선언 증거 출력 (research "리서치 완료"·tutor "이해도 확인 완료"·paper-read Step 7 등, 13라운드 Grok·렌즈3)
#
# 왜: `ls -l` 한 줄은 채팅에 손으로 적을 수 있다. 파일마다 sha256 을 찍어 두면 사용자가 같은 명령으로 재계산해 대조할 수 있고(qa 8항 "해시는 main 재계산" 과 같은 원칙),
#     없는 파일·빈 파일·디렉터리는 FAIL 로 드러난다. 자기선언을 완전히 막지는 못한다(출력 자체를 위조할 수는 있다) — 위조 비용을 올리고 사후 대조를 가능하게 하는 장치이며,
#     선언 보고에 이 출력 **원문**이 없으면 그 선언은 무효(launch-set.sh verify·spawn-tree.sh check 와 같은 규약).
#     또 하나의 한계(14라운드 렌즈2): "올바른 파일을 인자로 넘겼는지"는 검증하지 않는다 — 출력의 절대경로가 규약이 정한 경로(예: `{MEMORY_ROOT}/papers/{논문명}/review.md`)와
#     같은지는 보고를 읽는 쪽(사용자·main)이 대조한다.
# 사용: evidence-ls.sh <file>...
# 출력: 파일마다 `절대경로 \t bytes \t sha256 \t mtime(ISO)` + 마지막 줄 `EVIDENCE: OK n` (exit 0) / `EVIDENCE: FAIL` (하나라도 없음·빈 파일·디렉터리, exit 1)
set -uf
export LC_ALL=C
[ $# -ge 1 ] || { echo "usage: evidence-ls.sh <file>..."; exit 2; }
BAD=0
for f in "$@"; do
    if [ -f "$f" ] && [ -s "$f" ]; then
        printf '%s\t%s\t%s\t%s\n' "$(readlink -f -- "$f")" "$(stat -c %s -- "$f")" "$(sha256sum -- "$f" | cut -c1-64)" "$(date -Iseconds -r "$f")"
    else
        echo "FAIL 없음/빈 파일/디렉터리: $f"; BAD=1
    fi
done
if [ "$BAD" -eq 0 ]; then echo "EVIDENCE: OK $#"; exit 0; else echo "EVIDENCE: FAIL"; exit 1; fi
