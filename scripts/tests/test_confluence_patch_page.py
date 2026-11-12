"""confluence_patch_page.py 회귀 테스트 (네트워크 없음 — get_page·put_page 를 가짜로 바꾼다).

실행: uv run --with pytest --with requests python -m pytest scripts/tests/test_confluence_patch_page.py -q
"""
import json
import stat
import sys
import time
import types
from pathlib import Path

import pytest

try:
    import requests  # noqa: F401
except ImportError:   # 시험은 네트워크를 쓰지 않으므로 빈 모듈이면 충분하다
    sys.modules["requests"] = types.ModuleType("requests")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import confluence_patch_page as cpp


def test_sequential_replace_interference_is_avoided():
    # 앞 치환의 new 가 뒤 앵커 문자열을 품어도, 원문 위치 기준이라 뒤 앵커는 원문의 그 자리만 고친다.
    body = "AAA ... BBB ..."
    patches = [{"anchor": "AAA", "new": "BBB"}, {"anchor": "BBB", "new": "CCC"}]
    assert cpp.replace_by_original_position(body, patches) == "BBB ... CCC ..."


def test_overlapping_anchors_abort():
    with pytest.raises(SystemExit):
        cpp.replace_by_original_position("abcdef", [{"anchor": "abcd", "new": "x"}, {"anchor": "cdef", "new": "y"}])


def test_patch_order_independent_and_lengths_change():
    body = "1-first 2-second 3-third"
    patches = [{"anchor": "3-third", "new": "T"}, {"anchor": "1-first", "new": "FIRST!!!"}]
    assert cpp.replace_by_original_position(body, patches) == "FIRST!!! 2-second T"


@pytest.mark.parametrize("url", ["http://a.atlassian.net", "https://evil.example.com",
                                 "https://a.atlassian.net.evil.com", "https://a.atlassian.net/wiki",
                                 "https://a.atlassian.net?x=1"])
def test_site_must_be_https_atlassian_net(url):
    with pytest.raises(SystemExit):
        cpp.check_site(url)


def test_site_ok_strips_slash():
    assert cpp.check_site("https://a.atlassian.net/") == "https://a.atlassian.net"


def test_probe_backup_is_0600(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cpp, "SITE", "https://a.atlassian.net")
    monkeypatch.setattr(cpp, "get_page", lambda pid: ("T", 3, "<p>본문 하나</p>"))
    monkeypatch.setattr(sys, "argv", ["x", "--page", "9", "--probe", "본문", "--backup-dir", str(tmp_path)])
    cpp.main()
    files = list(tmp_path.glob("confluence_backup_9_v3_*.storage.html"))
    assert len(files) == 1 and stat.S_IMODE(files[0].stat().st_mode) == 0o600


@pytest.fixture
def approval_env(tmp_path, monkeypatch):
    """임시 HOME 의 가짜 세션 기록에 «AskUserQuestion 승인 답» 을 덧붙이는 함수를 돌려준다 (실제 _audit·실제 세션 기록은 건드리지 않는다)."""
    home = tmp_path / "home"
    log = home / ".claude/projects/p/s1.jsonl"   # 승인은 HOME 기준 세션 기록의 질문·답이다
    log.parent.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    n = [0]

    def approve(page, notify="notify", message="최신 결과 반영", answer="게시 승인"):
        n[0] += 1
        q = f"아래 게시를 승인하시겠습니까?\n게시 승인 요청 · page={page} · 알림={notify} · 버전 설명=«{message}»"
        qs = [{"question": q, "header": "승인", "options": [{"label": "게시 승인", "description": "d"}, {"label": "취소", "description": "d"}]}]
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        tuid = f"toolu_patch_{n[0]}"
        use = {"type": "assistant", "isSidechain": False, "timestamp": now,
               "message": {"role": "assistant", "content": [{"type": "tool_use", "name": "AskUserQuestion", "id": tuid, "input": {"questions": qs}}]}}
        res = {"type": "user", "isSidechain": False, "timestamp": now,
               "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tuid, "content": "ok"}]},
               "toolUseResult": {"questions": qs, "answers": {q: answer}, "annotations": {}}}
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps(use, ensure_ascii=False) + "\n" + json.dumps(res, ensure_ascii=False) + "\n")
    return approve


def _apply_setup(tmp_path, monkeypatch, extra_argv=()):
    """--apply 경로 시험 공통 준비: 가짜 get_page·put_page, 골격 스탬프 통과, 치환 목록 파일. put 호출 기록을 돌려준다."""
    monkeypatch.setattr(cpp, "SITE", "https://a.atlassian.net")
    monkeypatch.setattr(cpp, "get_page", lambda pid: ("T", 3, "AAA ... BBB ..."))
    monkeypatch.setattr(cpp, "_skeleton_stamp_ok", lambda body: True)
    monkeypatch.setattr(cpp, "_home_is_real", lambda: True)   # 시험은 임시 HOME 을 쓰므로 통과로 바꾼다
    sent = {}
    monkeypatch.setattr(cpp, "put_page", lambda pid, title, ver, body, msg, minor=False: sent.update(body=body, minor=minor) or ver + 1)
    pf = tmp_path / "p.json"
    pf.write_text('[{"anchor":"AAA","new":"BBB"},{"anchor":"BBB","new":"CCC"}]')
    monkeypatch.setattr(sys, "argv", ["x", "--page", "9", "--patches", str(pf), "--apply",
                                      "--backup-dir", str(tmp_path), *extra_argv])
    return sent


def test_main_apply_path_uses_original_position_replacement(tmp_path, monkeypatch, approval_env):
    """2026-10-01 P6 검수: main --apply 경로가 순차 치환으로 되돌아가면 앞 치환의 new 가 뒤 앵커를 먹는다(여기서만 드러난다)."""
    approval_env("9")
    sent = _apply_setup(tmp_path, monkeypatch)
    cpp.main()
    assert sent["body"] == "BBB ... CCC ..."


def test_apply_without_publish_approval_stops_before_put(tmp_path, monkeypatch, approval_env):
    """2026-10-06: 게시 승인(AskUserQuestion 답)이 없으면 --apply 는 put 을 부르지 않고 멈춘다."""
    sent = _apply_setup(tmp_path, monkeypatch)
    with pytest.raises(SystemExit) as e:
        cpp.main()
    assert "AskUserQuestion" in str(e.value) and not sent


def test_apply_minor_mismatching_approval_notify_stops(tmp_path, monkeypatch, approval_env):
    """2026-10-06: 승인 줄이 알림=notify 인데 --minor 로 부르면(조용한 수정) 멈춘다."""
    approval_env("9", notify="notify")
    sent = _apply_setup(tmp_path, monkeypatch, ["--minor"])
    with pytest.raises(SystemExit):
        cpp.main()
    assert not sent


def test_apply_minor_with_quiet_approval_passes_and_consumes(tmp_path, monkeypatch, approval_env):
    """2026-10-06: 알림=quiet 승인 + --minor 는 통과하고, 소모되어 같은 호출을 다시 하면 멈춘다."""
    approval_env("9", notify="quiet")
    sent = _apply_setup(tmp_path, monkeypatch, ["--minor"])
    cpp.main()
    assert sent["minor"] is True
    sent.clear()
    with pytest.raises(SystemExit):
        cpp.main()
    assert not sent


def test_apply_message_mismatch_stops(tmp_path, monkeypatch, approval_env):
    """2026-10-06: 버전 설명(--message)이 승인 줄과 다르면 멈춘다."""
    approval_env("9", message="다른 설명")
    sent = _apply_setup(tmp_path, monkeypatch)
    with pytest.raises(SystemExit):
        cpp.main()
    assert not sent


def test_apply_cancelled_approval_stops(tmp_path, monkeypatch, approval_env):
    """2026-10-07: 사용자가 승인 질문에서 «취소» 를 골랐다면 --apply 는 멈춘다."""
    approval_env("9", answer="취소")
    sent = _apply_setup(tmp_path, monkeypatch)
    with pytest.raises(SystemExit) as e:
        cpp.main()
    assert "AskUserQuestion" in str(e.value) and not sent


def test_apply_with_fake_home_stops_before_put(tmp_path, monkeypatch, approval_env):
    """2026-10-06 검수: HOME 이 실제 사용자 홈과 다르면(가짜 스탬프 폴더·세션 기록을 물린 경우) 승인이 있어도 put 을 부르지 않는다."""
    approval_env("9")
    real_check = cpp._home_is_real
    sent = _apply_setup(tmp_path, monkeypatch)
    monkeypatch.setattr(cpp, "_home_is_real", real_check)   # 임시 HOME 이므로 실제 판정은 False 다
    with pytest.raises(SystemExit) as e:
        cpp.main()
    assert "HOME" in str(e.value) and not sent


def test_apply_non_numeric_page_stops(tmp_path, monkeypatch, approval_env):
    """2026-10-06 검수: 숫자가 아닌 --page(tiny link 등)는 승인 검사에서 멈춘다."""
    sent = _apply_setup(tmp_path, monkeypatch)
    monkeypatch.setattr(cpp, "get_page", lambda pid: ("T", 3, "AAA ... BBB ..."))
    monkeypatch.setattr(sys, "argv", [("AbC" if a == "9" else a) for a in sys.argv])
    with pytest.raises(SystemExit) as e:
        cpp.main()
    assert "숫자 페이지 ID" in str(e.value) and not sent


def test_dry_run_does_not_need_or_consume_approval(tmp_path, monkeypatch, approval_env):
    """2026-10-06: --apply 없는 dry-run 은 승인을 요구하지도 소모하지도 않는다."""
    approval_env("9")
    sent = _apply_setup(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", [a for a in sys.argv if a != "--apply"])
    cpp.main()
    assert not sent
    monkeypatch.setattr(sys, "argv", sys.argv + ["--apply"])
    cpp.main()
    assert sent["body"] == "BBB ... CCC ..."


def test_apply_with_credential_in_new_body_stops_before_put(tmp_path, monkeypatch, approval_env):
    """2026-11-10 검토 관문: 스탬프가 통과로 바뀌어 있어도 게시 본문에 자격증명 꼴이 있으면 put 전에 멈춘다(가짜 값)."""
    approval_env("9")
    sent = _apply_setup(tmp_path, monkeypatch)
    (tmp_path / "p.json").write_text('[{"anchor":"AAA","new":"password = FAKEpw12345"}]')
    with pytest.raises(SystemExit) as e:
        cpp.main()
    assert "검토 관문" in str(e.value) and "FAKEpw" not in str(e.value) and not sent


def test_future_skeleton_stamp_is_invalid(tmp_path, monkeypatch):
    """2026-11-10 검수: 시각이 미래인 스탬프는 무효, 지금 시각이면 유효."""
    monkeypatch.setattr(cpp, "SKELETON_STAMP_DIR", str(tmp_path))
    h = cpp.hashlib.sha256(b"<p>x</p>").hexdigest()
    for when, ok in ((time.time() + 3600, False), (time.time(), True)):
        iso = cpp.datetime.fromtimestamp(when).astimezone().isoformat()
        (tmp_path / f"{h}.json").write_text(json.dumps({"time": iso}))
        assert cpp._skeleton_stamp_ok("<p>x</p>") is ok


def test_main_rejects_bad_site_before_any_call(monkeypatch):
    monkeypatch.setattr(cpp, "SITE", "http://evil.atlassian.net")
    monkeypatch.setattr(cpp, "get_page", lambda pid: pytest.fail("network call"))
    monkeypatch.setattr(sys, "argv", ["x", "--page", "9", "--probe", "a"])
    with pytest.raises(SystemExit):
        cpp.main()
