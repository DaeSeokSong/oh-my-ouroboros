"""jira_comment.py 회귀 테스트 (가짜 전송 계층, 실제 네트워크·실제 HOME 금지).
REF: knowledge/harness/code-history/scripts__tests__test_jira_comment.py.md
"""
import base64
import copy
import hashlib
import io
import json
import os
import re
import struct
import sys
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import jira_comment as jc

REAL_HTTP = jc.http
REAL_OPEN = jc._open
ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / ".scratch/0a1b2c3d/jira/abc123_10001.adf.json"
# WHY: 시험용 가짜 값. 리터럴 한 덩어리로 쓰면 커밋 시크릿 검사가 오탐한다(2026-10-01)
FAKE_CRED = "-".join(["FAKE", "CRED", "123"])   # noqa: FLY002
TOKEN = FAKE_CRED
SKILL = (
    "# x\n\n## Jira 댓글 자동 기록 (MANDATORY)\n\n댓글 형식 규칙:\n* 줄 수: 10줄 이내\n\n"
    "### Jira 댓글 쓰기·고치기 = REST\n\n본문 아래\n"
)


class Fake:

    def __init__(self):
        self.calls, self.comments, self.next_id, self.tamper = [], {}, 100, None
        self.override = {}
    def __call__(self, method, url, body=None):
        self.calls.append((method, url, body))
        m = re.search(r"/comment/(\d+)", url)
        if method in self.override:
            return self.override[method]
        if method == "POST":
            cid, self.next_id = str(self.next_id), self.next_id + 1
            self.comments[cid] = body["body"]
            return 201, {"id": cid}
        if method == "PUT":
            self.comments[m.group(1)] = body["body"]
            return 200, {"id": m.group(1)}
        if method == "GET" and m and m.group(1) in self.comments:
            b = self.comments[m.group(1)]
            return 200, {"id": m.group(1), "body": self.tamper(b) if self.tamper else b,
                         "created": "2026-09-29T00:00:00", "updated": "2026-09-30T00:00:00"}
        return 404, {"_raw": "nf"}

    def methods(self):
        return [c[0] for c in self.calls]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".atlassian_token").write_text(f"me@example.com\n{TOKEN}\n")
    skill = tmp_path / "SKILL.md"
    skill.write_text(SKILL, encoding="utf-8")
    monkeypatch.setattr(jc, "SKILL_PATH", skill)
    monkeypatch.delenv("JIRA_SITE", raising=False)
    monkeypatch.setattr(jc, "_cred_warned", False)
    monkeypatch.setattr(jc, "_open", lambda req, timeout=30: pytest.fail("real network call"))
    fake = Fake()
    monkeypatch.setattr(jc, "http", fake)
    body = tmp_path / "body.md"
    body.write_text("1. 첫째\n  * 하위\n    * 더 하위\n", encoding="utf-8")
    return type("E", (), {"home": tmp_path, "skill": skill, "fake": fake, "body": body})


def run(*args):
    return jc.main([str(x) for x in args])


def stamp_files(env):
    d = env.home / ".claude/_audit/jira-preview"
    return sorted(d.glob("*.json")) if d.exists() else []


def media_adf(text="앞 문장 하나"):
    return {"type": "doc", "version": 1, "content": [
        {"type": "bulletList", "content": [{"type": "listItem", "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": text}]},
            {"type": "mediaSingle", "attrs": {"layout": "center"}, "content": [
                {"type": "media", "attrs": {"type": "file", "id": "uuid-1", "collection": ""}}]}]}]}]}



def test_md_nested_lists_three_levels():
    adf = jc.md_to_adf("1. 가\n  * 나\n    * 다\n2. 라\n")
    ol = adf["content"][0]
    assert ol["type"] == "orderedList" and len(ol["content"]) == 2
    l1 = ol["content"][0]["content"][1]
    assert l1["type"] == "bulletList"
    l2 = l1["content"][0]["content"][1]
    assert l2["type"] == "bulletList"
    assert l2["content"][0]["content"][0]["content"][0]["text"] == "다"


def test_md_four_space_indent_and_dash_bullets():
    adf = jc.md_to_adf("- 가\n    - 나\n- 다\n")
    top = adf["content"][0]
    assert len(top["content"]) == 2
    assert top["content"][0]["content"][1]["type"] == "bulletList"


def test_md_inline_marks_and_code_block():
    adf = jc.md_to_adf("* **굵게** `코드` [글](https://x.io/a)\n  ```py\n  a = 1\n  ```\n")
    item = adf["content"][0]["content"][0]["content"]
    nodes = item[0]["content"]
    assert nodes[0] == {"type": "text", "text": "굵게", "marks": [{"type": "strong"}]}
    assert nodes[2] == {"type": "text", "text": "코드", "marks": [{"type": "code"}]}
    assert nodes[4]["marks"] == [{"type": "link", "attrs": {"href": "https://x.io/a"}}]
    cb = item[1]
    assert cb["type"] == "codeBlock" and cb["attrs"] == {"language": "py"}
    assert cb["content"][0]["text"] == "a = 1"


def test_md_urls_card_vs_link_and_plain_paragraph():
    adf = jc.md_to_adf("* 문서 https://your-company-prod.atlassian.net/wiki/spaces/A/pages/1 참고 https://example.com/p.\n설명 문단\n")
    nodes = adf["content"][0]["content"][0]["content"][0]["content"]
    assert {"type": "inlineCard", "attrs": {"url": "https://your-company-prod.atlassian.net/wiki/spaces/A/pages/1"}} in nodes
    link = next(n for n in nodes if n.get("marks"))
    assert link["text"] == "https://example.com/p"
    assert nodes[-1]["text"] == "."
    assert adf["content"][1]["type"] == "paragraph"


@pytest.mark.skipif(not SAMPLE.exists(), reason="sample ADF absent")
def test_sample_adf_renders_three_numbered_items():
    adf = json.loads(SAMPLE.read_text(encoding="utf-8"))
    text = jc.adf_to_text(adf)
    assert len(re.findall(r"^\d+\. ", text, re.MULTILINE)) == 3
    assert "[이미지]" in text



def test_preview_prints_rules_verbatim(env, capsys):
    assert run("preview", "--issue", "PROJ-1", "--body-file", env.body) == 0
    out = capsys.readouterr().out
    section = SKILL.split("\n### Jira 댓글 쓰기")[0].split("# x\n\n")[1].rstrip()
    assert section in out
    assert "notifyUsers=false" in out and "미리보기" in out
    assert "* 하위" not in out.split("== 형식 규칙")[0]
    assert len(stamp_files(env)) == 1


def test_preview_follows_skill_file_changes(env, capsys):
    env.skill.write_text(SKILL.replace("10줄 이내", "7줄 이내"), encoding="utf-8")
    run("preview", "--issue", "PROJ-1", "--body-file", env.body)
    out = capsys.readouterr().out
    assert "7줄 이내" in out and "10줄 이내" not in out


def test_preview_missing_section_rc2(env, capsys):
    env.skill.write_text("# nothing here\n", encoding="utf-8")
    assert run("preview", "--issue", "PROJ-1", "--body-file", env.body) == 2
    assert stamp_files(env) == []


def test_preview_warnings(env, capsys):
    env.body.write_text("문단입니다\n* " + "가" * 201 + "\n", encoding="utf-8")
    run("preview", "--issue", "PROJ-1", "--body-file", env.body)
    out = capsys.readouterr().out
    assert "목록 밖 문단" in out and "200자" in out
    env.body.write_text("", encoding="utf-8")
    run("preview", "--issue", "PROJ-1", "--body-file", env.body)
    assert "본문이 비었습니다" in capsys.readouterr().out



def test_post_without_stamp_rc3_no_calls(env, capsys):
    assert run("post", "--issue", "PROJ-1", "--body-file", env.body) == 3
    assert env.fake.calls == []
    assert "preview" in capsys.readouterr().err


def test_preview_then_post_ok_and_stamp_removed(env, capsys):
    run("preview", "--issue", "PROJ-1", "--body-file", env.body)
    assert run("post", "--issue", "PROJ-1", "--body-file", env.body) == 0
    assert env.fake.methods() == ["POST", "GET"]
    out = capsys.readouterr().out
    assert "focusedCommentId=100" in out and "/browse/PROJ-1" in out
    assert stamp_files(env) == []
    assert run("post", "--issue", "PROJ-1", "--body-file", env.body) == 3

def test_post_changed_body_other_issue_and_expired(env):
    run("preview", "--issue", "PROJ-1", "--body-file", env.body)
    assert run("post", "--issue", "PROJ-2", "--body-file", env.body) == 3
    env.body.write_text("* 다른 본문\n", encoding="utf-8")
    assert run("post", "--issue", "PROJ-1", "--body-file", env.body) == 3
    assert env.fake.calls == []
    env.body.write_text("* 원래\n", encoding="utf-8")
    run("preview", "--issue", "PROJ-1", "--body-file", env.body)
    for f in stamp_files(env):
        rec = json.loads(f.read_text())
        rec["time"] = (datetime.now() - timedelta(hours=7)).isoformat()
        f.write_text(json.dumps(rec))
    assert run("post", "--issue", "PROJ-1", "--body-file", env.body) == 3
    assert env.fake.calls == []


def test_stamp_permissions(env):
    run("preview", "--issue", "PROJ-1", "--body-file", env.body)
    f = stamp_files(env)[0]
    assert oct(f.stat().st_mode & 0o777) == "0o600"
    assert oct(f.parent.stat().st_mode & 0o777) == "0o700"


def test_post_verify_mismatch_rc4(env, capsys):
    run("preview", "--issue", "PROJ-1", "--body-file", env.body)
    env.fake.tamper = lambda b: jc.md_to_adf("* 다른 본문\n")
    assert run("post", "--issue", "PROJ-1", "--body-file", env.body) == 4
    assert "게시는 완료" in capsys.readouterr().err



def test_update_body_file_notify_false_and_backup(env):
    env.fake.comments["7"] = jc.md_to_adf("* 옛 본문\n")
    run("preview", "--issue", "PROJ-1", "--comment-id", 7, "--body-file", env.body)
    assert run("update", "--issue", "PROJ-1", "--comment-id", 7, "--body-file", env.body) == 0
    put = next(c for c in env.fake.calls if c[0] == "PUT")
    assert put[1].endswith("/comment/7?notifyUsers=false")
    backups = list((env.home / ".claude/_audit/jira-preview").glob("backup-PROJ-1-7-*.adf.json"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text()) == jc.md_to_adf("* 옛 본문\n")
    assert oct(backups[0].stat().st_mode & 0o777) == "0o600"


def test_update_body_file_rejected_when_media(env, capsys):
    env.fake.comments["7"] = media_adf()
    assert run("update", "--issue", "PROJ-1", "--comment-id", 7, "--body-file", env.body) == 2
    assert "--patches" in capsys.readouterr().err
    assert "PUT" not in env.fake.methods()


def test_update_patches_preserves_media_and_other_nodes(env, capsys):
    orig = media_adf("앞 문장 하나")
    env.fake.comments["7"] = copy.deepcopy(orig)
    patches = env.home / "p.json"
    patches.write_text(json.dumps([{"anchor": "문장 하나", "new": "문장 둘"}]), encoding="utf-8")
    run("preview", "--issue", "PROJ-1", "--comment-id", 7, "--patches", patches)
    out = capsys.readouterr().out
    assert "- 전: 앞 문장 하나" in out and "+ 후: 앞 문장 둘" in out
    assert run("update", "--issue", "PROJ-1", "--comment-id", 7, "--patches", patches) == 0
    new = env.fake.comments["7"]
    assert jc.fingerprint(new)[2] == ["uuid-1"]
    expected = copy.deepcopy(orig)
    expected["content"][0]["content"][0]["content"][0]["content"][0]["text"] = "앞 문장 둘"
    assert new == expected


def test_update_patches_anchor_zero_or_multiple_rc2(env):
    adf = jc.md_to_adf("* 가나 가나\n")
    env.fake.comments["7"] = adf
    patches = env.home / "p.json"
    for anchor in ("없음", "가나"):
        patches.write_text(json.dumps([{"anchor": anchor, "new": "x"}]), encoding="utf-8")
        assert run("preview", "--issue", "PROJ-1", "--comment-id", 7, "--patches", patches) == 2
        assert run("update", "--issue", "PROJ-1", "--comment-id", 7, "--patches", patches) == 2
    assert "PUT" not in env.fake.methods()
    assert env.fake.comments["7"] == adf and stamp_files(env) == []


def test_update_requires_stamp(env):
    env.fake.comments["7"] = jc.md_to_adf("* 옛\n")
    assert run("update", "--issue", "PROJ-1", "--comment-id", 7, "--body-file", env.body) == 3
    assert "PUT" not in env.fake.methods()



def test_get_summary_and_save(env, capsys):
    env.fake.comments["7"] = media_adf("요약 대상 문장")
    out_path = env.home / "saved.json"
    assert run("get", "--issue", "PROJ-1", "--comment-id", 7, "--save", out_path) == 0
    out = capsys.readouterr().out
    assert "bulletList" in out and "요약 대상 문장" in out and "uuid-1" in out
    assert json.loads(out_path.read_text()) == media_adf("요약 대상 문장")



def _issues(n):
    return {"issues": [{"key": f"PROJ-{i}", "fields": {"summary": f"제목 {i}", "status": {"name": "진행 중"},
                                                       "updated": "2026-10-23T01:00:00.000+0900"}} for i in range(1, n + 1)]}


def test_mine_json_shape_and_request(env, capsys):
    env.fake.override["POST"] = (200, _issues(2))
    assert run("mine", "--json") == 0
    out = capsys.readouterr().out
    assert json.loads(out) == [
        {"key": f"PROJ-{i}", "summary": f"제목 {i}", "status": "진행 중", "updated": "2026-10-23T01:00:00.000+0900",
         "url": f"https://your-company-prod.atlassian.net/browse/PROJ-{i}"} for i in (1, 2)]
    assert out.count("\n") == 1 and TOKEN not in out
    method, url, body = env.fake.calls[0]
    assert method == "POST" and url.endswith("/rest/api/3/search/jql") and body["maxResults"] == 10
    assert body["jql"].startswith("assignee = currentUser()") and body["fields"] == ["summary", "status", "updated"]


def test_mine_text_output(env, capsys):
    env.fake.override["POST"] = (200, _issues(1))
    assert run("mine") == 0
    assert capsys.readouterr().out == "PROJ-1  [진행 중]  제목 1\n"


@pytest.mark.parametrize("given,sent", [(0, 1), (31, 30), (5, 5)])
def test_mine_max_clamped(env, given, sent):
    env.fake.override["POST"] = (200, _issues(0))
    assert run("mine", "--max", given) == 0
    assert env.fake.calls[0][2]["maxResults"] == sent


@pytest.mark.parametrize("reply", [(401, {"errorMessages": [TOKEN]}), (0, {"_raw": "연결 실패: URLError"}),
                                   (200, {"nope": 1}), (200, {"issues": [{"fields": {}}]})])
def test_mine_errors_rc2(env, capsys, reply):
    env.fake.override["POST"] = reply
    assert run("mine", "--json") == 2
    cap = capsys.readouterr()
    err = json.loads(cap.out)
    assert list(err) == ["error"] and "\n" not in err["error"] and TOKEN not in cap.out + cap.err
    assert run("mine") == 2
    cap = capsys.readouterr()
    assert cap.out == "" and cap.err.strip() and TOKEN not in cap.err


def test_mine_unexpected_exception_prints_type_name_only_rc2(env, monkeypatch, capsys):
    def boom(*a, **k):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, TOKEN)
    monkeypatch.setattr(jc, "http", boom)
    assert run("mine", "--json") == 2
    cap = capsys.readouterr()
    assert json.loads(cap.out) == {"error": "UnicodeDecodeError"} and cap.err == ""
    assert run("mine") == 2
    cap = capsys.readouterr()
    assert cap.out == "" and cap.err == "예기치 못한 오류: UnicodeDecodeError\n" and "Traceback" not in cap.err and TOKEN not in cap.err


def test_token_never_leaks(env, monkeypatch, capsys):
    run("preview", "--issue", "PROJ-1", "--body-file", env.body)
    run("post", "--issue", "PROJ-1", "--body-file", env.body)
    monkeypatch.setattr(jc, "http", REAL_HTTP)

    def boom(req):
        assert req.get_header("Authorization")
        raise urllib.error.HTTPError(req.full_url, 401, "no", {}, io.BytesIO(f"bad {TOKEN}".encode()))

    monkeypatch.setattr(jc, "_open", boom)
    assert jc.main(["get", "--issue", "PROJ-1", "--comment-id", "9"]) == 5
    captured = capsys.readouterr()
    blob = captured.out + captured.err
    for f in (env.home / ".claude").rglob("*"):
        if f.is_file():
            blob += f.read_text()
    assert TOKEN not in blob
    assert base64.b64encode(f"me@example.com:{TOKEN}".encode()).decode() not in blob
    assert "HTTP 401" in blob



def test_arg_validation_rc2(env, capsys):
    bad_ids = ["7?notifyUsers=true#", "7\n", "٣", "7/x", "", "abc"]
    for bad in bad_ids:
        assert run("get", "--issue", "PROJ-1", "--comment-id", bad) == 2
        assert run("update", "--issue", "PROJ-1", "--comment-id", bad, "--body-file", env.body) == 2
    for bad in ["proj-1", "PROJ-1/../x", "PROJ-", "N-1", "PROJ-1\n", "PROJ-١"]:
        assert run("get", "--issue", bad, "--comment-id", "7") == 2
        assert run("preview", "--issue", bad, "--body-file", env.body) == 2
    assert env.fake.calls == [] and stamp_files(env) == []


class _Resp:

    def __init__(self, status=200, payload=b"{}", exc=None):
        self.status, self.payload, self.exc = status, payload, exc

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        if self.exc:
            raise self.exc
        return self.payload[:n] if n >= 0 else self.payload


def test_redirect_not_followed_and_auth_not_forwarded(env, monkeypatch):
    import http.server
    import threading
    hits = {"a": [], "b": []}

    def make(name, redirect_to=None):
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                hits[name].append(self.headers.get("Authorization"))
                if redirect_to:
                    self.send_response(302)
                    self.send_header("Location", redirect_to())
                else:
                    self.send_response(200)
                self.end_headers()

            def log_message(self, *a):
                pass
        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return srv

    b = make("b")
    a = make("a", lambda: f"http://127.0.0.1:{b.server_port}/x")
    monkeypatch.setenv("no_proxy", "*")
    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.setattr(jc, "_open", REAL_OPEN)
    try:
        status, _ = REAL_HTTP("GET", f"http://127.0.0.1:{a.server_port}/start")
    finally:
        a.shutdown()
        b.shutdown()
    assert status == 302
    assert len(hits["a"]) == 1 and hits["a"][0].startswith("Basic ")
    assert hits["b"] == []


def test_http_3xx_is_rc5(env, capsys):
    env.fake.override["GET"] = (302, {"_raw": "moved"})
    assert run("get", "--issue", "PROJ-1", "--comment-id", 7) == 5
    assert "HTTP 302" in capsys.readouterr().err


def test_jira_site_validation(env, monkeypatch, capsys):
    for bad in ["http://x.atlassian.net", "https://evil.com", "https://x.atlassian.net.evil.com",
                "https://atlassian.net", "https://x.atlassian.net/path"]:
        monkeypatch.setenv("JIRA_SITE", bad)
        assert run("get", "--issue", "PROJ-1", "--comment-id", 7) == 2
    assert env.fake.calls == []
    monkeypatch.setenv("JIRA_SITE", "https://acme.atlassian.net/")
    env.fake.comments["7"] = jc.md_to_adf("* a\n")
    assert run("get", "--issue", "PROJ-1", "--comment-id", 7) == 0
    assert env.fake.calls[0][1].startswith("https://acme.atlassian.net/rest/")


def test_inline_card_only_for_site_host(env, monkeypatch):
    other = jc.md_to_adf("* https://other.atlassian.net/wiki/spaces/A/pages/1\n")
    node = other["content"][0]["content"][0]["content"][0]["content"][0]
    assert node["type"] == "text" and node["marks"][0]["type"] == "link"
    monkeypatch.setenv("JIRA_SITE", "https://other.atlassian.net")
    again = jc.md_to_adf("* https://other.atlassian.net/wiki/spaces/A/pages/1\n")
    assert again["content"][0]["content"][0]["content"][0]["content"][0]["type"] == "inlineCard"


def test_post_status0_drops_stamp_and_warns(env, capsys):
    run("preview", "--issue", "PROJ-1", "--body-file", env.body)
    env.fake.override["POST"] = (0, {"_raw": "연결 실패: TimeoutError"})
    assert run("post", "--issue", "PROJ-1", "--body-file", env.body) == 5
    assert "게시 여부 불명" in capsys.readouterr().err
    assert stamp_files(env) == []
    env.fake.override.clear()
    assert run("post", "--issue", "PROJ-1", "--body-file", env.body) == 3
    assert env.fake.methods() == ["POST"]


def test_post_201_without_id_drops_stamp(env, capsys):
    run("preview", "--issue", "PROJ-1", "--body-file", env.body)
    env.fake.override["POST"] = (201, {})
    assert run("post", "--issue", "PROJ-1", "--body-file", env.body) == 5
    assert "게시 여부 불명" in capsys.readouterr().err and stamp_files(env) == []


def test_http_error_keeps_stamp(env):
    run("preview", "--issue", "PROJ-1", "--body-file", env.body)
    env.fake.override["POST"] = (400, {"errorMessages": ["bad"]})
    assert run("post", "--issue", "PROJ-1", "--body-file", env.body) == 5
    assert len(stamp_files(env)) == 1


def test_malformed_responses_rc5(env, capsys):
    for reply in [(200, {"_raw": "<html>"}), (200, []), (200, {"id": "7"}), (200, {"body": "text"})]:
        env.fake.override["GET"] = reply
        assert run("get", "--issue", "PROJ-1", "--comment-id", 7) == 5


def test_unexpected_exception_prints_type_only(env, capsys):
    def boom(*a, **k):
        raise ValueError(f"secret {TOKEN}")
    env.fake.override = {}
    jc.http = boom
    assert run("get", "--issue", "PROJ-1", "--comment-id", 7) == 5
    err = capsys.readouterr().err
    assert "ValueError" in err and TOKEN not in err and "Traceback" not in err


def test_real_http_read_failures_become_status0(env, monkeypatch):
    import http.client
    monkeypatch.setattr(jc, "http", REAL_HTTP)
    monkeypatch.setattr(jc, "_open", lambda req: _Resp(exc=http.client.IncompleteRead(b"x")))
    assert REAL_HTTP("GET", "https://a.atlassian.net/x")[0] == 0
    monkeypatch.setattr(jc, "_open", lambda req: _Resp(payload=b"x" * (5 * 1024 * 1024 + 10)))
    status, data = REAL_HTTP("GET", "https://a.atlassian.net/x")
    assert status == 0 and "5MB" in data["_raw"]
    monkeypatch.setattr(jc, "_open", lambda req: _Resp(payload=b'{"a": 1}'))
    assert REAL_HTTP("GET", "https://a.atlassian.net/x") == (200, {"a": 1})
    monkeypatch.setattr(jc, "_open", lambda req: pytest.fail("x") if False else (_ for _ in ()).throw(TimeoutError()))
    assert REAL_HTTP("GET", "https://a.atlassian.net/x")[0] == 0


def test_non_utf8_body_file_rc2(env):
    env.body.write_bytes(b"* \xff\xfe bad\n")
    assert run("preview", "--issue", "PROJ-1", "--body-file", env.body) == 2
    assert run("post", "--issue", "PROJ-1", "--body-file", env.body) == 2
    assert env.fake.calls == []


def test_media_without_id_does_not_crash(env, capsys):
    adf = media_adf("앞 문장")
    media = adf["content"][0]["content"][0]["content"][1]["content"][0]
    media["attrs"] = {"type": "external", "url": "https://img.example/x.png"}
    assert jc.fingerprint(adf)[2] == ["https://img.example/x.png"]
    media["attrs"] = {"type": "file"}
    assert len(jc.fingerprint(adf)[2]) == 1
    env.fake.comments["7"] = adf
    assert run("get", "--issue", "PROJ-1", "--comment-id", 7) == 0
    patches = env.home / "p.json"
    patches.write_text(json.dumps([{"anchor": "앞", "new": "뒤"}]), encoding="utf-8")
    assert run("preview", "--issue", "PROJ-1", "--comment-id", 7, "--patches", patches) == 0
    assert run("update", "--issue", "PROJ-1", "--comment-id", 7, "--patches", patches) == 0


def test_corrupt_and_future_stamps_rc3(env):
    run("preview", "--issue", "PROJ-1", "--body-file", env.body)
    f = stamp_files(env)[0]
    for content in ["garbage", "[]", "null", json.dumps({"time": "not-a-date"}),
                    json.dumps({"time": (datetime.now() + timedelta(days=1)).isoformat()})]:
        f.write_text(content)
        assert run("post", "--issue", "PROJ-1", "--body-file", env.body) == 3
    assert env.fake.calls == []


def test_empty_code_block_rc2(env):
    for md in ["* a\n  ```\n  ```\n", "```\n```\n", "```\n\n   \n```\n"]:
        env.body.write_text(md, encoding="utf-8")
        assert run("preview", "--issue", "PROJ-1", "--body-file", env.body) == 2
    assert stamp_files(env) == []


def test_stamp_dir_failures_rc2(env, monkeypatch, capsys):
    d = env.home / ".claude/_audit"
    d.mkdir(parents=True)
    (d / "jira-preview").write_text("i am a file")
    assert run("preview", "--issue", "PROJ-1", "--body-file", env.body) == 2
    (d / "jira-preview").unlink()

    def deny(*a, **k):
        raise PermissionError("no")
    monkeypatch.setattr(jc.os, "chmod", deny)
    assert run("preview", "--issue", "PROJ-1", "--body-file", env.body) == 2
    assert "스탬프 디렉터리" in capsys.readouterr().err


def test_verify_detects_structure_only_changes_rc4(env, capsys):
    env.body.write_text("* 가\n* 나\n", encoding="utf-8")

    def attempt(tamper):
        run("preview", "--issue", "PROJ-1", "--body-file", env.body)
        env.fake.tamper = tamper
        rc = run("post", "--issue", "PROJ-1", "--body-file", env.body)
        return rc, capsys.readouterr().err

    def to_ordered(b):
        b = copy.deepcopy(b)
        b["content"][0]["type"] = "orderedList"
        return b

    rc, err = attempt(to_ordered)
    assert rc == 4 and "doc.content[0].type" in err

    def drop_mark(b):
        b = copy.deepcopy(b)
        b["content"][0]["content"][0]["content"][0]["content"][0]["marks"] = []
        return b
    env.body.write_text("* **굵게**\n", encoding="utf-8")
    rc, err = attempt(drop_mark)
    assert rc == 4 and "marks" in err

    def link_to_other(b):
        b = copy.deepcopy(b)
        b["content"][0]["content"][0]["content"][0]["content"][0]["marks"][0]["attrs"]["href"] = "https://evil.example"
        return b
    env.body.write_text("* [글](https://good.example)\n", encoding="utf-8")
    rc, err = attempt(link_to_other)
    assert rc == 4 and "href" in err

    def card_to_link(b):
        b = copy.deepcopy(b)
        node = b["content"][0]["content"][0]["content"][0]["content"][0]
        b["content"][0]["content"][0]["content"][0]["content"][0] = {"type": "text", "text": node["attrs"]["url"]}
        return b
    env.body.write_text("* https://your-company-prod.atlassian.net/wiki/spaces/A/pages/1\n", encoding="utf-8")
    rc, err = attempt(card_to_link)
    assert rc == 4

    def code_changed(b):
        b = copy.deepcopy(b)
        b["content"][0]["content"][0]["content"][1]["content"][0]["text"] = "b = 2"
        return b
    env.body.write_text("* 가\n  ```\n  a = 1\n  ```\n", encoding="utf-8")
    rc, err = attempt(code_changed)
    assert rc == 4


def test_verify_ignores_server_added_attrs_and_merged_text(env):
    env.body.write_text("* 가 **굵게** 나\n", encoding="utf-8")

    def server_style(b):
        b = copy.deepcopy(b)

        def walk(n):
            n.setdefault("attrs", {})["localId"] = "abc123"
            for c in n.get("content", []):
                walk(c)
        walk(b)
        return b
    run("preview", "--issue", "PROJ-1", "--body-file", env.body)
    env.fake.tamper = server_style
    assert run("post", "--issue", "PROJ-1", "--body-file", env.body) == 0
    a = {"content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}
    b = {"content": [{"type": "text", "text": "ab"}]}
    assert jc.diff(a, b, "doc") is None


def test_update_stamp_bound_to_comment_id(env):
    env.fake.comments["7"] = jc.md_to_adf("* 옛 7\n")
    env.fake.comments["8"] = jc.md_to_adf("* 옛 8\n")
    run("preview", "--issue", "PROJ-1", "--comment-id", 7, "--body-file", env.body)
    assert run("update", "--issue", "PROJ-1", "--comment-id", 8, "--body-file", env.body) == 3
    assert "PUT" not in env.fake.methods()


def test_update_rejects_when_comment_changed_after_preview(env, capsys):
    env.fake.comments["7"] = jc.md_to_adf("* 옛\n")
    run("preview", "--issue", "PROJ-1", "--comment-id", 7, "--body-file", env.body)
    capsys.readouterr()
    env.fake.comments["7"] = jc.md_to_adf("* 누군가 고침\n")
    assert run("update", "--issue", "PROJ-1", "--comment-id", 7, "--body-file", env.body) == 3
    assert "preview 이후 댓글이 바뀜" in capsys.readouterr().err
    assert "PUT" not in env.fake.methods()


def test_preview_body_file_checks_current_comment(env, capsys):
    env.fake.comments["7"] = media_adf()
    assert run("preview", "--issue", "PROJ-1", "--comment-id", 7, "--body-file", env.body) == 2
    assert "--patches" in capsys.readouterr().err and stamp_files(env) == []
    cur = jc.md_to_adf("* 멘션 포함\n")
    cur["content"][0]["content"][0]["content"][0]["content"].append({"type": "mention", "attrs": {"id": "u1"}})
    cur["content"][0]["content"][0]["content"][0]["content"][0]["marks"] = [{"type": "em"}]
    env.fake.comments["8"] = cur
    assert run("preview", "--issue", "PROJ-1", "--comment-id", 8, "--body-file", env.body) == 0
    out = capsys.readouterr().out
    assert "mention" in out and "mark:em" in out and "사라집니다" in out


def test_patch_preview_escapes_control_chars(env, capsys):
    env.fake.comments["7"] = jc.md_to_adf("* 앞 \x1b[31m빨강 뒤\n")
    patches = env.home / "p.json"
    patches.write_text(json.dumps([{"anchor": "빨강", "new": "초록\x07\n끝"}]), encoding="utf-8")
    assert run("preview", "--issue", "PROJ-1", "--comment-id", 7, "--patches", patches) == 0
    out = capsys.readouterr().out
    assert "\x1b" not in out and "\x07" not in out
    assert "\\x1b" in out and "\\x07\\n끝" in out


def test_private_write_refuses_symlink_and_backup_names_unique(env):
    target = env.home / "victim.txt"
    target.write_text("keep")
    link = env.home / "link.json"
    link.symlink_to(target)
    with pytest.raises(jc.Fail) as e:
        jc.write_private(str(link), "x")
    assert e.value.rc == 2 and target.read_text() == "keep"
    env.fake.comments["7"] = jc.md_to_adf("* 옛\n")
    for text in ("* 하나\n", "* 둘\n"):
        env.body.write_text(text, encoding="utf-8")
        run("preview", "--issue", "PROJ-1", "--comment-id", 7, "--body-file", env.body)
        assert run("update", "--issue", "PROJ-1", "--comment-id", 7, "--body-file", env.body) == 0
    backups = list((env.home / ".claude/_audit/jira-preview").glob("backup-*"))
    assert len(backups) == 2 and all(re.search(r"-\d{8}-\d{6}-\d{6}\.adf\.json$", b.name) for b in backups)


def test_prune_old_stamps_and_backups_on_preview(env):
    d = env.home / ".claude/_audit/jira-preview"
    d.mkdir(parents=True)
    now = datetime.now().timestamp()
    files = {"old-stamp.json": 8, "fresh-stamp.json": 3, "backup-A-1-x.adf.json": 31, "backup-A-1-y.adf.json": 10}
    for name, age in files.items():
        (d / name).write_text("{}")
        os.utime(d / name, (now - age * 86400, now - age * 86400))
    run("preview", "--issue", "PROJ-1", "--body-file", env.body)
    left = {p.name for p in d.iterdir()}
    assert "old-stamp.json" not in left and "backup-A-1-x.adf.json" not in left
    assert {"fresh-stamp.json", "backup-A-1-y.adf.json"} <= left


def test_rules_section_boundaries(env, capsys):
    env.skill.write_text("## Jira 댓글 자동 기록\n\n", encoding="utf-8")
    assert run("preview", "--issue", "PROJ-1", "--body-file", env.body) == 2
    env.skill.write_text("## Jira 댓글 자동 기록\n규칙 본문\n## 전혀 다른 절\n무관한 내용\n", encoding="utf-8")
    assert run("preview", "--issue", "PROJ-1", "--body-file", env.body) == 0
    out = capsys.readouterr().out
    assert "규칙 본문" in out and "무관한 내용" not in out
    env.skill.write_text("## Jira 댓글 자동 기록\n끝까지 가는 본문\n", encoding="utf-8")
    run("preview", "--issue", "PROJ-1", "--body-file", env.body)
    assert "끝까지 가는 본문" in capsys.readouterr().out


def test_loose_token_file_warns_once(env, capsys):
    tok = env.home / ".atlassian_token"
    os.chmod(tok, 0o644)
    jc.read_credentials()
    jc.read_credentials()
    err = capsys.readouterr().err
    assert err.count("권한이 느슨합니다") == 1 and TOKEN not in err
    jc._cred_warned = False
    os.chmod(tok, 0o600)
    jc.read_credentials()
    assert capsys.readouterr().err == ""



def test_stamp_bound_to_site_and_preview_shows_destination(env, monkeypatch, capsys):
    run("preview", "--issue", "PROJ-1", "--body-file", env.body)
    assert "your-company-prod.atlassian.net" in capsys.readouterr().out
    monkeypatch.setenv("JIRA_SITE", "https://other.atlassian.net")
    assert run("post", "--issue", "PROJ-1", "--body-file", env.body) == 3
    assert env.fake.calls == []


def test_concurrent_post_only_one_publishes(env, monkeypatch):
    run("preview", "--issue", "PROJ-1", "--body-file", env.body)
    seen = []

    def racing(method, url, body=None):
        if method == "POST" and not seen:
            seen.append(1)
            monkeypatch.setattr(jc, "check_stamp", lambda *a, **k: None)
            seen.append(run("post", "--issue", "PROJ-1", "--body-file", env.body))
        return env.fake(method, url, body)

    monkeypatch.setattr(jc, "http", racing)
    assert run("post", "--issue", "PROJ-1", "--body-file", env.body) == 0
    assert seen[1] == 3 and env.fake.methods().count("POST") == 1


def test_post_5xx_consumes_stamp_and_warns(env, capsys):
    run("preview", "--issue", "PROJ-1", "--body-file", env.body)
    env.fake.override["POST"] = (502, {"_raw": "bad gateway"})
    assert run("post", "--issue", "PROJ-1", "--body-file", env.body) == 5
    assert "반영 여부 확인 필요" in capsys.readouterr().err and stamp_files(env) == []
    env.fake.override.clear()
    assert run("post", "--issue", "PROJ-1", "--body-file", env.body) == 3
    assert env.fake.methods() == ["POST"]


def test_post_4xx_restores_stamp_for_retry(env):
    run("preview", "--issue", "PROJ-1", "--body-file", env.body)
    env.fake.override["POST"] = (400, {"errorMessages": ["bad"]})
    assert run("post", "--issue", "PROJ-1", "--body-file", env.body) == 5
    assert len(stamp_files(env)) == 1
    env.fake.override.clear()
    assert run("post", "--issue", "PROJ-1", "--body-file", env.body) == 0


@pytest.mark.parametrize("code", [408, 429])
def test_post_408_429_consumes_stamp_as_unknown_outcome(env, capsys, code):
    run("preview", "--issue", "PROJ-1", "--body-file", env.body)
    env.fake.override["POST"] = (code, {"_raw": "slow"})
    assert run("post", "--issue", "PROJ-1", "--body-file", env.body) == 5
    assert "반영 여부 확인 필요" in capsys.readouterr().err and stamp_files(env) == []
    env.fake.override.clear()
    assert run("post", "--issue", "PROJ-1", "--body-file", env.body) == 3


def test_prune_old_removes_stale_claimed_leftovers(env):
    d = env.home / ".claude/_audit/jira-preview"
    d.mkdir(parents=True)
    now = datetime.now().timestamp()
    for name, age in {"stale.json.claimed": 8, "fresh.json.claimed": 1}.items():
        (d / name).write_text("{}")
        os.utime(d / name, (now - age * 86400, now - age * 86400))
    run("preview", "--issue", "PROJ-1", "--body-file", env.body)
    left = {p.name for p in d.iterdir()}
    assert "stale.json.claimed" not in left and "fresh.json.claimed" in left


def test_missing_credentials_restores_stamp(env):
    run("preview", "--issue", "PROJ-1", "--body-file", env.body)
    (env.home / ".atlassian_token").unlink()
    jc.http = REAL_HTTP
    assert run("post", "--issue", "PROJ-1", "--body-file", env.body) == 5
    assert len(stamp_files(env)) == 1



SECRET_LOC = "https://api.media.atlassian.com/file/{u}/binary?token=SUPERSECRETSIG&client=abc"


def png_bytes(w=4, h=3, pad=b"pixels"):
    return jc.PNG_MAGIC + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", w, h) + b"\x08\x02\x00\x00\x00" + pad


def uuid_for(att):
    return f"{int(att):08x}-0000-4000-8000-000000000000"


def fig_adf(old_media=None):
    def txt(s):
        return {"type": "text", "text": s}

    def para(*nodes):
        return {"type": "paragraph", "content": list(nodes)}

    def item(*blocks):
        return {"type": "listItem", "content": list(blocks)}

    second = item(para(txt("[그림 2] 둘째 "), {"type": "inlineCard", "attrs": {"url": "https://x.example/c"}}),
                  {"type": "bulletList", "content": [item(para(txt("하위 글머리")))]})
    doc = {"type": "doc", "version": 1, "content": [
        {"type": "bulletList", "content": [item(para(txt("[그림 1] 첫째 설명"))), second]}, para(txt("끝 문단"))]}
    if old_media:
        doc["content"].append({"type": "mediaSingle", "attrs": {"layout": "center"}, "content": [
            {"type": "media", "attrs": {"type": "file", "id": old_media, "collection": ""}}]})
    return doc


class FigFake(Fake):

    def __init__(self):
        super().__init__()
        self.attachments = []

    def __call__(self, method, url, body=None):
        if method == "GET" and "fields=attachment" in url:
            self.calls.append((method, url, body))
            return 200, {"fields": {"attachment": self.attachments}}
        return super().__call__(method, url, body)


class RawFake:

    def __init__(self):
        self.calls, self.next_att, self.upload_reply, self.on_call = [], 500, None, None
        self.location = SECRET_LOC.format

    def __call__(self, method, url, data=None, headers=None, timeout=30):
        self.calls.append(SimpleNamespace(method=method, url=url, data=data, headers=headers or {}, timeout=timeout))
        if self.on_call:
            self.on_call(self.calls[-1])
        if method == "POST":
            if self.upload_reply:
                return self.upload_reply
            att, self.next_att = self.next_att, self.next_att + 1
            return 200, {}, [{"id": str(att)}]
        att = re.search(r"/content/(\d+)$", url).group(1)
        return 303, {"location": self.location(u=uuid_for(att))}, {}


@pytest.fixture
def fig(env, monkeypatch):
    fake, raw = FigFake(), RawFake()
    monkeypatch.setattr(jc, "http", fake)
    monkeypatch.setattr(jc, "http_raw", raw)
    d = env.home / ".scratch" / "figs"
    d.mkdir(parents=True)
    (d / "a.png").write_bytes(png_bytes(4, 3, b"AAAA-unique-bytes"))
    (d / "b.png").write_bytes(png_bytes(8, 6, b"BBBB"))
    lst = d / "figs.json"
    lst.write_text(json.dumps([{"anchor": "[그림 1]", "file": "a.png"}, {"anchor": "[그림 2]", "file": "b.png"}]))
    fake.comments["7"] = fig_adf()
    return SimpleNamespace(env=env, fake=fake, raw=raw, dir=d, lst=lst)


def fpreview(fig):
    return run("preview", "--issue", "PROJ-1", "--comment-id", 7, "--figures", fig.lst)


def fupdate(fig):
    return run("update", "--issue", "PROJ-1", "--comment-id", 7, "--figures", fig.lst)


def upload_name(fig, name):
    return f"{name[:-4]}-{hashlib.sha256((fig.dir / name).read_bytes()).hexdigest()[:12]}.png"


def backups_of(fig):
    return list((fig.env.home / ".claude/_audit/jira-preview").glob("backup-PROJ-1-7-*.adf.json"))


def test_figures_preview_is_read_only_and_writes_stamp(fig, capsys):
    assert fpreview(fig) == 0
    out = capsys.readouterr().out
    assert set(fig.fake.methods()) == {"GET"} and fig.raw.calls == []
    assert len(stamp_files(fig.env)) == 1
    sha = hashlib.sha256((fig.dir / "a.png").read_bytes()).hexdigest()[:12]
    assert "a.png" in out and "b.png" in out and "새로 올림" in out and sha in out and "4×3" in out
    assert "[그림 1] 첫째 설명" in out and "--figures 로만" in out
    assert "글자 블록 4개·인라인 카드 1개" in out and "그림 0개 → 2개" in out


def test_figures_preview_marks_reuse_with_newest_id(fig, capsys):
    size, ua, ub = len((fig.dir / "a.png").read_bytes()), upload_name(fig, "a.png"), upload_name(fig, "b.png")
    fig.fake.attachments = [{"id": "900", "filename": ua, "size": size}, {"id": "901", "filename": ua, "size": size},
                            {"id": "902", "filename": ub, "size": 1}, "junk", {"id": "x"}]
    assert fpreview(fig) == 0
    out = capsys.readouterr().out
    assert "기존 첨부 901 재사용" in out and "기존 첨부 900" not in out
    assert out.count("새로 올림") == 1
    assert f"올라갈 이름 {ua}" in out and f"올라갈 이름 {ub}" in out
    assert re.fullmatch(r"a-[0-9a-f]{12}\.png", ua)


def test_figures_same_name_and_size_but_other_hash_is_not_reused(fig, capsys):
    size = len((fig.dir / "a.png").read_bytes())
    fig.fake.attachments = [{"id": "950", "filename": "a.png", "size": size},
                            {"id": "951", "filename": "a-000000000000.png", "size": size}]
    assert fpreview(fig) == 0
    assert "재사용" not in capsys.readouterr().out.split("== 그림 계획 ==")[1]
    assert fupdate(fig) == 0
    posts = [c for c in fig.raw.calls if c.method == "POST"]
    assert len(posts) == 2 and f'filename="{upload_name(fig, "a.png")}"'.encode() in posts[0].data
    media = fig.fake.comments["7"]["content"][0]["content"][0]["content"][1]["content"][0]["attrs"]
    assert media["alt"] == "a.png" and media["id"] == uuid_for(500)

def test_figures_argument_rules(fig, env):
    assert run("preview", "--issue", "PROJ-1", "--figures", fig.lst) == 2
    assert run("preview", "--issue", "PROJ-1", "--comment-id", 7, "--figures", fig.lst, "--body-file", env.body) == 2
    assert run("preview", "--issue", "PROJ-1", "--comment-id", 7) == 2
    bad = fig.dir / "bad.json"
    for content in ["[]", "{}", "not json", json.dumps([{"anchor": "", "file": "a.png"}]),
                    json.dumps([{"anchor": "x"}]),
                    json.dumps([{"anchor": f"[그림 {i}]", "file": "a.png"} for i in range(21)])]:
        bad.write_text(content)
        assert run("preview", "--issue", "PROJ-1", "--comment-id", 7, "--figures", bad) == 2
    assert stamp_files(fig.env) == [] and fig.raw.calls == []


def test_figures_anchor_zero_multiple_or_same_paragraph_rc2(fig, capsys):
    for items in ([{"anchor": "없는 글귀", "file": "a.png"}],
                  [{"anchor": "[그림", "file": "a.png"}],
                  [{"anchor": "[그림 1]", "file": "a.png"}, {"anchor": "[그림 1] 첫째", "file": "b.png"}]):
        fig.lst.write_text(json.dumps(items))
        assert fpreview(fig) == 2 and fupdate(fig) == 2
    assert "같은 문단" in capsys.readouterr().err
    assert stamp_files(fig.env) == [] and fig.raw.calls == [] and "PUT" not in fig.fake.methods()


def test_figures_existing_figure_after_anchor_rc2(fig, capsys):
    adf = fig_adf()
    item = adf["content"][0]["content"][0]
    item["content"].append({"type": "mediaSingle", "content": [{"type": "media", "attrs": {"id": "old"}}]})
    fig.fake.comments["7"] = adf
    assert fpreview(fig) == 2
    assert "이미 그림이 있습니다" in capsys.readouterr().err and stamp_files(fig.env) == []


@pytest.mark.parametrize("case", ["not_png", "too_big", "space name.png", "한글.png", "a.jpg", "link.png", "zero.png",
                                  "missing.png", "dir.png", "short.png", "dup"])
def test_figures_bad_file_rc2(fig, monkeypatch, case):
    d = fig.dir
    items = [{"anchor": "[그림 1]", "file": case}]
    if case == "not_png":
        items[0]["file"] = "x.png"
        (d / "x.png").write_bytes(b"GIF89a" + b"0" * 40)
    elif case == "too_big":
        monkeypatch.setattr(jc, "MAX_FIG_BYTES", 20)
        items[0]["file"] = "a.png"
    elif case in ("space name.png", "한글.png", "a.jpg"):
        (d / case).write_bytes(png_bytes())
    elif case == "link.png":
        (d / case).symlink_to(d / "a.png")
    elif case == "zero.png":
        (d / case).write_bytes(png_bytes(0, 3))
    elif case == "dir.png":
        (d / case).mkdir()
    elif case == "short.png":
        (d / case).write_bytes(jc.PNG_MAGIC)
    elif case == "dup":
        (d / "sub").mkdir()
        (d / "sub/a.png").write_bytes(png_bytes())
        items = [{"anchor": "[그림 1]", "file": "a.png"}, {"anchor": "[그림 2]", "file": "sub/a.png"}]
    fig.lst.write_text(json.dumps(items))
    assert fpreview(fig) == 2 and fupdate(fig) == 2
    assert stamp_files(fig.env) == [] and fig.raw.calls == [] and "PUT" not in fig.fake.methods()


def test_figures_files_outside_list_folder_rejected(fig, capsys):
    other = fig.env.home / "elsewhere"
    other.mkdir()
    (other / "c.png").write_bytes(png_bytes())
    (fig.env.home / "up.png").write_bytes(png_bytes())
    (fig.dir / "linkdir").symlink_to(other)
    for f in (str(other / "c.png"), "../up.png", "sub/../../up.png", "linkdir/c.png"):
        fig.lst.write_text(json.dumps([{"anchor": "[그림 1]", "file": f}]))
        assert fpreview(fig) == 2 and fupdate(fig) == 2
        assert "그림 목록 폴더 안" in capsys.readouterr().err
    assert stamp_files(fig.env) == [] and fig.raw.calls == []


def test_figures_preview_shows_real_path_and_allows_subfolder(fig, capsys):
    (fig.dir / "sub").mkdir()
    (fig.dir / "sub/c.png").write_bytes(png_bytes())
    fig.lst.write_text(json.dumps([{"anchor": "[그림 1]", "file": "sub/./c.png"}]))
    assert fpreview(fig) == 0
    assert os.path.realpath(fig.dir / "sub/c.png") in capsys.readouterr().out


def test_figures_anchor_parent_must_be_doc_or_list_item(fig, capsys):
    para = {"type": "paragraph", "content": [{"type": "text", "text": "[표] 칸 안 문단"}]}
    adf = fig_adf()
    adf["content"].append({"type": "table", "content": [{"type": "tableRow", "content": [
        {"type": "tableCell", "content": [para]}]}]})
    fig.fake.comments["7"] = adf
    fig.lst.write_text(json.dumps([{"anchor": "[표]", "file": "a.png"}]))
    assert fpreview(fig) == 2 and fupdate(fig) == 2
    assert "이 자리에는 그림을 넣을 수 없습니다" in capsys.readouterr().err
    assert fig.raw.calls == [] and stamp_files(fig.env) == []
    fig.lst.write_text(json.dumps([{"anchor": "끝 문단", "file": "a.png"}]))
    assert fpreview(fig) == 0


def test_figures_png_dimension_limit(fig, monkeypatch):
    (fig.dir / "wide.png").write_bytes(png_bytes(20001, 1))
    (fig.dir / "tall.png").write_bytes(png_bytes(1, 20001))
    (fig.dir / "max.png").write_bytes(png_bytes(20000, 20000))
    for name in ("wide.png", "tall.png"):
        fig.lst.write_text(json.dumps([{"anchor": "[그림 1]", "file": name}]))
        assert fpreview(fig) == 2
    fig.lst.write_text(json.dumps([{"anchor": "[그림 1]", "file": "max.png"}]))
    assert fpreview(fig) == 0
    monkeypatch.setattr(jc, "MAX_FIG_DIM", 3)
    fig.lst.write_text(json.dumps([{"anchor": "[그림 1]", "file": "a.png"}]))
    assert fpreview(fig) == 2


def test_figures_upload_name_too_long_rc2(fig):
    long = "x" * 90 + ".png"
    (fig.dir / long).write_bytes(png_bytes())
    fig.lst.write_text(json.dumps([{"anchor": "[그림 1]", "file": long}]))
    assert fpreview(fig) == 2


def test_figures_same_size_content_change_after_preview_rc3(fig):
    assert fpreview(fig) == 0
    old = (fig.dir / "a.png").read_bytes()
    (fig.dir / "a.png").write_bytes(old.replace(b"AAAA", b"ZZZZ"))
    assert len((fig.dir / "a.png").read_bytes()) == len(old) and (fig.dir / "a.png").read_bytes() != old
    assert fupdate(fig) == 3
    assert fig.raw.calls == [] and "PUT" not in fig.fake.methods()


def test_figures_comment_changed_during_upload_rc3_sends_nothing(fig, capsys):
    assert fpreview(fig) == 0
    capsys.readouterr()

    def someone_edits(call):
        if call.method == "POST":
            changed = fig_adf()
            changed["content"][1]["content"][0]["text"] = "업로드 중에 남이 고침"
            fig.fake.comments["7"] = changed
    fig.raw.on_call = someone_edits
    assert fupdate(fig) == 3
    assert "업로드하는 동안 댓글이 바뀌었습니다" in capsys.readouterr().err
    assert "PUT" not in fig.fake.methods() and backups_of(fig) == []
    assert len(stamp_files(fig.env)) == 1
    assert fig.fake.comments["7"]["content"][1]["content"][0]["text"] == "업로드 중에 남이 고침"


def _no_backup(files):
    return [f for f in files if not f.name.startswith("backup-")]


@pytest.mark.parametrize("reply,kept", [((400, {"errorMessages": ["bad"]}), 1), ((502, {"_raw": "gw"}), 0),
                                        ((408, {}), 0), ((429, {}), 0), ((0, {"_raw": "연결 실패: TimeoutError"}), 0),
                                        ((200, {}), 0)])
def test_figures_put_failures_restore_or_consume_stamp(fig, capsys, reply, kept):
    assert fpreview(fig) == 0
    capsys.readouterr()
    fig.fake.override["PUT"] = reply
    assert fupdate(fig) == 5
    err = capsys.readouterr().err
    assert len(_no_backup(stamp_files(fig.env))) == kept
    assert fig.fake.methods().count("PUT") == 1
    assert ("게시 여부 불명" in err) == (not kept)


def test_figures_backup_write_failure_restores_stamp_and_sends_no_put(fig, monkeypatch):
    assert fpreview(fig) == 0

    def deny(path, text):
        raise jc.Fail(2, "파일을 쓸 수 없습니다")
    monkeypatch.setattr(jc, "write_private", deny)
    assert fupdate(fig) == 2
    assert "PUT" not in fig.fake.methods()
    assert len(stamp_files(fig.env)) == 1


@pytest.mark.parametrize("mutation", ["text", "card"])
def test_figures_insert_step_changing_text_or_cards_blocks_put(fig, monkeypatch, mutation):
    real = jc.insert_figures

    def bad_insert(cur, plan, uuids):
        new = real(cur, plan, uuids)
        if mutation == "text":
            new["content"][1]["content"][0]["text"] = "삽입 단계가 글자를 바꿨다"
        else:
            new["content"][1]["content"].append({"type": "inlineCard", "attrs": {"url": "https://x.example/extra"}})
        return new
    monkeypatch.setattr(jc, "insert_figures", bad_insert)
    assert fpreview(fig) == 0
    assert fupdate(fig) == 2
    assert "PUT" not in fig.fake.methods() and backups_of(fig) == []
    assert len(stamp_files(fig.env)) == 1


def test_figures_update_without_stamp_rc3(fig):
    assert fupdate(fig) == 3
    assert fig.raw.calls == [] and "PUT" not in fig.fake.methods()


def test_figures_update_rejects_file_changed_after_preview(fig):
    assert fpreview(fig) == 0
    (fig.dir / "a.png").write_bytes(png_bytes(4, 3, b"CHANGED"))
    assert fupdate(fig) == 3
    assert fig.raw.calls == [] and "PUT" not in fig.fake.methods()


def test_figures_update_rejects_comment_changed_after_preview(fig, capsys):
    assert fpreview(fig) == 0
    capsys.readouterr()
    changed = fig_adf()
    changed["content"][1]["content"][0]["text"] = "누군가 고친 문단"
    fig.fake.comments["7"] = changed
    assert fupdate(fig) == 3
    assert "preview 이후 댓글이 바뀜" in capsys.readouterr().err
    assert fig.raw.calls == [] and "PUT" not in fig.fake.methods()


def test_figures_update_uploads_inserts_and_verifies(fig, capsys):
    orig = fig_adf()
    assert fpreview(fig) == 0
    capsys.readouterr()
    assert fupdate(fig) == 0
    cap = capsys.readouterr()
    posts = [c for c in fig.raw.calls if c.method == "POST"]
    assert [c.method for c in fig.raw.calls] == ["POST", "GET", "POST", "GET"]
    p = posts[0]
    assert p.url == "https://your-company-prod.atlassian.net/rest/api/3/issue/PROJ-1/attachments" and p.timeout == 300
    assert p.headers["X-Atlassian-Token"] == "no-check"
    boundary = p.headers["Content-Type"].split("multipart/form-data; boundary=")[1].encode()
    assert (fig.dir / "a.png").read_bytes() in p.data and (fig.dir / "b.png").read_bytes() not in p.data
    assert f'name="file"; filename="{upload_name(fig, "a.png")}"'.encode() in p.data and b"Content-Type: image/png" in p.data
    assert p.data.startswith(b"--" + boundary) and p.data.endswith(b"--" + boundary + b"--\r\n")
    assert fig.raw.calls[1].url.endswith("/rest/api/3/attachment/content/500")
    put = [c for c in fig.fake.calls if c[0] == "PUT"]
    assert len(put) == 1 and put[0][1].endswith("/comment/7?notifyUsers=false")
    backups = backups_of(fig)
    assert len(backups) == 1 and json.loads(backups[0].read_text()) == orig
    assert oct(backups[0].stat().st_mode & 0o777) == "0o600"
    new = fig.fake.comments["7"]
    before, after = jc.fingerprint(orig), jc.fingerprint(new)
    assert after[0] == before[0] and after[1] == before[1] == 1
    assert after[2] == sorted([uuid_for(500), uuid_for(501)])
    items = new["content"][0]["content"]
    assert items[0]["content"][1] == {"type": "mediaSingle", "attrs": {"layout": "center"}, "content": [
        {"type": "media", "attrs": {"type": "file", "id": uuid_for(500), "collection": "", "width": 4, "height": 3, "alt": "a.png"}}]}
    assert [c["type"] for c in items[1]["content"]] == ["paragraph", "mediaSingle", "bulletList"]
    stripped = copy.deepcopy(new)
    for it in stripped["content"][0]["content"]:
        it["content"] = [c for c in it["content"] if c["type"] != "mediaSingle"]
    assert stripped == orig
    assert f"그림 1: 첨부 500 · 미디어 {uuid_for(500)}" in cap.out and "focusedCommentId=7" in cap.out
    assert [f for f in stamp_files(fig.env) if not f.name.startswith("backup-")] == []
    assert fupdate(fig) == 2


def test_figures_reuse_skips_upload(fig, capsys):
    for name, aid in (("a.png", "900"), ("b.png", "901")):
        fig.fake.attachments.append({"id": aid, "filename": upload_name(fig, name), "size": len((fig.dir / name).read_bytes())})
    assert fpreview(fig) == 0
    assert capsys.readouterr().out.count("재사용") == 2
    assert fupdate(fig) == 0
    assert [c.method for c in fig.raw.calls] == ["GET", "GET"]
    assert jc.fingerprint(fig.fake.comments["7"])[2] == sorted([uuid_for(900), uuid_for(901)])


def test_figures_uuid_failure_sends_nothing_and_restores_stamp(fig, capsys):
    fig.raw.location = lambda **kw: "https://elsewhere.example/nofile?sig=LEAKME"
    assert fpreview(fig) == 0
    capsys.readouterr()
    assert fupdate(fig) == 5
    cap = capsys.readouterr()
    assert "미디어 UUID 를 얻지 못했습니다(HTTP 303)" in cap.err and "LEAKME" not in cap.out + cap.err
    assert "PUT" not in fig.fake.methods() and fig.fake.comments["7"] == fig_adf() and backups_of(fig) == []
    assert len(stamp_files(fig.env)) == 1
    fig.raw.location = SECRET_LOC.format
    assert fupdate(fig) == 0


def test_figures_uuid_lookup_non_redirect_status_rc5(fig, monkeypatch):
    assert fpreview(fig) == 0
    monkeypatch.setattr(jc, "http_raw", lambda m, u, *a, **k: (200, {"location": SECRET_LOC.format(u=uuid_for(1))}, {})
                        if m == "GET" else (200, {}, [{"id": "500"}]))
    assert fupdate(fig) == 5
    assert "PUT" not in fig.fake.methods() and len(stamp_files(fig.env)) == 1


@pytest.mark.parametrize("reply", [(0, {}, {"_raw": "연결 실패: TimeoutError"}), (502, {}, {"_raw": "gw"}),
                                   (408, {}, {}), (429, {}, {}), (201, {}, {}), (200, {}, [{"nope": 1}])])
def test_figures_upload_unknown_outcome_consumes_stamp(fig, capsys, reply):
    assert fpreview(fig) == 0
    capsys.readouterr()
    fig.raw.upload_reply = reply
    assert fupdate(fig) == 5
    assert "첨부 반영 여부 불명" in capsys.readouterr().err
    assert stamp_files(fig.env) == [] and "PUT" not in fig.fake.methods()
    assert fupdate(fig) == 3


def test_figures_upload_4xx_restores_stamp(fig):
    assert fpreview(fig) == 0
    fig.raw.upload_reply = (400, {}, {"errorMessages": ["bad"]})
    assert fupdate(fig) == 5
    assert len(stamp_files(fig.env)) == 1 and "PUT" not in fig.fake.methods()
    fig.raw.upload_reply = None
    assert fupdate(fig) == 0


def test_figures_exception_before_response_restores_stamp(fig, monkeypatch):
    assert fpreview(fig) == 0

    def no_cred(*a, **k):
        raise jc.Fail(5, "자격증명 파일을 읽을 수 없습니다")
    monkeypatch.setattr(jc, "http_raw", no_cred)
    assert fupdate(fig) == 5
    assert len(stamp_files(fig.env)) == 1 and "PUT" not in fig.fake.methods()


def test_figures_precheck_blocks_duplicate_or_colliding_uuid(fig):
    assert fpreview(fig) == 0
    fig.raw.location = lambda **kw: SECRET_LOC.format(u="11111111-0000-4000-8000-000000000000")
    assert fupdate(fig) == 2
    assert "PUT" not in fig.fake.methods() and len(stamp_files(fig.env)) == 1 and backups_of(fig) == []
    fig.raw.location, fig.raw.next_att = SECRET_LOC.format, 500
    fig.fake.comments["7"] = fig_adf(old_media=uuid_for(500))
    assert fpreview(fig) == 0
    assert fupdate(fig) == 2
    assert "PUT" not in fig.fake.methods()


def test_figures_check_result_rejects_text_or_card_change():
    cur = fig_adf()
    changed = copy.deepcopy(cur)
    changed["content"][1]["content"][0]["text"] = "바뀜"
    with pytest.raises(jc.Fail) as e:
        jc.check_figure_result(cur, changed, [])
    assert e.value.rc == 2
    nocard = copy.deepcopy(cur)
    nocard["content"][0]["content"][1]["content"][0]["content"].pop()
    with pytest.raises(jc.Fail):
        jc.check_figure_result(cur, nocard, [])
    with pytest.raises(jc.Fail):
        jc.check_figure_result(cur, cur, [uuid_for(1)])


def test_figures_location_never_printed_or_stored(fig, capsys):
    assert fpreview(fig) == 0
    assert fupdate(fig) == 0
    cap = capsys.readouterr()
    blob = cap.out + cap.err
    for f in (fig.env.home / ".claude").rglob("*"):
        if f.is_file():
            blob += f.read_text()
    assert "SUPERSECRETSIG" not in blob and "api.media.atlassian.com" not in blob and "token=" not in blob


def test_figures_verify_mismatch_rc4(fig, capsys):
    assert fpreview(fig) == 0
    capsys.readouterr()
    fig.fake.tamper = lambda b: jc.md_to_adf("* 다른 본문\n") if "PUT" in fig.fake.methods() else b
    assert fupdate(fig) == 4
    assert "게시는 완료" in capsys.readouterr().err


class _RawResp:

    def __init__(self, status=200, headers=None, payload=b"{}", exc=None):
        self.status, self.headers, self.payload, self.exc = status, headers or {}, payload, exc

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        if self.exc:
            raise self.exc
        return self.payload[:n] if n >= 0 else self.payload


def test_http_raw_reads_redirect_headers_and_passes_request_through_open(env, monkeypatch):
    seen = []

    def fake_open(req, timeout=30):
        seen.append((req, timeout))
        raise urllib.error.HTTPError(req.full_url, 303, "See Other", {"Location": "https://m.example/file/x?t=SIG"}, io.BytesIO(b""))
    monkeypatch.setattr(jc, "_open", fake_open)
    status, hdrs, body = jc.http_raw("GET", "https://a.atlassian.net/x")
    assert status == 303 and hdrs["location"].endswith("t=SIG") and body == {}
    assert seen[0][0].get_header("Authorization").startswith("Basic ") and seen[0][1] == 30


def test_http_raw_upload_request_shape_and_failures(env, monkeypatch):
    seen = []

    def ok_open(req, timeout=30):
        seen.append((req, timeout))
        return _RawResp(200, {"Content-Type": "application/json"}, b'[{"id": "5"}]')
    monkeypatch.setattr(jc, "_open", ok_open)
    status, hdrs, body = jc.http_raw("POST", "https://a.atlassian.net/u", b"BYTES", dict(jc.XSRF_OPT_OUT), 300)
    req, timeout = seen[0]
    assert (status, body, hdrs["content-type"]) == (200, [{"id": "5"}], "application/json")
    assert req.data == b"BYTES" and req.get_method() == "POST" and timeout == 300
    assert req.get_header("X-atlassian-token") == "no-check" and req.get_header("Accept") == "application/json"
    monkeypatch.setattr(jc, "_open", lambda req, timeout=30: (_ for _ in ()).throw(TimeoutError()))
    assert jc.http_raw("GET", "https://a.atlassian.net/x") == (0, {}, {"_raw": "연결 실패: TimeoutError"})
    monkeypatch.setattr(jc, "_open", lambda req, timeout=30: _RawResp(payload=b"x" * (5 * 1024 * 1024 + 10)))
    status, _, body = jc.http_raw("GET", "https://a.atlassian.net/x")
    assert status == 0 and "5MB" in body["_raw"]
    monkeypatch.setattr(jc, "_open", lambda req, timeout=30: _RawResp(400, payload=f"echo {TOKEN}".encode()))
    status, _, body = jc.http_raw("GET", "https://a.atlassian.net/x")
    assert status == 400 and TOKEN not in json.dumps(body) and "***" in body["_raw"]


def test_http_raw_does_not_follow_redirect_to_other_host(env, monkeypatch):
    import http.server
    import threading
    hits = {"a": [], "b": []}

    def make(name, redirect_to=None):
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                hits[name].append(self.headers.get("Authorization"))
                self.send_response(303 if redirect_to else 200)
                if redirect_to:
                    self.send_header("Location", redirect_to())
                self.end_headers()

            def log_message(self, *a):
                pass
        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return srv

    b = make("b")
    a = make("a", lambda: f"http://127.0.0.1:{b.server_port}/file/x")
    monkeypatch.setenv("no_proxy", "*")
    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.setattr(jc, "_open", REAL_OPEN)
    try:
        status, hdrs, _ = jc.http_raw("GET", f"http://127.0.0.1:{a.server_port}/start")
    finally:
        a.shutdown()
        b.shutdown()
    assert status == 303 and "/file/x" in hdrs["location"]
    assert len(hits["a"]) == 1 and hits["a"][0].startswith("Basic ") and hits["b"] == []



@pytest.fixture
def att(env, monkeypatch):
    fake, raw = FigFake(), RawFake()
    monkeypatch.setattr(jc, "http", fake)
    monkeypatch.setattr(jc, "http_raw", raw)

    def land(call):
        if call.method == "POST" and not raw.upload_reply and not raw.lose:
            m = re.search(rb'filename="([^"]+)"', call.data)
            content = call.data.split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n--", 1)[0]
            fake.attachments.append({"id": str(raw.next_att), "filename": m.group(1).decode(), "size": len(content)})

    raw.lose, raw.on_call = False, land
    d = env.home / ".scratch" / "files"
    d.mkdir(parents=True)
    (d / "a.csv").write_text("patient_id,name,score\n1,kim,0.5\n", encoding="utf-8")
    (d / "r.json").write_text('{"k": [1, 2]}', encoding="utf-8")
    (d / "p.pdf").write_bytes(b"%PDF-1.4\n%binary")
    lst = d / "list.json"
    lst.write_text(json.dumps([{"file": "a.csv"}, {"file": "r.json"}]))
    return SimpleNamespace(env=env, fake=fake, raw=raw, dir=d, lst=lst)


def apreview(att):
    return run("preview", "--issue", "PROJ-1", "--attach", att.lst)


def aattach(att):
    return run("attach", "--issue", "PROJ-1", "--attach", att.lst)


def aname(att, name):
    stem, ext = name.rsplit(".", 1)
    return f"{stem}-{hashlib.sha256((att.dir / name).read_bytes()).hexdigest()[:12]}.{ext.lower()}"


def test_attach_preview_is_read_only_and_shows_plan(att, capsys):
    assert apreview(att) == 0
    out = capsys.readouterr().out
    assert set(att.fake.methods()) == {"GET"} and att.raw.calls == [] and len(stamp_files(att.env)) == 1
    sha = hashlib.sha256((att.dir / "a.csv").read_bytes()).hexdigest()[:12]
    assert "이슈 PROJ-1 에 파일 2개 첨부" in out and "6. 이슈 파일 첨부는 attach 로만 합니다" in out
    assert str(att.dir / "a.csv") in out and sha in out and "text/csv" in out and "application/json" in out
    assert f"올라갈 이름 {aname(att, 'a.csv')}" in out and out.count("새로 올림") == 2
    assert "첫 줄: patient_id,name,score" in out and "줄 2개 · 첫 줄 열 3개" in out
    assert "형태: 객체 · 키 앞 10개: k" in out
    assert "! 환자 식별 정보로 보이는 열: patient_id, name" in out


def test_attach_preview_first_line_is_escaped_truncated_and_bom_skipped(att, capsys):
    (att.dir / "b.csv").write_bytes(("﻿id\x1b[31m," + "y" * 300 + "\nsecond\n").encode("utf-8"))
    att.lst.write_text(json.dumps([{"file": "b.csv"}]))
    assert apreview(att) == 0
    line = next(x for x in capsys.readouterr().out.splitlines() if "첫 줄:" in x)
    assert line.startswith("    첫 줄: id\\x1b[31m,yyy") and "second" not in line and "﻿" not in line and "\x1b" not in line
    assert line.count("y") == jc.PREVIEW_CHARS - len("id\x1b[31m,")


def test_attach_preview_marks_reuse(att, capsys):
    size = len((att.dir / "a.csv").read_bytes())
    att.fake.attachments = [{"id": "900", "filename": aname(att, "a.csv"), "size": size},
                            {"id": "901", "filename": aname(att, "a.csv"), "size": size},
                            {"id": "902", "filename": aname(att, "r.json"), "size": 1}]
    assert apreview(att) == 0
    out = capsys.readouterr().out
    assert "기존 첨부 901 재사용" in out and out.count("새로 올림") == 1


def test_attach_argument_rules(att, env):
    assert run("preview", "--issue", "PROJ-1", "--comment-id", 7, "--attach", att.lst) == 2
    assert run("preview", "--issue", "PROJ-1", "--attach", att.lst, "--body-file", env.body) == 2
    assert run("preview", "--issue", "PROJ-1") == 2
    bad = att.dir / "bad.json"
    for content in ["[]", "{}", "not json", json.dumps([{"file": ""}]), json.dumps([{"x": 1}]),
                    json.dumps([{"file": "a.csv"} for _ in range(jc.MAX_ATTACH + 1)])]:
        bad.write_text(content)
        assert run("preview", "--issue", "PROJ-1", "--attach", bad) == 2
        assert run("attach", "--issue", "PROJ-1", "--attach", bad) == 2
    assert stamp_files(att.env) == [] and att.raw.calls == []


@pytest.mark.parametrize("case", ["x.exe", "x.zip", "noext", "sp ace.csv", "한글.csv", "fake.pdf", "fake.png", "fake.jpg",
                                  "nul.csv", "latin.txt", "broken.json", "link.csv", "dir.csv", "missing.csv", "too_big",
                                  "dup"])
def test_attach_bad_file_rc2(att, monkeypatch, case):
    d, items = att.dir, [{"file": case}]
    if case in ("x.exe", "x.zip", "noext", "sp ace.csv", "한글.csv"):
        (d / case).write_text("a,b\n")
    elif case == "fake.pdf":
        (d / case).write_bytes(b"<html>not a pdf")
    elif case == "fake.png":
        (d / case).write_bytes(b"GIF89a" + b"0" * 30)
    elif case == "fake.jpg":
        (d / case).write_bytes(jc.PNG_MAGIC + b"0" * 30)
    elif case == "nul.csv":
        (d / case).write_bytes(b"a,b\n1,2\x00\n")
    elif case == "latin.txt":
        (d / case).write_bytes("café".encode("latin-1"))
    elif case == "broken.json":
        (d / case).write_text('{"a": ')
    elif case == "link.csv":
        (d / case).symlink_to(d / "a.csv")
    elif case == "dir.csv":
        (d / case).mkdir()
    elif case == "too_big":
        monkeypatch.setattr(jc, "MAX_ATTACH_BYTES", 10)
        items = [{"file": "a.csv"}]
    elif case == "dup":
        (d / "sub").mkdir()
        (d / "sub/a.csv").write_text("x\n")
        items = [{"file": "a.csv"}, {"file": "sub/a.csv"}]
    att.lst.write_text(json.dumps(items))
    assert apreview(att) == 2 and aattach(att) == 2
    assert stamp_files(att.env) == [] and att.raw.calls == []


def test_attach_accepts_each_allowed_type_and_uppercase_extension(att):
    (att.dir / "t.TSV").write_text("a\tb\n")
    (att.dir / "n.txt").write_text("hello\n")
    (att.dir / "i.png").write_bytes(png_bytes())
    (att.dir / "j.JPEG").write_bytes(b"\xff\xd8\xff\xe0data")
    (att.dir / "k.jpg").write_bytes(b"\xff\xd8\xff\xe1data")
    names = ("a.csv", "t.TSV", "n.txt", "r.json", "p.pdf", "i.png", "j.JPEG", "k.jpg")
    att.lst.write_text(json.dumps([{"file": f} for f in names]))
    assert apreview(att) == 0 and aattach(att) == 0
    posts = [c for c in att.raw.calls if c.method == "POST"]
    types = [re.search(rb"Content-Type: ([^\r]+)", c.data).group(1).decode() for c in posts]
    assert types == ["text/csv", "text/tab-separated-values", "text/plain", "application/json", "application/pdf",
                     "image/png", "image/jpeg", "image/jpeg"]
    assert f'filename="{aname(att, "t.TSV")}"'.encode() in posts[1].data and aname(att, "t.TSV").endswith(".tsv")


def test_attach_files_outside_list_folder_rejected(att, capsys):
    other = att.env.home / "elsewhere"
    other.mkdir()
    (other / "c.csv").write_text("x\n")
    (att.env.home / "up.csv").write_text("x\n")
    (att.dir / "linkdir").symlink_to(other)
    for f in (str(other / "c.csv"), "../up.csv", "sub/../../up.csv", "linkdir/c.csv"):
        att.lst.write_text(json.dumps([{"file": f}]))
        assert apreview(att) == 2 and aattach(att) == 2
        assert "첨부 목록 폴더 안" in capsys.readouterr().err
    assert stamp_files(att.env) == [] and att.raw.calls == []


def test_attach_allows_subfolder_and_shows_real_path(att, capsys):
    (att.dir / "sub").mkdir()
    (att.dir / "sub/c.csv").write_text("h\n")
    att.lst.write_text(json.dumps([{"file": "sub/./c.csv"}]))
    assert apreview(att) == 0
    assert str(att.dir / "sub/c.csv") in capsys.readouterr().out


def test_attach_without_stamp_rc3(att):
    assert aattach(att) == 3
    assert att.raw.calls == [] and "GET" not in att.fake.methods()


def test_attach_rejects_same_size_content_change_after_preview(att):
    assert apreview(att) == 0
    p = att.dir / "a.csv"
    old = p.read_bytes()
    p.write_bytes(old.replace(b"kim", b"lee"))
    assert len(p.read_bytes()) == len(old) and aattach(att) == 3
    assert att.raw.calls == [] and len(stamp_files(att.env)) == 1


def test_attach_stamp_is_bound_to_issue(att):
    assert apreview(att) == 0
    assert run("attach", "--issue", "PROJ-2", "--attach", att.lst) == 3 and att.raw.calls == []


def test_attach_uploads_with_headers_multipart_and_readback(att, capsys):
    assert apreview(att) == 0
    capsys.readouterr()
    assert aattach(att) == 0
    out = capsys.readouterr().out
    posts = [c for c in att.raw.calls if c.method == "POST"]
    assert [c.method for c in att.raw.calls] == ["POST", "POST"] and "PUT" not in att.fake.methods()
    for c, n in zip(posts, ("a.csv", "r.json")):
        assert c.url == "https://your-company-prod.atlassian.net/rest/api/3/issue/PROJ-1/attachments"
        assert c.headers[jc.XSRF_HEADER] == jc.XSRF_VALUE and c.timeout == 300
        assert c.headers["Content-Type"].startswith("multipart/form-data; boundary=")
        assert f'name="file"; filename="{aname(att, n)}"'.encode() in c.data and (att.dir / n).read_bytes() in c.data
    assert b"Content-Type: text/csv" in posts[0].data and b"Content-Type: application/json" in posts[1].data
    assert f"첨부 500 · {aname(att, 'a.csv')} · 새로" in out and f"첨부 501 · {aname(att, 'r.json')} · 새로" in out
    assert out.rstrip().endswith("https://your-company-prod.atlassian.net/browse/PROJ-1")
    assert stamp_files(att.env) == []
    assert att.fake.methods().count("GET") == 3
    assert aattach(att) == 3


def test_attach_reuse_skips_upload(att, capsys):
    size = len((att.dir / "a.csv").read_bytes())
    att.fake.attachments = [{"id": "900", "filename": aname(att, "a.csv"), "size": size}]
    assert apreview(att) == 0
    capsys.readouterr()
    assert aattach(att) == 0
    posts = [c for c in att.raw.calls if c.method == "POST"]
    assert len(posts) == 1 and f'filename="{aname(att, "r.json")}"'.encode() in posts[0].data
    assert f"첨부 900 · {aname(att, 'a.csv')} · 재사용" in capsys.readouterr().out
    att.lst.write_text(json.dumps([{"file": "a.csv"}]))
    n = len(att.raw.calls)
    assert apreview(att) == 0 and aattach(att) == 0 and len(att.raw.calls) == n


@pytest.mark.parametrize("reply", [(0, {}, {"_raw": "연결 실패: TimeoutError"}), (502, {}, {"_raw": "gw"}),
                                   (408, {}, {}), (429, {}, {}), (201, {}, {}), (200, {}, [{"nope": 1}])])
def test_attach_upload_unknown_outcome_consumes_stamp(att, capsys, reply):
    assert apreview(att) == 0
    capsys.readouterr()
    att.raw.upload_reply = reply
    assert aattach(att) == 5
    assert "첨부 반영 여부 불명" in capsys.readouterr().err
    assert stamp_files(att.env) == [] and aattach(att) == 3


def test_attach_upload_4xx_restores_stamp(att):
    assert apreview(att) == 0
    att.raw.upload_reply = (400, {}, {"errorMessages": ["bad"]})
    assert aattach(att) == 5
    assert len(stamp_files(att.env)) == 1
    att.raw.upload_reply = None
    assert aattach(att) == 0


def test_attach_exception_before_response_restores_stamp(att, monkeypatch):
    assert apreview(att) == 0

    def no_cred(*a, **k):
        raise jc.Fail(5, "자격증명 파일을 읽을 수 없습니다")
    monkeypatch.setattr(jc, "http_raw", no_cred)
    assert aattach(att) == 5 and len(stamp_files(att.env)) == 1


def test_attach_readback_missing_rc4(att, capsys):
    assert apreview(att) == 0
    capsys.readouterr()
    att.raw.lose = True
    assert aattach(att) == 4
    err = capsys.readouterr().err
    assert "첨부는 요청했으나 되읽기에서 찾지 못했습니다" in err and aname(att, "a.csv") in err
    assert stamp_files(att.env) == []


def test_attach_readback_size_mismatch_rc4(att):
    assert apreview(att) == 0

    def wrong_size(c):
        if c.method == "POST":
            att.fake.attachments.append({"id": "9", "filename": re.search(rb'filename="([^"]+)"', c.data).group(1).decode(), "size": 1})
    att.raw.on_call = wrong_size
    assert aattach(att) == 4


def test_attach_never_prints_credentials(att, capsys):
    assert apreview(att) == 0 and aattach(att) == 0
    cap = capsys.readouterr()
    assert TOKEN not in cap.out + cap.err and "me@example.com" not in cap.out + cap.err


def shown_lines(capsys):
    return [x.strip() for x in capsys.readouterr().out.split("== 첨부 계획 ==")[1].splitlines() if x.startswith("    ")]


def one_file_list(att, name, content):
    (att.dir / name).write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    att.lst.write_text(json.dumps([{"file": name}]))


def test_list_must_live_under_scratch_for_attach_and_figures(att):
    att.fake.comments["7"] = fig_adf()
    plain = att.env.home / "patients"
    plain.mkdir()
    (plain / "a.csv").write_text("x\n")
    (plain / "a.png").write_bytes(png_bytes())
    (plain / "l.json").write_text(json.dumps([{"file": "a.csv"}]))
    (plain / "f.json").write_text(json.dumps([{"anchor": "[그림 1]", "file": "a.png"}]))
    assert run("preview", "--issue", "PROJ-1", "--attach", plain / "l.json") == 2
    assert run("attach", "--issue", "PROJ-1", "--attach", plain / "l.json") == 2
    assert run("preview", "--issue", "PROJ-1", "--comment-id", 7, "--figures", plain / "f.json") == 2
    assert run("update", "--issue", "PROJ-1", "--comment-id", 7, "--figures", plain / "f.json") == 2
    assert stamp_files(att.env) == [] and att.raw.calls == []
    deep = att.env.home / ".scratch" / "x" / "y"
    deep.mkdir(parents=True)
    (deep / "a.csv").write_text("x\n")
    (deep / "l.json").write_text(json.dumps([{"file": "a.csv"}]))
    assert run("preview", "--issue", "PROJ-1", "--attach", deep / "l.json") == 0


def test_list_outside_scratch_message(att, capsys):
    plain = att.env.home / "patients"
    plain.mkdir()
    (plain / "a.csv").write_text("x\n")
    (plain / "l.json").write_text(json.dumps([{"file": "a.csv"}]))
    assert run("preview", "--issue", "PROJ-1", "--attach", plain / "l.json") == 2
    assert "목록 파일은 .scratch 아래 임시 폴더에 두십시오" in capsys.readouterr().err


def test_attach_preview_skips_leading_blank_lines(att, capsys):
    one_file_list(att, "b.csv", "\n  \r\n\nid,score\n1,2\n")
    assert apreview(att) == 0
    assert shown_lines(capsys)[0] == "첫 줄: id,score"


def test_attach_preview_counts_lines_and_columns(att, capsys):
    one_file_list(att, "c.csv", "a,b,c,d\n1,2,3,4\n5,6,7,8")
    assert apreview(att) == 0
    assert "줄 3개 · 첫 줄 열 4개" in shown_lines(capsys)
    one_file_list(att, "d.tsv", "a\tb\n1\t2\n")
    assert apreview(att) == 0
    assert "줄 2개 · 첫 줄 열 2개" in shown_lines(capsys)
    one_file_list(att, "t.txt", "a,b,c\n")
    assert apreview(att) == 0
    assert shown_lines(capsys) == ["첫 줄: a,b,c"]


def test_attach_preview_only_scans_first_64kib(att, capsys):
    one_file_list(att, "big.csv", "\n" * (jc.PREVIEW_SCAN + 10) + "late,line\n")
    assert apreview(att) == 0
    assert shown_lines(capsys)[0] == "첫 줄:"


def test_attach_preview_json_shape(att, capsys):
    one_file_list(att, "o.json", json.dumps({f"k{i}": i for i in range(15)}))
    assert apreview(att) == 0
    line = shown_lines(capsys)[0]
    assert line.endswith(", ".join(f"k{i}" for i in range(10))) and "k10" not in line
    one_file_list(att, "l.json", json.dumps([1, 2, 3]))
    assert apreview(att) == 0
    assert shown_lines(capsys) == ["형태: 배열 · 길이 3"]
    one_file_list(att, "s.json", "42")
    assert apreview(att) == 0
    assert shown_lines(capsys) == ["형태: int"]


@pytest.mark.parametrize("name,content,hits", [
    ("p.csv", "MRN,Date of Birth,score\n", "MRN, Date of Birth"),
    ("q.csv", "id,Email,값\n", "Email"),
    ("k.csv", "환자번호,성명,x\n", "환자번호, 성명"),
    ("t.tsv", "a\tPhone\n", "Phone"),
    ("n.json", '{"patient_id": 1, "ok": 2}', "patient_id"),
    ("x.txt", "ssn is here\n", "ssn is here")])
def test_attach_preview_warns_on_phi_looking_words(att, capsys, name, content, hits):
    one_file_list(att, name, content)
    assert apreview(att) == 0
    assert f"! 환자 식별 정보로 보이는 열: {hits}" in shown_lines(capsys)
    assert att.raw.calls == []
    assert len(stamp_files(att.env)) == 1
    assert aattach(att) == 0


def test_attach_preview_no_warning_without_phi_words(att, capsys):
    one_file_list(att, "ok.csv", "id,score,value\n1,2,3\n")
    assert apreview(att) == 0
    assert not [x for x in shown_lines(capsys) if x.startswith("!")]


def test_attach_empty_file_rc2(att):
    one_file_list(att, "empty.csv", b"")
    assert apreview(att) == 2 and aattach(att) == 2 and stamp_files(att.env) == []


def test_attach_limits_constants():
    assert jc.MAX_ATTACH_BYTES == 50 * 1024 * 1024 and jc.MAX_ATTACH_TOTAL == 100 * 1024 * 1024 and jc.MAX_ATTACH == 10


def test_attach_per_file_size_boundary(att, monkeypatch):
    monkeypatch.setattr(jc, "MAX_ATTACH_BYTES", 100)
    one_file_list(att, "exact.csv", "a" * 100)
    assert apreview(att) == 0
    one_file_list(att, "over.csv", "a" * 101)
    assert apreview(att) == 2


def test_attach_total_size_limit(att, monkeypatch, capsys):
    monkeypatch.setattr(jc, "MAX_ATTACH_TOTAL", 100)
    (att.dir / "h1.csv").write_text("a" * 50)
    (att.dir / "h2.csv").write_text("b" * 50)
    (att.dir / "h3.csv").write_text("c")
    att.lst.write_text(json.dumps([{"file": "h1.csv"}, {"file": "h2.csv"}]))
    assert apreview(att) == 0
    att.lst.write_text(json.dumps([{"file": "h1.csv"}, {"file": "h2.csv"}, {"file": "h3.csv"}]))
    capsys.readouterr()
    assert apreview(att) == 2 and aattach(att) == 2
    assert "합계가" in capsys.readouterr().err
    assert att.raw.calls == []


def test_attach_exactly_ten_files_allowed_eleven_rejected(att):
    for i in range(11):
        (att.dir / f"f{i}.csv").write_text(f"v{i}\n")
    att.lst.write_text(json.dumps([{"file": f"f{i}.csv"} for i in range(10)]))
    assert apreview(att) == 0 and aattach(att) == 0
    assert len([c for c in att.raw.calls if c.method == "POST"]) == 10
    att.lst.write_text(json.dumps([{"file": f"f{i}.csv"} for i in range(11)]))
    assert apreview(att) == 2


def test_attach_duplicate_names_are_case_insensitive(att):
    (att.dir / "sub").mkdir()
    (att.dir / "x.csv").write_text("same\n")
    (att.dir / "sub/x.CSV").write_text("same\n")
    att.lst.write_text(json.dumps([{"file": "x.csv"}, {"file": "sub/x.CSV"}]))
    assert apreview(att) == 2 and aattach(att) == 2
    (att.dir / "sub/x.CSV").write_text("other\n")
    assert apreview(att) == 2 and att.raw.calls == []


def test_attach_second_upload_4xx_keeps_first_and_reuses_it_on_retry(att):
    assert apreview(att) == 0
    n = [0]

    def second_fails(c):
        if c.method == "POST":
            n[0] += 1
            if n[0] == 2:
                att.raw.upload_reply = (400, {}, {"errorMessages": ["bad"]})
            att.raw.land(c)
    att.raw.land, att.raw.on_call = att.raw.on_call, second_fails
    assert aattach(att) == 5
    assert len(stamp_files(att.env)) == 1
    assert [x["filename"] for x in att.fake.attachments] == [aname(att, "a.csv")]
    att.raw.upload_reply, before = None, len(att.raw.calls)
    assert aattach(att) == 0
    posts = att.raw.calls[before:]
    assert len(posts) == 1 and f'filename="{aname(att, "r.json")}"'.encode() in posts[0].data


def test_multipart_file_default_stays_png_and_accepts_other_type():
    assert b"Content-Type: image/png\r\n\r\n" in jc.multipart_file("a.png", b"x")[1]
    assert b"Content-Type: text/csv\r\n\r\n" in jc.multipart_file("a.csv", b"x", "text/csv")[1]



def media_block(mid, alt):
    return {"type": "mediaSingle", "attrs": {"layout": "center"}, "content": [
        {"type": "media", "attrs": {"type": "file", "id": mid, "collection": "", "alt": alt}}]}


def rep_adf(first=True, second=True):
    adf = fig_adf()
    items = adf["content"][0]["content"]
    if second:
        items[1]["content"].insert(1, media_block("old-2", "old2.png"))
    if first:
        items[0]["content"].append(media_block("old-1", "old1.png"))
    return adf


@pytest.fixture
def rep(fig):
    fig.fake.comments["7"] = rep_adf()
    fig.lst.write_text(json.dumps([{"anchor": "[그림 1]", "file": "a.png", "replace": True},
                                   {"anchor": "[그림 2]", "file": "b.png", "replace": True}]))
    fig.pat = fig.dir / "pat.json"
    fig.pat.write_text(json.dumps([{"anchor": "첫째 설명", "new": "첫째 고친 설명"}]))
    return fig


def rpreview(f, patches=False):
    extra = ["--patches", f.pat] if patches else []
    return run("preview", "--issue", "PROJ-1", "--comment-id", 7, *extra, "--figures", f.lst)


def rupdate(f, patches=False):
    extra = ["--patches", f.pat] if patches else []
    return run("update", "--issue", "PROJ-1", "--comment-id", 7, *extra, "--figures", f.lst)


def test_replace_two_figures_swaps_old_ids_and_puts_new_uuids(rep, capsys):
    orig = rep_adf()
    assert rpreview(rep) == 0
    out = capsys.readouterr().out
    assert "교체: 옛 그림 old1.png (media id old-1) → 새 파일" in out and "교체: 옛 그림 old2.png (media id old-2) → 새 파일" in out
    assert "교체 2, 추가 0" in out and "그림 2개 → 2개" in out and set(rep.fake.methods()) == {"GET"}
    assert rupdate(rep) == 0
    put = [c for c in rep.fake.calls if c[0] == "PUT"]
    assert len(put) == 1 and put[0][1].endswith("/comment/7?notifyUsers=false")
    new = put[0][2]["body"]
    assert jc.fingerprint(new)[2] == sorted([uuid_for(500), uuid_for(501)])
    assert "old-1" not in json.dumps(new) and "old-2" not in json.dumps(new)
    assert jc.fingerprint(new)[:2] == jc.fingerprint(orig)[:2]
    assert new["content"][0]["content"][0]["content"][1]["content"][0]["attrs"]["alt"] == "a.png"
    assert json.loads(backups_of(rep)[0].read_text()) == orig
    assert "DELETE" not in rep.fake.methods() and all(c.method in ("GET", "POST") for c in rep.raw.calls)


def test_replace_and_add_mixed(rep):
    rep.fake.comments["7"] = rep_adf(second=False)
    rep.lst.write_text(json.dumps([{"anchor": "[그림 1]", "file": "a.png", "replace": True},
                                   {"anchor": "[그림 2]", "file": "b.png"}]))
    assert rpreview(rep) == 0 and rupdate(rep) == 0
    new = rep.fake.comments["7"]
    assert jc.fingerprint(new)[2] == sorted([uuid_for(500), uuid_for(501)])
    assert [c["type"] for c in new["content"][0]["content"][1]["content"]] == ["paragraph", "mediaSingle", "bulletList"]
    assert len(new["content"][0]["content"][0]["content"]) == 2


def test_replace_with_patches_finds_anchor_in_patched_text(rep, capsys):
    rep.pat.write_text(json.dumps([{"anchor": "[그림 1] 첫째 설명", "new": "[도표 1] 새 설명"}]))
    rep.lst.write_text(json.dumps([{"anchor": "[도표 1]", "file": "a.png", "replace": True}]))
    assert rpreview(rep, True) == 0
    out = capsys.readouterr().out
    assert "- 전: [그림 1] 첫째 설명" in out and "+ 후: [도표 1] 새 설명" in out and "치환 1곳" in out
    assert "교체: 옛 그림 old1.png" in out and "교체 1, 추가 0" in out and "그림 2개 → 2개" in out
    assert rupdate(rep, True) == 0
    new = rep.fake.comments["7"]
    assert new["content"][0]["content"][0]["content"][0]["content"][0]["text"] == "[도표 1] 새 설명"
    assert jc.fingerprint(new)[2] == sorted(["old-2", uuid_for(500)])
    assert jc.fingerprint(new)[1] == 1


def test_replace_without_figure_after_anchor_rc2(rep, capsys):
    rep.fake.comments["7"] = rep_adf(first=False)
    rep.lst.write_text(json.dumps([{"anchor": "[그림 1]", "file": "a.png", "replace": True}]))
    assert rpreview(rep) == 2 and rupdate(rep) == 2
    assert "바꿀 그림이 없습니다(자리 문단 바로 뒤에 그림이 있어야 합니다)" in capsys.readouterr().err
    assert stamp_files(rep.env) == [] and rep.raw.calls == [] and "PUT" not in rep.fake.methods()


def test_add_item_with_existing_figure_still_rc2_in_combined_mode(rep, capsys):
    rep.lst.write_text(json.dumps([{"anchor": "[그림 1]", "file": "a.png"}]))
    assert rpreview(rep, True) == 2
    assert "이미 그림이 있습니다" in capsys.readouterr().err and stamp_files(rep.env) == []


@pytest.mark.parametrize("bad", ["true", 1, None, [True]])
def test_replace_value_must_be_boolean_rc2(rep, bad):
    rep.lst.write_text(json.dumps([{"anchor": "[그림 1]", "file": "a.png", "replace": bad}]))
    assert rpreview(rep) == 2 and rupdate(rep) == 2
    assert stamp_files(rep.env) == [] and rep.raw.calls == []


def test_combined_patch_list_change_after_preview_rc3(rep):
    assert rpreview(rep, True) == 0
    rep.pat.write_text(json.dumps([{"anchor": "첫째 설명", "new": "미리보기와 다른 글"}]))
    assert rupdate(rep, True) == 3
    assert rep.raw.calls == [] and "PUT" not in rep.fake.methods()


def test_combined_stamp_binds_patch_list_and_replace_flag(rep):
    assert rpreview(rep, True) == 0
    assert rupdate(rep, False) == 3
    assert rupdate(rep, True) == 0
    assert jc.fingerprint(rep.fake.comments["7"])[2] == sorted([uuid_for(500), uuid_for(501)])


def test_replace_flag_is_part_of_stamp_hash():
    plan = [{"anchor": "a", "name": "a.png", "size": 1, "sha256": "x", "width": 1, "height": 1, "replace": False}]
    flipped = [{**plan[0], "replace": True}]
    assert jc.figures_stamp_hash("PROJ-1", "7", plan) != jc.figures_stamp_hash("PROJ-1", "7", flipped)
    assert jc.figures_stamp_hash("PROJ-1", "7", plan) == jc.figures_stamp_hash("PROJ-1", "7", plan, [])


def test_combined_figure_file_change_after_preview_rc3(rep):
    assert rpreview(rep, True) == 0
    (rep.dir / "a.png").write_bytes(png_bytes(4, 3, b"CHANGED-SAME-ANCHORS"))
    assert rupdate(rep, True) == 3
    assert rep.raw.calls == [] and "PUT" not in rep.fake.methods()


def test_combined_comment_changed_after_preview_rc3(rep):
    assert rpreview(rep, True) == 0
    changed = rep_adf()
    changed["content"][1]["content"][0]["text"] = "누군가 고친 문단"
    rep.fake.comments["7"] = changed
    assert rupdate(rep, True) == 3 and "PUT" not in rep.fake.methods()


@pytest.mark.parametrize("mutation", ["text", "card", "old_id_stays", "extra_media"])
def test_combined_insert_step_violations_block_put(rep, monkeypatch, mutation):
    real = jc.insert_figures

    def bad_insert(cur, plan, uuids):
        new = real(cur, plan, uuids)
        if mutation == "text":
            new["content"][1]["content"][0]["text"] = "교체 단계가 글자를 바꿨다"
        elif mutation == "card":
            new["content"][1]["content"].append({"type": "inlineCard", "attrs": {"url": "https://x.example/extra"}})
        elif mutation == "old_id_stays":
            new["content"][0]["content"][0]["content"].append(media_block("old-1", "old1.png"))
        else:
            new["content"].append(media_block("rogue", "rogue.png"))
        return new
    monkeypatch.setattr(jc, "insert_figures", bad_insert)
    assert rpreview(rep, True) == 0
    assert rupdate(rep, True) == 2
    assert "PUT" not in rep.fake.methods() and backups_of(rep) == []
    assert len(stamp_files(rep.env)) == 1


def test_check_figure_result_replace_rules():
    cur = rep_adf()
    base = copy.deepcopy(cur)
    new = jc.insert_figures(base, [{"anchor": "[그림 1]", "replace": True, "width": 1, "height": 1, "name": "n.png"}], [uuid_for(5)])
    jc.check_figure_result(cur, new, [uuid_for(5)], base, ["old-1"])
    with pytest.raises(jc.Fail):
        jc.check_figure_result(cur, new, [uuid_for(5)], base, [])
    with pytest.raises(jc.Fail):
        jc.check_figure_result(cur, new, ["old-2"], base, ["old-1"])
    with pytest.raises(jc.Fail):
        jc.check_figure_result(cur, new, [uuid_for(5)], base, ["nope"])


def test_replace_swaps_whole_block_and_preserves_neighbors():
    cur = rep_adf()
    e = {"anchor": "[그림 1]", "replace": True, "width": 9, "height": 7, "name": "n.png"}
    new = jc.insert_figures(cur, [e], [uuid_for(5)])
    kids = new["content"][0]["content"][0]["content"]
    assert [c["type"] for c in kids] == ["paragraph", "mediaSingle"] and kids[1]["content"][0]["attrs"]["id"] == uuid_for(5)
    assert cur == rep_adf()


def test_body_file_with_figures_or_patches_still_rc2(rep, env):
    assert run("preview", "--issue", "PROJ-1", "--comment-id", 7, "--body-file", env.body, "--figures", rep.lst) == 2
    assert run("preview", "--issue", "PROJ-1", "--comment-id", 7, "--body-file", env.body, "--patches", rep.pat) == 2
    assert run("update", "--issue", "PROJ-1", "--comment-id", 7, "--body-file", env.body, "--figures", rep.lst) == 2
    assert run("update", "--issue", "PROJ-1", "--comment-id", 7, "--body-file", env.body, "--patches", rep.pat) == 2
    assert run("update", "--issue", "PROJ-1", "--comment-id", 7) == 2
    assert run("preview", "--issue", "PROJ-1", "--comment-id", 7, "--attach", rep.lst, "--patches", rep.pat) == 2
    assert run("preview", "--issue", "PROJ-1", "--patches", rep.pat, "--figures", rep.lst) == 2
    assert stamp_files(env) == [] and rep.raw.calls == [] and "PUT" not in rep.fake.methods()


def test_patches_only_path_still_keeps_media_ids(rep):
    assert run("preview", "--issue", "PROJ-1", "--comment-id", 7, "--patches", rep.pat) == 0
    assert run("update", "--issue", "PROJ-1", "--comment-id", 7, "--patches", rep.pat) == 0
    assert jc.fingerprint(rep.fake.comments["7"])[2] == ["old-1", "old-2"]



def cap_block(mid, alt, caption="옛 설명 글", layout="wide", width=80):
    return {"type": "mediaSingle", "attrs": {"layout": layout, "width": width}, "content": [
        {"type": "media", "attrs": {"type": "file", "id": mid, "collection": "", "alt": alt}},
        {"type": "caption", "content": [{"type": "text", "text": caption}]}]}


def set_first_block(f, block):
    adf = rep_adf(second=False)
    adf["content"][0]["content"][0]["content"][1] = block
    f.fake.comments["7"] = adf
    f.lst.write_text(json.dumps([{"anchor": "[그림 1]", "file": "a.png", "replace": True}]))


def test_replace_keeps_caption_and_layout_and_shows_them(rep, capsys):
    set_first_block(rep, cap_block("old-1", "old1.png"))
    assert rpreview(rep) == 0
    out = capsys.readouterr().out
    assert "설명 글 유지: 옛 설명 글" in out and "media id old-1" in out
    assert rupdate(rep) == 0
    blk = rep.fake.comments["7"]["content"][0]["content"][0]["content"][1]
    assert blk["attrs"] == {"layout": "wide", "width": 80}
    assert [c["type"] for c in blk["content"]] == ["media", "caption"]
    assert blk["content"][0]["attrs"]["id"] == uuid_for(500) and blk["content"][1]["content"][0]["text"] == "옛 설명 글"


def test_replace_caption_can_be_patched_in_same_run(rep):
    set_first_block(rep, cap_block("old-1", "old1.png"))
    rep.pat.write_text(json.dumps([{"anchor": "옛 설명", "new": "새 설명"}]))
    assert rpreview(rep, True) == 0 and rupdate(rep, True) == 0
    blk = rep.fake.comments["7"]["content"][0]["content"][0]["content"][1]
    assert blk["content"][1]["content"][0]["text"] == "새 설명 글" and blk["attrs"]["layout"] == "wide"


def test_replace_block_with_two_media_rc2(rep, capsys):
    blk = cap_block("old-1", "old1.png")
    blk["content"].insert(1, {"type": "media", "attrs": {"type": "file", "id": "old-1b", "collection": ""}})
    set_first_block(rep, blk)
    assert rpreview(rep) == 2 and rupdate(rep) == 2
    assert "바꿀 그림 블록의 모양이 예상과 다릅니다(그림 1장이 아님)" in capsys.readouterr().err
    assert stamp_files(rep.env) == [] and rep.raw.calls == [] and "PUT" not in rep.fake.methods()


def test_replace_target_media_group_rc2(rep, capsys):
    set_first_block(rep, {"type": "mediaGroup", "content": [{"type": "media", "attrs": {"type": "file", "id": "old-1", "collection": ""}}]})
    assert rpreview(rep) == 2 and rupdate(rep) == 2
    assert "바꿀 그림이 없습니다" in capsys.readouterr().err and rep.raw.calls == [] and "PUT" not in rep.fake.methods()


def test_replace_new_uuid_equal_to_remaining_old_id_blocks_put_after_upload(rep):
    adf = rep_adf()
    adf["content"][0]["content"][1]["content"][1] = media_block(uuid_for(500), "keep.png")
    rep.fake.comments["7"] = adf
    rep.lst.write_text(json.dumps([{"anchor": "[그림 1]", "file": "a.png", "replace": True}]))
    assert rpreview(rep) == 0
    assert rupdate(rep) == 2
    assert next(c.method for c in rep.raw.calls) == "POST"
    assert "PUT" not in rep.fake.methods() and backups_of(rep) == [] and len(stamp_files(rep.env)) == 1
    assert rep.fake.comments["7"] == adf


def test_replace_one_of_two_identical_old_ids_removes_only_one(rep):
    adf = rep_adf()
    adf["content"][0]["content"][1]["content"][1] = media_block("old-1", "old1b.png")
    rep.fake.comments["7"] = adf
    rep.lst.write_text(json.dumps([{"anchor": "[그림 1]", "file": "a.png", "replace": True}]))
    assert rpreview(rep) == 0 and rupdate(rep) == 0
    assert jc.fingerprint(rep.fake.comments["7"])[2] == sorted(["old-1", uuid_for(500)])


def test_replace_with_empty_patch_list(rep, capsys):
    rep.pat.write_text("[]")
    assert rpreview(rep, True) == 0
    assert "치환 0곳" in capsys.readouterr().out
    assert rupdate(rep, True) == 0
    assert jc.fingerprint(rep.fake.comments["7"])[2] == sorted([uuid_for(500), uuid_for(501)])


def test_empty_string_arguments_count_as_given(rep, env):
    for cmd in ("preview", "update"):
        assert run(cmd, "--issue", "PROJ-1", "--comment-id", 7, "--body-file", "", "--patches", rep.pat) == 2
        assert run(cmd, "--issue", "PROJ-1", "--comment-id", 7, "--body-file", "", "--figures", rep.lst) == 2
        assert run(cmd, "--issue", "PROJ-1", "--comment-id", 7, "--patches", "") == 2
        assert run(cmd, "--issue", "PROJ-1", "--comment-id", 7, "--patches", rep.pat, "--figures", "") == 2
    assert run("preview", "--issue", "PROJ-1", "--body-file", "", "--attach", rep.lst) == 2
    assert stamp_files(env) == [] and rep.raw.calls == [] and "PUT" not in rep.fake.methods()



TABLE_MD = "| 판 | 값 |\n|:---|---:|\n| **굵게** | `코드` |\n| a\\|b | |\n"


def cell_nodes(cell):
    return cell["content"][0]["content"]


def test_md_table_to_adf_header_body_inline_empty_cell_and_escaped_pipe():
    adf = jc.md_to_adf("* 가\n\n" + TABLE_MD + "\n* 나\n")
    assert [n["type"] for n in adf["content"]] == ["bulletList", "table", "bulletList"]
    table = adf["content"][1]
    assert table["attrs"] == {"isNumberColumnEnabled": False, "layout": "default"}
    rows = table["content"]
    assert [r["type"] for r in rows] == ["tableRow"] * 3
    assert [[c["type"] for c in r["content"]] for r in rows] == [["tableHeader"] * 2, ["tableCell"] * 2, ["tableCell"] * 2]
    assert all(c["content"][0]["type"] == "paragraph" and len(c["content"]) == 1 for r in rows for c in r["content"])
    assert cell_nodes(rows[0]["content"][0]) == [{"type": "text", "text": "판"}]
    assert cell_nodes(rows[1]["content"][0]) == [{"type": "text", "text": "굵게", "marks": [{"type": "strong"}]}]
    assert cell_nodes(rows[1]["content"][1]) == [{"type": "text", "text": "코드", "marks": [{"type": "code"}]}]
    assert cell_nodes(rows[2]["content"][0]) == [{"type": "text", "text": "a|b"}]
    assert rows[2]["content"][1]["content"] == [{"type": "paragraph", "content": []}]
    assert "---" not in json.dumps(table, ensure_ascii=False)


def test_md_table_ends_at_first_non_pipe_line_and_keeps_following_text():
    adf = jc.md_to_adf("| a |\n|---|\n| 1 |\n뒤 문단\n")
    assert [n["type"] for n in adf["content"]] == ["table", "paragraph"]
    assert len(adf["content"][0]["content"]) == 2


def test_md_table_column_mismatch_stays_text_with_one_warning():
    warns = []
    adf = jc.md_to_adf("| a | b |\n|---|---|\n| 1 | 2 |\n| 3 |\n", warns)
    assert [n["type"] for n in adf["content"]] == ["paragraph"] * 4
    assert len(warns) == 1 and "열 수(1)" in warns[0] and "머리(2)" in warns[0] and "표 본문 2번째 줄" in warns[0]
    assert jc.md_to_adf("| a | b |\n|---|---|\n| 1 | 2 | 3 |\n")["content"][0]["type"] == "paragraph"


def test_md_table_needs_separator_line_with_same_column_count():
    for md in ("| a | b |\n| 1 | 2 |\n", "| a | b |\n|---|\n| 1 | 2 |\n", "| a | b |\n|--|x-|\n| 1 | 2 |\n", "| a | b |\n"):
        warns = []
        adf = jc.md_to_adf(md, warns)
        assert all(n["type"] == "paragraph" for n in adf["content"]) and warns == []


def test_format_warnings_do_not_count_table_as_paragraph():
    adf = jc.md_to_adf("1. 주제\n   * 결과: 표 참고\n\n" + TABLE_MD)
    assert jc.format_warnings(adf) == []
    assert any("목록 밖 문단" in w for w in jc.format_warnings(jc.md_to_adf(TABLE_MD + "\n문단입니다\n")))
    assert jc.unsupported(adf) == []


def test_table_text_fingerprint_canonical_and_rendering_are_stable():
    a, b = jc.md_to_adf(TABLE_MD), jc.md_to_adf(TABLE_MD)
    assert jc.canonical(a) == jc.canonical(b)
    assert jc.fingerprint(a) == (["판", "값", "굵게", "코드", "a|b", ""], 0, [])
    assert jc.table_shapes(a) == [[2, 2, 2]]
    assert jc.adf_to_text(a).split("\n") == ["표 3행 × 2열", "  판 | 값", "  **굵게** | `코드`", "  a|b | "]


def test_preview_shows_table_as_rows_by_columns_without_paragraph_warning(env, capsys):
    env.body.write_text("1. 주제\n   * 결과: 아래 표 참고\n\n| 판 | 값 |\n|---|---|\n| x | 1 |\n| y | 2 |\n", encoding="utf-8")
    assert run("preview", "--issue", "PROJ-1", "--body-file", env.body) == 0
    out = capsys.readouterr().out
    assert "표 3행 × 2열\n  판 | 값\n  x | 1\n  y | 2" in out
    assert "경고 없음" in out and "목록 밖 문단" not in out


def test_preview_warns_on_table_column_mismatch(env, capsys):
    env.body.write_text("* 가\n\n| a | b |\n|---|---|\n| 1 |\n", encoding="utf-8")
    assert run("preview", "--issue", "PROJ-1", "--body-file", env.body) == 0
    out = capsys.readouterr().out
    assert "표로 바꾸지 않고 글 문단으로" in out and "목록 밖 문단" in out
    assert "표 3행" not in out and "| a | b |" in out.split("== 미리보기 ==")[1]


def test_post_table_verify_ok_with_server_added_attrs_and_dropped_empty_content(env):
    env.body.write_text("* 가\n\n" + TABLE_MD, encoding="utf-8")

    def server_style(b):
        b = copy.deepcopy(b)

        def walk(n):
            n["attrs"] = {**n.get("attrs", {}), "localId": "abc123"}
            if n.get("type") == "paragraph" and n.get("content") == []:
                del n["content"]
            for c in n.get("content", []):
                walk(c)
        walk(b)
        return b
    run("preview", "--issue", "PROJ-1", "--body-file", env.body)
    env.fake.tamper = server_style
    assert run("post", "--issue", "PROJ-1", "--body-file", env.body) == 0


def test_verify_detects_table_count_row_and_cell_changes_rc4(env, capsys):
    env.body.write_text("* 가\n\n| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n", encoding="utf-8")

    def attempt(tamper):
        run("preview", "--issue", "PROJ-1", "--body-file", env.body)
        env.fake.tamper = tamper
        rc = run("post", "--issue", "PROJ-1", "--body-file", env.body)
        return rc, capsys.readouterr().err

    def drop_cell(b):
        b = copy.deepcopy(b)
        del b["content"][1]["content"][2]["content"][1]
        return b

    def drop_row(b):
        b = copy.deepcopy(b)
        del b["content"][1]["content"][2]
        return b

    def drop_table(b):
        b = copy.deepcopy(b)
        del b["content"][1]
        return b

    def table_to_paragraph(b):
        b = copy.deepcopy(b)
        b["content"][1] = {"type": "paragraph", "content": [{"type": "text", "text": "| a | b |"}]}
        return b

    for tamper in (drop_cell, drop_row, drop_table, table_to_paragraph):
        rc, err = attempt(tamper)
        assert rc == 4 and "표 구조" in err and "게시는 완료됐습니다" in err, tamper.__name__
    err = attempt(drop_cell)[1]
    assert "[[2, 2, 2]]" in err and "[[2, 2, 1]]" in err



ROWS = [["원본 x2t", "**0.91**", "0.88"], ["원본 x17t", "0.93", "`0.90`"]]


def table_comment(n_rows=8, head="판", cols=3):
    lines = [f"| {head} | " + " | ".join(f"지표{c}" for c in range(1, cols)) + " |", "|" + "---|" * cols]
    lines += [f"| 판{k} | " + " | ".join(f"0.{k}{c}" for c in range(1, cols)) + " |" for k in range(1, n_rows)]
    adf = media_adf("앞 문장 하나")
    adf["content"].append(jc.md_to_adf("\n".join(lines))["content"][0])
    return adf


def row_patch_file(env, *patches):
    path = env.home / "rows.json"
    path.write_text(json.dumps(list(patches) or [{"table_anchor": "판", "append_rows": ROWS}], ensure_ascii=False), encoding="utf-8")
    return path


def rows_run(cmd, path):
    return run(cmd, "--issue", "PROJ-1", "--comment-id", 7, "--patches", path)


def test_row_append_to_figure_comment_adds_rows_keeps_media_and_previews_change(env, capsys):
    orig = table_comment()
    env.fake.comments["7"] = copy.deepcopy(orig)
    path = row_patch_file(env)
    assert rows_run("preview", path) == 0
    out = capsys.readouterr().out
    assert "- 전: [표 «판»] 8행" in out
    assert "+ 후: [표 «판»] 10행 · 추가: 원본 x2t | **0.91** | 0.88 / 원본 x17t | 0.93 | `0.90`" in out
    assert "표 10행 × 3열" in out and set(env.fake.methods()) == {"GET"}
    assert rows_run("update", path) == 0
    new = env.fake.comments["7"]
    assert jc.table_shapes(orig) == [[3] * 8] and jc.table_shapes(new) == [[3] * 10]
    assert jc.fingerprint(new)[2] == ["uuid-1"] and new["content"][0] == orig["content"][0]
    rows = new["content"][1]["content"]
    assert rows[:8] == orig["content"][1]["content"]
    assert [[c["type"] for c in r["content"]] for r in rows[8:]] == [["tableCell"] * 3] * 2
    assert cell_nodes(rows[8]["content"][1]) == [{"type": "text", "text": "0.91", "marks": [{"type": "strong"}]}]
    assert cell_nodes(rows[9]["content"][2]) == [{"type": "text", "text": "0.90", "marks": [{"type": "code"}]}]
    assert rows[8] == jc.table_row(ROWS[0]) and rows[9] == jc.table_row(ROWS[1])
    put = [c for c in env.fake.calls if c[0] == "PUT"]
    assert len(put) == 1 and put[0][1].endswith("/comment/7?notifyUsers=false")
    assert len(list((env.home / ".claude/_audit/jira-preview").glob("backup-PROJ-1-7-*.adf.json"))) == 1


def test_table_row_helper_builds_header_or_body_cells_and_table_node_uses_it():
    assert [c["type"] for c in jc.table_row(["a", "b"], header=True)["content"]] == ["tableHeader"] * 2
    assert [c["type"] for c in jc.table_row(["a", "b"])["content"]] == ["tableCell"] * 2
    t = jc.table_node([["a"], ["b"]])
    assert t["content"] == [jc.table_row(["a"], True), jc.table_row(["b"])]


def test_row_anchor_not_found_or_two_tables_rc2(env, capsys):
    adf = table_comment()
    adf["content"].append(copy.deepcopy(adf["content"][1]))
    env.fake.comments["7"] = copy.deepcopy(adf)
    for anchor, n in (("없는 표", 0), ("판", 2)):
        path = row_patch_file(env, {"table_anchor": anchor, "append_rows": ROWS})
        for cmd in ("preview", "update"):
            assert rows_run(cmd, path) == 2
            assert f"일치하는 표가 {n}개입니다(정확히 1개여야 합니다)" in capsys.readouterr().err
    assert "PUT" not in env.fake.methods() and env.fake.comments["7"] == adf and stamp_files(env) == []


def test_row_anchor_matches_first_cell_exactly_after_strip_and_ignoring_marks(env):
    adf = media_adf()
    adf["content"].append(jc.md_to_adf("| **판** | 값 |\n|---|---|\n| x | 1 |\n")["content"][0])
    env.fake.comments["7"] = adf
    assert rows_run("preview", row_patch_file(env, {"table_anchor": "판 일부", "append_rows": [["y", "2"]]})) == 2
    path = row_patch_file(env, {"table_anchor": "  판 ", "append_rows": [["y", "2"]]})
    assert rows_run("preview", path) == 0 and rows_run("update", path) == 0
    assert jc.table_shapes(env.fake.comments["7"]) == [[2, 2, 2]]


def test_row_column_count_mismatch_rc2_names_row_and_counts(env, capsys):
    env.fake.comments["7"] = table_comment()
    path = row_patch_file(env, {"table_anchor": "판", "append_rows": [["a", "b", "c"], ["only", "two"]]})
    assert rows_run("preview", path) == 2 and rows_run("update", path) == 2
    assert "붙일 2번째 행의 칸 수(2)가 표 첫 행의 칸 수(3)와 다릅니다" in capsys.readouterr().err
    assert stamp_files(env) == [] and "PUT" not in env.fake.methods()


@pytest.mark.parametrize("attr", ["colspan", "rowspan"])
def test_row_append_rejects_table_with_merged_cells(env, capsys, attr):
    adf = table_comment()
    adf["content"][1]["content"][2]["content"][0]["attrs"] = {attr: 2}
    env.fake.comments["7"] = adf
    path = row_patch_file(env)
    assert rows_run("preview", path) == 2 and rows_run("update", path) == 2
    assert "병합 칸" in capsys.readouterr().err and "PUT" not in env.fake.methods() and stamp_files(env) == []


def test_row_append_allows_unit_span_attrs_on_cells(env):
    adf = table_comment()
    for r in adf["content"][1]["content"]:
        for c in r["content"]:
            c["attrs"] = {"colspan": 1, "rowspan": 1, "colwidth": [120]}
    env.fake.comments["7"] = adf
    path = row_patch_file(env)
    assert rows_run("preview", path) == 0 and rows_run("update", path) == 0
    assert jc.table_shapes(env.fake.comments["7"]) == [[3] * 10]


def test_row_and_text_patches_mix_in_one_file(env, capsys):
    env.fake.comments["7"] = table_comment()
    path = row_patch_file(env, {"anchor": "문장 하나", "new": "문장 둘"}, {"table_anchor": "판", "append_rows": ROWS[:1]},
                          {"anchor": "판3", "new": "판3 수정"})
    assert rows_run("preview", path) == 0
    out = capsys.readouterr().out
    assert "- 전: 앞 문장 하나" in out and "+ 후: 앞 문장 둘" in out and "9행 · 추가: 원본 x2t" in out and "+ 후: 판3 수정" in out
    assert rows_run("update", path) == 0
    new = env.fake.comments["7"]
    blocks = jc.fingerprint(new)[0]
    assert blocks[0] == "앞 문장 둘" and "판3 수정" in blocks and "원본 x2t" in blocks
    assert jc.table_shapes(new) == [[3] * 9] and jc.fingerprint(new)[2] == ["uuid-1"]


def test_two_row_patches_on_same_table_and_on_second_table(env):
    adf = table_comment()
    adf["content"].append(jc.md_to_adf("| 비교 | 값 |\n|---|---|\n| x | 1 |\n")["content"][0])
    env.fake.comments["7"] = adf
    path = row_patch_file(env, {"table_anchor": "판", "append_rows": ROWS[:1]}, {"table_anchor": "비교", "append_rows": [["z", ""]]},
                          {"table_anchor": "판", "append_rows": ROWS[1:]})
    assert rows_run("preview", path) == 0 and rows_run("update", path) == 0
    new = env.fake.comments["7"]
    assert jc.table_shapes(new) == [[3] * 10, [2] * 3]
    assert [r["content"][0]["content"][0]["content"] for r in new["content"][1]["content"][8:]] == \
        [[{"type": "text", "text": "원본 x2t"}], [{"type": "text", "text": "원본 x17t"}]]
    assert new["content"][2]["content"][2]["content"][1]["content"] == [{"type": "paragraph", "content": []}]


def test_row_patch_changed_after_preview_rc3(env):
    env.fake.comments["7"] = table_comment()
    path = row_patch_file(env)
    assert rows_run("preview", path) == 0
    row_patch_file(env, {"table_anchor": "판", "append_rows": [["다른", "행", "내용"]]})
    assert rows_run("update", path) == 3 and "PUT" not in env.fake.methods()


@pytest.mark.parametrize("bad", [
    {"table_anchor": "판"}, {"append_rows": [["a"]]}, {"table_anchor": "  ", "append_rows": [["a"]]},
    {"table_anchor": 1, "append_rows": [["a"]]}, {"table_anchor": "판", "append_rows": []},
    {"table_anchor": "판", "append_rows": [[]]}, {"table_anchor": "판", "append_rows": ["a"]},
    {"table_anchor": "판", "append_rows": [["a", 1]]}, {"table_anchor": "판", "append_rows": "a"},
    {"anchor": "x", "new": "y", "table_anchor": "판", "append_rows": [["a"]]}, {"anchor": "x"}, {"new": "y"}, "text", 3, None])
def test_load_patches_format_errors_rc2_show_both_formats(env, bad):
    path = env.home / "bad.json"
    path.write_text(json.dumps([{"anchor": "ok", "new": "ok"}, bad]), encoding="utf-8")
    with pytest.raises(jc.Fail) as e:
        jc.load_patches(path)
    assert e.value.rc == 2 and '"anchor"' in e.value.msg and '"table_anchor"' in e.value.msg and '"append_rows"' in e.value.msg
    path.write_text(json.dumps({"table_anchor": "판", "append_rows": [["a"]]}), encoding="utf-8")
    with pytest.raises(jc.Fail) as e2:
        jc.load_patches(path)
    assert e2.value.rc == 2


def test_load_patches_accepts_both_kinds_and_ignores_unknown_keys(env):
    items = [{"anchor": "a", "new": "b", "memo": 1}, {"table_anchor": "판", "append_rows": [["x", "y"]], "memo": "z"}]
    path = env.home / "ok.json"
    path.write_text(json.dumps(items), encoding="utf-8")
    assert jc.load_patches(path) == items


def old_figures_stamp_hash(issue, comment_id, plan, patches):
    keys = ("anchor", "name", "size", "sha256", "width", "height")
    rec = {"kind": "figures", "site": jc.site(), "issue": issue, "comment_id": comment_id,
           "figures": [{**{k: e[k] for k in keys}, **({"replace": True} if e["replace"] else {})} for e in plan]}
    if patches:
        rec["patches"] = [{"anchor": p["anchor"], "new": p["new"]} for p in patches]
    return hashlib.sha256(jc.canonical(rec).encode("utf-8")).hexdigest()


def test_figures_stamp_hash_text_only_patches_keep_old_hash_and_row_patches_are_bound(env):
    plan = [{"anchor": "a", "name": "a.png", "size": 1, "sha256": "x", "width": 1, "height": 1, "replace": False}]
    text = [{"anchor": "옛", "new": "새"}]
    assert jc.figures_stamp_hash("PROJ-1", "7", plan, text) == old_figures_stamp_hash("PROJ-1", "7", plan, text)
    assert jc.figures_stamp_hash("PROJ-1", "7", plan, [{"anchor": "옛", "new": "새", "memo": 1}]) == old_figures_stamp_hash("PROJ-1", "7", plan, text)
    row = [{"table_anchor": "판", "append_rows": [["a", "b"]]}]
    h = jc.figures_stamp_hash("PROJ-1", "7", plan, row)
    assert h != jc.figures_stamp_hash("PROJ-1", "7", plan) and h != jc.figures_stamp_hash("PROJ-1", "7", plan, text)
    assert h != jc.figures_stamp_hash("PROJ-1", "7", plan, [{"table_anchor": "판", "append_rows": [["a", "c"]]}])
    assert h != jc.figures_stamp_hash("PROJ-1", "7", plan, [{"table_anchor": "값", "append_rows": [["a", "b"]]}])
    mixed = jc.figures_stamp_hash("PROJ-1", "7", plan, text + row)
    assert mixed not in (h, jc.figures_stamp_hash("PROJ-1", "7", plan, text)) and mixed != jc.figures_stamp_hash("PROJ-1", "7", plan, row + text)


def test_figures_combined_with_row_patch_adds_rows_and_figures(fig, capsys):
    adf = fig_adf()
    adf["content"].append(jc.md_to_adf("| 판 | 값 |\n|---|---|\n| x | 1 |\n")["content"][0])
    fig.fake.comments["7"] = adf
    pat = fig.dir / "pat.json"
    pat.write_text(json.dumps([{"table_anchor": "판", "append_rows": [["y", "2"]]}]), encoding="utf-8")

    def go(cmd):
        return run(cmd, "--issue", "PROJ-1", "--comment-id", 7, "--patches", pat, "--figures", fig.lst)
    assert go("preview") == 0
    out = capsys.readouterr().out
    assert "- 전: [표 «판»] 2행" in out and "+ 후: [표 «판»] 3행 · 추가: y | 2" in out
    pat.write_text(json.dumps([{"table_anchor": "판", "append_rows": [["y", "3"]]}]), encoding="utf-8")
    assert go("update") == 3 and fig.raw.calls == [] and "PUT" not in fig.fake.methods()
    pat.write_text(json.dumps([{"table_anchor": "판", "append_rows": [["y", "2"]]}]), encoding="utf-8")
    assert go("update") == 0
    new = fig.fake.comments["7"]
    assert jc.table_shapes(new) == [[2, 2, 2]] and jc.fingerprint(new)[2] == sorted([uuid_for(500), uuid_for(501)])
    assert "y" in jc.fingerprint(new)[0] and jc.fingerprint(new)[1] == 1


def _mutate_text(new):
    new["content"][0]["content"][0]["content"][0]["content"][0]["text"] = "몰래 바뀐 글"


def _mutate_extra_row(new):
    new["content"][1]["content"].append(jc.table_row(["몰래", "붙은", "행"]))


def _mutate_drop_appended_row(new):
    new["content"][1]["content"].pop()


def _mutate_delete_existing_row(new):
    del new["content"][1]["content"][2]


def _mutate_existing_cell_mark(new):
    new["content"][1]["content"][1]["content"][1]["content"][0]["content"][0]["marks"] = [{"type": "strong"}]


def _mutate_appended_cell_text(new):
    new["content"][1]["content"][-1]["content"][0]["content"][0]["content"][0]["text"] = "고친 글"


@pytest.mark.parametrize("mutate", [_mutate_text, _mutate_extra_row, _mutate_drop_appended_row, _mutate_delete_existing_row,
                                    _mutate_existing_cell_mark, _mutate_appended_cell_text])
def test_update_refuses_when_result_differs_from_requested_rows_only(env, capsys, monkeypatch, mutate):
    env.fake.comments["7"] = table_comment()
    path = row_patch_file(env)
    real = jc.apply_patches

    def sneaky(adf, patches):
        new, changes = real(adf, patches)
        mutate(new)
        return new, changes
    monkeypatch.setattr(jc, "apply_patches", sneaky)
    assert rows_run("preview", path) == 2 and stamp_files(env) == []
    assert "보내지 않습니다" in capsys.readouterr().err
    assert rows_run("update", path) == 2
    assert "보내지 않습니다" in capsys.readouterr().err and "PUT" not in env.fake.methods()


def test_text_patch_aimed_at_appended_row_text_is_refused(env, capsys):
    env.fake.comments["7"] = table_comment()
    path = row_patch_file(env, {"table_anchor": "판", "append_rows": ROWS[:1]}, {"anchor": "원본 x2t", "new": "원본 X2T"})
    assert rows_run("update", path) == 2
    assert "붙은 행이 요청과 다릅니다" in capsys.readouterr().err and "PUT" not in env.fake.methods()


def test_check_rows_only_added_is_a_noop_without_row_patches():
    cur = table_comment()
    other = copy.deepcopy(cur)
    other["content"][0]["content"][0]["content"][0]["content"][0]["text"] = "전혀 다른 글"
    jc.check_rows_only_added(cur, other, [{"anchor": "a", "new": "b"}])
    jc.check_rows_only_added(cur, other, [])
    with pytest.raises(jc.Fail):
        jc.check_rows_only_added(cur, other, [{"table_anchor": "판", "append_rows": ROWS}])
