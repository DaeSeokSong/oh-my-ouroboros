#!/usr/bin/env python3
# ruff: noqa: EXE001
"""Confluence 게시 직전 «사용자 승인» 검사 도구 (2026-10-06 사용자 결정 «결정3. 2)», 2026-10-07 개정 1: 증거를 AskUserQuestion 답으로).

■ 왜 필요한가
`skills/confluence/SKILL.md` §3 은 기존 페이지를 고치기 전에 세 가지(업데이트 여부 · 관찰자 알림 · 버전 설명)를
사용자에게 묻게 하지만 강제하는 장치가 없었다. 2026-10-05 한 프로젝트 페이지 두 개가 사용자의 «바꿔» 한 마디로
세 가지 확인 없이 게시됐다. 그래서 게시 경로 두 곳이 이 검사를 요구한다:
  · MCP `updateConfluencePage`·`createConfluencePage` → `scripts/skeleton-gate.sh` 가 `check` 를 부른다
  · `scripts/confluence_patch_page.py --apply` → 이 모듈의 `check_and_consume()` 을 부른다
검사 규칙의 정본은 이 파일 하나다(두 경로가 같은 함수를 쓴다).

■ 왜 발화 인용이 아니라 질문·답인가 (2026-10-07 개정 1)
처음 구현(6d099d930)은 사용자 발화를 인용하게 했다. security 검수가, 같은 저장소의 최근 1시간 발화라면 요청 발화
(«이 내용으로 페이지 바꿔줘»)를 인용해 세 질문을 건너뛰어도 통과함을 재현했다. 증거가 질문 내용과 묶이지 않았기 때문이다.
그래서 증거를 «main 이 AskUserQuestion 으로 띄운 질문(대상·알림·버전 설명이 승인 줄로 들어 있음)에 사용자가 `게시 승인` 보기를
고른 기록» 으로 바꿨다. 질문 문자열과 답은 세션 기록(`~/.claude/projects/<프로젝트>/<세션id>.jsonl`)에서 읽는다.

■ 승인 질문 규약 (main 이 지키고 이 도구가 검사한다)
  · 질문 문자열에 아래 승인 줄이 정확히 한 줄 있다(앞뒤 설명은 자유). 형식은 `question` 하위명령이 출력한다.
      기존 페이지: `게시 승인 요청 · page=<ID>[,<ID>...] · 알림=<notify|quiet> · 버전 설명=«<버전 설명>»`
      새 페이지  : `게시 승인 요청 · new · space=<spaceId> · parent=<parentId 또는 없음> · 제목=«<제목>»`
  · 보기에 라벨이 정확히 `게시 승인` 인 것이 있고, 사용자가 고른 답이 정확히 `게시 승인` 이다. 다른 보기·자유 입력은 승인이 아니다.
  · 한 AskUserQuestion 에 질문이 여럿이면 질문마다 따로 판정한다(answers 는 질문 문자열 → 답 dict 라 질문별로 결박된다).

■ 승인 찾기와 답 결박 (`scripts/external-model-gate.py` last_user_message 와 같은 규칙)
  · assistant 항목(isSidechain 아님)의 tool_use(name=AskUserQuestion) id 와 user 항목(isSidechain 아님)의
    tool_result.tool_use_id 가 같고, 그 user 항목의 `toolUseResult.questions` 가 리스트·`answers` 가 dict 인 것만 인정한다.
  · 승인 시각 = 그 tool_result user 항목의 timestamp. 지금으로부터 3600초 이내여야 한다(미래·시간대 없음·해석 불가는 무효).
  · 대상 기록 = `~/.claude/projects/*/*.jsonl`(main 세션 기록만. `<세션id>/subagents/` 아래는 제외) 중 수정 시각이 1시간 이내인 파일.
    기록은 수백 MB 까지 커지므로 파일 끝에서 거꾸로 읽는다. 멈춤 판단에는 type 이 user·assistant 인 줄의 timestamp 만 쓰고,
    그런 줄이 연속 STALE_RUN(3)줄 이상 1시간보다 오래되면 멈춘다(답이 대기 중인 질문이 있으면 LOOKBACK_SLACK 만큼 더 본다.
    질문을 띄운 뒤 한참 있다 답한 경우 때문이다). queue-operation·file-history-snapshot 줄은 최근 줄 사이에 오래된 timestamp 로
    섞여 있어(실측: 1GB 기록 308,038줄 중 29건) 멈춤 판단에서 제외한다(2026-10-07 qa D1).
  · 승인보다 뒤에(기록 위치상) 사람이 친 새 사용자 메시지가 있으면 그 승인은 무효다. 사용자가 채팅으로 보류·변경을 말했을 수 있기
    때문이다(2026-10-07 security). 사람 메시지 판정은 external-model-gate.py last_user_message·_is_non_user 규칙을 옮겨 적은 것이며
    도구 결과·system-reminder·`<` 로 시작하는 주입·isMeta·isCompactSummary·origin 이 human 아님·피어/subagent 전달문은 제외한다.
    그래서 답을 받은 같은 턴에 게시해야 한다.
  · 대상(공간·부모·제목)·버전 설명에 탭·개행 등 제어문자가 있으면 거부한다.
  · 승인 줄의 대상(숫자 ID 목록 또는 new 의 space·parent·제목)이 호출 대상과 같고, 기존 페이지면 알림·버전 설명(앞뒤 공백 제거 후
    완전 일치)이 호출 값과 같아야 한다. 조건에 맞는 승인이 여럿이면 가장 최근 것부터 사용 장부에 없는 것을 쓴다.
  · 사용 장부 `~/.claude/_audit/publish-approval/used.tsv` 의 키 = `<tool_use_id>\\t<대상 키>`. 소모는 장부에 flock 을 걸고
    «없으면 추가» 를 원자적으로 한다(동시에 둘이 같은 승인을 쓰면 하나만 성공). 게시가 실패해도 승인은 이미 소모되므로
    다시 게시하려면 새 승인 질문이 필요하다.
  · 페이지 ID 는 숫자만 받는다(앞자리 0 제거 후 키로 쓴다). tiny link·URL 등은 «숫자 페이지 ID 로 다시» 사유로 거부.
  · 대상 키: 기존 페이지 `page:<ID>`, 새 페이지 `new:<space>:<parent>:<title>`.

■ 한계 (보고 대상)
  · 세션 기록 파일 형식에 의존한다. 형식이 바뀌면 승인을 못 찾아 fail-closed 로 게시가 막힌다.
  · 세션 기록·사용 장부를 손으로 고치는 위조는 막지 못한다(다른 `_audit` 장부와 같은 한계).
  · 질문 문구가 사용자에게 충분히 읽히는지(승인 줄 앞뒤 설명)는 판정하지 못한다. 그것은 main 의 몫이다.

사용:
  python3 ~/.claude/scripts/confluence_publish_approve.py question (--page <ID> [--page <ID> ...] --notify quiet|notify --message "<버전 설명>" \\
      | --new --space S --parent P --title T)          # 승인 줄·권장 보기를 출력만 한다(쓰기 없음)
  python3 ~/.claude/scripts/confluence_publish_approve.py check [--consume] \\
      (--page <ID> --notify quiet|notify --message "<버전 설명>" | --new --space S --parent P --title T)
check 출력은 JSON 한 줄 {"ok": bool, "reason": "..."}, ok 면 exit 0 아니면 exit 1. `stamp` 는 폐지돼 exit 2 와 안내를 낸다.
"""

import argparse
import fcntl
import glob
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

VALID_SECONDS = 3600
LOOKBACK_SLACK = 6 * 3600
CHUNK = 1 << 20
APPROVE_LABEL = "게시 승인"
CANCEL_LABEL = "취소"
LINE_HEAD = "게시 승인 요청"
_PAGE_RE = re.compile(r"게시 승인 요청 · page=([0-9]+(?:,[0-9]+)*) · 알림=(notify|quiet) · 버전 설명=«(.*)»")
_NEW_RE = re.compile(r"게시 승인 요청 · new · space=(\S+) · parent=(\S+) · 제목=«(.*)»")
PASTE_PREFIX = "<pasted_content"   # a pasted human message; every other `<` start is an injection (external-model-gate.py treats it as non-user too)
STALE_RUN = 3  # stop reading backwards after this many consecutive stale user/assistant lines
_TS_RE = re.compile(rb'"timestamp"\s*:\s*"([^"]+)"')
_KIND_RE = re.compile(rb'"type"\s*:\s*"(user|assistant)"')
_TOOL_RESULT_RE = re.compile(rb'"type"\s*:\s*"tool_result"')   # an escaped copy inside a text string (\"type\") cannot match
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f  \x85]")
# 아래 두 상수와 _is_non_user 는 scripts/external-model-gate.py 의 같은 이름 규칙을 옮겨 적은 것이다(2026-10-07, 그 파일은 고치지 않는다).
# 원본이 바뀌면 여기도 맞춘다. «사람이 친 글자가 아닌데 user 역할로 기록되는 항목» 의 판정 정본은 원본이다.
NON_USER_PREFIXES = ("Base directory for this skill:", "[SYSTEM NOTIFICATION", "[Subagent hand-back]",
                     "This session is being continued from a previous conversation",
                     "Another Claude session sent a message",
                     "[Request interrupted by user")


def _approval_dir():
    """Return the approval ledger directory under the current HOME."""
    return os.path.expanduser("~/.claude/_audit/publish-approval")


def norm_page(page):
    """Normalize a page ID to digits without leading zeros, or raise ValueError."""
    s = str(page).strip()
    if not re.fullmatch(r"[0-9]+", s) or not s.lstrip("0"):
        raise ValueError(f"페이지 ID «{s}» 는 숫자가 아님 — 숫자 페이지 ID 로 다시 지정할 것(tiny link·URL 불가)")
    return s.lstrip("0")


def page_key(page):
    """Build the target key of an existing page (normalized ID)."""
    return f"page:{norm_page(page)}"


def new_key(space, parent, title):
    """Build the target key of a page to be created."""
    return f"new:{str(space).strip()}:{str(parent or '').strip()}:{str(title).strip()}"


def approval_line(keys, notify=None, message=None):
    """Build the approval line main must put in the AskUserQuestion question for the given target keys."""
    if keys[0].startswith("page:"):
        return (f"{LINE_HEAD} · page={','.join(k[5:] for k in keys)} · 알림={notify or '<notify|quiet>'}"
                f" · 버전 설명=«{(message or '<버전 설명>').strip()}»")
    _, space, parent, title = keys[0].split(":", 3)
    return f"{LINE_HEAD} · new · space={space} · parent={parent or '없음'} · 제목=«{title}»"


def _parse_iso(s):
    """Parse an ISO time with timezone into epoch seconds, or None."""
    if not isinstance(s, str) or not s:
        return None
    try:
        dt = datetime.fromisoformat(s[:-1] + "+00:00" if s.endswith("Z") else s)
    except ValueError:
        return None
    return dt.timestamp() if dt.tzinfo else None


def _fresh(epoch, now):
    """True when epoch is not in the future and within the validity window."""
    return epoch is not None and 0 <= now - epoch <= VALID_SECONDS


def _ctrl_error(*texts):
    """Return a rejection reason when any text holds a control character (tab, newline, ...), else None."""
    if any(_CTRL_RE.search(str(t or "")) for t in texts):
        return "★대상(공간·부모·제목)·버전 설명에 탭·개행 등 제어문자가 있음 — 한 줄 평문으로 다시 지정할 것"
    return None


def parse_approval_line(question):
    """Parse the single approval line of a question into {keys, notify, message}, or None when absent or malformed."""
    lines = [ln.strip() for ln in str(question).splitlines() if ln.strip().startswith(LINE_HEAD)]
    if len(lines) != 1 or _ctrl_error(lines[0]):
        return None
    m = _PAGE_RE.fullmatch(lines[0])
    if m:
        try:
            keys = [page_key(p) for p in m.group(1).split(",")]
        except ValueError:
            return None
        msg = m.group(3).strip()
        return {"keys": keys, "notify": m.group(2), "message": msg} if msg else None
    m = _NEW_RE.fullmatch(lines[0])
    if m and m.group(3).strip():
        parent = "" if m.group(2) == "없음" else m.group(2)
        return {"keys": [new_key(m.group(1), parent, m.group(3))], "notify": None, "message": None}
    return None


def _reverse_lines(path):
    """Yield the non-empty raw lines of a file from the end, reading in chunks (session logs reach hundreds of MB)."""
    with open(path, "rb") as f:
        pos = f.seek(0, 2)
        held = []   # fragments of the line that continues to the left, in reading order (rightmost first)
        while pos > 0:
            step = min(CHUNK, pos)
            pos -= step
            f.seek(pos)
            data = f.read(step)
            parts = data.split(b"\n")
            if len(parts) == 1:
                held.append(data)
                continue
            last = parts[-1] + b"".join(reversed(held))
            if last:
                yield last
            for ln in reversed(parts[1:-1]):
                if ln:
                    yield ln
            held = [parts[0]]
        first = b"".join(reversed(held))
        if first:
            yield first


def _line_meta(line):
    """Return (kind, newest timestamp epoch) read from the head and tail of a raw line (key order varies).

    kind is 'user' or 'assistant' when such a top-level type marker is found, else None. Only those lines are real conversation
    turns; queue-operation or file-history-snapshot lines carry old timestamps among recent lines and must not stop the scan.
    """
    kind, best = None, None
    for seg in (line[:2048], line[-2048:]):
        k = _KIND_RE.search(seg)
        if k and kind is None:
            kind = k.group(1).decode()
        for m in _TS_RE.finditer(seg):
            e = _parse_iso(m.group(1).decode("utf-8", "replace"))
            if e is not None and (best is None or e > best):
                best = e
    return kind, best


def _is_non_user(d, t):
    """True for an entry recorded with role user whose text a human did not type (rule copied from scripts/external-model-gate.py).

    Skill bodies, compact summaries, automatic notices and peer or subagent hand-backs are marked by structure fields
    (isMeta, isCompactSummary, origin other than human) and, as a fallback, by text prefixes.
    """
    if d.get("isMeta") or d.get("isCompactSummary"):
        return True
    origin = d.get("origin")
    if origin is not None and not (isinstance(origin, dict) and origin.get("kind") == "human"):
        return True
    return t.startswith(NON_USER_PREFIXES) or "<cross-session-message" in t


def _is_human_message(d):
    """True when a parsed entry is a message a human typed in the main conversation (rule of last_user_message in external-model-gate.py).

    Two shapes: a `user` entry, and an `attachment` entry of attachment.type queued_command, which is the only record of a message
    typed while a turn is running (origin human or absent, commandMode not task-notification). Text that starts with `<` is an
    injection and not human, except a paste (`<pasted_content`), which a human typed in a gate context.
    """
    if d.get("type") == "attachment" and not d.get("isSidechain"):
        a = d.get("attachment")
        if not (isinstance(a, dict) and a.get("type") == "queued_command") or a.get("commandMode") == "task-notification":
            return False
        origin = a.get("origin", d.get("origin"))
        t = a.get("prompt")
        if isinstance(t, list):   # a message with an image arrives as content blocks; join the text blocks like the user branch (2026-10-07 review)
            t = " ".join(x.get("text", "") for x in t if isinstance(x, dict) and isinstance(x.get("text", ""), str) and x.get("type") == "text")
        if (origin is not None and not (isinstance(origin, dict) and origin.get("kind") == "human")) or not isinstance(t, str):
            return False
        t = t.strip()
        return bool(t) and (not t.startswith("<") or t.startswith(PASTE_PREFIX)) \
            and not t.startswith(NON_USER_PREFIXES) and "<cross-session-message" not in t
    if d.get("type") != "user" or d.get("isSidechain"):
        return False
    msg = d.get("message")
    c = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(c, str):
        t = c
    elif isinstance(c, list):
        if any(isinstance(x, dict) and x.get("type") == "tool_result" for x in c):
            return False
        t = " ".join(x.get("text", "") for x in c if isinstance(x, dict) and isinstance(x.get("text", ""), str) and x.get("type") == "text")
    else:
        return False
    t = t.strip()
    if t.startswith("<command-name>"):   # a slash command is recorded as <command-name>…<command-args>what the user typed</command-args>
        a = re.search(r"<command-args>(.*?)</command-args>", t, re.DOTALL)
        t = a.group(1).strip() if a else ""
    if not t or (t.startswith("<") and not t.startswith(PASTE_PREFIX)):   # system-reminder and local-command injections are not user text
        return False
    return not _is_non_user(d, t)


def _scan(path, now):
    """Yield (tool_use_id, answered_epoch, questions, answers) of fresh bound AskUserQuestion answers in one session file.

    Reads from the end. Stops after STALE_RUN consecutive user/assistant lines older than the window (plus LOOKBACK_SLACK while an
    answer waits for its question). An answer is dropped when a human-typed message comes after it in the file: the user may have
    held or changed the request in chat, so the approval no longer stands.
    """
    pending = {}
    human_after = False
    stale_run = 0
    for ln in _reverse_lines(path):
        kind, hint = _line_meta(ln)
        if kind and hint is not None:
            if now - hint > VALID_SECONDS + (LOOKBACK_SLACK if pending else 0):
                stale_run += 1
                if stale_run >= STALE_RUN:
                    return
            else:
                stale_run = 0
        has_ask = b"AskUserQuestion" in ln or b'"answers"' in ln
        queued = b"queued_command" in ln   # a message typed during a running turn is recorded only as an attachment line
        if not has_ask and not queued and (kind == "assistant" or not _KIND_RE.search(ln) or _TOOL_RESULT_RE.search(ln)):
            continue
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        if _is_human_message(d):
            human_after = True
            continue
        if d.get("isSidechain"):
            continue
        msg = d.get("message")
        blocks = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(blocks, list):
            continue
        if d.get("type") == "user":
            tur = d.get("toolUseResult")
            epoch = _parse_iso(d.get("timestamp"))
            if human_after or not (isinstance(tur, dict) and isinstance(tur.get("questions"), list)
                                   and isinstance(tur.get("answers"), dict) and _fresh(epoch, now)):
                continue
            for b in blocks:
                if isinstance(b, dict) and b.get("type") == "tool_result" and isinstance(b.get("tool_use_id"), str):
                    pending[b["tool_use_id"]] = (epoch, tur["answers"])
        elif d.get("type") == "assistant":
            for b in blocks:
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "AskUserQuestion" and b.get("id") in pending:
                    epoch, answers = pending.pop(b["id"])
                    qs = (b.get("input") or {}).get("questions")
                    if isinstance(qs, list):
                        yield b["id"], epoch, qs, answers


def _session_files(now):
    """Return main session logs (no subagents/) modified within the validity window, newest first."""
    files = []
    for p in glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl")):
        try:
            mt = os.path.getmtime(p)
        except OSError:
            continue
        if now - mt <= VALID_SECONDS:
            files.append((mt, p))
    return [p for _, p in sorted(files, reverse=True)]


def is_approval_question(tool_input):
    """True when an AskUserQuestion input holds a publish-approval question (the same condition find_approval applies, minus the answer).

    A question counts when its text has exactly one valid approval line and its options include the «게시 승인» label.
    scripts/handoff_check.py uses this to spot a review turn (2026-11-12); find_approval keeps its own inline copy of the condition.
    """
    qs = tool_input.get("questions") if isinstance(tool_input, dict) else None
    for q in qs if isinstance(qs, list) else []:
        text = q.get("question") if isinstance(q, dict) else None
        opts = q.get("options") if isinstance(q, dict) else None
        if (isinstance(text, str) and isinstance(opts, list) and parse_approval_line(text)
                and any(isinstance(o, dict) and o.get("label") == APPROVE_LABEL for o in opts)):
            return True
    return False


def find_approval(key, notify, message, now=None):
    """Return approvals for a target as [(answered_epoch, tool_use_id)] newest first (empty when none match)."""
    now = time.time() if now is None else now
    found = []
    for path in _session_files(now):
        try:
            for tuid, epoch, questions, answers in _scan(path, now):
                for q in questions:
                    qs = q.get("question") if isinstance(q, dict) else None
                    opts = q.get("options") if isinstance(q, dict) else None
                    if not isinstance(qs, str) or answers.get(qs) != APPROVE_LABEL:
                        continue
                    if not isinstance(opts, list) or not any(isinstance(o, dict) and o.get("label") == APPROVE_LABEL for o in opts):
                        continue
                    ap = parse_approval_line(qs)
                    if ap and key in ap["keys"] and (not key.startswith("page:") or (
                            ap["notify"] == notify and ap["message"] == str(message or "").strip())):
                        found.append((epoch, tuid))
                        break
        except OSError:
            continue
    return sorted(found, reverse=True)


def _used_pairs():
    """Return the set of (tool_use_id, target key) pairs already consumed."""
    pairs = set()
    try:
        with open(os.path.join(_approval_dir(), "used.tsv"), encoding="utf-8") as f:
            for line in f:
                p = line.rstrip("\n").split("\t")
                if len(p) >= 2:
                    pairs.add((p[0], p[1]))
    except OSError:
        pass
    return pairs


def _consume(tuid, key):
    """Atomically add (tool_use_id, key) to the used ledger under flock; False when it is already there."""
    d = _approval_dir()
    os.makedirs(d, mode=0o700, exist_ok=True)
    with os.fdopen(os.open(os.path.join(d, "used.tsv"), os.O_RDWR | os.O_CREAT, 0o600), "r+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        if any(ln.rstrip("\n").split("\t")[:2] == [tuid, key] for ln in f):
            return False
        f.seek(0, 2)
        f.write(f"{tuid}\t{key}\t{datetime.now(timezone.utc).astimezone().isoformat()}\n")  # noqa: UP017 — system python3 3.10 has no datetime.UTC
    return True


def check(key, notify=None, message=None, consume=False, cwd=None):
    """Check (and optionally consume) the AskUserQuestion approval of a target; return (ok, reason). cwd is ignored (compat)."""
    bad = _ctrl_error(key, message)
    if bad:
        return False, bad
    redo = ("AskUserQuestion 으로 아래 승인 줄을 질문에 넣어 물을 것(보기: «게시 승인»·«취소», 사용자가 «게시 승인» 을 골라야 함). "
            f"승인 줄:\n  {approval_line([key], notify, message)}")
    found = find_approval(key, notify, message)
    if not found:
        return False, (f"★게시 승인 기록 없음(최근 1시간 안에 사용자가 이 대상·알림·버전 설명의 승인 줄에 «{APPROVE_LABEL}» 을 고른 "
                       f"AskUserQuestion 답이 없음) — 게시 중단. {redo}")
    used = _used_pairs()
    fresh = [tuid for _, tuid in found if (tuid, key) not in used]
    if not fresh:
        return False, f"★이 승인은 이 대상에 이미 썼음(같은 승인 재사용 금지) — 게시 중단. 새 승인을 받을 것. {redo}"
    if consume and not any(_consume(tuid, key) for tuid in fresh):
        return False, f"★게시 승인을 소모하지 못함(다른 쪽이 먼저 썼을 수 있음) — 게시 중단. {redo}"
    return True, "ok"


def check_and_consume(page, notify, message):
    """Consume the approval of an existing page for the script path; exit with the reason when it fails."""
    try:
        key = page_key(page)
    except ValueError as e:
        sys.exit(f"\n{e}")
    ok, reason = check(key, notify, message, consume=True)
    if not ok:
        sys.exit("\n" + reason)


def main(argv=None):
    """CLI entry: question or check (stamp is retired); check prints one JSON line and exits 0/1."""
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["stamp"]:
        print("stamp 는 폐지됐다. 승인은 AskUserQuestion 질문으로 받는다. 승인 줄 형식은 `question` 하위명령으로 확인할 것:\n"
              f"  {approval_line(['page:<ID>'])}\n  {approval_line(['new:<spaceId>:<parentId>:<제목>'])}\n"
              f"보기는 «{APPROVE_LABEL}»·«{CANCEL_LABEL}» 를 둔다.", file=sys.stderr)
        return 2
    ap = argparse.ArgumentParser(description="Confluence 게시 승인 검사")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("question", "check"):
        p = sub.add_parser(name)
        p.add_argument("--new", action="store_true", help="새 페이지(공간·부모·제목으로 대상 지정)")
        p.add_argument("--space")
        p.add_argument("--parent", default="")
        p.add_argument("--title")
        p.add_argument("--notify", choices=("quiet", "notify"))
        p.add_argument("--message")
        if name == "question":
            p.add_argument("--page", action="append", default=[])
        else:
            p.add_argument("--page")
            p.add_argument("--consume", action="store_true")
            p.add_argument("--cwd", help="하위 호환용(무시한다)")
    a = ap.parse_args(argv)

    bad = _ctrl_error(a.space, a.parent, a.title, a.message)   # raw values: new_key() would strip a trailing newline silently
    if bad:
        print(json.dumps({"ok": False, "reason": bad}, ensure_ascii=False))
        return 1
    pages = a.page if a.cmd == "question" else ([a.page] if a.page else [])
    if a.new:
        if pages or not a.space or not (a.title or "").strip():
            ap.error("--new 는 --space·--title 이 필요하고 --page 와 함께 쓸 수 없다")
        keys = [new_key(a.space, a.parent, a.title)]
    else:
        if not pages or not a.notify or not (a.message or "").strip():
            ap.error("기존 페이지는 --page(1개+)·--notify·--message 가 모두 필요하다")
        try:
            keys = [page_key(p) for p in pages]
        except ValueError as e:
            print(json.dumps({"ok": False, "reason": str(e)}, ensure_ascii=False))
            return 1

    if a.cmd == "question":
        print(f"승인 줄(AskUserQuestion 질문 문자열에 정확히 한 줄로 넣을 것):\n{approval_line(keys, a.notify, a.message)}\n"
              f"권장 보기: 라벨 «{APPROVE_LABEL}» · «{CANCEL_LABEL}»")
        return 0
    if len(keys) != 1:
        ap.error("check 는 대상 하나만 받는다")
    ok, reason = check(keys[0], a.notify, a.message, a.consume)
    print(json.dumps({"ok": ok, "reason": reason}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
