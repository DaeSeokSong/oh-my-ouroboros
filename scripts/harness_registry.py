"""Read per-host and per-project values from the harness registry (config/hosts, config/projects).

Why (intent/2026-11-10-unify-project-server-bound.md): scripts stay generic and the values that only fit one
server or one project live in `config/hosts/<hostname>.json` and `config/projects/<project>.json`.
A missing value never falls back to another host or project: without --default the lookup fails loudly
and tells which file and key to add. Format and key rules: config/hosts/README.md, config/projects/README.md.

Shell:  python3 -I scripts/harness_registry.py host <key> [--host NAME] [--default VALUE]
        python3 -I scripts/harness_registry.py project <key> [--project NAME] [--default VALUE]
Python: from harness_registry import lookup; lookup("host", "bench_quiesce.off_cores")
Keys are dot paths into the JSON object. Scalars print as-is, lists and objects print as JSON.
Exit codes: 0 value printed, 1 value missing or registry unreadable, 2 usage error.
"""
import argparse
import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KINDS = {"host": "hosts", "project": "projects"}
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
MISSING = object()


class RegistryError(Exception):
    """Raised when a registry value is missing or the registry file is unusable."""


def current_host() -> str:
    return socket.gethostname()


def current_project(cwd=None) -> str:
    # REF: rules-lazy/mem0-conventions.md §A (git top level, as doc-formats uses)
    real = os.path.realpath(cwd or os.getcwd())
    if real == str(ROOT) or real.startswith(str(ROOT) + os.sep):
        return "claude-global"
    r = subprocess.run(["git", "-C", real, "rev-parse", "--show-toplevel"],
                       check=False, capture_output=True, text=True)
    top = r.stdout.strip() if r.returncode == 0 else ""
    return os.path.basename(top or real)


def lookup(kind, key, name=None, default=MISSING, root=None):
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {sorted(KINDS)}: {kind}")
    name = name or (current_host() if kind == "host" else current_project())
    if not NAME_RE.match(name):
        raise RegistryError(f"registry: invalid {kind} name: {name!r}")
    path = Path(root or ROOT) / "config" / KINDS[kind] / f"{name}.json"
    hint = f"등록부 `{path}` 에 `{key}` 를 더하십시오"
    if not path.is_file():
        if default is not MISSING:
            return default
        raise RegistryError(f"registry: no file for {kind} {name!r}. {hint}(파일이 없으면 새로 만듭니다).")
    try:
        node = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise RegistryError(f"registry: cannot read {path}: {e}") from e
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            if default is not MISSING:
                return default
            raise RegistryError(f"registry: {kind} {name!r} has no `{key}`. {hint}.")
        node = node[part]
    return node


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Print one value from the harness registry.")
    ap.add_argument("kind", choices=sorted(KINDS))
    ap.add_argument("key")
    ap.add_argument("--host")
    ap.add_argument("--project")
    ap.add_argument("--default")
    a = ap.parse_args(argv)
    name = a.host if a.kind == "host" else a.project
    try:
        v = lookup(a.kind, a.key, name, MISSING if a.default is None else a.default)
    except RegistryError as e:
        print(e, file=sys.stderr)
        return 1
    print(v if isinstance(v, (str, int, float)) and not isinstance(v, bool) else json.dumps(v, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
