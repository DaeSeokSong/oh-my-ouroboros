"""external_send_preflight.py 패턴 회귀 테스트.

실행: python3 ~/.claude/scripts/tests/test_external_send_preflight.py → 실패 0 이면 exit 0

■ 파악한 계약 (소스 대조 — 추측 아님)
  · 호출: `python3 external_send_preflight.py <작업디렉터리>` — 트리를 훑고, 차단 패턴이
    하나라도 걸리면 exit 1, 아니면 exit 0.
  · 판정은 마지막 «판정:» 줄로 드러난다. 차단이면 "판정: 보내지 마라…", 통과면
    "판정: 통과 — 알려진 위험 패턴 없음". 이 테스트는 그 줄로 판단한다(값은 출력되지 않는다).
  · 확장자와 무관하게 전부 훑는다(2026-10-01). 이진·8MiB 초과·읽기 실패 파일은 «미검사» 로 세어 차단한다.
  · 각 케이스는 **자기만의 임시 폴더**에서 돌린다. 한 폴더에 몰면 어느 파일이 걸렸는지
    구분되지 않아 오탐·미탐을 못 가른다.

■ 케이스
  차단: JSON password · 무따옴표 PASSWORD · token="…" · sk- 키 · ghp_ 키
  통과: `--env TOKEN="$TOKEN"`(변수 참조) · password=example · token=xxx · 일반 텍스트
REF: knowledge/harness/code-history/scripts__tests__test_external_send_preflight.py.md
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPT = Path.home() / ".claude/scripts/external_send_preflight.py"

# WHY: 가짜 비밀 값은 런타임에 조립한다. 소스 파일에 키 모양 리터럴이 있으면
# ci-gate-commit 의 시크릿 탐지가 이 테스트 파일 자체를 막는다(2026-09-08 실측).
_FAKE_VAL = "Sk9w" + "Q2vL" + "p7"
_FAKE_KEY_BODY = "A1b2C3d4" + "E5f6G7h8" + "I9j0K1l2" + "M3n4"
_SK = "sk" + "-" + _FAKE_KEY_BODY
_GHP = "gh" + "p_" + _FAKE_KEY_BODY + "O5p6Q7"

BLOCK_CASES = [
    ("JSON password", "conf.json", '{"user": "svc", "pass' + 'word": "' + _FAKE_VAL + '"}\n'),
    ("무따옴표 PASSWORD", "env.sh", "export PASS" + "WORD=" + _FAKE_VAL + "\n"),
    ('token="…"', "conf.txt", "tok" + 'en="' + _FAKE_VAL + 'zzz"\n'),
    ("sk- 키", "notes.txt", "OPENAI=" + _SK + "\n"),
    ("ghp_ 키", "notes.txt", "GH=" + _GHP + "\n"),
]

PASS_CASES = [
    ("--env TOKEN=\"$TOKEN\" 변수 참조", "run.sh",
     'docker run --env ACCESS_TOKEN="$ACCESS_TOKEN" --env TOKEN=${TOKEN} img\n'),
    ("password=example 문서 예시", "README.txt", 'password=example\n'),
    ("token=xxx 문서 예시", "README.txt", 'token=xxx\n'),
    ("일반 텍스트", "note.txt", '오늘 학습 4판을 발사했고 와쳐를 붙였다.\n'),
]


def verdict(content: str, filename: str) -> tuple[int, str]:
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / filename).write_text(content, encoding="utf-8")
        r = subprocess.run([sys.executable, str(SCRIPT), td], capture_output=True, text=True, check=False)
    line = next((ln for ln in r.stdout.splitlines() if ln.startswith("판정:")), "(판정 줄 없음)")
    return r.returncode, line


fail = 0

for name, fn, content in BLOCK_CASES:
    rc, line = verdict(content, fn)
    ok = rc == 1 and line.startswith("판정: 보내지 마라")
    fail += 0 if ok else 1
    print(f"{'OK ' if ok else 'FAIL'} [차단] {name}{'' if ok else f' (rc={rc} {line})'}")

for name, fn, content in PASS_CASES:
    rc, line = verdict(content, fn)
    ok = rc == 0 and line.startswith("판정: 통과")
    fail += 0 if ok else 1
    print(f"{'OK ' if ok else 'FAIL'} [통과] {name}{'' if ok else f' (rc={rc} {line})'}")

def verdict_tree(files: dict[str, bytes], chmod_zero: tuple[str, ...] = ()) -> tuple[int, str, str]:
    with tempfile.TemporaryDirectory() as td:
        for rel, data in files.items():
            p = Path(td) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        for rel in chmod_zero:
            (Path(td) / rel).chmod(0)
        r = subprocess.run([sys.executable, str(SCRIPT), td], capture_output=True, text=True, check=False)
        for rel in chmod_zero:
            (Path(td) / rel).chmod(0o600)
    line = next((ln for ln in r.stdout.splitlines() if ln.startswith("판정:")), "(판정 줄 없음)")
    return r.returncode, line, r.stdout


SECRET = ("tok" + 'en="' + _FAKE_VAL + 'zzz"\n').encode()
EXTRA = [
    ("목록 밖 확장자(.conf)의 비밀 → 차단", {"app.conf": SECRET}, (), "block", ""),
    ("목록 밖 확장자(.pem)의 개인키 → 차단", {"k.pem": b"-----BEGIN RSA PRIV" + b"ATE KEY-----\nxx\n"}, (), "block", ""),
    ("이진 파일 → 미검사 차단", {"a.bin": b"\x00\x01\x02binary"}, (), "block", "미검사"),
    ("8MiB 초과 텍스트 → 미검사 차단", {"big.txt": b"a" * ((8 << 20) + 1)}, (), "block", "미검사"),
    ("파일 이름의 DICOM UID → 차단", {"1.2.840.113619.2.55.3.txt": b"ok\n"}, (), "block", ""),
    ("폴더 이름의 DICOM UID → 차단", {"1.2.840.113619.2.55.3/note.txt": b"ok\n"}, (), "block", ""),
    ("목록 밖 확장자의 깨끗한 텍스트 + 일반 텍스트 → 통과", {"app.conf": b"debug=true\n", "n.txt": b"ok\n"}, (), "pass", ""),
]
if os.geteuid() != 0:
    EXTRA.append(("읽을 수 없는 파일 → 미검사 차단", {"locked.txt": b"ok\n"}, ("locked.txt",), "block", "미검사"))
for name, files, chm, want, must in EXTRA:
    rc, line, out = verdict_tree(files, chm)
    ok = (rc == 1 and line.startswith("판정: 보내지 마라") and must in out) if want == "block" else (rc == 0 and line.startswith("판정: 통과"))
    fail += 0 if ok else 1
    print(f"{'OK ' if ok else 'FAIL'} [{'차단' if want == 'block' else '통과'}] {name}{'' if ok else f' (rc={rc} {line})'}")

with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as other:
    (Path(other) / "secret.txt").write_text("ok\n", encoding="utf-8")
    (Path(td) / "n.txt").write_text("ok\n", encoding="utf-8")
    os.symlink(other, Path(td) / "linked")
    r = subprocess.run([sys.executable, str(SCRIPT), td], capture_output=True, text=True, check=False)
    ok = r.returncode == 1 and "폴더 심볼릭 링크" in r.stdout
    fail += 0 if ok else 1
    print(f"{'OK ' if ok else 'FAIL'} [차단] 폴더 심볼릭 링크 → 미검사 차단{'' if ok else f' (rc={r.returncode})'}")
    (Path(td) / "linked").unlink()
    r = subprocess.run([sys.executable, str(SCRIPT), td], capture_output=True, text=True, check=False)
    ok = r.returncode == 0
    fail += 0 if ok else 1
    print(f"{'OK ' if ok else 'FAIL'} [통과] 링크 없는 같은 트리 → 통과{'' if ok else f' (rc={r.returncode})'}")

# WHY: 성능: 수백 파일·2~3MB 꾸러미는 수 초 안에 끝나야 한다(게이트 마감 50초 공유)
t0 = time.monotonic()
rc, line, out = verdict_tree({f"d{i % 10}/f{i}.md": ("본문 줄입니다.\n" * 60).encode() for i in range(300)})
dt = time.monotonic() - t0
ok = rc == 0 and dt < 5
fail += 0 if ok else 1
print(f"{'OK ' if ok else 'FAIL'} [성능] 300파일 ~{300 * 60 * 17 // 1000}KB 통과 {dt:.2f}초{'' if ok else f' (rc={rc} {line})'}")

total = len(BLOCK_CASES) + len(PASS_CASES) + len(EXTRA) + 3
print(f"\n{'ALL PASS' if fail == 0 else f'FAIL {fail}'} ({total} cases)")
sys.exit(1 if fail else 0)
