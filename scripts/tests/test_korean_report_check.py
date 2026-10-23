"""korean_report_check.py 회귀 테스트 (intent/2026-10-16-korean-report-guard.md).

실행: uv run -q --with pytest python -m pytest scripts/tests/test_korean_report_check.py -q
계약: 코드·인라인 코드·인용·표·주소를 뺀 뒤 한글 없는 6단어 이상 문장이 있거나 한글 비율 0.4 미만이면 Stop 에서 block JSON 을 낸다.
"""
import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import korean_report_check as krc  # noqa: E402

ENGLISH = "The training run finished without any errors and all of the checkpoints were saved."
KOREAN = "결론부터 말씀드리면 학습은 정상 종료되었습니다. 체크포인트 3개를 저장했습니다."


def cli(payload, raw=None):
    data = raw if raw is not None else json.dumps(payload)
    p = subprocess.run([sys.executable, str(SCRIPTS / "korean_report_check.py")], input=data, capture_output=True, text=True)
    assert p.returncode == 0
    return p.stdout


def hits(text):
    return krc.find_english(text)[0]


def test_korean_with_code_paths_names_passes():
    text = "`train.py` 를 수정했습니다. 경로는 ~/workspace/.claude/scripts/foo.sh 이고 PyTorch Lightning 2.6 을 씁니다."
    assert hits(text) == []


def test_all_english_blocks():
    assert hits(ENGLISH)


def test_short_korean_with_many_identifiers_passes():
    # 2026-10-16 qa 오탐 두 건: 식별자 꼴 토큰이 많은 짧은 한글 보고가 비율 규칙에 걸리면 안 된다.
    assert hits("판정: PASS. 근거는 pytest 29 passed, bash -n OK, exit 0 입니다. 자세한 모델은 gpt-6.1-sol 과 Sonnet 5.5 입니다.") == []
    assert hits("result: PASS\nRESULT: DONE target=coder\n검수가 끝났습니다.") == []


def test_mixed_english_sentence_plus_korean_question_blocks():
    text = ENGLISH + " 이대로 진행할까요?"
    h = hits(text)
    assert h and h[0].startswith("The training run")


def test_english_inside_code_fence_inline_quote_table_passes():
    fenced = "수정 내용입니다.\n```\nThe training run finished without any errors and all checkpoints saved\n```\n끝입니다."
    assert hits(fenced) == []
    assert hits("명령은 `echo the training run finished without any errors at all` 입니다.") == []
    assert hits("인용입니다.\n> The training run finished without any errors and all checkpoints saved\n끝입니다.") == []
    assert hits("표입니다.\n| The training run finished without any errors and all checkpoints | b |\n끝입니다.") == []
    assert hits("주소는 https://example.com/the/training/run/finished/without/any/errors 입니다.") == []


def test_short_english_fragment_passes():
    assert hits("Done. 작업이 모두 끝났습니다. Ready to go now.") == []


def test_low_ratio_blocks():
    text = "ok " * 3 + "abcdefghijklmnopqrstuvwxyz" + " 한글"
    h, ratio = krc.find_english(text)
    assert ratio < 0.4 and h


def test_unterminated_fence_is_dropped():
    assert hits("설명입니다.\n```\nThe training run finished without any errors and all checkpoints saved") == []


def test_cli_blocks_with_polite_reason():
    out = cli({"hook_event_name": "Stop", "last_assistant_message": ENGLISH})
    d = json.loads(out)
    assert d["decision"] == "block" and "한글 존댓말" in d["reason"] and "«The training run" in d["reason"]


def test_cli_reason_snippet_capped_at_60():
    out = cli({"hook_event_name": "Stop", "last_assistant_message": ENGLISH})
    snippet = json.loads(out)["reason"].split("걸린 문장: «", 1)[1].rstrip("»")
    assert len(snippet) == 60


def test_cli_korean_passes():
    assert cli({"hook_event_name": "Stop", "last_assistant_message": KOREAN}).strip() == ""


def test_cli_subagent_stop_never_blocks():
    assert cli({"hook_event_name": "SubagentStop", "last_assistant_message": ENGLISH}).strip() == ""


def test_cli_stop_hook_active_never_blocks():
    assert cli({"hook_event_name": "Stop", "stop_hook_active": True, "last_assistant_message": ENGLISH}).strip() == ""


def test_cli_prefers_last_assistant_message_over_transcript(tmp_path):
    t = tmp_path / "t.jsonl"
    t.write_text(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": ENGLISH}]}}) + "\n")
    assert cli({"hook_event_name": "Stop", "last_assistant_message": KOREAN, "transcript_path": str(t)}).strip() == ""


def test_cli_transcript_fallback(tmp_path):
    t = tmp_path / "t.jsonl"
    t.write_text(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": ENGLISH}]}}) + "\n")
    assert json.loads(cli({"hook_event_name": "Stop", "transcript_path": str(t)}))["decision"] == "block"


def test_cli_no_text_passes():
    assert cli({"hook_event_name": "Stop"}).strip() == ""


def test_cli_broken_input_silent():
    assert cli(None, raw="{broken").strip() == ""
    assert cli(None, raw="").strip() == ""
