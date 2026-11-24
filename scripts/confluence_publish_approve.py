#!/usr/bin/env python3
# ruff: noqa: EXE001
"""Confluence 게시 직전 «사용자 승인» 검사 도구.

■ 쓰는 곳
게시 경로 두 곳이 이 검사를 요구한다:
  · MCP `updateConfluencePage`·`createConfluencePage` → `scripts/skeleton-gate.sh` 가 `check` 를 부른다
  · `scripts/confluence_patch_page.py --apply` → 이 모듈의 `check_and_consume()` 을 부른다
    (`--create --apply` 새 페이지 만들기는 `check_and_consume_new()`, 2026-11-22 개정 4. 새 페이지 승인 줄 · 판정은 MCP 생성 경로와 같다)
검사 규칙의 정본은 이 파일 하나다(두 경로가 같은 함수를 쓴다).

■ 승인 질문 규약 (main 이 지키고 이 도구가 검사한다)
  · 질문 문자열에 아래 승인 줄이 정확히 한 줄 있다(앞뒤 설명은 자유). 형식은 `question` 하위명령이 출력한다.
      기존 페이지: `게시 승인 요청 · page=<ID>[,<ID>...] · 알림=<notify|quiet> · 버전 설명=«<버전 설명>»`
      새 페이지  : `게시 승인 요청 · new · space=<spaceId> · parent=<parentId 또는 없음> · 제목=«<제목>»`
  · 제목 변경 · 이동(2026-11-22 개정 2, confluence_patch_page.py --title · --parent): 기존 페이지 줄 뒤에 값이 있을 때만
    ` · 새 제목=«<새 제목>»` 그다음 ` · 새 부모=<부모 ID>` 를 이 순서로 붙인다. 둘 다 없으면 위 기존 꼴과 글자 하나 다르지 않다.
      예: `게시 승인 요청 · page=123 · 알림=quiet · 버전 설명=«제목 정리» · 새 제목=«새 이름» · 새 부모=456`
    판정은 해석한 필드끼리 비교한다(대상 · 알림 · 버전 설명 · 새 제목 · 새 부모가 전부 같아야 통과, 없는 것은 없는 것끼리).
    그래서 새 필드가 든 승인은 치환만 하는 호출 · 제목 · 부모를 바꾸지 않는 MCP 수정에 통과하지 않고, 그 반대도 같다.
    (MCP 경로: 2026-11-22 개정 3 부터 skeleton-gate.sh 가 updateConfluencePage 의 title · parentId 가 있으면 --set-title · --set-parent 로 넘기고,
    spaceId 가 든 호출은 승인 검사 전에 막는다.)
    새 필드가 든 줄의 대상은 페이지 하나여야 하고(`page=1,2` 와 함께면 무효) 새 부모는 숫자 ID 만 받는다. 사용 장부 키는 그대로 `page:<ID>`.
    ★한 줄 = 한 해석: 버전 설명 `a» · 새 제목=«X` 와 «버전 설명 a + 새 제목 X» 는 같은 글자의 줄을 만든다. 그래서 버전 설명 · 새 제목에
    `» · 새 제목=«` · `» · 새 부모=` 가 든 값은 호출에서도 승인 줄에서도 거부한다. 남는 해석은 «새 필드가 있다» 하나뿐이다(사용자가 본 글자대로).
    한계: 표지는 글자 그대로만 본다. 버전 설명에 공백 두 칸 · 전각 구분점처럼 표지와 비슷해 보이는 글자를 쓰면 파서는 버전 설명 하나로 읽는다
    (보이는 것보다 적게 실행되는 쪽이라 권한이 늘지는 않는다).
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
  # 기존 페이지 제목 변경 · 이동: 위 기존 페이지 꼴(--page 1개)에 --set-title "<새 제목>" · --set-parent <부모 ID> 를 더한다.
  #   (--new 의 --title · --parent 는 «새 페이지 만들기» 대상이고, --set-* 는 «기존 페이지의 제목 · 부모를 바꾸기» 다)
check 출력은 JSON 한 줄 {"ok": bool, "reason": "..."}, ok 면 exit 0 아니면 exit 1. `stamp` 는 폐지돼 exit 2 와 안내를 낸다.
REF: knowledge/harness/code-history/scripts__confluence_publish_approve.py.md
"""

import argparse
import fcntl
import glob
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone

VALID_SECONDS = 3600
LOOKBACK_SLACK = 6 * 3600
CHUNK = 1 << 20
APPROVE_LABEL = "게시 승인"
CANCEL_LABEL = "취소"
LINE_HEAD = "게시 승인 요청"
_PAGE_RE = re.compile(r"게시 승인 요청 · page=([0-9]+(?:,[0-9]+)*) · 알림=(notify|quiet) · 버전 설명=«(.*?)»"
                      r"(?: · 새 제목=«(.*)»)?(?: · 새 부모=([0-9]+))?")
_FIELD_MARKS = ("» · 새 제목=«", "» · 새 부모=")
_NEW_RE = re.compile(r"게시 승인 요청 · new · space=(\S+) · parent=(\S+) · 제목=«(.*)»")
PASTE_PREFIX = "<pasted_content"   # WHY: a pasted human message; every other `<` start is an injection (external-model-gate.py treats it as non-user too)
STALE_RUN = 3
_TS_RE = re.compile(rb'"timestamp"\s*:\s*"([^"]+)"')
_KIND_RE = re.compile(rb'"type"\s*:\s*"(user|assistant)"')
_TOOL_RESULT_RE = re.compile(rb'"type"\s*:\s*"tool_result"')
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f  \x85]")
# WHY: 아래 두 상수와 _is_non_user 는 scripts/external-model-gate.py 의 같은 이름 규칙을 옮겨 적은 것이다(2026-10-07, 그 파일은 고치지 않는다).
# 원본이 바뀌면 여기도 맞춘다. «사람이 친 글자가 아닌데 user 역할로 기록되는 항목» 의 판정 정본은 원본이다.
NON_USER_PREFIXES = ("Base directory for this skill:", "[SYSTEM NOTIFICATION", "[Subagent hand-back]",
                     "This session is being continued from a previous conversation",
                     "Another Claude session sent a message",
                     "[Request interrupted by user")


def _approval_dir():
    return os.path.expanduser("~/.claude/_audit/publish-approval")


def norm_page(page):
    s = str(page).strip()
    if not re.fullmatch(r"[0-9]+", s) or not s.lstrip("0"):
        raise ValueError(f"페이지 ID «{s}» 는 숫자가 아님 — 숫자 페이지 ID 로 다시 지정할 것(tiny link·URL 불가)")
    return s.lstrip("0")


def page_key(page):
    return f"page:{norm_page(page)}"


def new_key(space, parent, title):
    # WHY: 키는 `new:<공간>:<부모>:<제목>` 이다. 공간 · 부모에 `:` 가 있으면 서로 다른 (공간, 부모, 제목)이 같은 키가 된다
    # (예: 부모 `5:판1` + 제목 `결과` = 부모 `5` + 제목 `판1:결과`, 2026-11-22 security). 공간 · 부모에 `:` 가 없으면
    # 앞의 두 `:` 가 칸 경계로만 읽히므로 제목에 `:` 가 있어도 키는 한 가지로만 나뉜다. 그래서 제목의 `:` 는 허용한다.
    # 호출 쪽(question · check · 스크립트 · MCP 훅)과 승인 줄 해석이 모두 이 함수를 지나므로 여기서 막으면 전부 fail-closed 다.
    space, parent = str(space).strip(), str(parent or "").strip()
    if ":" in space or ":" in parent:
        raise ValueError("★새 페이지의 공간·부모 값에 «:» 가 있음 — 승인 대상 키가 두 가지로 읽혀 거부한다. 공간 ID · 부모 ID 로 다시 지정할 것")
    return f"new:{space}:{parent}:{str(title).strip()}"


def norm_change(title=None, parent=None):
    if title is not None:
        if _ctrl_error(title):
            raise ValueError("★새 제목에 탭·개행 등 제어문자가 있음 — 한 줄 평문으로 다시 지정할 것")
        # WHY: 방향 제어(U+202A~E · U+2066~9) · 폭 없는 글자(Cf)와 줄 · 문단 구분자(Zl · Zp)는 승인 줄에서 보이는 글자와 실제 값을 갈라놓는다(2026-11-22 security).
        if any(unicodedata.category(c) in ("Cf", "Zl", "Zp") for c in str(title)):
            raise ValueError("★새 제목에 보이지 않는 글자 · 방향 제어 글자가 있음 — 승인 줄에서 사용자가 본 글자와 실제 값이 달라질 수 있어 거부한다")
        title = str(title).strip()
        if not title:
            raise ValueError("★새 제목이 비어 있음 — 바꿀 제목을 지정할 것")
        if _mark_error(title):
            raise ValueError(_mark_error(title))
    if parent is not None:
        try:
            parent = norm_page(parent)
        except ValueError as e:
            raise ValueError(f"★새 부모: {e}") from None
    return title, parent


def _mark_error(*texts):
    if any(m in str(t or "") for t in texts for m in _FIELD_MARKS):
        return "★버전 설명·새 제목에 «» · 새 제목=«» 나 «» · 새 부모=» 가 들어 있음 — 승인 줄이 두 가지로 읽혀 거부한다. 문구를 바꿔 다시 지정할 것"
    return None


def approval_line(keys, notify=None, message=None, title=None, parent=None):
    if keys[0].startswith("page:"):
        line = (f"{LINE_HEAD} · page={','.join(k[5:] for k in keys)} · 알림={notify or '<notify|quiet>'}"
                f" · 버전 설명=«{(message or '<버전 설명>').strip()}»")
        if title is not None:
            line += f" · 새 제목=«{title}»"
        if parent is not None:
            line += f" · 새 부모={parent}"
        return line
    _, space, parent, title = keys[0].split(":", 3)
    return f"{LINE_HEAD} · new · space={space} · parent={parent or '없음'} · 제목=«{title}»"


def _parse_iso(s):
    if not isinstance(s, str) or not s:
        return None
    try:
        dt = datetime.fromisoformat(s[:-1] + "+00:00" if s.endswith("Z") else s)
    except ValueError:
        return None
    return dt.timestamp() if dt.tzinfo else None


def _fresh(epoch, now):
    return epoch is not None and 0 <= now - epoch <= VALID_SECONDS


def _ctrl_error(*texts):
    if any(_CTRL_RE.search(str(t or "")) for t in texts):
        return "★대상(공간·부모·제목)·버전 설명에 탭·개행 등 제어문자가 있음 — 한 줄 평문으로 다시 지정할 것"
    return None


def parse_approval_line(question):
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
        title, parent = m.group(4), m.group(5)
        if not msg or _mark_error(msg, title):
            return None
        if title is not None or parent is not None:
            if len(keys) != 1:
                return None
            try:
                title, parent = norm_change(title, parent)
            except ValueError:
                return None
        return {"keys": keys, "notify": m.group(2), "message": msg, "title": title, "parent": parent}
    m = _NEW_RE.fullmatch(lines[0])
    if m and m.group(3).strip():
        parent = "" if m.group(2) == "없음" else m.group(2)
        try:
            return {"keys": [new_key(m.group(1), parent, m.group(3))], "notify": None, "message": None}
        except ValueError:
            return None
    return None


def _reverse_lines(path):
    with open(path, "rb") as f:
        pos = f.seek(0, 2)
        held = []
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
    if d.get("isMeta") or d.get("isCompactSummary"):
        return True
    origin = d.get("origin")
    if origin is not None and not (isinstance(origin, dict) and origin.get("kind") == "human"):
        return True
    return t.startswith(NON_USER_PREFIXES) or "<cross-session-message" in t


def _is_human_message(d):
    if d.get("type") == "attachment" and not d.get("isSidechain"):
        a = d.get("attachment")
        if not (isinstance(a, dict) and a.get("type") == "queued_command") or a.get("commandMode") == "task-notification":
            return False
        origin = a.get("origin", d.get("origin"))
        t = a.get("prompt")
        if isinstance(t, list):   # WHY: a message with an image arrives as content blocks; join the text blocks like the user branch (2026-10-07 review)
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
    if t.startswith("<command-name>"):
        a = re.search(r"<command-args>(.*?)</command-args>", t, re.DOTALL)
        t = a.group(1).strip() if a else ""
    if not t or (t.startswith("<") and not t.startswith(PASTE_PREFIX)):
        return False
    return not _is_non_user(d, t)


def _scan(path, now):
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
        queued = b"queued_command" in ln
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
    # WHY: scripts/handoff_check.py uses this to spot a review turn (2026-11-12); find_approval keeps its own inline copy of the condition.
    qs = tool_input.get("questions") if isinstance(tool_input, dict) else None
    for q in qs if isinstance(qs, list) else []:
        text = q.get("question") if isinstance(q, dict) else None
        opts = q.get("options") if isinstance(q, dict) else None
        if (isinstance(text, str) and isinstance(opts, list) and parse_approval_line(text)
                and any(isinstance(o, dict) and o.get("label") == APPROVE_LABEL for o in opts)):
            return True
    return False


def find_approval(key, notify, message, now=None, title=None, parent=None):
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
                            ap["notify"] == notify and ap["message"] == str(message or "").strip()
                            and ap.get("title") == title and ap.get("parent") == parent)):
                        found.append((epoch, tuid))
                        break
        except OSError:
            continue
    return sorted(found, reverse=True)


def _used_pairs():
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
    d = _approval_dir()
    os.makedirs(d, mode=0o700, exist_ok=True)
    with os.fdopen(os.open(os.path.join(d, "used.tsv"), os.O_RDWR | os.O_CREAT, 0o600), "r+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        if any(ln.rstrip("\n").split("\t")[:2] == [tuid, key] for ln in f):
            return False
        f.seek(0, 2)
        # WHY: system python3 3.10 has no datetime.UTC
        f.write(f"{tuid}\t{key}\t{datetime.now(timezone.utc).astimezone().isoformat()}\n")  # noqa: UP017
    return True


def check(key, notify=None, message=None, consume=False, cwd=None, title=None, parent=None):
    bad = _ctrl_error(key, message, title) or _mark_error(message)
    if bad:
        return False, bad
    if title is not None or parent is not None:
        if not key.startswith("page:"):
            return False, "★새 제목·새 부모는 기존 페이지 하나에만 쓴다(새 페이지 만들기는 space·parent·제목으로 지정)"
        try:
            title, parent = norm_change(title, parent)
        except ValueError as e:
            return False, str(e)
    redo = ("AskUserQuestion 으로 아래 승인 줄을 질문에 넣어 물을 것(보기: «게시 승인»·«취소», 사용자가 «게시 승인» 을 골라야 함). "
            f"승인 줄:\n  {approval_line([key], notify, message, title, parent)}")
    found = find_approval(key, notify, message, title=title, parent=parent)
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


def check_and_consume(page, notify, message, title=None, parent=None):
    try:
        key = page_key(page)
    except ValueError as e:
        sys.exit(f"\n{e}")
    ok, reason = check(key, notify, message, consume=True, title=title, parent=parent)
    if not ok:
        sys.exit("\n" + reason)


def check_and_consume_new(space, parent, title):
    try:
        key = new_key(space, parent, title)
    except ValueError as e:
        sys.exit(f"\n{e}")
    ok, reason = check(key, consume=True)
    if not ok:
        sys.exit("\n" + reason)


def main(argv=None):
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
        p.add_argument("--set-title", help="기존 페이지(--page 1개)의 새 제목. --new 의 --title(새 페이지 만들기)과 다르다")
        p.add_argument("--set-parent", help="기존 페이지(--page 1개)를 옮길 새 부모 페이지 ID(숫자). --new 의 --parent 와 다르다")
        if name == "question":
            p.add_argument("--page", action="append", default=[])
        else:
            p.add_argument("--page")
            p.add_argument("--consume", action="store_true")
            p.add_argument("--cwd", help="하위 호환용(무시한다)")
    a = ap.parse_args(argv)

    # NEVER: check stripped values here; new_key() would strip a trailing newline silently.
    bad = _ctrl_error(a.space, a.parent, a.title, a.message)
    if bad:
        print(json.dumps({"ok": False, "reason": bad}, ensure_ascii=False))
        return 1
    pages = a.page if a.cmd == "question" else ([a.page] if a.page else [])
    set_title, set_parent = a.set_title, a.set_parent
    if set_title is not None or set_parent is not None:
        if a.new or len(pages) != 1:
            ap.error("--set-title·--set-parent 는 기존 페이지 하나(--page 1개)에만 쓴다(--new 의 --title·--parent 는 새 페이지 만들기)")
        try:
            set_title, set_parent = norm_change(set_title, set_parent)
        except ValueError as e:
            print(json.dumps({"ok": False, "reason": str(e)}, ensure_ascii=False))
            return 1
    if a.new:
        if pages or not a.space or not (a.title or "").strip():
            ap.error("--new 는 --space·--title 이 필요하고 --page 와 함께 쓸 수 없다")
        try:
            keys = [new_key(a.space, a.parent, a.title)]
        except ValueError as e:
            print(json.dumps({"ok": False, "reason": str(e)}, ensure_ascii=False))
            return 1
    else:
        if not pages or not a.notify or not (a.message or "").strip():
            ap.error("기존 페이지는 --page(1개+)·--notify·--message 가 모두 필요하다")
        try:
            keys = [page_key(p) for p in pages]
        except ValueError as e:
            print(json.dumps({"ok": False, "reason": str(e)}, ensure_ascii=False))
            return 1

    if a.cmd == "question":
        bad = _mark_error(a.message)
        if bad:
            print(json.dumps({"ok": False, "reason": bad}, ensure_ascii=False))
            return 1
        print(f"승인 줄(AskUserQuestion 질문 문자열에 정확히 한 줄로 넣을 것):\n{approval_line(keys, a.notify, a.message, set_title, set_parent)}\n"
              f"권장 보기: 라벨 «{APPROVE_LABEL}» · «{CANCEL_LABEL}»")
        return 0
    if len(keys) != 1:
        ap.error("check 는 대상 하나만 받는다")
    ok, reason = check(keys[0], a.notify, a.message, a.consume, title=set_title, parent=set_parent)
    print(json.dumps({"ok": ok, "reason": reason}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
