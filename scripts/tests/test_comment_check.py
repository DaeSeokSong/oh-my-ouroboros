"""Tests for scripts/comment_check.py and its block in scripts/ci-gate-commit.sh (intent/2026-11-24-harness-review-six-items.md W17).

Run: uv run --no-project --with pytest python -m pytest scripts/tests/test_comment_check.py -q -p no:cacheprovider
Git cases build throwaway repositories under pytest tmp_path with global and system git config disabled.
"""

import importlib.util
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
CHECKER = SCRIPTS / "comment_check.py"
HOOK = SCRIPTS / "ci-gate-commit.sh"
_spec = importlib.util.spec_from_file_location("comment_check", CHECKER)
cc = importlib.util.module_from_spec(_spec)
sys.modules["comment_check"] = cc
_spec.loader.exec_module(cc)
ENV = dict(
    os.environ,
    GIT_CONFIG_GLOBAL="/dev/null",
    GIT_CONFIG_SYSTEM="/dev/null",
    GIT_AUTHOR_NAME="t",
    GIT_AUTHOR_EMAIL="t@t",
    GIT_COMMITTER_NAME="t",
    GIT_COMMITTER_EMAIL="t@t",
)


def codes(path, text, selected=None):
    return [
        line.split("[", 1)[1].split("]", 1)[0]
        for line in cc.check_text(path, text, selected)
    ]


def git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, env=ENV
    )


def make_repo(tmp_path, files=None):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    for name, body in (files or {}).items():
        write(repo, name, body)
    if files:
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "base")
    return repo


def write(repo, name, body):
    p = repo / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


def run_checker(cwd, *args):
    r = subprocess.run(
        [sys.executable, "-I", str(CHECKER), *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        env=ENV,
    )
    return r.returncode, r.stdout + r.stderr


@pytest.mark.parametrize(
    "comment",
    [
        "# WHY: limit set on 2026-11-24",
        "# WHY: 3 retries match the server limit",
        "# WHY: see https://example.com/a",
        "# WHY: format fixed by scripts/ci-gate-commit.sh",
        "# WHY: 근거는 config/hosts/host1.json 의 값이다",
        "# NEVER: do not call this from a hook",
        "# NEVER: 이 함수는 훅에서 부르지 않는다",
        "# REF: eq. (3) of the paper",
        "# REF: 공식 문서의 예제",
    ],
)
def test_category_passes(comment):
    assert codes("a.py", f"x = 1\n{comment}\ny = 2\n") == []


@pytest.mark.parametrize(
    ("comment", "code"),
    [
        ("# just a note", "no-tag"),
        ("# why: lowercase marker", "no-tag"),
        ("# WHY: because it reads better", "why-evidence"),
        ("# NEVER: try to avoid this", "never-soft"),
        ("# NEVER: should probably not run twice", "never-soft"),
        ("# NEVER: skip it if possible", "never-soft"),
        ("# NEVER: 가급적 부르지 않는다", "never-soft"),
        ("# NEVER: 되도록 쓰지 않는다", "never-soft"),
        ("# NEVER: 웬만하면 끄지 않는다", "never-soft"),
    ],
)
def test_category_violations(comment, code):
    assert codes("a.py", f"x = 1\n{comment}\n") == [code]


@pytest.mark.parametrize(
    "word",
    [
        "임시로",
        "임시 조치",
        "임시방편",
        "일단",
        "추후",
        "우선은",
        "for now",
        "For now",
        "TODO",
        "FIXME",
        "HACK",
        "XXX",
    ],
)
def test_excuse_words_in_any_category(word):
    assert "excuse" in codes("a.py", f"x = 1\n# REF: 2026-11-24 {word} x\n")


@pytest.mark.parametrize(
    "text",
    [
        "임시로 둔다",
        "일단 내린다",
        "일단 둔다",
        "일단 이렇게 둔다",
        "일단은 통과시킨다",
        "skip it for now (see issue 12)",
        "hardcoded for now - revisit",
        "for  now we skip",
        "TODO를 남겨 둔다",
        "이 함수는 FIXME가 남아 있다",
        "임시조치다",
        "임시 방편이다",
        "임시 코드라서 곧 지운다",
        "임시 주석이다",
        "임시처리 경로다",
        "TODO: fix",
        "FIXME",
        "for now we skip",
        "추후 정리",
        "우선은 이렇게",
    ],
)
def test_deferring_sentences_are_excuse(text):
    assert codes("a.py", f"x = 1\n# REF: 2026-11-24 {text}\n") == ["excuse"]


@pytest.mark.parametrize(
    "text",
    [
        "writes into a temporary folder",
        "Temporarily disables the cache",
        "all later steps read it",
        "Python 3.8 or later",
        "나중에 끝난 mv 가 덮어쓴다",
        "token=xxx is a placeholder",
        "names that start with todo- are skipped",
        "elapsed = for now minus start",
        "window for now - 3 h",
        "see docs/TODO.md",
        "listed in TODO.md",
        "latest",
        "hackathon",
        "fixme in lower case",
        "a hack in lower case",
        "정리가 일단락되면 표를 닫는다",
        "일단위로 집계한다",
        "임시 로그를 물려 시험한다",
        "임시로그 파일을 지운다",
        "end = for now+5s",
        "window is for now - 3 h",
        "for now() returns the clock",
        "임시 폴더를 만들고 종료 시 지운다",
        "임시 파일은 trap 이 지운다",
        "임시 디렉터리를 쓴다",
        "my_TODO_list is a variable",
        "knowledge/harness/TODO is a path",
    ],
)
def test_plain_words_are_not_excuse(text):
    assert codes("a.py", f"x = 1\n# REF: 2026-11-24 {text}\n") == []


def test_continuation_lines_belong_to_block():
    assert (
        codes(
            "a.py", "x = 1\n# WHY: 2026-11-24 limit\n# second line\n#\n# third line\n"
        )
        == []
    )


def test_marker_line_opens_new_block():
    assert codes("a.py", "x = 1\n# WHY: 2026-11-24\n# NEVER: try to x\n# REF: y\n") == [
        "never-soft"
    ]


def test_inline_comment_is_its_own_block():
    assert codes("a.py", "x = 1  # WHY: 2 bytes\ny = 2  # plain\n") == ["no-tag"]


def test_header_block_passes():
    text = "#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\n# plain header\n# usage: a.py\nx = 1\n# plain\n"
    assert codes("a.py", text) == ["no-tag"]
    assert codes("a.sh", "#!/bin/bash\n# plain header\nset -u\n# plain\n") == ["no-tag"]
    assert codes(
        "a.js", "#!/usr/bin/env node\n/**\n * plain header\n */\nfoo();\n// plain\n"
    ) == ["no-tag"]


def test_module_docstring_passes_function_docstring_checked():
    text = (
        '"""Plain module docstring."""\n'
        "def f():\n"
        '    """Plain function docstring."""\n'
        "class K:\n"
        '    """\n    WHY: 2026-11-24 multi-line docstring with marker on its first text line.\n    """\n'
        "async def g():\n"
        '    """REF: https://example.com"""\n'
    )
    out = cc.check_text("a.py", text)
    assert len(out) == 1
    assert out[0].startswith("a.py:3: [no-tag]")


@pytest.mark.parametrize(
    ("name", "text"),
    [
        (
            "a.py",
            "x = 1  # noqa: E501\ny = 2  # type: ignore[attr]\n# pylint: disable=c\n# fmt: off\nz = 3  # pragma: no cover\n",
        ),
        ("a.sh", "set -u\n# shellcheck disable=SC2034\nX=1\n"),
        (
            "a.js",
            "foo();\n// eslint-disable-next-line no-console\n/* eslint-disable */\nbar(); // @ts-ignore\n",
        ),
    ],
)
def test_machine_markers_pass(name, text):
    assert codes(name, text) == []


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("a.py", 'x = \'# not a comment\'\ny = """\n# still string\n"""\n'),
        (
            "a.sh",
            (
                "set -u\necho \"# a\" '# b' $'c \\' # d' a#b ${#x} $#\ncat <<EOF\n# heredoc\nEOF\ncat <<-'E'\n\t# tab heredoc\n\tE\n"
                'echo "multi\n# still string\n"\n'
            ),
        ),
        (
            "a.js",
            'foo();\nconst a = "// no";\nconst b = \'/* no */\';\nconst r = /\\/\\/ no [/]/g;\nconst t = `x // ${a + "}"} // no`;\nconst d = 4 / 2;\n',
        ),
    ],
)
def test_comment_leaders_inside_strings_are_not_comments(name, text):
    assert codes(name, text) == []


def test_sh_heredoc_does_not_hide_later_comments():
    assert codes("a.sh", "set -u\ncat <<EOF\nbody\nEOF\n# plain\n") == ["no-tag"]


def test_js_block_comment_first_text_line():
    assert codes("a.js", "foo();\n/**\n * WHY: 2026-11-24 a\n */\n") == []
    out = cc.check_text("a.js", "foo();\n/**\n * plain\n */\n")
    assert len(out) == 1
    assert out[0].startswith("a.js:3: [no-tag]")
    out = cc.check_text(
        "a.js", "foo();\n/**\n * WHY: 2026-11-24 ok\n */\n/**\n * plain\n */\n"
    )
    assert len(out) == 1
    assert out[0].startswith("a.js:6: [no-tag]")


def test_js_division_after_increment_is_not_regex():
    assert codes("a.js", "var a = i++ / 2; // plain\n") == ["no-tag"]


def test_js_adjacent_block_comments_are_separate():
    out = cc.check_text("a.js", "foo();\n/* WHY: 2026-11-24 a */\n/* plain */\n")
    assert len(out) == 1
    assert out[0].startswith("a.js:3: [no-tag]")


@pytest.mark.parametrize(
    "text",
    [
        "set -u\ncat <<< word\n# plain\n",
        "x=$(( 1 << n ))\n# plain\n",
        "x=$(( 1 << n ))  # plain\n",
        "(( n <<= 1 ))\n# plain\n",
    ],
)
def test_sh_here_string_and_arithmetic_do_not_open_heredoc(text):
    assert codes("a.sh", text) == ["no-tag"]


@pytest.mark.parametrize(
    ("comment", "want"),
    [
        ("x = 1  # noqa: E501 TODO", ["excuse"]),
        ("# noqa 임시로 둔다", ["no-tag", "excuse"]),
        ("# noqa trailing words", ["no-tag"]),
        ("x = 1  # type: ignore because", ["no-tag"]),
        ("# fmt: please", ["no-tag"]),
        ("# pragma once", ["no-tag"]),
        ("# shellcheck is fine", ["no-tag"]),
        ("# pylint: disable=c TODO", ["excuse"]),
    ],
)
def test_machine_markers_are_narrow(comment, want):
    assert codes("a.py", f"x = 0\n{comment}\n") == want


def test_coding_line_only_on_first_two_lines():
    assert codes("a.py", "# -*- coding: utf-8 -*-\nx = 1\n") == []
    assert codes("a.py", "x = 1\ny = 2\nz = 3\n# coding: utf-8\n") == ["no-tag"]


@pytest.mark.parametrize("comment", ["# NEVER:", "# REF:   ", "# WHY:"])
def test_empty_marker_is_violation(comment):
    assert codes("a.py", f"x = 1\n{comment}\n") == ["empty-tag"]


def test_marker_text_on_next_line_counts():
    assert codes("a.py", "x = 1\n# WHY:\n# 2026-11-24 limit\n") == []


def test_excuse_words_apply_to_head_block_and_module_docstring():
    assert codes("a.py", "# head TODO\nx = 1\n") == ["excuse"]
    assert codes("a.py", '"""Module; FIXME."""\nx = 1\n') == ["excuse"]
    assert codes("a.sh", "#!/bin/bash\n# 일단 이렇게 둔다\nset -u\n") == ["excuse"]


def test_for_now_before_time_operator_is_not_excuse():
    assert codes("a.py", "x = 1\n# REF: for now(2026) plus 3 days\n") == []
    assert codes("a.py", "x = 1\n# REF: for now + 2 h\n") == []
    assert codes("a.py", "x = 1\n# REF: 2026-11-24 skip it for now\n") == ["excuse"]


def test_python_syntax_error_still_checks_comments():
    assert codes("a.py", "x = (1,\n# plain\n") == ["no-tag"]
    assert codes("a.py", "def f(:\n    pass  # plain\n") == ["no-tag"]
    assert codes("a.py", "x = '\x00'\n# plain\n") == ["no-tag"]


def test_unscannable_file_blocks_and_others_continue(tmp_path, monkeypatch, capsys):
    def boom(text):
        raise RecursionError

    monkeypatch.setattr(cc, "scan_sh", boom)
    sh = tmp_path / "a.sh"
    sh.write_text("set -u\n", encoding="utf-8")
    py = tmp_path / "b.py"
    py.write_text("x = 1  # plain\n", encoding="utf-8")
    assert cc.main([str(sh), str(py)]) == 1
    out = capsys.readouterr().out
    assert f"{sh}:1: [unscannable]" in out
    assert f"{py}:1: [no-tag]" in out
    assert "RESULT: FAIL (2건)" in out


def test_evidence_check_is_fast_on_long_text():
    start = time.monotonic()
    out = cc.check_text("a.py", "x = 1\n# WHY: " + "a." * 20000 + "\n")
    assert time.monotonic() - start < 1
    assert codes("a.py", "x = 1\n# WHY: " + "a." * 20000 + "\n") == ["why-evidence"]
    assert out
    start = time.monotonic()
    cc.EVIDENCE.search("a/" + "a" * 20000)
    cc.EVIDENCE.search("a." * 20000)
    assert time.monotonic() - start < 1


def test_control_characters_are_masked(tmp_path):
    p = tmp_path / "a\x01.py"
    p.write_text("x = 1\n# a\x1bb\n", encoding="utf-8")
    rc, out = run_checker(tmp_path, str(p))
    assert rc == 1
    assert "a?.py:2: [no-tag]" in out
    assert "# a?b" in out
    assert "\x1b" not in out


HOSTILE = "\x1b\x07" + chr(0x85) + chr(0x202E) + chr(0x2066) + chr(0x200F)


@pytest.mark.parametrize("suffix", [".py", ".sh"])
def test_output_masks_c0_c1_and_bidi(tmp_path, suffix):
    p = tmp_path / f"n\x1b\x07{suffix}"
    p.write_text(f"x=1\n# plain {HOSTILE} end\n", encoding="utf-8")
    rc, out = run_checker(tmp_path, str(p))
    assert rc == 1
    assert "[no-tag]" in out
    assert not any(ch in out for ch in HOSTILE)


@pytest.mark.parametrize(
    ("name", "text", "want_line"),
    [
        ("a.py", 'def f():\r\r\r    """plain"""\n    return 1\n', 4),
        ("a.py", "x=1\n# WHY: 2026-11-24 ok\r\r# plain bad\n", 4),
        ("a.sh", "set -u\r# plain\n", 2),
        ("a.js", "foo();\r// plain\n", 2),
    ],
)
def test_bare_cr_breaks_lines(name, text, want_line):
    out = cc.check_text(name, text)
    assert len(out) == 1
    assert out[0].startswith(f"{name}:{want_line}: [no-tag]")


def test_bare_cr_checks_whole_file_and_crlf_keeps_selection():
    assert codes("a.py", "x=1\r# plain\n", {5}) == ["no-tag"]
    assert codes("a.py", "x=1\r\n# plain\r\ny=2\r\n", {3}) == []
    assert codes("a.py", "x=1\r\n# plain\r\ny=2\r\n", {2}) == ["no-tag"]


def test_docstrings_from_tokens_when_ast_fails(monkeypatch):
    def fail(*args, **kwargs):
        raise SystemError

    monkeypatch.setattr(cc.ast, "parse", fail)
    text = (
        '"""Module docstring."""\n'
        "def f():\n"
        '    """plain"""\n'
        "\n"
        'def g(): """plain one-liner"""\n'
        "class K(B):\n"
        '    """WHY: 2026-11-24 ok"""\n'
        "def h(x: int = (lambda: 1)()) -> int:\n"
        '    """REF: https://example.com"""\n'
    )
    out = cc.check_text("a.py", text)
    assert [line.split(": [")[0] for line in out] == ["a.py:3", "a.py:5"]
    assert all("[no-tag]" in line for line in out)


def test_docstrings_from_lines_when_tokenize_fails(monkeypatch):
    def fail(*args, **kwargs):
        raise MemoryError

    monkeypatch.setattr(cc.tokenize, "generate_tokens", fail)
    text = (
        'def f():\n    """plain"""\n    return 1\n'
        'class K:\n\n    """WHY: 2026-11-24\n    more\n    """\n'
        "x = 1  # plain\n"
    )
    out = cc.check_text("a.py", text)
    assert [line.split(": [")[0] for line in out] == ["a.py:2", "a.py:9"]


def test_load_errors_of_any_kind_are_unscannable(tmp_path, monkeypatch, capsys):
    repo = make_repo(tmp_path, {"base.txt": "x\n"})
    write(repo, "a.py", "x = 1\n")
    git(repo, "add", "a.py")

    def fail(*args, **kwargs):
        raise MemoryError

    monkeypatch.setattr(cc, "changed_lines", fail)
    monkeypatch.chdir(repo)
    assert cc.main(["--staged"]) == 1
    out = capsys.readouterr().out
    assert "a.py:1: [unscannable]" in out


@pytest.mark.parametrize("suffix", [".sh", ".py"])
def test_many_empty_comment_lines_are_fast(suffix):
    start = time.monotonic()
    out = cc.check_text(f"a{suffix}", "x=1\n" + "#\n" * 200000)
    assert time.monotonic() - start < 2
    assert len(out) == 1


@pytest.mark.parametrize(
    ("comment", "want"),
    [
        ("# -*- coding: utf-8 -*-", []),
        ("# vim: set fileencoding=utf-8 :", []),
        ("# coding=utf-8", []),
        ("# words first coding: utf-8", ["no-tag"]),
        ("# coding: utf-8 and some prose", ["no-tag"]),
    ],
)
def test_pep263_needs_standard_form(comment, want):
    assert codes("a.py", f"x = 1\n{comment}\n") == want


@pytest.mark.parametrize(
    ("comment", "want"),
    [
        ("x = 1  # noqa: E501", []),
        ("x = 1  # noqa: E501,F401", []),
        ("x = 1  # noqa: E501 (긴 줄이라서)", ["no-tag"]),
        ("z = 3  # pragma: no cover", []),
        ("z = 3  # pragma: no cover — 이유", ["no-tag"]),
    ],
)
def test_noqa_and_pragma_values_are_tool_syntax_only(comment, want):
    assert codes("a.py", f"x = 0\n{comment}\n") == want


def test_selected_lines_limit_blocks():
    text = "x = 1\n# old plain\ny = 2\n# new plain\n# WHY: 2026 kept\n"
    assert codes("a.py", text, {4}) == ["no-tag"]
    assert codes("a.py", text, {3}) == []
    assert codes("a.py", text, set()) == []


def test_output_line_format_and_truncation():
    out = cc.check_text("a.py", "x = 1\n# " + "y" * 100 + "\n")
    assert out[0].startswith("a.py:2: [no-tag] ")
    assert "#" + " " + "y" * 78 + "…" in out[0]
    assert "→" in out[0]


def test_other_extensions_skipped(tmp_path):
    p = tmp_path / "a.md"
    p.write_text("# plain\n", encoding="utf-8")
    assert run_checker(tmp_path, str(p)) == (0, "RESULT: PASS\n")


def test_exit_codes(tmp_path):
    good = tmp_path / "good.py"
    good.write_text("x = 1\n", encoding="utf-8")
    bad = tmp_path / "bad.py"
    bad.write_text("x = 1  # plain\n", encoding="utf-8")
    assert run_checker(tmp_path, str(good))[0] == 0
    rc, out = run_checker(tmp_path, str(bad))
    assert rc == 1
    assert out.rstrip().endswith("RESULT: FAIL (1건)")
    assert run_checker(tmp_path)[0] == 2
    rc, out = run_checker(tmp_path, str(tmp_path / "missing.py"))
    assert rc == 2
    assert "RESULT: ERROR (1건)" in out
    assert run_checker(tmp_path, "--staged")[0] == 2
    syntax = tmp_path / "syntax.py"
    syntax.write_text("x = (1,\n", encoding="utf-8")
    assert run_checker(tmp_path, str(syntax))[0] == 0
    syntax.write_text("x = (1,\n# plain\n", encoding="utf-8")
    assert run_checker(tmp_path, str(syntax))[0] == 1


def test_staged_checks_only_added_lines(tmp_path):
    repo = make_repo(tmp_path, {"a.py": "x = 1\n# old plain\n"})
    write(repo, "a.py", "x = 1\n# old plain\ny = 2  # new plain\n")
    git(repo, "add", "a.py")
    rc, out = run_checker(repo, "--staged")
    assert rc == 1
    assert "a.py:3: [no-tag]" in out
    assert "a.py:2:" not in out


def test_staged_reads_index_not_work_tree(tmp_path):
    repo = make_repo(tmp_path, {"a.py": "x = 1\n"})
    write(repo, "a.py", "x = 1\ny = 2  # plain\n")
    git(repo, "add", "a.py")
    write(repo, "a.py", "x = 1\ny = 2\n")
    assert run_checker(repo, "--staged")[0] == 1
    write(repo, "a.py", "x = 1\ny = 2\n")
    git(repo, "add", "a.py")
    write(repo, "a.py", "x = 1\ny = 2  # plain\n")
    assert run_checker(repo, "--staged")[0] == 0


def test_staged_without_head_checks_new_file(tmp_path):
    repo = make_repo(tmp_path)
    write(repo, "a.sh", "set -u\necho 1  # plain\n")
    git(repo, "add", "a.sh")
    rc, out = run_checker(repo, "--staged")
    assert rc == 1
    assert "a.sh:2: [no-tag]" in out


def test_diff_mode_tracked_lines_and_untracked_whole(tmp_path):
    repo = make_repo(tmp_path, {"a.py": "x = 1\n# old plain\n"})
    write(repo, "a.py", "x = 1\n# old plain\ny = 2\n")
    write(repo, "new.js", "foo();\n// plain\n")
    rc, out = run_checker(repo, "--diff")
    assert rc == 1
    assert "new.js:2: [no-tag]" in out
    assert "a.py" not in out


def test_space_and_non_ascii_names(tmp_path):
    repo = make_repo(tmp_path, {"새 파일 a.py": "x = 1\n"})
    write(repo, "새 파일 a.py", "x = 1  # plain\n")
    git(repo, "add", "-A")
    rc, out = run_checker(repo, "--staged")
    assert rc == 1
    assert "새 파일 a.py:1: [no-tag]" in out
    rc, out = run_checker(repo, "--diff")
    assert rc == 1
    assert "새 파일 a.py:1: [no-tag]" in out


def test_staged_pathspec_exclude(tmp_path):
    repo = make_repo(tmp_path)
    write(repo, "graphify-out/g.py", "x = 1  # plain\n")
    git(repo, "add", "-A")
    assert run_checker(repo, "--staged", "--", ":(exclude)graphify-out") == (
        0,
        "RESULT: PASS\n",
    )


BODY = "".join(f"v{k} = {k}\n" for k in range(10))


def test_staged_pure_rename_passes(tmp_path):
    repo = make_repo(tmp_path, {"a.py": BODY + "# old plain\n"})
    git(repo, "mv", "a.py", "b.py")
    assert run_checker(repo, "--staged") == (0, "RESULT: PASS\n")


def test_staged_rename_with_added_line_checks_only_that_line(tmp_path):
    repo = make_repo(tmp_path, {"a.py": BODY + "# old plain\n"})
    git(repo, "mv", "a.py", "b.py")
    write(repo, "b.py", BODY + "# old plain\ny = 2  # new plain\n")
    git(repo, "add", "b.py")
    rc, out = run_checker(repo, "--staged")
    assert rc == 1
    assert "b.py:12: [no-tag]" in out
    assert "b.py:11:" not in out


def test_diff_mode_rename_with_added_line(tmp_path):
    repo = make_repo(tmp_path, {"a.py": BODY + "# old plain\n"})
    git(repo, "mv", "a.py", "b.py")
    write(repo, "b.py", BODY + "# old plain\ny = 2  # new plain\n")
    rc, out = run_checker(repo, "--diff")
    assert rc == 1
    assert "b.py:12: [no-tag]" in out
    assert "b.py:11:" not in out


@pytest.mark.parametrize(
    ("name", "base", "new"),
    [
        ("a.sh", "set -u\n", "set -u\nprintf 'a\x00b'\n# plain\n"),
        ("a.js", "foo();\n", "foo();\nconst a = '\x00';\n// plain\n"),
        ("a.py", "x = 1\n", "x = 1\ny = '\x00'\n# plain\n"),
    ],
)
@pytest.mark.parametrize("attributes", [False, True])
def test_staged_nul_and_minus_diff_files_are_checked(
    tmp_path, name, base, new, attributes
):
    files = {
        name: base,
        **(
            {".gitattributes": "*.sh -diff\n*.js -diff\n*.py -diff\n"}
            if attributes
            else {}
        ),
    }
    repo = make_repo(tmp_path, files)
    write(repo, name, new)
    git(repo, "add", name)
    rc, out = run_checker(repo, "--staged")
    assert rc == 1
    assert f"{name}:3: [no-tag]" in out


def test_staged_skips_gitlink_and_symlink(tmp_path):
    repo = make_repo(tmp_path, {"a.py": "x = 1  # old plain\n"})
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=ENV,
    ).stdout.strip()
    git(repo, "update-index", "--add", "--cacheinfo", f"160000,{head},sub.py")
    (repo / "link.py").symlink_to("a.py")
    git(repo, "add", "link.py")
    assert run_checker(repo, "--staged") == (0, "RESULT: PASS\n")


def test_staged_reads_names_that_look_like_stage_syntax(tmp_path):
    repo = make_repo(tmp_path, {"base.txt": "x\n"})
    write(repo, "0:x.py", "x = 1  # plain\n")
    git(repo, "add", "-A")
    rc, out = run_checker(repo, "--staged")
    assert rc == 1
    assert "0:x.py:1: [no-tag]" in out


def test_staged_output_has_no_comment_text(tmp_path):
    repo = make_repo(tmp_path, {"base.txt": "x\n"})
    write(repo, "a.py", "x = 1  # secret-looking words here\n")
    git(repo, "add", "-A")
    rc, out = run_checker(repo, "--staged")
    assert rc == 1
    assert "a.py:1: [no-tag]" in out
    assert "secret-looking" not in out
    rc, out = run_checker(repo, "--diff")
    assert "secret-looking" in out


REAL = CHECKER.read_text(encoding="utf-8")


def run_hook(repo):
    r = subprocess.run(
        ["bash", str(HOOK)],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
        env=ENV,
    )
    return r.returncode, r.stdout + r.stderr


def commit_paths(repo, *paths):
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text(f'#!/bin/sh\nexec bash "{HOOK}"\n', encoding="utf-8")
    hook.chmod(0o755)
    r = subprocess.run(
        ["git", "commit", "-q", "-m", "t", "--", *paths],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
        env=ENV,
    )
    return r.returncode, r.stdout + r.stderr


def staged_repo(tmp_path, body, checker=None, stage_checker=True, base=None):
    repo = make_repo(tmp_path, base or {"base.txt": "x\n"})
    write(repo, "a.py", body)
    if checker is not None:
        write(repo, "scripts/comment_check.py", checker)
    git(
        repo,
        "add",
        "a.py",
        *(
            ["scripts/comment_check.py"]
            if checker is not None and stage_checker
            else []
        ),
    )
    return repo


def test_hook_blocks_on_violation(tmp_path):
    repo = staged_repo(tmp_path, "x = 1  # plain\n", REAL)
    rc, out = run_hook(repo)
    assert rc == 1
    assert "COMMENT RULE" in out
    assert "a.py:1: [no-tag]" in out


def test_hook_passes_clean_comments(tmp_path):
    repo = staged_repo(tmp_path, "x = 1  # WHY: 2026-11-24 limit\n", REAL)
    rc, out = run_hook(repo)
    assert rc == 0
    assert "PASSED" in out


def test_hook_skips_untracked_checker(tmp_path):
    repo = staged_repo(tmp_path, "x = 1  # plain\n", REAL, stage_checker=False)
    rc, out = run_hook(repo)
    assert rc == 0
    assert "COMMENT" not in out


def test_hook_runs_index_copy_not_work_tree(tmp_path):
    repo = staged_repo(tmp_path, "x = 1  # plain\n", REAL)
    write(repo, "scripts/comment_check.py", "import sys\n\nsys.exit(0)\n")
    rc, out = run_hook(repo)
    assert rc == 1
    assert "COMMENT RULE" in out


def test_partial_commit_skips_checker_outside_commit(tmp_path):
    repo = staged_repo(tmp_path, "x = 1  # plain\n", REAL)
    rc, out = commit_paths(repo, "a.py")
    assert rc == 0, out
    assert "COMMENT" not in out


def test_partial_commit_checks_when_checker_in_head(tmp_path):
    repo = staged_repo(
        tmp_path,
        "x = 1  # plain\n",
        base={"base.txt": "x\n", "scripts/comment_check.py": REAL},
    )
    rc, out = commit_paths(repo, "a.py")
    assert rc != 0
    assert "COMMENT RULE" in out


def test_staged_type_change_symlink_to_file(tmp_path):
    repo = make_repo(tmp_path, {"t.txt": "x\n", "scripts/comment_check.py": REAL})
    (repo / "x.py").symlink_to("t.txt")
    git(repo, "add", "x.py")
    git(repo, "commit", "-q", "-m", "link")
    (repo / "x.py").unlink()
    write(repo, "x.py", "x = 1  # plain\n")
    git(repo, "add", "x.py")
    rc, out = run_checker(repo, "--staged")
    assert rc == 1
    assert "x.py:1: [no-tag]" in out
    rc, out = run_hook(repo)
    assert rc == 1
    assert "COMMENT RULE" in out


BOM = chr(0xFEFF)
SYSTEM_PY = shutil.which("python3", path="/usr/bin:/bin")


@pytest.mark.parametrize(
    ("name", "text", "want"),
    [
        ("a.py", BOM + 'def f():\n    """plain"""\n', "a.py:2: [no-tag]"),
        ("a.py", BOM + '"""임시로 둔 모듈"""\n', "a.py:1: [excuse]"),
        ("a.sh", BOM + "set -u\n# plain\n", "a.sh:2: [no-tag]"),
        ("a.js", BOM + "foo();\n// plain\n", "a.js:2: [no-tag]"),
    ],
)
def test_leading_bom_is_dropped(tmp_path, name, text, want):
    out = cc.check_text(name, text)
    assert len(out) == 1
    assert out[0].startswith(want)
    if SYSTEM_PY:
        (tmp_path / name).write_text(text, encoding="utf-8")
        r = subprocess.run(
            [SYSTEM_PY, "-I", str(CHECKER), name],
            cwd=tmp_path,
            check=False,
            capture_output=True,
            text=True,
        )
        assert r.returncode == 1
        assert want in r.stdout


def test_ast_warnings_stay_quiet(tmp_path):
    p = tmp_path / "w.py"
    p.write_text('x = "\\("\n', encoding="utf-8")
    assert run_checker(tmp_path, str(p)) == (0, "RESULT: PASS\n")


def test_hook_copy_survives_staged_path_named_like_copy(tmp_path):
    repo = make_repo(tmp_path, {"base.txt": "x\n", "scripts/comment_check.py": REAL})
    write(repo, ".comment_check.py/x.txt", "x\n")
    write(repo, "a.py", "x = 1  # plain\n")
    git(repo, "add", "-A")
    rc, out = run_hook(repo)
    assert rc == 1
    assert "COMMENT RULE" in out
    assert "COMMENT CHECK · 경고" not in out


def test_hook_drops_checker_stderr(tmp_path):
    checker = (
        "import sys\n\n"
        'sys.stderr.write("STDERR-NOISE\\n")\n'
        'print("a.py:1: [no-tag] x")\n'
        'print("RESULT: FAIL (1건)")\n'
        "sys.exit(1)\n"
    )
    repo = staged_repo(tmp_path, "x = 1  # plain\n", checker)
    rc, out = run_hook(repo)
    assert rc == 1
    assert "COMMENT RULE" in out
    assert "STDERR-NOISE" not in out


def test_hook_uses_head_copy_when_checker_removed_in_commit(tmp_path):
    repo = make_repo(tmp_path, {"base.txt": "x\n", "scripts/comment_check.py": REAL})
    git(repo, "rm", "-q", "scripts/comment_check.py")
    write(repo, "a.py", "x = 1  # plain\n")
    git(repo, "add", "a.py")
    rc, out = run_hook(repo)
    assert rc == 1
    assert "COMMENT RULE" in out
    assert "a.py:1: [no-tag]" in out


@pytest.mark.parametrize(
    "checker",
    [
        "import sys\n\nprint('RESULT: ERROR (1건)')\nsys.exit(2)\n",
        "import sys\n\nsys.exit(1)\n",
        "import comment_check_missing_module_w17\n\ncomment_check_missing_module_w17.main()\n",
    ],
)
def test_hook_does_not_block_on_checker_error(tmp_path, checker):
    repo = staged_repo(tmp_path, "x = 1  # plain\n", checker)
    rc, out = run_hook(repo)
    assert rc == 0, out
    assert "COMMENT CHECK · 경고" in out
    assert "COMMENT RULE" not in out


def test_hook_skips_graphify_out(tmp_path):
    repo = make_repo(tmp_path, {"base.txt": "x\n", "scripts/comment_check.py": REAL})
    write(repo, "graphify-out/g.py", "x = 1  # plain\n")
    git(repo, "add", "-A")
    rc, out = run_hook(repo)
    assert rc == 0
    assert "COMMENT" not in out
