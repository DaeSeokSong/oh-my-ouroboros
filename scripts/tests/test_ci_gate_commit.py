"""ci-gate-commit.sh 회귀 테스트 — 임시 git 저장소에 파일을 stage 해 훅을 돌린다.

실행: python3 ~/.claude/scripts/tests/test_ci_gate_commit.py → 실패 0 이면 exit 0
CI_GATE_HOOK 에 훅 경로를 주면 그 사본을 시험한다(수정 전 사본 대조용).
시크릿 꼴 문자열은 조각을 이어 붙여 만든다(이 파일 자체가 훅 검사 대상이라 그대로 적으면 자기 커밋이 막힌다).
REF: knowledge/harness/code-history/scripts__tests__test_ci_gate_commit.py.md
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HOOK = Path(os.environ.get("CI_GATE_HOOK") or Path(__file__).resolve().parents[1] / "ci-gate-commit.sh")
KEY = "API" + "_KEY"
TOK = "TO" + "KEN"
PW = "pass" + "word"


def run_case(files: dict[str, str], base: dict[str, str] | None = None, delete: tuple[str, ...] = (), old_gone: tuple[str, ...] = (),
             exec_files: tuple[str, ...] = (), sub: str = "", via_commit: bool = False):
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null",
                   GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        subprocess.run(["git", "init", "-q", tmp], check=True, capture_output=True, env=env)
        if base:
            for name, body in base.items():
                p = Path(tmp) / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(body, encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=tmp, check=True, capture_output=True, env=env)
            subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=tmp, check=True, capture_output=True, env=env)
            if old_gone:
                for name in old_gone:
                    (Path(tmp) / name).unlink()
                subprocess.run(["git", "add", "-A"], cwd=tmp, check=True, capture_output=True, env=env)
                subprocess.run(["git", "commit", "-q", "-m", "drop"], cwd=tmp, check=True, capture_output=True, env=env)
            for name in delete:
                (Path(tmp) / name).unlink()
        for name, body in files.items():
            p = Path(tmp) / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8")
            if name in exec_files:
                p.chmod(0o755)
        subprocess.run(["git", "add", "-A"], cwd=tmp, check=True, capture_output=True, env=env)
        cwd = Path(tmp) / sub
        if via_commit:
            hook = Path(tmp) / ".git" / "hooks" / "pre-commit"
            hook.parent.mkdir(parents=True, exist_ok=True)
            hook.write_text(f'#!/bin/sh\nexec bash "{HOOK.resolve()}"\n', encoding="utf-8")
            hook.chmod(0o755)
            r = subprocess.run(["git", "commit", "-q", "-m", "t"], check=False, cwd=cwd, capture_output=True, text=True, env=env)
        else:
            r = subprocess.run(["bash", str(HOOK.resolve())], check=False, cwd=cwd, capture_output=True, text=True, env=env)
        return r.returncode, (r.stdout + r.stderr)


REAL = "abcdefgh12345678"
CASES = [
    ("비ASCII 이름 파일의 시크릿 → 차단", {"한글노트.md": f'{KEY}="{REAL}"\n'}, 1, "SECRET DETECTED"),
    ("비ASCII 이름 파일 깨끗 → 통과", {"한글노트.md": "안녕\n"}, 0, "PASSED"),
    ("개행이 든 이름 → fail-closed 차단", {"a\nb.md": "x\n"}, 1, "SKIPPED"),
    ("JSON 따옴표 키 대입 → 차단", {"c.json": f'{{"{PW}": "{REAL}"}}\n'}, 1, "SECRET DETECTED"),
    ("md 따옴표 키 대입 → 차단", {"n.md": f'"{PW}": "{REAL}"\n'}, 1, "SECRET DETECTED"),
    ("한 줄 자리표시자 앞·실제 값 뒤 → 차단", {"n.md": f'{KEY}="<YOUR_KEY_HERE>" {TOK}="{REAL}"\n'}, 1, "SECRET DETECTED"),
    ("한 줄 모두 자리표시자 → 통과", {"n.md": f'{KEY}="<YOUR_KEY_HERE>" {TOK}="<YOUR_TOKEN_HERE>"\n'}, 0, "PASSED"),
]

fail = 0
for name, files, want, phrase in CASES:
    rc, out = run_case(files)
    ok = rc == want and phrase in out
    fail += 0 if ok else 1
    print(f"{'OK ' if ok else 'FAIL'} {name}: exit {rc} (기대 {want})" + ("" if ok else f"\n     {out[:300]}"))

DEL = "agents/designer.md"
POINTER = f"see {DEL}\n"
UNRELATED = {"note.md": "무관한 새 파일\n"}
RECORDS = {"intent/a.md": POINTER, "_audit/b.md": POINTER, "docs/c.md": POINTER, "graphify-out/obsidian/설계 노트.md": POINTER}
BLOCK_MSG = "포인터를 고친 뒤 재커밋"
POINTER_CASES = [
    ("삭제 파일을 기록 폴더 문서만 가리킴 → 통과", {DEL: "x\n", **RECORDS}, 0, ["PASSED"], ["BROKEN POINTER"]),
    ("삭제 파일을 rules/ 문서가 가리킴 → 깨진 포인터 문구로 차단", {DEL: "x\n", "rules/r.md": POINTER}, 1,
     ["BROKEN POINTER", "rules/r.md", BLOCK_MSG], ["secret 탐지", "키 회전·제거 후 재커밋"]),
    ("삭제 파일을 skills/ 문서가 가리킴 → 차단", {DEL: "x\n", "skills/s/SKILL.md": POINTER}, 1,
     ["BROKEN POINTER", "skills/s/SKILL.md", BLOCK_MSG], ["secret 탐지"]),
    # WHY: skills/ 는 경로 순서상 기록 4건 뒤라서 head -3 이전에 거르지 않으면 가려진다
    ("기록 4건 + 살아 있는 문서 1건이 함께 가리킴 → 차단", {DEL: "x\n", **RECORDS, "skills/s/SKILL.md": POINTER}, 1,
     ["BROKEN POINTER", "skills/s/SKILL.md", BLOCK_MSG], ["intent/a.md", "graphify-out"]),
]
for name, base, want, musts, mustnots in POINTER_CASES:
    rc, out = run_case(UNRELATED, base=base, delete=(DEL,))
    ok = rc == want and all(m in out for m in musts) and not any(m in out for m in mustnots)
    fail += 0 if ok else 1
    print(f"{'OK ' if ok else 'FAIL'} {name}: exit {rc} (기대 {want})" + ("" if ok else f"\n     {out[:400]}"))

GONE = "agents/old-gone.md"
NEVER = "agents/never-existed.md"
REV_CASES = [
    ("intent/ 문서가 이번 커밋에서 삭제되는 파일을 가리킴 → 통과",
     {"intent/i.md": POINTER + "개정\n"}, {DEL: "x\n", "intent/i.md": POINTER}, (DEL,), (), 0, ["PASSED"]),
    ("intent/ 문서가 예전 커밋에서 이미 삭제된 파일을 가리킴 → 통과",
     {"intent/i.md": f"see {GONE}\n"}, {GONE: "x\n", "note0.md": "x\n"}, (), (GONE,), 0, ["PASSED"]),
    ("intent/ 문서가 한 번도 없던 경로를 가리킴 → 차단",
     {"intent/i.md": f"see {NEVER}\n"}, {"note0.md": "x\n"}, (), (), 1, ["BROKEN POINTER", NEVER]),
    ("rules/ 문서가 삭제되는 파일을 가리킴 → 차단",
     {"rules/r.md": POINTER + "개정\n"}, {DEL: "x\n", "rules/r.md": POINTER}, (DEL,), (), 1, ["BROKEN POINTER", "rules/r.md"]),
]
for name, files, base, delete, old_gone, want, musts in REV_CASES:
    rc, out = run_case(files, base=base, delete=delete, old_gone=old_gone)
    ok = rc == want and all(m in out for m in musts)
    fail += 0 if ok else 1
    print(f"{'OK ' if ok else 'FAIL'} {name}: exit {rc} (기대 {want})" + ("" if ok else f"\n     {out[:400]}"))

rc, out = run_case({"n.md": f'{KEY}="{REAL}"\n'}, base={DEL: "x\n", "rules/r.md": POINTER}, delete=(DEL,))
ok = rc == 1 and "secret 탐지" in out and "키 회전·제거 후 재커밋" in out and BLOCK_MSG not in out
fail += 0 if ok else 1
print(f"{'OK ' if ok else 'FAIL'} 시크릿 + 깨진 포인터 동시 → 시크릿 문구 유지: exit {rc} (기대 1)" + ("" if ok else f"\n     {out[:400]}"))

SHEBANG_PY = "#!/usr/bin/env python3\nprint(1)\n"
EXE_CASES = [
    ("100755 + shebang .py → EXE001 없이 통과", SHEBANG_PY, True, 0, "PASSED", "EXE001"),
    ("100644 + shebang .py → EXE001 로 차단", SHEBANG_PY, False, 1, "EXE001", "PASSED"),
    ("100755 + shebang 없는 .py → EXE002 로 차단", "print(1)\n", True, 1, "EXE002", "PASSED"),
]
if shutil.which("ruff"):
    for name, body, is_exec, want, must, mustnot in EXE_CASES:
        rc, out = run_case({"tool.py": body}, exec_files=("tool.py",) if is_exec else ())
        ok = rc == want and must in out and mustnot not in out
        fail += 0 if ok else 1
        print(f"{'OK ' if ok else 'FAIL'} {name}: exit {rc} (기대 {want})" + ("" if ok else f"\n     {out[:400]}"))
else:
    print("SKIP 실행 권한 lint 3건: ruff 없음")

SCRIPTS = Path(__file__).resolve().parents[1]
CHECKER = {f"scripts/{n}": (SCRIPTS / n).read_text(encoding="utf-8") for n in ("intent_check.py", "spec_check.py")}
INTENT_OK = ("# intent: t\n\n- 상태: 초안\n\n## 1. 문제\nx\n\n## 2. 제안 결과\n- 기준\n\n### 범위 밖\n- 모바일\n\n"
             "## 3. 영향\nx\n\n## 4. 제약\nx\n\n## 5. 열린 질문\nx\n\n## 6. 전제\nx\n")
INTENT_BAD = INTENT_OK.replace("### 범위 밖\n- 모바일\n\n", "")
WARN = "INTENT CHECK"
INTENT_CASES = [
    ("새 의뢰서 범위 밖 누락 → 경고만, 통과", {"intent/new.md": INTENT_BAD}, CHECKER, 0,
     [WARN, "intent/new.md", "범위 밖 소절 누락", "PASSED"], []),
    ("새 의뢰서 양식 맞음 → 경고 없음", {"intent/new.md": INTENT_OK}, CHECKER, 0, ["PASSED"], [WARN]),
    ("수정된 옛 의뢰서 → 검사 안 함", {"intent/old.md": INTENT_BAD + "개정\n"}, {**CHECKER, "intent/old.md": INTENT_BAD}, 0,
     ["PASSED"], [WARN]),
    ("공백 · 한글 이름 새 의뢰서 → 이름 그대로 경고", {"intent/새 의뢰서 a.md": INTENT_BAD}, CHECKER, 0,
     [WARN, "intent/새 의뢰서 a.md", "PASSED"], []),
    ("intent/README.md 추가 → 검사 안 함", {"intent/README.md": "목록\n"}, CHECKER, 0, ["PASSED"], [WARN]),
    ("검사기 없는 저장소 → 조용히 통과", {"intent/new.md": INTENT_BAD}, {"note0.md": "x\n"}, 0, ["PASSED"], [WARN]),
]
for name, files, base, want, musts, mustnots in INTENT_CASES:
    rc, out = run_case(files, base=base)
    ok = rc == want and all(m in out for m in musts) and not any(m in out for m in mustnots)
    fail += 0 if ok else 1
    print(f"{'OK ' if ok else 'FAIL'} {name}: exit {rc} (기대 {want})" + ("" if ok else f"\n     {out[:400]}"))

SUBDIR = {**CHECKER, "sub/k.md": "x\n"}
INTENT_COUNT_CASES = [
    ("새 의뢰서 두 개 모두 BAD → 경고 두 건", {"intent/a.md": INTENT_BAD, "intent/b.md": INTENT_BAD}, CHECKER, {}, 2),
    ("spec_check.py 없는 저장소(검사기 import 실패) → 경고 없음", {"intent/new.md": INTENT_BAD},
     {"scripts/intent_check.py": CHECKER["scripts/intent_check.py"]}, {}, 0),
    ("하위 폴더에서 git commit → 경고 한 건", {"intent/new.md": INTENT_BAD}, SUBDIR, {"sub": "sub", "via_commit": True}, 1),
    ("하위 폴더에서 훅 직접 실행 → 경고 한 건", {"intent/new.md": INTENT_BAD}, SUBDIR, {"sub": "sub"}, 1),
]
for name, files, base, kw, want_warns in INTENT_COUNT_CASES:
    rc, out = run_case(files, base=base, **kw)
    ok = rc == 0 and out.count(WARN) == want_warns
    fail += 0 if ok else 1
    print(f"{'OK ' if ok else 'FAIL'} {name}: exit {rc} · 경고 {out.count(WARN)}건 (기대 0 · {want_warns}건)" + ("" if ok else f"\n     {out[:400]}"))

print(f"\n{'ALL PASS' if fail == 0 else f'FAIL {fail}'} ({len(CASES) + len(POINTER_CASES) + len(REV_CASES) + 1 + (len(EXE_CASES) if shutil.which('ruff') else 0) + len(INTENT_CASES) + len(INTENT_COUNT_CASES)} cases)")
sys.exit(1 if fail else 0)
