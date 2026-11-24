"""korean_report_check.py --result-structure 시험 (intent/2026-11-24-harness-review-six-items.md W3 성공 기준 3).

실행: uv run --no-project --with pytest python -m pytest scripts/tests/test_korean_report_structure.py -q
계약: 옵션을 줄 때만 결과 보고 순서를 판정하고, 옵션이 없으면 Stop 훅 출력이 그대로다.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import korean_report_check as krc

CONCLUSION = "결론부터 말씀드리면 판 B 는 key 오차를 줄이지 못했습니다."
PAN = """| 판 | 1) 무엇을 하는 판인가 | 2) 관련 판 대비 차이 | 3) 기대한 효과 | 4) 이뤄졌는가 |
|---|---|---|---|---|
| B | key 손실 배율 ×10 | 대조 판 A(×1) 대비 배율만 바꿈 | key 오차 ↓ | 규칙 미충족: FAIL |"""
GLOSSARY = """| 지표 | 방향 ↑/↓/= | 한 줄 뜻 | 해석법 |
|---|---|---|---|
| key_err | ↓ | key 평균 오차 | 낮을수록 좋음 |"""
RESULT = """| 판 | key_err ↓ | cls_f1 ↑ |
|---|---|---|
| A | 5.4 | 0.81 |
| B | 5.6 | 0.80 |"""
BRIEF = "[Brief] 판 B 는 효과가 없었습니다. 정확도: 중간(시드 1개)"


def doc(*parts):
    return "\n\n".join(parts)


GOOD = doc(CONCLUSION, PAN, GLOSSARY, RESULT, "1) 관찰 하나", BRIEF)


def rows(text):
    return {item: (status, ev) for item, status, ev in krc.check_structure(text)}


def status(text, item):
    return rows(text)[item][0]


def cli(args, stdin=""):
    p = subprocess.run([sys.executable, str(SCRIPTS / "korean_report_check.py"), *args], check=False, input=stdin, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def test_good_report_passes_with_skips():
    got = rows(GOOD)
    assert not [i for i, (s, _) in got.items() if s == "FAIL"]
    assert [i for i, (s, _) in got.items() if s == "SKIP"] == ["판정 계산 선행", "핵심 관찰 1)2)3) · 쉬운 예시"]
    assert got["순서(결론 → 판 설명 → 용어표 → 결과표 → [Brief])"][0] == "PASS"


def test_cli_good_report_prints_item_lines_and_result_pass(tmp_path):
    f = tmp_path / "r.md"
    f.write_text(GOOD, encoding="utf-8")
    rc, out, _ = cli(["--result-structure", str(f)])
    lines = out.splitlines()
    assert rc == 0 and lines[-1] == "RESULT: PASS"
    assert all(ln.count(" | ") == 2 for ln in lines[:-1])


def test_conclusion_after_tables_fails_conclusion_and_cli_exit_1(tmp_path):
    text = doc(PAN, GLOSSARY, RESULT, CONCLUSION, BRIEF)
    assert status(text, "결론 선행") == "FAIL"
    f = tmp_path / "r.md"
    f.write_text(text, encoding="utf-8")
    rc, out, _ = cli(["--result-structure", str(f)])
    assert rc == 1 and out.splitlines()[-1] == "RESULT: FAIL"


def test_missing_one_pan_item_fails_only_that_item():
    text = GOOD.replace(" 3) 기대한 효과 |", " 3) 효과 |")
    got = rows(text)
    assert got["판 설명 3) 기대한 효과"][0] == "FAIL"
    assert got["판 설명 1) 무엇을 하는 판"][0] == "PASS"
    assert got["판 설명 4) 이뤄졌는가"][0] == "PASS"


def test_no_glossary_fails():
    assert status(GOOD.replace(GLOSSARY, ""), "지표 용어표") == "FAIL"


def test_glossary_omission_sentence_passes():
    text = GOOD.replace(GLOSSARY, "지표 정의는 직전 보고와 동일합니다.")
    assert status(text, "지표 용어표") == "PASS"


def test_result_table_without_direction_fails():
    text = GOOD.replace("key_err ↓ | cls_f1 ↑", "key_err | cls_f1")
    got = rows(text)
    assert got["결과표"][0] == "PASS"
    assert got["결과표 방향 표시 ↑↓"][0] == "FAIL"


def test_no_brief_fails_brief_and_accuracy():
    text = GOOD.replace(BRIEF, "마무리 문장입니다.")
    got = rows(text)
    assert got["[Brief]"][0] == "FAIL"
    assert got["정확도 표기"][0] == "FAIL"


def test_glossary_after_result_table_fails_order():
    text = doc(CONCLUSION, PAN, RESULT, GLOSSARY, BRIEF)
    assert status(text, "순서(결론 → 판 설명 → 용어표 → 결과표 → [Brief])") == "FAIL"


def test_tables_inside_code_fence_are_ignored():
    text = doc(CONCLUSION, "```\n" + PAN + "\n```", GLOSSARY, RESULT, BRIEF)
    assert status(text, "판 설명 1) 무엇을 하는 판") == "FAIL"


def test_cli_usage_and_missing_file_exit_2(tmp_path):
    assert cli(["--result-structure"])[0] == 2
    assert cli(["--result-structure", str(tmp_path / "none.md")])[0] == 2


def test_two_dash_and_one_dash_separators_are_tables():
    for sep in ("|--|--|--|", "|-|-|-|", "| :-: | --: | :-- |"):
        text = doc(CONCLUSION, GLOSSARY, f"| 판 | a ↑ | b ↓ |\n{sep}\n| A | 1 | 2 |", BRIEF)
        assert status(text, "결과표 방향 표시 ↑↓") == "PASS", sep


def test_long_space_line_is_linear_time():
    evil = "|" + " " * 40000 + "x"
    start = time.monotonic()
    krc.check_structure(doc(CONCLUSION, "| a | b |\n" + evil, BRIEF))
    assert time.monotonic() - start < 1.0


def test_non_utf8_file_exits_2(tmp_path):
    f = tmp_path / "bad.md"
    f.write_bytes(b"\xff\xfe\x80 not utf8")
    rc, out, err = cli(["--result-structure", str(f)])
    assert rc == 2 and out == "" and "Traceback" not in err


def test_file_over_size_limit_exits_2(tmp_path):
    f = tmp_path / "big.md"
    f.write_bytes(b"a" * (krc.MAX_REPORT_BYTES + 1))
    rc, out, err = cli(["--result-structure", str(f)])
    assert rc == 2 and out == "" and "MB" in err


def test_result_table_with_two_pan_keywords_is_not_pan_table():
    result = "| 판 | 무엇 | 차이 ↑ |\n|---|---|---|\n| A | 1 | 2 |"
    got = rows(doc(CONCLUSION, GLOSSARY, result, BRIEF))
    assert got["결과표"][0] == "PASS" and got["결과표 방향 표시 ↑↓"][0] == "PASS"
    assert got["판 설명 3) 기대한 효과"][0] == "FAIL"
    assert "네 열 가운데 2개만" in got["판 설명 3) 기대한 효과"][1]


def test_two_column_glossary_candidate_is_noted_on_result_row():
    cand = "| 지표 | 방향 ↑ |\n|---|---|\n| key_err | ↓ |"
    got = rows(doc(CONCLUSION, PAN, cand, BRIEF))
    assert got["지표 용어표"][0] == "FAIL" and "용어표 후보(머리 2열 일치)" in got["지표 용어표"][1]
    assert "용어표 후보(머리 2열 일치)가 결과표로 분류됨" in got["결과표"][1]


def test_without_option_hook_output_is_unchanged():
    ko = json.dumps({"hook_event_name": "Stop", "last_assistant_message": GOOD})
    rc, out, _ = cli([], ko)
    assert rc == 0 and out == ""
    en = json.dumps({"hook_event_name": "Stop", "last_assistant_message": "The training run finished without any errors and all of the checkpoints were saved."})
    rc, out, _ = cli([], en)
    assert rc == 0 and json.loads(out)["decision"] == "block"
