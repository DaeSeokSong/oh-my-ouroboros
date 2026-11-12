"""confluence_review_gate.py 와 그 연결부(골격 스탬프 · skeleton-gate.sh) 회귀 시험. 네트워크 없음, 값은 전부 가짜.

실행: python3 -m unittest scripts/tests/test_confluence_review_gate.py
"""
import json
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
import confluence_review_gate as rg
import confluence_skeleton_check as cs

GATE = SCRIPTS / "confluence_review_gate.py"
HOOK = SCRIPTS / "skeleton-gate.sh"
CLEAN = "<h1>요약</h1>\n<p>세 방식을 비교했습니다.</p>\n<table><tbody><tr><td>exponential</td><td>351</td></tr></tbody></table>\n"
EDITED = CLEAN.replace("351", "251")
DIRTY = CLEAN + "<p>password = FAKE-TEST-pw01 와 api_token = FAKE-TEST-0001 을 썼습니다.</p>\n<p>환자번호는 FAKE-PID-0001 입니다.</p>\n"


def run_cli(tmp: Path, publish: str, reviewed: str | None) -> subprocess.CompletedProcess:
    """Write the bodies to files and run the gate command line."""
    pub = tmp / "publish.storage.html"
    pub.write_text(publish, encoding="utf-8")
    args = [sys.executable, str(GATE), str(pub)]
    if reviewed is not None:
        rev = tmp / "reviewed.storage.html"
        rev.write_text(reviewed, encoding="utf-8")
        args += ["--reviewed", str(rev)]
    return subprocess.run(args, capture_output=True, text=True, check=False)


def is_deny(stdout: str) -> bool:
    """True when stdout is a PreToolUse deny JSON."""
    try:
        return json.loads(stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    except (ValueError, KeyError, TypeError):
        return False


class ReviewGateCli(unittest.TestCase):
    """Command line: F8-like, F9-like and clean bodies."""

    def setUp(self):
        """Make a scratch folder."""
        self.tmp = Path(tempfile.mkdtemp(prefix="review-gate-"))

    def tearDown(self):
        """Remove the scratch folder."""
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_hash_differs_denied(self):
        """F8 shape: the published body differs from the reviewed one."""
        r = run_cli(self.tmp, EDITED, CLEAN)
        self.assertEqual(r.returncode, 1)
        self.assertTrue(is_deny(r.stdout))

    def test_credentials_denied_without_echoing_values(self):
        """F9 shape: fake credential and patient id, values never printed."""
        r = run_cli(self.tmp, DIRTY, DIRTY)
        self.assertEqual(r.returncode, 1)
        self.assertTrue(is_deny(r.stdout))
        self.assertNotIn("FAKE-TEST", r.stdout)
        self.assertNotIn("FAKE-PID", r.stdout)

    def test_clean_same_body_passes(self):
        """Clean body published as reviewed; trailing newline differences are ignored like the stamp."""
        r = run_cli(self.tmp, CLEAN + "\n\n", CLEAN)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn(rg.stamp_hash(CLEAN.encode()), r.stdout)


class ScanShapes(unittest.TestCase):
    """Generic shapes hit, ordinary prose does not."""

    def test_hits(self):
        """Each generic shape is found, including quoted, tag-wrapped, prefixed names and label and value in separate cells."""
        for text in ("api_key: FAKEFAKE1234", "ghp_" + "a" * 24, "MRN 12345678", "patient_id=AB-1234", "900101-1234567",
                     'password = "FAKEpw12345"', "password: 'FAKEpw12345'", "api_key = <code>FAKEKEY12345</code>",
                     "db_password=FAKEpw9876", "MY_API_KEY = FAKEKEY12345", "github_token: FAKEtok123456",
                     '"password": "FAKEpw12345"',
                     "<tr><td><p>password</p></td><td><p><code>FAKEpw12345</code></p></td></tr>",
                     "<tr><th>등록번호</th><td>12345678</td></tr>", "차트번호: 1234567", "병록번호 AB-12345",
                     "환자 ID는 P0001234"):
            with self.subTest(text=text):
                self.assertTrue(rg.scan(text), text)

    def test_prose_passes(self):
        """Column names and policy prose without credential-shaped values are not hits."""
        for text in ("환자번호 열은 비식별화합니다.", "password 정책을 바꿨습니다.", "patient ID column", "token = 512", "2026-11-10",
                     "db_token = 512", "password: 필수", "password = abc", "api_key: <code>설정값</code>",
                     "<tr><td>password</td><td>정책 참고</td></tr>", "<tr><th>등록번호</th><td>열 이름</td></tr>",
                     "등록번호 열은 지웠습니다.", "secret santa 2026"):
            with self.subTest(text=text):
                self.assertEqual(rg.scan(text), [], text)

    def test_line_number_of_first_token_on_a_line(self):
        """A token at the start of line 2 is reported on line 2, not line 1."""
        self.assertEqual(rg.scan("첫 줄\nsk-" + "a" * 24), ["토큰 꼴 (2행)"])

    def test_long_whitespace_is_fast(self):
        """A long whitespace run after a label does not blow up."""
        t0 = time.time()
        rg.scan("환자번호" + " " * 50000 + "열" + "\npassword" + " " * 50000 + "= x")
        self.assertLess(time.time() - t0, 2.0)

    def test_missing_file_is_usage_error(self):
        """A missing file exits 2 with one stderr line and no traceback."""
        r = subprocess.run([sys.executable, str(GATE), "/nonexistent/x.storage.html"], capture_output=True, text=True, check=False)
        self.assertEqual(r.returncode, 2)
        self.assertNotIn("Traceback", r.stderr)


class SkeletonStampRefuses(unittest.TestCase):
    """The review stamp is never written for a body with a credential shape."""

    def test_stamp_refused(self):
        """stamp() exits 1 and writes nothing for a dirty body, writes one file for a clean body."""
        tmp = Path(tempfile.mkdtemp(prefix="review-stamp-"))
        try:
            with mock.patch.object(cs, "STAMP_DIR", str(tmp)):
                with self.assertRaises(SystemExit) as cm:
                    cs.stamp(DIRTY.encode(), "t/t", "t", "x", 0, 0)
                self.assertEqual(cm.exception.code, 1)
                self.assertEqual(list(tmp.iterdir()), [])
                cs.stamp(CLEAN.encode(), "t/t", "t", "x", 0, 0)
                self.assertEqual([p.name for p in tmp.iterdir()], [rg.stamp_hash(CLEAN.encode()) + ".json"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class HookPath(unittest.TestCase):
    """skeleton-gate.sh with a temporary HOME: approval and stamp present, the body decides."""

    def setUp(self):
        """Temporary HOME with scripts linked, a fake session log and a working folder."""
        self.home = Path(tempfile.mkdtemp(prefix="review-hook-home-"))
        (self.home / ".claude").mkdir()
        (self.home / ".claude/scripts").symlink_to(SCRIPTS)
        self.log = self.home / ".claude/projects/p/s1.jsonl"
        self.log.parent.mkdir(parents=True)
        self.repo = self.home / "repo"
        self.repo.mkdir()
        self.env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(self.home)}

    def tearDown(self):
        """Remove the temporary HOME."""
        shutil.rmtree(self.home, ignore_errors=True)

    def call(self, body: str, page: str, stamp_body: str | None = None, stamp_ahead: float = 0, title: str | None = None) -> str:
        """Stamp stamp_body (default: body), record a publish approval for the page, run the hook and return stdout."""
        stamp_dir = self.home / ".claude/_audit/skeleton-pass"
        stamp_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)  # noqa: UP017 — 시스템 python3(3.10) 호환
        stamped = (body if stamp_body is None else stamp_body).encode()
        (stamp_dir / f"{rg.stamp_hash(stamped)}.json").write_text(
            json.dumps({"format": "t/t", "time": (now + timedelta(seconds=stamp_ahead)).isoformat()}))
        q = f"아래 게시를 승인하시겠습니까?\n게시 승인 요청 · page={page} · 알림=notify · 버전 설명=«검토 관문 시험»"
        qs = [{"question": q, "header": "승인", "options": [{"label": "게시 승인", "description": "d"}, {"label": "취소", "description": "d"}]}]
        ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        tid = f"toolu_review_{page}"
        use = {"type": "assistant", "isSidechain": False, "timestamp": ts,
               "message": {"role": "assistant", "content": [{"type": "tool_use", "name": "AskUserQuestion", "id": tid, "input": {"questions": qs}}]}}
        res = {"type": "user", "isSidechain": False, "timestamp": ts,
               "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tid, "content": "ok"}]},
               "toolUseResult": {"questions": qs, "answers": {q: "게시 승인"}, "annotations": {}}}
        with open(self.log, "a", encoding="utf-8") as f:
            f.write(json.dumps(use, ensure_ascii=False) + "\n" + json.dumps(res, ensure_ascii=False) + "\n")
        payload = json.dumps({"tool_name": "mcp__claude_ai_Atlassian__updateConfluencePage", "cwd": str(self.repo),
                              "tool_input": {"pageId": page, "versionMessage": "검토 관문 시험", "contentFormat": "html", "body": body,
                                             **({"title": title} if title is not None else {})}})
        return subprocess.run(["bash", str(HOOK)], input=payload, capture_output=True, text=True, env=self.env, check=False).stdout

    def test_dirty_body_denied_even_with_stamp(self):
        """A stamped and approved body with a credential shape is still denied by the hook."""
        out = self.call(DIRTY, "991001")
        self.assertTrue(is_deny(out))
        self.assertIn("검토 관문", out)

    def test_clean_body_passes(self):
        """A stamped and approved clean body passes."""
        self.assertFalse(is_deny(self.call(CLEAN, "991002")))

    def test_f8_edited_after_review_denied(self):
        """F8 on the live path: only the reviewed body has a stamp, publishing the edited body is denied."""
        out = self.call(EDITED, "991003", stamp_body=CLEAN)
        self.assertTrue(is_deny(out))
        self.assertIn("스탬프", out)

    def test_title_with_credential_denied_even_without_body(self):
        """The title field is scanned too, also when the body is empty."""
        out = self.call("", "991004", title="접속 password = FAKEpw12345")
        self.assertTrue(is_deny(out))
        self.assertIn("1행", out)

    def test_future_stamp_invalid(self):
        """A stamp dated in the future does not count."""
        self.assertTrue(is_deny(self.call(CLEAN, "991005", stamp_ahead=3600)))


if __name__ == "__main__":
    unittest.main()
