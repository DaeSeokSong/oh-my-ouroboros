"""T41 대장 시험의 수치 반증(변형) 시험.

무엇을: scripts/ 를 임시 폴더에 복사하고(파이썬 shutil, 셸 cp · 리다이렉션을 쓰지 않는다) 사본 소스에 문자열 치환으로
  변형을 하나씩 넣은 뒤, 사본의 tests/test_t41_ledger.py 에서 해당 시험 함수만 돌린다. 기대한 검사가 FAIL 로 나오면 «잡힘»(PASS),
  통과해 버리면 시험이 그 결함을 못 본다는 뜻이라 FAIL 이다. 치환할 원문이 소스에 없으면(코드가 바뀜) 변형 미적용으로 FAIL 이다.
격리: 사본 시험은 test_t41_ledger.py 와 같이 임시 HOME 으로만 돈다. 실제 ~/.claude/_audit · _evolve 에 쓰지 않는다.

빼 둔 변형: 대장 자체 잠금(t41-ledger.sh add 의 flock -w 2) 제거. add 를 부르는 곳은 t41-append.sh 의 record() 하나이고
  그 바깥 `_usage/t41.lock` 이 이미 모든 add 를 직렬화하므로, 대장 잠금을 지워도 시험으로 관측할 수 있는 차이가 없다
  (10병렬 시험도 통과한다). 대장 잠금은 앞으로 다른 호출자가 생길 때를 위한 겹 잠금이다.

실행: python3 ~/.claude/scripts/tests/test_t41_ledger_mutation.py → 실패 0 이면 exit 0
REF: knowledge/harness/code-history/scripts__tests__test_t41_ledger_mutation.py.md
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
results = []

MUTATIONS = [
    ("(a) 경로 검사의 realpath 비교 → 문자열 접두 비교", "t41-ledger.sh",
     [('real="$(readlink -f -- "${p}" 2>/dev/null)" || return 4', 'real="${p}"'),
      ('root="$(readlink -f -- "${PROJ_ROOT}" 2>/dev/null)" || return 4', 'root="${PROJ_ROOT}"')],
     "test_paths", "3 경로(실제 HOME)"),
    ("(b) id 를 10분 억제 키(KEY)에 넣음", "t41-append.sh",
     [('  [[ "${id}" =~ ^[0-9a-f]{8}$ ]] || id=""\n', '  [[ "${id}" =~ ^[0-9a-f]{8}$ ]] || id=""\n  KEY="${KEY} [t41id:${id}]"\n')],
     "test_compat", "6 호환: 10분 억제 키에 id 가 없다"),
    ("(c) 대장 권한 600 검사 제거", "t41-ledger.sh",
     [('[[ "$(stat -c %a "${LEDGER}")" == "600" ]] ||', "true ||")],
     "test_perms", "4 권한: 644 대장에는 add 거부"),
    ("(d) 링크 검사와 존재 검사 순서 뒤집기", "t41-ledger.sh",
     [('  [[ -L "${p}" ]] && return 4\n  [[ -e "${p}" ]] || return 3\n', '  [[ -e "${p}" ]] || return 3\n  [[ -L "${p}" ]] && return 4\n')],
     "test_paths", "3 경로(실제 HOME)"),
    ("(e) id 5회 재생성 제거", "t41-ledger.sh",
     [("for _ in 1 2 3 4 5; do", "for _ in 1; do")],
     "test_id", "1 id: 충돌이면 다시 만든다"),
    ("(f) find-actor 의 timeout 2 제거", "t41-append.sh",
     [('< <(T41_SELF="${SELF:-0}" timeout 2 bash', '< <(T41_SELF="${SELF:-0}" bash')],
     "test_perms", "4 안정성: find-actor 시간 초과"),
    ("(g) 자기 귀속 표지(T41_SELF) 무시", "t41-ledger.sh",
     [('[[ "${T41_SELF:-0}" == 1 ]] && emit', "[[ 0 == 1 ]] && emit")],
     "test_join_review", "2 자기 귀속 표지: 표 밖 역할"),
    ("(h) 최신 후보가 링크면 빈 칸 → 다음 후보로 넘어감", "t41-ledger.sh",
     [("    ncand=$(( ncand + 1 ))\n", '    [[ -L "${f}" ]] && continue\n    ncand=$(( ncand + 1 ))\n')],
     "test_join_review", "2 최신 후보가 링크면 빈 칸"),
]


def check(name, ok, detail=""):
    results.append((name, ok, detail))


def make_copy(tmp):
    dst = Path(tmp) / "scripts"
    shutil.copytree(SCRIPTS, dst, symlinks=True, ignore=shutil.ignore_patterns("__pycache__"))
    return dst


def run_copy(dst, fn):
    r = subprocess.run([sys.executable, str(dst / "tests" / "test_t41_ledger.py"), fn], capture_output=True, text=True,
                       timeout=300, check=False)
    return r.returncode, r.stdout + r.stderr


with tempfile.TemporaryDirectory() as tmp:
    dst = make_copy(tmp)
    fns = sorted({m[3] for m in MUTATIONS})
    r = subprocess.run([sys.executable, str(dst / "tests" / "test_t41_ledger.py"), *fns], capture_output=True, text=True,
                       timeout=300, check=False)
    check(f"대조: 변형 없는 사본에서 {', '.join(fns)} 통과", r.returncode == 0, (r.stdout + r.stderr)[-400:])

for name, fname, subs, fn, want in MUTATIONS:
    with tempfile.TemporaryDirectory() as tmp:
        dst = make_copy(tmp)
        f = dst / fname
        src = f.read_text(encoding="utf-8")
        missing = [old for old, _ in subs if src.count(old) != 1]
        if missing:
            check(f"{name}: 잡힘", False, f"변형 미적용(원문이 정확히 1회 있지 않음): {missing}")
            continue
        for old, new in subs:
            src = src.replace(old, new)
        f.write_text(src, encoding="utf-8")
        rc, out = run_copy(dst, fn)
        caught = rc != 0 and any(ln.startswith("FAIL ") and want in ln for ln in out.splitlines())
        check(f"{name}: 잡힘", caught, f"rc={rc} {out[-400:]}")

fail = 0
for name, ok, detail in results:
    print(f"{'OK  ' if ok else 'FAIL'} {name}")
    if not ok:
        print(f"       실제: {detail[:400]}")
    fail += 0 if ok else 1

print(f"\n{'ALL PASS' if fail == 0 else f'FAIL {fail}'} ({len(results)} checks)")
sys.exit(1 if fail else 0)
