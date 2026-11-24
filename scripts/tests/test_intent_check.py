"""intent_check.py 회귀 테스트: 통과 의뢰서 · 제목 변형 · 절 누락 · 번호 불일치 · 범위 밖(누락 · 빈칸 · 없음 · 다른 절) ·
상태 줄 · 코드펜스 속 제목 · 템플릿 원본 · 실물 의뢰서 · 입력 방어(5MB · 비UTF-8 · 파일 없음 · 선형 시간).

실행: uv run --no-project --with pytest python -m pytest scripts/tests/test_intent_check.py -q
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import intent_check as ic

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "skills" / "intent" / "templates" / "intent.md"

GOOD = """# intent: 시험

- 상태: 초안
- 발안자: 사용자

## 1. 문제
목록이 없다.

> «원문»

## 2. 제안 결과
- 성공 기준 1: pytest 통과

### 범위 밖
- 모바일 화면

## 3. 영향 사용자·시스템
운영자.

## 4. 제약
push 는 사용자.

## 5. 열린 질문
- [ ] 정렬

## 6. 전제 (상속·재사용·기본값)
| 선택 | 무엇 | 달라지면 | 확인 |
|---|---|---|---|
| 정렬 | 최근 순 | 예 | 미확인 |

## 결정 이력
- 없음
"""


def run(tmp_path, text, capsys):
    f = tmp_path / "intent.md"
    f.write_text(text, encoding="utf-8")
    code = ic.main(["intent_check.py", str(f)])
    return code, capsys.readouterr().out.splitlines()


def test_good_intent_passes(tmp_path, capsys):
    code, out = run(tmp_path, GOOD, capsys)
    assert code == 0 and out[-1] == "RESULT: PASS"
    assert len(out) == 4 and all(line.startswith("[OK]") for line in out[:-1])


def test_title_variants_from_real_intents_pass(tmp_path, capsys):
    text = (GOOD.replace("## 3. 영향 사용자·시스템", "## 3. 영향")
            .replace("## 5. 열린 질문", "## 5. 열린 질문과 결정 이력")
            .replace("## 6. 전제 (상속·재사용·기본값)", "## 6) 전제"))
    code, out = run(tmp_path, text, capsys)
    assert code == 0, out


def test_section_order_does_not_matter(tmp_path, capsys):
    six = GOOD[GOOD.index("## 6."):GOOD.index("## 결정 이력")]
    text = GOOD.replace(six, "") + "\n## 개정 1 (2026-11-24)\n바꿈.\n\n" + six
    code, out = run(tmp_path, text, capsys)
    assert code == 0, out


def test_missing_section_fails(tmp_path, capsys):
    code, out = run(tmp_path, GOOD.replace("## 4. 제약", "## 4. 다른 제목"), capsys)
    assert code == 1 and out[-1] == "RESULT: FAIL"
    assert any("필수 절 누락" in x and "4. 제약" in x for x in out)


def test_wrong_number_fails(tmp_path, capsys):
    code, out = run(tmp_path, GOOD.replace("## 4. 제약", "## 7. 제약"), capsys)
    assert code == 1 and any("4. 제약" in x for x in out)


def test_unnumbered_title_fails(tmp_path, capsys):
    code, out = run(tmp_path, GOOD.replace("## 1. 문제", "## 문제"), capsys)
    assert code == 1 and any("1. 문제" in x for x in out)


def test_scope_out_missing_fails(tmp_path, capsys):
    code, out = run(tmp_path, GOOD.replace("### 범위 밖\n- 모바일 화면\n", ""), capsys)
    assert code == 1 and any("범위 밖 소절 누락" in x for x in out)


def test_scope_out_placeholder_fails_but_none_passes(tmp_path, capsys):
    code, out = run(tmp_path, GOOD.replace("- 모바일 화면", "> 안내만\n- TBD"), capsys)
    assert code == 1 and any("범위 밖 소절이 비어 있음" in x for x in out)
    code, out = run(tmp_path, GOOD.replace("- 모바일 화면", "없음"), capsys)
    assert code == 0 and out[-1] == "RESULT: PASS"


def test_scope_out_in_other_section_fails(tmp_path, capsys):
    text = GOOD.replace("### 범위 밖\n- 모바일 화면\n", "").replace("push 는 사용자.", "push 는 사용자.\n### 범위 밖\n- 모바일")
    code, out = run(tmp_path, text, capsys)
    assert code == 1 and any("범위 밖 소절 누락" in x for x in out)


def test_scope_out_after_other_subsections_passes(tmp_path, capsys):
    text = GOOD.replace("### 범위 밖", "### W1 묶음\n- 기준\n\n### 범위 밖")
    code, out = run(tmp_path, text, capsys)
    assert code == 0, out


def test_missing_section_two_reports_scope(tmp_path, capsys):
    code, out = run(tmp_path, GOOD.replace("## 2. 제안 결과", "## 2. 다른 것"), capsys)
    assert code == 1 and any("2. 제안 결과 절이 없음" in x for x in out)


def test_status_line_missing_fails(tmp_path, capsys):
    code, out = run(tmp_path, GOOD.replace("- 상태: 초안\n", ""), capsys)
    assert code == 1 and any("상태" in x and x.startswith("[FAIL]") for x in out)
    code, out = run(tmp_path, GOOD.replace("- 상태: 초안", "- 상태:"), capsys)
    assert code == 1


def test_status_line_inside_body_does_not_count(tmp_path, capsys):
    text = GOOD.replace("- 상태: 초안\n", "").replace("운영자.", "- 상태: 초안")
    code, out = run(tmp_path, text, capsys)
    assert code == 1 and any("상태" in x and x.startswith("[FAIL]") for x in out)


def test_headings_inside_code_fence_are_ignored(tmp_path, capsys):
    text = GOOD.replace("## 4. 제약\npush 는 사용자.", "```\n## 4. 제약\n```")
    code, out = run(tmp_path, text, capsys)
    assert code == 1 and any("4. 제약" in x for x in out)
    fenced_scope = GOOD.replace("### 범위 밖\n- 모바일 화면\n", "```\n### 범위 밖\n- 모바일 화면\n```\n")
    code, out = run(tmp_path, fenced_scope, capsys)
    assert code == 1 and any("범위 밖 소절 누락" in x for x in out)


def test_template_fails_only_on_scope_out(tmp_path, capsys):
    code, out = run(tmp_path, TEMPLATE.read_text(encoding="utf-8"), capsys)
    fails = [x for x in out if x.startswith("[FAIL]")]
    assert code == 1 and len(fails) == 1 and "범위 밖" in fails[0]


def test_template_titles_match_script_constants():
    lines = ic.strip_comments_and_fences(TEMPLATE.read_text(encoding="utf-8"))
    titles = [line[3:].strip() for line in lines if line.startswith("## ")]
    for num, name in ic.REQUIRED_SECTIONS:
        assert any(t.startswith(f"{num}. {name}") for t in titles), (num, name)


def test_real_intent_with_scope_out_passes(capsys):
    code = ic.main(["intent_check.py", str(ROOT / "intent" / "2026-11-24-harness-review-six-items.md")])
    assert code == 0, capsys.readouterr().out


def test_unclosed_comments_and_long_lines_are_linear(tmp_path, capsys):
    text = "<!-- a " * 20000 + "\n## 1" + " " * 50000 + "x\n" + GOOD
    t0 = time.perf_counter()
    run(tmp_path, text, capsys)
    assert time.perf_counter() - t0 < 1.0


def test_huge_title_number_is_mismatch_not_crash(tmp_path, capsys):
    code, out = run(tmp_path, GOOD.replace("## 4. 제약", "## " + "9" * 5000 + ". 제약"), capsys)
    assert code == 1 and out[-1] == "RESULT: FAIL" and any("4. 제약" in x for x in out)


def test_unexpected_error_exits_2_without_body(tmp_path, capsys, monkeypatch):
    def boom(text):
        raise RuntimeError("secret-body")
    monkeypatch.setattr(ic, "check", boom)
    f = tmp_path / "i.md"
    f.write_text(GOOD, encoding="utf-8")
    assert ic.main(["intent_check.py", str(f)]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and "RuntimeError" in captured.err and "secret-body" not in captured.err


def test_oversize_file_exits_2(tmp_path):
    f = tmp_path / "big.md"
    f.write_bytes(b"a" * (ic.MAX_BYTES + 1))
    assert ic.main(["intent_check.py", str(f)]) == 2


def test_non_utf8_exits_2(tmp_path):
    f = tmp_path / "latin.md"
    f.write_bytes("## 1. 문제\n".encode() + b"\xff\xfe\n")
    assert ic.main(["intent_check.py", str(f)]) == 2


def test_missing_file_and_bad_args_exit_2(tmp_path):
    assert ic.main(["intent_check.py", str(tmp_path / "none.md")]) == 2
    assert ic.main(["intent_check.py"]) == 2
