"""spec_check.py 회귀 테스트: 통과 명세 · 절 누락 · 추적표 누락 · 추적표 잉여 · 빈 검증 요구 · 템플릿 원본 · 파일 없음.

실행: uv run --no-project --with pytest python -m pytest scripts/tests/test_spec_check.py -q
"""
import re
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import spec_check as sc

TEMPLATE = Path(__file__).resolve().parents[2] / "skills" / "intent" / "templates" / "spec.md"

GOOD = """# 설계서: 시험

## 1. 목적과 범위
목록 화면을 만든다.
### 범위 밖
- 모바일

## 2. 행위자
운영자.

## 3. 고정 원칙
- 발사는 사용자가 한다.

## 4. 기능 요구
| 번호 | 요구 |
|---|---|
| FR-1 | 목록을 연다 |
| FR-2 | 상세를 연다 |

## 5. 비기능 요구
| 번호 | 요구 |
|---|---|
| NFR-1 | 2초 이내 |

## 6. 추적표
| 요구 번호 | 근거 | 검증 방법 |
|---|---|---|
| FR-1 | 의뢰서 2절 | test_list |
| FR-2 | 의뢰서 2절 | test_detail |
| NFR-1 | 사용자 원문 | 시간 측정 |

## 7. 위임받아 정한 것과 남은 확인
정렬은 최근 순.

## 8. 검증 요구
`pytest -q` 가 전부 통과한다.

## 9. 다음 단계
1. plan.md 작성
"""


def run(tmp_path, text, capsys):
    f = tmp_path / "spec.md"
    f.write_text(text, encoding="utf-8")
    code = sc.main(["spec_check.py", str(f)])
    return code, capsys.readouterr().out.splitlines()


def test_good_spec_passes(tmp_path, capsys):
    code, out = run(tmp_path, GOOD, capsys)
    assert code == 0 and out[-1] == "RESULT: PASS"
    assert all(line.startswith("[OK]") for line in out[:-1])


def test_missing_section_fails(tmp_path, capsys):
    code, out = run(tmp_path, GOOD.replace("## 3. 고정 원칙", "## 3. 다른 제목"), capsys)
    assert code == 1 and out[-1] == "RESULT: FAIL"
    assert any("필수 절 누락" in x and "고정 원칙" in x for x in out)


def test_id_missing_from_trace_fails(tmp_path, capsys):
    code, out = run(tmp_path, GOOD.replace("| NFR-1 | 사용자 원문 | 시간 측정 |\n", ""), capsys)
    assert code == 1
    assert any("추적표에 없는 번호" in x and "NFR-1" in x for x in out)


def test_id_only_in_trace_fails(tmp_path, capsys):
    text = GOOD.replace("| FR-2 | 의뢰서 2절 | test_detail |",
                        "| FR-2 | 의뢰서 2절 | test_detail |\n| FR-9 | 의뢰서 3절 | 없음 |")
    code, out = run(tmp_path, text, capsys)
    assert code == 1
    assert any("본문에 없는 추적표 번호" in x and "FR-9" in x for x in out)


def test_empty_verification_fails(tmp_path, capsys):
    text = GOOD.replace("`pytest -q` 가 전부 통과한다.", "> 안내: 무엇을 돌려 어떤 결과면 통과인지 적는다.\n\n| 대상 | 명령 |\n|---|---|\n| (예시) FR-1 | pytest |")
    code, out = run(tmp_path, text, capsys)
    assert code == 1
    assert any("검증 요구 절이 비어 있음" in x for x in out)


def test_template_itself_fails_on_scope_out_and_verification(tmp_path, capsys):
    code, out = run(tmp_path, TEMPLATE.read_text(encoding="utf-8"), capsys)
    assert code == 1 and out[-1] == "RESULT: FAIL"
    fails = [x for x in out if x.startswith("[FAIL]")]
    assert len(fails) == 2
    assert "범위 밖" in fails[0] and "검증 요구" in fails[1]


def test_unclosed_comments_and_long_spaces_are_linear(tmp_path, capsys):
    text = "<!-- a " * 20000 + "\n| a" + " " * 50000 + "\n1" + " " * 50000 + "x\n" + GOOD
    t0 = time.perf_counter()
    code, _ = run(tmp_path, text, capsys)
    assert time.perf_counter() - t0 < 1.0 and code == 0


def test_oversize_file_exits_2(tmp_path, capsys):
    f = tmp_path / "big.md"
    f.write_bytes(b"a" * (sc.MAX_BYTES + 1))
    assert sc.main(["spec_check.py", str(f)]) == 2


@pytest.mark.parametrize("body", [
    "TBD\n- TODO\n1.\nN/A\n미정\n-",
    "| 대상 | 명령 |\n|---|---|\n| FR-1 | | |\n| FR-2 | TBD | - |",
])
def test_placeholder_only_verification_fails(tmp_path, capsys, body):
    code, out = run(tmp_path, GOOD.replace("`pytest -q` 가 전부 통과한다.", body), capsys)
    assert code == 1 and any("검증 요구 절이 비어 있음" in x for x in out)


def test_scope_out_missing_fails(tmp_path, capsys):
    code, out = run(tmp_path, GOOD.replace("### 범위 밖\n- 모바일\n", ""), capsys)
    assert code == 1 and any("범위 밖 소절 누락" in x for x in out)


def test_scope_out_placeholder_fails_but_none_passes(tmp_path, capsys):
    code, out = run(tmp_path, GOOD.replace("- 모바일", "TBD"), capsys)
    assert code == 1 and any("범위 밖 소절이 비어 있음" in x for x in out)
    code, out = run(tmp_path, GOOD.replace("- 모바일", "없음"), capsys)
    assert code == 0 and out[-1] == "RESULT: PASS"


def test_template_titles_match_script_constants():
    lines = sc.strip_comments_and_fences(TEMPLATE.read_text(encoding="utf-8"))
    titles = [t for t, _ in sc.split_sections(lines)[1]]
    required = [t for t in titles if t in sc.REQUIRED_SECTIONS]
    assert sorted(required) == sorted(sc.REQUIRED_SECTIONS)
    assert sorted(set(titles) - set(sc.REQUIRED_SECTIONS)) == sorted(sc.OPTIONAL_SECTIONS)
    assert not re.search(r"^## .*\(선택\)", TEMPLATE.read_text(encoding="utf-8"), re.MULTILINE)


def test_missing_file_exits_2(tmp_path, capsys):
    assert sc.main(["spec_check.py", str(tmp_path / "none.md")]) == 2
    assert sc.main(["spec_check.py"]) == 2
