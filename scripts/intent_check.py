"""의뢰서(intent) 양식 검사기: `skills/intent/templates/intent.md` 양식을 지켰는지 기계로 판정한다.

무엇을: 의뢰서 마크다운 한 개(5MB 이하)를 읽어 세 가지를 판정한다.
  1) 필수 절 여섯 개(`## 1. 문제` ~ `## 6. 전제`)가 번호와 이름 모두 맞게 있는가
  2) «제안 결과»(2절) 안에 `### 범위 밖` 소절이 있고 내용이 있는가(«없음» 도 내용)
  3) 첫 `## ` 제목 앞 머리에 값이 있는 `상태:` 줄이 있는가
어떻게: 코드펜스 안 줄과 HTML 주석을 지운 뒤(선형 시간, spec_check 공용 함수) `## ` 제목을 모은다.
  이름은 앞부분 일치로 본다. 번호는 템플릿 번호와 같아야 한다.
  절 순서는 보지 않는다. 범위 밖 내용 판정은 spec_check 와 같다.
  출력은 항목별 한 줄과 마지막 `RESULT: PASS|FAIL` 이고 종료 코드는 0 / 1, 인자 오류 · 파일 없음 ·
  5MB 초과 · 비UTF-8 은 2다. 검사기 결함도 2다.
한계: 2026-11-24 이전 의뢰서는 대부분 범위 밖 소절이 없어 FAIL 이 정상이다(새 의뢰서용 검사).
  읽기 전용이며 표준 라이브러리와 같은 폴더의 spec_check 만 쓴다.
REF: knowledge/harness/code-history/scripts__intent_check.py.md
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from spec_check import MAX_BYTES, scope_out_body, strip_comments_and_fences, substantive

# NEVER: 템플릿(skills/intent/templates/intent.md)의 번호 · 절 이름과 따로 바꾸지 않는다(시험이 대조한다).
REQUIRED_SECTIONS = ((1, "문제"), (2, "제안 결과"), (3, "영향"), (4, "제약"), (5, "열린 질문"), (6, "전제"))
# WHY: 번호는 세 자리까지만 본다. 아주 긴 숫자는 int() 가 ValueError 를 내므로(4,300자 상한) 번호 불일치로 다룬다.
TITLE = re.compile(r"^([0-9]{1,3})\s*[.)]\s*(\S.*)$")
STATUS_LINE = re.compile(r"^\s*(?:[-*+]\s+)?상태\s*:\s*\S")


def find_section(sections: list[tuple[str, list[str]]], num: int, name: str) -> list[str] | None:
    for title, body in sections:
        m = TITLE.match(title)
        if m and int(m.group(1)) == num and m.group(2).startswith(name):
            return body
    return None


def check(text: str) -> list[tuple[bool, str]]:
    head: list[str] = []
    sections: list[tuple[str, list[str]]] = []
    for line in strip_comments_and_fences(text):
        if line.startswith("## "):
            sections.append((line[3:].strip(), []))
        elif sections:
            sections[-1][1].append(line)
        else:
            head.append(line)
    results: list[tuple[bool, str]] = []

    missing = [f"{n}. {name}" for n, name in REQUIRED_SECTIONS if find_section(sections, n, name) is None]
    if missing:
        results.append((False, "필수 절 누락: " + " · ".join(missing)))
    else:
        results.append((True, f"필수 절 {len(REQUIRED_SECTIONS)}개 모두 있음"))

    scope = find_section(sections, 2, "제안 결과")
    out_body = scope_out_body(scope) if scope is not None else None
    if scope is None:
        results.append((False, "범위 밖 소절을 볼 수 없음(2. 제안 결과 절이 없음)"))
    elif out_body is None:
        results.append((False, "범위 밖 소절 누락(2. 제안 결과 절 안에 `### 범위 밖`)"))
    elif not substantive(out_body):
        results.append((False, "범위 밖 소절이 비어 있음(없으면 «없음» 과 까닭을 적는다)"))
    else:
        results.append((True, "범위 밖 소절에 내용이 있음"))

    if any(STATUS_LINE.match(line) for line in head):
        results.append((True, "머리에 상태 줄이 있음"))
    else:
        results.append((False, "머리에 `상태:` 줄이 없음(첫 `## ` 제목 앞)"))
    return results


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] in ("-h", "--help"):
        print("사용법: intent_check.py <의뢰서 파일>", file=sys.stderr)
        return 2
    path = Path(argv[1])
    try:
        if path.stat().st_size > MAX_BYTES:
            print(f"파일이 너무 큼(상한 {MAX_BYTES} 바이트): {path}", file=sys.stderr)
            return 2
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        print(f"파일을 읽을 수 없음: {path} ({e})", file=sys.stderr)
        return 2
    try:
        results = check(text)
    except Exception as e:  # noqa: BLE001
        print(f"검사 중 예기치 않은 오류: {type(e).__name__}", file=sys.stderr)
        return 2
    for ok, msg in results:
        print(f"[{'OK' if ok else 'FAIL'}] {msg}")
    passed = all(ok for ok, _ in results)
    print(f"RESULT: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
