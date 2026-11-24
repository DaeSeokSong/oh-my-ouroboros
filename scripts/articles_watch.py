"""공식 글 목록 점검기: claude.com 글 목록의 링크 주소만 뽑아 장부와 비교하고 새 주소를 기록한다.

무엇을: `check` 는 목록 페이지(영문판 `https://claude.com/resources/articles?page=30`)를 받아 링크 주소만
  정규식으로 뽑는다. 대상은 두 종류다. 1) 내부 글 `/resources/articles/<slug>` 2) 허용 host
  (claude.dev · www.anthropic.com · anthropic.com)의 https 외부 글 링크(경로 성분 2개 이상).
  장부 `_usage/articles-watch/ledger.tsv`(탭 구분: url · first_seen · status · note)에 없는 주소를 `new` 로 더한다.
  장부가 없거나 비었으면(첫 실행) 찾은 전부를 `baseline` 으로 넣는다. `list` 는 장부를 보이고 `mark` 는 판정을 적는다.
  종료 코드: 0 성공 · 1 사용 오류 · 3 조회 실패. 마지막 줄은 `RESULT: OK found=N new=M` 또는 `RESULT: FAIL <사유>`.
  실패는 장부를 바꾸지 않고 `last-check.json` 에 ok=false 와 사유로 남겨 세션 시작 경보(ARTICLES_WATCH_FAIL)가 드러낸다.
NEVER: 장부와 상태 파일의 어떤 칸에도 페이지 글자를 넣지 않는다(실패 사유도 고정 코드 문구만 쓴다).
표준 라이브러리만 쓰며 네트워크는 `check` 가 `--html-file` 없이 실행될 때만 쓴다(https · 20초 · 5MB · claude.com 안 리다이렉트만).
REF: knowledge/harness/code-history/scripts__articles_watch.py.md
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import http.client
import json
import os
import re
import signal
import sys
import tempfile
import unicodedata
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE_DIR = ROOT / "_usage" / "articles-watch"
DEFAULT_URL = "https://claude.com/resources/articles?page=30"
BASE_HOST = "claude.com"
EXTERNAL_HOSTS = frozenset({"claude.dev", "www.anthropic.com", "anthropic.com"})
INTERNAL_PREFIX = "https://claude.com/resources/articles/"
HEADER = "url\tfirst_seen\tstatus\tnote"
STATUSES = ("baseline", "new", "reviewed", "skipped")
LEDGER_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)
MIN_INTERNAL = 50  # WHY: 2026-11-24 실측 내부 글 주소 고유 208건의 4분의 1 안팎. 이보다 적으면 페이지 구조 변경으로 본다
MAX_LINKS = 2000
MAX_BYTES = 5 * 1024 * 1024
TIMEOUT = 20
DEADLINE = 45  # NEVER: the shell wrapper's `timeout 60` must never be what kills it (whole check, SIGALRM)
MAX_NOTE = 200
MAX_EXTERNAL_URL = 300
USER_AGENT = "articles-watch/1.0"

HREF_RE = re.compile(r"""href\s*=\s*(?:"([^"]{0,600})"|'([^']{0,600})')""", re.IGNORECASE)
INTERNAL_RE = re.compile(r"(?:https://claude\.com)?/resources/articles/([A-Za-z0-9][A-Za-z0-9_-]{0,199})")
EXTERNAL_PATH_RE = re.compile(r"[A-Za-z0-9._~/%-]{1,300}")  # NEVER: add ; | $ ` ' " < > here (a URL must stay inert even if pasted into a shell)
ERROR_CHARS_RE = re.compile(r"[^A-Za-z0-9 _=<>()-]")  # NEVER: add ':' '/' '.' here (a URL must never survive in an error text)


class WatchFail(Exception):
    def __init__(self, reason: str, found: int = 0) -> None:
        super().__init__(reason)
        self.reason = reason
        self.found = found


class RedirectBlocked(Exception):
    """claude.com 밖으로 가는 리다이렉트."""


class UsageParser(argparse.ArgumentParser):
    def error(self, message: str):
        self.print_usage(sys.stderr)
        print(f"RESULT: FAIL usage: {message}", file=sys.stderr)
        sys.exit(1)


class ClaudeOnlyRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not is_claude_url(newurl, allow_port_443=True):
            raise RedirectBlocked(code)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def is_claude_url(url: str, allow_port_443: bool = False) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    allowed = {BASE_HOST, f"{BASE_HOST}:443"} if allow_port_443 else {BASE_HOST}
    return parts.scheme == "https" and parts.netloc.lower() in allowed


def check_url_arg(url: str) -> str:
    if not url.startswith("https://claude.com/") or not is_claude_url(url):
        raise ValueError("url must start with https://claude.com/")
    return url


def read_capped(resp) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = resp.read(65536)
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > MAX_BYTES:
            raise WatchFail("too_large")
        chunks.append(chunk)


def fetch_html(url: str) -> str:
    opener = urllib.request.build_opener(ClaudeOnlyRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    try:
        with opener.open(req, timeout=TIMEOUT) as resp:
            if resp.status != 200:
                raise WatchFail(f"http_status={resp.status}")
            raw = read_capped(resp)
    except RedirectBlocked:
        raise WatchFail("redirect_blocked") from None
    except urllib.error.HTTPError as exc:
        raise WatchFail(f"http_status={exc.code}") from None
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError):
        raise WatchFail("network_error") from None
    return raw.decode("utf-8", errors="replace")


def load_html_file(path: str) -> str:
    try:
        with open(path, "rb") as fh:
            raw = fh.read(MAX_BYTES + 1)
    except OSError:
        raise WatchFail("html_file_unreadable") from None
    if len(raw) > MAX_BYTES:
        raise WatchFail("too_large")
    return raw.decode("utf-8", errors="replace")


def external_url(href: str) -> str | None:
    try:
        parts = urlsplit(href)
        host = parts.hostname
    except ValueError:
        return None
    if parts.scheme != "https" or host not in EXTERNAL_HOSTS or parts.netloc.lower() != host:
        return None
    if len([seg for seg in parts.path.split("/") if seg]) < 2:
        return None
    url = f"https://{host}{parts.path}"
    return url if EXTERNAL_PATH_RE.fullmatch(parts.path) and len(url) <= MAX_EXTERNAL_URL else None


def is_ledger_url(url: str) -> bool:
    slug = INTERNAL_RE.fullmatch(url)
    if slug:
        return url == INTERNAL_PREFIX + slug.group(1)
    return external_url(url) == url


def extract_links(html: str) -> tuple[list[str], list[str]]:
    internal: dict[str, None] = {}
    external: dict[str, None] = {}
    for match in HREF_RE.finditer(html):
        href = match.group(1) if match.group(1) is not None else match.group(2)
        slug = INTERNAL_RE.fullmatch(href)
        if slug:
            internal[INTERNAL_PREFIX + slug.group(1)] = None
            continue
        ext = external_url(href)
        if ext:
            external[ext] = None
    return list(internal), list(external)


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


@contextlib.contextmanager
def locked(state_dir: Path, blocking: bool):
    state_dir.mkdir(parents=True, exist_ok=True)
    with open(state_dir / ".lock", "a+") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def read_lines(ledger: Path) -> list[str]:
    try:
        with ledger.open("r", encoding="utf-8", errors="replace", newline="") as fh:  # NEVER: split lines on anything but \n (no \r translation, no U+2028 and friends)
            text = fh.read()
    except FileNotFoundError:
        return []
    return [ln.rstrip("\r") for ln in text.split("\n")[1:] if ln.strip()]


def write_ledger(ledger: Path, lines: list[str]) -> None:
    atomic_write(ledger, HEADER + "\n" + "".join(ln + "\n" for ln in lines))


def clean_error(reason: str) -> str:
    return ERROR_CHARS_RE.sub("", reason)[:100]


def write_state(state_dir: Path, ok: bool, found: int, new: int, error: str) -> None:
    # NEVER: change indent=1 to a single-line dump (shell greps last-check.json one key per line)
    body = {"time": datetime.now().astimezone().isoformat(timespec="seconds"), "ok": ok, "found": found,
            "new": new, "error": clean_error(error)}
    atomic_write(state_dir / "last-check.json", json.dumps(body, indent=1, ensure_ascii=True) + "\n")


def raise_deadline(signum, frame) -> None:
    raise WatchFail("deadline_exceeded")


def run_check(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir)
    ledger = Path(args.ledger) if args.ledger else state_dir / "ledger.tsv"
    with locked(state_dir, blocking=False) as got:
        if not got:
            print("RESULT: FAIL busy: another check holds the lock")
            return 3
        found = 0
        reason = ""
        signal.signal(signal.SIGALRM, raise_deadline)
        signal.alarm(DEADLINE)
        try:
            html = load_html_file(args.html_file) if args.html_file else fetch_html(args.url)
            internal, external = extract_links(html)
            found = len(internal) + len(external)
            if len(internal) < MIN_INTERNAL:
                raise WatchFail(f"structure_changed internal={len(internal)}<{MIN_INTERNAL}", found)
            if found > MAX_LINKS:
                raise WatchFail(f"too_many_links found={found}", found)
            lines = read_lines(ledger)
            # NEVER: count a row as known unless its first column is an address this tool could have written (hand edits, forged lines are kept but not known)
            known = {u for u in (ln.split("\t", 1)[0] for ln in lines) if is_ledger_url(u)}
            today = date.today().isoformat()
            baseline = not lines
            status = "baseline" if baseline else "new"
            added = [f"{url}\t{today}\t{status}\t" for url in internal + external if url not in known]
            if added:
                write_ledger(ledger, lines + added)
            new = 0 if baseline else len(added)
            write_state(state_dir, True, found, new, "")
        except WatchFail as exc:
            reason, found = exc.reason, exc.found
        except OSError:
            reason = "ledger_io_error"
        except Exception:  # noqa: BLE001
            reason = "internal_error"
        finally:
            signal.alarm(0)
        if reason:
            with contextlib.suppress(Exception):
                write_state(state_dir, False, found, 0, reason)
            print(f"RESULT: FAIL {clean_error(reason)}")
            return 3
    if baseline:
        print(f"baseline: {len(added)} URLs recorded as baseline")
    print(f"RESULT: OK found={found} new={new}")
    return 0


def run_list(args: argparse.Namespace) -> int:
    ledger = Path(args.ledger) if args.ledger else Path(args.state_dir) / "ledger.tsv"
    if not ledger.is_file():
        print("RESULT: FAIL ledger_missing (장부 없음)", file=sys.stderr)
        return 1
    skipped = 0
    for line in read_lines(ledger):
        fields = line.split("\t")
        # NEVER: echo a ledger row as read. The ledger can be edited outside this tool, so print only the row rebuilt from
        # checked parts (url shape, ISO date, known status, note via clean_note).
        if len(fields) != 4 or not is_ledger_url(fields[0]) or not LEDGER_DATE_RE.fullmatch(fields[1]) or fields[2] not in STATUSES:
            skipped += 1
            continue
        if args.status is None or fields[2] == args.status:
            print("\t".join((fields[0], fields[1], fields[2], clean_note(fields[3]))))
    if skipped:
        print(f"형식 밖 행 {skipped}건 생략", file=sys.stderr)
    return 0


def clean_note(note: str) -> str:
    keep = (ch for ch in note if unicodedata.category(ch)[0] != "C" and unicodedata.category(ch) not in ("Zl", "Zp"))
    return "".join(keep)[:MAX_NOTE]


def run_mark(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir)
    ledger = Path(args.ledger) if args.ledger else state_dir / "ledger.tsv"
    urls = list(args.urls)
    if args.from_file:
        try:
            with open(args.from_file, "rb") as fh:
                raw = fh.read(1024 * 1024 + 1)
        except OSError:
            print("RESULT: FAIL from_file_unreadable", file=sys.stderr)
            return 1
        urls += [ln.strip() for ln in raw.decode("utf-8", errors="replace").split("\n") if ln.strip()]
    if not urls:
        print("RESULT: FAIL usage: no URL given", file=sys.stderr)
        return 1
    if not ledger.is_file():
        print("RESULT: FAIL ledger_missing (장부 없음)", file=sys.stderr)
        return 1
    note = clean_note(args.note) if args.note is not None else None
    wanted = set(urls)
    with locked(state_dir, blocking=True):
        lines = read_lines(ledger)
        index = {ln.split("\t", 1)[0]: i for i, ln in enumerate(lines)}
        missing = [u for u in dict.fromkeys(urls) if u not in index]
        if missing:
            # NEVER: echo back a line without an address shape (e.g. an arbitrary file given to --from-file); only count it
            odd = 0
            for url in missing:
                if is_ledger_url(url):
                    print(f"ERROR not in ledger: {url}", file=sys.stderr)
                else:
                    odd += 1
            if odd:
                print(f"ERROR 주소 꼴 아님: {odd}줄", file=sys.stderr)
            print(f"RESULT: FAIL not_in_ledger={len(missing)}")
            return 1
        for url in wanted:
            fields = lines[index[url]].split("\t")
            fields += [""] * (3 - len(fields))
            old_note = clean_note(" ".join(fields[3:]))
            lines[index[url]] = "\t".join([*fields[:2], args.status, old_note if note is None else note])
        write_ledger(ledger, lines)
    print(f"RESULT: OK marked={len(wanted)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = UsageParser(description="Official articles list watcher (links only, ledger-based)")
    sub = parser.add_subparsers(dest="cmd", required=True, parser_class=UsageParser)
    for name in ("check", "list", "mark"):
        sp = sub.add_parser(name)
        sp.add_argument("--ledger", default=None, help="ledger path (default: <state-dir>/ledger.tsv)")
        sp.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR))
        if name == "check":
            sp.add_argument("--url", default=DEFAULT_URL)
            sp.add_argument("--html-file", default=None)
        elif name == "list":
            sp.add_argument("--status", choices=STATUSES, default=None)
        else:
            sp.add_argument("--status", choices=("reviewed", "skipped"), required=True)
            sp.add_argument("--note", default=None)
            sp.add_argument("--from-file", default=None)
            sp.add_argument("urls", nargs="*")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "check":
        try:
            check_url_arg(args.url)
        except ValueError as exc:
            parser.error(str(exc))
        return run_check(args)
    if args.cmd == "list":
        return run_list(args)
    return run_mark(args)


if __name__ == "__main__":
    sys.exit(main())
