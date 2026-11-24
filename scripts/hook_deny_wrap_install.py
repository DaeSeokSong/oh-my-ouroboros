"""Wrap deny-capable PreToolUse command hooks in settings.json with scripts/hook-deny-wrap.sh (dry-run · apply · revert).

intent/2026-11-24-harness-review-six-items.md 개정 1 W9. 감쌀 대상은 아래 TARGETS 에 명시적으로 둔다(훅 이름 ↔ 명령에 든 문자열).
대상 선정(2026-11-24, 각 훅 스크립트를 열어 확인): 거부를 내는 PreToolUse command 훅 11개(agent-prompt-gate.py 는 enforce
모드일 때 거부하므로 넣는다). train-launch-warn.sh 는 additionalContext 경고만, agent-spawn-log.sh pre · skill-usage-log.sh 는 기록만(exit 0 고정)이라
감싸지 않는다(NOT_WRAPPED). 목록에 없는 새 PreToolUse 훅은 감싸지 않고 «대상 목록에 없음» 으로 알린다.

감싸는 꼴(2차 F2 · 3차 B1): `<WRAP><이름> --; else set --; fi; "$@" <원래 명령>`. WRAP 는 «감싸는 스크립트가 일반 파일이고
  `--ping`(stdin 은 /dev/null)에 정해진 글 «hook-deny-wrap ok» 로 답하면 set -- bash <스크립트> <이름> --» 까지의 접두다.
  없음 · 빈 파일 · 셔뱅만 · 잘림 · 문법 오류 · 읽기 불가 · 폴더 · 끊어진 링크면 답이 없어 "$@" 가 빈 채로 원래 명령만 돈다
  (감싸지 않음). 2차의 bash -n 가드는 빈 파일과 끝줄이 잘린 파일을 통과시켜 원래 훅이 0회 돌았다(되돌리기에서는 알아본다).
  `a || b` 꼴은 쓰지 않는다: 감싼 쪽이 거부(exit 2)하면 원래 명령이 한 번 더 돈다. 원래 명령은 한 번만 싣는다.
  hook-deny-wrap 을 담았지만 알아보는 꼴이 아닌 명령(예: 1차 꼴)은 감싸지도 되돌리지도 않고 알린다(3차 N6).
  원래 명령 부분:
  단순 명령(글자가 [A-Za-z0-9_./$~ -] 뿐이고 '=' 없음): 그대로. 바깥 셸이 원래 명령을 따로 돌릴 때와 같은 낱말로 쪼갠다.
  그 밖(인라인 셸 조각): `sh -c '<원래 명령>'`(shlex.quote). Claude Code 는 command 문자열을 Linux 에서 `sh -c` 로
    돌린다(공식 훅 문서 «Exec form and shell form»). 그래서 bash -c 가 아니라 sh -c 로 감싸 해석기를 바꾸지 않는다
    (dash 의 echo 는 역슬래시를 해석하므로 bash 로 바꾸면 결과가 달라질 수 있다).
쓰기: 파일 전체를 다시 직렬화하지 않고 바뀌는 command 문자열의 JSON 표기만 원문의 그 값 자리(오프셋)에서 바꾼다(들여쓰기 ·
  키 순서 · 한글 · 다른 칸의 바이트 유지, 같은 명령이 두 곳에 있어도 각 자리를 따로 바꾼다). 쓴 뒤 다시 읽어 «기대한 칸만
  바뀌었는가» 를 구조 비교하고 통과해야 os.replace 한다. --apply · --revert 는 바꾸기 전 원본 사본을 같은 폴더에 남긴다
  (W14 부터 이름 끝에 임의 글자가 붙고 모드 600).

개정 2 W14(상세 로그) 추가분:
  기록 전용 감싸기: TARGETS 가 아닌 나머지 command 훅(모든 이벤트, PreToolUse 의 경고 · 기록 훅 포함)을
    `<WRAP>--log-only <이름><MID><원래 명령>` 꼴로 감싼다. 이름 = 명령에 든 첫 scripts/<이름>.sh|.py, 없으면 inline.
    원래 명령 부분은 위와 같다(단순 명령 그대로 · 그 밖은 sh -c). 단 «단순 명령 || true» 는 `<단순 명령> || true` 로 둔다:
    감싸는 쪽이 진짜 종료 코드를 기록하고 바깥 || true 가 원래처럼 0 을 낸다. 위치 인자 · $PPID 를 쓰는 명령(RISKY)은
    감싸면 값이 바뀌므로 감싸지 않고 알린다. usage-log.sh 를 부르는 명령은 감싸지 않는다(자기 실행 줄을 스스로 쓴다).
  기록 훅 추가: USAGE_EVENTS 의 각 이벤트에 matcher 없는 항목 {"hooks": [usage-log.sh 명령]} 을 끝에 더한다(이미 있으면 그대로).
    --events 로 고른 이벤트만 더하거나 뺀다(기본 전부, 이 판의 Claude Code 가 모르는 이벤트 이름이 설정 전체를 무효로 만들 수
    있어 나눠 적용한다). 추가는 그 이벤트 배열의 마지막 항목 뒤(이벤트가 없으면 hooks 의 마지막 이벤트 뒤)에 «,\\n + 들여쓴
    항목» 글을 끼우고, 빼기는 정확히 그 글을 지운다(앞 항목 끝 ~ 이 항목 끝). 그래서 더한 뒤 빼면 원래 바이트로 돌아온다.
    우리 항목과 다른 훅이 한 항목에 섞였거나 우리 항목이 둘 이상이면 빼지 않고 알린다. 앞쪽 이벤트가 연달아 우리 항목뿐이면
    첫 남는 이벤트 앞까지 한 구간으로 지운다. hooks 의 모든 이벤트가 우리 항목뿐이면 빼지 않고 알린다.
  --events 는 기록 훅 항목에만 적용된다. --apply 의 기록 전용 감싸기는 이벤트와 무관하게 전부 한다. --revert --events X 는
    X 의 기록 훅 항목만 빼고 감싼 명령은 그대로 둔다. --revert(이벤트 없이)는 W14 분(기록 전용 감싸기 · 기록 훅 항목) 전부를
    되돌린다. W9 의 차단 훅 감싸기까지 되돌리려면 --revert-all(--events 를 주면 --revert --events 와 같다).
  settings.json 이 심볼릭 링크이면 실제 경로로 풀어 그 파일을 원자적으로 바꾼다(풀 수 없으면 중단). 쓰기 직전에 파일 내용의
    sha256 이 읽은 때와 다르면 중단하고 다시 실행하라고 알린다. 원본 사본은 처음부터 모드 600 이다(mkstemp).

Run: uv run --no-project python scripts/hook_deny_wrap_install.py [--dry-run|--apply|--revert|--revert-all]
       [--events E1,E2,…] [--settings PATH]
"""
import argparse
import copy
import hashlib
import json
import os
import re
import shlex
import sys
import tempfile
import time
from pathlib import Path

WRAP = ('HDW_SH=$HOME/.claude/scripts/hook-deny-wrap.sh; if [ -f "$HDW_SH" ] && '
        '[ "$(bash "$HDW_SH" --ping </dev/null 2>/dev/null)" = "hook-deny-wrap ok" ]; then set -- bash "$HDW_SH" ')
# NEVER: 새로 감쌀 때 쓰지 않는다(2차 꼴 bash -n 가드, 되돌리기 · 멱등 판정에서만 알아본다).
WRAP_V2 = ('HDW_SH=$HOME/.claude/scripts/hook-deny-wrap.sh; if [ -f "$HDW_SH" ] && bash -n "$HDW_SH" 2>/dev/null; '
           'then set -- bash "$HDW_SH" ')
MID = ' --; else set --; fi; "$@" '
TARGETS = [
    ("agent-type-gate", "scripts/agent-type-gate.py"),
    ("agent-prompt-gate", "scripts/agent-prompt-gate.py"),
    ("sensitive-file", "민감 파일 보호"),
    ("scope-gate", "scripts/scope-gate.sh"),
    ("bash-write-check", "scripts/bash-write-check.sh"),
    ("git-guardrails", "scripts/git-guardrails.sh"),
    ("external-model-gate", "scripts/external-model-gate.py"),
    ("read-once", "scripts/read-once.sh"),
    ("korean-style-gate", "scripts/korean-style-gate.sh"),
    ("skeleton-gate", "scripts/skeleton-gate.sh"),
    ("plan-confirm-gate", "scripts/plan-confirm-gate.py"),
]
NOT_WRAPPED = {
    "scripts/train-launch-warn.sh": "경고(additionalContext)만 내고 거부하지 않음",
    "scripts/agent-spawn-log.sh": "기록만 하고 exit 0 고정",
    "scripts/skill-usage-log.sh": "기록만 하고 출력 없이 exit 0",
}
SIMPLE = re.compile(r"[A-Za-z0-9_./$~ -]+")
LOG = "--log-only "
OR_TRUE = " || true"
USAGE_SCRIPT = "scripts/usage-log.sh"
USAGE_CMD = "bash $HOME/.claude/scripts/usage-log.sh"
USAGE_TIMEOUT = 10
# REF: event names and input fields — https://code.claude.com/docs/en/hooks (main 2026-11-24) and the hook_event_name strings of
# the local Claude Code 2.1.323 binary (2026-11-24), which contain all eight.
USAGE_EVENTS = ("PostToolUse", "PostToolUseFailure", "InstructionsLoaded", "SubagentStop", "SessionStart", "SessionEnd",
                "PreCompact", "PostCompact")
# WHY: WRAP above runs `set -- bash <wrapper> …` first (W9 3차 B1), so a simple command would see "$1"="bash", and a sh -c command
# would see scripts/hook-deny-wrap.sh as $PPID.
RISKY = re.compile(r"\$\{?(?:PPID\b|[0-9@*#])")
SCRIPT_NAME = re.compile(r"scripts/([A-Za-z0-9_.-]+?)\.(?:sh|py)\b")


def wrap(name: str, cmd: str, log: bool = False) -> str:
    keep = SIMPLE.fullmatch(cmd) or (log and cmd.endswith(OR_TRUE) and SIMPLE.fullmatch(cmd[:-len(OR_TRUE)]))
    inner = cmd if keep else "sh -c " + shlex.quote(cmd)
    return f"{WRAP}{LOG if log else ''}{name}{MID}{inner}"


def log_only(cmd: str) -> bool:
    return cmd.startswith(WRAP + LOG)


def unwrap(cmd: str) -> str | None:
    prefix = next((p for p in (WRAP, WRAP_V2) if cmd.startswith(p)), None)
    if prefix is None:
        return None
    body = cmd[len(prefix):]
    log = prefix == WRAP and body.startswith(LOG)
    name, sep, rest = body[len(LOG) if log else 0:].partition(MID)
    if not sep or not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
        return None
    if rest.startswith("sh -c "):
        try:
            toks = shlex.split(rest)
        except ValueError:
            toks = []
        if len(toks) == 3 and wrap(name, toks[2], log)[len(WRAP):] == body:
            return toks[2]
    return rest


def target_of(cmd: str) -> list[str]:
    return [n for n, key in TARGETS if key in cmd]


def plan(data: dict, mode: str, revert_all: bool = False) -> tuple[list[tuple], list[str]]:
    changes, notes = [], []
    for ev, entries in data.get("hooks", {}).items():
        for i, entry in enumerate(entries if isinstance(entries, list) else []):
            matcher = entry.get("matcher", "") if isinstance(entry, dict) else ""
            hooks = entry.get("hooks", []) if isinstance(entry, dict) else []
            for j, h in enumerate(hooks if isinstance(hooks, list) else []):
                cmd = h.get("command") if isinstance(h, dict) else None
                at = f"{ev} matcher={matcher}"
                if not isinstance(h, dict) or h.get("type") != "command" or not isinstance(cmd, str):
                    notes.append(f"건너뜀(command 훅 아님): {at} [{i}][{j}]")
                    continue
                if USAGE_SCRIPT in cmd:
                    continue
                orig = unwrap(cmd)
                if orig is None and "hook-deny-wrap" in cmd:
                    notes.append(f"건너뜀(hook-deny-wrap 을 담았지만 알아보는 꼴이 아님, 손으로 확인): {at} {cmd}")
                    continue
                if mode == "revert":
                    if orig is not None and (revert_all or log_only(cmd)):
                        changes.append(((ev, i, j), matcher, cmd, orig))
                    continue
                if orig is not None:
                    notes.append(f"이미 감쌈: {at} {cmd}")
                    continue
                names = target_of(cmd) if ev == "PreToolUse" else []
                if len(names) == 1:
                    changes.append(((ev, i, j), matcher, cmd, wrap(names[0], cmd)))
                elif len(names) > 1:
                    notes.append(f"건너뜀(대상 여럿과 일치 {names}): {at} {cmd}")
                elif RISKY.search(cmd):
                    notes.append(f"감싸지 않음(위치 인자 · $PPID 를 써서 감싸면 값이 바뀜): {at} {cmd}")
                else:
                    m = SCRIPT_NAME.search(cmd)
                    changes.append(((ev, i, j), matcher, cmd, wrap(m.group(1) if m else "inline", cmd, log=True)))
    return changes, notes


def has_usage(data: dict, ev: str) -> bool:
    entries = data.get("hooks", {}).get(ev, [])
    return any(isinstance(h, dict) and h.get("command") == USAGE_CMD
               for e in (entries if isinstance(entries, list) else []) if isinstance(e, dict)
               for h in (e.get("hooks") if isinstance(e.get("hooks"), list) else []))


def edit_usage(data: dict, ops: list[tuple[str, str]]) -> None:
    hooks = data.setdefault("hooks", {})
    for op, ev in ops:
        if op == "add":
            hooks.setdefault(ev, []).append({"hooks": [{"type": "command", "command": USAGE_CMD, "timeout": USAGE_TIMEOUT}]})
            continue
        kept = []
        for e in hooks.get(ev, []):
            if isinstance(e, dict) and isinstance(e.get("hooks"), list):
                e["hooks"] = [h for h in e["hooks"] if not (isinstance(h, dict) and h.get("command") == USAGE_CMD)]
                if not e["hooks"]:
                    continue
            kept.append(e)
        if kept:
            hooks[ev] = kept
        else:
            del hooks[ev]


# WHY: settings.json has trailing spaces on 3 lines and two command strings that occur twice (toolcall-text-guard.sh in Stop ·
# SubagentStop, cost-snapshot.sh in PreCompact · SessionEnd; checked 2026-11-24), so neither re-serialising nor replacing a unique
# literal keeps the other bytes. Edits go to the exact offsets of each value instead.
def spans(s: str) -> dict[tuple, tuple[int, int, int]]:
    out = {}
    ws = re.compile(r"[ \t\n\r]*")
    scalar = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][-+]?\d+)?|true|false|null")

    def val(i: int, path: tuple, head: int | None) -> int:
        i = ws.match(s, i).end()
        start, c = i, s[i]
        if c in "{[":
            close, n = ("}" if c == "{" else "]"), 0
            i = ws.match(s, i + 1).end()
            while s[i] != close:
                if c == "{":
                    ks = i
                    key, i = json.decoder.scanstring(s, i + 1)
                    i = val(ws.match(s, i).end() + 1, (*path, key), ks)
                else:
                    i = val(i, (*path, n), None)
                    n += 1
                i = ws.match(s, i).end()
                if s[i] == ",":
                    i = ws.match(s, i + 1).end()
            i += 1
        elif c == '"':
            _, i = json.decoder.scanstring(s, i + 1)
        else:
            i = scalar.match(s, i).end()
        out[path] = (start if head is None else head, start, i)
        return i

    val(0, (), None)
    return out


def indent_at(raw: str, pos: int) -> str:
    lead = raw[raw.rfind("\n", 0, pos) + 1:pos]
    return lead if not lead.strip() else ""


def block(obj, ind: str) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False).replace("\n", "\n" + ind)


def edit_text(raw: str, data: dict, changes: list[tuple], ops: list[tuple[str, str]],
              notes: list[str]) -> tuple[str, list[tuple[str, str]]]:
    sp, edits, done = spans(raw), [], []
    for (ev, i, j), _, before, after in changes:
        _, s0, s1 = sp[("hooks", ev, i, "hooks", j, "command")]
        ascii_ = raw[s0:s1] != json.dumps(before, ensure_ascii=False)
        edits.append((s0, s1, json.dumps(after, ensure_ascii=ascii_)))
    hooks = data.get("hooks", {})
    keys = list(hooks)
    entry = {"hooks": [{"type": "command", "command": USAGE_CMD, "timeout": USAGE_TIMEOUT}]}
    gone = []
    for op, ev in ops:
        arr = hooks.get(ev)
        if op == "add" and isinstance(arr, list) and arr:
            _, s0, s1 = sp[("hooks", ev, len(arr) - 1)]
            edits.append((s1, s1, ",\n" + indent_at(raw, s0) + block(entry, indent_at(raw, s0))))
        elif op == "add" and ev not in hooks and keys:
            k0, _, s1 = sp[("hooks", keys[-1])]
            ind = indent_at(raw, k0)
            edits.append((s1, s1, f",\n{ind}{json.dumps(ev)}: {block([entry], ind)}"))
        elif op == "remove" and [e == entry for e in arr].count(True) == 1 and len(arr) > 1:
            k = arr.index(entry)
            if k > 0:
                edits.append((sp[("hooks", ev, k - 1)][2], sp[("hooks", ev, k)][2], ""))
            else:
                edits.append((sp[("hooks", ev, 0)][1], sp[("hooks", ev, 1)][1], ""))
        elif op == "remove" and arr == [entry]:
            gone.append(ev)
        else:
            notes.append(f"건너뜀(기록 훅 항목을 글로 {'더하' if op == 'add' else '빼'}지 못하는 꼴, 손으로 확인): {ev}")
            continue
        done.append((op, ev))
    # WHY: a leading member and the next one both removed gave overlapping spans (W14 review 2026-11-24); a leading run is cut
    # as one span up to the first kept member, each following member from the end of the member before it.
    if gone and set(gone) >= set(keys):
        notes.append("건너뜀(hooks 의 모든 이벤트가 우리 항목뿐이라 글로 빼지 못함, 손으로 확인): " + ",".join(gone))
        done = [d for d in done if d[1] not in gone]
    elif gone:
        lead = 0
        while keys[lead] in gone:
            lead += 1
        if lead:
            edits.append((sp[("hooks", keys[0])][0], sp[("hooks", keys[lead])][0], ""))
        edits += [(sp[("hooks", keys[p - 1])][2], sp[("hooks", keys[p])][2], "")
                  for p in range(lead + 1, len(keys)) if keys[p] in gone]
    for s0, s1, text in sorted(edits, reverse=True):
        raw = raw[:s0] + text + raw[s1:]
    return raw, done


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="바뀔 항목만 보인다(기본)")
    g.add_argument("--apply", action="store_true", help="감싼다")
    g.add_argument("--revert", action="store_true", help="W14 분(기록 전용 감싸기 · 기록 훅 항목)을 되돌린다")
    g.add_argument("--revert-all", action="store_true", help="W9 의 차단 훅 감싸기까지 모두 되돌린다")
    ap.add_argument("--events", help="기록 훅 항목(usage-log.sh)만 이 이벤트들(쉼표 구분)에 더하거나 뺀다. 기록 전용 감싸기는 "
                                     "--apply 때 이벤트와 무관하게 전부 하고, --revert 에 --events 를 주면 감싸기는 그대로 둔다. "
                                     "없으면 전부")
    ap.add_argument("--settings", default=str(Path.home() / ".claude/settings.json"))
    a = ap.parse_args()
    events = [e for e in (a.events or ",".join(USAGE_EVENTS)).split(",") if e]
    if not set(events) <= set(USAGE_EVENTS):
        ap.error(f"--events 는 {','.join(USAGE_EVENTS)} 가운데서 고른다")
    revert = a.revert or a.revert_all
    mode = "apply" if a.apply else "revert-all" if a.revert_all else "revert" if a.revert else "dry-run"
    given = Path(a.settings)
    real = os.path.realpath(given)
    if given.is_symlink() and not os.path.isfile(real):
        print(f"중단: {given} 는 풀 수 없는 링크다(아무것도 쓰지 않음).", file=sys.stderr)
        return 1
    # NEVER: replace a symlinked settings.json by a regular file; the real target is read and atomically replaced instead.
    path = Path(real)
    raw_b = path.read_bytes()
    raw = raw_b.decode("utf-8")
    data = json.loads(raw)
    done, notes = plan(data, "revert" if revert else "apply", a.revert_all)
    if revert and a.events is not None:
        done = []
    ops = [("remove" if revert else "add", ev) for ev in events if has_usage(data, ev) is revert]
    new_raw, ops = edit_text(raw, data, done, ops, notes)

    expected = copy.deepcopy(data)
    for (ev, i, j), _, _, after in done:
        expected["hooks"][ev][i]["hooks"][j]["command"] = after
    edit_usage(expected, ops)

    print(f"[{mode}] {given} — 바뀔 항목 {len(done) + len(ops)}개 (명령 {len(done)} · 기록 훅 항목 {len(ops)})")
    for (ev, i, j), matcher, before, after in done:
        print(f"- matcher: {matcher}  [{ev} {i}][hooks {j}]\n  전: {before}\n  후: {after}")
    for op, ev in ops:
        print(f"- {'더함' if op == 'add' else '뺌'}: {ev} 에 {USAGE_CMD}")
    for n in notes:
        print(f"* {n}")
    if mode == "dry-run" or not (done or ops):
        return 0

    if json.loads(new_raw) != expected:
        print("중단: 다시 읽은 JSON 이 기대한 변경과 다르다(아무것도 쓰지 않음).", file=sys.stderr)
        return 1
    st = path.stat()
    tag = "pre-hook-deny-wrap" if mode == "apply" else "pre-hook-deny-unwrap"
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    backup = None
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(new_raw.encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
        if json.loads(Path(tmp).read_bytes().decode("utf-8")) != expected:
            raise ValueError("임시 파일 재검증 실패")
        os.chmod(tmp, st.st_mode & 0o777)
        bfd, backup = tempfile.mkstemp(dir=path.parent, prefix=f"{path.name}.{tag}.{time.strftime('%Y%m%d-%H%M%S')}.")
        with os.fdopen(bfd, "wb") as f:
            f.write(raw_b)
        if hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(raw_b).digest():
            Path(tmp).unlink(missing_ok=True)
            Path(backup).unlink(missing_ok=True)
            print(f"중단: {given} 가 읽은 뒤 바뀌었다(아무것도 쓰지 않음). 다시 실행하십시오.", file=sys.stderr)
            return 1
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    print(f"썼다: {path} (사본 {backup})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
