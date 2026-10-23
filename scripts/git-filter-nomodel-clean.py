#!/usr/bin/env python3
"""git clean 필터 — settings.json 의 상위 "model" 키를 diff 계산 전에 지운다.

왜 (2026-09-28 사용자 결정): /model 명령이 "새 세션 기본값"을 gitignored settings.local.json
이 아니라 추적되는 settings.json 에 직접 쓴다. 세션마다 모델을 바꾸는 것은 흔한 일인데 그때마다
git status/diff 에 뜨는 것이 소음이다. settings.local.json pin(있으면)이 재시작 시 이기므로
(rules/model-assignment.md) settings.json 의 "model" 키는 버려도 실제 동작이 바뀌지 않는다.

작업 트리 파일 자체는 건드리지 않는다 — git 이 add/diff/status 에 쓸 내용만 stdin→stdout 으로
변환한다(git clean 필터 규약). 등록: scripts/setup-harness.sh 섹션 3.5, `.gitattributes`.
"""
import json
import sys


def main() -> int:
    text = sys.stdin.read()
    try:
        d = json.loads(text)
    except Exception:
        sys.stdout.write(text)  # 파싱 불가하면 원문 그대로(다른 손상을 만들지 않는다)
        return 0
    d.pop("model", None)
    json.dump(d, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
