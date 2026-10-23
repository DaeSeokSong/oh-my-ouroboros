#!/usr/bin/env python3
"""oversight.tsv 의 5열 행에 6번째 열(주체)을 붙인다. 1회용 데이터 교정. (2026-09-14)

왜 스크립트인가: 5열 행 13개는 `주체` 열이 생기기 전(09-07~09-08)에 손으로 적힌 것이고, 그 13행
때문에 형식 검사가 매 세션 경보를 낸다. 값은 전부 main 이 적은 행이라 빈칸이 아니라 `main` 을 채운다.
다른 행은 손대지 않는다 — 6열 행의 게이트 어휘 드리프트는 데이터가 아니라 판정 문제라 여기 범위 밖이다.

사용: python3 scripts/oversight-fix-5col.py [--apply]   (기본은 --dry-run)
"""

import sys
from pathlib import Path

TSV = Path.home() / ".claude/_audit/oversight.tsv"
FILL = "main"


def main() -> int:
    apply = "--apply" in sys.argv[1:]
    if not TSV.exists():
        print(f"없음: {TSV}")
        return 1

    lines = TSV.read_text(encoding="utf-8").splitlines()
    out, targets = [], []
    for i, line in enumerate(lines, 1):
        if line and line.count("\t") == 4:  # 5열
            targets.append(i)
            out.append(line + "\t" + FILL)
        else:
            out.append(line)

    print(f"대상 {len(targets)}행: {targets}")
    if not apply:
        print("(dry-run — 변경 없음. 적용하려면 --apply)")
        return 0
    if targets:
        # 원자적 교체 — 부분 기록된 원장을 남기지 않는다.
        tmp = TSV.with_suffix(".tsv.tmp")
        tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
        tmp.replace(TSV)
        print(f"적용 완료: {len(targets)}행에 '{FILL}' 추가")
    return 0


if __name__ == "__main__":
    sys.exit(main())
