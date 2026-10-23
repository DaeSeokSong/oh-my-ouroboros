"""toolcall-text-guard.sh 회귀 테스트 (2026-10-01 감사: SubagentStop 은 자식 기록을 읽어야 한다; 2026-10-16: last_assistant_message 우선 + 한글 보고 검사).

실행: uv run -q --with pytest python -m pytest scripts/tests/test_toolcall_text_guard.py -q
계약: last_assistant_message 가 있으면 그것을, 없으면 Stop 은 transcript_path, SubagentStop 은 agent_transcript_path(자식 기록)의
      마지막 assistant 메시지를 검사한다. 여는 invoke 태그와 parameter 태그가 둘 다 본문 텍스트로 남아 있으면 decision:block.
      Stop 에서만 마크업 검사 뒤에 한글 보고 검사(korean_report_check.py)가 이어진다.
"""
import json
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "toolcall-text-guard.sh"
LEAK = "<invoke name=\"Bash\"><parameter name=\"command\">ls</parameter></invoke>"   # 가짜 도구 호출 마크업 원문
ENGLISH = "The training run finished without any errors and all of the checkpoints were saved."


def entry(text):
    return json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}) + "\n"


def run(payload, raw=None):
    data = raw if raw is not None else json.dumps(payload)
    p = subprocess.run(["bash", str(SCRIPT)], input=data, capture_output=True, text=True)
    assert p.returncode == 0
    return p.stdout


def blocked(out):
    return bool(out.strip()) and json.loads(out)["decision"] == "block"


def make(tmp_path, name, text):
    f = tmp_path / name
    f.write_text(entry(text))
    return str(f)


def test_stop_main_transcript_leak_blocks(tmp_path):
    out = run({"transcript_path": make(tmp_path, "p.jsonl", LEAK)})
    assert blocked(out) and "도구 호출 마크업" in out


def test_stop_clean_passes(tmp_path):
    assert run({"transcript_path": make(tmp_path, "p.jsonl", "정상 응답")}).strip() == ""


def test_subagent_stop_uses_child_transcript_clean(tmp_path):
    parent, child = make(tmp_path, "p.jsonl", LEAK), make(tmp_path, "c.jsonl", "자식 정상 응답")
    assert run({"transcript_path": parent, "agent_transcript_path": child}).strip() == ""


def test_subagent_stop_child_leak_blocks(tmp_path):
    parent, child = make(tmp_path, "p.jsonl", "정상 응답"), make(tmp_path, "c.jsonl", LEAK)
    assert blocked(run({"transcript_path": parent, "agent_transcript_path": child}))


def test_last_assistant_message_preferred_over_stale_transcript(tmp_path):
    stale = make(tmp_path, "p.jsonl", LEAK)
    assert run({"hook_event_name": "Stop", "last_assistant_message": "정상 응답", "transcript_path": stale}).strip() == ""
    clean = make(tmp_path, "q.jsonl", "정상 응답")
    assert blocked(run({"hook_event_name": "Stop", "last_assistant_message": LEAK, "transcript_path": clean}))


def test_last_assistant_message_works_without_transcript():
    assert blocked(run({"hook_event_name": "Stop", "last_assistant_message": LEAK}))


def test_stop_english_blocks_with_korean_reason():
    out = run({"hook_event_name": "Stop", "last_assistant_message": ENGLISH})
    assert blocked(out) and "한글 존댓말" in json.loads(out)["reason"] and "The training run" in out


def test_stop_korean_passes():
    assert run({"hook_event_name": "Stop", "last_assistant_message": "학습이 끝났습니다. 체크포인트를 저장했습니다."}).strip() == ""


def test_stop_english_via_transcript_fallback(tmp_path):
    t = make(tmp_path, "p.jsonl", ENGLISH)
    assert blocked(run({"hook_event_name": "Stop", "transcript_path": t}))


def test_subagent_stop_english_never_blocks(tmp_path):
    assert run({"hook_event_name": "SubagentStop", "last_assistant_message": ENGLISH}).strip() == ""
    child = make(tmp_path, "c.jsonl", ENGLISH)
    assert run({"hook_event_name": "SubagentStop", "agent_transcript_path": child}).strip() == ""


def test_stop_hook_active_never_blocks():
    assert run({"hook_event_name": "Stop", "stop_hook_active": True, "last_assistant_message": ENGLISH}).strip() == ""
    assert run({"hook_event_name": "Stop", "stop_hook_active": True, "last_assistant_message": LEAK}).strip() == ""


def test_markup_block_wins_over_korean_check():
    out = run({"hook_event_name": "Stop", "last_assistant_message": LEAK + "\n" + ENGLISH})
    assert out.count('"decision"') == 1 and "도구 호출 마크업" in out


def test_broken_json_input_is_silent():
    assert run(None, raw="{not json").strip() == ""
    assert run(None, raw="").strip() == ""
