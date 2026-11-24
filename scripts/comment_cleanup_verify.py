"""Check that only comments changed: the code of each file equals its copy at a base commit.

Usage: python3 -I scripts/comment_cleanup_verify.py [--base REV] [--not-self-read PATH]...
         [--no-parse PATH]... FILE...
  REV defaults to HEAD. The base copy is read with `git cat-file blob REV:PATH` (no diff driver,
  no textconv); the work tree copy is read from disk.
  All: if either first line starts with "#!", the two first lines must match byte for byte
       ([shebang]).
  .py: ast.dump without line numbers must match after dropping docstrings (first string statement
       of a module, def, async def or class); a body left empty or holding only `pass` counts as
       empty. A side that does not parse is [unparsed], unless both sides fail and the bytes match.
       Then the code lines must match as text, spaces included ([format]): comment tokens and the
       docstring statements (with a following ";") and the `pass` counted as empty above are cut,
       trailing whitespace is dropped and empty lines are skipped. If tokenize fails, a note only.
       [doc-used]: if the work tree file reads x.__doc__ or a bare __doc__ in a class body, every
       docstring must equal the base; a bare __doc__ elsewhere (description=__doc__ in main())
       reads the module docstring, so only that one must match.
  .sh .js: comments found by comment_check.scan_sh / scan_js are removed, then trailing whitespace
       and empty lines are dropped and the lines must match ([code]); an empty line after a line
       ending in a backslash is kept. A /* */ comment inside a line counts as one space.
       sh: bash -n on both sides ([syntax]; a note only when the base failed too). Then
       `bash --pretty-print` on stdin (parses and prints the commands, runs nothing; 30 s limit)
       compares two pairs ([parse]): the raw texts with empty output lines dropped, and texts
       with comment lines, inline comments and top-level empty lines removed, compared whole so
       empty lines inside here-documents and quotes count. Indentation is normalized by bash, so
       [code] alone catches it. If pretty-print fails on a side, times out or bash lacks the
       option, only a note is printed. --no-parse PATH (repeatable, PATH must be one of FILE,
       else exit 2) turns off [parse] for that file, and its result lines carry "(파서 비교 끔)";
       bash prints comments inside $(...) as they are, so deleting them fails [parse]. Use it
       only after main has read that file's `git diff` and confirmed only comments changed.
       A file with $0,
       ${0} or BASH_SOURCE on a line with sed, grep, awk, head, tail or cat must keep every line
       before its first code line byte for byte ([self-read]). --not-self-read PATH (repeatable,
       PATH must be one of FILE, else exit 2) turns off only this check for that file, and its
       result lines carry "(자기 읽기 검사 끔)". Use it only after main has read the matched lines
       of that file and confirmed they do not print the file's own head.
       js: node --check on the work tree file when node exists ([syntax]).
  The executable bit of the work tree file must match the mode at REV ([mode]).
  Other extensions, files missing at REV, symlinks and deleted files are [skip] and do not fail.
Output: "path: OK" or "path: [code] what differs" (line numbers and kinds, never code text), then
"검사 N개 · OK a · 실패 b · 건너뜀 c" (all [skip] still passes, so compare the OK count), then
RESULT: PASS or RESULT: FAIL (N건). Control characters are printed as "?".
Exit: 0 pass, 1 differences, 2 usage error or not a git repository.
Never modifies or executes the files (bash -n, bash --pretty-print and node --check only parse).

Limits:
  py: [format] compares each code line's text, so spaces, parentheses, quote style and literal
      spelling inside a line are caught. Not caught: trailing whitespace, empty lines and line
      ending (CR) changes. Code that reads docstrings without the name __doc__ in the same
      file (help(), inspect, doctest, CLI frameworks, getattr(x, "__doc__"),
      globals()["__doc__"]) or reads its own text through __file__ is not detected.
  sh js: the lexer of comment_check.py is not a parser; text it misreads as a comment is not
      compared by [code]. For sh, [parse] compares bash's own parse, but only when pretty-print
      succeeds on both sides (a note says when it does not). js has no such second check, and a
      regex after ")" read as division can hide text. Trailing whitespace and line ending (CR)
      changes are not detected by [code]; js and --no-parse files also miss empty line changes
      inside strings.
  Behavior that depends on line numbers (tracebacks, sed -n 'N,Mp', LINENO) is not compared.
  The self-read rule is a line pattern: awk's own $0 also matches, and a script that reads its
  text past the head, through read < "$0", mapfile, cut, other tools or $0 kept in a variable is
  not detected. Other files that search a comment's text are not detected.
"""

import argparse
import ast
import importlib.util
import io
import os
import re
import shutil
import stat
import subprocess
import sys
import tokenize
import warnings
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "comment_check", Path(__file__).resolve().with_name("comment_check.py")
)
cc = importlib.util.module_from_spec(_spec)
sys.modules["comment_check"] = cc
_spec.loader.exec_module(cc)

DEFS = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
SELF = re.compile(r"\$0|\$\{0\}|BASH_SOURCE")
READERS = re.compile(r"\b(?:sed|grep|awk|head|tail|cat)\b")
# WHY: BASH_ENV, ENV and NODE_OPTIONS make bash -n / node --check load other code (bash(1) INVOCATION, node --require).
ENV = {
    k: v for k, v in os.environ.items() if k not in ("BASH_ENV", "ENV", "NODE_OPTIONS")
}


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, check=False)


def py_view(data):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(data)
        docs, spans = [], []
        for node in list(ast.walk(tree)):
            if not isinstance(node, DEFS):
                continue
            body, doc, line = node.body, None, getattr(node, "lineno", 1)
            first = body[0] if body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                doc, line, body = first.value.value, first.lineno, body[1:]
                spans.append(first)
            if len(body) == 1 and isinstance(body[0], ast.Pass):
                spans.append(body[0])
                body = []
            node.body = body
            docs.append((getattr(node, "name", "<module>"), line, doc))
        names = {
            n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == "__doc__"
        }
        # WHY: a bare __doc__ means the class docstring only in class scope; in a function it is the module's (Python reference 4.2.2).
        todo = [
            s for c in ast.walk(tree) if isinstance(c, ast.ClassDef) for s in c.body
        ]
        inner = False
        while todo and not inner:
            n = todo.pop()
            inner = n in names
            if not isinstance(n, (*DEFS[1:], ast.Lambda)):
                todo.extend(ast.iter_child_nodes(n))
        attr = any(
            isinstance(n, ast.Attribute) and n.attr == "__doc__" for n in ast.walk(tree)
        )
        scope = "all" if attr or inner else "module" if names else None
        spans = [
            (s.lineno, s.col_offset, s.end_lineno, s.end_col_offset) for s in spans
        ]
        return tree, ast.dump(tree), docs, scope, spans
    except Exception:  # noqa: BLE001
        return None


def code_text(data, spans):
    text = data.decode("utf-8", "surrogateescape").removeprefix("﻿")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cut = [[] for _ in lines]
    for tok in tokenize.generate_tokens(io.StringIO("\n".join(lines)).readline):
        if tok.type == tokenize.COMMENT:
            cut[tok.start[0] - 1].append((tok.start[1], len(lines[tok.start[0] - 1])))

    def col(row, offset):
        raw = lines[row - 1].encode("utf-8", "surrogateescape")[:offset]
        return len(raw.decode("utf-8", "surrogateescape"))

    for row, c, end_row, end_c in spans:
        c, end_c = col(row, c), col(end_row, end_c)
        semi = re.match(r"[ \t]*;[ \t]*", lines[end_row - 1][end_c:])
        end_c += semi.end() if semi else 0
        for r in range(row, end_row + 1):
            cut[r - 1].append(
                (c if r == row else 0, end_c if r == end_row else len(lines[r - 1]))
            )
    out = []
    for n, line in enumerate(lines):
        for s, e in sorted(cut[n], reverse=True):
            line = line[:s] + line[e:]
        if line.strip():
            out.append((n + 1, line.rstrip()))
    return out


def first_diff(a, b, where):
    if isinstance(b, ast.AST) and hasattr(b, "lineno"):
        where = (b.lineno, type(b).__name__)
    if type(a) is not type(b):
        return where
    if isinstance(a, ast.AST):
        for f in a._fields:
            r = first_diff(getattr(a, f, None), getattr(b, f, None), where)
            if r:
                return r
        return None
    if isinstance(a, list):
        for x, y in zip(a, b):
            r = first_diff(x, y, where)
            if r:
                return r
        return where if len(a) != len(b) else None
    return where if a != b else None


def check_py(old, new, notes):
    a, b = py_view(old), py_view(new)
    if a is None or b is None:
        if a is None and b is None:
            return (
                [] if old == new else ["[unparsed] 양쪽 다 파싱되지 않고 바이트가 다름"]
            )
        return [f"[unparsed] {'작업 트리' if b is None else 'base'} 쪽을 파싱하지 못함"]
    if a[1] != b[1]:
        try:
            line, kind = first_diff(a[0], b[0], (1, "Module")) or (0, "?")
        except RecursionError:
            line, kind = 0, "?"
        return [f"[code] 코드가 다름: 작업 트리 줄 {line} 근처 ({kind})"]
    fails = []
    try:
        x, y = code_text(old, a[4]), code_text(new, b[4])
    except Exception as e:  # noqa: BLE001
        x = y = None
        notes.add(f"[format] 검사 못 함(토큰화 실패: {type(e).__name__})")
    if x is not None and [u[1] for u in x] != [v[1] for v in y]:
        k = next((i for i, (u, v) in enumerate(zip(x, y)) if u[1] != v[1]), None)
        k = min(len(x), len(y)) if k is None else k
        rows = [str(s[k][0]) if k < len(s) else "끝" for s in (x, y)]
        fails.append(
            f"[format] 코드 줄의 글(공백 포함)이 다름: base 줄 {rows[0]} · 작업 트리 줄 {rows[1]}"
        )
    pairs = zip(b[2], a[2]) if b[3] == "all" else zip(b[2][:1], a[2][:1])
    changed = [f"{n}:{ln}" for (n, ln, u), (_, _, v) in pairs if b[3] and u != v]
    if changed:
        fails.append(
            f"[doc-used] __doc__ 를 읽는 파일의 docstring 이 바뀜: {', '.join(changed)}"
        )
    return fails


def code_lines(text, scan):
    lines = text.split("\n")
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line) + 1)
    spans = {}
    for ln, _body, _inline, raw, gid in scan(text)[0]:
        if gid is None:
            line = lines[ln - 1]
            if not line.endswith(raw):
                raise ValueError(ln)
            end = starts[ln - 1] + len(line)
            spans[end - len(raw)] = (end, "")
            continue
        if gid in spans:
            continue
        if not text.startswith("/*", gid):
            raise ValueError(ln)
        j = text.find("*/", gid + 2)
        end = len(text) if j < 0 else j + 2
        if "\n" in text[gid:end]:
            spans[gid] = (end, "\n" * text.count("\n", gid, end))
            continue
        s, e = gid, end
        while s > 0 and text[s - 1] in " \t":
            s -= 1
        while e < len(text) and text[e] in " \t":
            e += 1
        if s == 0 or text[s - 1] == "\n":
            spans[gid] = (e, "")
        elif e == len(text) or text[e] == "\n":
            spans[s] = (e, "")
        else:
            spans[s] = (e, " ")
    out, k = [], 0
    for s in sorted(spans):
        if s < k:
            raise ValueError(s)
        out += [text[k:s], spans[s][1]]
        k = spans[s][0]
    out.append(text[k:])
    stripped = "".join(out).split("\n")
    kept = []
    for n, line in enumerate(stripped):
        s = line.rstrip()
        if s.endswith("\\") and s != line:
            s = line
        if s or (n and stripped[n - 1].endswith("\\")):
            kept.append((n + 1, s))
    return kept


def head_lines(text):
    out = []
    for line in text.split("\n"):
        if line.strip() and not line.lstrip().startswith("#"):
            break
        out.append(line)
    return out


def shebang(old, new):
    a, b = (d.split(b"\n", 1)[0] for d in (old, new))
    if (a.startswith(b"#!") or b.startswith(b"#!")) and a != b:
        return ["[shebang] shebang 줄이 다름"]
    return []


def parse_text(text):
    lines = text.split("\n")
    # WHY: an empty line turned into "#" is a comment only outside here-documents and quotes, so only top-level empty lines drop (qa probes sh01-sh02c, 2026-11-24).
    probe = ["#" if not line.strip() else line for line in lines]
    cut = {}
    for ln, _body, _inline, raw, _gid in cc.scan_sh("\n".join(probe))[0]:
        if not probe[ln - 1].endswith(raw):
            raise ValueError(ln)
        cut[ln - 1] = len(probe[ln - 1]) - len(raw)
    out = []
    for n, line in enumerate(lines):
        if n in cut:
            line = line[: cut[n]] if line.strip() else ""
            if not line.strip():
                continue
        out.append(line)
    return "\n".join(out).encode("utf-8", "surrogateescape")


def check_text_code(old, new, scan):
    fails = []
    ot, nt = (d.decode("utf-8", "surrogateescape") for d in (old, new))
    try:
        a, b = code_lines(ot, scan), code_lines(nt, scan)
    except Exception as e:  # noqa: BLE001
        return fails + [f"[unscannable] 주석 위치를 찾지 못함({type(e).__name__})"]
    for x, y in zip(a, b):
        if x[1] != y[1]:
            fails.append(
                f"[code] 주석 밖 줄이 다름: base 줄 {x[0]} · 작업 트리 줄 {y[0]}"
            )
            break
    else:
        if len(a) != len(b):
            k = min(len(a), len(b))
            side, rows = ("작업 트리", b) if len(b) > len(a) else ("base", a)
            fails.append(
                f"[code] {side} 에만 코드 줄이 더 있음: {side} 줄 {rows[k][0]}"
            )
    return fails


def bash_n(data):
    r = subprocess.run(
        ["bash", "-n"], input=data, capture_output=True, check=False, env=ENV
    )
    return r.returncode == 0


def check_sh(old, new, notes, self_read, parse):
    fails = check_text_code(old, new, cc.scan_sh)
    ot, nt = (d.decode("utf-8", "surrogateescape") for d in (old, new))
    if not self_read:
        notes.add("자기 읽기 검사 끔")
    if not parse:
        notes.add("파서 비교 끔")
    hits = [
        n
        for n, line in enumerate(nt.split("\n"), 1)
        if SELF.search(line) and READERS.search(line)
    ]
    hits = self_read and (
        hits
        or [
            n
            for n, line in enumerate(ot.split("\n"), 1)
            if SELF.search(line) and READERS.search(line)
        ]
    )
    if hits:
        a, b = head_lines(ot), head_lines(nt)
        if a != b:
            k = next(
                (i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b))
            )
            fails.append(
                f"[self-read] 줄 {hits[0]} 에서 자기 글을 읽는 파일의 머리가 바뀜: 줄 {k + 1}"
            )
    if shutil.which("bash") is None:
        notes.add("bash 없음: bash -n · --pretty-print 를 건너뜁니다")
        return fails
    if not bash_n(new):
        if bash_n(old):
            fails.append("[syntax] 작업 트리 쪽이 bash -n 을 통과하지 못함")
        else:
            notes.add("base 도 bash -n 을 통과하지 못하던 파일")
    if not parse:
        return fails
    try:
        stripped = parse_text(ot), parse_text(nt)
    except Exception as e:  # noqa: BLE001
        stripped = None
        notes.add(f"주석을 뺀 글을 만들지 못함({type(e).__name__})")
    # WHY: on stdin bash 5.1.16 prints one empty line per comment line (measured 2026-11-24), so the raw-text pass drops empty lines.
    pairs = [("원문, 빈 줄 제외", old, new, True)]
    if stripped:
        pairs.append(("주석을 뺀 글", *stripped, False))
    for label, x, y, drop in pairs:
        (pa, ea), (pb, eb) = pretty(x), pretty(y)
        if pa is None or pb is None:
            why = " · ".join(
                f"{s} {e}" for s, e in (("base", ea), ("작업 트리", eb)) if e
            )
            notes.add(f"bash --pretty-print 비교 못 함({label}: {why})")
            continue
        pa, pb = (
            [z for z in p.split(b"\n") if z.strip() or not drop] for p in (pa, pb)
        )
        if pa != pb:
            k = next(
                (i for i, (u, v) in enumerate(zip(pa, pb)) if u != v),
                min(len(pa), len(pb)),
            )
            fails.append(
                f"[parse] bash 파싱 결과가 다름({label}): pretty-print 출력의 {k + 1}번째 줄"
            )
            break
    return fails


def pretty(data):
    try:
        r = subprocess.run(
            ["bash", "--pretty-print"],
            input=data,
            capture_output=True,
            check=False,
            env=ENV,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return None, "시간 초과"
    if r.returncode:
        known = b"invalid option" not in r.stderr
        return None, f"종료 코드 {r.returncode}" if known else "옵션을 모름"
    return r.stdout, ""


def check_js(old, new, path):
    fails = check_text_code(old, new, cc.scan_js)
    node = shutil.which("node")
    if (
        node
        and subprocess.run(
            [node, "--check", str(path)], capture_output=True, check=False, env=ENV
        ).returncode
    ):
        fails.append("[syntax] 작업 트리 쪽이 node --check 를 통과하지 못함")
    return fails


def check_file(root, base, rel, notes, self_read, parse):
    suffix = Path(rel).suffix
    path = root / rel
    if suffix not in cc.TARGETS:
        return ["[skip] 검사하는 확장자(.py .sh .js)가 아님"], "skip"
    if path.is_symlink():
        return ["[skip] 심볼릭 링크"], "skip"
    if not path.is_file():
        return ["[skip] 작업 트리에 없는 파일(삭제됨)"], "skip"
    r = git(root, "cat-file", "blob", f"{base}:{rel}")
    if r.returncode:
        return ["[skip] base 에 없는 새 파일"], "skip"
    old, new, own = r.stdout, path.read_bytes(), set()
    fails = shebang(old, new)
    if suffix == ".py":
        fails += check_py(old, new, own)
    elif suffix == ".sh":
        fails += check_sh(old, new, own, self_read, parse)
    else:
        fails += check_js(old, new, path)
        if shutil.which("node") is None:
            notes.add("node 없음: node --check 를 건너뜁니다")
    entry = git(root, "--literal-pathspecs", "ls-tree", "-z", base, "--", rel).stdout
    mode = entry.split(b" ", 1)[0].decode()
    work = path.stat().st_mode
    if (mode == "100755") != bool(work & stat.S_IXUSR):
        fails.append(
            f"[mode] 실행 비트가 base 와 다름(base {mode} · 작업 트리 {stat.filemode(work)})"
        )
    if fails:
        mark = "".join(
            f" ({m})" for m in ("자기 읽기 검사 끔", "파서 비교 끔") if m in own
        )
        return [f + mark for f in fails], "fail"
    return [f"OK ({' · '.join(sorted(own))})" if own else "OK"], "ok"


def resolve(root, p):
    absolute = Path(p).absolute()
    real = absolute.parent.resolve() / absolute.name
    if not real.is_relative_to(root.resolve()):
        return None
    return real.relative_to(root.resolve()).as_posix()


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="comment_cleanup_verify.py",
        description="주석만 바뀌고 코드는 그대로인지 base 커밋과 비교한다(읽기 전용)",
    )
    ap.add_argument("--base", default="HEAD", help="비교할 커밋(기본 HEAD)")
    ap.add_argument(
        "--not-self-read",
        action="append",
        default=[],
        metavar="PATH",
        help="[self-read] 검사를 끌 파일(FILE 목록 안의 것, 여러 번 줄 수 있음)",
    )
    ap.add_argument(
        "--no-parse",
        action="append",
        default=[],
        metavar="PATH",
        help="[parse] 비교를 끌 sh 파일(FILE 목록 안의 것, 여러 번 줄 수 있음)",
    )
    ap.add_argument("files", nargs="+")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    root = cc.repo_root(Path.cwd())
    if root is None:
        print("[error] git 저장소 안에서 씁니다")
        return 2
    r = (
        None
        if a.base.startswith("-")
        else git(root, "rev-parse", "--verify", "-q", a.base + "^{commit}")
    )
    if r is None or r.returncode:
        print(cc.CTRL.sub("?", f"[error] base 커밋을 찾지 못함: {a.base}"))
        return 2
    base = r.stdout.decode().strip()
    rels = [(p, resolve(root, p)) for p in a.files]
    for p, rel in rels:
        if rel is None:
            print(cc.CTRL.sub("?", f"{p}: [error] 저장소 밖의 경로"))
            return 2
    off = {}
    for flag, given in (
        ("--not-self-read", a.not_self_read),
        ("--no-parse", a.no_parse),
    ):
        off[flag] = {resolve(root, p) for p in given}
        for p in given:
            if resolve(root, p) not in {rel for _, rel in rels}:
                print(cc.CTRL.sub("?", f"{p}: [error] {flag} 경로가 FILE 목록에 없음"))
                return 2
    total, notes, count = 0, set(), {"ok": 0, "fail": 0, "skip": 0}
    for display, rel in rels:
        lines, status = check_file(
            root,
            base,
            rel,
            notes,
            rel not in off["--not-self-read"],
            rel not in off["--no-parse"],
        )
        count[status] += 1
        if status == "fail":
            total += len(lines)
        for line in lines:
            print(cc.CTRL.sub("?", f"{display}: {line}"))
    for note in sorted(notes):
        print(f"알림: {note}")
    print(
        f"검사 {len(rels)}개 · OK {count['ok']} · 실패 {count['fail']} · 건너뜀 {count['skip']}"
    )
    print(f"RESULT: FAIL ({total}건)" if total else "RESULT: PASS")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
