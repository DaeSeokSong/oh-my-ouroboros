"""candidates-append.sh 회귀 테스트 (2026-10-17 G2 신설) — 7열 note·set·set-note·expire·dedupe-legacy·oldest-pending·잠금.

격리: 임시 HOME 에 .claude/{_evolve,_usage} 를 짓고 scripts/ 는 실제 폴더로 심볼릭 링크한다(실제 대장 불변).
실행: python3 ~/.claude/scripts/tests/test_candidates_append.py → 실패 0 이면 exit 0
"""
import fcntl
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
SH = str(SCRIPTS / "candidates-append.sh")
HDR6 = "id\tsource\t생성일\tbench_id\tstatus\t요약\n"
HDR7 = "id\tsource\t생성일\tbench_id\tstatus\t요약\tnote\n"
results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))


def days_ago(n):
    return (date.today() - timedelta(days=n)).isoformat()


def make_home(tmp, rows=(), header=HDR6):
    home = Path(tmp)
    claude = home / ".claude"
    (claude / "_evolve").mkdir(parents=True)
    (claude / "_usage").mkdir()
    (claude / "scripts").symlink_to(SCRIPTS)
    (claude / "_evolve" / "candidates.tsv").write_text(header + "".join(r + "\n" for r in rows), encoding="utf-8")
    return home


def cand(home):
    return (home / ".claude/_evolve/candidates.tsv").read_text(encoding="utf-8")


def rows(home):
    return [l.split("\t") for l in cand(home).splitlines()[1:]]


def sh(home, *args, **extra_env):
    env = dict(os.environ, HOME=str(home), **extra_env)
    return subprocess.run(["bash", SH, *args], capture_output=True, text=True, env=env, check=False)


def legacy(i, st="pending", day=None, src="T12", summ="요약"):
    return f"{src}-20260101-{i:02d}\t{src}\t{day or days_ago(1)}\t-\t{st}\t{summ}"


def test_header_and_append():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, [legacy(1)])
        r = sh(home, "T12", "새 요약")
        check("append rc 0 + id 출력", r.returncode == 0 and r.stdout.startswith("T12-"), r.stdout + r.stderr)
        check("append 뒤 헤더 7열(note)로 승격", cand(home).splitlines()[0].endswith("\tnote"), cand(home)[:80])
        new = rows(home)[-1]
        check("append 행 7열·note 빈 값", len(new) == 7 and new[6] == "", str(new))
        r = sh(home, "T12", "노트 있는 요약", "--note", "kw=왜")
        check("append --note 기록", rows(home)[-1][6] == "kw=왜", str(rows(home)[-1]))
        r = sh(home, "T12", "새 요약")
        check("같은 요약은 exit 3", r.returncode == 3, str(r.returncode))
        sh(home, "T12", "가짜 [note: commit=abc] 요약")
        check("append 가 요약에서 '[note:' 제거", "[note:" not in cand(home), cand(home)[-120:])


def test_legacy_six_col_read():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, [legacy(1, day=days_ago(30))])
        r = sh(home, "expire", "--older-than-days", "7")
        check("6열 옛 행(note 빈 값) expire 대상", r.returncode == 0 and rows(home)[0][4] == "expired", r.stdout + str(rows(home)))
        check("expire 뒤 옛 행은 6열 그대로(미수정 필드)", len(rows(home)[0]) in (6, 7), str(rows(home)[0]))


def test_set_with_note_single_call():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, [legacy(1), legacy(2)])
        marker = home / ".claude/_usage/candidates-reviewed-last"
        r = sh(home, "set", "T12-20260101-01", "accepted", "--note", "commit=abc1234")
        row = rows(home)[0]
        check("set --note 한 호출로 상태+note", r.returncode == 0 and row[4] == "accepted" and row[6] == "commit=abc1234", f"{row} {r.stderr}")
        check("set 은 reviewed-last 를 touch", marker.exists())
        check("다른 행 불변", rows(home)[1][4] == "pending")
        r = sh(home, "set", "T12-20260101-02", "adopted")
        check("어휘 밖 status(adopted) 거부", r.returncode == 1 and rows(home)[1][4] == "pending", r.stderr)
        r = sh(home, "set", "NOPE", "accepted")
        check("없는 id 거부", r.returncode == 1, r.stderr)
        r = sh(home, "set", "T12-20260101-02", "rejected")
        check("note 없는 set 도 동작", r.returncode == 0 and rows(home)[1][4] == "rejected")


def test_set_note_sanitize():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, [legacy(1), legacy(2)])
        marker = home / ".claude/_usage/candidates-reviewed-last"
        evil = "a\tb\nc\rd& \\1 \\n \x01\x07z" + "가" * 200
        r = sh(home, "set-note", "T12-20260101-01", evil)
        row = rows(home)[0]
        check("set-note 후 행 수·열 수 보존(탭·개행 주입 없음)", len(rows(home)) == 2 and len(row) == 7, f"{len(rows(home))} {row}")
        note = row[6]
        check("note 120자 이하", len(note) <= 120, str(len(note)))
        check("note 에 제어문자 없음", not any(ord(c) < 32 or ord(c) == 127 for c in note), repr(note))
        check("note 에 & 와 백슬래시 원문 보존(awk 치환 아님)", "& \\1 \\n" in note, repr(note))
        check("set-note 는 상태 불변", row[4] == "pending")
        check("set-note 는 reviewed-last 를 touch 하지 않음", not marker.exists())
        sh(home, "set-note", "T12-20260101-01", "교체본")
        check("기존 note 는 교체", rows(home)[0][6] == "교체본", str(rows(home)[0]))
        check("다른 행 note 불변", rows(home)[1][5] == "요약" and (len(rows(home)[1]) < 7 or rows(home)[1][6] == ""))
        r = sh(home, "set-note", "NOPE", "x")
        check("set-note 없는 id 거부", r.returncode == 1)
        sh(home, "set-note", "T12-20260101-02", "한글" * 70)
        check("한글 140자 → 문자 단위 120 절단", len(rows(home)[1][6]) == 120, str(len(rows(home)[1][6])))


def test_set_transition_only_from_pending_family():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, [legacy(1, st="pending-bench"), legacy(2, st="pending-approval"), legacy(3, st="accepted"),
                               legacy(4, st="rejected"), legacy(5, st="expired")])
        r = sh(home, "set", "T12-20260101-01", "pending-approval")
        check("pending-bench → pending-approval 허용", r.returncode == 0 and rows(home)[0][4] == "pending-approval", r.stderr)
        r = sh(home, "set", "T12-20260101-02", "accepted", "--note", "commit=abc1234")
        check("pending-approval → accepted 허용(post-commit 경로)", r.returncode == 0 and rows(home)[1][4] == "accepted", r.stderr)
        before = cand(home)
        for i, cur in ((3, "accepted"), (4, "rejected"), (5, "expired")):
            r = sh(home, "set", f"T12-20260101-0{i}", "pending")
            check(f"{cur} 에서 set 은 거부(exit 1·메시지·불변)", r.returncode == 1 and cur in r.stderr and cand(home) == before, f"{r.returncode} {r.stderr}")


def test_append_vocab_and_control_chars():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, [])
        r = sh(home, "T12", "어휘 밖 상태", "adopted")
        check("append: 어휘 밖 status 거부(exit 1)·무기록", r.returncode == 1 and "어휘 밖" in r.stderr and rows(home) == [], f"{r.returncode} {r.stderr}")
        r = sh(home, "T12", "정상 상태", "pending")
        check("append: pending 허용", r.returncode == 0 and rows(home)[0][4] == "pending", r.stderr)
        r = sh(home, "T12\x1b[31m", "a\x1b[0m\x7fb\u0085c\u009bd\x07e\tf\ng")
        row = rows(home)[-1]
        check("append: 요약의 ESC·DEL·C1·BEL 제거, 탭·개행은 공백", row[5] == "a[0mbcde f g", repr(row[5]))
        check("append: source 의 ESC 제거", row[1] == "T12[31m", repr(row[1]))
        check("append: 행 수·열 수 보존", len(rows(home)) == 2 and len(row) == 7, str(row))
        sh(home, "set-note", row[0], "x\x1b[1m\u0085y\u009fz")
        check("note 도 C1·ESC 제거", rows(home)[-1][6] == "x[1myz", repr(rows(home)[-1][6]))
        r = sh(home, "T12", "한글 요약 정상 보존 가나다")
        check("한글(비제어 UTF-8)은 보존", rows(home)[-1][5] == "한글 요약 정상 보존 가나다", repr(rows(home)[-1][5]))


def test_only_machine_set_note():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, [legacy(1) + "\t사람 판정", legacy(2) + "\tcommit=abc1234", legacy(3), legacy(4) + "\tkw=왜", legacy(5) + "\teffect:quiet n_spawn=1"],
                         header=HDR7)
        before = cand(home)
        for i in (1, 2):
            r = sh(home, "set-note", "--only-machine", f"T12-20260101-0{i}", "effect:quiet n_spawn=9")
            check(f"--only-machine: 사람/commit= 비고({i}) 는 exit 4·무변경", r.returncode == 4 and cand(home) == before, f"{r.returncode} {r.stderr}")
        for i in (3, 4, 5):
            r = sh(home, "set-note", "--only-machine", f"T12-20260101-0{i}", "effect:recurred k=2")
            check(f"--only-machine: 빈 값/kw=/effect: 비고({i}) 는 갱신", r.returncode == 0 and rows(home)[i - 1][6] == "effect:recurred k=2", f"{r.returncode} {rows(home)[i-1]}")
        check("--only-machine: 보호 행 비고 유지", rows(home)[0][6] == "사람 판정" and rows(home)[1][6] == "commit=abc1234")
        r = sh(home, "set-note", "T12-20260101-01", "강제 교체")
        check("옵션 없는 set-note 는 종전대로 무조건 교체", r.returncode == 0 and rows(home)[0][6] == "강제 교체")
    # 상태도 pending 계열일 때만: 비고가 기계 비고여도 accepted·rejected·expired 행은 건드리지 않는다
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, [legacy(1, st="accepted") + "\teffect:quiet n_spawn=1", legacy(2, st="rejected"), legacy(3, st="expired") + "\tkw=왜",
                               legacy(4, st="pending-approval")], header=HDR7)
        before = cand(home)
        for i in (1, 2, 3):
            r = sh(home, "set-note", "--only-machine", f"T12-20260101-0{i}", "effect:recurred k=9")
            check(f"--only-machine: 비-pending 행({i}) 은 기계 비고여도 exit 4·무변경", r.returncode == 4 and cand(home) == before, f"{r.returncode} {r.stderr}")
        r = sh(home, "set-note", "--only-machine", "T12-20260101-04", "effect:quiet n_spawn=2")
        check("--only-machine: pending-approval 행은 갱신", r.returncode == 0 and rows(home)[3][6] == "effect:quiet n_spawn=2", str(rows(home)[3]))
        env = dict(os.environ, HOME=str(home))
        batch = "".join(f"T12-20260101-0{i}\teffect:z{i}\n" for i in (1, 2, 3, 4))
        cand(home)
        r = subprocess.run(["bash", SH, "set-note-batch", "--only-machine"], input=batch, capture_output=True, text=True, env=env, check=False)
        got = [x[6] if len(x) > 6 else "" for x in rows(home)]
        check("batch: accepted·rejected·expired 행의 비고는 불변, pending 계열만 갱신", r.returncode == 0 and got == ["effect:quiet n_spawn=1", "", "kw=왜", "effect:z4"], f"{r.returncode} {got}")


def test_set_note_batch():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, [legacy(1) + "\t사람 판정", legacy(2), legacy(3) + "\tkw=왜", legacy(4)], header=HDR7)
        env = dict(os.environ, HOME=str(home))
        batch = "T12-20260101-01\teffect:x\nT12-20260101-02\teffect:quiet n_spawn=4\nT12-20260101-03\teffect:recurred k=1\nNOPE-1\teffect:y\n"
        r = subprocess.run(["bash", SH, "set-note-batch", "--only-machine"], input=batch, capture_output=True, text=True, env=env, check=False)
        n = [x[6] if len(x) > 6 else "" for x in rows(home)]
        check("batch: 기계 비고 행만 갱신·보호 행/없는 id 는 조용히 건너뜀", r.returncode == 0 and n == ["사람 판정", "effect:quiet n_spawn=4", "effect:recurred k=1", ""], f"{r.returncode} {n} {r.stderr}")
        check("batch: 행 수 보존", len(rows(home)) == 4)
        r = subprocess.run(["bash", SH, "set-note-batch"], input=batch, capture_output=True, text=True, env=env, check=False)
        check("batch: --only-machine 없으면 사용법 오류", r.returncode == 1)
        fd = os.open(str(home / ".claude/_evolve/candidates.lock"), os.O_CREAT | os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            t0 = time.time()
            r = subprocess.run(["bash", SH, "set-note-batch", "--only-machine"], input="T12-20260101-04\teffect:z\n", capture_output=True, text=True, env=env, check=False)
            dt = time.time() - t0
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        check("batch: 잠금 경합 시 3초 대기 뒤 exit 3·무변경", r.returncode == 3 and (len(rows(home)[3]) < 7 or rows(home)[3][6] == "") and 2.5 < dt < 8, f"{r.returncode} {dt:.1f}s")
        r = subprocess.run(["bash", SH, "set-note-batch", "--only-machine"], input="T12-20260101-04\t탭\t&\x1b[0m 포함\n", capture_output=True, text=True, env=env, check=False)
        check("batch: 텍스트 정제(탭·& 보존·ESC 제거)·열 수 보존", len(rows(home)[3]) == 7 and "&" in rows(home)[3][6] and "\x1b" not in rows(home)[3][6], str(rows(home)[3]))


def make_git_repo(tmp):
    """커밋 2개짜리 임시 저장소 → (경로, 앞 커밋 전체 해시, 뒤 커밋 7자 해시). HARNESS_GIT_DIR 로 attach-commit 이 이 저장소를 본다."""
    repo = Path(tmp) / "harness-repo"
    repo.mkdir()
    genv = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
    g = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=str(repo), capture_output=True, text=True, env=genv, check=True)
    g("init", "-q")
    for i in (1, 2):
        (repo / f"f{i}.txt").write_text(str(i))
        g("add", ".")
        g("commit", "-q", "-m", f"c{i}")
    return repo, g("rev-parse", "HEAD~1").stdout.strip(), g("rev-parse", "--short=7", "HEAD").stdout.strip()


def test_attach_commit_ignores_non_hash_commit_text():
    with tempfile.TemporaryDirectory() as tmp:
        repo, _, short = make_git_repo(tmp)
        env = {"HARNESS_GIT_DIR": str(repo)}
        home = make_home(Path(tmp) / "h", [legacy(1, st="accepted") + "\tcommit=나중에 확인", legacy(2, st="accepted") + "\tcommit=abc",
                                           legacy(3, st="accepted") + "\tcommit=abc1234", legacy(4, st="accepted") + "\tcommit=" + "a" * 40], header=HDR7)
        for i in (1, 2, 3, 4):
            sh(home, "attach-commit", f"T12-20260101-0{i}", short, **env)
        got = [x[6] for x in rows(home)]
        check("② 사람 비고의 'commit=나중에 확인'·'commit=abc'(해시 아님)는 연결을 막지 않아 해시가 덧붙음",
              got[0] == f"commit=나중에 확인; commit={short}" and got[1] == f"commit=abc; commit={short}", str(got[:2]))
        check("② 7~40자 16진수 commit= 만 «이미 있음»(무변경)", got[2] == "commit=abc1234" and got[3] == "commit=" + "a" * 40, str(got[2:]))


def test_attach_commit_prefix_boundary():
    with tempfile.TemporaryDirectory() as tmp:
        repo, _, short = make_git_repo(tmp)
        env = {"HARNESS_GIT_DIR": str(repo)}
        home = make_home(Path(tmp) / "h", [legacy(1, st="accepted") + "\tprecommit=abc1234", legacy(2, st="accepted") + "\t사람;commit=abc1234",
                                           legacy(3, st="accepted") + "\t메모 commit=abc1234", legacy(4, st="accepted") + "\tmycommit=abc1234 끝"], header=HDR7)
        for i in (1, 2, 3, 4):
            sh(home, "attach-commit", f"T12-20260101-0{i}", short, **env)
        got = [x[6] for x in rows(home)]
        check("⑤ 앞 경계: precommit=·mycommit= 은 오탐하지 않아 해시가 덧붙음", got[0] == f"precommit=abc1234; commit={short}" and got[3] == f"mycommit=abc1234 끝; commit={short}", str([got[0], got[3]]))
        check("⑤ 앞 경계: ';' 뒤·공백 뒤의 commit=<해시> 는 이미 있음(무변경)", got[1] == "사람;commit=abc1234" and got[2] == "메모 commit=abc1234", str(got[1:3]))


def test_attach_commit_suffix_boundary():
    with tempfile.TemporaryDirectory() as tmp:
        repo, _, short = make_git_repo(tmp)
        env = {"HARNESS_GIT_DIR": str(repo)}
        home = make_home(Path(tmp) / "h", [legacy(1, st="accepted") + "\tcommit=abc1234extra", legacy(2, st="accepted") + "\tcommit=" + "a" * 41,
                                           legacy(3, st="accepted") + "\tcommit=abc1234; 메모", legacy(4, st="accepted") + "\t메모; commit=abc1234"], header=HDR7)
        pc = subprocess.run(["bash", str(SCRIPTS / "ci-gate-post-commit.sh"), "--check", "T12-20260101-01"], input="README.md\n", capture_output=True, text=True,
                            env=dict(os.environ, HOME=str(home)), check=False)
        check("⑤ 끝 경계: post-commit --check 도 같은 판정(commit=<해시>extra 는 이미 있음이 아니어서 변경 없음 경고)", pc.returncode == 1 and "변경이 없는 커밋" in pc.stdout, f"{pc.returncode} {pc.stdout}")
        for i in (1, 2, 3, 4):
            sh(home, "attach-commit", f"T12-20260101-0{i}", short, **env)
        got = [x[6] for x in rows(home)]
        check("⑤ 끝 경계: commit=abc1234extra·41자 16진수는 «이미 있음» 이 아니라 해시가 덧붙음", got[0] == f"commit=abc1234extra; commit={short}" and got[1] == "commit=" + "a" * 41 + f"; commit={short}", str(got[:2]))
        check("⑤ 끝 경계: 해시 뒤가 ';'·공백·줄 끝이면 «이미 있음»(무변경)", got[2] == "commit=abc1234; 메모" and got[3] == "메모; commit=abc1234", str(got[2:]))


def test_attach_commit():
    with tempfile.TemporaryDirectory() as tmp:
        repo, full, short = make_git_repo(tmp)
        env = {"HARNESS_GIT_DIR": str(repo)}
        home = make_home(Path(tmp) / "h1", [legacy(1, st="accepted"), legacy(2, st="accepted") + "\t사람 판정", legacy(3, st="accepted") + "\tcommit=aaaaaaa",
                                            legacy(4, st="pending")], header=HDR7)
        r = sh(home, "attach-commit", "T12-20260101-01", short, **env)
        check("attach-commit: 빈 비고 → commit=<해시>", r.returncode == 0 and rows(home)[0][6] == f"commit={short}" and rows(home)[0][4] == "accepted", str(rows(home)[0]) + r.stderr)
        sh(home, "attach-commit", "T12-20260101-02", short, **env)
        check("attach-commit: 기존 비고 뒤에 '; commit=<해시>'", rows(home)[1][6] == f"사람 판정; commit={short}", str(rows(home)[1]))
        sh(home, "attach-commit", "T12-20260101-03", short, **env)
        check("attach-commit: 이미 commit= 이 있으면 무변경", rows(home)[2][6] == "commit=aaaaaaa", str(rows(home)[2]))
        r = sh(home, "attach-commit", "T12-20260101-04", short, **env)
        check("attach-commit: accepted 가 아니면 거부", r.returncode == 1 and rows(home)[3][4] == "pending", f"{r.returncode} {r.stderr}")
        r = sh(home, "attach-commit", "T12-20260101-01", "XYZ; rm", **env)
        check("attach-commit: 해시 형식 검증", r.returncode == 1)
        before = cand(home)
        for label, h in (("1자", "a"), ("6자", "abcdef"), ("41자", "a" * 41), ("130자", "a" * 130)):
            r = sh(home, "attach-commit", "T12-20260101-02", h, **env)
            check(f"attach-commit: {label} 해시 거부(exit 1·무변경·비정상 종료 아님)", r.returncode == 1 and cand(home) == before and "Traceback" not in r.stderr and "음수" not in r.stderr, f"{r.returncode} {r.stderr[:100]}")
        r = sh(home, "attach-commit", "T12-20260101-02", "deadbee", **env)
        check("attach-commit: 저장소에 없는 해시 거부(exit 1·무변경)", r.returncode == 1 and "없음" in r.stderr and cand(home) == before, f"{r.returncode} {r.stderr}")
        long_note = "가" * 119
        home2 = make_home(Path(tmp) / "h2", [legacy(1, st="accepted") + "\t" + long_note], header=HDR7)
        r = sh(home2, "attach-commit", "T12-20260101-01", full, **env)
        n = rows(home2)[0][6]
        check("attach-commit: 120자 한도 안에서 40자 해시가 잘리지 않음", len(n) <= 120 and n.endswith(f"; commit={full}"), f"{len(n)} {n[-30:]}")


def test_status_exact_match():
    """연속 문자열·공백/탭/개행 포함 status 는 부분 일치로 통과하지 못한다(append 와 set 둘 다)."""
    bad = ["pending pending-bench", "pending ", " pending", "pending\tpending-bench", "pending\n", "accepted rejected", "pend", "pending-bench pending-approval"]
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, [legacy(1)])
        before = cand(home)
        for s in bad:
            r = sh(home, "T12", f"요약-{abs(hash(s))}", s)
            check(f"append: status {s!r} 거부·무기록", r.returncode == 1 and "어휘 밖" in r.stderr and cand(home) == before, f"{r.returncode} {r.stderr}")
            r = sh(home, "set", "T12-20260101-01", s)
            check(f"set: status {s!r} 거부·불변", r.returncode == 1 and "어휘 밖" in r.stderr and cand(home) == before, f"{r.returncode} {r.stderr}")
        r = sh(home, "set", "T12-20260101-01", "pending-bench")
        check("정확히 일치하는 status 는 여전히 허용", r.returncode == 0 and rows(home)[0][4] == "pending-bench", r.stderr)


def test_expire_rules():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, [
            legacy(1, day=days_ago(30)),                       # 만료 대상
            legacy(2, day=days_ago(30)) + "\t검토중",           # note 있음 → 건너뜀
            legacy(3, st="pending-bench", day=days_ago(30)),   # pending 아님 → 건너뜀
            legacy(4, day=days_ago(2)),                        # 최근 → 건너뜀
        ], header=HDR7)
        marker = home / ".claude/_usage/candidates-reviewed-last"
        r = sh(home, "expire", "--older-than-days", "7", "--dry-run")
        check("dry-run 은 1건 예고·불변", "1건" in r.stdout and rows(home)[0][4] == "pending", r.stdout)
        r = sh(home, "expire", "--older-than-days", "7")
        st = [x[4] for x in rows(home)]
        check("expire: pending·보호 note 없음·오래됨만 expired", st == ["expired", "pending", "pending-bench", "pending"], str(st))
        check("expire 는 reviewed-last 를 touch 하지 않음", not marker.exists())
        r = sh(home, "expire", "--older-than-days", "x")
        check("잘못된 일수 거부", r.returncode == 1)
        r = sh(home, "expire", "--days", "7")
        check("옛 옵션 --days 는 거부(--older-than-days 만)", r.returncode == 1)


def test_expire_protection_scope():
    old = days_ago(30)
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, [
            legacy(1, day=old) + "\tkw=왜",                       # 기계 비고 → 만료
            legacy(2, day=old) + "\teffect:quiet n_spawn=3",      # 기계 비고 → 만료
            legacy(3, day=old) + "\t사람이 본 판정",                # 보호
            legacy(4, day=old) + "\tcommit=abc1234",              # 보호
            legacy(5, day=old) + "\t메모 kw=왜",                   # 접두가 아니면 보호
            legacy(6, day=old) + "\tkwx=1",                       # 비슷한 접두도 보호
        ], header=HDR7)
        sh(home, "expire", "--older-than-days", "7")
        st = [x[4] for x in rows(home)]
        check("expire: kw=·effect: 기계 비고는 만료, 그 밖의 비고는 보호",
              st == ["expired", "expired", "pending", "pending", "pending", "pending"], str(st))


def test_expire_lock_busy():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, [legacy(1, day=days_ago(30))], header=HDR7)
        before = cand(home)
        fd = os.open(str(home / ".claude/_evolve/candidates.lock"), os.O_CREAT | os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            t0 = time.time()
            r = sh(home, "expire", "--older-than-days", "7")
            dt = time.time() - t0
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        check("잠금 점유 중 expire → exit 3 + '잠금 실패'", r.returncode == 3 and "잠금 실패" in r.stderr, f"{r.returncode} {r.stderr}")
        check("잠금 실패 시 대장 불변·대기 약 1초", cand(home) == before and dt < 5, f"dt={dt:.2f}")


def test_dedupe_legacy():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, [
            legacy(1, src="T40", summ="온톨로지 커밋 ×9"),
            legacy(2, src="T40", summ="현황 보고 ×12"),
            legacy(3, src="T12", summ="왜 ×3 했어"),
            legacy(4, src="T12", summ="끝에 ×4"),   # T12 는 건드리지 않는다
        ])
        r = sh(home, "dedupe-legacy", "--dry-run")
        check("dedupe dry-run 2건 예고·불변", "2건" in r.stdout and "×9" in cand(home), r.stdout)
        r = sh(home, "dedupe-legacy")
        s = [x[5] for x in rows(home)]
        check("T40 ×N 접미만 제거", s == ["온톨로지 커밋", "현황 보고", "왜 ×3 했어", "끝에 ×4"], str(s))
        r = sh(home, "T40", "온톨로지 커밋 ×11")
        check("제거 뒤에도 같은 패턴은 중복 차단(exit 3)", r.returncode == 3, str(r.returncode))


def test_oldest_pending_priority():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, [
            f"T12-1\tT12\t{days_ago(40)}\t-\tpending\t교정 오래됨",
            f"T40-1\tT40\t{days_ago(5)}\t-\tpending\t반복 패턴 ×4",
            f"T41-1\tT41\t{days_ago(3)}\t-\tpending\tcoder/구현 정확성: RESULT: FAIL",
            f"T41-2\tT41\t{days_ago(50)}\t-\tpending\tqa/범위 준수: RESULT: BLOCKED",
            f"T40-2\tT40\t{days_ago(9)}\t-\tpending-bench\t더 오래된 반복 ×3",
            f"T12-2\tT12\t{days_ago(1)}\t-\texpired\t만료됨",
            f"T12-3\tT12\t{days_ago(2)}\t-\taccepted\t채택됨",
        ])
        r = sh(home, "oldest-pending", "--limit", "3", "--t41-axes", "coder/구현 정확성")
        ids = [l.split("\t")[0] for l in r.stdout.splitlines()]
        check("생성일 오름차순이 1차 키(오래된 T12 가 밀리지 않음)", ids == ["T41-2", "T12-1", "T40-2"], str(ids))
        r = sh(home, "oldest-pending", "--limit", "5", "--t41-axes", "")
        ids = [l.split("\t")[0] for l in r.stdout.splitlines()]
        check("미결 3종만·날짜 오름차순", ids == ["T41-2", "T12-1", "T40-2", "T40-1", "T41-1"], str(ids))
        r2 = sh(home, "oldest-pending", "--limit", "1", "--t41-axes", "")
        check("출력은 id·type·요약 3열 탭", len(r2.stdout.strip().split("\t")) == 3, r2.stdout)
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, [f"T12-1\tT12\t{days_ago(5)}\t-\tpending\t" + "가" * 100])
        out = sh(home, "oldest-pending").stdout.strip().split("\t")
        check("요약 60자 절단", len(out[2]) == 60, str(len(out[2])))


def test_append_pending_only_and_machine_note():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, [])
        for st in ("accepted", "rejected", "expired", "pending-bench", "pending-approval"):
            r = sh(home, "T12", f"처음부터 {st}", st, "--note", "commit=abc1234")
            check(f"A1: append {st} 거부(exit 1·무기록)", r.returncode == 1 and "pending 만" in r.stderr and rows(home) == [], f"{r.returncode} {r.stderr}")
        r = sh(home, "T12", "사람 비고", "--note", "사람이 적은 판정")
        check("A2: 사람 비고 거부(exit 1·set-note 안내·무기록)", r.returncode == 1 and "set-note" in r.stderr and rows(home) == [], f"{r.returncode} {r.stderr}")
        r = sh(home, "T12", "commit 비고", "--note", "commit=abc1234")
        check("A2: commit= 비고도 거부", r.returncode == 1 and rows(home) == [], r.stderr)
        r = sh(home, "T12", "기계 kw", "pending", "--note", "kw=왜")
        check("A2: kw= 기계 비고 통과", r.returncode == 0 and rows(home)[-1][6] == "kw=왜", r.stderr)
        r = sh(home, "T41", "기계 effect", "--note", "effect:quiet n_spawn=1")
        check("A2: effect: 기계 비고 통과", r.returncode == 0 and rows(home)[-1][6] == "effect:quiet n_spawn=1", r.stderr)
        r = sh(home, "T12", "비고 없음")
        check("A1/A2: 인자 없는 append 는 종전대로", r.returncode == 0 and rows(home)[-1][4] == "pending", r.stderr)


def test_append_dedupe_ignores_expired():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, [legacy(1, day=days_ago(60), summ="재발하는 교정"), legacy(2, st="accepted", summ="끝난 교정"),
                               legacy(3, st="rejected", summ="기각된 교정"), legacy(4, summ="미결 교정")], header=HDR7)
        sh(home, "expire", "--older-than-days", "7")
        check("A4 전제: 첫 행 expired", rows(home)[0][4] == "expired", str(rows(home)[0]))
        r = sh(home, "T12", "재발하는 교정")
        got = [x for x in rows(home) if x[5] == "재발하는 교정"]
        check("A4: expired 뒤 같은 요약 재append 는 새 id 로 들어감", r.returncode == 0 and len(got) == 2 and got[1][4] == "pending" and got[1][0] != got[0][0], f"{r.returncode} {got}")
        r = sh(home, "T12", "재발하는 교정")
        check("A4: 새 pending 행이 생긴 뒤 같은 요약은 다시 exit 3", r.returncode == 3, str(r.returncode))
        for s in ("끝난 교정", "기각된 교정", "미결 교정"):
            r = sh(home, "T12", s)
            check(f"A4: accepted·rejected·미결 행({s})과는 계속 중복 exit 3", r.returncode == 3, str(r.returncode))


def test_append_expired_within_37_days_still_duplicate():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, [legacy(1, st="expired", day=days_ago(10), summ="열흘 전 만료"), legacy(2, st="expired", day=days_ago(60), summ="두 달 전 만료"),
                               legacy(3, st="expired", day=days_ago(37), summ="37일 전 만료"), legacy(4, st="expired", day=days_ago(38), summ="38일 전 만료")], header=HDR7)
        r = sh(home, "T12", "열흘 전 만료")
        check("⑬ 10일 전 생성 expired 는 여전히 중복(rc 3·무기록)", r.returncode == 3 and len(rows(home)) == 4, f"{r.returncode} {len(rows(home))}")
        r = sh(home, "T12", "두 달 전 만료")
        check("⑬ 60일 전 생성 expired 는 재진입(rc 0·새 pending 행)", r.returncode == 0 and len(rows(home)) == 5 and rows(home)[-1][4] == "pending" and rows(home)[-1][5] == "두 달 전 만료", f"{r.returncode} {rows(home)[-1]}")
        r = sh(home, "T12", "37일 전 만료")
        check("⑬ 경계: 정확히 37일 전 expired 는 중복(rc 3)", r.returncode == 3, str(r.returncode))
        r = sh(home, "T12", "38일 전 만료")
        check("⑬ 경계: 38일 전 expired 는 재진입(rc 0)", r.returncode == 0, str(r.returncode))


def test_expire_skip_ids():
    old = days_ago(30)
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, [legacy(1, day=old), legacy(2, day=old), legacy(3, day=old)], header=HDR7)
        r = sh(home, "expire", "--older-than-days", "7", "--dry-run", "--skip-ids", "T12-20260101-01,T12-20260101-03")
        check("② expire --skip-ids: dry-run 이 제외 id 를 빼고 1건만 예고", "1건" in r.stdout and "T12-20260101-02" in r.stdout and "T12-20260101-01" not in r.stdout, r.stdout)
        sh(home, "expire", "--older-than-days", "7", "--skip-ids", "T12-20260101-01,T12-20260101-03")
        check("② expire --skip-ids: 제외 id 는 pending 유지·나머지만 expired", [x[4] for x in rows(home)] == ["pending", "expired", "pending"], str([x[4] for x in rows(home)]))
        r = sh(home, "expire", "--older-than-days", "7", "--skip-ids", "a;b")
        check("② expire --skip-ids: 허용 문자 밖은 거부(exit 1)", r.returncode == 1, str(r.returncode))


def test_expire_self_protection():
    old = days_ago(30)
    today = date.today().isoformat()
    t41 = f"T41-q\tT41\t{old}\t-\tpending\tcoder/구현 정확성: 조용\teffect:quiet n_spawn=0"
    with tempfile.TemporaryDirectory() as tmp:   # (b) 미결 T41 + 오늘의 done 없음 → exit 4
        home = make_home(tmp, [t41, legacy(2, day=old)], header=HDR7)
        before = cand(home)
        r = sh(home, "expire", "--older-than-days", "7")
        check("⑤ 미결 T41 이 있고 오늘의 done 이 없으면 exit 4·무변경·안내 문구", r.returncode == 4 and "효과 기록 전이라 만료 보류" in r.stderr and cand(home) == before, f"{r.returncode} {r.stderr}")
        r = sh(home, "expire", "--older-than-days", "7", "--dry-run")
        check("⑤ --dry-run 은 보류하지 않는다(미리보기)", r.returncode == 0 and "건이 expired" in r.stdout, f"{r.returncode} {r.stdout}")
        edir = home / f".claude/_usage/t41-effect-{today}.d"
        edir.mkdir()
        r = sh(home, "expire", "--older-than-days", "7")
        check("⑤ 선점 디렉터리만 있고 done 없음(10분 이내)도 exit 4", r.returncode == 4 and cand(home) == before, f"{r.returncode}")
        os.utime(edir, (time.time() - 1200, time.time() - 1200))
        r = sh(home, "expire", "--older-than-days", "7")
        check("⑤ 선점이 10분 넘게 done 없이 있으면(기록 세션 중단) 허용", r.returncode == 0 and [x[4] for x in rows(home)] == ["expired", "expired"], f"{r.returncode} {[x[4] for x in rows(home)]}")
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, [t41, legacy(2, day=old)], header=HDR7)
        edir = home / f".claude/_usage/t41-effect-{today}.d"
        edir.mkdir()
        (edir / "done").touch()
        r = sh(home, "expire", "--older-than-days", "7")
        check("⑤ done 이 있으면 만료 실행", r.returncode == 0 and [x[4] for x in rows(home)] == ["expired", "expired"], f"{r.returncode}")
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, [t41, legacy(2, day=old)], header=HDR7)
        r = sh(home, "expire", "--older-than-days", "7", "--force")
        check("⑤ --force 는 보류를 무시", r.returncode == 0 and [x[4] for x in rows(home)] == ["expired", "expired"], f"{r.returncode} {r.stderr}")
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, [legacy(1, day=old), f"T41-a\tT41\t{old}\t-\taccepted\t끝난 T41"], header=HDR7)
        r = sh(home, "expire", "--older-than-days", "7")
        check("⑤ 미결 T41 이 없으면(accepted 만) done 없이도 만료", r.returncode == 0 and rows(home)[0][4] == "expired", f"{r.returncode}")
    with tempfile.TemporaryDirectory() as tmp:   # (a) 재시도 큐의 id 자동 제외
        home = make_home(tmp, [legacy(1, day=old), legacy(2, day=old), legacy(3, day=old)], header=HDR7)
        q = home / ".claude/_usage/candidates-attach-retry.tsv"
        q.write_text("T12-20260101-01\tabc1234\n", encoding="utf-8")
        r = sh(home, "expire", "--older-than-days", "7", "--skip-ids", "T12-20260101-03")
        check("⑤ 재시도 큐의 id 는 자동 제외(+ --skip-ids 추가분도 제외)", r.returncode == 0 and [x[4] for x in rows(home)] == ["pending", "expired", "pending"], f"{r.returncode} {[x[4] for x in rows(home)]}")
        before = cand(home)
        fd = os.open(str(home / ".claude/_usage/candidates-attach-retry.lock"), os.O_CREAT | os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            t0 = time.time()
            r = sh(home, "expire", "--older-than-days", "7")
            dt = time.time() - t0
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        check("⑤ 큐 잠금을 못 잡으면 약 2초 뒤 exit 3·무변경(큐 내용을 모르므로 만료 안 함)", r.returncode == 3 and "재시도 큐" in r.stderr and cand(home) == before and 1.5 < dt < 8, f"{r.returncode} {dt:.1f}s {r.stderr}")


def test_set_machine_accepts_commit_from_expired():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, [legacy(1, st="expired"), legacy(2, st="expired"), legacy(3, st="expired"), legacy(4, st="rejected"), legacy(5, st="expired") + "\t사람 비고"],
                         header=HDR7)
        r = sh(home, "set", "T12-20260101-01", "accepted", "--note", "commit=abc1234", "--machine")
        check("expired + --machine accepted + commit=<해시> → accepted 전이", r.returncode == 0 and rows(home)[0][4] == "accepted" and rows(home)[0][6] == "commit=abc1234", f"{r.returncode} {r.stderr} {rows(home)[0]}")
        before = cand(home)
        for label, args in (("--machine 없음", ("set", "T12-20260101-02", "accepted", "--note", "commit=abc1234")),
                            ("해시 아닌 비고", ("set", "T12-20260101-02", "accepted", "--note", "commit=나중에", "--machine")),
                            ("해시 6자", ("set", "T12-20260101-02", "accepted", "--note", "commit=abcdef", "--machine")),
                            ("비고 없음", ("set", "T12-20260101-02", "accepted", "--machine")),
                            ("accepted 가 아닌 상태", ("set", "T12-20260101-02", "pending-bench", "--note", "commit=abc1234", "--machine"))):
            r = sh(home, *args)
            check(f"expired 예외 아님: {label} → exit 1·불변", r.returncode == 1 and cand(home) == before, f"{r.returncode} {r.stderr}")
        r = sh(home, "set", "T12-20260101-04", "accepted", "--note", "commit=abc1234", "--machine")
        check("rejected 는 --machine commit= 이어도 계속 거부", r.returncode == 1 and rows(home)[3][4] == "rejected", f"{r.returncode}")
        r = sh(home, "set", "T12-20260101-05", "accepted", "--note", "commit=abc1234", "--machine")
        check("expired 의 사람 비고는 덧붙임 규칙대로 보존", r.returncode == 0 and rows(home)[4][6] == "사람 비고; commit=abc1234", str(rows(home)[4]))
        check("--machine 전이라 reviewed-last 는 touch 안 함", not (home / ".claude/_usage/candidates-reviewed-last").exists())


def test_set_note_batch_1000_rows_fast():
    n = 1000
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, [f"T41-{i:04d}\tT41\t{days_ago(3)}\t-\tpending-bench\tcoder/구현 정확성: 후보 {i}\teffect:quiet n_spawn=0" for i in range(n)], header=HDR7)
        dirty = "\x1b[31m탭\t사이\r끝\u0085" + "가" * 150 + "   "
        batch = "".join(f"T41-{i:04d}\teffect:recurred k={i}\n" for i in range(n - 1)) + f"T41-{n - 1:04d}\t{dirty}\n"
        env = dict(os.environ, HOME=str(home))
        t0 = time.time()
        r = subprocess.run(["bash", SH, "set-note-batch", "--only-machine"], input=batch, capture_output=True, text=True, env=env, check=False)
        dt = time.time() - t0
        got = [x[6] for x in rows(home)]
        check("⑥ 1,000행 일괄 비고 갱신이 5초 안에 끝나고 전부 반영", r.returncode == 0 and dt < 5 and got[0] == "effect:recurred k=0" and got[998] == "effect:recurred k=998", f"rc={r.returncode} {dt:.1f}s {r.stderr[:100]}")
        sh(home, "set-note", "T41-0000", dirty)
        check("⑥ 정제 결과가 clean_note(set-note)와 같음(제어문자·탭·C1 제거·120자·앞뒤 공백)", got[n - 1] == rows(home)[0][6] and len(got[n - 1]) == 120 and "\x1b" not in got[n - 1], f"{len(got[n - 1])} {got[n - 1][:20]!r}")


def test_set_note_batch_4000_rows_via_stdin():
    n = 4000
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, [f"T41-{i:04d}\tT41\t{days_ago(3)}\t-\tpending-bench\tcoder/구현 정확성: 후보 {i} " + "긴요약" * 20 + "\teffect:quiet n_spawn=0" for i in range(n)], header=HDR7)
        batch = "".join(f"T41-{i:04d}\teffect:recurred k={i} " + "나" * 60 + "\n" for i in range(n))
        check("③ 시험 전제: 묶음이 단일 환경 변수 한도(128KB)를 넘는다", len(batch.encode("utf-8")) > 131072, str(len(batch.encode("utf-8"))))
        env = dict(os.environ, HOME=str(home))
        r = subprocess.run(["bash", SH, "set-note-batch", "--only-machine"], input=batch, capture_output=True, text=True, env=env, check=False)
        got = [x[6] for x in rows(home)]
        check("③ 4,000행 stdin 일괄 갱신 성공(Argument list too long 없음)·전부 반영", r.returncode == 0 and "Argument list too long" not in r.stderr and got[0].startswith("effect:recurred k=0 ") and got[n - 1].startswith(f"effect:recurred k={n - 1} "),
              f"rc={r.returncode} {r.stderr[:150]}")


def test_storage_failure_exits_5():
    if os.geteuid() == 0:
        check("exit 5 시험은 root 에서 건너뜀(읽기 전용 폴더에도 쓰기 가능)", True, "")
        return
    with tempfile.TemporaryDirectory() as tmp:
        repo, _, short = make_git_repo(tmp)
        home = make_home(Path(tmp) / "h", [legacy(1), legacy(2, st="accepted"), legacy(3, day=days_ago(30)), legacy(4, st="expired")], header=HDR7)
        sh(home, "set-note", "T12-20260101-01", "x")   # 잠금 파일을 먼저 만들어 둔다(읽기 전용 폴더에서는 새로 못 만든다)
        edir = home / ".claude/_evolve"
        before = cand(home)
        os.chmod(edir, 0o555)
        try:
            cases = {"set": ("set", "T12-20260101-01", "rejected"), "set(expired 예외)": ("set", "T12-20260101-04", "accepted", "--note", "commit=abc1234", "--machine"),
                     "set-note": ("set-note", "T12-20260101-01", "y"), "set-bench": ("set-bench", "T12-20260101-01", "b1"),
                     "attach-commit": ("attach-commit", "T12-20260101-02", short), "expire": ("expire", "--older-than-days", "7")}
            for label, args in cases.items():
                r = sh(home, *args, HARNESS_GIT_DIR=str(repo))
                check(f"Codex8: 읽기 전용 대장에 {label} → exit 5·«대장 저장 실패»·대장 불변", r.returncode == 5 and "대장 저장 실패" in r.stderr and cand(home) == before, f"{r.returncode} {r.stderr[:160]}")
            r = sh(home, "set", "NOPE", "accepted")
            check("Codex8: 거부(없는 id)는 여전히 exit 1(5 와 구분)", r.returncode == 1, str(r.returncode))
        finally:
            os.chmod(edir, 0o755)
        # append 는 기존 대장에 덧붙이므로(디렉터리 쓰기 불필요) 대장 파일 자체를 읽기 전용으로 만들어 주입한다
        os.chmod(edir / "candidates.tsv", 0o444)
        try:
            r = sh(home, "T12", "저장 실패 시험 요약")
            check("Codex8: 읽기 전용 대장 파일에 append → exit 5·«대장 저장 실패»·대장 불변", r.returncode == 5 and "대장 저장 실패" in r.stderr and cand(home) == before, f"{r.returncode} {r.stderr[:160]}")
        finally:
            os.chmod(edir / "candidates.tsv", 0o644)
        r = sh(home, "set", "T12-20260101-01", "rejected")
        check("Codex8: 쓰기가 가능해지면 같은 set 이 성공", r.returncode == 0 and rows(home)[0][4] == "rejected", f"{r.returncode} {r.stderr}")


def test_expire_holds_queue_lock_first():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, [legacy(1, day=days_ago(30))], header=HDR7)
        before = cand(home)
        fd = os.open(str(home / ".claude/_usage/candidates-attach-retry.lock"), os.O_CREAT | os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            t0 = time.time()
            r = sh(home, "expire", "--older-than-days", "7")   # 큐 파일이 없어도 큐 잠금을 먼저 잡는다
            dt = time.time() - t0
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        check("⑦ 큐 잠금을 쥔 채 expire(큐 파일 없음) → 약 2초 뒤 exit 3·대장 불변", r.returncode == 3 and cand(home) == before and 1.5 < dt < 8, f"{r.returncode} {dt:.1f}s {r.stderr}")
        # 대장 잠금이 점유돼 expire 가 실패해도 큐 잠금은 반드시 풀린다(잠금 순서 큐 → 대장, 누수 없음)
        fd = os.open(str(home / ".claude/_evolve/candidates.lock"), os.O_CREAT | os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            r = sh(home, "expire", "--older-than-days", "7")
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        qfd = os.open(str(home / ".claude/_usage/candidates-attach-retry.lock"), os.O_CREAT | os.O_RDWR)
        try:
            fcntl.flock(qfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            freed = True
        except BlockingIOError:
            freed = False
        finally:
            os.close(qfd)
        check("⑦ 대장 잠금 실패(exit 3)로 끝나도 큐 잠금은 풀려 있음", r.returncode == 3 and freed and cand(home) == before, f"{r.returncode} freed={freed}")
        r = sh(home, "expire", "--older-than-days", "7")
        check("⑦ 잠금이 모두 풀리면 정상 만료", r.returncode == 0 and rows(home)[0][4] == "expired", f"{r.returncode} {r.stderr}")


def test_expired_exception_end_boundary():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, [legacy(i, st="expired") for i in range(1, 6)], header=HDR7)
        before = cand(home)
        for label, note in (("해시 뒤에 글자 붙음", "commit=abc1234x"), ("41자 16진수", "commit=" + "a" * 41), ("해시 6자", "commit=abcdef")):
            r = sh(home, "set", "T12-20260101-01", "accepted", "--note", note, "--machine")
            check(f"Grok7⑤: expired 예외는 {label}({note[:20]}) 를 거부(exit 1·불변)", r.returncode == 1 and cand(home) == before, f"{r.returncode} {r.stderr}")
        r = sh(home, "set", "T12-20260101-02", "accepted", "--note", "commit=abc1234", "--machine")
        check("Grok7⑤: commit=abc1234(줄 끝)는 통과", r.returncode == 0 and rows(home)[1][4] == "accepted", f"{r.returncode} {r.stderr}")
        r = sh(home, "set", "T12-20260101-03", "accepted", "--note", "commit=abc1234; 메모", "--machine")
        check("Grok7⑤: 해시 뒤가 ';' 이면 통과", r.returncode == 0 and rows(home)[2][4] == "accepted", f"{r.returncode} {r.stderr}")
        r = sh(home, "set", "T12-20260101-04", "accepted", "--note", "commit=abc1234 (메모)", "--machine")
        check("Grok7⑤: 해시 뒤가 공백이면 통과", r.returncode == 0 and rows(home)[3][4] == "accepted", f"{r.returncode} {r.stderr}")


def test_expire_hold_wording():
    text = Path(SH).read_text(encoding="utf-8")
    check("Grok9 1: expire 보류 안내가 «--force·--dry-run·선점 10분 초과면 건너뜀» (force 가 무시된다는 오독 문구 없음)",
          "--force·--dry-run·선점 10분 초과면 이 보류를 건너뛴다" in text and "--force 는 무시" not in text and "무시: --force" not in text and "선점 10분 초과면 건너뜀" in text, "")
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, [f"T41-q\tT41\t{days_ago(30)}\t-\tpending\t조용\teffect:quiet n_spawn=0"], header=HDR7)
        r = sh(home, "expire", "--older-than-days", "7")
        check("Grok9 1: 실제 보류(exit 4) 안내 문구에 새 표현", r.returncode == 4 and "--force·--dry-run·선점 10분 초과면 이 보류를 건너뛴다" in r.stderr, f"{r.returncode} {r.stderr}")


def test_expire_holds_when_t41_count_fails():
    old = days_ago(30)
    rows_ = [legacy(1, day=old), f"T41-q\tT41\t{old}\t-\tpending\tcoder/구현 정확성: 조용\teffect:quiet n_spawn=0"]
    with tempfile.TemporaryDirectory() as tmp:   # 미결 T41 집계 awk 만 실패시키는 대역(루트에서도 동작)
        shim = Path(tmp) / "shim"
        shim.mkdir()
        (shim / "awk").write_text('#!/bin/bash\nif [[ "$*" == *\'$2=="T41"\'* && "$*" == *\'END {print n+0}\'* ]]; then echo "awk: injected" >&2; exit 2; fi\nexec /usr/bin/awk "$@"\n', encoding="utf-8")
        (shim / "awk").chmod(0o755)
        home = make_home(Path(tmp) / "h", rows_, header=HDR7)
        before = cand(home)
        path = f"{shim}:{os.environ['PATH']}"
        r = sh(home, "expire", "--older-than-days", "7", PATH=path)
        check("미결 T41 집계 awk 실패 → exit 4 «미결 T41 집계 실패라 만료 보류»·대장 불변(미결 0 으로 읽지 않음)", r.returncode == 4 and "미결 T41 집계 실패라 만료 보류" in r.stderr and cand(home) == before, f"{r.returncode} {r.stderr}")
        r = sh(home, "expire", "--older-than-days", "7", "--dry-run", PATH=path)
        check("집계 실패에도 --dry-run 은 보류 없이 통과(미리보기)", r.returncode == 0 and "건이 expired" in r.stdout, f"{r.returncode} {r.stdout} {r.stderr}")
        r = sh(home, "expire", "--older-than-days", "7", "--force", PATH=path)
        check("집계 실패에도 --force 는 보류를 건너뛴다", r.returncode == 0 and rows(home)[0][4] == "expired", f"{r.returncode} {r.stderr}")
    if os.geteuid() != 0:
        with tempfile.TemporaryDirectory() as tmp:   # 대장을 읽을 수 없게(권한 0) 한 뒤 expire
            home = make_home(tmp, rows_, header=HDR7)
            ledger = home / ".claude/_evolve/candidates.tsv"
            os.chmod(ledger, 0)
            try:
                r = sh(home, "expire", "--older-than-days", "7")
                rd = sh(home, "expire", "--older-than-days", "7", "--dry-run")
            finally:
                os.chmod(ledger, 0o644)
            check("대장 권한 0 → expire exit 4(집계 실패 보류)", r.returncode == 4 and "미결 T41 집계 실패라 만료 보류" in r.stderr, f"{r.returncode} {r.stderr}")
            # 미리보기가 만료 대상 집계를 못 하면 «0건 예정» 은 거짓이라 --dry-run 도 보류(exit 4)가 맞다(Grok 10차 승인).
            check("대장 권한 0 이면 --dry-run 도 만료 대상 집계 실패로 exit 4 + 메시지", rd.returncode == 4 and "만료 대상 집계 실패" in rd.stderr, f"{rd.returncode} {rd.stderr}")


def test_expire_ids_count_failure_holds():
    old = days_ago(30)
    with tempfile.TemporaryDirectory() as tmp:
        shim = Path(tmp) / "shim"
        shim.mkdir()
        # 만료 대상(ids) 집계 awk 만 실패시키는 대역
        (shim / "awk").write_text('#!/bin/bash\nif [[ "$*" == *\'skip[a[i]] = 1\'* && "$*" == *\'{print $1}\'* ]]; then echo "awk: injected" >&2; exit 2; fi\nexec /usr/bin/awk "$@"\n', encoding="utf-8")
        (shim / "awk").chmod(0o755)
        home = make_home(Path(tmp) / "h", [legacy(1, day=old), legacy(2, day=old)], header=HDR7)
        before = cand(home)
        path = f"{shim}:{os.environ['PATH']}"
        r = sh(home, "expire", "--older-than-days", "7", PATH=path)
        check("Grok10 2: 만료 대상 집계 awk 실패 → «expire: 0건» 이 아니라 exit 4 «만료 대상 집계 실패»·대장 불변", r.returncode == 4 and "만료 대상 집계 실패" in r.stderr and "expire:" not in r.stdout and cand(home) == before, f"{r.returncode} {r.stdout} {r.stderr}")
        r = sh(home, "expire", "--older-than-days", "7", "--dry-run", PATH=path)
        check("Grok10 2: --dry-run 도 같은 처리(exit 4)", r.returncode == 4 and "만료 대상 집계 실패" in r.stderr and cand(home) == before, f"{r.returncode} {r.stdout} {r.stderr}")
        r = sh(home, "expire", "--older-than-days", "7")
        check("Grok10 2: 대역 없이는 정상 만료", r.returncode == 0 and [x[4] for x in rows(home)] == ["expired", "expired"], f"{r.returncode} {r.stderr}")


def test_expire_date_failure_holds():
    # Grok 12차 1: 날짜 계산 실패는 입력 오류(1)가 아니라 보류(4)이고 대장은 그대로다.
    with tempfile.TemporaryDirectory() as tmp:
        shim = Path(tmp) / "shim"
        shim.mkdir()
        (shim / "date").write_text('#!/bin/bash\ncase "$*" in *days*) echo "date: injected" >&2; exit 1;; esac\nexec /usr/bin/date "$@"\n', encoding="utf-8")
        (shim / "date").chmod(0o755)
        home = make_home(Path(tmp) / "h", [legacy(1, day=days_ago(30))], header=HDR7)
        before = cand(home)
        r = sh(home, "expire", "--older-than-days", "7", PATH=f"{shim}:{os.environ['PATH']}")
        check("Grok12 1: 날짜 계산 실패 → exit 4 «만료 보류(날짜 계산 실패)»·대장 불변", r.returncode == 4 and "만료 보류(날짜 계산 실패)" in r.stderr and cand(home) == before, f"{r.returncode} {r.stderr}")


def test_set_note_only_machine_keeps_recurred():
    # Grok 11차 11: 단건 set-note --only-machine 도 batch 처럼 effect:recurred 를 덮지 않는다(exit 4·무변경). quiet·빈 비고는 갱신.
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, [legacy(1) + "\teffect:recurred k=2", legacy(2) + "\teffect:quiet n_spawn=0", legacy(3)], header=HDR7)
        before = cand(home)
        r = sh(home, "set-note", "--only-machine", "T12-20260101-01", "effect:quiet n_spawn=9")
        check("Grok11 11: effect:recurred 행은 단건 --only-machine 도 exit 4·대장 불변", r.returncode == 4 and "effect:recurred" in r.stderr and cand(home) == before, f"{r.returncode} {r.stderr}")
        r2 = sh(home, "set-note", "--only-machine", "T12-20260101-02", "effect:recurred k=1")
        r3 = sh(home, "set-note", "--only-machine", "T12-20260101-03", "effect:quiet n_spawn=9")
        got = [x[6] for x in rows(home)]
        check("Grok11 11: effect:quiet·빈 비고는 종전대로 갱신", r2.returncode == 0 and r3.returncode == 0 and got == ["effect:recurred k=2", "effect:recurred k=1", "effect:quiet n_spawn=9"], f"{r2.returncode} {r3.returncode} {got}")


def test_set_note_batch_keeps_recurred():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, [legacy(1) + "\teffect:recurred k=2", legacy(2) + "\teffect:quiet n_spawn=0", legacy(3), legacy(4) + "\t사람 비고"], header=HDR7)
        env = dict(os.environ, HOME=str(home))
        batch = "".join(f"T12-20260101-0{i}\teffect:quiet n_spawn=9\n" for i in (1, 2, 3, 4))
        r = subprocess.run(["bash", SH, "set-note-batch", "--only-machine"], input=batch, capture_output=True, text=True, env=env, check=False)
        got = [x[6] for x in rows(home)]
        check("Grok10 3: 일괄 갱신이 effect:recurred 를 quiet 로 덮지 않음(quiet·빈 비고는 갱신, 사람 비고 유지)",
              r.returncode == 0 and got == ["effect:recurred k=2", "effect:quiet n_spawn=9", "effect:quiet n_spawn=9", "사람 비고"], f"{r.returncode} {got}")


def test_expire_keeps_recurred():
    old = days_ago(30)
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, [legacy(1, day=old) + "\teffect:recurred k=2", legacy(2, day=old) + "\teffect:quiet n_spawn=3",
                               legacy(3, day=old) + "\tkw=왜"], header=HDR7)
        r = sh(home, "expire", "--older-than-days", "7", "--dry-run")
        check("A5: dry-run 은 recurred 를 빼고 2건 예고", "2건" in r.stdout and "T12-20260101-01" not in r.stdout, r.stdout)
        sh(home, "expire", "--older-than-days", "7")
        st = [x[4] for x in rows(home)]
        check("A5: effect:recurred 는 pending 유지·quiet·kw= 는 expired", st == ["pending", "expired", "expired"], str(st))


def test_oldest_pending_date_first_and_skip():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, [
            f"A-1\tT40\t{days_ago(20)}\t-\tpending\t오래됨 T40",
            f"A-2\tT12\t{days_ago(19)}\t-\tpending\t다음 날 T12",
            f"B-4\tT40\t{days_ago(10)}\t-\tpending\t같은 날 T40",
            f"B-3\tT41\t{days_ago(10)}\t-\tpending\tqa/범위 준수: 비축 T41",
            f"B-2\tT12\t{days_ago(10)}\t-\tpending\t같은 날 T12",
            f"B-1\tT41\t{days_ago(10)}\t-\tpending\tcoder/구현 정확성: 축 T41",
            f"C-1\tT12\t{days_ago(1)}\t-\tpending-approval\t최근",
            f"C-2\tT12\t{days_ago(1)}\t-\taccepted\t제외",
        ])
        ids = lambda r: [l.split("\t")[0] for l in r.stdout.splitlines()]
        r = sh(home, "oldest-pending", "--limit", "10", "--t41-axes", "coder/구현 정확성")
        check("A6: 날짜 오름차순, 같은 날짜는 축 T41 > T12 > T40 > 비축 T41 (2순위 등급 0·1·2·3)",
              ids(r) == ["A-1", "A-2", "B-1", "B-2", "B-4", "B-3", "C-1"], str(ids(r)))
        r = sh(home, "oldest-pending", "--limit", "3", "--skip", "3", "--t41-axes", "coder/구현 정확성")
        check("A6: --skip 3 은 앞 3건을 건너뜀", ids(r) == ["B-2", "B-4", "B-3"], str(ids(r)))
        r = sh(home, "oldest-pending", "--limit", "3", "--skip", "99")
        check("A6: skip 이 건수보다 크면 빈 출력·exit 0", r.returncode == 0 and r.stdout == "", f"{r.returncode} {r.stdout!r}")
        r = sh(home, "oldest-pending", "--skip", "x")
        check("A6: --skip 숫자 아님 거부", r.returncode == 1)


def test_set_bench():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, [legacy(1), legacy(2, st="pending-bench"), legacy(3, st="accepted"), legacy(4, st="expired")], header=HDR7)
        marker = home / ".claude/_usage/candidates-reviewed-last"
        r = sh(home, "set-bench", "T12-20260101-01", "bench-2026.10_a")
        check("A7: pending 행에 bench_id 기록·상태 불변", r.returncode == 0 and rows(home)[0][3] == "bench-2026.10_a" and rows(home)[0][4] == "pending", f"{r.stderr} {rows(home)[0]}")
        check("A7: reviewed-last 를 touch 하지 않음", not marker.exists())
        r = sh(home, "set-bench", "T12-20260101-02", "x" * 40)
        check("A7: 40자 bench_id 허용(pending-bench 행)", r.returncode == 0 and rows(home)[1][3] == "x" * 40, r.stderr)
        before = cand(home)
        for i, cur in ((3, "accepted"), (4, "expired")):
            r = sh(home, "set-bench", f"T12-20260101-0{i}", "b1")
            check(f"A7: {cur} 행 거부(exit 1·불변)", r.returncode == 1 and cand(home) == before, f"{r.returncode} {r.stderr}")
        for label, b in (("41자", "x" * 41), ("공백", "a b"), ("슬래시", "a/b"), ("탭", "a\tb"), ("빈 값", ""), ("세미콜론", "a;b")):
            r = sh(home, "set-bench", "T12-20260101-01", b)
            check(f"A7: bench_id {label} 거부(exit 1·불변)", r.returncode == 1 and cand(home) == before, f"{r.returncode} {r.stderr}")
        r = sh(home, "set-bench", "NOPE", "b1")
        check("A7: 없는 id 거부", r.returncode == 1)
        r = sh(home, "set-bench", "T12-20260101-01")
        check("A7: 인자 부족 사용법 오류", r.returncode == 1)


def test_set_note_appends_to_human_note():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, [legacy(1) + "\thold: 대기 중", legacy(2) + "\tkw=왜", legacy(3) + "\teffect:recurred k=2", legacy(4),
                               legacy(5) + "\t" + "가" * 110, legacy(6) + "\thold: 유지", legacy(7) + "\t" + "나" * 118,
                               legacy(8) + "\t" + "다" * 116, legacy(9) + "\t" + "라" * 110, legacy(10) + "\t" + "마" * 118,
                               legacy(11) + "\thold: " + "바" * 110], header=HDR7)
        r = sh(home, "set", "T12-20260101-01", "accepted", "--note", "commit=abc1234")
        check("③ set --note: 사람 비고는 '<기존>; <새>' 로 덧붙임", r.returncode == 0 and rows(home)[0][6] == "hold: 대기 중; commit=abc1234" and rows(home)[0][4] == "accepted", str(rows(home)[0]))
        for i, label in ((2, "kw="), (3, "effect:"), (4, "빈 비고")):
            sh(home, "set", f"T12-20260101-0{i}", "accepted", "--note", "commit=abc1234")
            check(f"③ set --note: {label} 은 교체", rows(home)[i - 1][6] == "commit=abc1234", str(rows(home)[i - 1]))
        sh(home, "set", "T12-20260101-05", "accepted", "--note", "commit=abc1234")
        n = rows(home)[4][6]
        check("(a) 새 비고가 commit= 이면 자르지 않고 기존 사람 비고를 끝에서 자름(104+2+14)", n == "가" * 104 + "; commit=abc1234" and len(n) == 120, f"{len(n)} {n[-24:]}")
        sh(home, "set", "T12-20260101-06", "rejected")
        check("③ set(--note 없음): 비고 불변", rows(home)[5][6] == "hold: 유지", str(rows(home)[5]))
        r = sh(home, "set", "T12-20260101-07", "accepted", "--note", "commit=abc1234")
        check("(a) 기존이 118자여도 commit= 은 온전·기존 비고만 잘림·stderr 없음", r.returncode == 0 and rows(home)[6][4] == "accepted" and rows(home)[6][6] == "나" * 104 + "; commit=abc1234" and r.stderr == "", f"{r.returncode} {rows(home)[6][6][-24:]} {r.stderr}")
        sh(home, "set", "T12-20260101-08", "accepted", "--note", "commit=" + "a" * 40)
        n8 = rows(home)[7][6]
        check("(a) 40자 해시(47자 비고)도 온전·기존 비고는 71자로 줄어듦", n8 == "다" * 71 + "; commit=" + "a" * 40 and len(n8) == 120, f"{len(n8)} {n8[-30:]}")
        sh(home, "set", "T12-20260101-11", "accepted", "--note", "commit=abc1234")
        n11 = rows(home)[10][6]
        check("(a) 긴 hold 비고 + commit= → 해시 온전·hold 접두 유지·기존 비고 잘림", n11.startswith("hold: 바") and n11.endswith("; commit=abc1234") and len(n11) == 120, f"{len(n11)} {n11[:10]} {n11[-24:]}")
        sh(home, "set", "T12-20260101-09", "accepted", "--note", "memo-long-text")
        check("⑩ commit= 이 아닌 새 비고는 새 비고 쪽을 자름(110+2+8)", rows(home)[8][6] == "라" * 110 + "; memo-lon" and len(rows(home)[8][6]) == 120, str(rows(home)[8][6][-14:]))
        r = sh(home, "set", "T12-20260101-10", "accepted", "--note", "memo-long-text")
        check("⑩ commit= 이 아닌 새 비고는 자리가 2자 미만이면 기존 유지·새 비고 버림·상태 전이·stderr 한 줄",
              r.returncode == 0 and rows(home)[9][4] == "accepted" and rows(home)[9][6] == "마" * 118 and "새 비고 버림" in r.stderr, f"{r.returncode} {r.stderr}")


def test_set_machine_flag_keeps_reviewed_marker():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, [legacy(1), legacy(2), legacy(3)], header=HDR7)
        marker = home / ".claude/_usage/candidates-reviewed-last"
        r = sh(home, "set", "T12-20260101-01", "accepted", "--note", "commit=abc1234", "--machine")
        check("③ set --machine: 상태·note 는 쓰고 reviewed-last 는 touch 안 함", r.returncode == 0 and rows(home)[0][4] == "accepted" and rows(home)[0][6] == "commit=abc1234" and not marker.exists(), f"{r.stderr} {rows(home)[0]}")
        r = sh(home, "set", "T12-20260101-02", "rejected", "--machine")
        check("③ set --machine(note 없음)도 마커 불변", r.returncode == 0 and rows(home)[1][4] == "rejected" and not marker.exists(), r.stderr)
        r = sh(home, "set", "T12-20260101-03", "accepted", "--machine", "--note", "commit=abc1234")
        check("③ 옵션 순서(--machine 먼저)도 허용", r.returncode == 0 and rows(home)[2][6] == "commit=abc1234" and not marker.exists(), r.stderr)
        home2 = make_home(Path(tmp) / "h2", [legacy(1)], header=HDR7)
        sh(home2, "set", "T12-20260101-01", "rejected")
        check("③ --machine 없는 set(사람 판정)은 마커를 touch", (home2 / ".claude/_usage/candidates-reviewed-last").exists())
        r = sh(home2, "set", "T12-20260101-01", "accepted", "--bogus")
        check("③ 알 수 없는 set 옵션은 사용법 오류", r.returncode == 1 and "사용법" in r.stderr, r.stderr)


def test_append_rejects_effect_recurred():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, [], header=HDR7)
        r = sh(home, "T41", "재발 위조", "--note", "effect:recurred k=3")
        check("⑦ append 는 effect:recurred 를 못 넣음(exit 1·set-note 안내·무기록)", r.returncode == 1 and "set-note" in r.stderr and rows(home) == [], f"{r.returncode} {r.stderr}")
        r = sh(home, "T41", "조용한 후보", "--note", "effect:quiet n_spawn=2")
        check("⑦ effect:quiet 는 통과", r.returncode == 0 and rows(home)[-1][6] == "effect:quiet n_spawn=2", r.stderr)
        r = sh(home, "T41", "기계 kw", "--note", "kw=왜")
        check("⑦ kw= 는 통과", r.returncode == 0, r.stderr)


def build_path_without(tmp, *names):
    """/usr/bin 의 모든 실행 파일을 링크한 PATH 전용 폴더에서 names 만 뺀다(그 명령이 없는 환경 모의)."""
    bindir = Path(tmp) / "bin-without"
    bindir.mkdir()
    for p in Path("/usr/bin").iterdir():
        if p.name not in names:
            (bindir / p.name).symlink_to(p)
    return str(bindir)


def test_no_flock_refuses_all_writes():
    with tempfile.TemporaryDirectory() as tmp:
        repo, _, short = make_git_repo(tmp)
        home = make_home(Path(tmp) / "h", [legacy(1, day=days_ago(30)), legacy(2, st="accepted"), legacy(3, src="T40", summ="x ×3")], header=HDR7)
        path = build_path_without(tmp, "flock")
        bash = shutil.which("bash") or "/usr/bin/bash"
        before = cand(home)
        cases = {"set": ("set", "T12-20260101-01", "rejected"), "set-note": ("set-note", "T12-20260101-01", "x"), "set-bench": ("set-bench", "T12-20260101-01", "b1"),
                 "attach-commit": ("attach-commit", "T12-20260101-02", short), "expire": ("expire", "--older-than-days", "7"),
                 "append": ("T12", "잠금 없는 새 요약"), "dedupe-legacy": ("dedupe-legacy",)}
        for label, args in cases.items():
            env = dict(os.environ, HOME=str(home), PATH=path, HARNESS_GIT_DIR=str(repo))
            r = subprocess.run([bash, SH, *args], capture_output=True, text=True, env=env, check=False)
            check(f"⑧ flock 없음: {label} → 잠금 불가·exit 3·대장 불변", r.returncode == 3 and "잠금 불가" in r.stderr and cand(home) == before, f"{r.returncode} {r.stderr[:150]}")


def test_oldest_pending_axis_rule():
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, [
            f"B-1\tT41\t{days_ago(3)}\t-\tpending\tcoder/구현 정확성 : 콜론 앞 공백",
            f"B-2\tT41\t{days_ago(3)}\t-\tpending\tcoder/구현 정확성2: 이름만 비슷한 다른 축",
            f"B-3\tT41\t{days_ago(3)}\t-\tpending\t  qa/범위 준수  : 앞뒤 공백",
        ], header=HDR7)
        r = sh(home, "oldest-pending", "--limit", "3", "--t41-axes", " coder/구현 정확성 ,qa/범위 준수")
        ids = [l.split("\t")[0] for l in r.stdout.splitlines()]
        check("⑨ 축은 요약의 첫 ':' 앞(앞뒤 공백 제거)과 정확히 일치할 때만 우선(공백 변형 허용·접두 유사는 불가)", ids == ["B-1", "B-3", "B-2"], str(ids))


def test_oldest_pending_axis_role_normalized():
    # Grok 16차 3: 후보 쪽 축도 role-alias 로 정규화해 비교한다(sec-g1/x 후보 대 security/x 축, 그 반대도).
    with tempfile.TemporaryDirectory() as tmp:
        home = make_home(tmp, [
            f"A-12\tT12\t{days_ago(3)}\t-\tpending\t같은 날 교정",
            f"A-41\tT41\t{days_ago(3)}\t-\tpending\tsec-g1/x: 보안 약점",
            f"B-12\tT12\t{days_ago(2)}\t-\tpending\t같은 날 교정 2",
            f"B-41\tT41\t{days_ago(2)}\t-\tpending\tsecurity/x: 보안 약점 2",
        ], header=HDR7)
        (home / ".claude/agents").mkdir()
        (home / ".claude/agents/security.md").write_text("x", encoding="utf-8")
        r = sh(home, "oldest-pending", "--limit", "4", "--t41-axes", "security/x")
        ids = [ln.split("\t")[0] for ln in r.stdout.splitlines()]
        check("Grok16 3: sec-g1/x 후보·security/x 후보 모두 security/x 축으로 우선순위 0(같은 날 T12 보다 먼저)", ids == ["A-41", "A-12", "B-41", "B-12"], str(ids))
        r = sh(home, "oldest-pending", "--limit", "4", "--t41-axes", "sec-g1/x")
        ids = [ln.split("\t")[0] for ln in r.stdout.splitlines()]
        check("Grok16 3: 넘긴 축이 sec-g1/x 여도 같은 결과", ids == ["A-41", "A-12", "B-41", "B-12"], str(ids))


def test_lock_wait_is_bounded():
    with tempfile.TemporaryDirectory() as tmp:
        repo, _, short = make_git_repo(tmp)
        home = make_home(Path(tmp) / "h", [legacy(1), legacy(2, st="accepted"), legacy(3, src="T40", summ="x ×3")], header=HDR7)
        before = cand(home)
        fd = os.open(str(home / ".claude/_evolve/candidates.lock"), os.O_CREAT | os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            for label, args, lo, hi in (("set", ("set", "T12-20260101-01", "rejected"), 0.8, 4), ("set-note", ("set-note", "T12-20260101-01", "x"), 0.8, 4),
                                        ("set-bench", ("set-bench", "T12-20260101-01", "b1"), 0.8, 4),
                                        ("attach-commit", ("attach-commit", "T12-20260101-02", short), 0.8, 4),
                                        ("dedupe-legacy", ("dedupe-legacy",), 4.5, 8),
                                        ("append", ("T12", "잠금 중 새 요약"), 4.5, 8)):
                t0 = time.time()
                r = sh(home, *args, HARNESS_GIT_DIR=str(repo))
                dt = time.time() - t0
                check(f"A3: 잠금 점유 중 {label} → exit 3 ({dt:.1f}초 대기)", r.returncode == 3 and "잠금 실패" in r.stderr and lo < dt < hi and cand(home) == before, f"{r.returncode} {dt:.1f}s {r.stderr}")
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        r = sh(home, "set", "T12-20260101-01", "rejected")
        check("A3: 잠금이 풀리면 set 정상", r.returncode == 0 and rows(home)[0][4] == "rejected", r.stderr)


for fn in (test_header_and_append, test_legacy_six_col_read, test_set_with_note_single_call, test_set_note_sanitize,
           test_set_transition_only_from_pending_family, test_status_exact_match, test_only_machine_set_note, test_set_note_batch, test_attach_commit, test_append_vocab_and_control_chars,
           test_expire_rules, test_expire_protection_scope, test_expire_lock_busy, test_dedupe_legacy, test_oldest_pending_priority,
           test_append_pending_only_and_machine_note, test_append_dedupe_ignores_expired, test_append_expired_within_37_days_still_duplicate, test_attach_commit_ignores_non_hash_commit_text, test_attach_commit_prefix_boundary, test_attach_commit_suffix_boundary, test_expire_skip_ids, test_expire_hold_wording, test_expire_holds_when_t41_count_fails, test_expire_ids_count_failure_holds, test_expire_date_failure_holds, test_set_note_only_machine_keeps_recurred, test_set_note_batch_keeps_recurred, test_set_note_batch_1000_rows_fast, test_set_note_batch_4000_rows_via_stdin, test_storage_failure_exits_5, test_expire_holds_queue_lock_first, test_expire_self_protection, test_set_machine_accepts_commit_from_expired, test_expired_exception_end_boundary, test_expire_keeps_recurred,
           test_oldest_pending_date_first_and_skip, test_set_bench, test_set_note_appends_to_human_note, test_lock_wait_is_bounded,
           test_set_machine_flag_keeps_reviewed_marker, test_append_rejects_effect_recurred, test_no_flock_refuses_all_writes,
           test_oldest_pending_axis_rule, test_oldest_pending_axis_role_normalized):
    fn()

fail = 0
for name, ok, detail in results:
    print(f"{'OK  ' if ok else 'FAIL'} {name}")
    if not ok:
        print(f"       실제: {detail[:300]}")
    fail += 0 if ok else 1
print(f"\n{'ALL PASS' if fail == 0 else f'FAIL {fail}'} ({len(results)} checks)")
sys.exit(1 if fail else 0)
