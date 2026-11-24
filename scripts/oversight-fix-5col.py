#!/usr/bin/env python3
"""oversight.tsv 의 5열 행에 6번째 열(주체)을 붙인다. 1회용 데이터 교정.

사용: python3 scripts/oversight-fix-5col.py [--apply]   (기본은 --dry-run)
REF: knowledge/harness/code-history/scripts__oversight-fix-5col.py.md
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
        if line and line.count("\t") == 4:
            targets.append(i)
            out.append(line + "\t" + FILL)
        else:
            out.append(line)

    print(f"대상 {len(targets)}행: {targets}")
    if not apply:
        print("(dry-run — 변경 없음. 적용하려면 --apply)")
        return 0
    if targets:
        tmp = TSV.with_suffix(".tsv.tmp")
        tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
        tmp.replace(TSV)
        print(f"적용 완료: {len(targets)}행에 '{FILL}' 추가")
    return 0


if __name__ == "__main__":
    sys.exit(main())
