"""git clean 필터 — settings.json 의 상위 "model" 키를 diff 계산 전에 지운다.

작업 트리 파일 자체는 건드리지 않는다 — git 이 add/diff/status 에 쓸 내용만 stdin→stdout 으로
변환한다(git clean 필터 규약). 등록: scripts/setup-harness.sh 섹션 3.5, `.gitattributes`.
REF: knowledge/harness/code-history/scripts__git-filter-nomodel-clean.py.md
"""
import json
import sys

DROPPED_KEYS = ("model", "modelSettings")


def main() -> int:
    text = sys.stdin.read()
    try:
        d = json.loads(text)
    except (ValueError, RecursionError):
        sys.stdout.write(text)
        return 0
    if not isinstance(d, dict):
        sys.stdout.write(text)
        return 0
    for key in DROPPED_KEYS:
        d.pop(key, None)
    json.dump(d, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
