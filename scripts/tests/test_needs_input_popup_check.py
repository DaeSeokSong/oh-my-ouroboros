"""needs_input_popup_check.py 시험. 실행: uv run -q --with pytest python -m pytest scripts/tests/test_needs_input_popup_check.py"""
import json
import pathlib
import subprocess
import sys

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "needs_input_popup_check.py"
CONFIRM = "[결정 팝업 확인] 답을 받았습니다"
NI = "요약입니다.\nneeds input: 어느 판을 기준으로 할지 골라 주십시오"


def user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def use(uid):
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": uid, "name": "mcp__decision-popup__ask", "input": {}}]}}


def ask_use(uid):
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": uid, "name": "AskUserQuestion", "input": {}}]}}


def result(uid, text="ok", is_error=False):
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": uid, "content": text, "is_error": is_error}]}}


def run(tmp_path, entries, text=NI, **extra):
    """Run the hook on a fake transcript and return its stdout."""
    tp = tmp_path / "t.jsonl"
    if entries is not None:
        tp.write_text("\n".join(e if isinstance(e, str) else json.dumps(e, ensure_ascii=False) for e in entries) + "\n",
                      encoding="utf-8")
    data = {"hook_event_name": "Stop", "transcript_path": str(tp), "last_assistant_message": text, **extra}
    p = subprocess.run([sys.executable, "-I", str(SCRIPT)], input=json.dumps(data), capture_output=True, text=True,
                       timeout=20, check=False)
    assert p.returncode == 0
    return p.stdout.strip()


def is_block(out):
    return json.loads(out)["decision"] == "block"


def test_no_needs_input_passes(tmp_path):
    assert run(tmp_path, [user("hi")], text="완료했습니다.") == ""


def test_needs_input_without_popup_blocks(tmp_path):
    assert is_block(run(tmp_path, [user("hi")]))


def test_not_decision_marker_passes(tmp_path):
    assert run(tmp_path, [user("hi")], text="needs input: 접근 권한 승인 부탁드립니다 (결정 아님)") == ""


def test_popup_this_turn_passes(tmp_path):
    assert run(tmp_path, [user(CONFIRM), user("다음"), use("a"), result("a")]) == ""


def test_open_popup_from_earlier_turn_without_confirm_passes(tmp_path):
    assert run(tmp_path, [user("작업"), use("a"), result("a")]) == ""


def test_popup_before_last_confirm_blocks(tmp_path):
    assert is_block(run(tmp_path, [use("a"), result("a"), user(CONFIRM), user("다음")]))


def test_failed_popup_not_a_basis(tmp_path):
    assert is_block(run(tmp_path, [user(CONFIRM), use("a"), result("a", "입력 오류: label")]))
    assert is_block(run(tmp_path, [user(CONFIRM), use("a"), result("a", "boom", is_error=True)]))


def test_ask_user_question_success_is_a_basis_in_mobile_mode(tmp_path):
    assert run(tmp_path, [user(CONFIRM), ask_use("a"), result("a")]) == ""


def test_failed_ask_user_question_not_a_basis(tmp_path):
    assert is_block(run(tmp_path, [user(CONFIRM), ask_use("a"), result("a", "boom", is_error=True)]))


def test_tool_use_without_result_yet_passes(tmp_path):
    assert run(tmp_path, [user(CONFIRM), use("a")]) == ""


def test_needs_input_inside_code_fence_ignored(tmp_path):
    assert run(tmp_path, [user("hi")], text="예시\n```\nneeds input: x\n```\n끝") == ""


def test_bold_form_is_target(tmp_path):
    assert is_block(run(tmp_path, [user("hi")], text="**needs input:** 골라 주십시오"))
    assert is_block(run(tmp_path, [user("hi")], text="  Needs Input: 골라 주십시오"))


def test_missing_or_broken_transcript_passes(tmp_path):
    assert run(tmp_path, None) == ""
    assert run(tmp_path, ["{not json", "[1,2]", "\x00garbage"]) == ""
    assert is_block(run(tmp_path, ["{not json", user("hi")]))


def test_stop_hook_active_passes(tmp_path):
    assert run(tmp_path, [user("hi")], stop_hook_active=True) == ""


def test_subagent_stop_passes(tmp_path):
    assert run(tmp_path, [user("hi")], hook_event_name="SubagentStop") == ""


def test_all_targets_need_marker(tmp_path):
    text = "needs input: a (결정 아님)\nneeds input: 고르십시오"
    assert is_block(run(tmp_path, [user("hi")], text=text))
