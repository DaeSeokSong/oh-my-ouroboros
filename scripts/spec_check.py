"""설계서(SRS) 절 구성 검사기: `skills/intent/templates/spec.md` 양식을 지켰는지 기계로 판정한다.

무엇을: 명세 마크다운 한 개(5MB 이하)를 읽어 네 가지를 판정한다.
  1) 필수 절 제목 9개가 전부 있는가
  2) «목적과 범위» 절 안에 `### 범위 밖` 소절이 있고 내용이 있는가(«없음» 도 내용)
  3) 본문의 모든 FR-n · NFR-n 이 추적표에 있고, 추적표에만 있는 번호는 없는가
  4) «검증 요구» 절에 안내 문구가 아닌 실내용이 있는가
어떻게: `## ` 제목 줄(코드펜스 밖)에서 번호 접두를 떼어 절을 나누고, 안내 줄(`>` 로 시작) ·
  HTML 주석 · 표 머리와 구분선 · `(예시)` 행 · 빈 칸뿐인 행 · 자리 표시(대소문자 무시: tbd · todo · n/a · 미정 · `-` ·
  번호만 있는 줄 · 요구 번호 칸만 있는 표 행)를 뺀 나머지를 «실내용» 으로 본다.
  주석 제거와 표 구분선 판정은 정규식 역추적을 피해 선형 시간으로 처리한다(입력 폭주 방어).
  출력은 항목별 한 줄과 마지막 `RESULT: PASS|FAIL` 이고 종료 코드는 0 / 1, 인자 오류 · 파일 없음은 2다.
  이 검사기는 읽기 전용이며 표준 라이브러리만 쓴다.
REF: knowledge/harness/code-history/scripts__spec_check.py.md
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# NEVER: 템플릿(skills/intent/templates/spec.md)의 절 제목과 따로 바꾸지 않는다(시험이 대조한다).
REQUIRED_SECTIONS = (
    "목적과 범위", "행위자", "고정 원칙", "기능 요구", "비기능 요구",
    "추적표", "위임받아 정한 것과 남은 확인", "검증 요구", "다음 단계",
)
OPTIONAL_SECTIONS = ("화면 지도", "화면 요구", "기존 요구 처리")

TRACE_SECTION = "추적표"
VERIFY_SECTION = "검증 요구"
EXAMPLE_MARK = "(예시)"
REQ_ID = re.compile(r"(?<![A-Za-z])(N?FR)-(\d+)")
NUM_PREFIX = re.compile(r"^\d+\s*[.)]\s*")
SCOPE_OUT_SUBSECTION = "범위 밖"
SCOPE_SECTION = "목적과 범위"
MAX_BYTES = 5 * 1024 * 1024
# NEVER: «없음» 을 넣지 않는다(범위 밖 소절에서 실내용이다).
PLACEHOLDERS = frozenset({"", "tbd", "todo", "n/a", "미정", "-"})
LIST_MARK = re.compile(r"^(?:[-*+]|\d+[.)])(?:\s+|$)")


def is_table_sep(s: str) -> bool:
    s = s.strip()
    return "--" in s and not set(s) - set("|-: ")


def drop_html_comments(text: str) -> str:
    out, i = [], 0
    while True:
        start = text.find("<!--", i)
        end = text.find("-->", start + 4) if start >= 0 else -1
        if end < 0:
            out.append(text[i:])
            return "".join(out)
        out.append(text[i:start])
        out.append("\n" * text.count("\n", start, end))
        i = end + 3


def strip_comments_and_fences(text: str) -> list[str]:
    text = drop_html_comments(text)
    out, in_fence = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            out.append("")
        else:
            out.append("" if in_fence else line)
    return out


def split_sections(lines: list[str]) -> tuple[list[str], list[tuple[str, list[str]]]]:
    head: list[str] = []
    sections: list[tuple[str, list[str]]] = []
    for line in lines:
        if line.startswith("## "):
            sections.append((NUM_PREFIX.sub("", line[3:].strip()), []))
        elif sections:
            sections[-1][1].append(line)
        else:
            head.append(line)
    return head, sections


def real_lines(lines: list[str]) -> list[str]:
    out = []
    for i, line in enumerate(lines):
        s = line.strip()
        if not s or s.startswith(">") or EXAMPLE_MARK in s or is_table_sep(s):
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if s.startswith("|") and is_table_sep(nxt):
            continue
        if not re.sub(r"[|\-*+\[\]xX\s]", "", s):
            continue
        out.append(line)
    return out


def substantive(lines: list[str]) -> list[str]:
    out = []
    for line in real_lines(lines):
        s = line.strip()
        if s.startswith("|"):
            cells = [c.strip().lower() for c in s.strip("|").split("|")]
            body = cells[1:] if len(cells) >= 2 else cells
            if all(c in PLACEHOLDERS for c in body):
                continue
        elif LIST_MARK.sub("", s).strip().lower() in PLACEHOLDERS:
            continue
        out.append(line)
    return out


def scope_out_body(section_lines: list[str]) -> list[str] | None:
    body: list[str] | None = None
    for line in section_lines:
        if line.startswith("#"):
            if body is not None:
                break
            if line.startswith("### ") and NUM_PREFIX.sub("", line[4:].strip()) == SCOPE_OUT_SUBSECTION:
                body = []
        elif body is not None:
            body.append(line)
    return body


def find_ids(lines: list[str]) -> set[str]:
    return {f"{m.group(1)}-{int(m.group(2))}" for line in lines for m in REQ_ID.finditer(line)}


def table_first_cells(lines: list[str]) -> list[str]:
    cells = []
    for line in real_lines(lines):
        s = line.strip()
        if s.startswith("|"):
            cells.append(s.strip("|").split("|", 1)[0])
    return cells


def check(text: str) -> list[tuple[bool, str]]:
    lines = strip_comments_and_fences(text)
    head, sections = split_sections(lines)
    titles = [t for t, _ in sections]
    results: list[tuple[bool, str]] = []

    missing = [t for t in REQUIRED_SECTIONS if t not in titles]
    if missing:
        results.append((False, "필수 절 누락: " + " · ".join(missing)))
    else:
        results.append((True, f"필수 절 {len(REQUIRED_SECTIONS)}개 모두 있음"))

    scope = next((b for t, b in sections if t == SCOPE_SECTION), None)
    if scope is not None:
        out_body = scope_out_body(scope)
        if out_body is None:
            results.append((False, "범위 밖 소절 누락(목적과 범위 절 안에 `### 범위 밖`)"))
        elif not substantive(out_body):
            results.append((False, "범위 밖 소절이 비어 있음(없으면 «없음» 이라고 적는다)"))
        else:
            results.append((True, "범위 밖 소절에 내용이 있음"))

    trace_lines = next((b for t, b in sections if t == TRACE_SECTION), [])
    body_lines = head + [x for t, b in sections if t != TRACE_SECTION for x in b]
    body_ids = find_ids(real_lines(body_lines))
    trace_ids = find_ids(table_first_cells(trace_lines))
    no_trace = sorted(body_ids - trace_ids)
    no_body = sorted(trace_ids - body_ids)
    if no_trace:
        results.append((False, "추적표에 없는 번호: " + " · ".join(no_trace)))
    if no_body:
        results.append((False, "본문에 없는 추적표 번호: " + " · ".join(no_body)))
    if not no_trace and not no_body:
        results.append((True, f"요구 번호 {len(body_ids)}개가 본문과 추적표에서 일치함"))

    verify = next((b for t, b in sections if t == VERIFY_SECTION), None)
    if verify is None:
        results.append((False, "검증 요구 절이 없음"))
    elif not substantive(verify):
        results.append((False, "검증 요구 절이 비어 있음(안내 문구 · 예시 행 · 자리 표시뿐)"))
    else:
        results.append((True, "검증 요구 절에 내용이 있음"))
    return results


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] in ("-h", "--help"):
        print("사용법: spec_check.py <명세 파일>", file=sys.stderr)
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
    results = check(text)
    for ok, msg in results:
        print(f"[{'OK' if ok else 'FAIL'}] {msg}")
    passed = all(ok for ok, _ in results)
    print(f"RESULT: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
