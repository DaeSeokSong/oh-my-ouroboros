"""confluence_patch_page.py 회귀 테스트 (네트워크 없음 — get_page·put_page 를 가짜로 바꾼다).

실행: uv run --with pytest --with requests python -m pytest scripts/tests/test_confluence_patch_page.py -q
REF: knowledge/harness/code-history/scripts__tests__test_confluence_patch_page.py.md
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
except ImportError:
    sys.modules["requests"] = types.ModuleType("requests")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import confluence_patch_page as cpp


def test_sequential_replace_interference_is_avoided():
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
    home = tmp_path / "home"
    log = home / ".claude/projects/p/s1.jsonl"
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
    monkeypatch.setattr(cpp, "SITE", "https://a.atlassian.net")
    monkeypatch.setattr(cpp, "get_page", lambda pid: ("T", 3, "AAA ... BBB ..."))
    monkeypatch.setattr(cpp, "_skeleton_stamp_ok", lambda body: True)
    monkeypatch.setattr(cpp, "_home_is_real", lambda: True)
    sent = {}
    monkeypatch.setattr(cpp, "put_page", lambda pid, title, ver, body, msg, minor=False: sent.update(body=body, minor=minor) or ver + 1)
    pf = tmp_path / "p.json"
    pf.write_text('[{"anchor":"AAA","new":"BBB"},{"anchor":"BBB","new":"CCC"}]')
    monkeypatch.setattr(sys, "argv", ["x", "--page", "9", "--patches", str(pf), "--apply",
                                      "--backup-dir", str(tmp_path), *extra_argv])
    return sent


def test_main_apply_path_uses_original_position_replacement(tmp_path, monkeypatch, approval_env):
    approval_env("9")
    sent = _apply_setup(tmp_path, monkeypatch)
    cpp.main()
    assert sent["body"] == "BBB ... CCC ..."


def test_apply_without_publish_approval_stops_before_put(tmp_path, monkeypatch, approval_env):
    sent = _apply_setup(tmp_path, monkeypatch)
    with pytest.raises(SystemExit) as e:
        cpp.main()
    assert "AskUserQuestion" in str(e.value) and not sent


def test_apply_minor_mismatching_approval_notify_stops(tmp_path, monkeypatch, approval_env):
    approval_env("9", notify="notify")
    sent = _apply_setup(tmp_path, monkeypatch, ["--minor"])
    with pytest.raises(SystemExit):
        cpp.main()
    assert not sent


def test_apply_minor_with_quiet_approval_passes_and_consumes(tmp_path, monkeypatch, approval_env):
    approval_env("9", notify="quiet")
    sent = _apply_setup(tmp_path, monkeypatch, ["--minor"])
    cpp.main()
    assert sent["minor"] is True
    sent.clear()
    with pytest.raises(SystemExit):
        cpp.main()
    assert not sent


def test_apply_message_mismatch_stops(tmp_path, monkeypatch, approval_env):
    approval_env("9", message="다른 설명")
    sent = _apply_setup(tmp_path, monkeypatch)
    with pytest.raises(SystemExit):
        cpp.main()
    assert not sent


def test_apply_cancelled_approval_stops(tmp_path, monkeypatch, approval_env):
    approval_env("9", answer="취소")
    sent = _apply_setup(tmp_path, monkeypatch)
    with pytest.raises(SystemExit) as e:
        cpp.main()
    assert "AskUserQuestion" in str(e.value) and not sent


def test_apply_with_fake_home_stops_before_put(tmp_path, monkeypatch, approval_env):
    approval_env("9")
    real_check = cpp._home_is_real
    sent = _apply_setup(tmp_path, monkeypatch)
    monkeypatch.setattr(cpp, "_home_is_real", real_check)
    with pytest.raises(SystemExit) as e:
        cpp.main()
    assert "HOME" in str(e.value) and not sent


def test_apply_non_numeric_page_stops(tmp_path, monkeypatch, approval_env):
    sent = _apply_setup(tmp_path, monkeypatch)
    monkeypatch.setattr(cpp, "get_page", lambda pid: ("T", 3, "AAA ... BBB ..."))
    monkeypatch.setattr(sys, "argv", [("AbC" if a == "9" else a) for a in sys.argv])
    with pytest.raises(SystemExit) as e:
        cpp.main()
    assert "숫자 페이지 ID" in str(e.value) and not sent


def test_dry_run_does_not_need_or_consume_approval(tmp_path, monkeypatch, approval_env):
    approval_env("9")
    sent = _apply_setup(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", [a for a in sys.argv if a != "--apply"])
    cpp.main()
    assert not sent
    monkeypatch.setattr(sys, "argv", sys.argv + ["--apply"])
    cpp.main()
    assert sent["body"] == "BBB ... CCC ..."


def test_apply_with_credential_in_new_body_stops_before_put(tmp_path, monkeypatch, approval_env):
    approval_env("9")
    sent = _apply_setup(tmp_path, monkeypatch)
    (tmp_path / "p.json").write_text('[{"anchor":"AAA","new":"password = FAKEpw12345"}]')
    with pytest.raises(SystemExit) as e:
        cpp.main()
    assert "검토 관문" in str(e.value) and "FAKEpw" not in str(e.value) and not sent


def test_future_skeleton_stamp_is_invalid(tmp_path, monkeypatch):
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


import confluence_publish_approve as cpa
import confluence_review_gate as crg
import korean_style_check as ksc

BODY0 = "AAA ... BBB ... <p>원문 그대로</p>"


def _change_line(page, notify="notify", message="최신 결과 반영", title=None, parent=None):
    line = f"게시 승인 요청 · page={page} · 알림={notify} · 버전 설명=«{message}»"
    if title is not None:
        line += f" · 새 제목=«{title}»"
    if parent is not None:
        line += f" · 새 부모={parent}"
    return line


@pytest.fixture
def server(tmp_path, monkeypatch):
    home = tmp_path / "home"
    log = home / ".claude/projects/p/s1.jsonl"
    log.parent.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    pages = {"9": {"title": "T", "spaceId": "S1", "parentId": "100", "version": 3, "body": BODY0},
             "100": {"title": "부모A", "spaceId": "S1", "parentId": None, "version": 1, "body": ""},
             "200": {"title": "부모B", "spaceId": "S1", "parentId": None, "version": 1, "body": ""},
             "300": {"title": "다른 공간", "spaceId": "S2", "parentId": None, "version": 1, "body": ""}}
    st = {"pages": pages, "puts": [], "calls": [], "honor_parent": True, "keep_parent_on_title": True}

    def get_page(pid):
        p = pages[pid]
        return p["title"], p["version"], p["body"]

    def get_page_info(pid, with_body=False):
        p = pages.get(str(pid))
        return None if p is None else {**p, "body": p["body"] if with_body else None}

    def put_page(pid, title, ver, body, msg, minor=False, parent_id=None):
        st["puts"].append({"title": title, "body": body, "parent_id": parent_id, "minor": minor})
        p = pages[pid]
        p.update(title=title, body=body, version=ver + 1)
        if parent_id is not None and st["honor_parent"]:
            p["parentId"] = parent_id
        if not st["keep_parent_on_title"]:
            p["parentId"] = "999"
        return ver + 1

    monkeypatch.setattr(cpp, "SITE", "https://a.atlassian.net")
    monkeypatch.setattr(cpp, "get_page", get_page)
    monkeypatch.setattr(cpp, "get_page_info", get_page_info)
    monkeypatch.setattr(cpp, "put_page", put_page)
    monkeypatch.setattr(cpp, "_home_is_real", lambda: True)
    monkeypatch.setattr(cpp, "_skeleton_stamp_ok", lambda body: st["calls"].append("skeleton") or True)
    monkeypatch.setattr(crg, "scan", lambda text: st["calls"].append("review") or [])
    monkeypatch.setattr(ksc, "regression", lambda *a, **k: st["calls"].append("style") or 0)
    n = [0]

    def approve(**kw):
        n[0] += 1
        q = "아래 게시를 승인하시겠습니까?\n" + _change_line(kw.pop("page", "9"), **kw)
        qs = [{"question": q, "header": "승인", "options": [{"label": "게시 승인", "description": "d"}, {"label": "취소", "description": "d"}]}]
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        tuid = f"toolu_change_{n[0]}"
        use = {"type": "assistant", "isSidechain": False, "timestamp": now,
               "message": {"role": "assistant", "content": [{"type": "tool_use", "name": "AskUserQuestion", "id": tuid, "input": {"questions": qs}}]}}
        res = {"type": "user", "isSidechain": False, "timestamp": now,
               "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tuid, "content": "ok"}]},
               "toolUseResult": {"questions": qs, "answers": {q: "게시 승인"}, "annotations": {}}}
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps(use, ensure_ascii=False) + "\n" + json.dumps(res, ensure_ascii=False) + "\n")

    def run(*args, apply=True):
        monkeypatch.setattr(sys, "argv", ["x", "--page", "9", "--backup-dir", str(tmp_path), *args, *(["--apply"] if apply else [])])
        return cpp.main()

    st["approve"], st["run"] = approve, run
    st["ledger"] = home / ".claude/_audit/publish-approval/used.tsv"
    return st


def _stops(server, *args, apply=True):
    with pytest.raises(SystemExit) as e:
        server["run"](*args, apply=apply)
    assert e.value.code not in (0, None) and not server["puts"]
    return str(e.value.code)


def test_change_title_only_puts_new_title_same_body_no_parent_and_skips_body_checks(server, capsys):
    server["approve"](title="새 이름")
    server["run"]("--title", "  새 이름 ")
    put = server["puts"][0]
    assert put["title"] == "새 이름" and put["parent_id"] is None and put["body"] == BODY0
    assert server["calls"] == []
    out = capsys.readouterr().out
    assert "본문 검사 세 가지" in out and "«T» → «새 이름»" in out and "본문 그대로" in out


def test_change_parent_only_puts_parent_id_and_keeps_title(server, capsys):
    server["approve"](parent="200")
    server["run"]("--parent", "0200")
    put = server["puts"][0]
    assert put["title"] == "T" and put["parent_id"] == "200" and put["body"] == BODY0 and server["calls"] == []
    assert "100(부모A) → 200(부모B)" in capsys.readouterr().out


def test_change_title_and_parent_together(server):
    server["approve"](title="새 이름", parent="200")
    server["run"]("--title", "새 이름", "--parent", "200")
    put = server["puts"][0]
    assert (put["title"], put["parent_id"], put["body"]) == ("새 이름", "200", BODY0)


def test_change_with_patches_runs_all_body_checks(server, tmp_path):
    (tmp_path / "p.json").write_text('[{"anchor":"AAA","new":"ZZZ"}]')
    server["approve"](title="새 이름", parent="200")
    server["run"]("--patches", str(tmp_path / "p.json"), "--title", "새 이름", "--parent", "200")
    put = server["puts"][0]
    assert put["body"] == BODY0.replace("AAA", "ZZZ") and put["title"] == "새 이름" and put["parent_id"] == "200"
    assert sorted(server["calls"]) == ["review", "skeleton", "style"]


def test_change_without_approval_stops(server):
    assert "AskUserQuestion" in _stops(server, "--title", "새 이름")


def test_change_title_mismatch_stops(server):
    server["approve"](title="다른 이름")
    _stops(server, "--title", "새 이름")


def test_change_parent_mismatch_stops(server):
    server["approve"](parent="100")
    _stops(server, "--parent", "200")


def test_plain_approval_cannot_change_title(server):
    server["approve"]()
    _stops(server, "--title", "새 이름")


def test_field_approval_cannot_be_used_for_patch_only_call(server, tmp_path):
    (tmp_path / "p.json").write_text('[{"anchor":"AAA","new":"ZZZ"}]')
    server["approve"](title="새 이름")
    _stops(server, "--patches", str(tmp_path / "p.json"))


@pytest.mark.parametrize("args, hint", [(("--parent", "300"), "다른 공간"), (("--parent", "9"), "자기 자신"),
                                        (("--parent", "abc"), "숫자 페이지 ID"), (("--title", "   "), "비어"),
                                        (("--title", "줄\n바꿈"), "제어문자"), (("--parent", "404"), "조회 실패")])
def test_change_invalid_target_stops_without_consuming(server, args, hint):
    server["approve"](parent=args[1]) if args[0] == "--parent" and args[1].isdigit() else server["approve"](title="x")
    assert hint in _stops(server, *args)
    assert not server["ledger"].exists()


def test_change_parent_without_space_id_stops_without_consuming(server):
    server["pages"]["400"] = {"title": "공간 모름", "spaceId": None, "parentId": None, "version": 1, "body": ""}
    server["approve"](parent="400")
    assert "공간을 확인할 수 없어" in _stops(server, "--parent", "400")
    assert not server["ledger"].exists()


def test_change_title_only_ignores_missing_space_id(server):
    server["pages"]["9"]["spaceId"] = None
    server["approve"](title="새 이름")
    server["run"]("--title", "새 이름")
    assert server["puts"][0]["title"] == "새 이름"


@pytest.mark.parametrize("bad", [chr(0x202E) + "뒤집힘", "폭" + chr(0x200B) + "없음", chr(0x2066) + "격리"])
def test_change_title_with_invisible_or_bidi_char_stops(server, bad):
    server["approve"](title="x")
    assert "보이지 않는 글자" in _stops(server, "--title", bad)
    assert not server["ledger"].exists()


def test_change_title_with_guillemets_passes(server):
    server["approve"](title="새 «이름» Name")
    server["run"]("--title", "새 «이름» Name")
    assert server["puts"][0]["title"] == "새 «이름» Name"


def test_change_nothing_to_change_does_not_consume(server, capsys):
    server["approve"](title="T", parent="100")
    server["run"]("--title", "T", "--parent", "100")
    assert not server["puts"] and not server["ledger"].exists() and "바꿀 것 없음" in capsys.readouterr().out


def test_change_dry_run_neither_reads_nor_consumes_approval(server, monkeypatch, capsys):
    monkeypatch.setattr(cpa, "check_and_consume", lambda **k: pytest.fail("dry-run consulted the approval"))
    monkeypatch.setattr(cpa, "find_approval", lambda *a, **k: pytest.fail("dry-run consulted the approval"))
    server["run"]("--title", "새 이름", "--parent", "200", apply=False)
    out = capsys.readouterr().out
    assert not server["puts"] and "dry-run 종료" in out and "«T» → «새 이름»" in out and "100(부모A) → 200(부모B)" in out


def test_change_reread_parent_mismatch_exits_nonzero(server):
    server["approve"](parent="200")
    server["honor_parent"] = False
    with pytest.raises(SystemExit) as e:
        server["run"]("--parent", "200")
    assert e.value.code not in (0, None) and "부모" in str(e.value.code) and server["puts"]


def test_change_title_only_detects_parent_moved_by_server(server):
    server["approve"](title="새 이름")
    server["keep_parent_on_title"] = False
    with pytest.raises(SystemExit) as e:
        server["run"]("--title", "새 이름")
    assert e.value.code not in (0, None) and "부모 999" in str(e.value.code)


def test_change_body_hash_difference_only_warns(server, monkeypatch, capsys):
    server["approve"](title="새 이름")
    orig = cpp.put_page

    def normalizing_put(*a, **k):
        v = orig(*a, **k)
        server["pages"]["9"]["body"] += " "
        return v
    monkeypatch.setattr(cpp, "put_page", normalizing_put)
    server["run"]("--title", "새 이름")
    assert "★경고: 재조회 본문이 백업과 다름" in capsys.readouterr().out


CREATE_BODY = "<h1>새 페이지</h1>\r\n<p>본문 «그대로» &amp; 끝 공백  </p>\n"


@pytest.fixture
def creator(tmp_path, monkeypatch):
    home = tmp_path / "home"
    log = home / ".claude/projects/p/s1.jsonl"
    log.parent.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    pages = {"100": {"title": "부모A", "spaceId": "77", "parentId": None, "version": 1, "body": ""},
             "300": {"title": "다른 공간", "spaceId": "88", "parentId": None, "version": 1, "body": ""},
             "400": {"title": "공간 모름", "spaceId": None, "parentId": None, "version": 1, "body": ""}}
    st = {"pages": pages, "posts": [], "calls": [], "server_title": None, "server_body_suffix": ""}

    def get_page_info(pid, with_body=False):
        p = pages.get(str(pid))
        return None if p is None else {**p, "body": p["body"] if with_body else None}

    def post_page(space, parent, title, body):
        st["posts"].append({"space": space, "parent": parent, "title": title, "body": body})
        pages["5001"] = {"title": st["server_title"] or title, "spaceId": space, "parentId": parent,
                         "version": 1, "body": body + st["server_body_suffix"]}
        return "5001"

    monkeypatch.setattr(cpp, "SITE", "https://a.atlassian.net")
    monkeypatch.setattr(cpp, "get_page", lambda pid: pytest.fail("--create must not read an existing page"))
    monkeypatch.setattr(cpp, "get_page_info", get_page_info)
    monkeypatch.setattr(cpp, "post_page", post_page)
    monkeypatch.setattr(cpp, "_home_is_real", lambda: True)
    monkeypatch.setattr(cpp, "_skeleton_stamp_ok", lambda body: st["calls"].append("skeleton") or True)
    monkeypatch.setattr(crg, "scan", lambda text: st["calls"].append(("review", text.split("\n", 1)[0])) or [])
    monkeypatch.setattr(ksc, "report", lambda body, *a, **k: st["calls"].append("style") or 0)
    bf = tmp_path / "body.storage.html"
    bf.write_bytes(CREATE_BODY.encode("utf-8"))
    n = [0]

    def approve(space="77", parent="100", title="새 페이지"):
        n[0] += 1
        q = f"아래 게시를 승인하시겠습니까?\n게시 승인 요청 · new · space={space} · parent={parent or '없음'} · 제목=«{title}»"
        qs = [{"question": q, "header": "승인", "options": [{"label": "게시 승인", "description": "d"}, {"label": "취소", "description": "d"}]}]
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        tuid = f"toolu_create_{n[0]}"
        use = {"type": "assistant", "isSidechain": False, "timestamp": now,
               "message": {"role": "assistant", "content": [{"type": "tool_use", "name": "AskUserQuestion", "id": tuid, "input": {"questions": qs}}]}}
        res = {"type": "user", "isSidechain": False, "timestamp": now,
               "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tuid, "content": "ok"}]},
               "toolUseResult": {"questions": qs, "answers": {q: "게시 승인"}, "annotations": {}}}
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps(use, ensure_ascii=False) + "\n" + json.dumps(res, ensure_ascii=False) + "\n")

    def run(*args, apply=True, base=("--space", "77", "--parent", "100", "--title", "새 페이지")):
        monkeypatch.setattr(sys, "argv", ["x", "--create", *base, "--body-file", str(bf), *args, *(["--apply"] if apply else [])])
        return cpp.main()

    st.update(approve=approve, run=run, file=bf, ledger=home / ".claude/_audit/publish-approval/used.tsv")
    return st


def _create_stops(creator, *args, apply=True, **kw):
    with pytest.raises(SystemExit) as e:
        creator["run"](*args, apply=apply, **kw)
    assert e.value.code not in (0, None) and not creator["posts"]
    return str(e.value.code)


def test_create_apply_posts_file_body_verbatim_and_prints_page_id(creator, capsys):
    creator["approve"]()
    creator["run"]()
    assert creator["posts"] == [{"space": "77", "parent": "100", "title": "새 페이지", "body": CREATE_BODY}]
    assert creator["calls"] == ["style", ("review", "새 페이지"), "skeleton"]
    out = capsys.readouterr().out
    assert "PAGE_ID=5001" in out.splitlines() and "생성: ID 5001" in out
    assert f"본문이 파일과 같음(sha256 {cpp.hashlib.sha256(CREATE_BODY.encode()).hexdigest()[:16]}… 일치)" in out


def test_create_without_parent(creator, capsys):
    creator["approve"](parent=None)
    creator["run"](base=("--space", "77", "--title", "새 페이지"))
    assert creator["posts"][0]["parent"] is None
    assert "parent=없음" in capsys.readouterr().out


def test_create_dry_run_neither_posts_nor_reads_approval_and_prints_question_command(creator, monkeypatch, capsys):
    monkeypatch.setattr(cpa, "check_and_consume_new", lambda *a, **k: pytest.fail("dry-run consulted the approval"))
    monkeypatch.setattr(cpa, "find_approval", lambda *a, **k: pytest.fail("dry-run consulted the approval"))
    creator["run"](apply=False, base=("--space", "077", "--parent", "0100", "--title", "  새 페이지 "))
    out = capsys.readouterr().out
    assert not creator["posts"] and "dry-run 종료" in out and creator["calls"] == ["style"]
    assert "confluence_publish_approve.py question --new --space=77 --parent=100 --title='새 페이지'" in out
    assert "게시 승인 요청 · new · space=77 · parent=100 · 제목=«새 페이지»" in out


def test_create_without_approval_stops(creator):
    assert "AskUserQuestion" in _create_stops(creator)


@pytest.mark.parametrize("kw", [{"space": "78"}, {"parent": "101"}, {"title": "다른 페이지"}, {"parent": None}])
def test_create_mismatching_approval_stops(creator, kw):
    creator["approve"](**kw)
    _create_stops(creator)


def test_create_consumes_approval_once(creator):
    creator["approve"]()
    creator["run"]()
    creator["posts"].clear()
    assert "이미" in _create_stops(creator)


@pytest.mark.parametrize("which", ["style", "review", "skeleton"])
def test_create_body_check_blocks_before_post_without_consuming(creator, monkeypatch, which):
    creator["approve"]()
    if which == "style":
        monkeypatch.setattr(ksc, "report", lambda *a, **k: 1)
    elif which == "review":
        monkeypatch.setattr(crg, "scan", lambda text: ["토큰 꼴 (3행)"])
    else:
        monkeypatch.setattr(cpp, "_skeleton_stamp_ok", lambda body: False)
    _create_stops(creator)
    assert not creator["ledger"].exists()


def test_create_invalid_inputs_stop(creator, tmp_path):
    cases = [(("--space", "abc", "--title", "T"), "공간 ID"), (("--space", "77", "--parent", "x1", "--title", "T"), "부모"),
             (("--space", "77", "--title", "   "), "비어"), (("--space", "77", "--title", chr(0x202E) + "T"), "보이지 않는 글자"),
             (("--space", "77", "--title", "가\t나"), "제어문자"), (("--space", "77"), "제목")]
    for base, hint in cases:
        assert hint in _create_stops(creator, base=base), base
    files = {"없는 파일": None, "빈 파일": b"  \n", "큰 파일": b"a" * (4 * 1024 * 1024 + 1), "UTF-8 아님": "본문".encode("euc-kr")}
    hints = {"없는 파일": "없음", "빈 파일": "비어", "큰 파일": "4MB", "UTF-8 아님": "UTF-8"}
    for label, data in files.items():
        if data is None:
            creator["file"].unlink()
        else:
            creator["file"].write_bytes(data)
        assert hints[label] in _create_stops(creator), label
    assert not creator["ledger"].exists()


@pytest.mark.parametrize("parent, hint", [("300", "다른 공간"), ("404", "조회 실패"), ("400", "공간을 확인할 수 없어")])
def test_create_bad_parent_stops(creator, parent, hint):
    creator["approve"](parent=parent)
    assert hint in _create_stops(creator, base=("--space", "77", "--parent", parent, "--title", "새 페이지"))
    assert not creator["ledger"].exists()


@pytest.mark.parametrize("extra", [("--page", "9"), ("--patches", "p.json"), ("--probe",), ("--minor",)])
def test_create_conflicting_flags_are_usage_errors(creator, extra):
    with pytest.raises(SystemExit) as e:
        creator["run"](*extra)
    assert e.value.code == 2 and not creator["posts"]


def test_page_still_required_without_create(monkeypatch):
    monkeypatch.setattr(cpp, "SITE", "https://a.atlassian.net")
    monkeypatch.setattr(sys, "argv", ["x", "--probe", "a"])
    with pytest.raises(SystemExit) as e:
        cpp.main()
    assert e.value.code == 2


def test_create_message_is_noted_as_unused(creator, capsys):
    creator["run"]("--message", "설명", apply=False)
    assert "생성에는 버전 설명이 실리지 않는다" in capsys.readouterr().out


class _Resp:
    def __init__(self, code, text="", data=None):
        self.status_code, self.text, self._data = code, text, data

    def json(self):
        return self._data


def test_post_page_server_rejection_exits_with_consumed_note(monkeypatch):
    monkeypatch.setattr(cpp, "SITE", "https://a.atlassian.net")
    monkeypatch.setattr(cpp, "auth", lambda: ("u", "fake"))
    monkeypatch.setattr(cpp.requests, "post", lambda *a, **k: _Resp(400, "title already exists " + "x" * 900))
    with pytest.raises(SystemExit) as e:
        cpp.post_page("77", "100", "T", "<p>b</p>")
    msg = str(e.value.code)
    assert msg.startswith("[실패] 400") and "승인은 이미 소모됐다" in msg and len(msg) < 700


def test_post_page_timeout_is_unknown_outcome_and_sends_once(monkeypatch):
    monkeypatch.setattr(cpp, "SITE", "https://a.atlassian.net")
    monkeypatch.setattr(cpp, "auth", lambda: ("u", "fake"))
    sent = []

    def boom(*a, **k):
        sent.append(k["json"])
        raise cpp.requests.ConnectionError("reset")
    monkeypatch.setattr(cpp.requests, "post", boom)
    with pytest.raises(SystemExit) as e:
        cpp.post_page("77", None, "T", "<p>b</p>")
    assert "만들어졌는지 알 수 없다" in str(e.value.code) and len(sent) == 1 and "parentId" not in sent[0]


def test_create_reread_mismatch_exits_nonzero(creator, capsys):
    creator["approve"]()
    creator["server_title"] = "서버가 바꾼 제목"
    with pytest.raises(SystemExit) as e:
        creator["run"]()
    assert e.value.code not in (0, None) and "제목" in str(e.value.code)
    assert "PAGE_ID=5001" in capsys.readouterr().out


@pytest.mark.parametrize("resp", [_Resp(200, "<html>not json</html>"), _Resp(200, "{}", {}), _Resp(200, "x", {"id": "../9"}),
                                  _Resp(200, "x", ["5001"])])
def test_post_page_unreadable_id_exits_without_traceback(monkeypatch, resp):
    def bad_json():
        raise ValueError("no json")
    if resp._data is None:
        resp.json = bad_json
    monkeypatch.setattr(cpp, "SITE", "https://a.atlassian.net")
    monkeypatch.setattr(cpp, "auth", lambda: ("u", "fake"))
    monkeypatch.setattr(cpp.requests, "post", lambda *a, **k: resp)
    with pytest.raises(SystemExit) as e:
        cpp.post_page("77", None, "T", "<p>b</p>")
    assert "새 ID 를 읽지 못했다" in str(e.value.code)


def test_post_page_numeric_id_from_json_number(monkeypatch):
    monkeypatch.setattr(cpp, "SITE", "https://a.atlassian.net")
    monkeypatch.setattr(cpp, "auth", lambda: ("u", "fake"))
    monkeypatch.setattr(cpp.requests, "post", lambda *a, **k: _Resp(200, "x", {"id": 5001}))
    assert cpp.post_page("77", None, "T", "<p>b</p>") == "5001"


def test_create_question_command_works_for_dash_title(creator, capsys):
    import shlex
    creator["run"](apply=False, base=("--space", "77", "--parent", "100", "--title", "-foo 결과"))
    cmd = next(ln for ln in capsys.readouterr().out.splitlines() if "confluence_publish_approve.py question" in ln)
    argv = shlex.split(cmd)
    assert cpa.main(argv[argv.index("question"):]) == 0
    assert "게시 승인 요청 · new · space=77 · parent=100 · 제목=«-foo 결과»" in capsys.readouterr().out


def test_create_space_with_colon_is_rejected(creator):
    assert "공간 ID" in _create_stops(creator, base=("--space", "1:5", "--title", "x"))


def test_create_body_hash_difference_only_warns(creator, capsys):
    creator["approve"]()
    creator["server_body_suffix"] = " "
    creator["run"]()
    assert "★경고: 재조회 본문이 파일과 다름" in capsys.readouterr().out
