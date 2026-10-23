"""Typo rules (4: dictionary, 5: doubled particles, 6: repeated word) of korean_style_check / korean_report_check.

Run: cd ~/.claude && uv run -q --with pytest python -m pytest scripts/tests/test_korean_typo_check.py -q -p no:cacheprovider
Contract (2026-10-23 user order): 4 and 5 block, 6 only warns; code, inline code, URL and quotes are excluded; table cells are checked.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import korean_report_check as krc
import korean_style_check as ksc

WRONG_RIGHT = list(ksc.TYPO_DICT.items())


def wrongs(text):
    return [(w, r) for _, w, r in ksc.find_typos(text)]


@pytest.mark.parametrize("wrong,right", WRONG_RIGHT)
def test_every_dictionary_entry_is_caught(wrong, right):
    assert (wrong, right) in wrongs(f"이 문장에 {wrong} 가 들어 있습니다.")


def test_dictionary_size_is_pinned():
    assert len(ksc.TYPO_DICT) == 29  # 사전을 넓히지 않기로 한 지시(2026-10-23)를 깨면 여기서 걸린다


@pytest.mark.parametrize("ok", [
    "돼요", "할게요", "며칠", "되도록", "함께", "께서 말씀하셨습니다", "의의가 큽니다", "은은하다", "안 돼요", "습니다",
    "가을을 맞아", "마을을 지나", "고을을 돌아", "왠지", "웬만하면", "금세", "역할", "희한", "일일이", "깨끗이", "오랜만", "텐데",
])
def test_correct_forms_pass(ok):
    assert wrongs(ok) == []


@pytest.mark.parametrize("bad,pair", [
    ("결과를를 봅니다", ("를를", "를")), ("자료을을 봅니다", ("을을", "을")), ("하는는 중", ("는는", "는")),
    ("서버에서에서 실행", ("에서에서", "에서")),
])
def test_doubled_particles_blocked(bad, pair):
    assert pair in wrongs(bad)


def test_longer_entry_wins():
    assert wrongs("할께요") == [("할께요", "할게요")]


@pytest.mark.parametrize("text", [
    "사용자는 «결과 보고 양식은 이게 아니었을탠데?» 라고 했습니다.",
    "그는 “됬다” 고 썼습니다.", '원문은 "할께" 입니다.',
    "`됬` 는 코드 안입니다.", "```\n됬 되요\n```", "주소는 https://example.com/됬/되요 입니다.",
])
def test_excluded_zones_are_not_checked(text):
    assert wrongs(text) == []


def test_table_cell_is_checked_and_line_number_kept():
    md = "| 열 | 값 |\n|---|---|\n| 상태 | 됬음 |\n"
    assert ksc.find_typos(md) == [(3, "됬", "됐")]


def test_repeated_word_is_warning_only():
    html = "<p>이 작업 작업 은 끝났습니다.</p>"
    blocked, warned = ksc.check(html)
    assert blocked == []
    assert [w[0] for w in warned] == ["같은 어절 연속"] and "작업 작업" in warned[0][2]


def test_repeat_ignores_short_digits_and_different_words():
    assert ksc.find_repeats("가 가 100 100 --- --- 작업 완료 작업") == []


def test_check_blocks_typo_with_line_prefix():
    blocked, _ = ksc.check("<p>첫 줄입니다.</p>\n<p>그래서 됬습니다.</p>")
    assert blocked == [("오탈자", "typo", "2: 됬 → 됐")]


def test_regression_ignores_line_shift_but_flags_new_typo():
    before, after = "<p>됬습니다.</p>", "<p>추가</p>\n<p>됬습니다.</p>"
    assert ksc.regression(before, after) == 0
    assert ksc.regression(before, after + "\n<p>되요</p>") == 1


def test_cli_markdown_table_blocks_and_exit_code(tmp_path):
    f = tmp_path / "doc.md"
    f.write_text("| a | b |\n|---|---|\n| 값 | 몇일 |\n", encoding="utf-8")
    p = subprocess.run([sys.executable, str(SCRIPTS / "korean_style_check.py"), str(f)], check=False, capture_output=True, text=True)
    assert p.returncode == 1 and "3: 몇일 → 며칠" in p.stdout


def test_cli_repeat_only_exits_zero(tmp_path):
    f = tmp_path / "doc.md"
    f.write_text("이 작업 작업 은 끝났습니다.\n", encoding="utf-8")
    p = subprocess.run([sys.executable, str(SCRIPTS / "korean_style_check.py"), str(f)], check=False, capture_output=True, text=True)
    assert p.returncode == 0 and "경고" in p.stdout


def hook(text):
    payload = {"hook_event_name": "Stop", "last_assistant_message": text}
    p = subprocess.run([sys.executable, str(SCRIPTS / "korean_report_check.py")], input=json.dumps(payload), check=False, capture_output=True, text=True)
    assert p.returncode == 0
    return json.loads(p.stdout) if p.stdout.strip() else None


def test_report_blocks_with_pairs_in_reason():
    out = hook("작업이 됬습니다. 내일 할께요. 결과를를 확인했습니다.")
    assert out["decision"] == "block"
    for s in ("오탈자: 됬 → 됐", "오탈자: 할께요 → 할게요", "오탈자: 를를 → 를"):
        assert s in out["reason"]


def test_report_reason_has_at_most_8_unique_pairs():
    words = "됬 됀 되요 되서 않돼 할께 줄께 갈께 볼께 몇일 됬"
    out = hook(f"정리합니다. {words} 입니다.")
    assert out["reason"].count("오탈자:") == 8


def test_report_ignores_quotes_code_and_clean_text():
    assert hook("정상 보고입니다. 사용자 원문 «할께» 와 `됬` 는 인용입니다.\n> 인용 줄 됬습니다") is None
    assert hook("작업 작업 은 경고 대상이라 보고 훅은 보지 않습니다.") is None


def test_report_check_fails_open_when_typo_check_breaks(monkeypatch):
    monkeypatch.setattr(krc, "find_typo_pairs", lambda t: 1 / 0)
    assert krc.find_english("정상입니다.")[0] == []
    # main() swallows the error inside its own try block and keeps the English check working
    import io
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"hook_event_name": "Stop", "last_assistant_message": "정상 됬습니다."})))
    krc.main()
