"""handoff_check.py 회귀 테스트 (2026-10-23: 세션 작업 현황 파일이 30분 넘게 묵으면 Stop 훅이 갱신을 요구).

실행: uv run -q --with pytest python -m pytest scripts/tests/test_handoff_check.py -q
계약(2026-11-12 추가): 이번 턴의 마지막 tool_use 가 게시 승인 질문(AskUserQuestion, 승인 줄 + «게시 승인» 보기)이고 그 id 의
      tool_result 가 아직 없으면(묻고 답을 기다리며 끝나는 턴) 카드가 없거나 묵어도 통과. 답이 온 뒤 · 질문 뒤 다른 tool_use ·
      이전 턴의 승인 질문 · 승인이 아닌 질문 · id 없음 · 판정 오류는 면제가 아니다.
계약: 일한 턴(마지막 사용자 메시지 뒤 assistant tool_use 1개 이상)에 <뿌리>/.scratch/handoff/<세션 앞 8자>.md 가
      없거나 문턱(HANDOFF_STALE_MIN, 기본 30분)보다 오래되면 decision:block 한 줄. 그 밖의 모든 경우와 오류는 무출력.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "handoff_check.py"
SID = "abcd1234-0000-0000-0000-000000000000"


def jl(*entries):
    return "".join(json.dumps(e) + "\n" for e in entries)


USER = {"type": "user", "message": {"role": "user", "content": "작업해 주세요"}}
TOOL_USE = {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}]}}
TOOL_RESULT = {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}}
TEXT = {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "답변"}]}}
WORKED = jl(USER, TOOL_USE, TOOL_RESULT, TEXT)
CHAT_ONLY = jl(USER, TOOL_USE, TOOL_RESULT, TEXT, {"type": "user", "message": {"role": "user", "content": "질문입니다"}}, TEXT)


def run(payload, home, env_extra=None, raw=None):
    env = {"PATH": os.environ["PATH"], "HOME": str(home), **(env_extra or {})}
    data = raw if raw is not None else json.dumps(payload)
    p = subprocess.run([sys.executable, "-I", str(SCRIPT)], input=data, capture_output=True, text=True, env=env, check=False)
    assert p.returncode == 0
    return p.stdout


def blocked(out):
    return bool(out.strip()) and json.loads(out)["decision"] == "block"


def setup(tmp_path, transcript=WORKED):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    tp = tmp_path / "t.jsonl"
    tp.write_text(transcript)
    home = tmp_path / "home"
    home.mkdir()
    payload = {"session_id": SID, "cwd": str(repo), "transcript_path": str(tp), "hook_event_name": "Stop"}
    return repo, home, payload


def handoff(root, age_min=None):
    f = Path(root) / ".scratch" / "handoff" / "abcd1234.md"
    if age_min is not None:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("현황")
        t = time.time() - age_min * 60
        os.utime(f, (t, t))
    return f


def test_worked_turn_without_file_blocks_with_path(tmp_path):
    repo, home, payload = setup(tmp_path)
    out = run(payload, home)
    assert blocked(out)
    assert str(handoff(repo)) in json.loads(out)["reason"]


def test_worked_turn_fresh_file_passes(tmp_path):
    repo, home, payload = setup(tmp_path)
    handoff(repo, 1)
    assert run(payload, home).strip() == ""


def test_worked_turn_old_file_blocks(tmp_path):
    repo, home, payload = setup(tmp_path)
    handoff(repo, 40)
    assert blocked(run(payload, home))


def test_chat_only_turn_passes(tmp_path):
    _, home, payload = setup(tmp_path, CHAT_ONLY)
    assert run(payload, home).strip() == ""


def test_stop_hook_active_passes(tmp_path):
    _, home, payload = setup(tmp_path)
    assert run({**payload, "stop_hook_active": True}, home).strip() == ""


def test_outside_git_passes(tmp_path):
    _, home, payload = setup(tmp_path)
    plain = tmp_path / "plain"
    plain.mkdir()
    assert run({**payload, "cwd": str(plain)}, home).strip() == ""


def test_harness_home_cwd_uses_dot_claude(tmp_path):
    _, home, payload = setup(tmp_path)
    sub = home / ".claude" / "sub"
    sub.mkdir(parents=True)
    out = run({**payload, "cwd": str(sub)}, home)
    assert blocked(out)
    assert str(handoff(home / ".claude")) in json.loads(out)["reason"]


def test_broken_input_passes(tmp_path):
    _, home, _ = setup(tmp_path)
    assert run(None, home, raw="{not json").strip() == ""
    assert run({"session_id": SID, "cwd": str(tmp_path), "transcript_path": str(tmp_path / "none.jsonl")}, home).strip() == ""


def test_stale_threshold_env(tmp_path):
    repo, home, payload = setup(tmp_path)
    handoff(repo, 40)
    assert run(payload, home, {"HANDOFF_STALE_MIN": "60"}).strip() == ""
    assert blocked(run(payload, home, {"HANDOFF_STALE_MIN": "10"}))
    assert blocked(run(payload, home, {"HANDOFF_STALE_MIN": "abc"}))


APPROVAL_Q = "게시 승인 요청 · page=123 · 알림=quiet · 버전 설명=«수정»"


def ask(tid, question, labels):
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "id": tid, "name": "AskUserQuestion", "input": {
        "questions": [{"question": question, "options": [{"label": x} for x in labels]}]}}]}}


PUBLISH_ASK = ask("a1", "게시할까요?\n" + APPROVAL_Q, ["게시 승인", "취소"])
OTHER_ASK = ask("a2", "어느 쪽으로 할까요?", ["가", "나"])
NO_LABEL_ASK = ask("a3", APPROVAL_Q, ["예", "아니오"])
ANSWER = {"type": "user", "message": {"role": "user", "content": "게시 승인"}}


def test_review_turn_old_file_passes(tmp_path):
    repo, home, payload = setup(tmp_path, jl(USER, TOOL_USE, TOOL_RESULT, PUBLISH_ASK))
    handoff(repo, 40)
    assert run(payload, home).strip() == ""


def test_review_turn_without_file_passes(tmp_path):
    _, home, payload = setup(tmp_path, jl(USER, TOOL_USE, TOOL_RESULT, PUBLISH_ASK))
    assert run(payload, home).strip() == ""


PUBLISH_RESULT = {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "a1", "content": "게시 승인"}]}}
NO_ID_ASK = {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "name": "AskUserQuestion", "input": PUBLISH_ASK["message"]["content"][0]["input"]}]}}


def test_answered_publish_question_old_file_blocks(tmp_path):
    repo, home, payload = setup(tmp_path, jl(USER, PUBLISH_ASK, PUBLISH_RESULT, TEXT))
    handoff(repo, 40)
    assert blocked(run(payload, home))


def test_publish_question_then_other_tool_use_blocks(tmp_path):
    repo, home, payload = setup(tmp_path, jl(USER, PUBLISH_ASK, TOOL_USE, TOOL_RESULT))
    handoff(repo, 40)
    assert blocked(run(payload, home))


def test_publish_question_without_tool_use_id_blocks(tmp_path):
    repo, home, payload = setup(tmp_path, jl(USER, TOOL_USE, TOOL_RESULT, NO_ID_ASK))
    handoff(repo, 40)
    assert blocked(run(payload, home))


def test_publish_question_pending_old_file_passes(tmp_path):
    repo, home, payload = setup(tmp_path, jl(USER, PUBLISH_ASK))
    handoff(repo, 40)
    assert run(payload, home).strip() == ""


def test_other_question_old_file_blocks(tmp_path):
    repo, home, payload = setup(tmp_path, jl(USER, TOOL_USE, TOOL_RESULT, OTHER_ASK))
    handoff(repo, 40)
    assert blocked(run(payload, home))


def test_approval_line_without_approve_option_blocks(tmp_path):
    _, home, payload = setup(tmp_path, jl(USER, TOOL_USE, TOOL_RESULT, NO_LABEL_ASK))
    assert blocked(run(payload, home))


def test_approval_question_in_earlier_turn_blocks(tmp_path):
    repo, home, payload = setup(tmp_path, jl(USER, PUBLISH_ASK, ANSWER, TOOL_USE, TOOL_RESULT, TEXT))
    handoff(repo, 40)
    assert blocked(run(payload, home))


def test_broken_transcript_line_same_as_before(tmp_path):
    repo, home, payload = setup(tmp_path, jl(USER, TOOL_USE) + "{broken\n")
    handoff(repo, 40)
    assert blocked(run(payload, home))


def test_malformed_ask_input_blocks(tmp_path):
    bad = {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": "a4", "name": "AskUserQuestion", "input": "not a dict"}]}}
    _, home, payload = setup(tmp_path, jl(USER, bad))
    assert blocked(run(payload, home))


GUARD = SCRIPT.with_name("toolcall-text-guard.sh")
ENGLISH = "The training run finished without any errors and all of the checkpoints were saved."


def run_guard(payload, home):
    env = {"PATH": os.environ["PATH"], "HOME": str(home)}
    p = subprocess.run(["bash", str(GUARD)], input=json.dumps(payload), capture_output=True, text=True, env=env, check=False)
    assert p.returncode == 0
    return p.stdout


def test_guard_wiring_handoff_block_after_clean_korean(tmp_path):
    _, home, payload = setup(tmp_path)
    out = run_guard({**payload, "last_assistant_message": "정상 응답입니다"}, home)
    assert blocked(out) and "작업 현황 파일" in out and out.count('"decision"') == 1


def test_guard_wiring_korean_block_suppresses_handoff(tmp_path):
    _, home, payload = setup(tmp_path)
    out = run_guard({**payload, "last_assistant_message": ENGLISH}, home)
    assert blocked(out) and "작업 현황 파일" not in out and out.count('"decision"') == 1
