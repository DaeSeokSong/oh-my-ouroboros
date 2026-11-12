"""PreToolUse extension of git-guardrails.sh: allow-list for `git -c`, history-erasing subcommands, discarded-change paths.

Called by git-guardrails.sh just before its final `exit 0` (2026-11-09, agent cleanup step 5, revised after review R1-R11,
then spec r5: heredoc ban H and wide deny C).
Reads the hook JSON on stdin, prints one deny JSON line only when it blocks, and always exits 0. The shell wrapper turns
a non-zero exit or a crash into a deny, so this file never has to fail open.

Why a Python file: the shell hook judges git commands with regexes over a quote-stripped string. That cannot say
"this path has uncommitted changes" or "this -c key is harmless". Both need real tokens and a real `git diff`.

Rules (token based, `shlex` with punctuation splitting and newline as a separator, comments not interpreted so a wrong
comment guess never hides a later command; the price is a few false positives):
  1. `-c <key>=<v>` allow-list, also applied to `git config` writes (R9: key+value, --add, --replace-all, `config set`;
     reads and --list pass; --unset(-all) and `unset` pass only for the repo's own config, user/system/file scope is denied).
     Allowed = keys that only change output format, identity or protocol: advice.* color.*
     core.quotepath core.autocrlf core.safecrlf core.abbrev user.name user.email protocol.version init.defaultbranch
     diff.noprefix diff.renames diff.algorithm merge.conflictstyle status.showuntrackedfiles log.decorate gc.auto
     maintenance.auto, plus core.hookspath only when it points at the harness hooks dir. Everything else can make git run a
     program (core.fsmonitor, core.pager, diff.external, core.editor, alias.*, credential.helper ...) or pull in another
     config file (include.path), so it is denied. Section and last name are case-insensitive in git, the subsection is
     not, so only those two are lowered. `--config-env` is always denied (the value lives in the environment).
  2. Environment variables that do the same as -c or move git's files (GIT_CONFIG_*, GIT_EXTERNAL_DIFF, GIT_SSH*,
     GIT_ASKPASS, HOME, XDG_CONFIG_HOME, LD_PRELOAD, LD_AUDIT, BASH_ENV, PATH, GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE ... R4).
     Without this the allow-list is bypassed with `GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.pager ...` or `HOME=/x` (a
     different global config). `NAME+=value` counts as an assignment. Pager and editor variables are fine only with a
     harmless value (cat less more true : or empty). They are checked across shell payloads too (`FOO=x bash -c 'git ...'`).
  3. Subcommands that erase history or objects: filter-repo, filter-branch, update-ref -d/--stdin/zero oid, gc --prune*,
     prune (not -n), reflog expire/delete, rebase (only --abort and --show-current-patch pass).
  4. restore/checkout of paths: denied only when the paths have uncommitted changes (worktree vs index, index vs HEAD, or
     a file hidden from diff by assume-unchanged/skip-worktree = `ls-files -v` tag lowercase or S, R5), checked by real git
     calls. A blanket ban would block harmless restores, and the shell hook already blocks the whole-tree forms
     (`.` `./` `:/`). The check call neutralizes repo-config code execution (core.fsmonitor etc.) with -c overrides and a
     scrubbed environment (GIT_ATTR_NOSYSTEM too). Diff may run a clean filter (R10): when the repo's own config (not
     system/global, those are the user's) has `filter.*`, paths whose `filter` attribute is set (git check-attr) are
     denied without running diff. Denying every path of such a repo, as the first draft of R10 said, would block all
     restores in the harness repo itself (local filter.nomodel) and fail the existing tests.
  5. Shell payloads are re-checked recursively, depth limit 3 (R3): sh/bash/rbash/zsh/dash/ksh/ash/mksh/yash/fish/tcsh/csh/busybox
     `-c` (also bundles like -lc; here-strings also for `source` and `.`), eval, `env -S`, `su -c`, `flock -c`, `script -c`, `watch`, `tmux new-session/new-window/
     split-window/respawn-pane/send-keys`, here-strings fed to a shell, and `$(...)`/backticks inside a quoted token that
     mentions git. Plain quoted strings (`grep "git push"`, commit messages) stay data, otherwise they would be false hits.
  6. Same effect, other door (R6/R7): checkout-index, read-tree -u/--reset, apply -R, update-index --assume-unchanged/
     --skip-worktree, and long-option abbreviations (git accepts unambiguous prefixes: `gc --pru`, `reset --ha`,
     `checkout --forc`, `switch --discard`, `clean --forc`, `update-ref --std`). An ambiguous abbreviation makes git fail,
     so denying it costs nothing.
  7. Shell expansion hygiene (R1): a backslash-newline with git present, and `$` backtick `{` `}` or glob characters in the
     subcommand token, the global options, or the arguments of the subcommands above are denied because the shell would
     rewrite them after we looked. Exceptions: globs in restore/checkout path arguments (the check call sees the same
     pathspec) and in the non-option arguments of the rule 11 subcommands (patterns, refspecs, URLs), and `@{...}`
     revision syntax (`@{-1}`, `HEAD@{1}`, `@{u}`), also in the restore/checkout path-brace deny. Read-only diff/log/show/grep
     are not in the hygiene set: `git log $BRANCH` and `git grep 'a*'` are everyday use.
  8. Heredoc ban (spec r5 H, replaces R2/R2b): a command that mentions git (recursion included) and holds an unquoted `<<`
     (not `<<<`) is denied: «git 명령과 heredoc(<<) 을 함께 쓰지 않습니다 — 커밋 메시지는 git commit -F <파일> 로».
     The heredoc body parser (R2) and the re-check of the lines it removed (R2b) are deleted. Why: the start test had
     been bypassed three times in a row (`<<` inside quotes, `((1<<2))`, `$'\\'...'`), each patch invited the next
     bypass, and a body that is never parsed cannot hide a command. Detection works on tokens: a token made only of
     punctuation characters that still holds `<<` after `<<<` is cut out. A `<<` inside a longer quoted word
     (`-m "fix <<EOF"`) is data and passes. A tokenizer failure with git and `<<` in the text gets the same message.
  9. Redirection digits (R8): a 1-2 digit token right before a redirection operator is a file descriptor (`2>&1`) and is
     removed from the arguments. Longer digit tokens are kept so a 40-zero oid is never swallowed. A `<(` / `>(` token
     is a process substitution, not a redirection: the next token is not swallowed as a target and the inside is
     analyzed as an ordinary command.
 10. Shell-level indirection (R11, user decision F5T=2, from the hidden case `alias g=git; g gc --prune=now`): inside a
     command that mentions git (recursion included) these are denied because the hook cannot see which git runs:
     an `alias` whose value has git (also `alias -g`, `alias --`), `hash` registering a git path (`hash g=/usr/bin/git`,
     `hash -p <git path> g`), a command word holding `$` or a backtick (`G=git; $G gc`, `"$G" gc`, `${G} gc`,
     `` `echo git` gc ``), and a function definition whose body mentions git (the arguments arrive from outside:
     `f() { git "$@"; }; f gc --prune=now`; the body end is found with a quote-aware bracket match so `"}"` cannot end
     it early). Aliases, functions and variables without git stay untouched (`alias ll='ls -l'`). The principle is
     blocked, not the single sample.
 11. Wide deny (spec r5 C, user decision F5C=2). Principle: a git form is denied when it (D) throws away uncommitted work
     or the index, (R) erases refs, objects, reflog or configuration in a way that is hard to undo, or (X) makes git run
     a program the caller chose (options and environment included). Left open is only what is normal and recoverable:
     `--abort` of merge/cherry-pick/revert/am/rebase, reset --soft/--mixed, clean -n, branch -d / -m, remote prune,
     fetch --prune, gc / gc --auto / --aggressive (prune keeps 2 weeks), maintenance run, pack-refs, prune-packed,
     fsck --lost-found, commit --amend (reflog), --paginate, GIT_CEILING_DIRECTORIES, GIT_TRACE* with a flag value
     (1 2 true false 0 or empty; a file path value appends to any file, r5fix 13), status.
     Denied form                                           | Why                                               | Principle
     merge/cherry-pick/revert/am --quit                    | forgets MERGE_HEAD / sequencer state              | R
     reset --hard/--merge/--keep                           | resets index and worktree                         | D
     clean without -n/--dry-run                            | deletes untracked files                           | D
     rm -f/--force, mv -f/--force                          | removes modified files, overwrites a target       | D
     worktree remove/move --force                          | drops a worktree that has changes                 | D
     worktree prune                                        | erases worktree records                           | R
     submodule deinit/update --force                       | discards submodule changes                        | D
     submodule foreach                                     | the string runs as shell, never analyzed          | X
     sparse-checkout except list/check-rules               | hides tracked files via skip-worktree (like R5)   | D
     diff/log/show/... --output, archive -o/--output       | overwrites a file                                 | D
     update-index --force-remove                           | drops an index entry                              | D
     checkout -B, switch -C/--force-create                 | force-moves a branch                              | R
     tag -d/-f, branch -f/-D/-M/-C                         | deletes or moves refs                             | R
     symbolic-ref with a value or -d                       | repoints/deletes HEAD, worktree no longer matches | R
     notes remove/prune/edit/--force                       | erases notes, or runs the editor                  | R, X
     replace (except list)                                 | swaps objects inside history                      | R
     remote remove/rm                                      | erases remote config and tracking refs            | R
     fetch/pull +refspec or --force                        | overwrites local refs or tags                     | R
     update-ref moving an existing ref to a non-descendant | drops commits from a branch (git rev-parse check) | R
     repack -d                                             | deletes packs, unreachable objects with them      | R
     maintenance except run                                | registers a scheduler job that runs git later     | X
     fast-import --force                                   | overwrites branch refs                            | R
     config --edit/-e/edit, --remove-section               | runs the editor, erases a section                 | X, R
     bisect run, difftool, mergetool                       | run a script or tool                              | X
     grep -O/--open-files-in-pager                         | runs a pager program                              | X
     --upload-pack/--receive-pack/--exec, clone -u         | run the program that is named                     | X
     init/clone --template                                 | template directory copies hooks                   | X
     LD_AUDIT=, BASH_ENV= (rule 2)                         | load code into every program                      | X
     checkout/restore --ours/--theirs                      | overwrites a conflicted file with one side        | D
     update-index --remove/--cacheinfo/--index-info/--replace | drops or rewrites index entries (like --force-remove) | D
     any subcommand --output (also stash/reflog show)      | overwrites a file (not only diff/log/show/archive) | D
     worktree add -B                                       | force-moves an existing branch                    | R
     config --unset/--unset-all/unset with --global/--system/--file | erases a user/system setting       | R
     clone -c/--config key=value                           | same allow-list as `git -c` (core.sshCommand ...) | X
     ext:: URL or GIT_ALLOW_PROTOCOL                       | the ext transport runs an arbitrary command       | X
     instaweb, send-email, web--browse, remote-ext         | start a server/mail/browser the caller names      | X
     GIT_*_PATHSPECS (rule 2)                              | changes pathspec matching, the check call differs | D
     Where the other rows live: stash create (any stash form except list/show) and branch -D are denied by the shell part
     of git-guardrails.sh; rebase --quit/--exec is rule 3 (rebase passes only with --abort or --show-current-patch);
     checkout --ours <path> is the row above (it used to be left to rule 4, which lets it pass when the path is clean).
     sec4 hardening (the 26 cases of probe_cases_sec4.json, 2026-11-09), families rather than samples:
       - update-ref delete letter inside a short bundle (-zd, -dm); `-m` ends the bundle, its value is a message.
       - A name split by quotes or backslashes (g"i"t, g'i't, g-backslash-it) is git: git-guardrails.sh looks for `git`
         in a copy without quotes/backslashes before its early exit and judges a backslash-free copy too, and this file
         uses has_git() wherever it used to look for the plain word.
       - `~` at the start of a restore/checkout path (the shell expands it after the check call ran), a `cd` inside a
         quoted payload (`eval 'cd sub'`), `$(...)` closed by a `)` inside quotes (`$(echo ')'; git ...)`), an unquoted
         backtick substitution (judged on a copy where backticks separate commands), any tmux subcommand that carries a
         command string, and a `$` word between a wrapper and git (`sudo -u root $G tag`).
       - `git config --unset*` is open for the repo's own config and denied for user/system/file scope.
     r5fix hardening (stage5_fix_r5.md, 2026-11-09, 14 items), again families:
       - zsh `=git` (the path of git) is git: cmd_base() drops a leading `=` wherever a command word is judged.
       - `chdir` moves the shell like `cd`/`pushd`. More environment names: GIT_TEST_* PERL5OPT PERL5DB PERL5LIB PERLLIB
         GITPERLLIB GCONV_PATH LOCPATH NLSPATH BROWSER MANPAGER. GIT_TRACE* passes only with 1 2 true false 0 or empty
         (any other value is a file or fd that git appends to).
       - `apply` passes only as a query (--check --stat --numstat --summary, never with --apply): a reversed patch can
         erase uncommitted changes. restore/checkout paths with an unquoted parenthesis or angle bracket inside a word
         (zsh glob `a(.)`, `(a|b).txt`, `a<->`) are denied, see glob_op_paths(). The first non-option word of remote,
         bisect, submodule, worktree, notes, maintenance, sparse-checkout, bundle may not hold a glob (`remote re*`).
       - `fetch --prune-tags`/`-P`, and `--prune`/`-p` with `--tags` or a refspec that writes outside refs/remotes/ (it
         deletes local branches/tags); `merge-file` without -p/--stdout (overwrites the first file); `fast-export`/
         `fast-import` --export-marks/--export-pack-edges, `index-pack -o`, `format-patch -o/--output-directory` and
         `bundle create` (write to a named file); two-argument `update-ref` only when git is at a command position.
       - The shell-hook rules (push pull send-pack http-push, stash except list/show, commit --no-v*/-n, checkout/switch
         -f, restore/checkout `.` `./` `:/`, remote/subtree push) are judged here too (check_shell_rules), so a
         `git-<sub>` executable path and `=git` get the same verdict as plain `git <sub>`.
     r6fix hardening (stage5_fix_r6.md, 2026-11-09, 11 items), families again:
       - Quoted or backslash-escaped punctuation (`';'` `'|'` `"("` `\\;` ...) is an argument. tokenize() swaps such
         characters for private-use stand-ins before shlex and marks a token left with only punctuation as a QuotedTok;
         is_op() is False for it, so it no longer splits a segment (`git branch ';' -D x` used to look like two commands
         and lost its `-D`) and no longer counts as `<<`. git-guardrails.sh strip_quoted does the same on its side
         (a quote body of only punctuation, or a backslash before punctuation, becomes the word QQ).
       - Commands that run the text they are fed are shells for the here-string rule: `source` and `.` (STREAM_SHELLS)
         and `rbash` (SHELLS). Pipes and process substitutions into them are blocked by bash-write-check.sh.
       - A name that receives a value is judged like a `NAME=value` prefix (bad_targets): `read`, `for NAME in`,
         `printf -v`, `declare/typeset/export/local/readonly`, `mapfile/readarray`, `select`, `getopts`. The value is
         unknown there, so every name bad_env() could reject with some value is rejected. ENV_DENY also holds LESSOPEN
         LESSCLOSE SHELLOPTS PS4.
       - short_hit(): a `stop` letter is an option that takes a value, so the rest of the bundle is its value and the
         next argument is its value when the letter ends the bundle (merge-file `-L`, clean `-e`, tag `-m -F -u`,
         grep `-e -f -A -B -C -m`). `clean -en` is a pattern `n`, not a dry run; `git grep -eOK` is no longer a hit.
       - commit joins the expansion check (with bundle, format-patch, index-pack, fast-export, merge-file) except for the
         values of -m/--message/-F/--file and the commit values of -c/-C/--reuse-message/--reedit-message (`-c $SHA`);
         everything after `--` (pathspecs) is not checked; globs in the non-option arguments are fine.
       - cherry-pick/revert/am `--skip` is denied; `config --rename-section` (and `rename-section`) is denied for the
         global/system/file scope and open for the repo's own config; `apply` takes its query flag only before `--`;
         fetch --prune skips the value of an option such as `--depth 1` when it looks for the remote and the refspecs.

Fail-closed on purpose: the 4-step agent-type hook fails open, but git commands here destroy data, so anything that
cannot be decided is denied: a quote parse failure, an unexpected exception, a git that is not at a command position
(`xargs git restore`), `cd`/`chdir`/`pushd` anywhere (the base folder is unknown), `$` or backticks or `{}` in a path, a failing
or slow (3 s) check call.

Known limits: aliases defined in a repo config that wrap a subcommand, scripts written to a file and run later,
wrappers outside the list (ssh, parallel, xargs payloads ...), `--git-dir`/`--work-tree` only denied when a path check
is needed (the shell hook denies them everywhere), and a 1-2 digit token right before a redirection operator is removed
from the arguments (`git log -n 2 >f` drops the `2`). That last one is a real hole, not harmless: a path literally named
1 or 2 (`git restore 1 >f`) is not seen by the rules that read paths.
R11 limits: git assembled from pieces with no git word anywhere in the command (`G=g; H=it; $G$H gc`) is not seen,
nor is git reached through a non-command-position `$` (`xargs $G`). A user's own shell configuration (the git aliases
and functions of e.g. the oh-my-zsh git plugin: `grhh`, `gst`) holds no git word in the command, so the hook cannot see
them. 사용자 셸 설정의 기존 git 별칭은 볼 수 없음 (2026-11-09 이 서버 Bash 도구 셸 스냅샷엔 없음: 별칭은 run-help ·
which-command 2개뿐). Function-definition detection is text based (quote aware, no here-document awareness), and a
`case` pattern `a)` inside a `name() ( ... )` body can end the body match early.
sec4 limits: a git name that the shell assembles (glob `g?t`, `/usr/bin/g*`, `$'g\x69t'`, variables) holds no git word
after quote/backslash removal, so neither hook sees it; a text piped into a shell (`echo 'git tag -d v1' | bash`) is
left to bash-write-check.sh; `merge -s <name>` runs a `git-merge-<name>` program from PATH; config unset in the repo's
own scope and `ext::`-like helpers other than `ext` (`fd::`, `hg::`) stay open; `send-email` and the other program
subcommands are denied whole, not only with their program options.
Rule 8 limits: none left since r6fix 1 (a quoted `<<` is an argument and passes). The tokenizer refuses input that already
holds the private-use characters U+E000-U+E007 (they would be read back as punctuation); with git in the text it is denied.
Rule 11 limits: forms outside the table stay open (`format-patch` and `index-pack` without `-o` still write files next to
the cwd/pack); `restore --staged` passes although it drops staged content (everyday unstaging, spec r1); an
option hidden in a variable is not seen in diff/log/show/grep (not in the hygiene set); `--quit`, `maintenance unregister`, `worktree prune` are denied
although mild (the spec leaves only the listed forms open); update-ref compares with the repo found from the hook cwd,
so outside a repository a two-argument `update-ref` is denied.
r5fix limits: glob_op_paths() reads the raw text per piece (split at ; & | newline) and looks only at words of a piece that
holds a git word and `restore`/`checkout`; a glob qualifier in another piece or in a variable is not seen, and an unquoted
`>`/`<` glued inside a word (`a>b`) is denied although it could be a plain redirect. The wide `apply` deny also blocks a
patch applied on purpose (`git apply p.diff`, `--index`); the user runs it. A refspec destination that is a bare name
(`main:main`) counts as local under `fetch --prune`. `popd` is not treated like `cd`. `=git` is recognized only as a command
word (`=git` inside a quoted payload is judged by the recursion). A text piped into a shell, and `| sed e` / `s///e`, are
left to bash-write-check.sh (the sed forms are denied there since r5fix 2, widened by r6fix 3).
r6fix limits: glob_op_paths() reads comments as code, so a parenthesis in a trailing comment of a restore/checkout line
(`git restore a.txt # note (see x)`) is denied like a zsh glob; write the comment on its own line or leave the parenthesis
out. bad_targets() only sees the command word of a segment (`read` after `sudo -u x` is missed), takes a `read -p` prompt
for a name (a prompt called PATH is denied), and does not follow namerefs (`declare -n r=HOME; r=/x`). A `NAME=value`
word inside a quoted commit message is still taken for an assignment (`git commit -m 'BROWSER=x'` is denied).
"""
import json
import os
import re
import shlex
import subprocess
import sys

TAIL = "— 사용자 직접 실행 원칙. 목적을 설명하고 승인받은 뒤 첫 줄 '# APPROVED'로 재실행하세요 (code-execution.md § Hook 차단 시 처리)."
# 2026-11-12 decision F1/G1: push and pull are the user's alone, an `# APPROVED` marker never lifts them. git-guardrails.sh
# passes --approved (marker line removed from the command). Then only verdicts marked deny(..., ok=True) are skipped: forms
# whose git subcommand is fixed and is not push/pull (discarded work, erased refs, hook bypass, file writes, tools
# or hook files on disk: --template, maintenance, a configured difftool). Everything else stays a deny by default, and only
# these may stay so: push/pull and their family (incl. lfs push/pre-push/pull, subtree push/pull, svn dcommit/fetch/
# rebase ...), and forms that can hide one so the verdict cannot be fixed: a command string git runs (rebase -x, bisect run,
# submodule foreach, difftool -x, filter-branch and filter-repo as a whole, --upload-pack/--exec, ext::, send-email
# --to-cmd and the other PROG_SUBS, grep -O), other git-* programs (--exec-path, GIT_EXEC_PATH), `-c`/config keys outside
# the allow-list, --config-env, environment that runs code or pulls in config (all but ENV_LIFT and GIT_TRACE*), shell
# expansion in the subcommand, global options, an action word or the arguments of lfs/svn/subtree, shell indirection
# (alias, hash, function, `$` command word), nesting, line continuation, a failed parse, heredoc. A rule added later is
# therefore not lifted unless marked.
STRICT_TAIL = ("— 승인 표시(# APPROVED)로도 통과하지 않습니다. push·pull 과 그것을 감출 수 있는 형태는 사용자가 터미널에서 직접 실행하세요"
               " (2026-11-12 결정, code-execution.md § Hook 차단 시 처리).")
APPROVED = "--approved" in sys.argv[1:]
HEREDOC_MSG = "git 명령과 heredoc(<<) 을 함께 쓰지 않습니다 — 커밋 메시지는 git commit -F <파일> 로"
MAX_DEPTH = 3
PUNCT = set(";&|()<>\n")
QUOTE_MAP = {c: chr(0xE000 + n) for n, c in enumerate(";&|()<>\n")}  # private-use stand-ins for quoted/escaped punctuation
QUOTE_BACK = {ord(v): k for k, v in QUOTE_MAP.items()}
SHELLS = {"sh", "bash", "rbash", "zsh", "dash", "ksh", "ash", "mksh", "yash", "fish", "tcsh", "csh", "busybox"}
STREAM_SHELLS = SHELLS | {"source", "."}  # also run a text fed through a here-string (`. /dev/stdin <<< '...'`)
CMD_PREFIX = {"env", "command", "exec", "nohup", "nice", "time", "sudo"}
ASSIGN = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\+?=(.*)", re.DOTALL)
SHC = re.compile(r"-[A-Za-z]*c[A-Za-z]*")
WRAPPERS = {"env", "command", "exec", "nohup", "nice", "time", "sudo", "doas", "runuser", "xargs", "timeout", "setsid", "stdbuf", "ionice"}
CD_WORD = re.compile(r"(?:^|[\s;&|(`'\"{])(?:cd|chdir|pushd)(?:$|[\s;&|)`'\"])")
GIT_WORD = re.compile(r"(?<![A-Za-z0-9_])git(?![A-Za-z0-9_])")
VALUE_LONG = {"--config-env", "--git-dir", "--work-tree", "--namespace", "--super-prefix", "--attr-source"}
PATHSPEC_OPTS = {"--literal-pathspecs", "--glob-pathspecs", "--noglob-pathspecs", "--icase-pathspecs"}
CFG_SECTIONS = {"advice", "color"}
CFG_ALLOW = {
    "core.quotepath", "core.autocrlf", "core.safecrlf", "core.abbrev", "user.name", "user.email", "protocol.version",
    "init.defaultbranch", "diff.noprefix", "diff.renames", "diff.algorithm", "merge.conflictstyle",
    "status.showuntrackedfiles", "log.decorate", "gc.auto", "maintenance.auto",
}
HOME = os.path.expanduser("~")
HOOK_PATHS = {
    "~/.claude/.git/hooks", f"{HOME}/.claude/.git/hooks", os.path.realpath(f"{HOME}/.claude/.git/hooks"),
}
ENV_DENY = {
    "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT", "GIT_EXTERNAL_DIFF", "GIT_SSH", "GIT_SSH_COMMAND", "GIT_ASKPASS",
    "SSH_ASKPASS", "GIT_PROXY_COMMAND", "GIT_EXEC_PATH", "GIT_TEMPLATE_DIR", "HOME", "XDG_CONFIG_HOME", "LD_PRELOAD",
    "LD_LIBRARY_PATH", "LD_AUDIT", "BASH_ENV", "PATH", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_DIR", "GIT_COMMON_DIR", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM",
    "GIT_CONFIG", "GIT_LITERAL_PATHSPECS", "GIT_GLOB_PATHSPECS", "GIT_NOGLOB_PATHSPECS", "GIT_ICASE_PATHSPECS",
    "GIT_ALLOW_PROTOCOL", "PERL5OPT", "PERL5DB", "PERL5LIB", "PERLLIB", "GITPERLLIB", "GCONV_PATH", "LOCPATH", "NLSPATH",
    "BROWSER", "MANPAGER", "LESSOPEN", "LESSCLOSE", "SHELLOPTS", "PS4",
}
TRACE_NAME = re.compile(r"GIT_TRACE\w*")
ENV_LIFT = {"GIT_LITERAL_PATHSPECS", "GIT_GLOB_PATHSPECS", "GIT_NOGLOB_PATHSPECS", "GIT_ICASE_PATHSPECS", "GIT_INDEX_FILE",
            "GIT_WORK_TREE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
            "GIT_TEMPLATE_DIR"}  # marker lifts them; GIT_TEMPLATE_DIR = --template (hook files, like core.hooksPath)
TRACE_SAFE = {"1", "2", "true", "false", "0", ""}  # any other GIT_TRACE* value is a file path or fd: appends to an arbitrary file
ENV_PAGER = {"GIT_PAGER", "PAGER", "GIT_EDITOR", "EDITOR", "VISUAL", "GIT_SEQUENCE_EDITOR"}
PAGER_SAFE = {"cat", "less", "more", "true", ":", ""}
ENV_DROP = {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_EXTERNAL_DIFF", "GIT_PAGER"}
LONG_OPTS = [  # restore/checkout long options we care about, for unambiguous-prefix expansion (git accepts them)
    "--staged", "--worktree", "--source", "--patch", "--pathspec-from-file", "--pathspec-file-nul", "--detach",
    "--orphan", "--conflict",
]
LONG_VAL = {"--source", "--orphan", "--conflict", "--pathspec-from-file"}
# Subcommands of the wide deny (rule 11) whose arguments get the shell-expansion check; their non-option arguments may hold globs.
WIDE_SUBS = {
    "merge", "cherry-pick", "revert", "am", "rm", "mv", "worktree", "submodule", "sparse-checkout", "archive", "tag", "branch",
    "symbolic-ref", "notes", "replace", "remote", "fetch", "pull", "repack", "maintenance", "fast-import", "bisect",
    "difftool", "mergetool", "ls-remote", "clone", "init",
    "commit", "bundle", "format-patch", "index-pack", "fast-export", "merge-file",  # r6fix 7
    "lfs", "svn", "subtree",  # 2026-11-12: a `$a` there can become push/pull
}
# Subcommands whose first non-option argument is an action word (remove, run, foreach, prune, create ...); a glob there can rewrite it.
ACT_SUBS = {"remote", "bisect", "submodule", "worktree", "notes", "maintenance", "sparse-checkout", "bundle", "lfs", "svn", "subtree"}
# Subcommands that start a server, send mail or run a program the caller picks (rule 11 X).
PROG_SUBS = {"instaweb", "send-email", "web--browse", "remote-ext"}
# Options whose next argument is a value, not an action word (so `notes --ref x remove` finds `remove`).
VAL_OPTS = {"-m", "--ref", "-F", "-C", "-c", "--message", "--file"}
# fetch options whose next argument is a value (so `fetch --depth 1 <url>` does not take `1` for the remote)
FETCH_VAL = {"--depth", "--deepen", "--shallow-since", "--shallow-exclude", "--jobs", "-j", "--refmap", "--filter",
             "--negotiation-tip", "--server-option", "-o"}
# r6fix 4: builtins that store a value into the variable they name (read, declare ...); `for NAME in` and `printf -v NAME` are handled in bad_targets
ENV_VALUE_CMDS = {"read", "declare", "typeset", "export", "local", "readonly", "mapfile", "readarray", "select", "getopts"}
# Subcommands whose arguments get the shell-expansion check (rules 3, 4 and R6, R7, R9, rule 11).
EXPAND_SUBS = {
    "filter-repo", "filter-branch", "update-ref", "gc", "prune", "reflog", "rebase", "restore", "checkout",
    "checkout-index", "read-tree", "apply", "reset", "switch", "clean", "update-index", "config",
} | WIDE_SUBS
GLOB_OK = {"restore", "checkout"} | WIDE_SUBS
CFG_READ = {
    "--get", "--get-all", "--get-regexp", "--get-urlmatch", "--get-color", "--get-colorbool", "-l", "--list",
    "--unset", "--unset-all", "--remove-section", "--rename-section", "--show-origin", "--show-scope",
}
CFG_VALUE_OPTS = {"-f", "--file", "--blob", "--type", "--default", "--comment"}
# R11: words that may stand before the command word of a segment (wrappers and shell flow keywords)
HEAD_SKIP = CMD_PREFIX | {"builtin", "!", "{", "do", "then", "else", "elif", "if", "while", "until"}
# R11: a function definition `name() {` / `name() (` / `function name {`; the opening bracket is group 1
FUNC_DEF = re.compile(r"(?:function\s+[^\s;&|(){}'\"]+\s*(?:\(\s*\))?|[A-Za-z_][\w:.+-]*\s*\(\s*\))\s*([{(])")


class Deny(Exception):
    """Raised to stop the check with a deny reason."""


def deny(msg, ok=False):
    """Abort the check with msg; ok=True marks a verdict an `# APPROVED` marker lifts (then the check goes on)."""
    if ok and APPROVED:
        return
    raise Deny(f"{msg} {TAIL if ok else STRICT_TAIL}")


class QuotedTok(str):
    """A token made only of quoted or backslash-escaped punctuation (`';'`, `\\|`): an argument, not a shell operator."""


def is_op(tok):
    """Return True when tok is a shell operator token (only ; & | ( ) < > newline characters, and not quoted)."""
    return bool(tok) and set(tok) <= PUNCT and not isinstance(tok, QuotedTok)


def tokenize(cmd):
    """Split a shell command into tokens, with ; & | ( ) < > and newline as separate tokens and comments uninterpreted.

    r6fix 1: quoted or escaped punctuation is an argument. A pre-pass swaps such characters for private-use stand-ins so
    shlex keeps them inside the word; afterwards a token left with only punctuation becomes a QuotedTok (is_op() is False).
    The quote states mirror shlex posix mode (no escapes inside '...', only \\" and \\\\ inside "...").
    """
    if any(0xE000 <= ord(c) < 0xE008 for c in cmd):
        raise ValueError("reserved character")
    out, q, i = [], "", 0
    while i < len(cmd):
        ch = cmd[i]
        if q:
            if ch == q:
                q = ""
            elif q == '"' and ch == "\\" and i + 1 < len(cmd) and cmd[i + 1] in '"\\':
                out.append(ch)
                i += 1
                ch = cmd[i]
            else:
                ch = QUOTE_MAP.get(ch, ch)
        elif ch == "\\" and i + 1 < len(cmd):
            i += 1
            ch = QUOTE_MAP[cmd[i]] if cmd[i] in QUOTE_MAP else "\\" + cmd[i]
        elif ch in "'\"":
            q = ch
        out.append(ch)
        i += 1
    lex = shlex.shlex("".join(out), posix=True, punctuation_chars=";&|()<>\n")
    lex.whitespace = " \t\r"
    lex.whitespace_split = True
    lex.commenters = ""
    toks = []
    for t in lex:
        back = t.translate(QUOTE_BACK)
        toks.append(QuotedTok(back) if back != t and back and set(back) <= PUNCT else back)
    return toks


def segments(tokens):
    """Group tokens into command segments; drop redirection operators, their targets and fd digits.

    Returns a list of (tokens, here-string targets). A 1-2 digit token right before a redirection operator is a file
    descriptor (`2>&1`) and is removed; longer digit tokens stay so an all-zero oid is never swallowed.
    """
    segs, cur, here, skip, is_here = [], [], [], False, False
    for t in tokens:
        if skip:
            skip = False
            if is_here:
                here.append(t)
        elif is_op(t):
            if set(t) & set("<>") and not t.endswith("("):  # `<(` / `>(` open a process substitution: no target to skip
                if cur and cur[-1].isdigit() and len(cur[-1]) <= 2:
                    cur.pop()
                skip, is_here = True, t == "<<<"
            else:
                if cur:
                    segs.append((cur, here))
                cur, here = [], []
        else:
            cur.append(t)
    if cur:
        segs.append((cur, here))
    return segs


def glob_op_paths(cmd):
    """Return True when a git restore/checkout piece (split at ; & | newline) holds a zsh glob operator glued into a word.

    The tokenizer cuts `a(.)` or `a<->` at the operators, so the path the check call sees (`a`) differs from what zsh
    expands. Words that start with an operator (`>f`, `2>&1`, `<(cmd)`) are redirections and a leading `$(`/`(` or trailing
    `)` is a subshell; any other unquoted parenthesis or angle bracket inside a word is a glob operator.
    """
    pieces, piece, raw, plain, q, i = [], [], [], [], "", 0

    def flush_word():
        """Close the current word into the current piece."""
        if raw:
            piece.append(("".join(raw), "".join(plain)))
        raw.clear()
        plain.clear()

    while i < len(cmd):
        ch = cmd[i]
        if q:
            if ch == q:
                q = ""
            elif ch == "\\" and q == '"' and i + 1 < len(cmd):
                i += 1
                raw.append("x")
                plain.append(cmd[i])
            else:
                raw.append("x")
                plain.append(ch)
        elif ch == "\\" and i + 1 < len(cmd):
            i += 1
            raw.append("x")
            plain.append(cmd[i])
        elif ch in "'\"":
            q = ch
        elif ch in " \t\r":
            flush_word()
        elif ch in ";&|\n":
            flush_word()
            pieces.append(piece[:])
            piece.clear()
        else:
            raw.append(ch)
            plain.append(ch)
        i += 1
    flush_word()
    pieces.append(piece)
    for words in pieces:
        names = [re.sub(r"^(\$?\(|`)+", "", p) for _, p in words]
        if not (any(is_git_tok(n) for n in names) and any(n in ("restore", "checkout") or cmd_base(n) in ("git-restore", "git-checkout") for n in names)):
            continue
        for n, (r, _) in enumerate(words):
            if re.search(r"<\d*-\d*>", r):
                return True
            # a bare leading `(` is a subshell only on the first word of the piece (`(git ...)`), elsewhere it opens a zsh group
            r = re.sub(r"^(\$\(|`)+", "", r)
            r = re.sub(r"^\(+", "", r) if n == 0 else r
            if not re.match(r"\d*[<>]", r) and re.search(r"[()<>]", r.rstrip(")")):
                return True
    return False


def has_git(text):
    """Return True when text mentions git, also when quotes or backslashes split the name (g"i"t or g-backslash-it)."""
    # backslash-newline is dropped by the shell before it splits words (2026-11-12: `gi\<newline>t push` was not seen as git)
    return bool(GIT_WORD.search(text) or GIT_WORD.search(re.sub(r"[\"'\\]", "", re.sub(r"\\\r?\n", "", text))))


def cmd_base(tok):
    """Return the command name of a word: path prefix dropped and zsh's leading `=` (`=git` = the path of git) removed."""
    return os.path.basename(tok).lstrip("=")


def is_git_tok(tok):
    """Return True for `git` or `git-<sub>` (any path prefix, also zsh `=git`)."""
    b = cmd_base(tok)
    return b == "git" or (b.startswith("git-") and len(b) > 4)


def bad_env(tok):
    """Return the variable name when tok is a NAME=value or NAME+=value assignment that matters to git, else None."""
    m = ASSIGN.fullmatch(tok)
    if not m:
        return None
    n, v = m.groups()
    if deny_name(n):
        return n
    if TRACE_NAME.fullmatch(n) and v not in TRACE_SAFE:
        return n
    if n in ENV_PAGER and v not in PAGER_SAFE:
        return n
    return None


def deny_name(n):
    """Return True when a variable called n matters to git whatever value it gets."""
    return n in ENV_DENY or n.startswith("GIT_TEST_") or bool(re.fullmatch(r"GIT_CONFIG_(KEY|VALUE)_\d+", n))


def env_lifted(n):
    """Return True when the marker lifts variable n: it only moves pathspec/index/object lookup or appends a trace file, no command or config."""
    return n in ENV_LIFT or bool(TRACE_NAME.fullmatch(n))


def bad_targets(seg):
    """r6fix 4: return a git-relevant variable name that the segment makes receive a value (`read`, `for NAME in`, `printf -v`, `declare` ...), else None.

    The value is unknown (it comes from stdin, a loop list or a format), so any name that bad_env() could reject with
    some value is rejected. `NAME=value` arguments are already judged by bad_env() on the token itself.
    """
    k = head_index(seg)
    if k >= len(seg):
        return None
    cmd, args = cmd_base(seg[k]), seg[k + 1:]
    if cmd == "for":
        names = args[:1]
    elif cmd == "printf":
        names = [a[2:] if len(a) > 2 else (args[j + 1] if j + 1 < len(args) else "") for j, a in enumerate(args) if a.startswith("-v")]
    elif cmd in ENV_VALUE_CMDS:
        names = [a for a in args if not a.startswith("-") and "=" not in a]  # NAME=value is bad_env()'s job
        names = names[1:2] if cmd == "getopts" else names
    else:
        return None
    for a in names:
        m = re.match(r"[A-Za-z_]\w*", a)
        if m and (deny_name(m[0]) or TRACE_NAME.fullmatch(m[0]) or m[0] in ENV_PAGER):
            return m[0]
    return None


def has_expansion(tok, glob=True):
    """Return True when tok holds shell expansion syntax ($ backtick braces, and globs unless glob=False); @{...} is fine."""
    t = re.sub(r"@\{[^{}$`]*\}", "", tok)
    return any(ch in t for ch in ("$`{}" + ("*?[" if glob else "")))


def long_hit(args, names):
    """Return True when an option before `--` is a (prefix) abbreviation of one of the long option names."""
    for a in args:
        if a == "--":
            break
        if a.startswith("--"):
            n = a[2:].partition("=")[0]
            if n and any(x.startswith(n) for x in names):
                return True
    return False


def short_hit(args, letters, stop=""):
    """Return True when a short option bundle before `--` contains one of the letters.

    A `stop` letter takes a value: the rest of the bundle is that value, and when the letter ends the bundle the next
    argument is (r6fix 5: `merge-file -L pn`, `clean -e -n`).
    """
    skip = False
    for a in args:
        if skip:
            skip = False
            continue
        if a == "--":
            break
        if a.startswith("-") and not a.startswith("--"):
            for idx, ch in enumerate(a[1:], 1):
                if ch in letters:
                    return True
                if ch in stop:
                    skip = idx == len(a) - 1
                    break
    return False


def check_config(val, label="git -c"):
    """Deny a config key=value whose key is outside the allow-list."""
    if "$" in val or "`" in val:
        deny(f"{label} {val} (변수 확장 — 검증 불가)")
    key, _, v = val.partition("=")
    parts = key.split(".")
    if len(parts) < 2:
        deny(f"{label} {key} (허용 목록 밖 — 프로그램 실행·설정 끌어오기 가능)")
    first, last = parts[0].lower(), parts[-1].lower()
    norm = ".".join([first, *parts[1:-1], last])
    if first in CFG_SECTIONS or norm in CFG_ALLOW:
        return
    if norm == "core.hookspath" and v.removesuffix("/") in HOOK_PATHS:
        return
    deny(f"{label} {key} (허용 목록 밖 — 프로그램 실행·설정 끌어오기 가능)", ok=norm == "core.hookspath")  # hook path: lifted as before


def check_config_write(args):
    """Apply the -c allow-list to `git config` write forms (key+value, --add, --replace-all, `set`); reads pass."""
    if long_hit(args, ("edit", "remove-section")) or short_hit(args, "e"):
        deny("git config --edit/--remove-section (편집기 실행·섹션 영구 삭제)", ok=True)
    wide = long_hit(args, ("global", "system", "file", "blob")) or short_hit(args, "f")
    if wide and long_hit(args, ("unset-all",)):
        deny("git config --unset(-all) 를 --global/--system/--file 범위에 (사용자·시스템 설정 항목 삭제 — 되돌리려면 값을 알아야 함)", ok=True)
    if wide and long_hit(args, ("rename-section",)):
        deny("git config --rename-section 을 --global/--system/--file 범위에 (사용자·시스템 설정 섹션 이름 바꿈 — 옛 키가 사라짐)", ok=True)
    pos, read, add, k = [], False, False, 0
    while k < len(args):
        a = args[k]
        k += 1
        if a == "--":
            pos += args[k:]
            break
        if a.startswith("-"):
            name = a.partition("=")[0]
            read = read or name in CFG_READ
            add = add or name in ("--add", "--replace-all")
            if name in CFG_VALUE_OPTS and "=" not in a:
                k += 1
        else:
            pos.append(a)
    if pos[:1] in (["edit"], ["remove-section"]):
        deny("git config edit/remove-section (편집기 실행·섹션 영구 삭제)", ok=True)
    if wide and pos[:1] == ["unset"]:
        deny("git config unset 을 --global/--system/--file 범위에 (사용자·시스템 설정 항목 삭제)", ok=True)
    if wide and pos[:1] == ["rename-section"]:
        deny("git config rename-section 을 --global/--system/--file 범위에 (사용자·시스템 설정 섹션 이름 바꿈)", ok=True)
    if read:
        return
    if pos[:1] == ["set"]:
        pos = pos[1:]
        add = True
    elif pos[:1] and pos[0] in ("get", "list", "unset", "rename-section"):
        return
    if (add and pos) or len(pos) >= 2:
        check_config(f"{pos[0]}={pos[1] if len(pos) > 1 else ''}", "git config")


def parse_args(args, short_val):
    """Split restore/checkout args into (options, positionals before `--`, args after `--`, saw `--`)."""
    opts, pos, post, dd, k = [], [], [], False, 0
    while k < len(args):
        a = args[k]
        k += 1
        if dd:
            post.append(a)
        elif a == "--":
            dd = True
        elif a.startswith("--"):
            name, eq, _ = a.partition("=")
            hits = [f for f in LONG_OPTS if f.startswith(name)] if len(name) >= 3 else []
            name = hits[0] if name not in LONG_OPTS and len(hits) == 1 else name
            opts.append(name)
            if name in LONG_VAL and not eq:
                k += 1
        elif a.startswith("-") and len(a) > 1:
            for idx, ch in enumerate(a[1:]):
                opts.append("-" + ch)
                if ch in short_val:
                    if idx == len(a) - 2:
                        k += 1
                    break
        else:
            pos.append(a)
    return opts, pos, post, dd


def git_env():
    """Return a scrubbed environment for the check calls."""
    env = {k: v for k, v in os.environ.items() if k not in ENV_DROP and not k.startswith("GIT_CONFIG_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0", GIT_ATTR_NOSYSTEM="1")
    return env


def run_git(base, popts, *args, stdin=None):
    """Run a read-only git check call with repo-config code execution neutralized; deny on failure or timeout."""
    cmd = ["git", "--no-pager", "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false",
           "-c", "core.hooksPath=/dev/null", "-C", base, *popts, *args]
    feed = {"stdin": subprocess.DEVNULL} if stdin is None else {"input": stdin}
    try:
        return subprocess.run(cmd, timeout=3, capture_output=True, check=False, env=git_env(), text=True,
                              errors="replace", **feed)
    except (OSError, subprocess.SubprocessError):
        deny("확인용 git 호출 실패 또는 3초 초과 — 변경 여부를 판정할 수 없어 차단", ok=True)


def changed_paths(base, popts, paths):
    """Return paths with uncommitted or diff-hidden changes; deny when git cannot tell or filters are configured."""
    # R10. Only repo-level scopes count: system/global config is the user's own (e.g. git-lfs), and HOME / GIT_CONFIG_GLOBAL
    # reassignment is already denied by rule 2. When a repo-level filter.* exists, diff may run its clean filter, but only
    # on files whose `filter` attribute is set, so deny just those paths. (Denying every path of such a repo would block
    # all restores in the harness repo itself, which has a local filter.nomodel.)
    r = run_git(base, popts, "config", "--show-scope", "--get-regexp", r"^filter\.")
    if r.returncode not in (0, 1):
        deny("확인용 git config 실패 — 필터 설정을 판정할 수 없어 차단", ok=True)
    if any(ln.split("\t")[0] not in ("system", "global") for ln in r.stdout.split("\n") if ln):
        files = run_git(base, popts, "ls-files", "-z", "--", *paths)
        attrs = run_git(base, popts, "check-attr", "-z", "--stdin", "filter", stdin=files.stdout)
        if files.returncode != 0 or attrs.returncode != 0:
            deny("확인용 git check-attr 실패 — 필터 적용 여부를 판정할 수 없어 차단", ok=True)
        fields = attrs.stdout.split("\0")
        if any(v not in ("unspecified", "unset") for v in fields[2::3] if v):
            deny("필터가 설정된 저장소의 필터 적용 파일 — 확인 호출이 필터를 실행할 수 있음", ok=True)
    names = []
    for extra in ([], ["--cached"]):
        if extra and run_git(base, popts, "rev-parse", "--verify", "--quiet", "HEAD").returncode != 0:
            continue
        r = run_git(base, popts, "diff", "--name-only", "--no-ext-diff", "--no-textconv", *extra, "--", *paths)
        if r.returncode != 0:
            deny("확인용 git diff 실패 — 변경 여부를 판정할 수 없어 차단", ok=True)
        names += [n for n in r.stdout.split("\n") if n]
    r = run_git(base, popts, "ls-files", "-v", "--", *paths)
    if r.returncode != 0:
        deny("확인용 git ls-files 실패 — 변경 여부를 판정할 수 없어 차단", ok=True)
    # lowercase tag = assume-unchanged, S = skip-worktree: diff cannot see edits to these files
    names += [ln[2:] for ln in r.stdout.split("\n") if len(ln) > 2 and (ln[0].islower() or ln[0] == "S")]
    return names


def is_commit(base, popts, arg):
    """Return True when arg resolves to a commit (an option-looking arg never does); deny on check failure."""
    if arg.startswith("-"):
        return False
    rc = run_git(base, popts, "rev-parse", "--verify", "--quiet", arg + "^{commit}").returncode
    if rc not in (0, 1):
        deny("확인용 git rev-parse 실패 — 인자 종류를 판정할 수 없어 차단", ok=True)
    return rc == 0


def resolve_base(ctx, cdirs, relocated):
    """Return the folder git will run in, or deny when it cannot be known."""
    if ctx["has_cd"]:
        deny("명령 안에 cd·chdir·pushd 가 있어 기준 폴더를 확정할 수 없음 — git -C <폴더> 형태로 쓰세요", ok=True)
    if relocated:
        deny("--git-dir·--work-tree 지정 — 확인 호출이 다른 저장소를 볼 수 있어 차단", ok=True)
    base = ctx["cwd"]
    for d in cdirs:
        if re.search(r"[$`]", d):
            deny("git -C 경로에 변수 확장 — 기준 폴더를 확정할 수 없음", ok=True)
        base = os.path.join(base, os.path.expanduser(d))
    return base


def check_restore_checkout(sub, args, cmdpos, ctx, cdirs, popts, relocated):
    """Deny restore/checkout of paths that have uncommitted changes (rule 4)."""
    opts, pos, post, dd = parse_args(args, "s" if sub == "restore" else "bB")
    switch = False
    if sub == "restore":
        if ("--staged" in opts or "-S" in opts) and not ("--worktree" in opts or "-W" in opts):
            return  # index only
        paths = pos + post
    else:
        switch = any(o in opts for o in ("-b", "-B", "-d", "--orphan", "--detach"))
        paths = post if (switch or dd) else pos  # without `--`, pos[0] may still be a tree-ish
    if ctx["glob_ops"]:  # r5fix 6: zsh expands `a(.)` / `<->` / `(a|b)` to other paths than the tokens we checked
        deny(f"git {sub} (경로 자리에 괄호·꺾쇠 glob 연산자 — zsh 가 펼친 경로를 확정할 수 없음)", ok=True)
    if "--patch" in opts or "-p" in opts or "--pathspec-from-file" in opts:
        deny(f"git {sub} -p/--patch/--pathspec-from-file (버릴 변경을 미리 확인할 수 없음)", ok=True)
    if not cmdpos and not (switch and not dd):
        deny(f"git {sub} (git 이 명령 자리에 있지 않아 경로를 확정할 수 없음)", ok=True)
    if not paths:
        return
    if any(re.search(r"[$`{}]", re.sub(r"@\{[^{}$`]*\}", "", p)) for p in paths):  # @{-1} / HEAD@{1} are revisions
        deny(f"git {sub} (경로에 $·백틱·{{}} — 확정할 수 없음)", ok=True)
    if any(p.startswith("~") for p in paths):  # the shell expands ~ after this check, the check call would see a literal ~
        deny(f"git {sub} (경로가 ~ 로 시작 — 셸이 펼친 경로를 확정할 수 없음)", ok=True)
    base = resolve_base(ctx, cdirs, relocated)
    if sub == "checkout" and not switch and not dd and is_commit(base, popts, paths[0]):
        paths = paths[1:]
        if not paths:
            return
    names = changed_paths(base, popts, paths)
    if names:
        deny(f"git {sub} {' '.join(paths)} (커밋 안 된 변경이 있는 경로 — 되돌릴 수 없음: {names[0]} 외 {len(names) - 1}개)", ok=True)


def check_ref_move(args, cmdpos, ctx, cdirs, popts, relocated):
    """Deny `update-ref <ref> <new>` that moves an existing ref to a commit that is not its descendant (R: drops commits)."""
    pos = [a for k, a in enumerate(args) if not a.startswith("-") and (k == 0 or args[k - 1] != "-m")]
    if len(pos) < 2:
        return
    if not cmdpos:  # r5fix 12: like restore/checkout, the folder git runs in is only known when git stands at a command position
        deny("git update-ref (git 이 명령 자리에 있지 않아 기준 폴더를 확정할 수 없음)", ok=True)
    base = resolve_base(ctx, cdirs, relocated)
    rc = run_git(base, popts, "rev-parse", "--verify", "--quiet", pos[0]).returncode
    if rc == 1:
        return  # new ref: nothing is overwritten
    if rc != 0 or run_git(base, popts, "merge-base", "--is-ancestor", pos[0], pos[1]).returncode != 0:
        deny(f"git update-ref {pos[0]} {pos[1]} (기존 ref 를 후손이 아닌 커밋으로 이동 — 커밋이 브랜치에서 빠질 수 있음)", ok=True)


def clone_configs(args):
    """Return the key=value strings given to `git clone -c` / `--config` (separate, `=` joined or glued; long-option prefixes too)."""
    out, k = [], 0
    while k < len(args):
        a = args[k]
        k += 1
        if a == "--":
            break
        if a.startswith("--"):
            name, eq, val = a.partition("=")
            if len(name) > 2 and "config".startswith(name[2:]):
                out.append(val if eq else (args[k] if k < len(args) else ""))
                k += 0 if eq else 1
        elif a.startswith("-") and len(a) > 1:
            for idx, ch in enumerate(a[1:], 2):
                if ch in "cbuoj":  # clone short options that take a value; the rest of the bundle (or the next arg) is it
                    glued = a[idx:]
                    if ch == "c":
                        out.append(glued or (args[k] if k < len(args) else ""))
                    k += 0 if glued else 1
                    break
    return out


def without_messages(args):
    """r6fix 7: return commit args without the values of -m/--message/-F/--file (free text that may hold `$` or backticks).

    The reuse options -c/-C/--reuse-message/--reedit-message are dropped too: their value is a commit (`-c $SHA`, an everyday
    form that the existing shell-hook tests keep open), and the value of a value-taking option cannot turn into an option.
    Everything after `--` is dropped as well (`git commit -F "$F" -- "$P"`: a pathspec cannot become an option).
    """
    out, k = [], 0
    while k < len(args):
        a = args[k]
        k += 1
        if a == "--":
            break  # pathspecs: they cannot turn into options, and commit has no path check to fool
        if a.startswith("--"):
            name, eq, _ = a.partition("=")
            if len(name) > 2 and any(f.startswith(name) for f in ("--message", "--file", "--reuse-message", "--reedit-message")):
                k += 0 if eq else 1
                continue
        elif a.startswith("-") and len(a) > 1:
            hit = next((idx for idx, ch in enumerate(a[1:], 2) if ch in "mFcC"), 0)  # the rest of the bundle, or the next arg, is the value
            if hit:
                k += 0 if a[hit:] else 1
                continue
        out.append(a)
    return out


def before_dd(args):
    """Return the arguments before a `--` separator (all of them when there is none)."""
    return args[:args.index("--")] if "--" in args else args


def fetch_prune_reason(args):
    """r5fix 7: return why `fetch` with prune would delete local branches/tags, or None.

    --prune-tags (-P) always; --prune (-p) with --tags/-t or with a refspec whose destination is not under refs/remotes/
    (the first positional is the remote and may hold a colon: git@host:repo). Plain `fetch --prune origin` stays open.
    r6fix 10: the value of an option such as `--depth 1` is skipped when looking for the remote and the refspecs.
    """
    pos, k = [], 0
    while k < len(args):
        a = args[k]
        k += 1
        if a == "--":
            pos += args[k:]
            break
        if a.startswith("-"):
            if "=" not in a and (a in FETCH_VAL or (a.startswith("--") and len(a) > 3 and any(v.startswith(a) for v in FETCH_VAL))):
                k += 1
        else:
            pos.append(a)
    names = [a[2:].partition("=")[0] for a in before_dd(args) if a.startswith("--")]
    if short_hit(args, "P") or any(len(n) >= 6 and "prune-tags".startswith(n) for n in names):
        return "--prune-tags (로컬 태그 삭제)"
    if not (short_hit(args, "p") or any(len(n) >= 3 and "prune".startswith(n) for n in names)):
        return None
    if short_hit(args, "t") or long_hit(args, ("tags",)):
        return "--prune 과 --tags (원격에 없는 로컬 태그 삭제)"
    for r in pos[1:]:
        dst = r.lstrip("+").partition(":")[2]
        if dst and not dst.startswith(("refs/remotes/", "remotes/")):
            return f"--prune 과 로컬 ref 를 대상으로 하는 refspec {r} (로컬 브랜치·태그 삭제)"
    return None


def check_shell_rules(sub, args):
    """r5fix 10: the shell-hook rules (push/pull/stash/commit hook skip/forced switch/whole-tree restore) judged here too.

    The same verdict as git-guardrails.sh, so that `git-<sub>` executables and `=git` (which its regexes cannot see) get it.
    """
    if sub in ("push", "pull", "send-pack", "http-push"):
        deny(f"git {sub} (push/pull은 항상 사용자 직접 — agent-routing.md)")
    elif sub == "stash" and args[:1] not in (["list"], ["show"]):
        deny("git stash (작업트리 변경을 치우거나 덮어씀 — 조회는 list·show)", ok=True)
    elif sub == "commit" and any(a.startswith("--no-v") or re.fullmatch(r"-[aeinopqsvz]*n[a-zA-Z0-9]*", a) for a in before_dd(args)):
        deny("git commit --no-verify/-n (pre-commit·commit-msg 게이트 전면 우회)", ok=True)
    elif sub in ("checkout", "switch") and (short_hit(args, "f") or long_hit(args, ("force", "discard-changes"))):
        deny(f"git {sub} -f/--force/--discard-changes (로컬 수정 폐기 강제 전환)", ok=True)
    elif sub in ("restore", "checkout") and any(a in (".", "./", ":/") for a in args):
        deny(f"git {sub} . (작업트리 전체 폐기 — 경로 지정 복구는 허용)", ok=True)
    elif sub in ("remote", "subtree", "lfs") and ("push" in args or (sub == "lfs" and "pre-push" in args)):  # lfs: 2026-11-12 security
        deny(f"git {sub} … push (push 우회 — push/pull은 항상 사용자 직접)")
    elif sub in ("lfs", "subtree") and "pull" in args:  # 2026-11-12: same rank as git pull
        deny(f"git {sub} … pull (pull 우회 — push/pull은 항상 사용자 직접)")
    elif sub == "svn" and {"fetch", "rebase"} & set(args):  # pulls from the SVN server
        deny("git svn fetch/rebase (SVN 서버에서 받아옴 — push/pull은 항상 사용자 직접)")
    elif sub == "svn" and {"dcommit", "set-tree", "commit-diff", "branch", "tag"} & set(args):  # writes to the SVN server (2026-11-12 security)
        deny("git svn dcommit/set-tree/commit-diff/branch/tag (SVN 서버로 올려 보냄 — push/pull은 항상 사용자 직접)")


def check_wide(sub, args):
    """Spec r5 C: deny the forms of rule 11 (D discards work, R erases refs/objects/config, X runs a chosen program)."""
    pos = [a for k, a in enumerate(args) if not a.startswith("-") and (k == 0 or args[k - 1] not in VAL_OPTS)]
    act = pos[0] if pos else ""
    force = short_hit(args, "f") or long_hit(args, ("force",))
    if sub in ACT_SUBS and any(c in act for c in "*?["):  # r5fix 9: `git remote re*` can become `git remote remove`
        deny(f"git {sub} {act} (동작어 자리의 glob — 셸이 다른 낱말로 펼칠 수 있음)")
    if sub == "clone":  # clone -c / --config takes key=value like `git -c`: same allow-list
        for v in clone_configs(args):
            check_config(v, "git clone -c")
    if long_hit(args, ("output",)):  # own test: inside the elif chain a lifted --output would hide the program rows below
        deny(f"git {sub} --output (기존 파일 덮어쓰기)", ok=True)
    if long_hit(args, ("upload-pack", "receive-pack", "exec")) or (sub == "clone" and short_hit(args, "u")):
        deny(f"git {sub} --upload-pack/--receive-pack/--exec (git 이 지정한 프로그램을 실행)")
    elif sub in PROG_SUBS:
        deny(f"git {sub} (서버·메일·브라우저 등 지정한 프로그램을 실행 — --httpd·--to-cmd·--browser)")
    elif sub in ("init", "clone") and long_hit(args, ("template",)):
        deny(f"git {sub} --template (템플릿 폴더의 훅이 복사됨)", ok=True)
    elif sub in ("merge", "cherry-pick", "revert", "am") and long_hit(args, ("quit",)):
        deny(f"git {sub} --quit (진행 중 작업 상태 삭제 — --abort 만 통과)", ok=True)
    elif sub in ("cherry-pick", "revert", "am") and long_hit(args, ("skip",)):
        deny(f"git {sub} --skip (진행 중인 항목을 버리고 넘어감 — 작업 상태가 바뀜, --abort 만 통과)", ok=True)
    elif sub in ("checkout", "restore") and long_hit(args, ("ours", "theirs")):
        deny(f"git {sub} --ours/--theirs (충돌 파일을 한쪽 버전으로 덮어씀 — 해결 중인 변경이 사라짐)", ok=True)
    elif sub in ("rm", "mv") and force:
        deny(f"git {sub} -f/--force (수정된 파일 삭제·대상 덮어쓰기)", ok=True)
    elif sub == "worktree" and ((act in ("remove", "move") and force) or act == "prune" or (act == "add" and short_hit(args, "B"))):
        deny("git worktree remove/move --force·prune·add -B (변경 있는 worktree 삭제·기록 삭제·기존 브랜치 강제 이동)", ok=True)
    elif sub == "submodule" and (act == "foreach" or (act in ("deinit", "update") and force)):
        deny("git submodule foreach·deinit/update --force (문자열 인자 실행·서브모듈 변경 폐기)", ok=act != "foreach")
    elif sub == "sparse-checkout" and act not in ("", "list", "check-rules"):
        deny("git sparse-checkout (skip-worktree 로 추적 파일을 숨기거나 지움 — list 만 통과)", ok=True)
    elif sub == "archive" and short_hit(args, "o"):
        deny("git archive -o (기존 파일 덮어쓰기)", ok=True)
    elif sub == "tag" and (short_hit(args, "df", stop="mFu") or long_hit(args, ("delete", "force"))):
        deny("git tag -d/-f (태그 삭제·이동)", ok=True)
    elif sub == "branch" and (short_hit(args, "fDMC") or long_hit(args, ("force",))):
        deny("git branch -f/-D/-M/-C (브랜치 강제 삭제·이동 — -d/-m 만 통과)", ok=True)
    elif sub == "symbolic-ref" and (short_hit(args, "d") or long_hit(args, ("delete",)) or len(pos) >= 2):
        deny("git symbolic-ref 쓰기/-d (HEAD 를 옮기거나 지움 — 작업 트리와 어긋남)", ok=True)
    elif sub == "notes" and (act in ("remove", "prune", "edit") or force):  # act skips the value of --ref
        deny("git notes remove/prune/edit/--force (노트 삭제·편집기 실행)", ok=True)
    elif sub == "replace" and args and not (short_hit(args, "l") or long_hit(args, ("list",))):
        deny("git replace (객체 대체 — 이력 재작성에 준함, list 만 통과)", ok=True)
    elif sub == "remote" and act in ("remove", "rm"):
        deny("git remote remove (원격 설정과 추적 ref 삭제)", ok=True)
    elif sub in ("fetch", "pull") and (force or any(a.startswith("+") for a in args)):
        deny(f"git {sub} --force/+refspec (로컬 ref·태그 강제 덮어쓰기)", ok=sub == "fetch")
    elif sub == "repack" and short_hit(args, "d"):
        deny("git repack -d (팩 삭제 — 도달 불가 객체도 함께 사라짐)", ok=True)
    elif sub == "maintenance" and act not in ("", "run"):
        deny("git maintenance (run 이외 — 스케줄러 등록·해제)", ok=True)
    elif sub == "fast-import" and force:
        deny("git fast-import --force (브랜치 ref 덮어쓰기)", ok=True)
    elif sub == "bisect" and act == "run":
        deny("git bisect run (스크립트 실행)")
    elif sub in ("difftool", "mergetool"):
        deny(f"git {sub} (외부 도구 실행)", ok=not (short_hit(args, "x") or long_hit(args, ("extcmd",))))  # -x/--extcmd: a command string
    elif sub == "grep" and (short_hit(args, "O", stop="efABCm") or long_hit(args, ("open-files-in-pager",))):
        deny("git grep -O/--open-files-in-pager (페이저 프로그램 실행)")
    elif sub == "fetch" and fetch_prune_reason(args):
        deny(f"git fetch {fetch_prune_reason(args)}", ok=True)
    elif sub == "merge-file" and not (short_hit(args, "p", stop="L") or long_hit(args, ("stdout",))):
        deny("git merge-file -p/--stdout 없이 (첫 파일을 제자리에서 덮어씀)", ok=True)
    elif sub in ("fast-export", "fast-import") and long_hit(args, ("export-marks", "export-pack-edges")):
        deny(f"git {sub} --export-marks/--export-pack-edges (지정한 파일에 씀)", ok=True)
    elif sub == "index-pack" and short_hit(args, "o"):
        deny("git index-pack -o (지정한 파일에 씀)", ok=True)
    elif sub == "format-patch" and (short_hit(args, "o") or long_hit(args, ("output-directory",))):
        deny("git format-patch -o/--output-directory (지정한 폴더에 파일을 씀)", ok=True)
    elif sub == "bundle" and act == "create":
        deny("git bundle create (기존 파일 덮어쓰기)", ok=True)


def check_subcommand(sub, args, cmdpos, ctx, cdirs, popts, relocated):
    """Apply the wide deny (rule 11), the history-erasing rules (3), same-effect rules (R6, R7), config writes (R9), path rule (4)."""
    check_shell_rules(sub, args)
    check_wide(sub, args)
    if sub in ("filter-repo", "filter-branch"):
        deny(f"git {sub} (이력 전체 재작성)")  # shell filters / python callbacks (abbreviations too): never lifted
    elif sub == "update-ref" and (
        short_hit(args, "d", stop="m") or long_hit(args, ("stdin", "delete")) or any(re.fullmatch(r"0{4,}", a) for a in args)
    ):
        deny("git update-ref -d/--stdin/영 oid (ref 삭제 — --stdin 은 삭제 줄을 검증할 수 없음)", ok=True)
    elif sub == "update-ref" and not APPROVED:  # every verdict of the path/ref checks is lifted by the marker: skip their git calls
        check_ref_move(args, cmdpos, ctx, cdirs, popts, relocated)
    elif sub == "gc" and long_hit(args, ("prune",)):
        deny("git gc --prune (도달 불가 객체 영구 삭제)", ok=True)
    elif sub == "prune" and not any(a == "--dry-run" or re.fullmatch(r"-[a-z]*n[a-z]*", a) for a in args):
        deny("git prune (도달 불가 객체 영구 삭제 — -n/--dry-run 만 통과)", ok=True)
    elif sub == "reflog" and next((a for a in args if not a.startswith("-")), "") in ("expire", "delete"):
        deny("git reflog expire/delete (복구 단서 삭제)", ok=True)
    elif sub == "rebase" and args not in (["--abort"], ["--show-current-patch"]):  # --exec/-x runs commands: not lifted
        deny("git rebase (이력 재작성 — --abort·--show-current-patch 만 통과)", ok=not (long_hit(args, ("exec",)) or short_hit(args, "x")))
    elif sub == "checkout-index":
        deny("git checkout-index (작업 트리 덮어쓰기)", ok=True)
    elif sub == "read-tree" and (short_hit(args, "u") or long_hit(args, ("reset",))):
        deny("git read-tree -u/--reset (작업 트리 덮어쓰기)", ok=True)
    elif sub == "apply" and (long_hit(args, ("apply",)) or not any(a in ("--check", "--stat", "--numstat", "--summary") for a in before_dd(args))):
        deny("git apply (작업 트리를 바꿈, 되돌린 패치로 변경도 지움 — --check·--stat·--numstat·--summary 조회형만 통과)", ok=True)
    elif sub == "reset" and long_hit(args, ("hard", "merge", "keep")):
        deny("git reset --hard/--merge/--keep (색인·작업 트리 변경 폐기 — --soft·--mixed 만 통과)", ok=True)
    elif sub == "clean" and not (short_hit(args, "n", stop="e") or long_hit(args, ("dry-run",))):
        deny("git clean (추적 안 되는 파일 삭제 — -n/--dry-run 만 통과)", ok=True)
    elif sub == "switch" and (short_hit(args, "C") or long_hit(args, ("force", "discard-changes", "force-create"))):
        deny("git switch -C/--force/--discard-changes (브랜치 강제 이동·작업 트리 변경 폐기)", ok=True)
    elif sub == "update-index" and long_hit(
        args, ("assume-unchanged", "skip-worktree", "remove", "force-remove", "cacheinfo", "index-info", "replace")
    ):
        deny("git update-index --assume-unchanged/--skip-worktree/--remove/--force-remove/--cacheinfo/--index-info (변경을 숨기거나 색인 항목을 지우거나 바꿈)", ok=True)
    elif sub == "config":
        check_config_write(args)
    elif sub == "checkout" and (short_hit(args, "B") or long_hit(args, ("force",))):
        deny("git checkout -B/--force (브랜치 강제 이동·작업 트리 변경 폐기)", ok=True)
    elif sub in ("restore", "checkout") and not APPROVED:
        check_restore_checkout(sub, args, cmdpos, ctx, cdirs, popts, relocated)


def at_cmd(seg, i):
    """Return True when seg[i] stands at a command position (only assignments and wrapper words before it)."""
    return all(ASSIGN.fullmatch(t) or t in CMD_PREFIX for t in seg[:i])


def check_git(seg, i, ctx):
    """Judge the git invocation at seg[i]: global options, -c allow-list, environment, expansion, then the subcommand."""
    b = cmd_base(seg[i])
    cmdpos = at_cmd(seg, i)
    rest = seg[i + 1:]
    cfgs, cdirs, popts, relocated, k = [], [], [], False, 0
    if b == "git":
        while k < len(rest) and rest[k].startswith("-"):
            o = rest[k]
            k += 1
            name, eq, val = o.partition("=")
            long_ = o.startswith("--")
            if long_ and name == "--config-env":
                deny("git --config-env (값이 환경 변수에 있어 검증할 수 없음)")
            if long_ and name == "--exec-path" and eq:
                deny("git --exec-path=<값> (다른 위치의 git-* 실행 파일을 돌리게 됨)")  # like GIT_EXEC_PATH: the subcommand name no longer fixes what runs
            if o in ("-c", "-C") or (long_ and name in VALUE_LONG):
                if long_ and eq:
                    v = val
                elif k < len(rest):
                    v = rest[k]
                    k += 1
                else:
                    break
                if o == "-c":
                    cfgs.append(v)
                elif o == "-C":
                    cdirs.append(v)
                elif name in ("--git-dir", "--work-tree"):
                    relocated = True
            elif not long_ and o.startswith("-c"):
                cfgs.append(o[2:])
            elif name in PATHSPEC_OPTS:
                popts.append(name)
        sub, args = (rest[k], rest[k + 1:]) if k < len(rest) else (None, [])
    else:
        sub, args = b[4:], rest
    if ctx["env_bad"]:
        deny(f"git 실행 환경 변수 {ctx['env_bad']} (-c 와 같은 효과 — 프로그램 실행·설정 끌어오기 가능)", ok=env_lifted(ctx["env_bad"]))
    if any(re.match(r"(?:[^\s=]*=)?ext::", t) for t in rest):
        deny("git 인자의 ext:: 전송 (임의 명령 실행)")
    for t in rest[:k]:
        if has_expansion(t):
            deny(f"git {t} (전역 옵션의 셸 확장 — 검증 불가)")
    for c in cfgs:
        check_config(c)
    if not sub:
        return
    if has_expansion(sub):
        deny(f"git {sub} (하위명령의 셸 확장 — 검증 불가)")
    if sub in EXPAND_SUBS:
        path_sub, dd = sub in GLOB_OK, False
        for a in without_messages(args) if sub == "commit" else args:
            if a == "--":
                dd = True
            elif has_expansion(a, glob=not (path_sub and (dd or not a.startswith("-")))):
                deny(f"git {sub} {a} (셸 확장 — 검증 불가)", ok=sub not in ACT_SUBS)  # an action word could become foreach/push
    check_subcommand(sub, args, cmdpos, ctx, cdirs, popts, relocated)


def subst_bodies(tok):
    """Return the inner texts of `$(...)` and backtick substitutions in a token."""
    out = [tok[m.end():closing_index(tok, m.end(), "(", ")")] for m in re.finditer(r"\$\(", tok)]  # quote aware: `')'` stays inside
    return out + tok.split("`")[1::2]


def wrapper_payload(seg, i, long_cmd=False):
    """Return the command string a `-c`-style wrapper at seg[i] runs, or None."""
    for j in range(i + 1, len(seg)):
        t = seg[j]
        if SHC.fullmatch(t) and j + 1 < len(seg):
            return seg[j + 1]
        if long_cmd and t == "--command" and j + 1 < len(seg):
            return seg[j + 1]
        if long_cmd and t.startswith("--command="):
            return t.partition("=")[2]
    return None


def env_split_payload(seg, i):
    """Return the string given to `env -S` / `--split-string`, or None."""
    for j in range(i + 1, len(seg)):
        t = seg[j]
        if t in ("-S", "--split-string") and j + 1 < len(seg):
            return seg[j + 1]
        if t.startswith("--split-string="):
            return t.partition("=")[2]
        if t.startswith("-S") and len(t) > 2:
            return t[2:]
    return None


def head_index(seg):
    """Return the index of the command word in seg, skipping assignments, wrapper words, flow keywords and wrapper options."""
    k, wrapped = 0, False
    while k < len(seg):
        t = seg[k]
        if ASSIGN.fullmatch(t) or t in HEAD_SKIP:
            wrapped = wrapped or t in CMD_PREFIX
        elif not (wrapped and t.startswith("-")):
            break
        k += 1
    return k


def check_indirection(seg, git_seen):
    """R11: deny a segment that hides git behind an alias, hash entry or variable/backtick command word."""
    k = head_index(seg)
    if k >= len(seg):
        return
    head, args = seg[k], seg[k + 1:]
    what = "셸 별칭·변수·함수로 git 을 감쌈 — 검증 불가"
    # wrappers take option values (`sudo -u root $G tag`), so the command word is not found by skipping dashes alone:
    # a $ or backtick word between a wrapper and the first git word may be the command
    w = next((j for j, t in enumerate(seg) if cmd_base(t) in WRAPPERS), None)
    if git_seen and w is not None:
        for t in seg[w + 1:]:
            if is_git_tok(t):
                break
            if re.match(r"[$`]", t):
                deny(f"{t} (래퍼 뒤의 변수·백틱 — {what})")
    if git_seen and re.search(r"[$`]", head):
        deny(f"{head} (명령 자리의 변수·백틱 — {what})")
    name = cmd_base(head)
    if name == "alias" and any(has_git(a) for a in args):
        deny(f"alias 정의에 git ({what})")
    if name == "hash" and (
        any("=" in a and has_git(a.partition("=")[2]) for a in args)
        or any(a == "-p" and j + 1 < len(args) and has_git(args[j + 1]) for j, a in enumerate(args))
    ):
        deny(f"hash 로 git 경로 등록 ({what})")


def closing_index(text, k, opener, closer):
    """Return the index of the bracket closing the one opened just before text[k], skipping quoted text; len(text) if none."""
    depth, q = 1, ""
    while k < len(text):
        ch = text[k]
        if q:
            if ch == "\\" and q == '"':
                k += 1
            elif ch == q:
                q = ""
        elif ch == "\\":
            k += 1
        elif ch in "'\"":
            q = ch
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return k
        k += 1
    return len(text)


def check_functions(cmd):
    """R11: deny a function definition (outside quotes) whose body mentions git; arguments passed from outside are unknowable."""
    q, i = "", 0
    while i < len(cmd):
        ch = cmd[i]
        if q:
            if ch == "\\" and q == '"':
                i += 1
            elif ch == q:
                q = ""
        elif ch == "\\":
            i += 1
        elif ch in "'\"":
            q = ch
        elif i == 0 or cmd[i - 1] in " \t\n;&|(){":
            m = FUNC_DEF.match(cmd, i)
            if m:
                opener = m.group(1)
                end = closing_index(cmd, m.end(), opener, "}" if opener == "{" else ")")
                if has_git(cmd[m.end():end]):
                    deny("함수 정의 본문에 git (셸 별칭·변수·함수로 git 을 감쌈 — 검증 불가)")
        i += 1


def analyze(cmd, depth, ctx):
    """Tokenize cmd and check every git invocation in it, recursing into shell-carried command strings."""
    if depth > MAX_DEPTH:
        if has_git(cmd):
            deny("셸 페이로드 중첩이 깊어 해석을 멈춤")
        return
    ctx = {**ctx, "git": ctx["git"] or has_git(cmd)}
    if re.search(r"\\\r?\n", cmd) and has_git(cmd):
        deny("줄 이음(백슬래시+개행) — 검증 불가")
    check_functions(cmd)
    try:
        toks = tokenize(cmd)
    except ValueError:
        if has_git(cmd):
            deny(HEREDOC_MSG if "<<" in cmd else "따옴표 해석 실패 — 명령을 판정할 수 없어 차단")
        return
    if ctx["git"] and any(is_op(t) and "<<" in t.replace("<<<", "") for t in toks):
        deny(HEREDOC_MSG)
    if "`" in cmd:  # an unquoted backtick substitution is glued to its neighbours by shlex: judge a copy where it separates commands
        analyze(cmd.replace("`", ";"), depth, ctx)
    segs = segments(toks)
    ctx = {
        **ctx,
        # cd inside a quoted payload (`eval 'cd sub'`) also moves the shell, so look at the raw text too
        "has_cd": ctx["has_cd"] or any(t in ("cd", "chdir", "pushd") for t in toks) or bool(CD_WORD.search(cmd)),
        # a name the marker cannot lift comes first, so a liftable one never hides it (2026-11-12)
        "env_bad": next(iter(sorted((n for n in (ctx["env_bad"], *map(bad_env, toks), *(bad_targets(s) for s, _ in segs)) if n), key=env_lifted)), None),
        "glob_ops": ctx["glob_ops"] or glob_op_paths(cmd),
    }
    for seg, here in segs:
        check_indirection(seg, ctx["git"])
        if any(cmd_base(t) in STREAM_SHELLS for t in seg):
            for s in here:
                analyze(s, depth + 1, ctx)
        for i, t in enumerate(seg):
            b = cmd_base(t)
            payloads = []
            if ("$(" in t or "`" in t) and has_git(t):
                payloads += subst_bodies(t)
            if b in SHELLS or b in ("su", "flock", "script"):
                payloads.append(wrapper_payload(seg, i, long_cmd=b not in SHELLS))
            elif b == "env":
                payloads.append(env_split_payload(seg, i))
            elif b == "eval":
                payloads.append(" ".join(seg[i + 1:]))
            elif b == "watch":
                payloads.append(" ".join(a for a in seg[i + 1:] if not a.startswith("-")))
            elif b == "tmux":
                # any tmux subcommand can carry a command string (run-shell, if-shell, send-keys, new-window ...)
                targs = [a for a in seg[i + 1:] if not a.startswith("-")][1:]
                payloads += targs + [" ".join(targs)]
            for p in payloads:
                if p:
                    analyze(p, depth + 1, ctx)
            if is_git_tok(t):
                check_git(seg, i, ctx)


def main():
    """Read the hook JSON, print a deny line when the command is blocked, always return 0."""
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    cmd = ((data.get("tool_input") or {}).get("command") or "") if isinstance(data, dict) else ""
    if not isinstance(cmd, str) or not cmd:
        return 0
    cwd = data.get("cwd") or os.getcwd()
    try:
        analyze(cmd, 0, {"cwd": cwd, "has_cd": False, "env_bad": None, "git": False, "glob_ops": False})
        return 0
    except Deny as e:
        reason = str(e)
    except Exception as e:  # noqa: BLE001 - fail closed: a git command we could not judge is denied
        if not has_git(cmd):
            return 0
        reason = f"확장 검사 판정 실패({type(e).__name__}) {STRICT_TAIL}"
    out = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                  "permissionDecisionReason": f"[git 차단] {reason}"}}
    print(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
