"""Lint only the lines you changed, read-only (rules-lazy/coding-conventions.md § 주석 규칙, agents/coder.md).

Usage: python3 -I ~/.claude/scripts/lint_changed.py FILE...
  Lines: changed against HEAD in the git repository of the current directory. Untracked files,
  files outside that repository and files when the directory is not a repository are checked whole.
  .py: ruff check --no-fix --no-cache (syntax errors are always shown).
  .sh: bash -n (always shown) and shellcheck -f gcc ("shellcheck 없음" when missing).
  .py .sh .js: comment rules of comment_check.py on the same lines. Other extensions are skipped.
Output: "path:line: [tool code] message" per finding, then RESULT: PASS, RESULT: FAIL (N건)
or RESULT: ERROR (N건); a missing tool is named at the end, as in "RESULT: PASS (건너뜀: ruff)".
Exit: 0 pass, 1 findings, 2 usage error, unreadable input or tool error.
Never modifies or executes the files (bash -n only parses).
"""

import argparse
import importlib.util
import re
import shutil
import subprocess
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "comment_check", Path(__file__).resolve().with_name("comment_check.py")
)
cc = importlib.util.module_from_spec(_spec)
sys.modules["comment_check"] = cc
_spec.loader.exec_module(cc)

DIAG = re.compile(r"^.*?:(\d+):\d+: (.*)$")
BASH_LINE = re.compile(r"line (\d+): (.*)$")


def changed(path):
    root = cc.repo_root(Path.cwd())
    absolute = Path(path).absolute()
    real = absolute.parent.resolve() / absolute.name
    if root is None or not real.is_relative_to(root):
        return None
    return cc.changed_lines(root, real.relative_to(root).as_posix(), False)


def run(cmd):
    return subprocess.run(
        cmd, check=False, capture_output=True, text=True, errors="replace"
    )


def lint_py(path, sel, found, errors, notes):
    ruff = shutil.which("ruff")
    if ruff is None:
        notes.add("ruff 없음: py 린트를 건너뜁니다")
        return
    r = run(
        [
            ruff,
            "check",
            "--no-fix",
            "--no-cache",
            "--quiet",
            "--output-format",
            "concise",
            path,
        ]
    )
    if r.returncode not in (0, 1):
        errors.append(
            f"{path}: [error] ruff exit {r.returncode}: {r.stderr.strip()[:200]}"
        )
        return
    for m in map(DIAG.match, r.stdout.splitlines()):
        if m and (
            sel is None
            or int(m[1]) in sel
            or m[2].startswith(("SyntaxError", "invalid-syntax"))
        ):
            code, _, msg = m[2].partition(" ")
            found.append(
                f"{path}:{m[1]}: [ruff {code.rstrip(':')}] {msg.removeprefix('[*] ')}"
            )


def lint_sh(path, sel, found, errors, notes):
    for line in run(["bash", "-n", path]).stderr.splitlines():
        m = BASH_LINE.search(line)
        found.append(
            f"{path}:{m[1]}: [bash -n] {m[2]}" if m else f"{path}: [bash -n] {line}"
        )
    shellcheck = shutil.which("shellcheck")
    if shellcheck is None:
        notes.add("shellcheck 없음: sh 의 shellcheck 를 건너뜁니다")
        return
    r = run([shellcheck, "-f", "gcc", path])
    if r.returncode not in (0, 1):
        errors.append(
            f"{path}: [error] shellcheck exit {r.returncode}: {r.stderr.strip()[:200]}"
        )
        return
    for m in map(DIAG.match, r.stdout.splitlines()):
        if m and (sel is None or int(m[1]) in sel):
            msg, _, code = m[2].rpartition(" [")
            found.append(f"{path}:{m[1]}: [shellcheck {code.rstrip(']')}] {msg}")


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="lint_changed.py", description="바꾼 줄만 린트한다(읽기 전용)"
    )
    ap.add_argument("files", nargs="+")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    found, errors, notes = [], [], set()
    for path in a.files:
        suffix = Path(path).suffix
        if suffix not in cc.TARGETS:
            continue
        try:
            text = Path(path).read_bytes().decode("utf-8", "replace")
            sel = changed(path)
        except (OSError, RuntimeError) as e:
            errors.append(f"{path}: [error] {e}")
            continue
        if suffix == ".py":
            lint_py(path, sel, found, errors, notes)
        elif suffix == ".sh":
            lint_sh(path, sel, found, errors, notes)
        found += cc.check_text(path, text, sel)
    for note in sorted(notes):
        print(note)
    return cc.finish(found, errors, sorted(note.split()[0] for note in notes))


if __name__ == "__main__":
    sys.exit(main())
