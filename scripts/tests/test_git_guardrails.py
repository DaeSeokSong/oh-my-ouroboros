"""git-guardrails.sh 회귀 테스트 (자체 완결 — 실제 git 명령을 돌리지 않고 훅 판정만 본다).

실행: python3 ~/.claude/scripts/tests/test_git_guardrails.py → 실패 0 이면 exit 0
케이스: push·pull·reset --hard·commit --no-verify·config core.hooksPath 차단 /
        stash push·drop·clear·pop·apply 차단, 조회(list·show)는 통과(2026-09-14) /
        복합 명령 세그먼트 평가(2026-09-14 재감사 B3·B4): `stash list && stash drop`·`config --get ; config set` 차단,
        조회만 이어 붙인 복합은 통과 — 허용 예외가 그 조각 밖까지 덮던 구멍 /
        셸 `-c` 페이로드 안의 push·reset 차단(2026-09-08 security 재현) /
        `git -c protocol.version=2 push` 차단(옵션과 값이 별개 토큰) /
        통과 쌍: git status·log, 인용 메시지 안의 「git push」·「-n」 글자, 하네스 훅 경로 지정, `bash -c 'git status'`.
차단마다 통과 쌍을 함께 둔다. 오탐이 나면 이 훅은 일상 커밋을 막아 작업이 멈춘다.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

HOOK = Path(os.environ.get("GIT_GUARDRAILS_HOOK") or Path.home() / ".claude/scripts/git-guardrails.sh")   # 수정 전 사본 대조용
HOOKS_DIR = str(Path.home() / ".claude/.git/hooks")


def blocked(cmd: str) -> bool:
    """훅을 실행해 deny 판정이 나왔는지 반환."""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}})
    r = subprocess.run(["bash", str(HOOK)], input=payload, check=False, capture_output=True, text=True)
    return '"deny"' in r.stdout


def reason(cmd: str) -> str:
    """훅을 실행해 deny 사유 문구를 반환(통과면 빈 문자열)."""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}})
    r = subprocess.run(["bash", str(HOOK)], input=payload, check=False, capture_output=True, text=True)
    return json.loads(r.stdout)["hookSpecificOutput"]["permissionDecisionReason"] if '"deny"' in r.stdout else ""


AQ = "# APPROVED 사용자 «그렇게 진행해 주세요»\n"   # 승인 마커 줄(인용의 로그 실재는 bash-write-check 소관)
STRICT = "승인 표시(# APPROVED)로도 통과하지 않습니다"   # 2026-11-12 결정 F1·G1: 마커로 안 풀리는 차단의 문구

# (이름, 명령, 차단 기대)
CASES = [
    # ── 차단 ──
    ("git push origin main → 차단", "git push origin main", True),
    ("bash -c 'git push' → 차단", "bash --noprofile --norc -c 'git push'", True),
    ("sh -c 'git reset --hard' → 차단", "sh -c 'git reset --hard HEAD~1'", True),
    ("git -c protocol.version=2 push → 차단", "git -c protocol.version=2 push origin main", True),
    ("git commit --no-verify → 차단", "git commit --no-verify -m x", True),
    ("git config core.hooksPath → 차단", "git config core.hooksPath /dev/null", True),
    # stash (2026-09-14) — 훅 밖이던 유일한 git 파괴 동작
    ("git stash (인자 없음=push) → 차단", "git stash", True),
    ("git stash push -m → 차단", "git stash push -m wip", True),
    ("git stash drop → 차단", "git stash drop stash@{0}", True),
    ("git stash clear → 차단", "git stash clear", True),
    ("git stash pop → 차단", "git stash pop", True),
    ("git stash apply → 차단", "git stash apply", True),
    ("bash -c 'git stash' → 차단", "bash -c 'git stash drop'", True),
    # 복합 명령 세그먼트 평가 (2026-09-14 재감사 B3·B4) — 앞 조각의 허용 예외가 뒤 조각을 덮던 구멍
    ("stash list && stash drop → 차단", "git stash list && git stash drop stash@{0}", True),
    ("stash show ; stash clear → 차단", "git stash show -p stash@{0}; git stash clear", True),
    ("config --get ; config set → 차단", "git config --get core.hooksPath ; git config core.hooksPath /tmp/evil", True),
    # 2026-10-01 감사 — 공백 없는 인용은 셸이 벗기고 실행한다(지워서 통과시키던 구멍)
    ("git 'push' → 차단", "git 'push' origin main", True),
    ('git "stash" → 차단', 'git "stash"', True),
    ('git checkout "." → 차단', 'git checkout "."', True),
    ('git commit "--no-verify" → 차단', 'git commit "--no-verify" -m x', True),
    ('git pu"s"h → 차단', 'git pu"s"h origin main', True),
    ("bash -c 'git \"push\"' → 차단", "bash -c 'git \"push\"'", True),
    # 2026-10-01 감사 — 작업트리 폐기의 다른 표기
    ("git checkout ./ → 차단", "git checkout ./", True),
    ("git restore :/ → 차단", "git restore :/", True),
    ("git checkout -f main → 차단", "git checkout -f main", True),
    ("git switch -f → 차단", "git switch -f main", True),
    ("git switch --discard-changes → 차단", "git switch --discard-changes main", True),
    ("git checkout --force → 차단", "git checkout --force main", True),
    ("git -c alias.x=checkout x . → 차단", "git -c alias.x=checkout x .", True),
    # ── 통과 (차단 쌍) ──
    ("git status → 통과", "git status", False),
    ("커밋 메시지 안의 「git push」 → 통과", "git commit -m 'docs: git push 규칙 보강'", False),
    ("커밋 메시지 안의 「-n」 → 통과", "git commit -m 'fix: -n flag note'", False),
    ("하네스 훅 경로 지정 → 통과", f"git -c core.hooksPath={HOOKS_DIR} commit -m x", False),
    ("git log --oneline -3 → 통과", "git log --oneline -3", False),
    ("bash -c 'git status' → 통과", "bash -c 'git status'", False),
    ("git stash list → 통과 (조회)", "git stash list", False),
    ("git stash show -p → 통과 (조회)", "git stash show -p stash@{0}", False),
    ("커밋 메시지 안의 「git stash」 → 통과", "git commit -m 'docs: git stash 규칙 보강'", False),
    ("# APPROVED + git stash → 통과", "# APPROVED\ngit stash", False),
    ("stash list 단독 → 통과 (세그먼트 평가 뒤에도)", "git stash list", False),
    ("조회 두 조각 → 통과", "git stash list && git stash show -p stash@{0}", False),
    # 2026-10-01 감사 — 여러 줄 커밋 메시지 본문의 «git push» 글자는 오차단하지 않는다(줄 단위 따옴표 제거가 쌍을 못 접던 결함)
    ("여러 줄 커밋 메시지 속 git push → 통과", 'git commit -m "docs: line1\nnote: git push 규칙\nline3"', False),
    ("heredoc 커밋 메시지 속 git push → 차단(r5 H)", "git commit -m \"$(cat <<'EOF'\nfix: x\n\ngit push 는 사용자 직접\nEOF\n)\"", True),
    ("여러 줄 명령의 앞 줄 stash list 가 뒷 줄 drop 을 덮지 않음 → 차단", "git stash list\ngit stash drop", True),
    ("경로 지정 복구 checkout HEAD -- ./src → 통과", "git checkout HEAD -- ./src/a.py", False),
    ("git checkout -b 새 브랜치 → 통과", "git checkout -b feature-x", False),
    ("git switch -c → 통과", "git switch -c feature-x", False),
    ("인용 속 -f 글자 → 통과", "git commit -m 'checkout -f 규칙 보강'", False),
    ("공백 없는 인용 메시지 → 통과", 'git commit -m "WIP"', False),
    # 2026-10-01 P6 검수 — 큰따옴표 속 아포스트로피 둘이 작은따옴표 쌍으로 읽혀 사이의 push 를 지우던 구멍(따옴표는 왼쪽부터 짝짓는다)
    ("큰따옴표 속 아포스트로피 둘 사이의 push → 차단", "git commit -m \"it's a\" && git push && echo \"don't\"", True),
    ("작은따옴표 속 큰따옴표 둘 사이의 push → 차단", "git commit -m 'a \"b' && git push && echo 'c\" d'", True),
    ("아포스트로피 든 커밋 메시지 단독 → 통과", "git commit -m \"it's a fix, don't worry\"", False),
    # 2026-10-01 P6 보안 재검수 H — 따옴표 벗기기와 짝짓기를 한 번의 왼쪽→오른쪽 주사로(P1-2·P2-3)
    ("P1-2 echo \"it's\" && git push && echo \"don't\" → 차단", "echo \"it's\" && git push && echo \"don't\"", True),
    ("P1-2 echo '\"' ; git push ; echo '\"' → 차단", "echo '\"' ; git push ; echo '\"'", True),
    ("P1-2 git commit -m \"it's a\" && git push && echo \"don't\" → 차단", "git commit -m \"it's a\" && git push && echo \"don't\"", True),
    ("P2-3 이스케이프 따옴표 사이의 push → 차단", "echo \\\" ; git push ; echo \\\"", True),
    ("P2-3 이스케이프 작은따옴표 사이의 push → 차단", "echo \\' ; git push ; echo \\'", True),
    ("P2-3 주석 속 아포스트로피 뒤 줄의 push → 차단", "git status # don't\ngit push # it's", True),
    ("큰따옴표 안 \\\" 이스케이프 뒤 push → 차단", "echo \"a \\\" b\" && git push && echo \"c\"", True),
    ("가용성 git commit -F msg -- 경로 → 통과", "git commit -F msg -- scripts/a.sh", False),
    ("가용성 여러 줄 -m 줄머리 install·kill·push 와 아포스트로피 → 통과", "git commit -m \"fix: it's x\n\ninstall 안내\nkill 안내\npush 안내 don't\"", False),
    ("가용성 heredoc 커밋 메시지 -F - → 차단(r5 H)", "git commit -F - <<'EOF'\nfix: Don't push\nEOF", True),
    ("가용성 git log --format → 통과", "git log --format='%h %s'", False),
    ("가용성 echo \"don't\" 단독 → 통과", "echo \"don't\"", False),
    ("가용성 주석 달린 읽기 → 통과", "ls # it's fine", False),
    # 2026-10-02 I: 주석 구간은 지우지 않고 남긴다(주석 오판이 뒤 명령을 숨기지 못하게 하는 닫힘 방향 설계). 그래서 주석 속 «git push» 글자는
    #   차단된다 — 직전 묶음의 «통과» 기대를 «차단»으로 바꾼다(오탐 허용, 미탐 불허).
    ("주석 속 git push 글자 → 차단(닫힘 방향 오탐 허용)", "git status # git push 는 사용자 직접", True),
    ("I 이스케이프 공백 뒤 # 는 주석 아님 → 차단", "echo a\\ #b; git push", True),
    ("I ${x:- #} 안의 # 뒤 push → 차단", "echo ${x:- #}; git push", True),
    ("I 빈 주석 다음 줄 push → 차단", "echo a #\ngit push", True),
    ("I $'…' 안의 \\' 는 따옴표를 닫지 않음 → 차단", "echo $'it\\'s' ; git push ; echo $'x\\''", True),
    ("I (git push) → 차단", "(git push)", True),
    ("I $(git push) → 차단", "echo $(git push)", True),
    ("I $(git stash drop) → 차단", "echo $(git stash drop)", True),
    ("I $(git checkout .) → 차단", "echo $(git checkout .)", True),
    ("I $(git stash list) → 통과", "echo $(git stash list)", False),
    ("I 주석 속 아포스트로피 → 통과", "ls # it's fine", False),
    ("I 인용 속 # → 통과", "git log --format='%h %s # x'", False),
    ("I URL 속 # → 통과", "curl -s https://a/b#c", False),
    ("가용성 # 낱말 속 → 통과", "git log --format=%h#x", False),
    # 2026-10-17 core.hooksPath 변형 (외부 검토 반례)
    ("hooksPath 소문자 키 → 차단", "git -c core.hookspath=/dev/null commit -m x", True),
    ("hooksPath -c 붙여쓰기 → 차단", "git -cCore.hooksPath=/dev/null commit -m x", True),
    ("hooksPath --config-env → 차단", "git --config-env=core.hooksPath=X commit -m x", True),
    ("hooksPath GIT_CONFIG_* 환경변수 → 차단",
     "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=/dev/null git commit -m x", True),
    ("hooksPath 서브셸 괄호 → 차단", "(git -c core.hooksPath=/tmp/evil commit -m x)", True),
    ("hooksPath 경로 접두 git → 차단", "/usr/bin/git -c core.hooksPath=/tmp/evil commit -m x", True),
    ("-c 키에 변수 확장 → 차단", "h=core.hooksPath; git -c $h=/tmp/evil commit -m x", True),
    ("--config-env 키에 변수 확장 → 차단", "git --config-env=$k=ENVV commit -m x", True),
    ("commit -c $SHA (커밋 재사용) → 통과", "git commit -c $SHA", False),
    ("-c user.name 일반 지정 → 통과", "git -c user.name=x commit -m y", False),
    ("GIT_CONFIG_PARAMETERS 공백 든 따옴표 값 → 차단",
     "GIT_CONFIG_PARAMETERS=\"'core.hooksPath'='/dev/null' 'user.name'='x'\" git commit -m x", True),
    ("GIT_CONFIG_PARAMETERS 값 안 세미콜론 뒤 hooksPath → 차단",
     "GIT_CONFIG_PARAMETERS=\"'user.name'='x;y' 'core.hooksPath'='/dev/null'\" git commit -m x", True),
    ("GIT_CONFIG_PARAMETERS 따옴표 접합 hooks\"\"Path → 차단",
     "GIT_CONFIG_PARAMETERS=\"'user.name'='x y' 'core.hooks\"\"Path'='/dev/null'\" git commit -m x", True),
    ("GIT_CONFIG_KEY 백슬래시로 쪼갠 hooksPath → 차단",
     "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooks\\Path GIT_CONFIG_VALUE_0=/dev/null git commit -m x", True),
    ("git config 백슬래시로 쪼갠 hooksPath 영구 설정 → 차단", "git config core.hooks\\Path /dev/null", True),
    ("git config 따옴표 접합 hooksPath 영구 설정 → 차단", "git config 'core.hooks''Path' /dev/null", True),
    ("env git config 백슬래시 hooksPath → 차단", "env git config core.hooks\\Path /dev/null", True),
    ("nohup git config 백슬래시 hooksPath → 차단", "nohup git config core.hooks\\Path /dev/null", True),
    ("command git config 백슬래시 hooksPath → 차단", "command git config core.hooks\\Path /dev/null", True),
    ("경로 접두 git config 백슬래시 hooksPath → 차단", "/usr/bin/git config core.hooks\\Path /dev/null", True),
    ("VAR=1 git config 백슬래시 hooksPath → 차단", "A=1 B=2 git config core.hooks\\Path /dev/null", True),
    ("sudo -n timeout 5 git config 백슬래시 hooksPath → 차단", "sudo -n timeout 5 git config core.hooks\\Path /dev/null", True),
    ("env -u FOO git config 백슬래시 hooksPath → 차단", "env -u FOO git config core.hooks\\Path /dev/null", True),
    ("sudo -u x env -i git config 소문자 hookspath → 차단", "sudo -u x env -i git config core.hookspath y", True),
    ("bash -c 페이로드 안 env git config 백슬래시 hooksPath → 차단", "bash -c 'env git config core.hooks\\Path /dev/null'", True),
    ("bash -c 페이로드 안 git config --get (읽기) → 통과", "bash -c 'git config --get core.hooksPath'", False),
    ("커밋 메시지 속 env git config core.hooksPath (정규화본 전체 기준, 과차단 허용) → 차단",
     'git commit -m "env git config core.hooksPath"', True),
    ("env git config --get hooksPath (읽기) → 통과", "env git config --get core.hooks\\Path", False),
    ("git config --get hooksPath (읽기) → 통과", "git config --get core.hooksPath", False),
    ("ANSI-C 인용으로 감춘 -c 키 → 차단", "git -c $'core.hooks\\x50ath=/tmp/e' commit -m x", True),
    ("ANSI-C 인용으로 감춘 GIT_CONFIG 환경 변수 → 차단",
     "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=$'core.hooks\\x50ath' GIT_CONFIG_VALUE_0=/dev/null git commit -m x", True),
    ("커밋 메시지 인자의 $'a' (과차단 허용) → 차단", "git commit -m $'a'", True),
    # ── 2026-10-17 검수팀 보안 A1: 커밋 -n 묶음 어디든
    ("commit -nm → 차단", "git commit -nm x", True),
    ("commit -nS → 차단", "git commit -nS", True),
    ("commit -na → 차단", "git commit -na", True),
    ("commit -an -m → 차단", "git commit -an -m x", True),
    ("commit -m x -vn → 차단", "git commit -m x -vn", True),
    ("commit -pn → 차단", "git commit -pn", True),
    ("commit -p 단독 → 통과", "git commit -p", False),
    ("--git-dir= 옵션형 → 차단", "git --git-dir=/tmp/r commit -m x", True),
    ("--work-tree 값 분리형 → 차단", "git --work-tree /tmp/w commit -m x", True),
    ("commit -mn (메시지 n) → 통과", "git commit -mn", False),
    ("commit -S -m x → 통과", "git commit -S -m x", False),
    ("git commit -m x → 통과", "git commit -m x", False),
    # A2: --no-verify 약어 (git 2.34.1 실측: --no-veri 부터 훅 건너뜀, 그 아래는 --no-verbose 와 모호)
    ("commit --no-verif → 차단", "git commit --no-verif -m x", True),
    ("commit --no-veri → 차단", "git commit --no-veri -m x", True),
    ("commit --no-ve → 차단", "git commit --no-ve -m x", True),
    ("commit --no-v → 차단", "git commit --no-v -m x", True),
    ("commit --no-edit → 통과", "git commit --no-edit", False),
    ("commit 백슬래시로 쪼갠 --no-ver\\ify → 차단", "git commit --no-ver\\ify -m x", True),
    ("commit 메시지 속 --no-verify 글자 → 통과", 'git commit -m "docs: --no-verify 설명"', False),
    # A3: 브랜치 강제 삭제 조합
    ("branch -D → 차단", "git branch -D x", True),
    ("branch -fd → 차단", "git branch -fd x", True),
    ("branch -df → 차단", "git branch -df x", True),
    ("branch -d --force → 차단", "git branch -d --force x", True),
    ("branch --force -d → 차단", "git branch --force -d x", True),
    ("branch --delete --force → 차단", "git branch --delete --force x", True),
    ("branch -d -f → 차단", "git branch -d -f x", True),
    ("branch -d x → 통과", "git branch -d x", False),
    ("branch -f x HEAD~1 (강제 이동) → 차단(r5 C, 2026-11-09 F5C)", "git branch -f x HEAD~1", True),
    ("branch --list → 통과", "git branch --list", False),
    # A4: 훅 설정 2단계 우회
    ("config include.path → 차단", "git config include.path /tmp/evil", True),
    ("config includeIf.path → 차단", "git config includeIf.gitdir:/x/.path /tmp/evil", True),
    ("-c include.path= → 차단", "git -c include.path=/tmp/evil commit -m x", True),
    ("config --get include.path (읽기) → 통과", "git config --get include.path", False),
    ("GIT_CONFIG_GLOBAL → 차단", "GIT_CONFIG_GLOBAL=/tmp/e git commit -m x", True),
    ("env GIT_DIR → 차단", "env GIT_DIR=/tmp/r git commit -m x", True),
    ("export GIT_CONFIG_SYSTEM → 차단", "export GIT_CONFIG_SYSTEM=/tmp/e; git commit -m x", True),
    ("GIT_COMMON_DIR → 차단", "GIT_COMMON_DIR=/x git commit -m x", True),
    ("bash -c 안 GIT_DIR → 차단", "bash -c 'GIT_DIR=/x git commit -m x'", True),
    ("HARNESS_GIT_DIR 같은 이름은 통과", "HARNESS_GIT_DIR=/x git status", False),
    # A5: push 우회
    ("config alias 셸 정의 → 차단", "git config alias.p '!git push'", True),
    ("config --global alias 함수 정의 → 차단", "git config --global alias.x '!f() { git push; }; f'", True),
    ("-c alias.= 셸 → 차단", "git -c alias.p='!git push' p", True),
    ("submodule foreach push → 차단", "git submodule foreach 'git push'", True),
    ("send-pack → 차단", "git send-pack /tmp/r main", True),
    ("subtree push → 차단", "git subtree push --prefix=x origin main", True),
    ("remote … push → 차단", "git remote foo push", True),
    ("config --get alias (읽기) → 통과", "git config --get alias.co", False),
    ("config user.name → 통과", "git config user.name x", False),
    ("remote -v → 통과", "git remote -v", False),
    ("submodule foreach git status → 차단(r5 C: foreach 는 항상 deny, 2026-11-09 F5C)", "git submodule foreach git status", True),
    ("GIT_CONFIG_COUNT 설명만 있는 커밋 메시지 → 통과", 'git commit -m "GIT_CONFIG_COUNT 설명"', False),
    ("공백 든 따옴표 hooksPath 값 → 차단", 'git -c "core.hooksPath=/tmp/a b" commit -m x', True),
    ("공백 든 따옴표 alias 값 → 차단", 'git -c "alias.x=reset --hard" x', True),
    ("공백 든 따옴표 커밋 메시지 → 통과", 'git commit -m "a b"', False),
    ("커밋 메시지 속 -c alias 글자 → 통과", 'git commit -m "fix: -c alias.x 처리"', False),
    ("백슬래시로 쪼갠 hooksPath 키 → 차단", "git -c core.hooks\\Path=/x commit -m x", True),
    ("HOME 재대입 뒤 하네스 훅 경로 예외 불인정 → 차단", "HOME=/tmp/e git -c core.hooksPath=$HOME/.claude/.git/hooks commit -m x", True),
    ("export HOME 재대입 + ~ 표기 → 차단", "export HOME=/tmp/e; git -c core.hooksPath=~/.claude/.git/hooks commit -m x", True),
    ("GIT_AUTHOR_NAME 공백 든 따옴표 값 → 통과", 'GIT_AUTHOR_NAME="a b" git commit -m x', False),
    ("git config 소문자 키 영구 지정 → 차단", "git config core.hookspath /dev/null", True),
    ("git config 소문자 키 --get → 통과", "git config --get core.hookspath", False),
    ("hooksPath 하네스 경로 + 소문자 키 → 통과", f"git -c core.hookspath={HOOKS_DIR} commit -m x", False),
    # ── 2026-11-12 결정 F1·G1: push · pull 은 마커로도 안 풀린다(I1), 그 밖의 확정된 차단은 마커로 풀린다(I2)
    ("I2 마커 + reset --hard → 통과", AQ + "git reset --hard HEAD~1", False),
    ("I2 마커 + checkout . → 통과", AQ + "git checkout .", False),
    ("I2 마커 + clean -fd → 통과", AQ + "git clean -fd", False),
    ("I2 마커 + branch -D → 통과", AQ + "git branch -D x", False),
    ("I2 마커 + commit --no-verify → 통과", AQ + "git commit --no-verify -m x", False),
    ("I2 마커 + config core.hooksPath 설정 → 통과", AQ + "git config core.hooksPath /tmp/h", False),
    ("I2 마커 + stash drop; stash clear → 통과", AQ + "git stash drop; git stash clear", False),
    ("I2 마커 + git 아닌 명령 → 통과", AQ + "rm scratch.txt", False),
    ("I2 마커 + 커밋 메시지 속 push·pull 낱말 → 통과", AQ + "git commit -m 'docs: git push 와 git pull 규칙'", False),
    ("I2 마커 인용 속 git push 낱말 + git status → 통과(마커 줄은 떼고 본다)", "# APPROVED 사용자 «git push 해 주세요»\ngit status", False),
    ("I1 마커 + git push → 차단", AQ + "git push origin main", True),
    ("I1 마커 + git pull → 차단", AQ + "git pull", True),
    ("I1 마커 + 풀리는 stash 뒤 push → 차단", AQ + "git stash; git push origin main", True),
    ("I1 마커 + 풀리는 reset --hard 뒤 push → 차단", AQ + "git reset --hard && git push", True),
    ("I1 마커 + -c alias 로 감싼 push → 차단", AQ + "git -c alias.p=push p origin", True),
    ("I1 마커 + config alias 설정 → 차단", AQ + "git config alias.p push", True),
    ("I1 마커 + 하위 명령 자리 변수 → 차단", AQ + "git $SUB origin main", True),
    ("I1 마커 + GIT_CONFIG_* 로 만든 alias → 차단", AQ + "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.st GIT_CONFIG_VALUE_0=push git st", True),
    ("I1 마커 + rebase --exec → 차단", AQ + "git rebase --exec 'git push' main", True),
    ("I1 마커 + submodule foreach → 차단", AQ + "git submodule foreach git status", True),
    ("I1 마커 + 풀리는 --output 이 뒤 규칙을 가리지 않음(difftool -x) → 차단", AQ + "git difftool --output=x -x cat", True),
    ("I2 마커 + 설정된 difftool(명령 문자열 없음) → 통과", AQ + "git difftool HEAD", False),
    # 2026-11-12 security: push 계열 낱말 누락 보완(lfs push · svn 올려 보내기)
    ("git lfs push → 차단", "git lfs push origin main", True),
    ("git lfs push --all → 차단", "git lfs push --all origin", True),
    ("git svn dcommit → 차단", "git svn dcommit", True),
    ("git svn set-tree → 차단", "git svn set-tree HEAD", True),
    ("git svn branch → 차단", "git svn branch -m msg new", True),
    ("git lfs ls-files → 통과", "git lfs ls-files", False),
    ("git lfs track → 통과", "git lfs track '*.bin'", False),
    ("git svn log → 통과", "git svn log", False),
    ("커밋 메시지 속 git lfs push → 통과", "git commit -m 'docs: git lfs push 안내'", False),
    ("커밋 메시지 속 git svn dcommit → 통과", "git commit -m 'docs: git svn dcommit 안내'", False),
    # 2026-11-12: lfs pull 은 pull 과 같은 급(마커로도 안 풀림), 조회는 통과
    ("git lfs pull → 차단", "git lfs pull origin", True),
    ("git lfs status → 통과", "git lfs status", False),
    ("git lfs env → 통과", "git lfs env", False),
    ("커밋 메시지 속 git lfs pull → 통과", "git commit -m 'docs: git lfs pull 안내'", False),
    # 2026-11-12: 줄 이음(백슬래시+줄바꿈)은 셸이 지운다 → 이어 붙인 사본으로 판정
    ("줄 이음으로 쪼갠 git 이름 + push → 차단", "gi\\\nt push origin main", True),
    ("줄 이음으로 쪼갠 git 이름 + pull → 차단", "g\\\nit pull", True),
    ("줄 이음으로 쪼갠 하위 명령 push → 차단", "git pu\\\nsh origin main", True),
    ("줄 이음으로 쪼갠 lfs push → 차단", "git lfs pu\\\nsh origin", True),
    ("줄 이음으로 나눈 git 아닌 명령 → 통과", "ls \\\n  -la", False),
    ("원문의 줄 이음이 든 git 명령 → 차단(HEAD 와 같음: 원문 검사는 그대로)", "git log \\\n  --oneline -3", True),
    ("여러 줄 커밋 메시지(줄 이음 없음) → 통과", 'git commit -m "fix: a\n\nb 설명"', False),
    ("I1 마커 + 원문의 줄 이음이 든 git 명령 → 차단(판정 불가 종류)", AQ + "git log \\\n  --oneline -3", True),
    ("I1 마커 + 줄 이음으로 나눈 stash → 차단(판정 불가 종류)", AQ + "git \\\n  stash", True),
    # 2026-11-12: 승인 마커로 풀리지 않는 범위는 push · pull 을 감출 수 있는 꼴로 한정 — 감출 수 없는 것은 풀린다
    ("I2 마커 + --work-tree → 통과", AQ + "git --work-tree /tmp/w status", False),
    ("I2 마커 + init --template → 통과", AQ + "git init --template=/tmp/t x", False),
    ("I2 마커 + maintenance start → 통과", AQ + "git maintenance start", False),
    ("I1 마커 + filter-repo(호출 전체가 안 풀림) → 차단", AQ + "git filter-repo --path x", True),
    ("I1 마커 + filter-branch 셸 필터 → 차단", AQ + "git filter-branch --tree-filter 'git push' HEAD", True),
    ("I2 마커 + GIT_INDEX_FILE → 통과", AQ + "GIT_INDEX_FILE=/tmp/i git status", False),
    ("I1 마커 + 풀리는 변수 뒤 GIT_CONFIG_* → 차단", AQ + "GIT_INDEX_FILE=/tmp/i GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.st GIT_CONFIG_VALUE_0=push git st", True),
    # ── 2026-11-12 reviewer · security 반송: 원문은 HEAD 검사 그대로 + 이어 붙인 사본은 추가 검사
    ("줄 끝 겹 백슬래시 + 인용 사이의 push → 차단", "echo \\\\\n\"x\" ; git push origin main ; echo \\\\\n\"y\"", True),
    ("I1 마커 + 줄 끝 겹 백슬래시 + 인용 사이의 push → 차단", AQ + "echo \\\\\n\"x\" ; git push origin main ; echo \\\\\n\"y\"", True),
    ("I1 마커 + 인용 속 겹 백슬래시 줄 끝 뒤 push → 차단", AQ + "echo \"a\\\\\n\" ; git push origin main ; echo \"b\"", True),
    ("인용 속 줄 이음이 든 commit → 차단(HEAD 와 같음)", "git commit -m 'x\\\ny'", True),
    ("I1 마커 + 줄 이음으로 쪼갠 git 이름 push → 차단", AQ + "g\\\nit push origin main", True),
    ("I1 마커 + filter-branch --setup 명령 문자열 → 차단", AQ + "git filter-branch --setup 'git push origin main' HEAD", True),
    ("I1 마커 + filter-branch 약어 --tree-f → 차단", AQ + "git filter-branch --tree-f 'git push' HEAD", True),
    ("I1 마커 + filter-repo 콜백 약어 → 차단", AQ + "git filter-repo --filename-callb 'return x'", True),
    ("git lfs pre-push → 차단", "git lfs pre-push origin", True),
    ("I1 마커 + git lfs pre-push → 차단", AQ + "git lfs pre-push origin", True),
    ("git lfs $a (인자 변수) → 차단", "git lfs $a origin main", True),
    ("I1 마커 + git lfs $a → 차단", AQ + "git lfs $a origin main", True),
    ("I1 마커 + git svn $a → 차단", AQ + "git svn $a", True),
    ("I1 마커 + git subtree $a → 차단", AQ + "git subtree $a --prefix=x origin main", True),
    ("git subtree pull → 차단", "git subtree pull --prefix=x origin main", True),
    ("git svn rebase → 차단", "git svn rebase", True),
    ("I1 마커 + git svn fetch → 차단", AQ + "git svn fetch", True),
    ("I1 마커 + GIT_CONFIG_PARAMETERS 의 alias → 차단", AQ + "GIT_CONFIG_PARAMETERS=\"'alias.x=!git push' 'core.hooksPath=/x'\" git x", True),
    ("I1 마커 + HOME 재대입 → 차단", AQ + "HOME=/tmp/h git x", True),
    ("I1 마커 + --git-dir → 차단", AQ + "git --git-dir=/tmp/x status", True),
    ("I1 마커 + -c alias(내용 무관) → 차단", AQ + "git -c alias.p=status p", True),
    ("I1 마커 + rebase --exec= → 차단", AQ + "git rebase --exec=true main", True),
    ("I1 마커 + --exec-path → 차단(GIT_EXEC_PATH 와 같은 종류)", AQ + "git --exec-path=/tmp/x status", True),
    ("I2 마커 + GIT_TEMPLATE_DIR → 통과(--template 과 같은 종류)", AQ + "GIT_TEMPLATE_DIR=/tmp/t git init x", False),
    ("I2 마커 + -c core.hooksPath → 통과", AQ + "git -c core.hooksPath=/tmp/h commit -m x", False),
]

fail = 0
for name, cmd, want in CASES:
    got = blocked(cmd)
    ok = got == want
    fail += 0 if ok else 1
    print(f"{'OK ' if ok else 'FAIL'} {name}: deny={got} (기대 {want})")

# I1 표: 마커 없이 «마커로 안 풀리는» 사유(push · pull 사유 포함)로 막히는 경우마다 마커를 붙여도 같은 사유 종류로 막히는지 본다.
#   push · pull 사유 문구는 모두 그 종류여야 한다(«# APPROVED 로 재실행» 안내가 붙으면 안 된다).
n_i1 = 0
for name, cmd, _ in CASES:
    if cmd.startswith("# APPROVED"):
        continue
    r0 = reason(cmd)
    pushy = "push/pull은 항상 사용자 직접" in r0
    if STRICT not in r0 and not pushy:
        continue
    n_i1 += 1
    r1 = reason(AQ + cmd)
    ok = STRICT in r0 and STRICT in r1 and "터미널에서 직접" in r1
    fail += 0 if ok else 1
    print(f"{'OK ' if ok else 'FAIL'} I1 마커 변형 {name}: {'차단' if r1 else '통과'}")
assert n_i1 >= 40, n_i1   # 표가 비어 공허하게 통과하지 않게
# 문구: 풀리는 차단은 종전 안내(# APPROVED 로 재실행)를 그대로 쓴다
r_ok = reason("git stash")
ok = "'# APPROVED'로 재실행" in r_ok and STRICT not in r_ok
fail += 0 if ok else 1
print(f"{'OK ' if ok else 'FAIL'} 풀리는 차단 문구 유지(git stash)")

print(f"\n{'ALL PASS' if fail == 0 else f'FAIL {fail}'} ({len(CASES)} cases)")
sys.exit(1 if fail else 0)
