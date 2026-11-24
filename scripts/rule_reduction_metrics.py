"""rule_reduction_metrics.py: 상시 규칙 축소 실험의 동작 지표 M1 ~ M7 과 «이득» 을 세션 기록 · 하네스 기록에서 읽기 전용으로 집계한다.

무엇을: 줄이기 전(기준 창)과 뒤(뒤 창)를 같은 스크립트로 재서 비교한다. 지표마다 값 · 분자 · 분모를 마크다운 표로 내고,
  분모가 0 이면 «해당 없음» 이다. 프로젝트별 층화 표는 프로젝트를 P1 … 번호로만 적는다(작업성 턴 많은 순).
  기록 읽기(iter_main_files) · 턴 가르기(iter_events)는 agent_usage_report.py 가 불러 쓴다.
정본: 의뢰서 intent/2026-11-24-always-on-rule-reduction.md(성공 기준 1 · 2, 4절 제약, 6절 전제),
  지표 정의 docs/superpowers/plans/2026-11-24-always-on-rule-reduction-design.md 4절.
사용:
  uv run --no-project python scripts/rule_reduction_metrics.py --since 2026-11-17T00:00:00+09:00 --until 2026-11-24T00:00:00+09:00 \\
      [--rules-since 2026-11-17T00:00:00+09:00] --label base [--out] [--home DIR]
  uv run --no-project python scripts/rule_reduction_metrics.py --mark-window base --end 2026-12-01
  시각은 시간대가 붙은 ISO 꼴이어야 한다(창은 since 이상 until 미만). 종료 코드 0, 사용 오류 · 쓰기 거부 · 예기치 못한 예외 2.

■ 출력 · 쓰기
  대화 본문 · 프롬프트 · 파일 경로 · 프로젝트 이름 · 세션 id 를 출력과 예외 글에 싣지 않는다(건너뛴 파일은 까닭과 «N번째 파일» 만).
  표에 들어가는 태그 · 훅 이름은 허용 글자만 남긴다. 쓰기는 두 가지뿐이다:
  · --out: <home>/_audit/rule-reduction/<label>.md 를 새로 만든다(모드 600). 폴더는 링크를 따라가지 않는 dir fd 로 한 칸씩 열어
    (없으면 700 으로 만듦) 링크 · 폴더 아님이면 거부하고, 이미 있는 파일(링크 포함)은 O_EXCL 로 거부한다.
  · --mark-window <label> --end <YYYY-MM-DD>: <home>/_usage/rule-reduction-window 에 «label TAB 끝 날짜» 한 줄을 쓴다(덮어씀, 모드 600).
    링크 · 일반 파일 아님 · 하드 링크 수 1 아님이면 거부한다. harness-usage-check.sh 의 RULE_REDUCTION_WINDOW_DUE 경보가 읽는다.
  label 은 [A-Za-z0-9._-]{1,40} 만 받는다.

■ 방어
  줄 단위 스트리밍. 파일은 O_NOFOLLOW · O_NONBLOCK 으로 열고 fstat 로 일반 파일인지 다시 본다(링크 · FIFO 는 까닭과 함께 건너뜀).
  파일당 크기 상한 MAX_FILE_BYTES(4GiB. 창 기준을 턴 단위로 바꾸며 장수 세션도 열게 됐고, 실측 최대 main 기록이 2,089MiB 다),
  전체 시간 예산 TIME_BUDGET_S(최근 9일에 쓰인 main 기록 27개를 통째로 풀어도 약 30초였다. 그 20배).
  예산을 넘으면 그 자리에서 멈추고 머리에 «부분 결과» 와 멈춘 파일 번호를 적는다. 깨진 JSON 줄은 세고 건너뛴다(세션 기록은 바이트 검사를
  통과한 대상 꼴 줄만 풀므로 그 가운데 깨진 줄을 센다).
  조작되거나 깨진 한 줄이 집계를 죽이거나 늦추거나 출력을 부풀리지 못하게 한다(2026-11-24 security 낮음 6건 · qa 지적):
  · 한 줄은 MAX_LINE_BYTES(64MiB)까지만 메모리에 올린다. 넘는 줄은 읽지 않고 다음 개행까지 건너뛰며 «큰 줄» 로 센다. 시간 예산은 줄마다 본다.
  · 깊은 중첩 JSON 의 RecursionError 도 깨진 줄로 센다. 값은 타입을 확인하고 쓴다(문자열이 아닌 text · prompt 는 str() 로 펼치지 않는다:
    깊은 목록의 repr 이 재귀 한도를 넘는다). usage 는 bool 이 아닌 정수만 쓰고 그 밖(문자열 · inf · NaN)이면 그 응답을 그 행에서 뺀다.
  · 정규식에 넣는 글은 REGEX_MAX_CHARS(20만 자)로 자른다. LaTeX 의 \\[…\\] · \\(…\\) 는 안에 같은 여는 표지가 오면 거기서 멈추게 해
    닫힘 없는 여는 표지가 줄지어도 선형이다(옛 꼴은 20만 자에서 2.6초).
  · 종류가 늘 수 있는 표(M4 의 까닭 · 훅 · 태그, 프로젝트 층화)는 위에서 MAX_ROWS(30)행과 «그 밖 M종 합계» 한 행만 낸다.
  · 대화 기록 훅 차단 태그는 KNOWN_HOOK_TAGS(2026-11-24 실측 쓰기 차단 1,218 · 외부 모델 게이트 61 · git 차단 26 + 계획 확정 게이트)만
    그대로 싣고 나머지는 «기타» 로 모은다. hook-deny.tsv 의 훅 이름은 [A-Za-z0-9_.-]{1,40} 가 아니면 글자를 지우지 않고 «기타» 로 모은다.
  · label 은 fullmatch 로 보고 «.» · «..» 를 거부한다(끝 개행 · 숨은 파일 이름을 받지 않는다).
시험: scripts/tests/test_rule_reduction_metrics.py (pytest, 합성 기록).
REF: knowledge/harness/code-history/scripts__rule_reduction_metrics.py.md (창 · 세션 기록 형식 · «사람이 넣은 글» 판정 · 지표 정의)
"""
from __future__ import annotations

import argparse
import errno
import importlib.util
import json
import os
import re
import stat
import statistics
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

sys.dont_write_bytecode = True   # NEVER: korean_style_check 를 불러올 때 scripts/ 에 __pycache__ 를 남기지 않는다

HARNESS = Path(__file__).resolve().parent.parent
LABEL_RX = re.compile(r"[A-Za-z0-9._-]{1,40}")
DATE_RX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_FILE_BYTES = 4 << 30
MAX_LOG_BYTES = 256 << 20
MAX_LINE_BYTES = 64 << 20
REGEX_MAX_CHARS = 200_000
MAX_ROWS = 30
TIME_BUDGET_S = 600.0
HEAD_LINES = 500
POPUP, ASK = "mcp__decision-popup__ask", "AskUserQuestion"
RECOMMEND_RX = re.compile(r"추천|권장|recommended", re.IGNORECASE)
MODEL_PREFIX_RX = re.compile(r"^\s*(opus|sonnet|haiku|fable)\s*:", re.IGNORECASE)
# NEVER: scripts/external-model-gate.py 의 NON_USER_PREFIXES 와 따로 바꾸지 않는다(그 파일은 훅이라 불러오지 않고 옮겨 적는다)
NON_USER_PREFIXES = ("Base directory for this skill:", "[SYSTEM NOTIFICATION", "[Subagent hand-back]",
                     "This session is being continued from a previous conversation",
                     "Another Claude session sent a message", "[Request interrupted by user")
HUMAN_TAGS = frozenset({"command-name", "command-message", "bash-input", "pasted_content"})
NONHUMAN_TAGS = frozenset({"task-notification", "local-command-stdout", "local-command-stderr", "local-command-caveat",
                           "bash-stdout", "bash-stderr", "system-reminder", "artifact-content-authored-by-others"})
TAG_RX = re.compile(r"<([A-Za-z][\w-]*)")
CODE_RX = re.compile(r"```.*?(?:```|\Z)|`[^`\n]*`", re.DOTALL)
LATEX_RX = re.compile(r"\$\$[^$]{1,2000}?\$\$|\\\[(?:(?!\\\[)[\s\S]){1,2000}?\\\]|\\\((?:(?!\\\()[\s\S]){1,500}?\\\)"
                      r"|\\begin\{[A-Za-z*]{1,20}\}|\$[^$\n]{0,200}?\\[A-Za-z]+[^$\n]{0,200}?\$")
HOOK_ERR_RX = re.compile(r"^PreToolUse:[A-Za-z0-9_]{1,80} hook error: \[([^\]\n]{1,24})\]")
KNOWN_HOOK_TAGS = frozenset({"쓰기 차단", "외부 모델 게이트", "git 차단", "계획 확정 게이트"})
HOOK_NAME_RX = re.compile(r"[A-Za-z0-9_.-]{1,40}")
KIND_RX = re.compile(r"\(([a-z]{1,12})\)\s*$")
T41_RX = re.compile(r"^- (\d{4}-\d{2}-\d{2}) T41: ")
MARKERS = (b'"type":"user"', b'"type":"assistant"', b'"type":"attachment"', b'"compact_boundary"', b'"type":"api-request-shape"')


class UsageError(Exception):
    pass


class BudgetExceeded(Exception):
    pass


def load_circled():
    spec = importlib.util.spec_from_file_location("korean_style_check", Path(__file__).resolve().parent / "korean_style_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.find_circled


def parse_ts(s) -> datetime | None:
    # NEVER: 시간대 없는 시각은 받지 않는다(창 경계가 서버마다 달라진다). hook-deny.tsv 의 +0900 꼴도 읽는다
    if not isinstance(s, str) or not s.strip() or len(s) > 64:
        return None
    s = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", s.strip().replace("Z", "+00:00"))
    try:
        t = datetime.fromisoformat(s)
    except ValueError:
        return None
    return t if t.tzinfo else None


def open_regular(path: str, cap: int | None):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as e:
        return None, "링크" if e.errno == errno.ELOOP else f"열기 오류({type(e).__name__})"
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode):
        os.close(fd)
        return None, "일반 파일 아님"
    if cap is not None and st.st_size > cap:
        os.close(fd)
        return None, "크기 상한 초과"
    return os.fdopen(fd, "rb"), None


def as_str(v) -> str:
    # NEVER: 문자열이 아닌 값을 str() 로 펼치지 않는다: 깊게 중첩된 목록의 repr 이 재귀 한도를 넘는다(2026-11-24 security)
    return v if isinstance(v, str) else ""


def text_of(content) -> tuple[str, bool]:
    if isinstance(content, str):
        return content, False
    if not isinstance(content, list):
        return "", False
    blocks = [b for b in content if isinstance(b, dict)]
    return (" ".join(as_str(b.get("text")) for b in blocks if b.get("type") == "text"),
            any(b.get("type") in ("image", "document") for b in blocks))


def classify_user(d: dict) -> str:
    # REF: knowledge/harness/code-history/scripts__rule_reduction_metrics.py.md «사람이 넣은 글» 판정
    if d.get("isMeta") or d.get("isCompactSummary"):
        return "other"
    o = d.get("origin")
    if o is not None and not (isinstance(o, dict) and o.get("kind") == "human"):
        return "other"
    content = (d.get("message") or {}).get("content") if isinstance(d.get("message"), dict) else None
    if not isinstance(content, (str, list)):
        return "unknown"
    text, media = text_of(content)
    s = text.strip()
    if not s:
        return "human" if media else "other"
    if s.startswith(NON_USER_PREFIXES) or "<cross-session-message" in s:
        return "other"
    if s.startswith("<"):
        m = TAG_RX.match(s)
        tag = m.group(1) if m else ""
        return "human" if tag in HUMAN_TAGS else "other" if tag in NONHUMAN_TAGS else "unknown"
    return "human"


def strings_in(v):
    # NEVER: 키 이름은 세지 않는다. 값만 본다(팝업 스키마의 «recommended» 같은 키를 추천 혼입으로 세지 않게). 재귀 대신 스택(깊은 중첩 입력)
    stack = [v]
    while stack:
        x = stack.pop()
        if isinstance(x, str):
            yield x
        elif isinstance(x, dict):
            stack.extend(x.values())
        elif isinstance(x, list):
            stack.extend(x)


def iter_lines(fh, st: Counter):
    while True:
        raw = fh.readline(MAX_LINE_BYTES + 1)
        if not raw:
            return
        if len(raw) > MAX_LINE_BYTES:
            st["big_lines"] += 1
            while raw and not raw.endswith(b"\n"):
                raw = fh.readline(1 << 20)
            continue
        yield raw


def first_timestamp(fh, st: Counter) -> datetime | None:
    for n, raw in enumerate(iter_lines(fh, st)):
        if n >= HEAD_LINES:
            break
        if b'"timestamp":"' not in raw:
            continue
        try:
            d = json.loads(raw)
        except (ValueError, RecursionError):
            continue
        ts = parse_ts(d.get("timestamp")) if isinstance(d, dict) else None
        if ts:
            return ts
    return None


def iter_main_files(projects: Path, since: datetime, res: dict):
    # NEVER: 내는 꼴과 res 칸을 scripts/agent_usage_report.py 와 따로 바꾸지 않는다(그 파일이 쓰는 계약).
    if not projects.is_dir() or projects.is_symlink():
        res["skipped"]["projects 폴더 없음 · 링크"] += 1
        return
    n = 0
    for pi, pent in enumerate(sorted(os.scandir(projects), key=lambda e: e.name)):
        if pent.is_symlink() or not pent.is_dir(follow_symlinks=False):
            continue
        for fent in sorted(os.scandir(pent.path), key=lambda e: e.name):
            if not fent.name.endswith(".jsonl"):
                continue
            n += 1
            if fent.is_symlink() or not fent.is_file(follow_symlinks=False):
                res["skipped"]["링크 · 일반 파일 아님"] += 1
                continue
            if fent.stat(follow_symlinks=False).st_mtime < since.timestamp():
                res["out_mtime"] += 1
                continue
            fh, why = open_regular(fent.path, MAX_FILE_BYTES)
            if fh is None:
                res["skipped"][why] += 1
                continue
            with fh:
                ts = first_timestamp(fh, Counter())   # WHY: 머리 500줄의 큰 줄은 본문 스트리밍에서 다시 센다
                if ts is None:
                    res["skipped"]["시작 시각 없음"] += 1
                    continue
                res["read"] += 1
                fh.seek(0)
                yield pi, n, fh, ts


def iter_events(fh, start: datetime, st: Counter, deadline: float):
    # NEVER: 사건 꼴과 st 칸을 scripts/agent_usage_report.py 와 따로 바꾸지 않는다(그 파일이 쓰는 계약).
    seen: set[str] = set()
    tools_seen: set[str] = set()
    queued: set[str] = set()
    need_usage = True
    boundary_open = False
    yield ("reload", "start", start)
    for raw in iter_lines(fh, st):
        if time.monotonic() > deadline:
            raise BudgetExceeded
        st["lines"] += 1
        is_user = MARKERS[0] in raw
        if not any(m in raw for m in MARKERS):
            continue
        if is_user and b'"tool_use_id":"' in raw and not (b'"is_error":true' in raw and b" hook error: [" in raw):
            continue
        try:
            d = json.loads(raw)
        except (ValueError, RecursionError):   # WHY: 깊이 1000 넘는 중첩 줄 하나가 집계 전체를 끝내지 않게
            st["bad_lines"] += 1
            continue
        if not isinstance(d, dict) or d.get("isSidechain"):
            continue
        u = d.get("uuid")
        if isinstance(u, str):
            if u in seen:
                st["dup_entries"] += 1
                continue
            seen.add(u)
        kind = d.get("type")
        if kind == "system":
            ts = parse_ts(d.get("timestamp"))
            if d.get("subtype") == "compact_boundary" and ts:
                boundary_open, need_usage = True, True
                yield ("reload", "compact", ts)
        elif kind == "api-request-shape":
            tl = (d.get("shape") or {}).get("tools") if isinstance(d.get("shape"), dict) else None
            if isinstance(tl, list):
                yield ("tools", len(tl))
        elif kind == "assistant":
            m = d.get("message") if isinstance(d.get("message"), dict) else {}
            if d.get("isApiErrorMessage") or m.get("model") == "<synthetic>":
                st["synthetic"] += 1
                continue
            if need_usage and isinstance(m.get("usage"), dict):
                need_usage = False
                yield ("usage", m["usage"])
            content = m.get("content")
            for b in content if isinstance(content, list) else []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and as_str(b.get("text")).strip():
                    yield ("text", b["text"])
                elif b.get("type") == "tool_use":
                    tid = b.get("id")
                    if isinstance(tid, str):
                        if tid in tools_seen:
                            continue
                        tools_seen.add(tid)
                    yield ("tool", b)
        elif kind == "user":
            content = (d.get("message") or {}).get("content") if isinstance(d.get("message"), dict) else None
            if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("is_error"):
                        c = b.get("content")
                        c = " ".join(as_str(x.get("text")) for x in c if isinstance(x, dict)) if isinstance(c, list) else as_str(c)
                        m = HOOK_ERR_RX.match(c[:REGEX_MAX_CHARS])
                        if m:   # WHY: 태그 칸은 도구 결과 글이라 알려진 태그만 그대로 싣는다(24자 자유 문장이 표에 실리지 않게)
                            yield ("hookerr", m.group(1) if m.group(1) in KNOWN_HOOK_TAGS else "기타")
                continue
            if d.get("isCompactSummary"):
                ts = parse_ts(d.get("timestamp"))
                if not boundary_open and ts:
                    need_usage = True
                    yield ("reload", "compact", ts)
                boundary_open = False
            cls = classify_user(d)
            if cls == "human":
                key = text_of(content)[0].strip()
                if key and key in queued:
                    queued.discard(key)
                    continue
                ts = parse_ts(d.get("timestamp"))
                st["human_entries"] += 1
                yield ("turn", ts)
            elif cls == "unknown":
                st["unclassified"] += 1
            else:
                yield ("other", None)
        elif kind == "attachment":
            a = d.get("attachment") if isinstance(d.get("attachment"), dict) else {}
            if a.get("type") != "queued_command":
                continue
            o = a.get("origin")
            if a.get("commandMode") == "prompt" and isinstance(o, dict) and o.get("kind") == "human" and not a.get("isMeta"):
                p = a.get("prompt")
                queued.add((p if isinstance(p, str) else text_of(p)[0]).strip())
                st["human_queued"] += 1
                yield ("turn", parse_ts(d.get("timestamp")))
            else:
                yield ("other", None)


class Session:
    def __init__(self, st: Counter, usage: dict, find_circled, since: datetime, until: datetime, rules_since: datetime | None):
        self.st, self.usage, self.find_circled = st, usage, find_circled
        self.since, self.until, self.rules_since = since, until, rules_since
        self.reload_ts: datetime | None = None
        self.usage_slot: str | None = None
        self.turn: dict | None = None
        self.has_compact = False
        self.window_turns = self.picked = 0

    def in_win(self, ts) -> bool:
        return ts is not None and self.since <= ts < self.until

    def rules_ok(self, ts) -> bool:
        return self.rules_since is None or (ts is not None and ts >= self.rules_since)

    def close_turn(self):
        t, st = self.turn, self.st
        self.turn = None
        if t is None or not t["sel"]:
            return
        st["turns"] += 1
        if t["tool"]:
            st["work_turns"] += 1
            st["m1_hit"] += bool(t["first"])
            st["m1_hit_before_tool"] += bool(t["first"] and t["before_tool"])
            st["m1_tool_after_other_only"] += not t["tool_before_other"]

    def finish(self):
        self.close_turn()
        st = self.st
        st["sessions"] += self.picked > 0
        if self.rules_since is not None and self.window_turns and not self.picked and not self.has_compact:
            st["sessions_dropped_no_compact"] += 1

    def handle(self, ev):
        kind, val = ev[0], ev[-1]
        st, t = self.st, self.turn
        if kind == "reload":
            self.reload_ts = val
            self.has_compact |= ev[1] == "compact"
            self.usage_slot = None
            if self.in_win(val):
                st[f"reload_{ev[1]}"] += 1
                if self.rules_ok(val):
                    self.usage_slot = ev[1]
        elif kind == "usage":
            if self.usage_slot:
                self.usage[self.usage_slot].append(val)
                self.usage_slot = None
        elif kind == "turn":
            self.close_turn()
            sel = False
            if self.in_win(val):
                st["turns_window"] += 1
                self.window_turns += 1
                sel = self.rules_ok(self.reload_ts)
                st["turns_excluded_rules"] += not sel
                self.picked += sel
            self.turn = {"sel": sel, "first": None, "before_tool": False, "tool": False, "other": False, "tool_before_other": False}
        elif t is None or not t["sel"]:
            return
        elif kind == "other":
            t["other"] = True
        elif kind == "text":
            st["text_blocks"] += 1
            st["m3_circled"] += len(self.find_circled(val, html=False))   # WHY: find_circled 는 스스로 20만 자로 자른다
            st["m3_latex"] += len(LATEX_RX.findall(CODE_RX.sub(" ", val[:REGEX_MAX_CHARS])))
            if t["first"] is None:
                t["first"] = "[이해]" in val
                t["before_tool"] = not t["tool"]
        elif kind == "hookerr":
            st[f"m4_transcript:{val}"] += 1
        elif kind == "tool":
            self.tool_use(val)

    def tool_use(self, b: dict):
        st, t, name = self.st, self.turn, b.get("name")
        inp = b.get("input") if isinstance(b.get("input"), dict) else {}
        t["tool_before_other"] = t["tool_before_other"] or not t["other"]
        t["tool"] = True
        if name in (POPUP, ASK):
            st[f"m2_calls:{name}"] += 1
            st[f"m2_hits:{name}"] += any(RECOMMEND_RX.search(s[:REGEX_MAX_CHARS]) for s in strings_in(inp))
        if name in ("Agent", "Task"):
            st["m7_calls"] += 1
            desc, model = inp.get("description"), inp.get("model")
            m = MODEL_PREFIX_RX.match(desc) if isinstance(desc, str) else None
            has_model = isinstance(model, str) and bool(model)
            if not m:
                st["m7_no_prefix"] += 1
            elif has_model and m.group(1).lower() != model.strip().lower():
                st["m7_mismatch"] += 1
            else:
                st["m7_prefix_ok"] += 1
                st["m7_prefix_ok_no_model"] += not has_model
            st["m7_depth"] += "[SKILL_DEPTH" in as_str(inp.get("prompt"))


def scan_transcripts(projects: Path, since: datetime, until: datetime, rules_since: datetime | None, deadline: float, find_circled) -> dict:
    res = {"projects": {}, "usage": {"start": [], "compact": []}, "skipped": Counter(), "out_mtime": 0, "read": 0, "partial": None}
    for pi, n, fh, start in iter_main_files(projects, since, res):
        if time.monotonic() > deadline:
            res["partial"] = n
            return res
        st = res["projects"].setdefault(pi, Counter())
        s = Session(st, res["usage"], find_circled, since, until, rules_since)
        try:
            for ev in iter_events(fh, start, st, deadline):
                s.handle(ev)
        except BudgetExceeded:
            res["partial"] = n
            s.finish()
            return res
        s.finish()
    return res


def local_dates(since: datetime, until: datetime) -> tuple[date, date]:
    # WHY: 날짜만 있는 기록(_evolve/candidates.tsv · _audit/history.md)은 서버 시간대 날짜로 쓰여 있다
    return since.astimezone().date(), (until - timedelta(microseconds=1)).astimezone().date()


def read_log_lines(path: Path, facts: list, name: str, hc: Counter):
    fh, why = open_regular(str(path), MAX_LOG_BYTES) if path.exists() or path.is_symlink() else (None, "없음")
    if fh is None:
        facts.append(f"{name}: {why}")
        return
    with fh:
        for raw in iter_lines(fh, hc):
            yield raw.decode("utf-8", "replace").rstrip("\n")


def scan_harness(home: Path, since: datetime, until: datetime) -> tuple[Counter, list]:
    hc, facts = Counter(), []
    d0, d1 = local_dates(since, until)

    def in_win(s):
        t = parse_ts(s)
        return t is not None and since <= t < until

    def in_days(s):
        try:
            return DATE_RX.match(s) is not None and d0 <= date.fromisoformat(s) <= d1
        except ValueError:
            return False

    for ln in read_log_lines(home / "_audit/plan-confirm-gate.tsv", facts, "plan-confirm-gate.tsv", hc):
        c = ln.split("\t")
        if len(c) >= 4 and in_win(c[0]):
            m = KIND_RX.search(c[3][-REGEX_MAX_CHARS:])
            hc[f"plan:{'판정 불가' if '판정 불가' in c[3] else m.group(1) if m else '기타'}"] += 1
    hook_deny = home / "_audit/hook-deny.tsv"
    if hook_deny.exists() or hook_deny.is_symlink():
        hc["hook_deny_present"] = 1
        for ln in read_log_lines(hook_deny, facts, "hook-deny.tsv", hc):
            c = ln.split("\t")
            if len(c) >= 4 and in_win(c[0]):
                # NEVER: 허용 글자가 아닌 이름은 글자를 지워 싣지 않는다. «기타» 로 모은다(경로 꼴이 «/» 만 빠진 채 실리던 qa 지적)
                hc[f"hookdeny:{c[3] if HOOK_NAME_RX.fullmatch(c[3]) else '기타'}"] += 1
    for ln in read_log_lines(home / "_evolve/prompts.jsonl", facts, "prompts.jsonl", hc):
        try:
            d = json.loads(ln)
        except (ValueError, RecursionError):
            hc["bad_log_lines"] += 1
            continue
        hc["prompts"] += isinstance(d, dict) and in_win(d.get("ts"))
    for ln in read_log_lines(home / "_evolve/candidates.tsv", facts, "candidates.tsv", hc):
        c = ln.split("\t")
        hc["t12"] += len(c) >= 3 and c[1] == "T12" and in_days(c[2])
    for ln in read_log_lines(home / "_audit/history.md", facts, "history.md", hc):
        m = T41_RX.match(ln)
        hc["t41"] += bool(m and in_days(m.group(1)))
    for ln in read_log_lines(home / "_audit/agent-spawn.log", facts, "agent-spawn.log", hc):
        c = ln.split("\t")
        hc["spawn_post"] += len(c) >= 2 and c[1] == "post" and in_win(c[0])
    return hc, facts


def ratio(n: int, d: int, per: int = 0) -> str:
    if d <= 0:
        return "해당 없음"
    return f"{100 * n / d:.1f}%" if per == 0 else f"{per * n / d:.2f}"


def cell(s) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", " ", str(s)).replace("|", "\\|")


def cap_rows(items: list) -> tuple[list, int, int]:
    rest = items[MAX_ROWS:]
    return items[:MAX_ROWS], len(rest), sum(v for _, v in rest)


def token(u: dict, key: str) -> int | None:
    v = u.get(key)
    if v is None:
        return 0
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def quartiles(xs: list[int]) -> tuple[str, str, str]:
    if not xs:
        return ("해당 없음",) * 3
    if len(xs) == 1:
        return (str(xs[0]),) * 3
    q1, q2, q3 = statistics.quantiles(xs, n=4, method="inclusive")
    return f"{q2:g}", f"{q1:g}", f"{q3:g}"


def render(label: str, since: datetime, until: datetime, rules_since: datetime | None, tr: dict, hc: Counter, facts: list,
           elapsed: float) -> str:
    tot = Counter()
    for st in tr["projects"].values():
        tot.update(st)
    turns, work = tot["turns"], tot["work_turns"]
    skipped = sum(tr["skipped"].values())
    why = " · ".join(f"{k} {v}" for k, v in sorted(tr["skipped"].items())) or "없음"
    status = (f"부분 결과(시간 예산 {TIME_BUDGET_S:g}초 초과, {tr['partial']}번째 파일에서 멈춤)" if tr["partial"] else "완전")
    d0, d1 = local_dates(since, until)
    rs = rules_since.isoformat() if rules_since else "없음(창 안 모든 턴)"
    dropped = tot["sessions_dropped_no_compact"] if rules_since else "해당 없음(--rules-since 없음)"
    lines = [
        f"# 상시 규칙 축소 지표: {label}", "",
        (f"- 창: {since.isoformat()} 이상 ~ {until.isoformat()} 미만(턴 시작 시각 기준, 하네스 기록은 줄의 시각 기준, "
         f"날짜만 있는 기록은 {d0} ~ {d1}) · 규칙 읽은 시점 하한(--rules-since): {rs}"),
        (f"- 턴: 창 안 {tot['turns_window']} · --rules-since 로 빠짐 {tot['turns_excluded_rules']} · 고른 턴 {turns} · "
         f"재로드 지점(창 안) 세션 시작 {tot['reload_start']} · compact {tot['reload_compact']} · compact 가 없어 통째로 빠진 세션 {dropped} · "
         "resume 은 재로드로 치지 않음(기록에서 알아볼 표지 미확인, 참고 건수 없음)"),
        (f"- 세션(고른 턴이 있는) {tot['sessions']} · 프로젝트 {sum(1 for s in tr['projects'].values() if s['sessions'])} · 읽은 파일 {tr['read']} · "
         f"창 밖 파일(수정 시각) {tr['out_mtime']} · 건너뛴 파일 {skipped}(까닭: {why})"),
        (f"- 읽은 파일 전체: 깨진 줄 {tot['bad_lines']} · 큰 줄(읽지 않음) {tot['big_lines']} · 중복 항목(같은 uuid) {tot['dup_entries']} · "
         f"API 오류 대리 항목 {tot['synthetic']} · 사람 글 {tot['human_entries']}(턴 도중 대기 글 {tot['human_queued']} 별도) · "
         f"분류 불가 user 항목 {tot['unclassified']}"),
        f"- 하네스 기록: {' · '.join(facts) if facts else '모두 읽음'} · 깨진 줄 {hc['bad_log_lines']} · 큰 줄(읽지 않음) {hc['big_lines']}",
        f"- 상태: {status} · 걸린 시간 {elapsed:.1f}초 · subagent 기록은 열지 않음(지표가 main 기록만 씀)", "",
        "| 지표 | 값 | 분자 | 분모 | 비고 |", "|---|---|---|---|---|",
    ]

    def row(name, n, d, per=0, note=""):
        lines.append(f"| {cell(name)} | {ratio(n, d, per)} | {n} | {d} | {cell(note)} |")

    def kind_rows(src: Counter, prefix: str, name: str, note: str) -> bool:
        items = sorted(((k[len(prefix):], v) for k, v in src.items() if k.startswith(prefix)), key=lambda x: (-x[1], x[0]))
        shown, rest_n, rest_sum = cap_rows(items)
        for k, v in shown:
            row(name.format(k), v, work, 100, note)
        if rest_n:
            row(name.format(f"그 밖 {rest_n}종 합계"), rest_sum, work, 100, note)
        return bool(items)

    nb = "재로드 경계 미적용"
    row("M1 [이해] 부착률", tot["m1_hit"], work, note=f"첫 tool_use 앞 {tot['m1_hit_before_tool']} · "
        f"tool_use 가 사람 글 아닌 턴 시작 뒤에만 있는 작업성 턴 {tot['m1_tool_after_other_only']} · 고른 턴 {turns}")
    for name, label_ in ((POPUP, "결정 팝업"), (ASK, "선택 창")):
        row(f"M2 {label_} 추천 혼입", tot[f"m2_hits:{name}"], tot[f"m2_calls:{name}"], note=f"{name} 입력 문자열 값의 추천 · 권장 · recommended")
    row("M3 원문자 (100턴당)", tot["m3_circled"], turns, 100, f"assistant 텍스트 블록 {tot['text_blocks']} · find_circled 재사용")
    row("M3 LaTeX 꼴 (100턴당)", tot["m3_latex"], turns, 100, "코드펜스 · 인라인 코드 밖")
    lines.append("| M3 반말 종결 비율 | 미측정(판정기 없음) | - | - | korean_style_check.py 에 반말 판정 함수가 없음 |")
    if not kind_rows(hc, "plan:", "M4 계획 확정 경고 {} (작업성 100턴당)", f"plan-confirm-gate.tsv · {nb}"):
        row("M4 계획 확정 경고 (작업성 100턴당)", 0, work, 100, f"plan-confirm-gate.tsv 창 안 줄 없음 · {nb}")
    if not kind_rows(hc, "hookdeny:", "M4 hook-deny {} (작업성 100턴당)", f"hook-deny.tsv · {nb}"):
        lines.append(f"| M4 hook-deny | 해당 없음 | - | - | {'창 안 줄 없음' if hc['hook_deny_present'] else 'hook-deny.tsv 없음'} · {nb} |")
    if not kind_rows(tot, "m4_transcript:", "M4 대화 기록 훅 차단 [{}] (작업성 100턴당)", "추가 행: 고른 턴의 PreToolUse hook error 도구 결과"):
        row("M4 대화 기록 훅 차단 (작업성 100턴당)", 0, work, 100, "추가 행: 고른 턴 안 차단 없음")
    row("M5 T12 후보 (프롬프트 100개당)", hc["t12"], hc["prompts"], 100, f"candidates.tsv 생성일 날짜 단위 · {nb}")
    row("M6 T41 기록 (spawn 100개당)", hc["t41"], hc["spawn_post"], 100, f"history.md 날짜 단위 · agent-spawn.log post 줄 · {nb}")
    row("M7 description 모델 접두 일치", tot["m7_prefix_ok"], tot["m7_calls"],
        note=f"접두 없음 {tot['m7_no_prefix']} · 불일치 {tot['m7_mismatch']} · 일치 중 model 인자 없음 {tot['m7_prefix_ok_no_model']}")
    row("M7 [SKILL_DEPTH 포함", tot["m7_depth"], tot["m7_calls"])
    for slot, where in (("start", "세션 시작"), ("compact", "compact 직후")):
        for key, name in (("input_tokens", "입력 토큰"), ("cache_creation_input_tokens", "cache 생성 토큰"), (None, "합계(입력 + cache 생성 + 읽기)")):
            keys = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens") if key is None else (key,)
            vals = [[token(u, k) for k in keys] for u in tr["usage"][slot] if isinstance(u, dict)]
            xs = [sum(v) for v in vals if None not in v]
            med, q1, q3 = quartiles(xs)
            lines.append(f"| 이득 {where} 첫 응답 {name} 중앙값 | {med} | - | {len(xs)} | 사분위 {q1} ~ {q3}{' · 추가 행' if key is None else ''} |")

    lines += ["", "## 프로젝트별 (작업성 턴 많은 순, 번호만)", "",
              "| 프로젝트 | 세션 | 턴 | 작업성 턴 | M1 | M2 혼입/호출 | M3 원문자 | M3 LaTeX | M7 접두 일치 |", "|---|---|---|---|---|---|---|---|---|"]
    order = sorted((s for s in tr["projects"].values() if s["sessions"]), key=lambda s: (-s["work_turns"], -s["turns"], -s["sessions"]))
    rest = Counter()
    for s in order[MAX_ROWS:]:
        rest.update(s)
    shown = [(f"P{i}", s) for i, s in enumerate(order[:MAX_ROWS], 1)] + ([(f"그 밖 {len(order) - MAX_ROWS}개 합계", rest)] if rest else [])
    for name, st in shown:
        hits = st[f"m2_hits:{POPUP}"] + st[f"m2_hits:{ASK}"]
        calls = st[f"m2_calls:{POPUP}"] + st[f"m2_calls:{ASK}"]
        lines.append(f"| {name} | {st['sessions']} | {st['turns']} | {st['work_turns']} | {ratio(st['m1_hit'], st['work_turns'])} | "
                     f"{hits}/{calls} | {st['m3_circled']} | {st['m3_latex']} | {ratio(st['m7_prefix_ok'], st['m7_calls'])} |")
    return "\n".join(lines) + "\n"


def open_in(home: Path, parts: tuple[str, ...], name: str, flags: int) -> int:
    fd = os.open(os.path.realpath(home), os.O_RDONLY | os.O_DIRECTORY)
    try:
        for p in parts:
            try:
                os.mkdir(p, 0o700, dir_fd=fd)
            except FileExistsError:
                pass
            try:
                nfd = os.open(p, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except OSError as e:
                raise UsageError(f"{p} 가 링크이거나 폴더가 아니라 쓰기를 거부했습니다({type(e).__name__})") from e
            os.close(fd)
            fd = nfd
        try:
            return os.open(name, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=fd)
        except FileExistsError as e:
            raise UsageError("기록 파일이 이미 있어 덮어쓰지 않습니다") from e
        except OSError as e:
            raise UsageError(f"기록 파일을 열지 못했습니다({type(e).__name__}, 링크 거부 포함)") from e
    finally:
        os.close(fd)


def write_out(home: Path, label: str, text: str) -> None:
    fd = open_in(home, ("_audit", "rule-reduction"), f"{label}.md", os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        os.fchmod(fd, 0o600)
        fh.write(text)


def mark_window(home: Path, label: str, end: str) -> None:
    fd = open_in(home, ("_usage",), "rule-reduction-window", os.O_WRONLY | os.O_CREAT)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            raise UsageError("창 파일이 일반 파일이 아니거나 하드 링크라 거부했습니다")
        os.fchmod(fd, 0o600)
        os.ftruncate(fd, 0)
        os.write(fd, f"{label}\t{end}\n".encode())
    finally:
        os.close(fd)


def parse_args(argv):
    ap = argparse.ArgumentParser(description="상시 규칙 축소 실험 지표 집계(읽기 전용)")
    ap.add_argument("--since")
    ap.add_argument("--until")
    ap.add_argument("--rules-since", help="규칙 읽은 시점(세션 시작 · compact 경계)이 이 시각 이상인 턴만 센다")
    ap.add_argument("--label", default="run")
    ap.add_argument("--home", type=Path, default=HARNESS, help="하네스 홈(projects · _audit · _evolve · _usage 의 뿌리)")
    ap.add_argument("--out", action="store_true", help="<home>/_audit/rule-reduction/<label>.md 에도 쓴다(덮어쓰지 않음)")
    ap.add_argument("--mark-window", metavar="LABEL")
    ap.add_argument("--end", metavar="YYYY-MM-DD")
    a = ap.parse_args(argv)
    for lab in (a.label, a.mark_window):
        if lab is not None and (not LABEL_RX.fullmatch(lab) or lab in (".", "..")):
            raise UsageError("label 은 [A-Za-z0-9._-]{1,40} 만 받고 «.» · «..» 는 받지 않습니다")
    if not a.home.is_dir():
        raise UsageError("--home 폴더가 없습니다")
    if a.mark_window is not None:
        try:
            ok = bool(a.end and DATE_RX.match(a.end) and date.fromisoformat(a.end))
        except ValueError:
            ok = False
        if not ok:
            raise UsageError("--mark-window 에는 --end YYYY-MM-DD(있는 날짜)가 필요합니다")
        return a
    a.since_t, a.until_t = parse_ts(a.since), parse_ts(a.until)
    if a.since_t is None or a.until_t is None or not a.since_t < a.until_t:
        raise UsageError("--since · --until 은 시간대가 붙은 ISO 시각이고 since < until 이어야 합니다")
    a.rules_t = parse_ts(a.rules_since) if a.rules_since is not None else None
    if a.rules_since is not None and a.rules_t is None:
        raise UsageError("--rules-since 는 시간대가 붙은 ISO 시각이어야 합니다")
    return a


def main(argv=None) -> int:
    try:
        a = parse_args(argv)
        if a.mark_window is not None:
            mark_window(a.home, a.mark_window, a.end)
            print(f"창 표지를 썼습니다: _usage/rule-reduction-window ({a.mark_window} · {a.end})")
            return 0
        t0 = time.monotonic()
        tr = scan_transcripts(a.home / "projects", a.since_t, a.until_t, a.rules_t, t0 + TIME_BUDGET_S, load_circled())
        hc, facts = scan_harness(a.home, a.since_t, a.until_t)
        text = render(a.label, a.since_t, a.until_t, a.rules_t, tr, hc, facts, time.monotonic() - t0)
        if a.out:
            write_out(a.home, a.label, text)
        sys.stdout.write(text)
        if a.out:
            print(f"\n기록 파일을 썼습니다: _audit/rule-reduction/{a.label}.md")
        return 0
    except UsageError as e:
        print(f"오류: {e}", file=sys.stderr)
        return 2
    except SystemExit as e:
        return 2 if e.code else 0
    except Exception as e:  # noqa: BLE001
        # NEVER: 예외 글을 내지 않는다(경로 · 본문이 실릴 수 있어 종류 이름만 낸다)
        print(f"오류: 예기치 못한 예외({type(e).__name__})", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
