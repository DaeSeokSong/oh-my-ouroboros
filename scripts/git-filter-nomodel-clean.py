"""git clean 필터 — settings.json 의 상위 "model" 키를 diff 계산 전에 지운다.

왜 (2026-09-28 사용자 결정): /model 명령이 "새 세션 기본값"을 gitignored settings.local.json
이 아니라 추적되는 settings.json 에 직접 쓴다. 세션마다 모델을 바꾸는 것은 흔한 일인데 그때마다
git status/diff 에 뜨는 것이 소음이다. settings.local.json pin(있으면)이 재시작 시 이기므로
(rules/model-assignment.md) settings.json 의 "model" 키는 버려도 실제 동작이 바뀌지 않는다.

"modelSettings" 키도 같이 지운다 (2026-11-12 사용자 결정 «settings.json에서는 무시해»): 모델별 effort
기본값(예: modelSettings.<모델 ID>.effortLevel)도 사용자가 화면에서 바꿀 때마다 이 파일에 쓰이고,
추적되면 모델 ID 가 박힌 값이 다른 서버로 전파된다. 서브에이전트의 모델 · effort 는 agents/*.md 머리와
rules/model-assignment.md 가 정하므로 이 키를 버려도 위임 동작은 바뀌지 않는다. 상위 "effortLevel"
(모델과 무관한 기본 effort)은 지우지 않는다(추적 유지).

작업 트리 파일 자체는 건드리지 않는다 — git 이 add/diff/status 에 쓸 내용만 stdin→stdout 으로
변환한다(git clean 필터 규약). 등록: scripts/setup-harness.sh 섹션 3.5, `.gitattributes`.
"""
import json
import sys

# git 이 비교에서 빼는 상위 키. 사용자가 세션마다 바꾸는 값이라 추적하지 않는다.
DROPPED_KEYS = ("model", "modelSettings")


def main() -> int:
    text = sys.stdin.read()
    try:
        d = json.loads(text)
    except (ValueError, RecursionError):
        sys.stdout.write(text)  # 파싱 불가하면 원문 그대로(다른 손상을 만들지 않는다)
        return 0
    if not isinstance(d, dict):
        sys.stdout.write(text)  # 최상위가 객체가 아니면 지울 키가 없다. 원문 그대로
        return 0
    for key in DROPPED_KEYS:
        d.pop(key, None)
    json.dump(d, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
