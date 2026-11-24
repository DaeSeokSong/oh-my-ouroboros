"""Tests for scripts/comment_cleanup_verify.py (intent/2026-11-24-comment-bulk-cleanup.md, bundle 0).

Run: uv run --no-project --with pytest python -m pytest scripts/tests/test_comment_cleanup_verify.py -q -p no:cacheprovider
Each case builds a throwaway repository under pytest tmp_path with global and system git config disabled.
"""

import ast
import importlib.util
import io
import os
import subprocess
import sys
import tokenize
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
TOOL = SCRIPTS / "comment_cleanup_verify.py"
_spec = importlib.util.spec_from_file_location("comment_cleanup_verify", TOOL)
ccv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ccv)
ENV = dict(
    os.environ,
    GIT_CONFIG_GLOBAL="/dev/null",
    GIT_CONFIG_SYSTEM="/dev/null",
    GIT_AUTHOR_NAME="t",
    GIT_AUTHOR_EMAIL="t@t",
    GIT_COMMITTER_NAME="t",
    GIT_COMMITTER_EMAIL="t@t",
)

PY = '''"""Module contract."""

import os

LIMIT = 3  # inline note


def f(x):
    """Function doc."""
    # full line note
    if x > LIMIT:
        y = x + 1
        return "a # b"
    return os.sep


class A:
    """Class doc."""

    v = 2
'''

SH = """#!/usr/bin/env bash
# head note
set -euo pipefail
X=1 # inline note
# body note
cat <<EOF
# inside heredoc
EOF
echo "a # b" $X
"""

JS = """#!/usr/bin/env node
// head note
const a = 1 // inline
/* block
   note */
const t = `x // y`
function g() { try { return a } catch { /* keep */ } }
module.exports = { a, t, g }
"""


def git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, env=ENV
    )


def make_repo(tmp_path, files):
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-q")
    for name, body in files.items():
        (repo / name).write_text(body, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    return repo


def run(cwd, *args):
    r = subprocess.run(
        [sys.executable, "-I", str(TOOL), *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        env=ENV,
    )
    return r.returncode, r.stdout + r.stderr


def verify(tmp_path, name, base, work):
    repo = make_repo(tmp_path, {name: base})
    (repo / name).write_text(work, encoding="utf-8")
    return run(repo, name)


@pytest.mark.parametrize(
    ("name", "base", "work"),
    [
        (
            "a.py",
            PY,
            PY.replace("  # inline note", "").replace("    # full line note\n", ""),
        ),
        ("a.py", PY, PY.replace("# full line note", "# WHY: 2026-11-24 note")),
        (
            "a.sh",
            SH,
            SH.replace(" # inline note", "  ").replace("# body note\n", "\n\n"),
        ),
        ("a.sh", SH, SH.replace("# head note", "# REF: other")),
        (
            "a.js",
            JS,
            JS.replace(" // inline", "").replace("/* block\n   note */\n", ""),
        ),
        ("a.js", JS, JS.replace("{ /* keep */ }", "{ }")),
    ],
)
def test_comment_only_change_passes(tmp_path, name, base, work):
    code, out = verify(tmp_path, name, base, work)
    assert (code, out.splitlines()[-1]) == (0, "RESULT: PASS"), out
    assert f"{name}: OK" in out


@pytest.mark.parametrize(
    ("name", "old", "new"),
    [
        ("a.py", "y = x + 1", "y = x + 2"),
        ("a.py", "LIMIT = 3", "LIMIT = 4"),
        ("a.py", '"a # b"', '"a # c"'),
        ("a.py", "x > LIMIT", "x >= LIMIT"),
        ("a.py", '        return "a # b"', '    return "a # b"'),
        ("a.py", "import os\n", "import os\nimport re\n"),
        ("a.sh", "set -euo pipefail\nX=1", "X=1\nset -euo pipefail"),
        ("a.sh", 'echo "a # b"', 'echo "a # c"'),
        ("a.sh", "X=1 #", "X=2 #"),
        ("a.sh", "# inside heredoc", "# inside heredoc changed"),
        ("a.sh", "echo ", "  echo "),
        ("a.js", "`x // y`", "`x // z`"),
        ("a.js", "const a = 1", "const a = 2"),
    ],
)
def test_code_change_fails(tmp_path, name, old, new):
    base = {"a.py": PY, "a.sh": SH, "a.js": JS}[name]
    assert old in base
    code, out = verify(tmp_path, name, base, base.replace(old, new, 1))
    assert code == 1, out
    assert f"{name}: [code]" in out
    parse = name == "a.sh" and old != "echo "
    assert out.splitlines()[-1] == f"RESULT: FAIL ({1 + parse}건)", out
    assert (f"{name}: [parse]" in out) == parse


def test_py_line_swap_fails(tmp_path):
    base = "a = 1\nb = 2\n"
    code, out = verify(tmp_path, "a.py", base, "b = 2\na = 1\n")
    assert code == 1 and "a.py: [code] 코드가 다름: 작업 트리 줄 1" in out


@pytest.mark.parametrize(
    "work",
    [
        PY.replace('    """Function doc."""\n', ""),
        PY.replace('"""Module contract."""\n\n', ""),
        PY.replace("Class doc.", "Changed doc."),
        PY.replace("    v = 2\n", '    """Added doc."""\n\n    v = 2\n').replace(
            '    """Class doc."""\n\n', ""
        ),
        PY.replace("def f(x):\n", 'def f(x):\n    """New."""\n').replace(
            '    """Function doc."""\n', ""
        ),
    ],
)
def test_docstring_delete_change_add_passes(tmp_path, work):
    code, out = verify(tmp_path, "a.py", PY, work)
    assert code == 0, out


def test_docstring_only_body_becomes_pass(tmp_path):
    code, out = verify(
        tmp_path,
        "a.py",
        'def f():\n    """Doc."""\n',
        "def f():\n    pass\n",
    )
    assert code == 0, out


def test_doc_used_file_docstring_change_fails(tmp_path):
    base = PY + "\nprint(__doc__)\n"
    code, out = verify(tmp_path, "a.py", base, base.replace("Module contract.", "New."))
    assert code == 1 and "a.py: [doc-used]" in out and "<module>:1" in out
    code, out = verify(tmp_path / "b", "a.py", base, base.replace("Function doc.", "x"))
    assert code == 0, out


@pytest.mark.parametrize(
    ("use", "frozen"),
    [
        ("def main():\n    print(__doc__)\n", False),
        ("print(f.__doc__)\n", True),
        ("class B:\n    t = __doc__\n", True),
        ("class B:\n    def m(self):\n        return __doc__\n", False),
    ],
)
def test_doc_used_scope(tmp_path, use, frozen):
    base = PY + "\n\n" + use
    code, out = verify(tmp_path, "a.py", base, base.replace("Function doc.", "x"))
    assert (code == 1) == frozen and ("a.py: [doc-used]" in out) == frozen, out
    code, out = verify(
        tmp_path / "m", "a.py", base, base.replace("Module contract.", "N.")
    )
    assert code == 1 and "<module>:1" in out, out


def test_doc_used_module_only_with_real_wandb_style_main(tmp_path):
    base = (
        '"""Tool help."""\n\nimport argparse\n\n\ndef helper():\n    """Inner doc."""\n'
        "    return 1\n\n\ndef main():\n    argparse.ArgumentParser(description=__doc__)\n"
    )
    work = base.replace('    """Inner doc."""\n', "")
    code, out = verify(tmp_path, "a.py", base, work)
    assert code == 0, out
    code, out = verify(tmp_path / "b", "a.py", base, work.replace("Tool help.", "T."))
    assert code == 1 and "[doc-used]" in out and "<module>:1" in out


@pytest.mark.parametrize(
    ("base", "work", "ok"),
    [
        ("h = hashlib.sha256()  # note\n", "h =hashlib.sha256()\n", False),
        ("h = f(a,b)\n# c\n", "h = f(a, b)\n", False),
        ("x = 'a'\n", 'x = "a"\n', False),
        ("x = (1)\n", "x = 1\n", False),
        ("x = 1_000\n", "x = 1000\n", False),
        ("x = 1  # c\n# full\ny = 2\n", "x = 1\ny = 2\n", True),
        ("x = 1#c\n", "x = 1\n", True),
        (
            's = """a\n  # not comment\nb"""\n',
            's = """a\n  # not comment\nb"""\n',
            True,
        ),
        ('s = ("""a\nb""")  # c\n', 's = """a\nb"""\n', False),
        ("x = 1 + \\\n    2  # c\n", "x = 1 + \\\n    2\n", True),
        ("x = 1 + \\\n    2\n", "x = 1 + \\\n  2\n", False),
        ('def f(): "d"; return 1\n', "def f(): return 1\n", True),
        ('def f():\n    "d"; return 1\n', "def f():\n    return 1\n", True),
        (
            'def f():\n    """a\n    b"""\n    return 1\n',
            "def f():\n    return 1\n",
            True,
        ),
        ('def f():\n    """d"""\n', "def f():\n    pass\n", True),
        ('class A:\n    """d"""\n    pass\n', "class A:\n    pass\n", True),
        ("if x:\n\ty = 1  # c\n", "if x:\n\ty = 1\n", True),
        ("if x:\n\ty = 1\n", "if x:\n    y = 1\n", False),
    ],
)
def test_format(tmp_path, base, work, ok):
    code, out = verify(tmp_path, "a.py", base, work)
    assert (code == 0) == ok, out
    assert ("a.py: [format] 코드 줄의 글(공백 포함)이 다름: base 줄 " in out) != ok, out


def test_format_real_file_space_removed(tmp_path):
    base = (SCRIPTS.parent / "tools/eval-pipeline/eval_pipeline.py").read_text(
        encoding="utf-8"
    )
    assert "h = hashlib.sha256()" in base
    code, out = verify(
        tmp_path,
        "e.py",
        base,
        base.replace("h = hashlib.sha256()", "h =hashlib.sha256()"),
    )
    assert code == 1 and "e.py: [format]" in out and "[code]" not in out, out


def test_format_tokenize_failure_is_note(tmp_path, monkeypatch):
    def broken(*_a):
        raise tokenize.TokenError("x")

    monkeypatch.setattr(ccv.tokenize, "generate_tokens", broken)
    notes = set()
    assert ccv.check_py(b"x = 1  # c\n", b"x =1\n", notes) == []
    assert notes == {"[format] 검사 못 함(토큰화 실패: TokenError)"}


def test_doc_used_attribute_and_comment_change(tmp_path):
    base = 'def f():\n    """Doc."""\n\n\nprint(f.__doc__)  # note\n'
    code, out = verify(tmp_path, "a.py", base, base.replace("  # note", ""))
    assert code == 0, out
    code, out = verify(tmp_path / "b", "a.py", base, base.replace("Doc.", "D."))
    assert code == 1 and "[doc-used]" in out and "f:2" in out


SELF_SH = """#!/usr/bin/env bash
# Usage: x.sh [arg]
#   prints this help
usage() { sed -n '2,3p' "$0"; }
usage
"""


def test_self_read_head_change_fails(tmp_path):
    code, out = verify(tmp_path, "x.sh", SELF_SH, SELF_SH.replace("prints", "shows"))
    assert code == 1 and "x.sh: [self-read]" in out and "줄 4" in out


def test_self_read_body_comment_change_passes(tmp_path):
    base = SELF_SH + "# tail note\necho done\n"
    code, out = verify(tmp_path, "x.sh", base, base.replace("# tail note\n", ""))
    assert code == 0, out


def test_plain_sh_head_change_passes(tmp_path):
    base = SELF_SH.replace('"$0"', "file.txt")
    code, out = verify(tmp_path, "x.sh", base, base.replace("prints", "shows"))
    assert code == 0, out


def test_not_self_read_option(tmp_path):
    repo = make_repo(tmp_path, {"x.sh": SELF_SH, "y.sh": SH})
    (repo / "x.sh").write_text(SELF_SH.replace("prints", "shows"), encoding="utf-8")
    code, out = run(repo, "x.sh")
    assert code == 1 and "x.sh: [self-read]" in out
    code, out = run(repo, "--not-self-read", "x.sh", "x.sh", "y.sh")
    assert code == 0, out
    assert "x.sh: OK (자기 읽기 검사 끔)" in out and "y.sh: OK\n" in out
    code, out = run(repo, "--not-self-read", "./x.sh", "x.sh")
    assert code == 0 and "(자기 읽기 검사 끔)" in out
    code, out = run(repo, "--not-self-read", "y.sh", "x.sh")
    assert code == 2 and "y.sh: [error]" in out
    (repo / "x.sh").write_text(
        SELF_SH.replace("prints", "shows").replace("usage\n", "usage x\n"),
        encoding="utf-8",
    )
    code, out = run(repo, "--not-self-read", "x.sh", "x.sh")
    assert code == 1 and "x.sh: [code]" in out and "(자기 읽기 검사 끔)" in out
    assert "[self-read]" not in out


@pytest.mark.parametrize(("name", "base"), [("a.sh", SH), ("a.js", JS)])
def test_shebang_change_fails(tmp_path, name, base):
    work = base.replace("#!/usr/bin/env ", "#!/usr/local/bin/", 1)
    code, out = verify(tmp_path, name, base, work)
    assert code == 1 and f"{name}: [shebang]" in out


def test_continuation_followed_by_comment_line(tmp_path):
    base = "echo a \\\n  # note\necho b\n"
    code, out = verify(tmp_path, "a.sh", base, "echo a \\\necho b\n")
    assert code == 1 and "[code]" in out


def test_inline_block_comment_joining_tokens_fails(tmp_path):
    code, out = verify(tmp_path, "a.js", "const x = a/**/in b\n", "const x = ain b\n")
    assert code == 1 and "[code]" in out


def test_broken_sh_syntax(tmp_path):
    code, out = verify(tmp_path, "a.sh", SH, SH + "if true; then\n")
    assert code == 1 and "a.sh: [syntax]" in out


def test_sh_broken_in_base_is_note_only(tmp_path):
    base = "if true; then\n  echo a # note\n"
    code, out = verify(tmp_path, "a.sh", base, base.replace(" # note", ""))
    assert code == 0, out
    assert "a.sh: OK (base 도 bash -n 을 통과하지 못하던 파일 · " in out
    assert "bash --pretty-print 비교 못 함(원문, 빈 줄 제외: base 종료 코드 " in out


LEXER_TRAP = """v="$(echo "it's")"
w='a #b'
n=${#w}
echo "$v$w" $# $n
"""


@pytest.mark.parametrize(
    ("old", "new", "codes"),
    [
        ("#b'", "#c'", ["[parse]"]),
        ("${#w}", "${#v}", ["[code]", "[parse]"]),
        ("$# ", "$@ ", ["[code]", "[parse]"]),
    ],
)
def test_lexer_traps_are_caught(tmp_path, old, new, codes):
    code, out = verify(tmp_path, "a.sh", LEXER_TRAP, LEXER_TRAP.replace(old, new))
    assert code == 1, out
    for c in codes:
        assert f"a.sh: {c}" in out, out


def test_heredoc_hash_line_change_caught_by_both(tmp_path):
    code, out = verify(
        tmp_path, "a.sh", SH, SH.replace("# inside heredoc", "# inside here")
    )
    assert code == 1 and "a.sh: [code]" in out and "a.sh: [parse]" in out, out


def test_comment_only_sh_passes_parse_check(tmp_path):
    work = SH.replace("# body note\n", "\n\n# REF: x\n").replace(
        "X=1 # inline note", "X=1"
    )
    code, out = verify(tmp_path, "a.sh", SH, work)
    assert code == 0 and "a.sh: OK\n" in out, out
    work = LEXER_TRAP.replace("n=${#w}\n", "# note\nn=${#w}  # tail\n")
    code, out = verify(tmp_path / "b", "a.sh", LEXER_TRAP, work)
    assert code == 0 and "비교 못 함(주석을 뺀 글: base 종료 코드 " in out, out


@pytest.mark.parametrize(
    ("base", "work"),
    [
        (
            "git commit -F - <<EOF\nsubject\n\nbody\nEOF\n",
            "git commit -F - <<EOF\nsubject\nbody\nEOF\n",
        ),
        ('msg="a\n\nb"\necho "$msg"\n', 'msg="a\nb"\necho "$msg"\n'),
        ("cat <<EOF\na\n   \nb\nEOF\n", "cat <<EOF\na\nb\nEOF\n"),
        ("cat <<EOF\na\nb\nEOF\n", "cat <<EOF\na\n\n\nb\nEOF\n"),
    ],
)
def test_empty_line_inside_heredoc_or_string_fails(tmp_path, base, work):
    code, out = verify(tmp_path, "a.sh", base, work)
    assert code == 1 and "a.sh: [parse] bash 파싱 결과가 다름(주석을 뺀 글)" in out, out


def test_top_level_empty_lines_and_comment_lines_pass(tmp_path):
    base = "a=1\n\n# section\n\nb=2\n# c\ncat <<EOF\nx\n\nEOF\n"
    code, out = verify(tmp_path, "a.sh", base, "a=1\nb=2\ncat <<EOF\nx\n\nEOF\n")
    assert code == 0 and "a.sh: OK\n" in out, out


COMSUB = 'x=$(\n  # c\n  echo a\n)\necho "$x"\n'


def test_no_parse_option(tmp_path):
    repo = make_repo(tmp_path, {"a.sh": COMSUB, "b.sh": SH})
    (repo / "a.sh").write_text(COMSUB.replace("  # c\n", ""), encoding="utf-8")
    code, out = run(repo, "a.sh", "b.sh")
    assert code == 1 and "a.sh: [parse]" in out
    code, out = run(repo, "--no-parse", "a.sh", "a.sh", "b.sh")
    assert code == 0 and "a.sh: OK (파서 비교 끔)" in out and "b.sh: OK\n" in out, out
    code, out = run(repo, "--no-parse", "c.sh", "a.sh")
    assert code == 2 and "c.sh: [error] --no-parse" in out
    (repo / "a.sh").write_text(
        COMSUB.replace("  # c\n", "").replace("echo a", "echo b"), encoding="utf-8"
    )
    code, out = run(repo, "--no-parse", "a.sh", "a.sh")
    assert code == 1 and "a.sh: [code]" in out and "(파서 비교 끔)" in out
    assert "[parse]" not in out


@pytest.mark.parametrize(
    ("base", "work", "ok"),
    [
        (
            "#!/usr/bin/env python3\nprint(1)\n",
            "#!/usr/bin/env python\nprint(1)\n",
            False,
        ),
        ("#!/usr/bin/env -S uv run python3\nprint(1)\n", "print(1)\n", False),
        ("print(1)\n", "#!/usr/bin/env python3\nprint(1)\n", False),
        (
            "#!/usr/bin/env python3\n# c\nprint(1)\n",
            "#!/usr/bin/env python3\nprint(1)\n",
            True,
        ),
    ],
)
def test_py_shebang(tmp_path, base, work, ok):
    code, out = verify(tmp_path, "a.py", base, work)
    assert (code == 0) == ok and ("a.py: [shebang]" in out) != ok, out


def test_mode_compared_with_base_not_index(tmp_path):
    repo = make_repo(tmp_path, {"a.sh": SH})
    os.chmod(repo / "a.sh", 0o755)
    git(repo, "add", "a.sh")
    code, out = run(repo, "a.sh")
    assert code == 1 and "a.sh: [mode] 실행 비트가 base 와 다름(base 100644" in out
    git(repo, "commit", "-qm", "exec")
    assert run(repo, "a.sh")[0] == 0
    os.chmod(repo / "a.sh", 0o644)
    code, out = run(repo, "a.sh")
    assert code == 1 and "base 100755" in out


def clean_sh(text):
    lines = text.split("\n")
    head = len(ccv.head_lines(text)) if not not_self_read(text) else 0
    drop = set()
    for ln, _body, _inline, raw, _gid in ccv.cc.scan_sh(text)[0]:
        k = ln - 1
        if k < head or raw.startswith("#!") or (k and lines[k - 1].endswith("\\")):
            continue
        lines[k] = lines[k][: len(lines[k]) - len(raw)].rstrip()
        if not lines[k].strip():
            drop.add(k)
    return "\n".join(x for k, x in enumerate(lines) if k not in drop)


def test_all_tracked_sh_comment_free_copies_pass(tmp_path):
    root = SCRIPTS.parent
    names = (
        subprocess.run(
            ["git", "ls-files", "-z", "*.sh"], cwd=root, capture_output=True, check=True
        )
        .stdout.decode()
        .split("\0")
    )
    files = {n: (root / n).read_text(encoding="utf-8") for n in names if n}
    repo = tmp_path / "repo"
    for n, text in files.items():
        (repo / n).parent.mkdir(parents=True, exist_ok=True)
        (repo / n).write_text(text, encoding="utf-8")
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    for n, text in files.items():
        (repo / n).write_text(clean_sh(text), encoding="utf-8")
    _, out = run(repo, *files)
    fails = [x for x in out.splitlines() if ": [" in x]
    assert all("[parse] bash 파싱 결과가 다름(원문, 빈 줄 제외)" in x for x in fails), (
        out
    )
    bad = sorted({x.split(": [", 1)[0] for x in fails})
    code, out = run(repo, *[f for n in bad for f in ("--no-parse", n)], *files)
    assert code == 0, out
    assert f"검사 {len(files)}개 · OK {len(files)} · 실패 0 · 건너뜀 0" in out, out
    assert "비교 못 함" not in out, out


def test_summary_line(tmp_path):
    repo = make_repo(tmp_path, {"a.py": "x = 1\n", "b.py": "y = 1\n"})
    (repo / "b.py").write_text("y = 2\n", encoding="utf-8")
    (repo / "c.txt").write_text("z\n", encoding="utf-8")
    code, out = run(repo, "a.py", "b.py", "c.txt", "new.py")
    assert out.splitlines()[-2:] == [
        "검사 4개 · OK 1 · 실패 1 · 건너뜀 2",
        "RESULT: FAIL (1건)",
    ], out
    code, out = run(repo, "c.txt")
    assert code == 0 and out.splitlines()[-2] == "검사 1개 · OK 0 · 실패 0 · 건너뜀 1"


def test_pretty_print_unknown_option_is_note(tmp_path):
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "bash").write_text(
        '#!/bin/sh\ncase "$1" in --pretty-print) echo "bash: --pretty-print: invalid'
        ' option" >&2; exit 2;; esac\nexec /bin/bash "$@"\n',
        encoding="utf-8",
    )
    os.chmod(fake / "bash", 0o755)
    repo = make_repo(tmp_path, {"a.sh": SH})
    (repo / "a.sh").write_text(SH.replace("# body note", "# x"), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, "-I", str(TOOL), "a.sh"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
        env=dict(ENV, PATH=f"{fake}:{ENV['PATH']}"),
    )
    assert r.returncode == 0, r.stdout
    assert "옵션을 모름" in r.stdout


def test_pretty_print_runs_nothing(tmp_path):
    marks = [tmp_path / f"m{k}" for k in range(7)]
    body = (
        "#!/usr/bin/env bash\n"
        f"touch {marks[0]}\n"
        f"x=$(touch {marks[1]})\n"
        f"y=`touch {marks[2]}`\n"
        f"cat <(touch {marks[3]})\n"
        f'eval "touch {marks[4]}"\n'
        f"echo hi > {marks[5]}\n"
        f"trap 'touch {marks[6]}' EXIT\n"
        "# note\n"
    )
    repo = make_repo(tmp_path, {"s.sh": body})
    (repo / "s.sh").write_text(body.replace("# note", "# other"), encoding="utf-8")
    code, out = run(repo, "s.sh")
    assert code == 0 and "s.sh: OK\n" in out, out
    assert ccv.pretty(body.encode())[0]
    assert [m for m in marks if m.exists()] == []


def test_py_unparsed(tmp_path):
    code, out = verify(tmp_path, "a.py", PY, PY + "def (:\n")
    assert code == 1 and "a.py: [unparsed] 작업 트리" in out
    broken = "def (:\n# note\n"
    code, out = verify(tmp_path / "b", "a.py", broken, broken)
    assert code == 0, out
    code, out = verify(tmp_path / "c", "a.py", broken, "def (:\n")
    assert code == 1 and "[unparsed] 양쪽" in out


def test_mode_change_fails(tmp_path):
    repo = make_repo(tmp_path, {"a.sh": SH})
    os.chmod(repo / "a.sh", 0o755)
    code, out = run(repo, "a.sh")
    assert code == 1 and "a.sh: [mode]" in out


def test_space_and_korean_file_name(tmp_path):
    name = "이름 있는 파일.py"
    code, out = verify(tmp_path, name, PY, PY.replace("  # inline note", ""))
    assert code == 0 and f"{name}: OK" in out
    code, out = verify(tmp_path / "b", name, PY, PY.replace("= 3", "= 5"))
    assert code == 1 and f"{name}: [code]" in out


def test_skips_do_not_fail(tmp_path):
    repo = make_repo(tmp_path, {"gone.py": "x = 1\n", "n.md": "a\n"})
    (repo / "gone.py").unlink()
    (repo / "new.py").write_text("x = 1\n", encoding="utf-8")
    code, out = run(repo, "gone.py", "new.py", "n.md")
    assert code == 0, out
    assert (
        "gone.py: [skip]" in out and "new.py: [skip]" in out and "n.md: [skip]" in out
    )


def test_base_option(tmp_path):
    repo = make_repo(tmp_path, {"a.py": "x = 1\n"})
    (repo / "a.py").write_text("x = 2\n", encoding="utf-8")
    git(repo, "commit", "-qam", "second")
    (repo / "a.py").write_text("x = 2  # note\n", encoding="utf-8")
    assert run(repo, "a.py")[0] == 0
    assert run(repo, "--base", "HEAD~1", "a.py")[0] == 1


def test_exit_codes_for_usage(tmp_path):
    repo = make_repo(tmp_path, {"a.py": "x = 1\n"})
    assert run(repo, "--base", "nope", "a.py")[0] == 2
    assert run(repo, "--base", "--help", "a.py")[0] == 2
    assert run(repo)[0] == 2
    outside = tmp_path / "out"
    outside.mkdir()
    code, out = run(outside, "a.py")
    assert code == 2 and "git 저장소" in out
    assert run(repo, str(outside / "a.py"))[0] == 2


def test_control_characters_are_masked(tmp_path):
    name = "a\x1bb.py"
    code, out = verify(tmp_path, name, "x = 1\n", "x = 2\n")
    assert code == 1 and "a?b.py: [code]" in out and "\x1b" not in out


def strip_py_comments(text):
    lines = text.split("\n")
    cut = {}
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type == tokenize.COMMENT and not tok.string.startswith("#!"):
            cut[tok.start[0] - 1] = tok.start[1]
    out = []
    for k, line in enumerate(lines):
        if k in cut:
            line = line[: cut[k]].rstrip()
            if not line:
                continue
        out.append(line)
    return "\n".join(out)


def strip_sh_comments(text):
    lines = text.split("\n")
    for ln, _body, _inline, raw, _gid in ccv.cc.scan_sh(text)[0]:
        if ln == 1 and raw.startswith("#!"):
            continue
        if ln > 1 and lines[ln - 2].endswith("\\"):
            continue
        lines[ln - 1] = lines[ln - 1][: len(lines[ln - 1]) - len(raw)].rstrip()
    return "\n".join(line for line in lines if line.strip()) + "\n"


def pick(pattern, count, keep=lambda t: True):
    found = []
    for p in sorted(SCRIPTS.glob(pattern)):
        text = p.read_text(encoding="utf-8")
        if keep(text):
            found.append((p.name, text))
        if len(found) == count:
            break
    assert len(found) == count
    return found


def not_self_read(text):
    return not any(
        ccv.SELF.search(x) and ccv.READERS.search(x) for x in text.split("\n")
    )


def test_real_scripts_comment_free_copy_passes_and_line_drop_fails(tmp_path):
    py = [
        (n, (SCRIPTS / n).read_text(encoding="utf-8"))
        for n in ("comment_check.py", "lint_changed.py", "comment_cleanup_verify.py")
    ] + pick("[a-b]*.py", 2)
    sh = pick("*.sh", 3, not_self_read)
    files = dict(py + sh)
    repo = make_repo(tmp_path, files)
    for name, text in py:
        (repo / name).write_text(strip_py_comments(text), encoding="utf-8")
    for name, text in sh:
        (repo / name).write_text(strip_sh_comments(text), encoding="utf-8")
    code, out = run(repo, *files)
    assert (code, out.splitlines()[-1]) == (0, "RESULT: PASS"), out
    for name, text in py:
        lines = text.split("\n")
        k = (
            next(n for n in ast.parse(text).body if isinstance(n, ast.Import)).lineno
            - 1
        )
        (repo / name).write_text(
            "\n".join(lines[:k] + lines[k + 1 :]), encoding="utf-8"
        )
    for name, text in sh:
        lines = strip_sh_comments(text).split("\n")
        k = next(
            i
            for i in range(1, len(lines) - 1)
            if lines[i]
            and not lines[i].endswith("\\")
            and not lines[i - 1].endswith("\\")
        )
        (repo / name).write_text(
            "\n".join(lines[:k] + lines[k + 1 :]), encoding="utf-8"
        )
    code, out = run(repo, *files)
    assert code == 1, out
    for name in files:
        assert f"{name}: [code]" in out, out
