"""public-export.sh 회귀 테스트 (임시 HOME 의 가짜 하네스 저장소 — 실제 하네스·공개 미러는 건드리지 않는다).

실행: uv run --with pytest python -m pytest scripts/tests/test_public_export.py -q
"""
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "public-export.sh"


def sh(*args, cwd, env):
    return subprocess.run(list(args), check=False, cwd=cwd, env=env, capture_output=True, text=True)


@pytest.fixture
def ex(tmp_path):
    home = tmp_path / "home"
    h = home / ".claude"
    (h / "config").mkdir(parents=True)
    (h / "docs").mkdir()
    (h / "public").mkdir()
    (h / "config/public-export-rules.txt").write_text("a|docs\nf|FORBIDDENWORD\n")
    (h / "docs/ok.md").write_text("깨끗한 문서\n")
    (h / "public/README.md").write_text("공개 README\n")
    env = {**os.environ, "HOME": str(home), "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
    sh("git", "init", "-q", cwd=h, env=env)

    def commit():
        sh("git", "add", "-A", cwd=h, env=env)
        sh("git", "commit", "-q", "-m", "x", cwd=h, env=env)

    def run(*args):
        return sh("bash", str(SCRIPT), *args, cwd=tmp_path, env=env)

    commit()
    return type("X", (), {"h": h, "tmp": tmp_path, "run": run, "commit": staticmethod(commit), "env": env})


def test_publish_refuses_non_mirror_nonempty_target_and_keeps_files(ex):
    target = ex.tmp / "precious"
    target.mkdir()
    (target / "mine.txt").write_text("소중한 파일")
    r = ex.run("--publish", str(target))
    assert r.returncode == 2 and "미러 표식" in r.stderr
    assert (target / "mine.txt").read_text() == "소중한 파일"   # 수정 전에는 --delete 로 지워졌다


def test_publish_ok_into_empty_dir_then_marker_allows_resync(ex):
    target = ex.tmp / "mirror"
    r = ex.run("--publish", str(target))
    assert r.returncode == 0, r.stdout + r.stderr
    assert (target / "docs/ok.md").exists() and (target / ".public-export-mirror").exists()
    (target / "stale.txt").write_text("지워져야 하는 옛 파일")   # 미러 표식이 있으면 --delete 동기화 허용
    assert ex.run("--publish", str(target)).returncode == 0
    assert not (target / "stale.txt").exists()


def test_publish_accepts_mirror_origin_without_marker(ex):
    target = ex.tmp / "mirror2"
    target.mkdir()
    sh("git", "init", "-q", cwd=target, env=ex.env)
    sh("git", "remote", "add", "origin", "https://github.com/x/oh-my-ouroboros.git", cwd=target, env=ex.env)
    (target / "old.txt").write_text("옛 파일")
    assert ex.run("--publish", str(target)).returncode == 0


def test_publish_refuses_target_inside_harness(ex):
    r = ex.run("--publish", str(ex.h / "docs"))
    assert r.returncode == 2


def test_forbidden_word_in_path_name_blocks(ex):
    (ex.h / "docs/FORBIDDENWORD-notes.md").write_text("본문은 깨끗\n")
    ex.commit()
    r = ex.run()
    assert r.returncode == 3 and "경로 이름" in r.stdout


def test_invalid_utf8_file_is_not_skipped_by_gate(ex):
    (ex.h / "docs/bad.bin").write_bytes(b"\x00\xff\xfe FORBIDDENWORD \xff\n")   # 이진: grep -I 가 건너뛰던 형태
    ex.commit()
    assert ex.run().returncode == 3


def test_empty_allowlist_refuses_instead_of_publishing_everything(ex):
    (ex.h / "config/public-export-rules.txt").write_text("f|FORBIDDENWORD\n")
    ex.commit()
    r = ex.run()
    assert r.returncode == 2 and "allowlist" in r.stderr


def test_untracked_public_files_are_not_staged(ex):
    (ex.h / "public/leak.txt").write_text("미추적 잔재\n")
    target = ex.tmp / "mirror3"
    assert ex.run("--publish", str(target)).returncode == 0
    assert (target / "README.md").exists() and not (target / "leak.txt").exists()


# ---- --stage-out(2026-10-23, intent/2026-10-23-public-mirror-refresh.md): 정제본을 남기고 게이트 결과로 끝낸다 ----
def test_stage_out_keeps_sanitized_copy_and_does_not_publish(ex):
    out = ex.tmp / "stage"
    r = ex.run("--stage-out", str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    assert (out / "docs/ok.md").read_text() == "깨끗한 문서\n" and (out / "README.md").exists()
    assert not (ex.tmp / "home/workspace/oh-my-ouroboros").exists()   # 발행 대상 폴더는 만들지 않는다


def test_stage_out_keeps_copy_even_when_gate_blocks(ex):
    (ex.h / "docs/bad.md").write_text("FORBIDDENWORD 남음\n")
    ex.commit()
    out = ex.tmp / "stage2"
    r = ex.run("--stage-out", str(out))
    assert r.returncode == 3 and "금지 패턴" in r.stdout
    assert (out / "docs/bad.md").exists()                                 # 막혀도 막힌 자리를 검사할 수 있게 남긴다


def test_stage_out_refuses_nonempty_dir(ex):
    out = ex.tmp / "busy"
    out.mkdir()
    (out / "x.txt").write_text("x")
    r = ex.run("--stage-out", str(out))
    assert r.returncode == 2 and (out / "x.txt").read_text() == "x"


def test_stage_out_relative_path_is_resolved_from_caller_cwd(ex):
    r = ex.run("--stage-out", "rel-stage")                              # 시험 러너의 cwd 는 ex.tmp
    assert r.returncode == 0, r.stdout + r.stderr
    assert (ex.tmp / "rel-stage/docs/ok.md").exists()
    assert not (ex.h / "rel-stage").exists()                            # 하네스 안에 만들지 않는다(qa 2026-10-23)


def test_stage_out_refuses_tracked_place_inside_harness_and_symlink(ex):
    r = ex.run("--stage-out", str(ex.h / "docs-out"))
    assert r.returncode == 2 and not (ex.h / "docs-out").exists()          # 하네스 안 추적 경로 거부
    assert ex.run("--stage-out", str(ex.h / ".scratch/s1")).returncode == 0  # .scratch 아래는 허용
    real = ex.tmp / "real-out"
    real.mkdir()
    link = ex.tmp / "link-out"
    link.symlink_to(real)
    assert ex.run("--stage-out", str(link)).returncode == 2
    assert oct((ex.h / ".scratch/s1").stat().st_mode & 0o777) == "0o700"


# ---- d|·r|·j| 규칙과 정제 뒤 문법 게이트(2026-10-23: 내부 언급은 가명 치환이 아니라 삭제) ----
def rules(ex, body):
    (ex.h / "config/public-export-rules.txt").write_text("a|docs\na|settings.json\n" + body)
    ex.commit()


def test_d_rule_deletes_lines_only_in_glob_matched_files(ex):
    (ex.h / "docs/a.md").write_text("keep\nINTERNAL line\nkeep2\n")
    (ex.h / "docs/b.txt").write_text("INTERNAL line\n")
    rules(ex, "d|docs/*.md|INTERNAL\n")
    out = ex.tmp / "o1"
    r = ex.run("--stage-out", str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    assert (out / "docs/a.md").read_text() == "keep\nkeep2\n"
    assert (out / "docs/b.txt").read_text() == "INTERNAL line\n"
    assert "미적중" not in r.stdout


def test_r_rule_is_limited_to_glob(ex):
    (ex.h / "docs/a.md").write_text("see FOO here\n")
    (ex.h / "docs/b.txt").write_text("see FOO here\n")
    rules(ex, "r|docs/*.md|s/ FOO//\n")
    out = ex.tmp / "o2"
    assert ex.run("--stage-out", str(out)).returncode == 0
    assert (out / "docs/a.md").read_text() == "see here\n"
    assert (out / "docs/b.txt").read_text() == "see FOO here\n"


def test_unmatched_rule_warns_without_blocking_or_echoing_expr(ex):
    rules(ex, "d|docs/*.md|NOSUCHTEXT_SECRET\nr|nomatch/*|s/x/y/\n")
    r = ex.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "⚠ 미적중 규칙: d|docs/*.md" in r.stdout and "⚠ 미적중 규칙: r|nomatch/*" in r.stdout
    assert "NOSUCHTEXT_SECRET" not in r.stdout + r.stderr


def test_j_rule_removes_hook_and_cleans_empty_groups(ex):
    import json
    (ex.h / "settings.json").write_text(json.dumps({"model": "x", "hooks": {
        "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "bash ~/a/secret-hook.sh"}]},
                       {"matcher": "Edit", "hooks": [{"type": "command", "command": "bash ~/a/keep.sh"}]}],
        "Stop": [{"hooks": [{"type": "command", "command": "bash ~/a/secret-hook.sh"}]}]}}))
    rules(ex, "j|secret-hook\n")
    out = ex.tmp / "o3"
    r = ex.run("--stage-out", str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    data = json.loads((out / "settings.json").read_text())
    assert data["model"] == "x" and "Stop" not in data["hooks"]
    assert [g["matcher"] for g in data["hooks"]["PreToolUse"]] == ["Edit"]


def test_d_rule_breaking_python_blocks_with_exit_3_but_keeps_stage_copy(ex):
    (ex.h / "docs/m.py").write_text("def f():\n    return 1\n")   # 본문 줄을 지우면 빈 함수 = 문법 오류
    rules(ex, "d|docs/*.py|return 1\n")
    out = ex.tmp / "o4"
    r = ex.run("--stage-out", str(out))
    assert r.returncode == 3 and "정제 뒤 문법 깨짐: docs/m.py" in r.stdout
    assert (out / "docs/m.py").exists()


def test_d_rule_ere_may_contain_slash_and_hash(ex):
    (ex.h / "docs/a.md").write_text("keep\npath /internal/x # note\nkeep2\n")
    rules(ex, "d|docs/*|/internal/x # note\n")
    out = ex.tmp / "o5"
    r = ex.run("--stage-out", str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    assert (out / "docs/a.md").read_text() == "keep\nkeep2\n"
