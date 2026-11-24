"""Comment rule checker for .py .sh .js files (rules-lazy/coding-conventions.md § 주석 규칙).

Usage:
  python3 -I comment_check.py FILE...                  check whole files
  python3 -I comment_check.py --staged [-- PATHSPEC...]
      read regular index blobs by object id (never the work tree; gitlinks and symlinks are skipped)
      and check only the comment blocks holding a line added by `git diff --cached -U0 --text`
  python3 -I comment_check.py --diff [-- PATHSPEC...]
      same selection for the work tree against HEAD; untracked files are checked whole
  Renames are detected the same way for the file list and the line list, so a pure rename adds no line.
  Other extensions are skipped silently. File names come from git with -z.

Rules:
  A comment block is a run of consecutive full-line comments, or one inline comment. A line that
  starts with a category marker opens a new block, and each js /* */ comment is its own block whose
  first non-empty text line is its first line.
  Each block and every function or class docstring must start with WHY:, NEVER: or REF: followed by
  text. WHY: needs objective evidence: a date, a number, an http address, a file path, an issue or
  equation number. Words that defer work (the EXCUSE pattern below: a few Korean words, "f-o-r n-o-w"
  unless "(" follows directly, minus or plus follows, or "-"/"+" and a digit follow, and the
  upper-case markers T-O-D-O, F-I-X-M-E, H-A-C-K, X-X-X, also before a Korean particle;
  T-O-D-O inside a file name such as docs/T-O-D-O.md is not counted) are violations everywhere,
  including the file head block, the module docstring and machine marker lines. Plain words such
  as temporary or afterwards are allowed. NEVER: must not hedge (the SOFT pattern below).
  Exempt from the marker check: the file head block (the first comment block before the first code
  line, after shebang or PEP 263 coding lines), the module docstring, and machine marker lines that
  start with noqa (end, or ":" and only tool characters A-Z a-z 0-9 _ , . = - space), pragma: (same
  characters), type: ignore (end or "["), shellcheck <directive>=, pylint:, fmt: on|off|skip,
  eslint- or @ts-. A PEP 263 line passes only on line 1-2 in a standard form right after "#"
  (-*- coding: x -*-, coding: x, coding=x, vim: set fileencoding=x).
  A file that cannot be scanned is a violation ([unscannable]); other files are still checked.
  Python falls back from ast to tokenize to a line scan; docstrings are then found from tokens or
  from a triple-quoted line after a def/class line, so comments in broken files are checked.
  Line breaks: CRLF counts as one break; a bare CR also breaks a line (as Python does) and then
  the whole file is checked, because git numbers lines by LF only.

Scope: this is a consistency gate for comments, not a security boundary. Input crafted to fool
the lexer (sh "$(...'..."...')", js ") /`/") can hide the comments of the rest of the file, and a
commit that changes the checker itself runs that changed copy; review covers both. Text past
2,000 characters of a block is not judged. In file mode an unreadable path is a usage error
(exit 2). Moving lines inside a file makes git report them as added, so moved old comments are
checked.

Output: one line per violation "path:line: [code] what: comment(80 chars) -> how to fix". Every
printed line has C0, DEL, C1 and bidi format characters shown as "?". Not masked: U+2028, U+2029,
U+061C, U+200B, U+200D. A leading UTF-8 BOM (U+FEFF) is dropped before judging; line numbers stay.
--staged prints no comment text ("path:line: [code] what -> how to fix"),
because a commented-out credential would be printed again. Then RESULT: PASS, RESULT: FAIL (N건)
or RESULT: ERROR (N건).
Exit: 0 pass, 1 violations, 2 usage error or the checker cannot run (no repository, no git).
Reads files and runs git only (diff with --no-ext-diff --no-textconv); never executes the files.

Limits: sh and js comments come from a small lexer, not a parser.
  sh: `#` is a comment only at the start of a word; quotes, $'..', heredoc bodies, here-strings
      and $(( )) or (( )) arithmetic are skipped. A quote inside $(...) nested in "..." or an
      unusual heredoc delimiter can mislead it.
  js: a `/` starts a regex literal when the previous token is an operator, an opening bracket or a
      keyword such as return; `) /re/` after if(...) is read as division. Backticks inside ${...}
      of a template literal are not tracked.
  WHY: evidence is a pattern match; whether the evidence is true is left to review.
"""

import argparse
import ast
import io
import re
import subprocess
import sys
import tokenize
import warnings
from pathlib import Path

TARGETS = (".py", ".sh", ".js")
LIMIT = 2000
TAG = re.compile(r"(WHY|NEVER|REF):")
MACHINE = re.compile(
    r"(?:noqa(?:$|:[A-Za-z0-9_,.= -]*$)|pragma:[A-Za-z0-9_,.= -]*$|type:\s*ignore(?=$|\[)"
    r"|shellcheck\s+[a-z-]+=|pylint:|fmt:\s*(?:on|off|skip)\b|eslint-|@ts-)",
    re.IGNORECASE,
)
PEP263 = re.compile(
    r"^[ \t\f]*#[ \t]*(?:-\*-[ \t]*coding[:=][ \t]*[-\w.]+[ \t]*-\*-|coding[:=][ \t]*[-\w.]+"
    r"|vim:[ \t]*set[ \t]+fileencoding=[-\w.]+[ \t]*:?)[ \t]*$"
)
EVIDENCE = re.compile(
    r"\d|https?://|[\w.~-]/[\w.~-]*\.[A-Za-z]|/[\w.~-]+/"
    r"|\b[\w-]+\.(?:py|sh|js|ts|md|json|ya?ml|toml|txt|tsv|csv|ini|cfg)\b"
)
EXCUSE = re.compile(
    r"임시로(?!그)|임시\s*(?:조치|방편|코드|주석|처리)|(?<![가-힣])일단(?![락위])|추후|우선은"
    r"|(?i:\bfor\s+now\b)(?!\(|\s*(?:minus|plus)\b|\s*[-+]\s*\d)"
    r"|(?<![/A-Za-z0-9_])TODO(?![A-Za-z0-9_.])|(?<![A-Za-z0-9_])(?:FIXME|HACK|XXX)(?![A-Za-z0-9_])"
)
SOFT = re.compile(
    r"가급적|되도록|웬만하면|\b(?:try to|should probably|if possible)\b", re.IGNORECASE
)
BIDI = "".join(
    map(chr, (0x200E, 0x200F, *range(0x202A, 0x202F), *range(0x2066, 0x206A)))
)
CTRL = re.compile(r"[\x00-\x1f\x7f-\x9f" + BIDI + "]")
TRIPLE = re.compile(r"""^[rRuU]?("{3}|'{3})""")
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", re.MULTILINE)
HEREDOC = re.compile(r"<<(-?)[ \t]*(?:'([^'\n]*)'|\"([^\"\n]*)\"|\\?([A-Za-z_]\w*))")
REGEX_PREV = "(,=:[!&|?{};+-*%<>~^"
REGEX_WORDS = {
    "return",
    "typeof",
    "case",
    "do",
    "else",
    "in",
    "of",
    "new",
    "delete",
    "void",
    "throw",
    "yield",
    "await",
}
WHAT = {
    "no-tag": "범주 표지가 없는 주석",
    "empty-tag": "표지 뒤에 글이 없음",
    "why-evidence": "WHY: 에 객관적 근거가 없음",
    "never-soft": "NEVER: 가 단정형이 아님",
    "excuse": "변명 투",
    "unscannable": "검사하지 못한 파일",
}
FIX = {
    "no-tag": "첫 줄을 WHY: · NEVER: · REF: 가운데 하나로 시작하거나 주석을 지웁니다",
    "empty-tag": "표지 뒤에 근거 · 금지 내용 · 출처를 적거나 주석을 지웁니다",
    "why-evidence": "날짜 · 수치 · 주소 · 파일 경로 · 이슈 번호 · 수식 번호 같은 객관적 근거를 넣습니다",
    "never-soft": "«하지 않는다» 처럼 단정형으로 고칩니다",
    "excuse": "변명 투 낱말을 빼고 근거를 적거나 주석을 지웁니다",
    "unscannable": "파일을 UTF-8 텍스트로 읽히게 고친 뒤 다시 검사합니다",
}


def scan_lines(text):
    comments, code = [], set()
    for ln, line in enumerate(text.split("\n"), 1):
        quote, k = None, 0
        while k < len(line):
            ch = line[k]
            if quote:
                if ch == "\\":
                    k += 1
                elif ch == quote:
                    quote = None
            elif ch in "'\"":
                quote = ch
            elif ch == "#":
                comments.append(
                    (ln, line[k + 1 :], bool(line[:k].strip()), line[k:], None)
                )
                break
            k += 1
        if line[:k].strip():
            code.add(ln)
    return comments, min(code, default=float("inf")), line_docs(text.split("\n"))


def line_docs(lines):
    docs, k = [], 0
    while k < len(lines):
        head = lines[k].strip()
        k += 1
        if not (re.match(r"(?:async\s+)?(?:def|class)\s", head) and head.endswith(":")):
            continue
        while k < len(lines) and not lines[k].strip():
            k += 1
        m = TRIPLE.match(lines[k].strip()) if k < len(lines) else None
        if not m:
            continue
        start, body = k, [lines[k].strip()[m.end() :]]
        while m[1] not in body[-1] and k + 1 < len(lines):
            k += 1
            body.append(lines[k])
        body[-1] = body[-1].split(m[1])[0]
        docs.append(
            (
                start + 1,
                k + 1,
                [(start + 1 + j, t, t) for j, t in enumerate(body)],
                "doc",
            )
        )
        k += 1
    return docs


def token_docs(toks):
    docs, depth, want, after_colon = [], 0, False, None
    sig = [
        t
        for t in toks
        if t.type not in (tokenize.COMMENT, tokenize.NL, tokenize.ENCODING)
    ]
    if sig and sig[0].type == tokenize.STRING:
        docs.append(string_doc(sig[0], "header"))
    for k, tok in enumerate(sig):
        if tok.type == tokenize.NAME and tok.string in ("def", "class"):
            want, depth = True, 0
        elif want and tok.type == tokenize.OP:
            depth += (tok.string in "([{") - (tok.string in ")]}")
            if tok.string == ":" and depth == 0:
                want, after_colon = False, k
        if after_colon is not None and k == after_colon + 1:
            nxt = sig[k : k + 3]
            kinds = [t.type for t in nxt]
            if kinds[:1] == [tokenize.STRING]:
                docs.append(string_doc(nxt[0], "doc"))
            elif kinds == [tokenize.NEWLINE, tokenize.INDENT, tokenize.STRING]:
                docs.append(string_doc(nxt[2], "doc"))
            after_colon = None
    return docs


def string_doc(tok, kind):
    body = re.sub(r"^[A-Za-z]*('''|\"\"\"|'|\")", "", tok.string)
    body = re.sub(r"('''|\"\"\"|'|\")$", "", body)
    lines = [(tok.start[0] + j, t, t) for j, t in enumerate(body.split("\n"))]
    return (tok.start[0], tok.end[0], lines, kind)


def scan_py(text):
    rows, comments, docs = set(), [], []
    skip = {
        tokenize.COMMENT,
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.ENDMARKER,
    }
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except Exception:  # noqa: BLE001
        return scan_lines(text)
    for tok in toks:
        if tok.type == tokenize.COMMENT:
            comments.append((tok.start[0], tok.string[1:], tok.string))
        elif tok.type not in skip:
            rows.update(range(tok.start[0], tok.end[0] + 1))
    marked = [(ln, body, ln in rows, raw, None) for ln, body, raw in comments]
    first_code = min(rows, default=float("inf"))
    # WHY: any ast failure (SyntaxError, MemoryError, SystemError, ...) falls back to token docstrings (2026-11-24 security N1).
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(text)
    except Exception:  # noqa: BLE001
        return marked, first_code, token_docs(toks)
    for node in ast.walk(tree):
        if (
            not isinstance(
                node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            )
            or not node.body
        ):
            continue
        first = node.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            lines = [
                (first.lineno + k, t, t)
                for k, t in enumerate(first.value.value.split("\n"))
            ]
            docs.append(
                (
                    first.lineno,
                    first.end_lineno,
                    lines,
                    "header" if isinstance(node, ast.Module) else "doc",
                )
            )
    return marked, first_code, docs


def scan_sh(text):
    comments, code, pending = [], set(), []
    i, n, line, state = 0, len(text), 1, ""
    while i < n:
        c = text[i]
        if state:
            code.add(line)
            if c == "\\" and state != "'":
                line += text[i + 1 : i + 2] == "\n"
                i += 2
                continue
            if (c == "'" and state in ("'", "$'")) or (c == '"' and state == '"'):
                state = ""
            line += c == "\n"
            i += 1
            continue
        if c == "\n":
            line += 1
            i += 1
            for delim, dash in pending:
                while i < n:
                    j = text.find("\n", i)
                    j = n if j < 0 else j
                    body = text[i:j]
                    code.add(line)
                    line, i = line + 1, j + 1
                    if (body.lstrip("\t") if dash else body) == delim:
                        break
            pending = []
            continue
        if c == "#" and (i == 0 or text[i - 1] in " \t\n;&|()"):
            j = text.find("\n", i)
            j = n if j < 0 else j
            comments.append((line, text[i + 1 : j], line in code, text[i:j], None))
            i = j
            continue
        if text.startswith("<<<", i):
            code.add(line)
            i += 3
            continue
        if text.startswith("<<", i):
            m = HEREDOC.match(text, i)
            if m:
                delim = next(g for g in (m[2], m[3], m[4]) if g is not None)
                pending.append((delim, m[1] == "-"))
                code.add(line)
                i = m.end()
                continue
        if text.startswith("((", i) or text.startswith("$((", i):
            code.add(line)
            i, depth = i + (3 if c == "$" else 2), 2
            while i < n and depth:
                depth += (text[i] == "(") - (text[i] == ")")
                line += text[i] == "\n"
                code.add(line)
                i += 1
            continue
        if c == "\\":
            code.add(line)
            line += text[i + 1 : i + 2] == "\n"
            i += 2
            continue
        if c in "'\"":
            state = c
        elif c == "$" and text.startswith("$'", i):
            state, i = "$'", i + 1
        if not c.isspace():
            code.add(line)
        i += 1
    return comments, min(code, default=float("inf")), []


def starts_regex(text, i):
    k = i - 1
    while k >= 0 and text[k] in " \t\r\n":
        k -= 1
    if k >= 1 and text[k] in "+-" and text[k - 1] == text[k]:
        return False
    if k < 0 or text[k] in REGEX_PREV:
        return True
    j = k
    while j >= 0 and (text[j].isalnum() or text[j] in "_$"):
        j -= 1
    return text[j + 1 : k + 1] in REGEX_WORDS


def scan_js(text):
    comments, code, braces = [], set(), []
    i, n, line, state = 0, len(text), 1, ""
    if text.startswith("#!"):
        i = text.find("\n") if "\n" in text else n
    while i < n:
        c = text[i]
        if state:
            code.add(line)
            if c == "\\":
                line += text[i + 1 : i + 2] == "\n"
                i += 2
                continue
            if state == "`" and text.startswith("${", i):
                braces.append(0)
                state, i = "", i + 2
                continue
            if c == state or (c == "\n" and state != "`"):
                state = ""
            line += c == "\n"
            i += 1
            continue
        if c == "\n":
            line, i = line + 1, i + 1
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            comments.append((line, text[i + 2 : j], line in code, text[i:j], None))
            i = j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            end = n if j < 0 else j + 2
            inline = line in code
            for k, part in enumerate(text[i + 2 : j if j >= 0 else n].split("\n")):
                body = part.strip().lstrip("*").strip()
                raw = ("/*" + part if k == 0 else part).strip()
                comments.append((line + k, body, inline and k == 0, raw, i))
            line += text.count("\n", i, end)
            i = end
            continue
        code.add(line)
        if c == "/" and starts_regex(text, i):
            i, in_class = i + 1, False
            while i < n and text[i] != "\n":
                ch = text[i]
                i += 2 if ch == "\\" else 1
                if ch == "[":
                    in_class = True
                elif ch == "]":
                    in_class = False
                elif ch == "/" and not in_class:
                    break
            continue
        if c in "'\"`":
            state = c
        elif c == "{" and braces:
            braces[-1] += 1
        elif c == "}" and braces:
            if braces[-1] == 0:
                braces.pop()
                state = "`"
            else:
                braces[-1] -= 1
        i += 1
    return comments, min(code, default=float("inf")), []


def group(comments, first_code):
    blocks, cur = [], None
    for ln, body, inline, raw, gid in comments:
        text = body.strip()
        if ln == 1 and raw.startswith("#!"):
            cur = None
            continue
        if (ln <= 2 and PEP263.match(raw)) or MACHINE.match(text):
            blocks.append([ln, ln, [(ln, body, raw)], "machine", gid, True])
            cur = None
            continue
        if (
            cur
            and not inline
            and cur[1] == ln - 1
            and cur[4] == gid
            and not (TAG.match(text) and cur[5])
        ):
            cur[1] = ln
            cur[2].append((ln, body, raw))
            cur[5] = cur[5] or bool(text)
            continue
        cur = [ln, ln, [(ln, body, raw)], "block", gid, bool(text)]
        blocks.append(cur)
        if inline:
            cur = None
    head = next((b for b in blocks if b[3] == "block"), None)
    if head is not None and head[0] < first_code:
        head[3] = "header"
    return [b[:4] for b in blocks]


def excuse_word(text):
    m = EXCUSE.search(text[:LIMIT])
    return m[0] if m else None


def report(path, ln, code, raw, word, quote):
    head = f"{path}:{ln}: [{code}] {WHAT[code]}"
    if not quote:
        return f"{head} → {FIX[code]}"
    snip = raw if len(raw) <= 80 else raw[:80] + "…"
    return f"{head}{f' «{word}»' if word else ''}: {snip} → {FIX[code]}"


def check_blocks(path, blocks, selected, quote):
    out = []
    for first, last, lines, kind in sorted(blocks, key=lambda b: b[0]):
        if selected is not None and selected.isdisjoint(range(first, last + 1)):
            continue
        texts = [(ln, body.strip(), raw.strip()) for ln, body, raw in lines]
        head = next((x for x in texts if x[1]), texts[0])
        joined = " ".join(t for _, t, _ in texts)[:LIMIT]
        tag = TAG.match(head[1])
        if kind in ("block", "doc"):
            rest = TAG.sub("", joined, count=1).strip() if tag else ""
            soft = SOFT.search(rest)
            if not tag:
                out.append(report(path, head[0], "no-tag", head[2], "", quote))
            elif not rest:
                out.append(report(path, head[0], "empty-tag", head[2], "", quote))
            elif tag[1] == "WHY" and not EVIDENCE.search(rest):
                out.append(report(path, head[0], "why-evidence", head[2], "", quote))
            elif tag[1] == "NEVER" and soft:
                out.append(report(path, head[0], "never-soft", head[2], soft[0], quote))
        for ln, t, raw in texts:
            word = excuse_word(t)
            if word:
                out.append(report(path, ln, "excuse", raw, word, quote))
                break
    return out


def check_text(path, text, selected=None, quote=True):
    scan = {".py": scan_py, ".sh": scan_sh, ".js": scan_js}.get(Path(path).suffix)
    if scan is None:
        return []
    text = text.removeprefix(chr(0xFEFF)).replace("\r\n", "\n")
    if "\r" in text:
        text, selected = text.replace("\r", "\n"), None
    # WHY: a scan failure must block instead of passing, and must not stop the other files (2026-11-24 security review D2).
    try:
        comments, first_code, docs = scan(text)
        return check_blocks(path, group(comments, first_code) + docs, selected, quote)
    except Exception as e:  # noqa: BLE001
        return [report(path, 1, "unscannable", type(e).__name__, "", quote)]


def git(args, cwd, data=None):
    r = subprocess.run(
        ["git", *args], check=False, cwd=cwd, input=data, capture_output=True
    )
    if r.returncode:
        raise RuntimeError(
            f"git {args[0]} 실패: {r.stderr.decode('utf-8', 'replace').strip()[:200]}"
        )
    return r.stdout


def split_z(data):
    return [x.decode("utf-8", "surrogateescape") for x in data.split(b"\0") if x]


def repo_root(cwd):
    r = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=False,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return Path(r.stdout.strip()) if r.returncode == 0 else None


def base_rev(root):
    r = subprocess.run(
        ["git", "rev-parse", "--verify", "-q", "HEAD"],
        check=False,
        cwd=root,
        capture_output=True,
    )
    return (
        "HEAD"
        if r.returncode == 0
        else git(["hash-object", "-t", "tree", "--stdin"], root, b"").decode().strip()
    )


def changed_lines(root, rel, staged, old=None):
    if staged:
        diff = ["diff", "--cached"]
    elif old is None and not git(
        ["--literal-pathspecs", "ls-files", "-z", "--", rel], root
    ):
        return None
    else:
        diff = ["diff", base_rev(root)]
    flags = [
        "--find-renames",
        "-U0",
        "--text",
        "--no-color",
        "--no-ext-diff",
        "--no-textconv",
    ]
    out = git(
        ["--literal-pathspecs", *diff, *flags, "--", *([old] if old else []), rel], root
    )
    lines = set()
    for m in HUNK.finditer(out.decode("utf-8", "replace")):
        start = int(m[1])
        lines.update(range(start, start + (int(m[2]) if m[2] is not None else 1)))
    return lines


def changed_files(fields):
    files, k = [], 0
    while k < len(fields):
        if fields[k].startswith("R"):
            files.append((fields[k + 2], fields[k + 1]))
            k += 3
        else:
            files.append((fields[k + 1], None))
            k += 2
    return files


def load(a, errors):
    items = []
    if not (a.staged or a.diff):
        for p in a.paths:
            if Path(p).suffix in TARGETS:
                try:
                    items.append(
                        (p, Path(p).read_bytes().decode("utf-8", "replace"), None)
                    )
                except OSError as e:
                    errors.append(f"{p}: [error] 읽기 실패({e.strerror})")
        return items
    cwd = Path.cwd()
    root = repo_root(cwd)
    if root is None:
        raise RuntimeError("--staged · --diff 는 git 저장소 안에서 씁니다")
    filt = [
        "--name-status",
        "--find-renames",
        "--no-relative",
        "-z",
        "--diff-filter=ACMRT",
        "--",
        *a.paths,
    ]
    if a.staged:
        files = changed_files(split_z(git(["diff", "--cached", *filt], cwd)))
        blobs = {}
        for entry in split_z(git(["ls-files", "-s", "-z"], root)):
            meta, _, path = entry.partition("\t")
            mode, sha, stage = meta.split()
            if stage == "0" and mode in ("100644", "100755"):
                blobs[path] = sha
    else:
        files = changed_files(split_z(git(["diff", base_rev(root), *filt], cwd)))
        others = [
            "ls-files",
            "--others",
            "--exclude-standard",
            "--full-name",
            "-z",
            "--",
            *a.paths,
        ]
        files += [(p, "") for p in split_z(git(others, cwd))]
    for rel, old in files:
        if Path(rel).suffix not in TARGETS:
            continue
        try:
            if a.staged:
                if rel not in blobs:
                    continue
                data = git(["cat-file", "blob", blobs[rel]], root)
            else:
                p = root / rel
                if p.is_symlink() or not p.is_file():
                    continue
                data = p.read_bytes()
            sel = None if old == "" else changed_lines(root, rel, a.staged, old)
            items.append((rel, data.decode("utf-8", "replace"), sel))
        except Exception as e:  # noqa: BLE001
            items.append((rel, None, type(e).__name__))
    return items


def finish(violations, errors, skipped=()):
    for line in violations + errors:
        print(CTRL.sub("?", line))
    note = f", 건너뜀: {', '.join(skipped)}" if skipped else ""
    if violations:
        print(f"RESULT: FAIL ({len(violations)}건{note})")
        return 1
    if errors:
        print(f"RESULT: ERROR ({len(errors)}건{note})")
        return 2
    print(f"RESULT: PASS (건너뜀: {', '.join(skipped)})" if skipped else "RESULT: PASS")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="comment_check.py",
        description="주석 규칙 검사 (rules-lazy/coding-conventions.md § 주석 규칙)",
    )
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument(
        "--staged",
        action="store_true",
        help="index 를 읽고 스테이징된 새 줄이 든 주석만 본다",
    )
    mode.add_argument(
        "--diff",
        action="store_true",
        help="작업 트리를 HEAD 와 비교해 바꾼 줄이 든 주석만 본다",
    )
    ap.add_argument(
        "paths", nargs="*", help="파일(전체 검사) 또는 --staged · --diff 의 pathspec"
    )
    a = ap.parse_args(argv)
    if not (a.staged or a.diff or a.paths):
        ap.error("파일을 주거나 --staged · --diff 를 씁니다")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    violations, errors = [], []
    # WHY: an uncaught exception exits 1, the code reserved for violations; a checker that cannot run must exit 2 (exit contract above).
    try:
        items = load(a, errors)
    except Exception as e:  # noqa: BLE001
        items = []
        errors.append(f"[error] {type(e).__name__}: {e}")
    for display, text, selected in items:
        if text is None:
            violations.append(
                report(display, 1, "unscannable", selected, "", not a.staged)
            )
        else:
            violations += check_text(display, text, selected, not a.staged)
    return finish(violations, errors)


if __name__ == "__main__":
    sys.exit(main())
