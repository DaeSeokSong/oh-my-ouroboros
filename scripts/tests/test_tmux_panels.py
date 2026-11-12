"""tmux-panels.sh purge·cleanup 회귀 테스트 (가짜 tmux — 실제 tmux 서버·pane 은 건드리지 않는다).

실행: uv run --with pytest python -m pytest scripts/tests/test_tmux_panels.py -q

규칙 문면: 자기 pane($TMUX_PANE)은 절대 지우지 않고, purge 는 자동 생성(✳ 제목) pane 만,
cleanup 은 ✳ 와 setup 이 만든 "name [role]" pane 만 지우며, 지울 목록을 먼저 출력하고,
학습 세션(train.env 의 TRAIN_TMUX_PREFIX 로 시작하는 세션) 은 대상에서 뺀다.
"""
import json
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "tmux-panels.sh"

FAKE_TMUX = textwrap.dedent('''\
    #!/usr/bin/python3
    import json, os, sys
    st = json.load(open(os.environ["FAKE_TMUX_STATE"]))
    a = sys.argv[1:]
    log = open(os.environ["FAKE_TMUX_LOG"], "a")
    def fmt_line(f, row):
        for k, v in row.items():
            f = f.replace("#{" + k + "}", str(v))
        return f
    cmd = a[0]
    if cmd == "list-panes":
        f = a[a.index("-F") + 1]
        rows = st["panes"]
        if "-t" in a:
            idx = a[a.index("-t") + 1].lstrip(":")
            rows = [r for r in rows if str(r["window_index"]) == idx]
        else:
            rows = [r for r in rows if r["window_index"] == st["current_window"]]
        for r in rows:
            print(fmt_line(f, r))
    elif cmd == "list-windows":
        f = a[a.index("-F") + 1]
        seen = []
        for r in st["panes"]:
            key = (r["window_index"], r["window_name"], r["session_name"])
            if key not in seen:
                seen.append(key)
                print(fmt_line(f, r))
    elif cmd in ("kill-pane", "kill-window", "select-pane"):
        log.write(cmd + " " + a[a.index("-t") + 1] + "\\n")
    sys.exit(0)
''')


@pytest.fixture
def tm(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "tmux"
    fake.write_text(FAKE_TMUX)
    fake.chmod(0o755)
    proj = tmp_path / "proj" / ".claude"
    proj.mkdir(parents=True)
    (proj / "train.env").write_text("TRAIN_TMUX_PREFIX=exp-demo\nCKPT_ROOT=/x\n")

    def pane(pid, title, win=0, wname="main", sess="work"):
        return {"pane_id": pid, "pane_title": title, "window_index": win, "window_name": wname, "session_name": sess}

    state = {"current_window": 0, "panes": [
        pane("%1", "bash"),                       # 사용자가 연 일반 pane (첫 pane 이지만 main 이 아니다)
        pane("%2", "alice [coder]"),              # setup 패널
        pane("%3", "✳ Task"),                     # 자동 생성
        pane("%5", "✳ claude"),                   # 자기 자신(✳ 제목이어도 지우면 안 된다)
        pane("%6", "✳ Task", sess="exp-demo3"),    # 학습 세션 pane
        pane("%7", "w", win=1, wname="tm-1"),     # 오버플로우 창
        pane("%8", "self-win", win=2, wname="tm-2"),   # 자기 pane 이 든 오버플로우 창은 지우지 않는다
    ]}
    (tmp_path / "state.json").write_text(json.dumps(state, ensure_ascii=False))

    def run(cmd, self_pane="%5"):
        if self_pane == "%8":   # 자기 pane 이 tm-2 창에 있는 경우
            state["current_window"] = 2
            (tmp_path / "state.json").write_text(json.dumps(state, ensure_ascii=False))
        env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "TMUX_PANE": self_pane,
               "FAKE_TMUX_STATE": str(tmp_path / "state.json"), "FAKE_TMUX_LOG": str(tmp_path / "log"),
               "CLAUDE_PROJECT_DIR": str(tmp_path / "proj")}
        r = subprocess.run(["bash", str(SCRIPT), cmd], check=False, capture_output=True, text=True, env=env, cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        log = (tmp_path / "log").read_text().splitlines() if (tmp_path / "log").exists() else []
        return r.stdout, [x for x in log if x.startswith("kill-")]

    return run


def test_purge_kills_only_auto_created_panes_never_self_or_train(tm):
    out, kills = tm("purge")
    assert kills == ["kill-pane %3"]                      # %1 일반·%2 setup·%5 자기·%6 학습 세션 보존
    assert out.index("삭제 대상") < out.index("Purged")   # 목록 먼저, 삭제 나중


def test_purge_does_not_assume_first_pane_is_main(tm):
    # 자기 pane 이 첫 pane 이 아니고 ✳ 제목이어도 지워지지 않는다(수정 전에는 %5 를 지웠다)
    _, kills = tm("purge")
    assert "kill-pane %5" not in kills and "kill-pane %6" not in kills


def test_cleanup_kills_setup_and_auto_panes_and_overflow_windows(tm):
    out, kills = tm("cleanup")
    assert set(kills) == {"kill-pane %2", "kill-pane %3", "kill-window :1", "kill-window :2"}   # 자기(%5)·일반(%1)·학습(%6) 제외
    assert "삭제 대상" in out


def test_cleanup_outside_tmux_exits_zero_with_notice_and_kills_nothing(tmp_path):
    """2026-10-01 P6 검수: tmux 밖에서 cleanup 이 exit 127(또는 첫 pane 을 자기로 오인해 삭제)이던 결함 — 안내 후 정상 종료."""
    env = {k: v for k, v in os.environ.items() if k not in ("TMUX", "TMUX_PANE")}
    env["PATH"] = "/usr/bin:/bin"                                    # tmux 가 없거나 서버가 없는 환경
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    r = subprocess.run(["bash", str(SCRIPT), "cleanup"], check=False, capture_output=True, text=True, env=env, cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert "tmux 밖" in r.stdout and "삭제 대상" not in r.stdout


def test_cleanup_keeps_window_that_contains_self(tm):
    _, kills = tm("cleanup", self_pane="%8")
    assert "kill-window :2" not in kills and "kill-pane %8" not in kills
