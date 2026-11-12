"""git_guard_ext.py 회귀 테스트 (2026-11-09 5단계).

실행: uv run --no-project python scripts/tests/test_git_guard_ext.py
임시 git 저장소(파일 a.txt·b.txt·sub/f.txt, 커밋 1개, a.txt·sub/f.txt 는 수정됨)를 만들고
git-guardrails.sh 전체 체인과 확장 파일 단독 판정을 본다. 막힘마다 통과 쌍을 함께 둔다.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
HOOK = SCRIPTS / "git-guardrails.sh"
EXT = SCRIPTS / "git_guard_ext.py"
HOOKS_DIR = str(Path.home() / ".claude/.git/hooks")
REPO = ""
FREPO = ""
BREPO = ""
TMP = ""


def setUpModule():
    """Create the temporary repositories: REPO (plain), FREPO (has a filter.* config), BREPO (a previous branch for @{-1})."""
    global REPO, FREPO, BREPO, TMP
    TMP = tempfile.mkdtemp(prefix="gge-")
    REPO = os.path.join(TMP, "repo")
    FREPO = os.path.join(TMP, "frepo")
    BREPO = os.path.join(TMP, "brepo")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}

    def git(repo, *a):
        subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True, env=env)

    for repo in (REPO, FREPO, BREPO):
        os.makedirs(os.path.join(repo, "sub"))
        git(repo, "init", "-q", "-b", "main")
        git(repo, "config", "user.name", "t")
        git(repo, "config", "user.email", "t@example.com")
        for rel in ("a.txt", "b.txt", "c.txt", "d.txt", "sub/f.txt"):
            Path(repo, rel).write_text("v1\n")
        git(repo, "add", ".")
        git(repo, "commit", "-q", "-m", "init")
        Path(repo, "a.txt").write_text("v2\n")
    git(BREPO, "checkout", "-q", "-b", "other")  # now @{-1} = main
    Path(BREPO, "a.txt").write_text("v1\n")  # keep BREPO clean
    Path(REPO, "sub/f.txt").write_text("v2\n")
    # c.txt: assume-unchanged, d.txt: skip-worktree; both edited, so `git diff` cannot see the change (R5)
    git(REPO, "update-index", "--assume-unchanged", "c.txt")
    git(REPO, "update-index", "--skip-worktree", "d.txt")
    Path(REPO, "c.txt").write_text("v2\n")
    Path(REPO, "d.txt").write_text("v2\n")
    git(FREPO, "config", "filter.x.clean", "cat")  # R10: only a.txt carries the filter attribute
    Path(FREPO, ".gitattributes").write_text("a.txt filter=x\n")
    git(FREPO, "add", ".gitattributes")
    git(FREPO, "commit", "-q", "-m", "attrs")


def tearDownModule():
    """Remove the temporary repository."""
    shutil.rmtree(TMP, ignore_errors=True)


def run(cmd_list, cmd, cwd):
    """Run a hook command with a PreToolUse payload and return whether it printed a deny."""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd})
    r = subprocess.run(cmd_list, input=payload, check=False, capture_output=True, text=True)
    return '"deny"' in r.stdout


def chain(cmd, cwd=None):
    """Judge through the whole git-guardrails.sh chain."""
    return run(["bash", str(HOOK)], cmd, cwd or REPO)


def ext(cmd, cwd=None):
    """Judge through git_guard_ext.py alone."""
    return run(["python3", "-I", str(EXT)], cmd, cwd or REPO)


def ext_mod():
    """Import git_guard_ext.py as a module (for the tokenizer test)."""
    spec = importlib.util.spec_from_file_location("git_guard_ext", EXT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# (이름, 명령, 차단 기대)
CASES = [
    # restore
    ("restore 수정 파일", "git restore a.txt", True),
    ("restore 수정 안 한 파일", "git restore b.txt", False),
    ("restore --staged", "git restore --staged a.txt", False),
    ("restore -SW 수정 파일", "git restore -SW a.txt", True),
    ("restore --source=HEAD 수정 파일", "git restore --source=HEAD a.txt", True),
    ("restore --source HEAD 수정 파일(값 분리)", "git restore --source HEAD a.txt", True),
    ("restore -s HEAD 수정 파일", "git restore -s HEAD a.txt", True),
    ("restore -p", "git restore -p a.txt", True),
    ("restore --pathspec-from-file", "git restore --pathspec-from-file=list.txt", True),
    ("restore --stag 약어 + 수정 파일 안 건드림", "git restore --stag a.txt", False),
    ("restore --stag --work 약어 수정 파일", "git restore --stag --work a.txt", True),
    ("restore 경로 없음", "git restore", False),
    # checkout
    ("checkout -- 수정 파일", "git checkout -- a.txt", True),
    ("checkout -- 수정 안 한 파일", "git checkout -- b.txt", False),
    ("checkout HEAD -- 수정 파일", "git checkout HEAD -- a.txt", True),
    ("checkout 수정 파일(-- 없이)", "git checkout a.txt", True),
    ("checkout 브랜치 전환", "git checkout main", False),
    ("checkout -b new", "git checkout -b new", False),
    ("checkout -b new HEAD", "git checkout -b new HEAD", False),
    ("checkout --detach HEAD", "git checkout --detach HEAD", False),
    ("checkout -p", "git checkout -p HEAD -- a.txt", True),
    # 기준 폴더
    ("cd sub && git restore f.txt", "cd sub && git restore f.txt", True),
    ("git -C repo restore 수정 파일", "git -C @REPO@ restore a.txt", True),
    ("git -C repo restore 수정 안 한 파일", "git -C @REPO@ restore b.txt", False),
    ("git -C sub restore (상대 -C)", "git -C sub restore f.txt", True),
    ("경로에 변수 확장", "git restore $F", True),
    # 이력 · 객체 삭제
    ("filter-repo", "git filter-repo --path x", True),
    ("filter-branch", "git filter-branch --tree-filter x", True),
    ("update-ref -d", "git update-ref -d refs/heads/x", True),
    ("update-ref --stdin", "git update-ref --stdin", True),
    ("update-ref 생성", "git update-ref refs/heads/x HEAD", False),
    ("gc --prune=now", "git gc --prune=now", True),
    ("gc", "git gc", False),
    ("gc --no-prune", "git gc --no-prune", False),
    ("reflog expire", "git reflog expire --expire=now --all", True),
    ("reflog delete", "git reflog delete HEAD@{1}", True),
    ("reflog", "git reflog", False),
    ("reflog show", "git reflog show HEAD", False),
    ("rebase main", "git rebase main", True),
    ("rebase -i", "git rebase -i HEAD~2", True),
    ("rebase --abort", "git rebase --abort", False),
    ("prune", "git prune", True),
    ("prune -n", "git prune -n", False),
    # -c 허용 목록
    ("-c core.fsmonitor", "git -c core.fsmonitor=x status", True),
    ("-c core.pager", "git -c core.pager=x log", True),
    ("-c diff.external", "git -c diff.external=x diff", True),
    ("-c core.editor", "git -c core.editor=x commit", True),
    ("-cCore.Pager=x", "git -cCore.Pager=x log", True),
    ("-c 변수 확장", "git -c user.name=$X status", True),
    ("--config-env", "git --config-env=user.name=NAME status", True),
    ("-c user.name", "git -c user.name=x status", False),
    ("-c protocol.version", "git -c protocol.version=2 status", False),
    ("-c core.quotePath=false", "git -c core.quotePath=false status", False),
    ("-c color.ui", "git -c color.ui=always log", False),
    ("-c 하네스 훅 경로", f"git -c core.hooksPath={HOOKS_DIR} status", False),
    ("-c 하네스 훅 경로 끝 슬래시", f"git -c core.hooksPath={HOOKS_DIR}/ status", False),
    ("-c 하네스 훅 경로 + HOME 재대입", f"HOME=/tmp git -c core.hooksPath={HOOKS_DIR} status", True),
    ("-c 다른 훅 경로", "git -c core.hooksPath=/tmp/evil status", True),
    ("--exec-path=값", "git --exec-path=/tmp/evil status", True),
    # 환경 변수
    ("GIT_CONFIG_COUNT", "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.pager GIT_CONFIG_VALUE_0=x git log", True),
    ("GIT_EXTERNAL_DIFF", "GIT_EXTERNAL_DIFF=x git diff", True),
    ("export GIT_SSH_COMMAND", "export GIT_SSH_COMMAND=x; git fetch", True),
    ("GIT_PAGER=cat", "GIT_PAGER=cat git log", False),
    ("GIT_PAGER=evil", "GIT_PAGER=evil git log", True),
    ("env 바깥 + bash -c 안", "GIT_SSH=x bash -c 'git status'", True),
    ("git 없는 명령의 변수", "GIT_SSH=x ls", False),
    # 우회형
    ("bash -c rebase", "bash -c 'git rebase main'", True),
    ("bash -c 안 restore", "bash -c 'git restore a.txt'", True),
    ("eval rebase", "eval git rebase main", True),
    ("중첩 bash -c", "bash -c \"bash -c 'git rebase main'\"", True),
    ("git-core 전체 경로", "/usr/lib/git-core/git-rebase main", True),
    ("git-filter-repo", "git-filter-repo --path x", True),
    ("따옴표 쪼개기", 'git "re"base main', True),
    ("xargs git restore", "xargs git restore", True),
    ("앞 대입 + restore", "FOO=1 git restore a.txt", True),
    ("줄바꿈 뒤 rebase", "git status\ngit rebase main", True),
    ("파이프 뒤 rebase", "git log | git rebase main", True),
    ("env 접두 + restore 수정 안 한 파일", "env FOO=1 git restore b.txt", False),
    ("timeout 접두 + restore (명령 자리 아님)", "timeout 5 git restore b.txt", True),
    ("셸에 먹이는 heredoc", "bash <<'EOF'\ngit rebase main\nEOF", True),
    ("치환이 있는 heredoc", "cat <<EOF\n$(git rebase main)\nEOF", True),
    # 오탐 방지
    ("heredoc 커밋 메시지(아포스트로피)는 이제 막힘(r5 H)", "git commit -F - <<'EOF'\nfix: Don't rebase\nEOF", True),
    ("heredoc 메시지 + 뒤 명령", "git commit -F - <<'EOF'\nit's rebase\nEOF\ngit rebase main", True),
    ("커밋 메시지 속 git rebase", 'git commit -m "docs: git rebase 설명"', False),
    ("git log --grep=rebase", "git log --grep=rebase", False),
    ("git status", "git status", False),
    ("git diff 리다이렉션", "git diff > /tmp/out.txt", False),
    ("git log 2>&1", "git log 2>&1", False),
    ("git 없는 명령", "ls -la", False),
]

# 검수 지적 R1~R10 (2026-11-09 개정 2). 확장 파일 단독으로도 같은 판정이어야 한다.
R_CASES = [
    # R1 셸 확장 위생
    ("줄 이음으로 쪼갠 하위명령", "git re\\\nbase main", True),
    ("줄 이음 + git 없음", "echo a\\\nb", False),
    ("하위명령에 변수", "git $SUB main", True),
    ("하위명령에 ${}", "git ${X}base main", True),
    ("하위명령에 glob", "git re*e main", True),
    ("하위명령에 백틱", "git `echo rebase` main", True),
    ("전역 옵션에 변수", "git $OPTS status", True),
    ("전역 옵션 값에 변수", 'git -C "$D" status', True),
    ("rebase 인자에 변수", "git rebase $B", True),
    ("restore 경로 glob 은 확인 호출로 판정(수정 파일 포함)", "git restore a*", True),
    ("restore 경로 glob 수정 안 한 파일", "git restore b*", False),
    ("reflog show @{}", "git reflog show HEAD@{0}", False),
    ("커밋 메시지의 중괄호·glob·변수", 'git commit -m "a*b {c} $d"', False),
    # heredoc 금지 H (옛 R2 판정은 폐기: 따옴표 밖 << 가 있으면 전부 막힘, 따옴표 안·산술·주석 속 << 도 같은 사례로 남겨 둠)
    ("큰따옴표 안 <<", 'echo "<<EOF"\ngit rebase main', True),
    ("작은따옴표 안 <<", "echo '<<X'\ngit rebase main", True),
    ("커밋 메시지 안 <<", 'git commit -m "fix: handle <<EOF markers"\ngit rebase main', True),
    ("주석 안 <<", "git status # <<X\ngit rebase main", True),
    ("산술 안 <<", "echo $((1<<X))\ngit rebase main", True),
    ("종결자 없는 셸 heredoc", "bash <<EOF\ngit rebase main", True),
    ("<<< 는 heredoc 아님", "cat <<< x\ngit rebase main", True),
    ("heredoc 커밋 메시지는 막힘(r5 H)", "git commit -F - <<'EOF'\nfix: Don't push\nEOF", True),
    ("heredoc 를 셸로 파이프", "cat <<EOF | bash\ngit rebase main\nEOF", True),
    # R3 문자열 래퍼
    ("sh -lc", "sh -lc 'git rebase main'", True),
    ("zsh -c", "zsh -c 'git rebase main'", True),
    ("fish -c", "fish -c 'git rebase main'", True),
    ("busybox sh -c", "busybox sh -c 'git rebase main'", True),
    ("env -S", "env -S 'git rebase main'", True),
    ("env --split-string=", "env --split-string='git rebase main'", True),
    ("su -c", "su -c 'git rebase main' root", True),
    ("flock -c", "flock /tmp/l -c 'git rebase main'", True),
    ("script -qc", "script -qc 'git rebase main' /dev/null", True),
    ("watch", "watch 'git rebase main'", True),
    ("watch -n", "watch -n 5 'git rebase main'", True),
    ("tmux new-session", "tmux new-session -d 'git rebase main'", True),
    ("tmux send-keys", "tmux send-keys -t s 'git rebase main' Enter", True),
    ("here-string 을 셸에", "bash <<< 'git rebase main'", True),
    ("따옴표 안 $()", 'echo "$(git rebase main)"', True),
    ("따옴표 안 백틱", 'echo "`git rebase main`"', True),
    ("watch 안전한 명령", "watch 'git status'", False),
    ("tmux 안전한 명령", "tmux send-keys -t s 'git status' Enter", False),
    ("bash -c 안전한 명령", "bash -c 'git status'", False),
    ("따옴표 안 안전한 $()", 'echo "$(git status)"', False),
    ("따옴표 문자열은 데이터", 'grep "git rebase" notes.txt', False),
    # R4 환경 변수
    ("HOME 재대입", "HOME=/tmp git status", True),
    ("XDG_CONFIG_HOME", "XDG_CONFIG_HOME=/tmp git status", True),
    ("LD_PRELOAD", "LD_PRELOAD=/tmp/x.so git status", True),
    ("PATH 대입", "PATH=/tmp:$PATH git status", True),
    ("export PATH", "export PATH=/tmp; git status", True),
    ("PATH+=", "PATH+=:/tmp git status", True),
    ("GIT_OBJECT_DIRECTORY", "GIT_OBJECT_DIRECTORY=/tmp git log", True),
    ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_GLOBAL=/tmp/c git log", True),
    ("GIT_INDEX_FILE", "GIT_INDEX_FILE=/tmp/i git status", True),
    ("GIT_WORK_TREE", "GIT_WORK_TREE=/tmp git status", True),
    ("GIT_PAGER+=", "GIT_PAGER+=evil git log", True),
    ("무해한 변수", "LANG=C git status", False),
    ("목록 밖 += 변수", "FOO+=x git status", False),
    # R5 diff 에 안 보이는 변경
    ("assume-unchanged 로 숨긴 수정", "git restore c.txt", True),
    ("skip-worktree 로 숨긴 수정", "git restore d.txt", True),
    ("update-index --assume-unchanged", "git update-index --assume-unchanged b.txt", True),
    ("update-index --skip-worktree", "git update-index --skip-worktree b.txt", True),
    ("update-index --assume-unch 약어", "git update-index --assume-unch b.txt", True),
    ("update-index --no-assume-unchanged", "git update-index --no-assume-unchanged c.txt", False),
    ("update-index --no-skip-worktree", "git update-index --no-skip-worktree d.txt", False),
    ("update-index --refresh", "git update-index --refresh", False),
    # R6 같은 효과의 다른 하위명령
    ("checkout-index", "git checkout-index -f -a", True),
    ("git-checkout-index", "/usr/lib/git-core/git-checkout-index -a", True),
    ("read-tree -u", "git read-tree -u HEAD", True),
    ("read-tree -mu 묶음", "git read-tree -mu HEAD", True),
    ("read-tree --reset", "git read-tree --reset HEAD", True),
    ("read-tree 단순", "git read-tree HEAD", False),
    ("apply -R", "git apply -R p.diff", True),
    ("apply --reverse", "git apply --reverse p.diff", True),
    ("apply --rev 약어", "git apply --rev p.diff", True),
    ("apply --check", "git apply --check p.diff", False),
    ("apply --stat", "git apply --stat p.diff", False),
    ("apply 단순 (r5fix 5: 조회형이 아니면 막힘)", "git apply p.diff", True),
    # R7 옵션 약어 · 영 oid
    ("gc --pru", "git gc --pru=now", True),
    ("gc --p", "git gc --p", True),
    ("gc --auto", "git gc --auto", False),
    ("reset --ha", "git reset --ha HEAD", True),
    ("reset --soft", "git reset --soft HEAD", False),
    ("checkout --forc", "git checkout --forc main", True),
    ("switch --force", "git switch --force main", True),
    ("switch --discard 약어", "git switch --discard main", True),
    ("switch 단순", "git switch main", False),
    ("clean --forc", "git clean --forc", True),
    ("clean -n", "git clean -n", False),
    ("update-ref --std", "git update-ref --std", True),
    ("update-ref --del", "git update-ref --del refs/heads/x", True),
    ("update-ref 영 oid", "git update-ref refs/heads/x 0000000000000000000000000000000000000000", True),
    ("update-ref 영 oid + 리다이렉션", "git update-ref refs/heads/x 0000000000000000000000000000000000000000 >/dev/null", True),
    ("update-ref 일반 oid", "git update-ref refs/heads/x 1234567890abcdef", False),
    # R8 리다이렉션 숫자
    ("rebase --abort 2>&1", "git rebase --abort 2>&1", False),
    ("rebase main 2>&1", "git rebase main 2>&1", True),
    ("rebase --abort >/dev/null 2>&1", "git rebase --abort >/dev/null 2>&1", False),
    # R9 git config 쓰기
    ("config user.name 쓰기", "git config user.name x", False),
    ("config --global user.email", "git config --global user.email a@b.c", False),
    ("config core.pager 쓰기", "git config core.pager x", True),
    ("config --add core.editor", "git config --add core.editor x", True),
    ("config --replace-all core.fsmonitor", "git config --replace-all core.fsmonitor x", True),
    ("config --local --file 목록 밖", "git config --local --file x.cfg diff.external y", True),
    ("config set 목록 밖", "git config set core.pager x", True),
    ("config set 허용 키", "git config set user.name x", False),
    ("config --get", "git config --get core.pager", False),
    ("config 키만", "git config core.pager", False),
    ("config --list", "git config --list", False),
    ("config -l", "git config -l", False),
    ("config --unset", "git config --unset core.pager", False),
    ("config --global --unset-all (sec4: 사용자 설정 항목 삭제라 막힘)", "git config --global --unset-all core.pager", True),
    ("config --unset-all 저장소 범위", "git config --unset-all core.pager", False),
    ("config get", "git config get core.pager", False),
    ("config --show-origin --get", "git config --show-origin --get core.pager", False),
]

# 개정 3 (R11 셸 수준 간접 이름) · 개정 4 소수정(프로세스 치환 등). 확장 파일 단독으로도 같은 판정이어야 한다. R2b(heredoc 본문 재검사)는 r5 H 로 폐기됐다.
R11_CASES = [
    ("alias g=git", "alias g=git; g gc --prune=now", True),
    ("alias 줄바꿈", "alias g=git\ng gc --prune=now", True),
    ("alias --", "alias -- g=git; g rebase main", True),
    ("alias -g", "alias -g G=git; G gc", True),
    ("alias 값에 git 명령", "alias gg='git gc'; gg --prune=now", True),
    ("변수 명령어", "G=git; $G gc --prune=now", True),
    ('따옴표 변수 명령어', 'G=git; "$G" rebase main', True),
    ("${} 명령어", "G=git; ${G} rebase main", True),
    ("백틱 명령어", "G=git; `echo git` gc", True),
    ("$() 명령어", "$(echo git) gc --prune=now", True),
    ("함수 정의", 'f() { git "$@"; }; f gc --prune=now', True),
    ("function 키워드", 'function f { git "$@"; }; f rebase main', True),
    ("함수 본문 따옴표 안 }", 'f() { echo "}"; git "$@"; }; f gc --prune=now', True),
    ("서브셸 본문 함수", 'f() ( git "$@" ); f gc --prune=now', True),
    ("hash -p", "hash -p /usr/bin/git g; g rebase main", True),
    ("hash 이름=경로", "hash g=/usr/bin/git; g rebase main", True),
    ("bash -c 안 alias", "bash -c 'alias g=git; g gc'", True),
    ("별칭 없는 alias", "alias ll='ls -l'; git status", False),
    ("함수 본문에 git 없음", "f() { :; }; git status", False),
    ("따옴표 속 함수 꼴", 'git commit -m "f() { git x; }"', False),
    ("git 없는 변수 명령", 'X=ls; $X -l', False),
    ("git 상태", "git status", False),
    ("git log", "git log --oneline -3", False),
]

R4_CASES = [
    # 옛 R2b(본문으로 잘못 판정된 줄 재검사) 사례: r5 H 이후엔 << 자체가 막히거나(산술·heredoc) 앞뒤 명령이 막힌다
    ("맨몸 산술 << ", "((1<<2))\ngit rebase main\n2", True),
    ("맨몸 산술 공백", "(( x = 1<<2 ))\ngit rebase main\n2", True),
    ("for 산술", "for ((i=1<<0; i<2; i++)); do :; done\ngit rebase main\n0", True),
    ("ANSI-C 인용 안 \\'", "echo $'\\' <<EOF\n' ; git rebase main\nEOF", True),
    ("heredoc 본문의 명령 자리 git(파싱 실패 줄)", "cat <<EOF\nit's ok; git rebase main\nEOF", True),
    ("heredoc 본문의 대입 뒤 git", "cat <<EOF\nFOO=1 git rebase main\nEOF", True),
    # r5 H: git 낱말 + 따옴표 밖 << 이면 본문이 무엇이든 막힘
    ("heredoc 커밋 메시지(아포스트로피)", "git commit -F - <<'EOF'\nfix: Don't push\nEOF", True),
    ("heredoc 커밋 메시지 속 git rebase 설명", "git commit -F - <<'EOF'\ndocs: git rebase 설명\nEOF", True),
    ("heredoc 메시지 중간에 git 낱말", "git commit -F - <<'EOF'\nfix: x\n\nrun git rebase later; don't\nEOF", True),
    ("heredoc 메시지 속 백틱 git", "git commit -F - <<'EOF'\nuse `git rebase` carefully\nEOF", True),
    ("heredoc 메시지 속 bash -c", "git commit -F - <<'EOF'\nnote: bash -c 'git rebase main' is risky\nEOF", True),
    ("heredoc 메시지 속 $ 로 시작하는 줄", "git commit -F - <<'EOF'\n$HOME is set; git ok\nEOF", True),
    ("<<- 탭 제거 heredoc", "git commit -F - <<-EOF\nfix: x\nEOF", True),
    ("공백 없는 <<", "git commit -F -<<EOF\nfix: x\nEOF", True),
    ("heredoc 뒤에 git 이 오는 경우", "cat <<EOF > f.txt\nhello\nEOF\ngit status", True),
    ("heredoc 안에 git 만 있고 명령은 비git", "cat <<EOF\ngit status 설명\nEOF", True),
    ("산술 << + git status", "echo $((1<<3)); git status", True),
    ("git 없는 heredoc 은 통과", "cat <<EOF\nit's fine\nEOF", False),
    ("git 없는 heredoc 파일 쓰기", "cat <<'EOF' > /tmp/x.txt\nhello\nEOF", False),
    ("따옴표 안 << 는 데이터", 'git commit -m "fix: handle <<EOF markers"', False),
    ("<<< 는 heredoc 아님", "git log <<< ''", False),
    # 소수정 1: 프로세스 치환
    ("프로세스 치환 <(", "cat <(git rebase main)", True),
    ("프로세스 치환 >(", "tee >(git rebase main) < /dev/null", True),
    ("프로세스 치환 안전한 명령", "diff <(git log -1) <(git log -2)", False),
]


# 개정 5 C: 넓은 범위 대상 목록 89건 (probe_cases_sec3.json 과 같은 순서, 차단 기대). 통과 = 정상·되돌릴 수 있음.
C_CASES = [
    ("git merge --abort", False), ("git merge --quit", True), ("git cherry-pick --abort", False),
    ("git cherry-pick --quit", True), ("git revert --abort", False), ("git am --abort", False),
    ("git reset --merge", True), ("git reset --keep HEAD~1", True), ("git reset --mixed HEAD~1", False),
    ("git reset --soft HEAD~1", False), ("git rm -f a.txt", True), ("git rm -rf src", True),
    ("git mv -f a.txt b.txt", True), ("yes | git clean -di", True), ("git clean -n -d", False),
    ("git worktree remove --force ../wt", True), ("git worktree remove -f -f ../wt", True),
    ("git worktree prune", True), ("git submodule deinit -f --all", True),
    ("git submodule update --init --force", True), ("git submodule foreach 'git reset --hard'", True),
    ("git submodule foreach 'git checkout -- .'", True), ("git sparse-checkout set subdir", True),
    ("git sparse-checkout disable", True), ("git diff --output=a.txt", True), ("git log --output=a.txt", True),
    ("git archive HEAD -o a.txt", True), ("git restore --staged a.txt", False), ("git checkout --ours a.txt", True),
    ("git update-index --force-remove a.txt", True), ("git checkout -B main HEAD~1", True),
    ("git switch -C main HEAD~1", True), ("git commit --amend --no-edit", False), ("git rebase --abort", False),
    ("git rebase --quit", True), ("git stash create", True), ("git tag -d v1", True), ("git tag --delete v1", True),
    ("git tag -f v1 HEAD~1", True), ("git branch -d feature", False), ("git branch -f main HEAD~2", True),
    ("git branch -M old main", True), ("git branch --move --force old main", True),
    ("git branch -m main renamed", False), ("git branch -D x", True),
    ("git symbolic-ref HEAD refs/heads/other", True), ("git symbolic-ref -d HEAD", True),
    ("git notes remove HEAD", True), ("git notes add -f -m x HEAD", True), ("git notes prune", True),
    ("git replace -d abc123", True), ("git replace --graft HEAD HEAD~1", True), ("git remote remove origin", True),
    ("git remote prune origin", False), ("git fetch --prune origin", False), ("git fetch . +dev:main", True),
    ("git update-ref refs/heads/main HEAD~2", True), ("git gc", False), ("git gc --aggressive", False),
    ("git gc --auto", False), ("git repack -a -d", True), ("git repack -ad -l", True),
    ("git pack-refs --all --prune", False), ("git maintenance run", False),
    ("git maintenance run --task=gc", False), ("git maintenance start", True), ("git maintenance register", True),
    ("git fast-import --force", True), ("git prune-packed", False), ("git fsck --lost-found", False),
    ("git config --remove-section remote.origin", True), ("git config --edit", True),
    ("git bisect run ./check.sh", True), ("git difftool -y -x ./tool.sh", True),
    ("git difftool -y --extcmd=./tool.sh", True), ("git grep --open-files-in-pager=./tool.sh x", True),
    ("git ls-remote --upload-pack='touch /tmp/x' /tmp/repo", True),
    ("git fetch --upload-pack='touch /tmp/x' /tmp/repo", True),
    ("git clone --upload-pack='touch /tmp/x' /tmp/repo /tmp/c", True),
    ("git archive --remote=/tmp/repo --exec='touch /tmp/x' HEAD", True), ("git init --template=/tmp/tpl /tmp/n", True),
    ("git clone --template=/tmp/tpl /tmp/repo /tmp/c2", True), ("LD_AUDIT=/tmp/x.so git status", True),
    ("BASH_ENV=/tmp/x git status", True), ("GIT_TRACE2_EVENT=/tmp/f git status", True),  # r5fix 13: 파일 경로 값은 임의 파일 추가 쓰기
    ("GIT_CEILING_DIRECTORIES=/ git status", False), ("git --paginate log", False),
    ("git rebase --exec x main", True), ("git status", False),
]

# 같은 근거의 정상 사용: 넓은 범위 deny 가 평소 쓰는 형태를 막지 않는지 본다.
C_NORMAL = [
    "git symbolic-ref HEAD", "git symbolic-ref --short HEAD", "git symbolic-ref -q HEAD", "git tag", "git tag -l 'v*'",
    "git tag v2 -m release", "git tag -a v3 -m 'release note'", "git branch", "git branch -a", "git branch -vv",
    "git branch --list 'feat/*'", "git branch new-one", "git branch -u origin/main", "git remote -v",
    "git remote add up https://example.com/r.git", "git remote show origin", "git fetch origin",
    "git fetch --all --tags", "git notes list", "git notes show HEAD", "git notes add -m 'x' HEAD",
    "git submodule status", "git submodule update --init", "git worktree list", "git worktree add ../w2",
    "git rm --cached a.txt", "git rm -r --cached sub", "git mv b.txt e.txt", "git sparse-checkout list",
    "git diff --stat", "git diff --name-only HEAD", "git log --oneline -3", "git log --format=%s -n 2",
    "git show HEAD --stat", "git grep -n foo", "git grep -e 'a*' -- '*.py'", "git replace -l", "git replace",
    "git config --get user.name", "git config user.name x", "git config --unset core.pager", "git merge feature",
    "git merge --no-ff feature", "git cherry-pick HEAD", "git revert --no-edit HEAD", "git am --continue",
    "git clean -n", "git clean --dry-run -d", "git reset", "git reset HEAD a.txt", "git switch -c topic",
    "git checkout -b topic2", "git update-ref refs/heads/main HEAD", "git update-ref -m msg refs/heads/new HEAD",
    "git repack", "git repack -l", "git bisect start", "git bisect good", "git bisect reset", "git clone https://example.com/r.git",
    "git init", "git init -b main", "git archive HEAD", "git archive --format=tar HEAD", "git maintenance run --auto",
    "git commit -m 'x' -t msg.txt", "git status --short", "git ls-remote origin", "git stash list",
]

# 5단계 sec4: 같은 계열 전체를 막는 원리의 사례(probe_cases_sec4.json 26건 중 확장 검사가 맡는 23건 + 변형). 확장 파일 단독으로도 같은 판정이어야 한다.
SEC4_CASES = [
    # update-ref 삭제 옵션: 짧은 옵션 묶음 속 d (-m 의 값은 제외)
    ("update-ref -zd", "git update-ref -zd refs/heads/x", True),
    ("update-ref -dm msg", "git update-ref -dm msg refs/heads/x", True),
    ("update-ref -m d (메시지 값)", "git update-ref -m d refs/heads/new HEAD", False),
    # pathspec 해석을 바꾸는 환경 변수
    ("GIT_ICASE_PATHSPECS", "GIT_ICASE_PATHSPECS=1 git restore A.TXT", True),
    ("GIT_LITERAL_PATHSPECS", "GIT_LITERAL_PATHSPECS=1 git restore a.txt", True),
    # 셸이 펼칠 ~ 경로
    ("restore ~ 경로", "git restore ~/.claude/CLAUDE.md", True),
    ("checkout -- ~ 경로", "git checkout -- ~/.claude/CLAUDE.md", True),
    ("restore --staged ~ 경로(색인만)", "git restore --staged ~/x", False),
    # 인용 속 cd 와 래퍼 뒤 변수 명령
    ("eval 'cd sub'; restore", "eval 'cd sub'; git restore a.txt", True),
    ("env -C 다른 폴더", "env -C /tmp/b git update-ref refs/heads/main HEAD~3", True),
    ("sudo -u root $G", "G=git; sudo -u root $G tag -d v1", True),
    ("인용 속 cd 글자만 있는 커밋 메시지", "git commit -m 'fix cd handling'", False),
    # 명령 치환 안의 인용된 ) 와 쪼갠 이름
    ("치환 속 인용된 )", "echo \"$(echo ')'; git tag -d v1)\"", True),
    ("치환 속 쪼갠 이름", "echo \"$(g'i't tag -d v1)\"", True),
    ("따옴표로 쪼갠 이름", 'g"i"t tag -d v1', True),
    ("백슬래시로 쪼갠 이름", "g\\it update-ref -d refs/heads/x", True),
    ("빈 따옴표로 쪼갠 이름", 'g""it tag -d v1', True),
    ("따옴표 쪼갠 이름 정상 명령", 'g"i"t status', False),
    ("따옴표 없는 백틱 치환", "echo `git tag -d v1`", True),
    ("백틱 치환 속 쪼갠 이름", "echo `g'i't tag -d v1`", True),
    ("백틱 치환 정상 명령", "echo `git status`", False),
    # tmux 의 모든 명령 문자열 운반 하위명령
    ("tmux run-shell", "tmux run-shell 'git tag -d v1'", True),
    ("tmux send", "tmux send -t s 'git tag -d v1' Enter", True),
    ("tmux if-shell", "tmux if-shell true 'git branch -D x'", True),
    ("tmux new-window", "tmux new-window 'git tag -d v1'", True),
    ("tmux 정상 명령", "tmux send-keys -t s 'git status' Enter", False),
    # clone -c / --config: -c 허용 목록과 같은 기준
    ("clone -c core.sshCommand", "git clone -c core.sshCommand=/tmp/x ssh://h/r /tmp/c", True),
    ("clone --config core.fsmonitor", "git clone --config core.fsmonitor=/tmp/x /tmp/repo /tmp/c", True),
    ("clone --config= 붙임", "git clone --config=core.pager=x a b", True),
    ("clone --conf 약어", "git clone --conf=core.pager=x a b", True),
    ("clone -c 붙임", "git clone -ccore.pager=x a b", True),
    ("clone 앞 옵션 뒤 -c", "git clone -b main -c core.fsmonitor=x a b", True),
    ("clone -c user.name 허용", "git clone -c user.name=y /tmp/repo /tmp/c", False),
    ("clone 정상", "git clone -b main --depth 1 /tmp/repo /tmp/c", False),
    # ext:: 전송, 프로그램을 돌리는 하위명령
    ("ext:: 전송", "GIT_ALLOW_PROTOCOL=ext git ls-remote 'ext::touch /tmp/x'", True),
    ("ext:: 환경 변수 없이", "git fetch 'ext::sh -c x' main", True),
    ("send-email --to-cmd", "git send-email --to-cmd=/tmp/x a.patch", True),
    ("instaweb --httpd", "git instaweb --httpd=/tmp/x", True),
    # 색인 항목을 지우거나 바꿈
    ("update-index --remove", "git update-index --remove a.txt", True),
    ("update-index --cacheinfo", "git update-index --add --cacheinfo 100644,0123456789012345678901234567890123456789,x", True),
    ("update-index --refresh 정상", "git update-index --refresh", False),
    ("update-index --add 정상", "git update-index --add b.txt", False),
    # --output 은 하위명령과 무관하게 파일 덮어쓰기
    ("stash show --output", "git stash show --output=a.txt", True),
    ("reflog show --output", "git reflog show --output=a.txt", True),
    ("log --output", "git log --output=x", True),
    # worktree add -B, notes --ref 값 건너뛰기
    ("worktree add -B", "git worktree add -B main ../wt HEAD~5", True),
    ("worktree add -b 정상", "git worktree add -b nb ../w2 HEAD", False),
    ("notes --ref x remove", "git notes --ref x remove HEAD", True),
    ("notes --ref=x remove", "git notes --ref=x remove HEAD", True),
    ("notes --ref x show 정상", "git notes --ref x show HEAD", False),
    ("notes add -m remove 정상", "git notes --ref=x add -m remove HEAD", False),
    # config 항목 삭제는 사용자·시스템·파일 범위에서 막고 저장소 범위는 연다
    ("config --global --unset-all", "git config --global --unset-all user.name", True),
    ("config --file --unset", "git config --file x --unset a.b", True),
    ("config unset --global", "git config unset --global a.b", True),
    ("config --unset 저장소 범위", "git config --unset core.pager", False),
    ("config --global 읽기", "git config --global user.name", False),
    # checkout/restore --ours/--theirs
    ("checkout --ours", "git checkout --ours a.txt", True),
    ("restore --theirs", "git restore --theirs a.txt", True),
]

# git 이름을 쪼갠 명령은 셸 규칙(push·reset --hard)도 받아야 한다. 확장 파일은 push 를 모르므로 셸 훅 전체에서만 본다.
SEC4_SHELL_CASES = [
    ('g"i"t push', True), ("g'i't push origin main", True), ("g\\it push", True), ("bash -c 'g\\it push'", True),
    ('g""it reset --hard', True), ('g"i"t log --oneline', False), ("echo gi t", False),
]


# r5fix (stage5_fix_r5.md, 14 items): each family has deny cases and pass pairs. The extension alone must give the same verdicts.
R5FIX_CASES = [
    # 1 zsh =git
    ("=git tag -d", "=git tag -d v1", True),
    ("=git push", "=git push origin main", True),
    ("=bash -c 안 git tag -d", "=bash -c 'git tag -d v1'", True),
    ("=git-push 실행 파일 꼴", "=git-push origin", True),
    ("=git status", "=git status", False),
    ("=git log", "=git log --oneline -3", False),
    # 3 chdir
    ("chdir 뒤 restore", "chdir sub && git restore f.txt", True),
    ("chdir 뒤 status 는 통과", "chdir sub && git status", False),
    # 4 environment names
    ("GIT_TEST_ 접두", "GIT_TEST_FOO=1 git status", True),
    ("GIT_TEST_GETTEXT_POISON", "GIT_TEST_GETTEXT_POISON=1 git log", True),
    ("PERL5OPT", "PERL5OPT=-Mx git status", True),
    ("PERL5DB", "PERL5DB=x git status", True),
    ("PERL5LIB", "PERL5LIB=/tmp git status", True),
    ("PERLLIB", "PERLLIB=/tmp git status", True),
    ("GITPERLLIB", "GITPERLLIB=/tmp git status", True),
    ("GCONV_PATH", "GCONV_PATH=/tmp git log", True),
    ("LOCPATH", "LOCPATH=/tmp git log", True),
    ("NLSPATH", "NLSPATH=/tmp git log", True),
    ("BROWSER", "BROWSER=x git help -w status", True),
    ("MANPAGER", "MANPAGER=x git help status", True),
    ("GIT_TESTING 은 접두 GIT_TEST_ 가 아님", "GIT_TESTING=1 git status", False),
    ("LANG", "LANG=C git status", False),
    # 5 apply: query forms only
    ("apply --index", "git apply --index p.diff", True),
    ("apply --check --apply", "git apply --check --apply p.diff", True),
    ("apply --stat --apply", "git apply --stat --apply p.diff", True),
    ("apply --numstat", "git apply --numstat p.diff", False),
    ("apply --summary", "git apply --summary p.diff", False),
    ("apply --check --index", "git apply --check --index p.diff", False),
    # 6 zsh glob operators in restore/checkout paths
    ("restore a(.)", "git restore a(.)", True),
    ("restore *(.)", "git restore *(.)", True),
    ("restore (a|b).txt", "git restore (a|b).txt", True),
    ("restore a<->", "git restore a<->", True),
    ("restore <->", "git restore <->", True),
    ("checkout -- *(om[1])", "git checkout -- *(om[1])", True),
    ("restore @(a|b).txt", "git restore @(a|b).txt", True),
    ("restore 뒤 리다이렉션", "git restore b.txt >/dev/null", False),
    ("restore 뒤 2>&1", "git restore b.txt 2>&1", False),
    ("서브셸 안 restore", "(git restore b.txt)", False),
    ("$() 안 restore", "echo $(git restore b.txt)", False),
    ("restore 뒤 다른 서브셸", "git restore b.txt && (echo hi)", False),
    # 7 fetch --prune
    ("fetch --prune 로컬 브랜치 refspec", "git fetch --prune origin refs/heads/*:refs/heads/*", True),
    ("fetch --prune 로컬 태그 refspec", "git fetch --prune origin refs/tags/*:refs/tags/*", True),
    ("fetch --prune-tags", "git fetch --prune-tags origin", True),
    ("fetch --prune-t 약어", "git fetch --prune-t origin", True),
    ("fetch -P", "git fetch -P origin", True),
    ("fetch -p 이름 refspec", "git fetch -p origin main:main", True),
    ("fetch --prune --tags", "git fetch --prune --tags origin", True),
    ("fetch --pru 약어 + 로컬 refspec", "git fetch --pru origin dev:dev", True),
    ("fetch --prune 일반", "git fetch --prune origin", False),
    ("fetch -p 인자 없음", "git fetch -p", False),
    ("fetch --prune 원격 추적 refspec", "git fetch --prune origin refs/heads/*:refs/remotes/origin/*", False),
    ("fetch --prune 원격 URL 에 콜론", "git fetch --prune git@host:repo.git", False),
    ("fetch --tags (prune 없음)", "git fetch --tags origin", False),
    ("fetch 로컬 refspec (prune 없음)", "git fetch origin dev:dev", False),
    # 8 merge-file
    ("merge-file 제자리 덮어씀", "git merge-file a b c", True),
    ("merge-file --ours", "git merge-file --ours a b c", True),
    ("merge-file -p", "git merge-file -p a b c", False),
    ("merge-file --stdout", "git merge-file --stdout a b c", False),
    ("merge-file -L 라벨 + -p", "git merge-file -p -L x -L y -L z a b c", False),
    # 9 glob in the action word
    ("remote re*", "git remote re* origin", True),
    ("bisect ru*", "git bisect ru* ./x.sh", True),
    ("submodule fore*", "git submodule fore* ls", True),
    ("worktree pru*", "git worktree pru*", True),
    ("notes --ref x re*", "git notes --ref x re* HEAD", True),
    ("bundle creat*", "git bundle creat* b HEAD", True),
    ("maintenance sta?t", "git maintenance sta?t", True),
    ("remote show", "git remote show origin", False),
    ("remote -v", "git remote -v", False),
    ("bisect good", "git bisect good", False),
    ("worktree list", "git worktree list", False),
    ("notes --ref=x show", "git notes --ref=x show HEAD", False),
    # 10 shell-hook rules inside the extension (git-<sub> paths)
    ("git-push 경로", "/usr/lib/git-core/git-push origin", True),
    ("git-pull 경로", "/usr/lib/git-core/git-pull", True),
    ("git-stash drop 경로", "/usr/lib/git-core/git-stash drop", True),
    ("git-commit --no-verify 경로", "/usr/lib/git-core/git-commit --no-verify -m x", True),
    ("git-commit -n 경로", "/usr/lib/git-core/git-commit -n -m x", True),
    ("git-commit -an 묶음", "/usr/lib/git-core/git-commit -an -m x", True),
    ("commit --no-verif 약어", "git commit --no-verif -m x", True),
    ("git-reset --hard 경로", "/usr/lib/git-core/git-reset --hard", True),
    ("git-clean -f 경로", "/usr/lib/git-core/git-clean -f", True),
    ("git-checkout . 경로", "/usr/lib/git-core/git-checkout .", True),
    ("git-branch -D 경로", "/usr/lib/git-core/git-branch -D x", True),
    ("checkout -f", "git checkout -f main", True),
    ("switch -f", "git switch -f main", True),
    ("switch --discard-changes", "git switch --discard-changes main", True),
    ("restore --staged .", "git restore --staged .", True),
    ("restore ./", "git restore ./", True),
    ("restore :/", "git restore :/", True),
    ("send-pack", "git send-pack origin", True),
    ("http-push", "git http-push http://h/r.git main", True),
    ("subtree push", "git subtree push --prefix=x origin main", True),
    ("push", "git push", True),
    ("pull", "git pull origin main", True),
    ("stash", "git stash", True),
    ("stash pop", "git stash pop", True),
    ("stash create", "git stash create", True),
    ("git-status 경로", "/usr/lib/git-core/git-status", False),
    ("git-stash list 경로", "/usr/lib/git-core/git-stash list", False),
    ("stash show", "git stash show -p", False),
    ("commit -m", "git commit -m x", False),
    ("commit 메시지 속 -n", "git commit -m 'fix -n handling'", False),
    ("commit --amend --no-edit", "git commit --amend --no-edit", False),
    ("checkout -b", "git checkout -b topic", False),
    ("switch main", "git switch main", False),
    ("checkout main", "git checkout main", False),
    # 11 file-writing options
    ("fast-export --export-marks", "git fast-export --export-marks=/tmp/m --all", True),
    ("fast-import --export-marks 값 분리", "git fast-import --export-marks /tmp/m", True),
    ("fast-import --export-pack-edges", "git fast-import --export-pack-edges=/tmp/e", True),
    ("index-pack -o", "git index-pack -o /tmp/x.idx p.pack", True),
    ("format-patch -o", "git format-patch -o /tmp/out -1", True),
    ("format-patch -o 붙임", "git format-patch -o/tmp/out -1", True),
    ("format-patch --output-directory", "git format-patch --output-directory=/tmp/out -1", True),
    ("format-patch --output-d 약어", "git format-patch --output-d=/tmp/out -1", True),
    ("bundle create", "git bundle create /tmp/b.bundle HEAD", True),
    ("bundle verify", "git bundle verify /tmp/b.bundle", False),
    ("bundle list-heads", "git bundle list-heads /tmp/b.bundle", False),
    ("format-patch --stdout", "git format-patch --stdout -1", False),
    ("fast-export 일반", "git fast-export --all", False),
    ("index-pack --stdin", "git index-pack --stdin", False),
    # 12 update-ref only at a command position
    ("timeout 뒤 update-ref", "timeout 5 git update-ref refs/heads/zz-new HEAD", True),
    ("xargs git update-ref", "xargs git update-ref refs/heads/zz-new HEAD", True),
    ("update-ref 명령 자리", "git update-ref refs/heads/zz-new HEAD", False),
    ("env 대입 뒤 update-ref", "env FOO=1 git update-ref refs/heads/zz-new HEAD", False),
    ("update-ref 한 인자는 폴더 불필요", "xargs git update-ref refs/heads/zz-new", False),
    # 13 GIT_TRACE values
    ("GIT_TRACE=파일", "GIT_TRACE=/tmp/f git status", True),
    ("GIT_TRACE2_EVENT=파일", "GIT_TRACE2_EVENT=/tmp/f git status", True),
    ("GIT_TRACE=3 (fd)", "GIT_TRACE=3 git status", True),
    ("GIT_TRACE_PERFORMANCE=파일", "GIT_TRACE_PERFORMANCE=/tmp/p git status", True),
    ("export GIT_TRACE2=파일", "export GIT_TRACE2=/tmp/t; git status", True),
    ("GIT_TRACE=1", "GIT_TRACE=1 git status", False),
    ("GIT_TRACE=true", "GIT_TRACE=true git status", False),
    ("GIT_TRACE=false", "GIT_TRACE=false git log", False),
    ("GIT_TRACE2=0", "GIT_TRACE2=0 git status", False),
    ("GIT_TRACE_PACKET=2", "GIT_TRACE_PACKET=2 git status", False),
    ("GIT_TRACE_CURL= (빈 값)", "GIT_TRACE_CURL= git status", False),
]


# stage5_fix_r6.md (2026-11-09): quoted punctuation, source/./rbash, variable-receiving names, option values, commit expansion ...
R6FIX_CASES = [
    # 1 quoted or escaped punctuation is an argument, not an operator
    ("인용 ; 뒤 branch -D", "git branch ';' -D x", True),
    ("인용 | 뒤 tag -d", "git tag '|' -d v1", True),
    ("인용 & 뒤 reset --hard", "git reset '&' --hard", True),
    ("백슬래시 ; 뒤 reset --hard", "git reset \\; --hard", True),
    ("인용 ( 뒤 branch -D", 'git branch "(" -D x', True),
    ("인용 ; grep 인자", "git log --grep ';' --oneline", False),
    ("인용 | grep 인자", "git log --grep '|' -n 3", False),
    ("인용 << grep 인자 (옛 한계 해소)", "git log --grep '<<' --oneline", False),
    ("commit 메시지 ;", "git commit -m ';' --amend", False),
    ("백슬래시 ; 가 낱말 안", "git log --grep=a\\;b -1", False),
    ("인용 안 구두점이 낱말 속", "git log --format='%h;%s' -3", False),
    # 2 source / . / rbash run the text fed to them
    (". 에 here-string", ". /dev/stdin <<< 'git rebase main'", True),
    ("source 에 here-string", 'source /dev/stdin <<< "git rebase main"', True),
    ("rbash -c", "rbash -c 'git rebase main'", True),
    ("rbash here-string", "rbash <<< 'git rebase main'", True),
    ("source 파일", "source ./env.sh && git status", False),
    (". 파일", ". ./env.sh; git status", False),
    ("git add . 는 here-string 없음", "git add . && git status", False),
    # 4 names that receive a value
    ("read GIT_DIR", "read GIT_DIR; git status", True),
    ("read 여러 이름 중 PATH", "read -r x PATH; git status", True),
    ("for PATH in", "for PATH in a b; do git status; done", True),
    ("printf -v HOME", "printf -v HOME x; git log -1", True),
    ("printf -vHOME 붙임", "printf -vHOME x; git log -1", True),
    ("declare -x PERL5OPT", "declare -x PERL5OPT; git status", True),
    ("export LESSOPEN", "export LESSOPEN; git status", True),
    ("mapfile PATH", "mapfile PATH < f; git status", True),
    ("read GIT_TRACE (값 미상)", "read GIT_TRACE; git status", True),
    ("while read PATH", "while read PATH; do git status; done < f", True),
    ("read 일반 이름", "read x; git status", False),
    ("for 일반 이름", "for f in a b; do git log -1 -- \"$f\"; done", False),
    ("printf -v 일반 이름", "printf -v x %s a; git status", False),
    ("export 일반 대입", "export FOO=1; git status", False),
    ("read -p 프롬프트", "read -p 'go? ' ans; git status", False),
    # 6 more environment names
    ("LESSOPEN=", "LESSOPEN=x git log", True),
    ("LESSCLOSE=", "LESSCLOSE=x git log", True),
    ("PS4=", "PS4=x git status", True),
    ("SHELLOPTS=", "SHELLOPTS=xtrace git status", True),
    # 5 value-taking short options end the bundle
    ("merge-file -Lp (p 는 라벨 값)", "git merge-file -Lp a b c", True),
    ("merge-file -pL", "git merge-file -pL x a b c", False),
    ("merge-file -p", "git merge-file -p a b c", False),
    ("clean -f -e -n (-n 은 -e 의 값)", "git clean -f -e -n", True),
    ("clean -fe n", "git clean -fe n", True),
    ("clean -e n -f", "git clean -e n -f", True),
    ("clean -dxen (n 은 -e 의 값, -f 없음)", "git clean -dxen", True),
    ("clean -n", "git clean -n", False),
    ("clean -ne x", "git clean -ne x", False),
    ("tag -mdf (df 는 메시지)", "git tag -mdf v1", False),
    ("tag -d", "git tag -d v1", True),
    ("grep -eOK (OK 는 패턴)", "git grep -eOK foo", False),
    ("grep -O", "git grep -O less foo", True),
    # 7 expansion in commit and the subcommands of r5fix 11
    ("commit 인자의 변수", "git commit -m x $F", True),
    ("commit --fixup 변수", "git commit --fixup=$X", True),
    ("commit -m 값의 변수", 'git commit -m "$MSG"', False),
    ("commit --message= 값의 변수", 'git commit --message="a$b"', False),
    ("commit -F 값의 변수", 'git commit -F "$f"', False),
    ("commit -am 값의 변수", 'git commit -am "$msg"', False),
    ("commit -- 뒤 경로 변수", 'git commit -q -F "$F" -- "$P"', False),
    ("commit 경로 변수 (-- 없음)", 'git commit -m x "$P"', True),
    ("commit -c 커밋 값의 변수", "git commit -c $SHA", False),
    ("commit -C 커밋 값의 변수", "git commit -C $SHA", False),
    ("commit --reuse-message 값의 변수", "git commit --reuse-message=$SHA", False),
    ("commit 경로 glob", "git commit -m x -- a.txt sub/*.txt", False),
    ("format-patch 변수", "git format-patch $O HEAD~1", True),
    ("merge-file 변수", "git merge-file -p $A b c", True),
    ("fast-export 변수", "git fast-export $X", True),
    ("bundle verify 변수", "git bundle verify $X", True),
    ("index-pack 변수", "git index-pack $P", True),
    # 8 --skip and config --rename-section
    ("cherry-pick --skip", "git cherry-pick --skip", True),
    ("revert --skip", "git revert --skip", True),
    ("am --skip", "git am --skip", True),
    ("cherry-pick --abort", "git cherry-pick --abort", False),
    ("revert --abort", "git revert --abort", False),
    ("am --abort", "git am --abort", False),
    ("config --global --rename-section", "git config --global --rename-section a b", True),
    ("config --system --rename-section", "git config --system --rename-section a b", True),
    ("config -f --rename-section", "git config -f x.cfg --rename-section a b", True),
    ("config --global rename-section 낱말", "git config --global rename-section a b", True),
    ("config --rename-section 로컬", "git config --rename-section a b", False),
    ("config --global --get", "git config --global --get user.name", False),
    # 9 apply: only the arguments before `--` can be the query flag
    ("apply -- 뒤 --check", "git apply -- p.diff --check", True),
    ("apply --check", "git apply --check p.diff", False),
    ("apply --stat -- 파일", "git apply --stat -- p.diff", False),
    # 10 fetch --prune: the value of --depth is not the remote
    ("fetch --prune --depth 1 URL", "git fetch --prune --depth 1 https://h/r.git", False),
    ("fetch --depth 1 --prune URL", "git fetch --depth 1 --prune https://h/r.git", False),
    ("fetch -j 4 --prune origin", "git fetch -j 4 --prune origin", False),
    ("fetch --prune --depth 1 로컬 refspec", "git fetch --prune --depth 1 origin refs/heads/main:refs/heads/main", True),
    ("fetch --prune --depth=1 로컬 refspec", "git fetch --prune --depth=1 origin refs/heads/main:refs/heads/main", True),
    ("chdir 뒤 restore", "chdir /tmp; git restore a.txt", True),
]


class ChainTest(unittest.TestCase):
    """Cases judged through the full git-guardrails.sh chain."""

    def test_r6fix_cases(self):
        """r6fix: every family has the expected verdict through the whole chain."""
        for name, cmd, want in R6FIX_CASES:
            with self.subTest(name=name, cmd=cmd):
                self.assertEqual(chain(cmd), want)

    def test_r5fix_cases(self):
        """r5fix: every family has the expected verdict through the whole chain."""
        for name, cmd, want in R5FIX_CASES:
            with self.subTest(name=name, cmd=cmd):
                self.assertEqual(chain(cmd), want)

    def test_cases(self):
        """Every case matches its expected verdict."""
        for name, cmd, want in CASES + R_CASES + R11_CASES + R4_CASES:
            with self.subTest(name=name, cmd=cmd):
                self.assertEqual(chain(cmd.replace("@REPO@", REPO)), want)

    def test_wide_list_89(self):
        """Spec r5 C: every one of the 89 listed commands has its expected verdict through the whole chain."""
        self.assertEqual(len(C_CASES), 89)
        for cmd, want in C_CASES:
            with self.subTest(cmd=cmd):
                self.assertEqual(chain(cmd), want)

    def test_wide_normal_use_passes(self):
        """Everyday forms next to the denied ones stay open."""
        for cmd in C_NORMAL:
            with self.subTest(cmd=cmd):
                self.assertFalse(chain(cmd))

    def test_sec4_cases(self):
        """sec4: each family has a deny case and a pass pair through the whole chain."""
        for name, cmd, want in SEC4_CASES:
            with self.subTest(name=name, cmd=cmd):
                self.assertEqual(chain(cmd), want)

    def test_sec4_split_git_name_gets_shell_rules(self):
        """A quote/backslash-split git name is recognized by the early exit, so push and reset --hard rules apply."""
        for cmd, want in SEC4_SHELL_CASES:
            with self.subTest(cmd=cmd):
                self.assertEqual(chain(cmd), want)

    def test_c_flag_pair_runs_from_outside_repo(self):
        """`git -C <repo>` is honoured even when the hook cwd is elsewhere."""
        self.assertTrue(chain(f"git -C {REPO} restore a.txt", cwd=TMP))
        self.assertFalse(chain(f"git -C {REPO} restore b.txt", cwd=TMP))

    def test_approved_marker_still_bypasses(self):
        """The first-line # APPROVED marker is handled before the extension."""
        self.assertFalse(chain("# APPROVED test approval\ngit rebase main"))


class ExtAloneTest(unittest.TestCase):
    """Cases judged by git_guard_ext.py without the shell wrapper."""

    def test_r_cases_without_shell_hook(self):
        """R1-R10 cases give the same verdict from the extension alone (not merely via the shell hook)."""
        for name, cmd, want in R_CASES + R11_CASES + R4_CASES:
            with self.subTest(name=name, cmd=cmd):
                self.assertEqual(ext(cmd), want)

    def test_wide_list_89_without_shell_hook(self):
        """The extension alone gives the same verdicts (r5fix 10: the stash rule is in the extension too)."""
        for cmd, want in C_CASES:
            with self.subTest(cmd=cmd):
                self.assertEqual(ext(cmd), want)

    def test_wide_normal_use_passes_without_shell_hook(self):
        """Everyday forms pass in the extension alone."""
        for cmd in C_NORMAL:
            with self.subTest(cmd=cmd):
                self.assertFalse(ext(cmd))

    def test_sec4_cases_without_shell_hook(self):
        """sec4: the extension alone gives the same verdicts as the whole chain."""
        for name, cmd, want in SEC4_CASES:
            with self.subTest(name=name, cmd=cmd):
                self.assertEqual(ext(cmd), want)

    def test_r5fix_cases_without_shell_hook(self):
        """r5fix: the extension alone gives the same verdicts (the shell-hook rules are repeated in it)."""
        for name, cmd, want in R5FIX_CASES:
            with self.subTest(name=name, cmd=cmd):
                self.assertEqual(ext(cmd), want)

    def test_r6fix_cases_without_shell_hook(self):
        """r6fix: the extension alone gives the same verdicts."""
        for name, cmd, want in R6FIX_CASES:
            with self.subTest(name=name, cmd=cmd):
                self.assertEqual(ext(cmd), want)

    def test_quoted_punctuation_tokens(self):
        """r6fix 1: quoted or escaped punctuation becomes a QuotedTok argument; unquoted operators stay operators."""
        toks = ext_mod().tokenize("git log --grep ';' \\| \"(\" ; echo x")
        self.assertEqual(list(toks), ["git", "log", "--grep", ";", "|", "(", ";", "echo", "x"])
        self.assertEqual([type(t).__name__ for t in toks[3:6]], ["QuotedTok"] * 3)
        self.assertEqual(type(toks[6]).__name__, "str")
        with self.assertRaises(ValueError):
            # the next line holds the stand-in character U+E000 itself: input that already has it is refused
            ext_mod().tokenize("echo")

    def test_glob_operator_scope(self):
        """r5fix 6: only the extension tells a quoted or index-only `a(.)` from a zsh glob (the shell hook's `.` rule denies both)."""
        self.assertFalse(ext("git restore 'a(.)'"))
        self.assertFalse(ext("git restore --staged a(.)"))
        self.assertTrue(ext("git restore a(.)"))

    def test_heredoc_deny_message(self):
        """Spec r5 H: the deny reason is the fixed heredoc message, also when the tokenizer fails on an apostrophe."""
        for cmd in ("git commit -F - <<'EOF'\nfix: x\nEOF", "git commit -F - <<'EOF'\nfix: Don't\nEOF"):
            payload = json.dumps({"tool_input": {"command": cmd}, "cwd": REPO})
            r = subprocess.run(["python3", "-I", str(EXT)], input=payload, check=False, capture_output=True, text=True)
            self.assertIn("heredoc(<<)", json.loads(r.stdout)["hookSpecificOutput"]["permissionDecisionReason"])

    def test_at_brace_revision_is_not_a_path_brace(self):
        """Minor fix 2: `@{-1}` passes the restore/checkout path check (a real previous branch exists); a plain brace path is denied."""
        for fn in (ext, chain):
            with self.subTest(fn=fn.__name__):
                self.assertFalse(fn("git checkout @{-1}", cwd=BREPO))
                self.assertTrue(fn("git checkout a{b,c}.txt", cwd=BREPO))

    def test_blocks(self):
        """Direct verdicts for a few blocking forms."""
        for cmd in ("git rebase main", "git restore a.txt", "git -c core.pager=x log", "git prune"):
            with self.subTest(cmd=cmd):
                self.assertTrue(ext(cmd))

    def test_passes(self):
        """Direct verdicts for a few passing forms and non-git commands."""
        for cmd in ("git status", "git restore b.txt", "ls -la", "echo rebase"):
            with self.subTest(cmd=cmd):
                self.assertFalse(ext(cmd))

    def test_unclosed_quote_with_git_is_denied(self):
        """A quote parse failure is denied when git appears, ignored otherwise."""
        self.assertTrue(ext('git commit -m "abc'))
        self.assertFalse(ext('echo "abc'))

    def test_empty_and_bad_json_do_not_block(self):
        """Unreadable input produces no deny and exit code 0."""
        for stdin in ("", "not json", "[]", '{"tool_input":{}}'):
            with self.subTest(stdin=stdin):
                r = subprocess.run(["python3", "-I", str(EXT)], input=stdin, check=False, capture_output=True, text=True)
                self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_filter_repo_denied_without_diff(self):
        """R10: a path with a repo-level filter attribute is denied before diff runs; other paths and index-only pass."""
        payload = json.dumps({"tool_input": {"command": "git restore a.txt"}, "cwd": FREPO})
        r = subprocess.run(["python3", "-I", str(EXT)], input=payload, check=False, capture_output=True, text=True)
        self.assertIn("필터가 설정된 저장소", json.loads(r.stdout)["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertTrue(ext("git restore a.txt b.txt", cwd=FREPO))
        self.assertFalse(ext("git restore b.txt", cwd=FREPO))
        self.assertFalse(ext("git restore --staged a.txt", cwd=FREPO))
        self.assertFalse(ext("git status", cwd=FREPO))

    def test_hidden_change_reason(self):
        """R5: the deny reason names the assume-unchanged file even though git diff is empty."""
        payload = json.dumps({"tool_input": {"command": "git restore c.txt"}, "cwd": REPO})
        r = subprocess.run(["python3", "-I", str(EXT)], input=payload, check=False, capture_output=True, text=True)
        self.assertIn("c.txt", json.loads(r.stdout)["hookSpecificOutput"]["permissionDecisionReason"])

    def test_deny_json_shape(self):
        """The deny line has the same shape as git-guardrails.sh deny()."""
        payload = json.dumps({"tool_input": {"command": "git rebase main"}, "cwd": REPO})
        r = subprocess.run(["python3", "-I", str(EXT)], input=payload, check=False, capture_output=True, text=True)
        out = json.loads(r.stdout)["hookSpecificOutput"]
        self.assertEqual((out["hookEventName"], out["permissionDecision"]), ("PreToolUse", "deny"))
        self.assertTrue(out["permissionDecisionReason"].startswith("[git 차단] "))
        self.assertIn("# APPROVED", out["permissionDecisionReason"])


if __name__ == "__main__":
    unittest.main()
