#!/usr/bin/env python3
"""launch_queue.py — 판이 GPU 보다 많을 때 사용자가 승인한 대기 목록의 다음 판을 와쳐가 자동 발사 (2026-10-01 신설)

의뢰서 `intent/2026-10-01-watcher-auto-launch-queue.md`, 계획 `docs/superpowers/plans/2026-10-01-watcher-auto-launch-queue.md`
의 Phase 1~5 구현이다. 파이썬 3.10 표준 라이브러리만 쓴다(시스템 python3, tomllib 금지).

사용
  launch_queue.py table   <목록.json> [--gpus 0,1,2]      승인 표(판 · 목적 · 기준판 · 변경 사항 · 배치) 출력
  launch_queue.py place   <목록.json> --gpus 0,1,2        판 < GPU 일 때 묶음 배치 «제안»(표 출력만, 발사 없음)
  launch_queue.py approve <목록.json> [--session 이름]     사용자가 «이대로»를 고른 뒤: 목록 sha256 을 승인으로 기록(halted 해제)
  launch_queue.py start   <목록.json> --gpus 0,1,2         지정 GPU 마다 첫 판을 올린다(GPU 는 사용자 배정이라 필수 인자)
  launch_queue.py next --queue <목록.json> --item ID --gpu N --exit C [--attempt K]   와쳐 --on-exit 가 부른다(끝난 판 기록 → 다음 판 발사)
                                                        --attempt: 발사한 시도 번호(launch-set --queue-attempt 가 결박). 현재 시도와 다르거나 이미 처리된 보고는 무시한다
  launch_queue.py status  <목록.json>                      판별 상태
  launch_queue.py wait-event <목록.json> [--timeout 6900] [--interval 30]   처리 안 된 이벤트가 생길 때까지 막고, 한 줄 JSON 으로 출력(rc 0) · 시간 만료 rc 3
  launch_queue.py events  <목록.json> [--pending]          이벤트 목록(소비하지 않음 — 예약 점검용)
  launch_queue.py relaunch <목록.json> --item ID --fix-note '…' [--gpus 0,1]   needs-fix 판을 판당 1회 다시 올린다(목록 파일 불변)
  launch_queue.py release <목록.json> --item ID --reason '…' [--by 이름] [--then-next]   «살아 있을 수 있음» 표시를 사람이 내린다
  launch_queue.py summary <목록.json>                      목록이 끝났으면 실패 판 요약 표
  launch_queue.py halt    <목록.json> --reason '…'         정지 스위치: 이후 start·next·relaunch 발사 0건(해제는 approve 재실행뿐)
  launch_queue.py include-gpu <목록.json> --gpu N --reason '…' [--then-next]   연속 재실패로 제외된 GPU 를 다시 사슬에 넣는다

이벤트 종류(<이름>.events/*.json, wait-event 가 소비 표시로 .consumed 를 붙인다): needs-fix · queue-changed · launch-blocked ·
  launch-failed · gpu-excluded · all-gpus-excluded · halted · queue-finished · watcher-lost(도는 판의 와쳐 PID 가 죽음)
와쳐 종료 코드(next --exit): 0 완료 · 2 비정상 종료 · 3 평가 실패 · 4 와쳐 타임아웃 · 5 memguard 발사 거부 · 6 평가 시간 초과 · 7 와쳐가 신호로 중단.
  4·6·7 은 «학습(또는 평가)이 살아 있을 수 있음» 보류라 그 GPU 에 다음 판을 올리지 않는다(사람이 release 로 푼다, D7).
환경변수: LAUNCH_QUEUE_OVERSIGHT = 감시 서명 스크립트 경로(기본 scripts/oversight-append.sh, 시험이 바꿔 쓴다)

파일(목록 `<프로젝트>/.claude/launch-queue/<이름>.json` 옆, 이름 = 파일 줄기)
  <이름>.state.json  진행 상태(이 도구만 씀)   <이름>.lock  flock   <이름>.events/  세션이 읽을 이벤트
  <이름>.launch/<id>-<시도>.sh  판마다 만든 발사 스크립트 + <id>-<시도>.rc(launch-set.sh 종료 코드)

■ 판단 근거 (이식)
  · 명령은 문자열이 아니라 argv 배열이다. 셸 문자열 조립·인용 사고를 없애고, 승인된 목록 밖의 문자열이 셸에 닿지 않게 한다.
    발사 스크립트의 인자는 전부 shlex.quote 로 인용한다.
  · 승인 = 목록 파일 바이트의 sha256. `next` 는 매번 현재 파일 해시를 승인 해시와 대조하고, 다르면 아무것도 올리지 않고
    state 에 halted 를 남겨 알린다. 목록이 깨졌어도(JSON 오류) 해시 대조가 먼저라 «바뀌었다»로 멈춘다. halted 는 `approve` 전까지 유지한다.
  · 중복 발사 방지 = flock + 예약. 판 고르기·예약(status=launching)은 락 안에서, 발사(최대 수 분)는 락 밖에서 하고, 결과는 다시 락 안에서 적는다.
    그래서 두 판이 같은 순간 끝나도 같은 판이 두 번 올라가지 않고, 발사 중에도 다른 `next` 가 막히지 않는다.
  · tmux 배치(2026-10-02 사용자 규칙, background-task.md § 세션 번호 = GPU 번호): 세션 이름은 `<접두><그 판의 GPU 번호>` 하나뿐이다. 세션이 없으면
    new-session 으로 만들어 그 첫 창을 쓰고, 있으면 new-window 로 창을 더한다(그 밖의 번호로 새 세션을 만들지 않는다). 창 번호는 tmux 가 정해 -P -F 로 받고,
    send-keys 는 `=세션:창번호` 로 그 창에만 보낸다. 예전의 «현재 최대 번호 + 1» 세션 번호를 락 안에서 예약하던 일은 없어졌다(세션은 GPU 번호로 정해지고
    창 번호는 tmux 가 주므로 번호 경합이 없다). 같은 GPU 에 두 판이 동시에 오르는 일은 락 안의 occupant 검사와 예약(launching)이 막는다.
    launch-set `--name` 은 같은 세션을 여러 판이 쓰므로 `<세션>-<판 id>-<시도>` 로 판·시도마다 다르게 하고(state·와쳐 로그·memguard 스코프 이름이 거기서 나온다),
    state 의 tmux 필드에는 `세션:창번호` 를 적는다(옛 state 는 세션 이름만이고 어디서도 파싱하지 않아 그대로 읽힌다).
  · 발사 결과는 launch-set.sh 종료 코드로 판정한다(스크립트가 .rc 파일로 남김). 0=발사+검증 통과 · 1=검증 실패 · 76=GPU·CPU 사전검사 거부
    · 65=시작 직후 종료(로그에 memguard 거부가 있으면 거부, 아니면 크래시).
  · 사전검사는 두 번 한다. 후보 고르기는 gpu_preflight.decide 로 «VRAM 이 들어가는가»만 빠르게 보고(표본 없음), 실제 사용률·CPU 표본은 launch-set.sh 가 한다.
  · 외부 효과(tmux·알림·감시 서명·GPU 조회)는 백엔드(TmuxBackend / 시험용 FakeBackend)로 분리했다.

  · 비정상 종료(exit 2)는 needs-fix + 이벤트로 세션을 깨우고 그 GPU 에는 다음 판을 계속 올린다. 세션이 원인을 고쳐 `relaunch` 하면 판당 1회만
    다시 올린다(재발사는 승인 목록을 바꾸지 않는다 — 발사 인자를 바꿨으면 해시가 달라져 «재승인 필요»로 거부된다). 다시 exit 2 면 그 판만 failed.
    D8(2026-10-01): relaunch 는 세션이 원인을 확인한 뒤에만 부른다. 허용 원인은 background-task.md § 실패 시 원인 분석의 «경로·import·인자 오류»뿐이고
    로직 오류·메모리 부족·권한 오류는 재발사하지 않고 사용자에게 보고한다. 이 도구는 로그를 읽어 원인을 자동 분류하지 않는다(분류기는 규모가 커서 보류) —
    분류 책임은 needs-fix 이벤트의 hint 를 받는 세션에 있고, 판당 1회 한정과 승인 해시 대조가 그 바깥 안전장치다.
    같은 GPU 에서 서로 다른 두 판이 연속으로 «재발사 후 재실패»하면 그 GPU 만 사슬에서 뺀다(카드 결함·메모리 문제로 목록이 한 GPU 에서 소진되는 것 방지).
  · 기다림 판정(Phase 4, 의뢰서 결정 2·계획서 142~145줄): 지금 빈 GPU 가 느린 기종이고, 빠른 기종 GPU 중 «남은 시간 + 빠른 기종 소요 < 빈 기종 소요»인 것 수 m 이
    미발사 판 수 k 이상(k ≤ m)이면 그 GPU 를 비워 두고 빠른 GPU 를 기다린다. 판마다 예상 시간은 신고받지 않고, 같은 목록의 끝난·도는 판의 «경과 ÷ 진행률»을
    기종별 중앙값으로 쓴다. 한 기종이라도 자료가 없거나 남은 시간을 못 읽으면 기다리지 않는다. 비워 둔 GPU 는 state 의 idle_gpus 에 적고 다음
    next·relaunch·release 때 다시 평가한다(빠른 GPU 쪽이 실패·타임아웃·점유로 끝나 깨워 줄 next 가 발사하지 않아도 판이 굶지 않게).
    진행 로그는 파일 끝 256KB 만 읽고 락 밖에서 읽는다. progress_regex 는 approve 때 컴파일·그룹 2개·중첩 한정자(재앙적 역추적) 검사를 한다(파이썬 re 에는 시간 제한이 없다).
  · 배치 제안(Phase 5)은 표시만 한다. 프로젝트 train.env 가 DDP_READY·PROP_BATCH_READY 를 선언하지 않았으면 판당 1장으로 내리고 이유를 적는다.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import fcntl
import glob
import hashlib
import importlib.util
import json
import math
import os
import re
import shlex
import statistics
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
LAUNCH_SET = HERE / "launch-set.sh"
HARNESS = HERE.parents[1]
_spec = importlib.util.spec_from_file_location("gpu_preflight", HERE / "gpu_preflight.py")
gp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gp)

ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")   # fullmatch 로만 쓴다($ 는 끝 개행을 통과시킨다). 첫 글자 영숫자(선행 - · . 금지), `..` 는 is_safe_name 이 막는다
CTRL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")         # 개행·ESC·탭 등 제어문자 — 표·알림·로그에 섞이면 화면을 속인다
MIN_INTERVAL = 5.0          # wait-event 폴링 간격 하한(초). 시험이 낮춰 쓴다
LOG_TAIL_BYTES = 256 * 1024  # 로그는 끝 이만큼만 읽는다(전체 read 금지)
PROGRESS_MAX = 10**7        # 진행률 현재·전체의 상한(거대 수는 못 읽은 것으로 취급)
REQUIRED = ("id", "purpose", "baseline", "change", "argv", "expect", "log_dir", "vram_gb", "cpu_cores", "done_regex", "eval_cmd")
OPTIONAL = ("done_log", "log", "memguard_args", "watcher_args", "progress_regex", "intent")
LAUNCH_WAIT_SEC = 300       # launch-set.sh 한 번: 사전검사 표본 60 + 안정화 30 + settle 10 + 와쳐 5 에 여유
STALE_RESERVE_SEC = 900     # launching 예약이 이보다 오래되면 next 가 죽은 것으로 보고 닫는다
MAX_REFUSALS = 3            # 같은 판이 거부만 반복하며 목록을 맴도는 것을 막는 상한
PLACEMENT_TABLE = HERE / "placement_table.json"
TERMINAL = ("done", "failed", "launch-failed", "eval-failed", "timeout", "removed")   # 목록 종료 판정에서 «끝난» 상태(needs-fix 는 세션이 고칠 기회라 제외). removed = 재승인 때 목록에서 빠진 queued 판(종료 판정·기다림 k 에서 제외)
HOLD_CODES = (4, 6, 7)      # 와쳐 종료 코드 중 «학습·평가가 살아 있을 수 있음» 보류(4 타임아웃 · 6 평가 시간 초과 · 7 와쳐 신호 중단)
EPOCH_RE = re.compile(r"[Ee]poch\D{0,3}(\d+)\s*/\s*(\d+)")                # progress_regex 가 없을 때 쓰는 에폭 진행 문구 «Epoch 12/60»
MEMGUARD_REFUSED = re.compile(r"\[memguard\].*(거부|불가)")   # train-watcher.sh 가 쓰는 판정과 같은 문구


class QueueError(Exception):
    """목록 형식·승인·환경 오류 — main 이 메시지를 찍고 code(기본 2, 인자 오류는 64)로 끝낸다."""

    def __init__(self, msg: str, code: int = 2):
        super().__init__(msg)
        self.code = code


# ───────────────────────── 목록 읽기·검증 ─────────────────────────

def is_safe_name(v) -> bool:
    """판 id·목록 name 검증. 발사 스크립트 주석·파일명·세션 이름에 그대로 들어가므로 개행·공백·경로 조각을 막는다."""
    return isinstance(v, str) and bool(ID_RE.fullmatch(v)) and ".." not in v


def has_control(v) -> bool:
    """문자열(중첩 list·dict 포함) 어디든 제어문자가 있는가."""
    if isinstance(v, str):
        return bool(CTRL_RE.search(v))
    if isinstance(v, list):
        return any(has_control(x) for x in v)
    if isinstance(v, dict):
        return any(has_control(k) or has_control(x) for k, x in v.items())
    return False


def check_progress_regex(rx: str) -> None:
    """progress_regex 검사: 길이 ≤ 200 · 컴파일 · 그룹 정확히 2개(현재·전체) · 중첩 한정자 금지.

    파이썬 re 에는 시간 제한이 없어 재앙적 역추적 패턴(`(a+)+`)이 와쳐를 멈출 수 있다. 읽는 쪽을 제한할 수 없으니 승인 때 막는다.
    """
    if len(rx) > 200:
        raise QueueError("progress_regex 가 200자를 넘습니다")
    try:
        pat = re.compile(rx)
    except re.error as e:
        raise QueueError(f"progress_regex 를 컴파일할 수 없습니다: {e}")
    if pat.groups != 2:
        raise QueueError(f"progress_regex 는 그룹이 정확히 2개(현재·전체)여야 합니다(현재 {pat.groups}개)")
    if re.search(r"\([^()]*[+*][^()]*\)\s*[+*{]", rx):
        raise QueueError("progress_regex 에 중첩 한정자((…+)+ 꼴)가 있어 거부합니다 — 역추적 폭주 위험")


def parse_queue(raw: bytes, stem: str, check_log_dup: bool = True) -> dict:
    """목록 JSON 바이트를 검증해 돌려준다. 형식 오류는 QueueError.

    check_log_dup: 판 사이 로그 경로 중복 검사. 승인 시점(approve·table·place)에만 켠다 — 이 검사가 생기기 전에 승인돼 이미 도는 목록이
    다음 판을 올리는 발사 경로(launch_one)에서 거부되면 자동 사슬이 끊기므로 거기서는 끈다(2026-10-01 P6 검수)."""
    try:
        q = json.loads(raw)
    except ValueError as e:
        raise QueueError(f"목록이 JSON 이 아닙니다: {e}")
    if has_control(q):
        raise QueueError("목록의 문자열에 제어문자(개행·ESC·탭 등)가 있습니다 — 표·알림·로그를 속일 수 있어 거부합니다")
    if not isinstance(q, dict) or not isinstance(q.get("items"), list) or not q["items"]:
        raise QueueError("목록은 {name, items:[…]} 이고 items 가 비어 있으면 안 됩니다")
    if not is_safe_name(q.get("name")):
        raise QueueError(f"name({q.get('name')!r}) 은 [A-Za-z0-9][A-Za-z0-9._-]* 이고 '..' 를 담지 않아야 합니다")
    if q.get("name") != stem:
        raise QueueError(f"name({q.get('name')!r}) 이 파일 이름({stem!r})과 달라야 할 이유가 없습니다 — 일치시키세요")
    seen = set()
    for i, it in enumerate(q["items"]):
        if not isinstance(it, dict):
            raise QueueError(f"items[{i}] 가 객체가 아닙니다")
        tag = f"items[{i}]({it.get('id', '?')})"
        for k in REQUIRED:
            if k not in it:
                raise QueueError(f"{tag}: 필수 항목 {k} 없음")
        extra = set(it) - set(REQUIRED) - set(OPTIONAL)
        if extra:
            raise QueueError(f"{tag}: 알 수 없는 항목 {sorted(extra)} (오타 방지로 거부)")
        if not is_safe_name(it["id"]):
            raise QueueError(f"{tag}: id 는 [A-Za-z0-9][A-Za-z0-9._-]* 이고 '..' 를 담지 않아야 합니다")
        if it["id"] in seen:
            raise QueueError(f"{tag}: id 중복")
        seen.add(it["id"])
        for k in ("purpose", "baseline", "change", "expect", "log_dir", "done_regex", "eval_cmd") + tuple(k for k in OPTIONAL if k in it):
            if not isinstance(it[k], str) or not it[k].strip():
                raise QueueError(f"{tag}: {k} 는 빈 문자열이 아닌 문자열")
        if not os.path.isabs(it["log_dir"]):
            raise QueueError(f"{tag}: log_dir 는 절대 경로(로컬 디스크)")
        a = it["argv"]
        if not isinstance(a, list) or not a or not all(isinstance(t, str) and t for t in a):
            raise QueueError(f"{tag}: argv 는 비어 있지 않은 문자열 배열")
        if not any("{GPU}" in t for t in a):
            raise QueueError(f"{tag}: argv 에 GPU 자리표시 {{GPU}} 가 없음 — 어느 GPU 에 올릴지 정할 수 없습니다")
        for k in ("vram_gb", "cpu_cores"):
            if not positive_finite(it[k]):   # JSON 의 NaN·Infinity 는 파이썬이 받아들이고 `> 0` 검사를 통과하므로 유한 양수만 허용한다
                raise QueueError(f"{tag}: {k} 는 유한한 양수")
        if "progress_regex" in it:
            check_progress_regex(it["progress_regex"])
    # 판 사이 로그 경로 중복 금지: --log 를 안 주면 <log_dir>/run.log 라 같은 log_dir 의 두 판이 한 파일에 섞여 쓰고(동시 판), 완료 마커·진행률 판정도 서로 오염된다
    owner: dict = {}
    for it in q["items"] if check_log_dup else ():
        lp = os.path.normpath(it.get("log") or f"{it['log_dir']}/run.log")
        if lp in owner:
            raise QueueError(f"판 {owner[lp]} 와 {it['id']} 의 로그 경로가 같습니다({lp}) — 판마다 log_dir 또는 log 를 다르게 주세요")
        owner[lp] = it["id"]
    return q


def positive_finite(v) -> bool:
    """bool 이 아닌 유한한 양수(int·float)인가. 거대 정수(float 변환 불가)는 False."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    try:
        return math.isfinite(v) and v > 0
    except OverflowError:
        return False


_MASKS = [(re.compile(p, re.I), r) for p, r in (
    (r"((token|key|password|passwd|secret|api[_-]?key)=)[^ ]+", r"\1***"),
    (r"(--?[A-Za-z_-]*(key|token|password|passwd|secret)[A-Za-z_-]*)\s+\S+", r"\1 ***"),
    (r"((Authorization|Cookie|X-Api-Key|Proxy-Authorization):\s*)[^\"']+", r"\1***"),
    (r"(Bearer|Basic)\s+[^\s\"']+", r"\1 ***"),
    (r"(://[^/:\s]+:)[^@\s]+@", r"\1***@"))]


def mask(s: str) -> str:
    """launch-set.sh 의 mask() 와 같은 규칙으로 시크릿 형태 값을 가린다."""
    for rx, rep in _MASKS:
        s = rx.sub(rep, s)
    return s


def cell(s) -> str:
    """표·한 줄 요약에 넣는 문자열: 제어문자 제거, `|` 와 개행을 치환(파이프 표가 깨지거나 화면이 속지 않게)."""
    return CTRL_RE.sub(" ", str(s)).replace("|", "/")


def check_secrets(q: dict) -> None:
    """argv·eval_cmd 등 실행 필드에 시크릿 형태가 있으면 승인 거부 — launch-set.sh 가 발사 때 어차피 거부하지만 승인 표에 시크릿이 찍히기 전에 막는다."""
    for it in q["items"]:
        for field, val in (("argv", " ".join(it["argv"])), *[(t, it[t]) for t in ("eval_cmd", "done_regex", "watcher_args", "memguard_args") if it.get(t)], *[("argv", t) for t in it["argv"]]):
            if mask(val) != val:
                raise QueueError(f"판 {it['id']}: {field} 에 시크릿 형태(token=·--api-key VALUE 등)가 있어 승인할 수 없습니다 — 자격증명은 환경 파일·헬퍼로 옮기세요")


def sha256(raw: bytes) -> str:
    """목록 파일 바이트의 sha256 — 승인의 정본 값."""
    return hashlib.sha256(raw).hexdigest()


def read_env(qpath: Path) -> dict:
    """프로젝트 `.claude/train.env` 의 KEY=VALUE. 목록은 <프로젝트>/.claude/launch-queue/ 아래라 parents[2] 가 프로젝트다."""
    out: dict = {}
    try:
        for line in (qpath.parents[2] / ".claude" / "train.env").read_text().splitlines():
            m = re.match(r"\s*(?:export\s+)?([A-Z][A-Z0-9_]*)=(.*)$", line)
            if m:
                out[m.group(1)] = m.group(2).split("#")[0].strip().strip("'\"")
    except (OSError, IndexError):
        pass
    return out


def read_prefix(qpath: Path) -> str | None:
    """train.env 의 TRAIN_TMUX_PREFIX(형식이 맞을 때만)."""
    v = read_env(qpath).get("TRAIN_TMUX_PREFIX", "")
    return v if re.match(r"^[A-Za-z0-9._-]+$", v) else None


# ───────────────────────── state · 락 · 이벤트 ─────────────────────────

def state_path(qpath: Path) -> Path:
    """<이름>.state.json"""
    return qpath.with_name(qpath.stem + ".state.json")


@contextlib.contextmanager
def locked(qpath: Path):
    """<이름>.lock 에 flock. 열 때마다 새 파일 기술자라 같은 프로세스의 스레드끼리도 서로 막는다."""
    with open(qpath.with_name(qpath.stem + ".lock"), "a+") as fd:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)


def load_state(qpath: Path) -> dict:
    """state 를 읽는다. 없으면 빈 state."""
    p = state_path(qpath)
    if p.exists():
        return json.loads(p.read_text())
    return {"approved": None, "halted": None, "items": {}, "excluded_gpus": [], "decisions": [], "idle_gpus": {}}


def _atomic_write(p: Path, text: str) -> None:
    tmp = p.with_name(f"{p.name}.tmp.{os.getpid()}")
    tmp.write_text(text)
    os.replace(tmp, p)


def save_state(qpath: Path, st: dict) -> None:
    """임시 파일 + os.replace — 락 없이 읽는 `status` 도 반쯤 쓴 파일을 보지 않는다. 호출자가 락을 쥐고 있어야 한다."""
    _atomic_write(state_path(qpath), json.dumps(st, ensure_ascii=False, indent=2) + "\n")


def private_dir(d: Path) -> Path:
    """상태·이벤트·발사 스크립트 폴더는 0700 으로 만든다(이미 있어도 권한을 좁힌다)."""
    d.mkdir(mode=0o700, exist_ok=True)
    os.chmod(d, 0o700)
    return d


def write_event(qpath: Path, kind: str, **info) -> Path:
    """<이름>.events/ 에 이벤트 파일 하나. 세션이 wait-event 로 읽는다."""
    d = private_dir(qpath.with_name(qpath.stem + ".events"))
    p = d / f"{time.strftime('%Y%m%dT%H%M%S')}-{kind}-{os.getpid()}-{time.monotonic_ns() % 10**6}.json"
    _atomic_write(p, json.dumps({"kind": kind, "at": now_iso(), **info}, ensure_ascii=False, indent=2) + "\n")
    return p


def now_iso() -> str:
    """현재 시각 문자열."""
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def new_item_state(rank: int) -> dict:
    """판 하나의 초기 상태. 필드 자리는 Phase 3~4 가 쓰는 것까지 미리 둔다."""
    return {"status": "queued", "attempt": 0, "rank": rank, "gpu": None, "tmux": None, "launch_state": None,
            "started": None, "ended": None, "exit": None, "fix_note": None, "fail_reason": None, "refused": 0, "maybe_alive": False,
            "fixes": 0, "fail_stage": None, "log": None}


def sync_items(st: dict, q: dict) -> int:
    """재승인 때 목록을 state 에 맞춘다. 돌려주는 값은 «새로 queued 가 된 판 수»(새 판 + removed 였다가 목록에 다시 들어온 판).

    새 판은 queued 로 추가하고, 이미 queued 인 판의 순번(rank)은 목록 순서대로 다시 매긴다(순서만 바꿔 재승인해도 옛 순서가 남는 결함 수정).
    순번 값 자체는 queued 판들이 갖던 값을 목록 순서로 재배분하므로 도는·끝난 판의 순번과 안 겹치게 유지된다. relaunch 로 맨 앞에 둔 판(fixes≥1)은 그 우선권을 지킨다.
    목록에서 빠진 queued 판은 removed(종결)로 두어 종료 판정·기다림 판정의 k 에서 빠지게 한다. 도는·끝난 판은 목록에서 빠져도 건드리지 않는다.
    """
    added = 0
    for it in q["items"]:
        s = st["items"].get(it["id"])
        rank = max((x["rank"] for x in st["items"].values()), default=-1) + 1
        if s is None:
            st["items"][it["id"]] = new_item_state(rank)
            added += 1
        elif s["status"] == "removed":   # 뺐다가 다시 넣음 — 처음부터 다시 줄 선다(이전 시도 기록은 없다: removed 는 발사 전 판)
            st["items"][it["id"]] = new_item_state(rank)
            added += 1
    listed = [it["id"] for it in q["items"]]
    for pid, s in st["items"].items():
        if s["status"] == "queued" and pid not in listed:
            s["status"], s["fail_reason"] = "removed", "재승인 때 목록에서 빠짐"
    movable = [pid for pid in listed if st["items"][pid]["status"] == "queued" and st["items"][pid].get("fixes", 0) == 0]   # 목록 순서
    for pid, r in zip(movable, sorted(st["items"][pid]["rank"] for pid in movable)):
        st["items"][pid]["rank"] = r
    return added


def back_of_queue(st: dict) -> int:
    """목록 맨 뒤 순번."""
    return max((s["rank"] for s in st["items"].values()), default=-1) + 1


def requeue(st: dict, s: dict, why: str) -> bool:
    """거부된 판을 queued 로 되돌려 목록 뒤로 보낸다. 시도 수는 올리지 않고, 거부가 상한이면 닫는다. 상한으로 닫았으면 True(호출자가 이벤트·알림을 낸다)."""
    s["attempt"] = max(s["attempt"] - 1, 0)
    s["refused"] += 1
    s["fail_reason"] = why
    if s["refused"] >= MAX_REFUSALS:
        s["status"], s["fail_reason"] = "launch-failed", f"거부 {s['refused']}회 반복: {why}"
        return True
    s["status"], s["rank"] = "queued", back_of_queue(st)
    return False


def record_exit(st: dict, item_id: str, gpu: int, code: int) -> list[str]:
    """끝난 판의 와쳐 종료 코드를 상태로 기록한다. 0=done 2=needs-fix 3=eval-failed 4=timeout 5=발사 거부(목록 뒤로) 6=평가 시간 초과 7=와쳐 신호 중단.

    와쳐가 종료를 보고했으니 maybe_alive 는 일단 내린다. 단 4(타임아웃)·6(평가 시간 초과, 평가는 안 죽인다)·7(신호로 와쳐만 죽음)은
    학습·평가가 살아 있으므로 올려 둔다 — GPU 를 비우지 않았다는 표시라 occupant() 가 그 GPU 의 다음 발사를 막는다(D7).
    2(비정상 종료): 첫 번째면 needs-fix(세션이 고쳐 relaunch 할 기회). 이미 한 번 재발사한 판(fixes≥1)이면 그 판만 failed 로 닫는다.
    돌려주는 태그: needs-fix · refailed · gpu-excluded(같은 GPU 에서 서로 다른 두 판이 연속 재실패 → 그 GPU 제외) · refusal-cap(거부 상한으로 launch-failed). 호출자가 이벤트·알림을 만든다.
    """
    tags: list[str] = []
    s = st["items"].get(item_id)
    if s is None:
        return tags
    s["ended"], s["exit"], s["gpu"], s["maybe_alive"] = now_iso(), code, gpu, code in HOLD_CODES
    refail = st.setdefault("gpu_refail", {})
    if code == 0:
        s["status"] = "done"
        refail.pop(str(gpu), None)   # «연속»이 끊긴다
    elif code == 3:   # 학습은 정상 종료했고 평가만 실패 — GPU 문제가 아니므로 이것도 «연속»을 끊는다
        s["status"], s["fail_reason"] = "eval-failed", "평가 명령 실패(exit 3)"
        refail.pop(str(gpu), None)
    elif code == 2 and s.get("fixes", 0) == 0:
        s["status"] = "needs-fix"
        s["fail_reason"] = "비정상 종료(완료 마커 없음)"
        tags.append("needs-fix")
    elif code == 2:
        s["status"], s["fail_stage"], s["fail_reason"] = "failed", "refail", "재발사 후 다시 비정상 종료(exit 2)"
        tags.append("refailed")
        seq = refail.setdefault(str(gpu), [])
        seq.append(item_id)
        if len(seq) >= 2 and seq[-1] != seq[-2] and gpu not in st["excluded_gpus"]:
            st["excluded_gpus"].append(gpu)
            tags.append("gpu-excluded")
    elif code == 4:
        s["status"], s["fail_reason"] = "timeout", "와쳐 타임아웃: 학습이 살아 있을 수 있어 GPU 를 비우지 않음"
    elif code == 6:
        s["status"], s["fail_reason"] = "timeout", "평가 시간 초과: 평가 프로세스가 살아 있을 수 있어 GPU 를 비우지 않음(평가는 죽이지 않았다)"
    elif code == 7:
        s["status"], s["fail_reason"] = "timeout", "와쳐가 신호(TERM·INT)로 중단됨: 학습이 살아 있을 수 있어 GPU 를 비우지 않음"
    elif code == 5:
        if requeue(st, s, "와쳐가 memguard 발사 거부를 감지"):
            tags.append("refusal-cap")
    else:
        s["status"], s["fail_reason"] = "failed", f"예상 밖 와쳐 종료 코드 {code}"
    return tags


def sweep_stale(st: dict, now: float | None = None) -> None:
    """오래된 launching 예약(next 가 중간에 죽음)을 launch-failed 로 닫아 판이 영영 갇히지 않게 한다."""
    now = time.time() if now is None else now
    for s in st["items"].values():
        if s["status"] == "launching" and now - s.get("reserved_epoch", now) > STALE_RESERVE_SEC:
            s["status"], s["fail_reason"], s["maybe_alive"] = "launch-failed", "예약 후 발사 결과가 기록되지 않음(next 비정상 종료 의심)", True


def occupant(st: dict, gpu: int) -> str | None:
    """이 GPU 를 쥔 판 id(없으면 None). launching·running 이거나, 발사 실패·타임아웃이어도 학습이 살아 있을 수 있는(maybe_alive) 판이다.

    next 가 방금 종료를 기록한 판은 record_exit 가 상태를 바꾸고 maybe_alive 를 내렸으므로 여기 걸리지 않는다.
    """
    for pid, s in st["items"].items():
        if s["gpu"] == gpu and (s["status"] in ("launching", "running") or s.get("maybe_alive")):
            return pid
    return None


def gate(qpath: Path, st: dict, raw: bytes, notes: list[str]) -> bool:
    """승인 해시 대조. 진행 가능하면 True. 처음 달라진 순간에만 halted·이벤트를 남기고 알림 문구를 notes 에 넣는다."""
    if st["halted"]:
        return False
    ap = st["approved"]
    if ap is None:
        raise QueueError("승인 기록이 없습니다 — 표를 보이고 사용자가 «이대로»를 고른 뒤 approve 를 먼저 실행하세요")
    cur = sha256(raw)
    if cur != ap["sha256"]:
        st["halted"] = {"reason": "queue-changed", "at": now_iso(), "approved_sha256": ap["sha256"], "current_sha256": cur}
        write_event(qpath, "queue-changed", approved_sha256=ap["sha256"], current_sha256=cur)
        notes.append(f"[{qpath.stem}] 대기 목록이 승인 뒤 바뀌어 자동 발사를 멈췄습니다(승인 {ap['sha256'][:8]} → 현재 {cur[:8]}). 확인 후 approve 를 다시 실행하세요")
        return False
    return True


# ───────────────────────── 후보 선택 (순수) ─────────────────────────

def ordered(q: dict, st: dict) -> list[dict]:
    """목록 순서(state 의 rank, 같으면 목록 순서)."""
    return sorted(q["items"], key=lambda it: st["items"].get(it["id"], {}).get("rank", 10**9))


def fits(item: dict, gpu: int, gpus: dict) -> bool:
    """이 GPU 에 이 판이 들어가는가 — gpu_preflight.decide 재사용. 표본이 없으니 사용률은 0 으로 두고 CPU 는 건너뛴다(실제 측정은 launch-set.sh)."""
    if gpu not in gpus:
        return False
    a = SimpleNamespace(vram_gb=item["vram_gb"], cpu_cores=item["cpu_cores"], util_max=70.0, sample_sec=60, cpu_reserve=8.0, vram_margin=0.1)
    ok, _ = gp.decide(gpus, [gpu], {gpu: 0.0}, float("inf"), a)
    return ok


def pick_candidate(order: list[dict], items_state: dict, gpu: int, gpus: dict, skip: set) -> dict | None:
    """목록 순서대로 queued 이고 이 GPU 에 들어가는 첫 판. 안 들어가면 건너뛴다. 순수 함수 — Phase 4 기다림 판정이 앞에 낄 자리."""
    for it in order:
        if items_state[it["id"]]["status"] == "queued" and it["id"] not in skip and fits(it, gpu, gpus):
            return it
    return None


def read_progress(tail: str, progress_regex: str | None = None) -> tuple[int, int] | None:
    """로그 꼬리에서 마지막 «현재/전체» 일치를 읽는다. 그룹이 None·정수 아님·0·음수·현재>전체·거대 수(> PROGRESS_MAX)·정규식 오류는 전부 None.

    progress_regex 는 첫 두 그룹이 현재·전체여야 한다(없으면 «Epoch 12/60» 형식).
    """
    if not tail:
        return None
    try:
        last = None
        for last in re.finditer(progress_regex or EPOCH_RE, tail):
            pass
        cur, total = int(last.group(1)), int(last.group(2))
    except (re.error, AttributeError, IndexError, ValueError, TypeError, OverflowError):
        return None
    if cur <= 0 or total <= 0 or cur > total or total > PROGRESS_MAX:
        return None
    return cur, total


def _good_hours(x: float | None) -> float | None:
    return x if x is not None and math.isfinite(x) and x >= 0 else None


def remaining_hours(tail: str, elapsed_h: float | None, progress_regex: str | None = None) -> float | None:
    """남은 시간 추정 = 경과 × (전체 − 현재) ÷ 현재. 못 읽으면 None. 판마다 예상 시간을 신고받지 않으려는 의도다(결정 2)."""
    p = read_progress(tail, progress_regex)
    if p is None or not elapsed_h or elapsed_h <= 0:
        return None
    return _good_hours(elapsed_h * (p[1] - p[0]) / p[0])


def estimate_total_hours(tail: str, elapsed_h: float | None, progress_regex: str | None = None) -> float | None:
    """새 판 소요 추정의 재료: 도는 판의 «경과 ÷ 진행률» = 경과 × 전체 ÷ 현재. 못 읽으면 None."""
    p = read_progress(tail, progress_regex)
    if p is None or not elapsed_h or elapsed_h <= 0:
        return None
    return _good_hours(elapsed_h * p[1] / p[0])


def iso_epoch(s: str | None) -> float | None:
    """now_iso() 형식 문자열 → epoch 초. 못 읽으면 None."""
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z").timestamp()
    except (TypeError, ValueError):
        return None


def elapsed_hours(started: str | None, now: float | None = None) -> float | None:
    """state 의 started(ISO 시각)부터 now(기본 지금)까지의 시간(h). started 가 없으면 None."""
    t = iso_epoch(started)
    return None if t is None else ((time.time() if now is None else now) - t) / 3600


def progress_tail(item: dict) -> str:
    """진행 문구가 찍히는 파일의 끝 256KB: done_log 글롭의 가장 최근 파일, 없으면 --log(기본 <log_dir>/run.log).

    창 발사(tty)는 표준출력이 창으로 가서 run.log 에 에폭 줄이 없을 수 있다. 그때는 done_log 로 프로젝트 로그를 가리켜야 읽힌다.
    """
    try:
        cands = sorted(glob.glob(item["done_log"]), key=os.path.getmtime) if item.get("done_log") else []
    except OSError:
        cands = []
    return file_tail(cands[-1] if cands else (item.get("log") or f"{item['log_dir']}/run.log"), 400)


def kind_of(info: dict) -> str:
    """GPU 정보 → 기종 키(H/L, 모르면 이름 그대로)."""
    return gpu_kind(info["name"]) or info["name"]


def collect_estimates(q: dict, st: dict, gpus: dict, now: float | None = None) -> tuple[dict, dict]:
    """(기종별 소요 중앙값 type_total h, {GPU: 도는 판의 남은 시간 h|None}).

    같은 목록에서 끝난(done) 판은 실제 소요, 도는 판은 «경과 ÷ 진행률» 추정을 기종별로 모아 중앙값을 낸다. 진행률을 못 읽은 도는 판은 남은 시간만 None 이다.
    같은 GPU 에 여러 판이 돌면 남은 시간은 가장 긴 것(하나라도 모르면 None). 로그를 읽으므로 락 밖에서 부른다.
    """
    by_id = {it["id"]: it for it in q["items"]}
    ests: dict = {}
    rem: dict = {}
    for pid, s in st["items"].items():
        g = s.get("gpu")
        if pid not in by_id or g not in gpus:
            continue
        kd = kind_of(gpus[g])
        if s["status"] == "running":
            it = by_id[pid]
            tail, el, rx = progress_tail(it), elapsed_hours(s.get("started"), now), it.get("progress_regex")
            tot, r = estimate_total_hours(tail, el, rx), remaining_hours(tail, el, rx)
            if tot is not None:
                ests.setdefault(kd, []).append(tot)
            old = rem.get(g, 0.0)
            rem[g] = None if (r is None or old is None) else max(old, r)
        elif s["status"] == "done" and iso_epoch(s.get("ended")) is not None:
            dur = _good_hours(elapsed_hours(s.get("started"), iso_epoch(s["ended"])))
            if dur:
                ests.setdefault(kd, []).append(dur)
    return {kd: statistics.median(v) for kd, v in ests.items()}, rem


def should_wait(free_gpu: int, gpus: dict, k: int, type_total: dict, running_rem: dict) -> tuple[bool, str]:
    """지금 빈 GPU 를 비워 두고 더 빠른 기종 GPU 가 비기를 기다려야 하는가. 순수 함수 — (기다림 여부, 근거 문장). 의뢰서 결정 2·계획서 142~145줄.

    빠른 기종 = type_total 이 빈 GPU 기종보다 작은 기종. 빠른 기종의 도는 GPU 중 «남은 시간 + 그 기종 소요 < 빈 기종 소요»인 것의 수 m 이
    미발사 판 수 k 이상(k ≤ m)이면 기다린다(모든 대기 판이 빠른 GPU 에서 더 일찍 끝나므로 느린 GPU 를 놀려도 손해가 없다). 그 밖에는 바로 올린다.
    한 기종이라도 소요 자료(type_total)가 없거나 빠른 GPU 의 남은 시간을 못 읽으면(None) 기다리지 않는다 — 현재 규칙대로 올린다.
      gpus {GPU: 정보} 기종 구분용 · k 미발사(queued) 판 수 · type_total {기종: 소요 h} · running_rem {GPU: 남은 시간 h|None}(도는 판들)
    """
    if k <= 0:
        return False, "대기 판이 없어 기다릴 이유 없음"
    fk = kind_of(gpus[free_gpu])
    t_free = type_total.get(fk)
    if t_free is None:
        return False, f"기종 {fk} 의 소요 자료가 없어 기다리지 않음"
    known = {kind_of(gpus[g]) for g in set(running_rem) | {free_gpu} if g in gpus}
    missing = sorted(known - set(type_total))
    if missing:
        return False, f"기종 {', '.join(missing)} 의 소요 자료가 없어 기다리지 않음"
    fast = {kd for kd in known if type_total[kd] < t_free}
    head = f"빈 GPU {free_gpu}({fk}) 소요 {t_free:.2f}h · 미발사 k={k}"
    if not fast:
        return False, f"{head} → 더 빠른 기종 GPU 가 없어 바로 올림"
    m, parts = 0, []
    for g, r in sorted(running_rem.items()):
        if g not in gpus or kind_of(gpus[g]) not in fast:
            continue
        if r is None:
            return False, f"{head} → 빠른 GPU {g} 의 남은 시간을 읽지 못해 기다리지 않음"
        tf = type_total[kind_of(gpus[g])]
        if r + tf < t_free:
            m += 1
            parts.append(f"GPU {g}: 남은 {r:.2f}h + 소요 {tf:.2f}h = {r + tf:.2f}h")
    if m and k <= m:
        return True, f"{head} · 빠른 GPU m={m} → k ≤ m 이라 기다림 ({'; '.join(parts)} < {t_free:.2f}h)"
    return False, f"{head} · 빠른 GPU m={m} → " + ("k > m 이라 바로 올림" if m else "일찍 끝나는 빠른 GPU 가 없어 바로 올림")


# ───────────────────────── Phase 5: 판 < GPU 배치 제안 ─────────────────────────

def gpu_kind(name: str) -> str | None:
    """GPU 이름 → 표의 기종 글자(H=H100, L=L40S). 모르면 None."""
    return "H" if "H100" in name else "L" if "L40S" in name else None


def propose_placement(job_ids: list[str], gpus: dict, env: dict, table: dict) -> dict:
    """판 수·GPU 구성·프로젝트 선언으로 배치를 «제안»한다(발사 없음). 순수 함수.

    돌려주는 dict: mode(bundle|one-per-gpu|queue) · label · reason(판당 1장으로 내린 이유|None) · groups([{gpus, jobs}]) · waiting(판 id) · row(표 행|None).
    판 ≥ GPU 는 묶음 대상이 아니라 «판당 1장 + 대기 목록 자동 발사»다. 판 < GPU 는 표(placement_table.json)의 행을 쓰되, 표의 GPU 구성과 같고
    그 행이 요구하는 선언(DDP_READY·PROP_BATCH_READY=1)을 프로젝트가 모두 했을 때만 묶음을 낸다. 아니면 빈 GPU 마다 한 판으로 내리고 이유를 적는다.
    """
    gids, n = list(gpus), len(job_ids)
    one = lambda: [{"gpus": [g], "jobs": [j]} for g, j in zip(gids, job_ids)]   # noqa: E731
    if n >= len(gids):
        label = "판 > GPU: 판당 1장 + 앞 GPU 수만큼 먼저 올리고 끝나는 GPU 에 대기 판 자동 발사" if n > len(gids) else "판 = GPU: 판당 1장"
        return {"mode": "queue", "label": label, "reason": None, "groups": one(), "waiting": job_ids[len(gids):], "row": None}
    base = {"mode": "one-per-gpu", "label": "빈 GPU 마다 한 판", "groups": one(), "waiting": [], "row": None}
    row, cfg = table["rows"].get(str(n)), table["config"]
    kinds: dict = {}
    for g in gids:
        kinds.setdefault(gpu_kind(gpus[g]["name"]), []).append(g)
    if row is None:
        return {**base, "reason": f"배치 표에 판 {n}개 행이 없음"}
    if {k: len(v) for k, v in kinds.items()} != {table["kinds"][name]: c for name, c in cfg.items()}:
        return {**base, "reason": f"GPU 구성이 표({', '.join(f'{k} {c}장' for k, c in cfg.items())})와 다름"}
    missing = [d for d in row["needs"] if env.get(d) != "1"]
    if missing:
        return {**base, "reason": f"프로젝트 train.env 에 {', '.join(missing)}=1 선언이 없어 DDP 조건을 갖춘 것으로 보지 않음(rules-lazy/background-task.md 주의 사항)"}
    pos = {f"{k}{i + 1}": g for k, v in kinds.items() for i, g in enumerate(v)}
    jobs, groups = iter(job_ids), []
    for grp in row["groups"]:
        groups.append({"gpus": [pos[t] for t in grp["gpus"]], "jobs": [next(jobs) for _ in range(grp["jobs"])]})
    return {"mode": "bundle", "label": row["layout"], "reason": None, "groups": groups, "waiting": [], "row": row}


def placement_cells(plan: dict) -> dict:
    """{판 id: 승인 표 «배치» 열 문구}."""
    out = {j: "대기(자동 발사)" for j in plan["waiting"]}
    for k, grp in enumerate(plan["groups"], 1):
        for i, j in enumerate(grp["jobs"], 1):
            g = ",".join(map(str, grp["gpus"]))
            out[j] = f"GPU {g}" + (f" (묶음 {k}, {i}번째)" if plan["mode"] == "bundle" else "")
    return out


def print_placement(plan: dict) -> None:
    """배치 제안 블록 출력(표시만 — 발사하지 않는다)."""
    print(f"\n배치 제안: {plan['label']}")
    if plan["reason"]:
        print(f"  판당 1장으로 내린 이유: {plan['reason']}")
    if plan["row"]:
        r = plan["row"]
        print(f"  표 값(벤치 3차, 같은 길이 판 동시 시작 가정): 끝나는 시각 {r['finish_h']}h · 판당 1장 병렬 {r['parallel_h']}h")
    print("| 묶음 | GPU | 판(순서) |")
    print("|---|---|---|")
    for k, grp in enumerate(plan["groups"], 1):
        print(f"| {k} | {','.join(map(str, grp['gpus']))} | {' → '.join(grp['jobs'])} |")
    if plan["waiting"]:
        print(f"| 대기 | - | {' → '.join(plan['waiting'])} (GPU 가 비는 대로 자동 발사) |")
    print("제안일 뿐 발사하지 않습니다. 묶음(DDP) 배치는 사용자가 «이대로»를 고른 뒤 세션이 DDP 명령으로 직접 올립니다(대기 목록 start 는 판당 1장만 올립니다).")


def classify_launch(rc: int | None, log_tail: str) -> str:
    """launch-set.sh 종료 코드 → ok / verify-failed / refused / not-started / crashed / timeout / error.

    not-started(64 인자·경로 오류, 67 같은 이름 state 가 이미 있음)는 아무것도 뜨지 않은 거부라 그 GPU 에 다음 후보를 계속 올린다.
    """
    if rc is None:
        return "timeout"
    if rc == 0:
        return "ok"
    if rc == 1:
        return "verify-failed"
    if rc in (64, 67):
        return "not-started"
    if rc == 76 or (rc == 65 and MEMGUARD_REFUSED.search(log_tail)):
        return "refused"
    return "crashed" if rc == 65 else "error"


# ───────────────────────── 백엔드 ─────────────────────────

def file_tail(path: str | Path, n: int = 50) -> str:
    """파일 끝 LOG_TAIL_BYTES 안의 마지막 n 줄(없으면 빈 문자열). 전체를 읽지 않는다."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(f.tell() - LOG_TAIL_BYTES, 0))
            data = f.read(LOG_TAIL_BYTES)
    except OSError:
        return ""
    return "\n".join(data.decode("utf-8", "replace").splitlines()[-n:])


_ORIG_UMASK: int | None = None   # main() 이 077 로 좁히기 전의 umask. 학습 로그 폴더·tmux·학습 프로세스는 이 값을 따라야 한다


def run_proc(cmd: list, **kw):
    """subprocess.run 인데 자식 프로세스만 원래 umask 로 돌린다(이 도구의 077 이 tmux 서버·학습·알림 스크립트로 새지 않게). umask 는 자식 안에서만 바꿔 스레드 안전하다."""
    if _ORIG_UMASK is not None:
        kw["preexec_fn"] = lambda: os.umask(_ORIG_UMASK)
    return subprocess.run(cmd, **kw)


def makedirs_orig(path: str) -> None:
    """os.makedirs 인데 새로 만든 폴더 권한을 원래 umask 기준으로 맞춘다(학습 로그 폴더 권한을 이 도구가 바꾸지 않는다). 이미 있던 폴더는 건드리지 않는다."""
    new, p = [], Path(path)
    while not p.exists() and p != p.parent:
        new.append(p)
        p = p.parent
    os.makedirs(path, exist_ok=True)
    if _ORIG_UMASK is not None:
        for d in new:
            os.chmod(d, 0o777 & ~_ORIG_UMASK)


class TmuxBackend:
    """실제 효과: tmux 세션 생성·키 전송, nvidia-smi, 알림, 감시 서명."""

    def gpus(self) -> dict:
        return gp.read_gpus()

    def env_problem(self) -> str | None:
        """memguard 스코프에 필요한 사용자 systemd 환경이 없으면 사유를 돌려준다(새 세션에 -e 로 넘기므로 이 프로세스에 있어야 한다)."""
        miss = [k for k in ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS") if not os.environ.get(k)]
        return f"{', '.join(miss)} 없음 — memguard 가 스코프를 못 만듭니다" if miss else None

    def open_window(self, session: str, cwd: str) -> str:
        """`<접두><GPU 번호>` 세션의 창 하나를 마련하고 `세션:창번호` 를 돌려준다. 세션이 없으면 만들어 그 첫 창을, 있으면 새 창을 더한다.

        세션 지정은 `=이름`(정확 일치) — 접두 일치로 exp1 이 exp10 을 집지 않게 한다. 창 번호는 tmux 가 정해 -P -F 로 받는다.
        이미 다른 판이 도는 창에는 아무것도 보내지 않는다(항상 방금 만든 창만 쓴다).
        """
        env = [x for k in ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS") for x in ("-e", f"{k}={os.environ[k]}")]
        fmt = ["-P", "-F", "#{window_index}"]

        def has() -> bool:
            return run_proc(["tmux", "has-session", "-t", f"={session}"], capture_output=True).returncode == 0
        r = None
        if not has():   # tmux 서버를 처음 띄울 수도 있어 원래 umask 로(077 이 서버·학습으로 새지 않게)
            r = run_proc(["tmux", "new-session", "-d", *fmt, "-s", session, "-c", cwd, *env], capture_output=True, text=True)
            if r.returncode != 0 and not has():
                raise RuntimeError(f"tmux new-session 실패(rc={r.returncode}): {r.stderr.strip()[:200]}")
        if r is None or r.returncode != 0:   # 세션이 이미 있거나, 확인 직후 다른 곳에서 만들어졌다
            r = run_proc(["tmux", "new-window", "-d", *fmt, "-t", f"={session}:", "-c", cwd, *env], capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError(f"tmux new-window 실패(rc={r.returncode}): {r.stderr.strip()[:200]}")
        idx = r.stdout.strip()
        if not idx.isdigit():
            raise RuntimeError(f"tmux 가 창 번호를 돌려주지 않음: {r.stdout.strip()[:80]!r}")
        return f"{session}:{idx}"

    def launch(self, target: str, script: Path, rc_file: Path, timeout: float) -> int | None:
        """open_window 가 돌려준 `세션:창번호` 로 발사 스크립트를 보내고 .rc 파일이 생길 때까지 기다린다. 시간 초과면 None."""
        run_proc(["tmux", "send-keys", "-t", f"={target}", f"bash {shlex.quote(str(script))}", "Enter"], check=True)
        end = time.time() + timeout
        while time.time() < end:
            if rc_file.exists() and rc_file.read_text().strip():
                return int(rc_file.read_text().strip())
            time.sleep(2)
        return None

    def verify(self, state_file: str) -> tuple[int, str]:
        r = run_proc(["bash", str(LAUNCH_SET), "verify", state_file], capture_output=True, text=True)
        return r.returncode, r.stdout

    def notify(self, msg: str) -> None:
        """와쳐와 같은 방식: 출력까지 버린다(터미널 벨이 로그를 깨뜨린 이력)."""
        run_proc(["bash", str(HARNESS / "scripts" / "claude-notify.sh"), "launch-queue", msg],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def sign(self, gate: str, target: str, basis: str, actor: str, cwd: str) -> None:
        """감시 서명 원장에 한 줄(scripts/oversight-append.sh, LAUNCH_QUEUE_OVERSIGHT 로 경로를 바꿀 수 있다). 실패해도 본 동작은 계속하고 stderr 경고만 낸다."""
        script = os.environ.get("LAUNCH_QUEUE_OVERSIGHT") or str(HARNESS / "scripts" / "oversight-append.sh")
        try:
            r = run_proc(["bash", script, gate, target, basis, actor], cwd=cwd, capture_output=True, text=True, timeout=30)
            err = "" if r.returncode == 0 else f"rc={r.returncode} {r.stderr.strip()[:200]}"
        except (OSError, subprocess.SubprocessError) as e:
            err = f"{type(e).__name__}: {e}"
        if err:
            print(f"[launch_queue] 경고: 감시 서명({gate}) 기록 실패 — {err}", file=sys.stderr)

    def oversight(self, target: str, basis: str, actor: str, cwd: str) -> None:
        """감시 서명 원장에 launch 한 줄."""
        self.sign("launch", target, basis, actor, cwd)


def make_backend() -> TmuxBackend:
    """실제 백엔드를 고르는 유일한 자리. GPU_PREFLIGHT_FAKE 는 시험 전용이라 여기서 지운다(조용히 두면 가짜 GPU 상태로 실발사가 승인된다).

    시험은 FakeBackend 를 main(backend=…)에 직접 넣으므로 이 함수를 거치지 않는다.
    """
    if os.environ.pop("GPU_PREFLIGHT_FAKE", None) is not None:
        print("[launch_queue] 경고: GPU_PREFLIGHT_FAKE 는 시험 전용이라 실제 백엔드에서 제거했습니다", file=sys.stderr)
    return TmuxBackend()


class FakeBackend:
    """시험용: 아무것도 실행하지 않고 호출만 기록한다. GPU 상태·launch-set 종료 코드는 시험이 정한다."""

    def __init__(self, gpus: dict):
        self.gpu_state, self.rc, self.delay = gpus, {}, 0.0
        self.sessions, self.launches, self.notes, self.signatures, self.signs = {}, [], [], [], []   # sessions: 세션 이름 → 만든 창 번호들
        self.env_msg, self.verify_rc = None, 0

    def gpus(self) -> dict:
        return {g: dict(v) for g, v in self.gpu_state.items()}

    def env_problem(self) -> str | None:
        return self.env_msg

    def open_window(self, session: str, cwd: str) -> str:
        wins = self.sessions.setdefault(session, [])   # 세션이 없으면 만들고 첫 창(0), 있으면 창을 더한다
        wins.append(len(wins))
        return f"{session}:{wins[-1]}"

    def launch(self, target: str, script: Path, rc_file: Path, timeout: float) -> int | None:
        time.sleep(self.delay)   # 경합 시험이 두 next 를 겹치게 하려는 지연
        item = script.stem.rsplit("-", 1)[0]
        self.launches.append((item, target, script))
        return self.rc.get(item, 0)

    def verify(self, state_file: str) -> tuple[int, str]:
        return self.verify_rc, "VERIFY PASS (fake)\n" if self.verify_rc == 0 else "VERIFY FAIL (fake)\n"

    def notify(self, msg: str) -> None:
        self.notes.append(msg)

    def oversight(self, target: str, basis: str, actor: str, cwd: str) -> None:
        self.signatures.append((target, basis, actor))

    def sign(self, gate: str, target: str, basis: str, actor: str, cwd: str) -> None:
        self.signs.append((gate, target, basis, actor))


# ───────────────────────── 발사 ─────────────────────────

def launch_name(session: str, item_id: str, attempt: int) -> str:
    """launch-set `--name`(허용 [A-Za-z0-9._-]). 같은 세션을 여러 판이 쓰므로 판·시도마다 다르게 `<세션>-<판 id>-<시도>`.

    state(launch-state-<이름>.json)·와쳐 로그·memguard 스코프(memguard-<이름>-<pid>)가 이 이름에서 나온다. 판 id 도 같은 문자 집합이라 형식은 늘 맞고,
    마지막 `-시도` 는 정수라 (판 id, 시도) 쌍이 다르면 이름도 다르다.
    """
    return f"{session}-{item_id}-{attempt}"


def write_launch_script(qpath: Path, item: dict, attempt: int, session: str, gpu: int) -> tuple[Path, Path]:
    """판 하나의 발사 스크립트와 .rc 경로. launch-set.sh 인자는 전부 shlex.quote 로 인용한다.

    cwd 는 프로젝트 루트다(argv 의 상대 경로 `runner.sh` 가 거기 있다). log_dir 는 로그·state 자리일 뿐이다.
    GPU_PREFLIGHT_FAKE 는 시험 전용이라 실제 발사에서는 지운다.
    """
    d = private_dir(qpath.with_name(qpath.stem + ".launch"))
    script, rc = d / f"{item['id']}-{attempt}.sh", d / f"{item['id']}-{attempt}.rc"
    ld, proj = item["log_dir"], str(qpath.parents[2])
    name = launch_name(session, item["id"], attempt)
    ls = ["bash", str(LAUNCH_SET), "launch", "--name", name, "--log", item.get("log") or f"{ld}/run.log",
          "--done-regex", item["done_regex"], "--eval-cmd", item["eval_cmd"], "--title", f"{qpath.stem}:{item['id']}",
          "--expect", item["expect"], "--state", f"{ld}/launch-state-{name}.json", "--watcher-log", f"{ld}/watcher-{name}.log",
          "--gpu", str(gpu), "--vram-gb", str(item["vram_gb"]), "--cpu-cores", str(item["cpu_cores"]),
          "--queue", str(qpath), "--queue-item", item["id"]]
    if "--queue-attempt" in LAUNCH_SET.read_text():   # 시도 번호 결박(next --attempt). 옛 launch-set.sh 는 이 인자를 몰라 발사 전체가 64 로 거부되므로 지원하는 사본일 때만 붙인다
        ls += ["--queue-attempt", str(attempt)]
    for flag, key in (("--done-log", "done_log"), ("--memguard-args", "memguard_args"), ("--watcher-args", "watcher_args"), ("--intent", "intent")):
        if item.get(key):
            ls += [flag, item[key]]
    ls += ["--", *[t.replace("{GPU}", str(gpu)) for t in item["argv"]]]
    q = shlex.quote
    script.write_text(
        "#!/usr/bin/env bash\n"
        "# launch_queue.py 가 만든 발사 스크립트(내용은 승인된 대기 목록에서 생성 — 사용자 문자열은 주석에 넣지 않는다)\n"
        f"cd {q(proj)} || {{ printf '%s\\n' 64 > {q(str(rc))}; exit 64; }}\n"   # cd 실패도 .rc 에 남겨 next 가 5분 기다리지 않게 한다
        "unset GPU_PREFLIGHT_FAKE\n"
        f"{' '.join(q(t) for t in ls)}\n"
        "rc=$?\n"
        f"printf '%s\\n' \"$rc\" > {q(str(rc))}\n"
        'exit "$rc"\n')
    return script, rc


def launch_blocker(qpath: Path, be) -> tuple[str | None, str | None]:
    """(tmux 접두, 발사 못 하는 사유). 접두가 없거나 systemd 환경이 없으면 발사하지 않는다."""
    prefix = read_prefix(qpath)
    if prefix is None:
        return None, f"{qpath.parents[2]}/.claude/train.env 에 TRAIN_TMUX_PREFIX 가 없음"
    return prefix, be.env_problem()


def code_snapshot(proj: Path) -> dict | None:
    """프로젝트 저장소의 코드 상태: HEAD · 작업 트리 변경 요약 해시(status + diff 의 sha256) · 변경 파일 수. git 저장소가 아니면 None.

    .claude/launch-queue/ 는 제외한다(state·이벤트가 계속 바뀌어 해시가 항상 달라진다). approve 때 기록하고 발사·재발사 때 다시 구해 비교한다.
    """
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    ex = ":(exclude).claude/launch-queue"

    def git(*args: str) -> str | None:
        r = subprocess.run(["git", "-C", str(proj), *args], capture_output=True, text=True, timeout=30, env=env)
        return r.stdout if r.returncode == 0 else None
    try:
        head, status, diff = git("rev-parse", "HEAD"), git("status", "--porcelain", "--", ".", ex), git("diff", "HEAD", "--", ".", ex)
    except (OSError, subprocess.SubprocessError):
        return None
    if head is None or status is None or diff is None:
        return None
    return {"head": head.strip(), "dirty_sha": hashlib.sha256((status + "\0" + diff).encode()).hexdigest(), "changed": len([ln for ln in status.splitlines() if ln.strip()])}


def code_sig(snap: dict | None) -> str:
    """코드 상태 식별 문자열(알림 중복 방지용)."""
    return f"{snap['head']}:{snap['dirty_sha']}" if snap else ""


def code_changed(approved: dict | None, now: dict | None) -> str | None:
    """승인 때 코드 상태와 지금을 비교한 문장(같거나 한쪽이 없으면 None)."""
    if not approved or not now or code_sig(approved) == code_sig(now):
        return None
    if approved["head"] != now["head"]:
        return f"승인 이후 코드가 바뀜(HEAD {approved['head'][:8]}→{now['head'][:8]}, 변경 파일 {now['changed']}개)"
    return f"승인 이후 코드가 바뀜(HEAD {now['head'][:8]} 동일, 작업 트리 변경 파일 {approved['changed']}→{now['changed']}개)"


def wait_inputs(qpath: Path, be) -> dict | None:
    """기다림 판정 재료(기종별 소요 중앙값·도는 판 남은 시간). 락 없이 읽는다 — state 는 원자 교체라 일관되고 추정치라 약간 낡아도 된다. 실패하면 None(기다리지 않음)."""
    try:
        st = load_state(qpath)
        if not any(s["status"] in ("running", "done") for s in st["items"].values()):
            return {"type_total": {}, "running_rem": {}}
        tt, rr = collect_estimates(parse_queue(qpath.read_bytes(), qpath.stem), st, be.gpus())
        return {"type_total": tt, "running_rem": rr}
    except Exception:  # noqa: BLE001 — 추정이 어긋나도 발사를 막지 않는다
        return None


def watcher_alive(launch_state: str | None) -> bool | None:
    """launch-set state 의 와쳐 PID 가 살아 있는가(/proc 읽기만). state 를 못 읽으면 None."""
    try:
        d = json.loads(Path(launch_state).read_text())
        pid = int(d["watcher_pid"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if pid <= 0:
        return False
    try:
        start = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return False
    return not d.get("watcher_start") or str(d["watcher_start"]) == start   # PID 재사용 방지


LAUNCHED = "발사:"   # launch_one 이 성공했을 때 돌려주는 문장의 머리


def abort_if_stopped(qpath: Path, item_id: str) -> tuple[str, list[str]] | None:
    """발사 직전 재확인(락 안): 멈춤(halted)이거나 목록이 승인 해시와 달라졌으면 예약(launching)을 queued 로 되돌리고 (사유, 알림들)을 돌려준다. 계속해도 되면 None.

    예약은 락 안에서 하지만 발사(tmux·launch-set, 수 분)는 락 밖이라, 그 사이에 사용자가 halt 하거나 목록을 고쳐도 이미 예약된 판이 올라가
    «halt 이후 발사 0건»(background-task.md § 대기 목록 자동 발사 «정지»)이 깨졌다. 확인 자체가 실패하면 안전 쪽(발사 안 함)으로 간다.
    되돌릴 때 시도 번호도 한 칸 내린다(requeue 와 같다 — 이 시도는 시작도 안 했다).
    """
    notes: list[str] = []
    with locked(qpath):
        st = load_state(qpath)
        s = st["items"].get(item_id)
        try:
            ok = gate(qpath, st, qpath.read_bytes(), notes)
            why = "" if ok else ("승인 해시 불일치로 멈춤" if st["halted"] and st["halted"].get("reason") == "queue-changed" else "사용자 정지(halt)")
        except Exception as e:  # noqa: BLE001
            ok, why = False, f"발사 직전 확인 실패 {type(e).__name__}: {e}"
        if ok:
            return None
        if s is None or s["status"] != "launching":   # 예약이 이미 풀렸다(sweep_stale 등) — 되돌릴 것이 없다
            save_state(qpath, st)   # gate 가 쓴 변화(처음 멈춤)는 남긴다
            return f"발사 직전 {why}: 판 {item_id} 는 이미 예약이 풀려 있어 건드리지 않음", notes
        s.update(status="queued", gpu=None, tmux=None, attempt=max(s["attempt"] - 1, 0), log=None)
        s.pop("reserved_epoch", None)
        save_state(qpath, st)
    return f"발사 직전 {why}: 판 {item_id} 발사를 취소하고 queued 로 되돌림", notes


def launch_one(qpath: Path, gpu: int, be, actor: str, announce: bool, only_item: str | None = None) -> str:
    """GPU 하나에 대기 목록의 판 하나를 올린다. 거부된 판은 건너뛰고 다음 후보를 본다. 결과 한 줄을 돌려준다.

    예약(락 안) → 발사(락 밖) → 결과 기록(락 안) 순서라 두 next 가 겹쳐도 같은 판을 두 번 올리지 않는다.
    후보는 목록 순서대로 이 GPU 에 들어가는 첫 queued 판이되, should_wait 가 «기다려라»고 한 판은 건너뛴다(Phase 4).
    only_item 이 있으면 그 판만 후보다(relaunch 가 쓴다 — 후보가 없어도 «들어가는 판 없음» 알림을 내지 않는다).
    """
    prefix, problem = launch_blocker(qpath, be)
    if problem:
        write_event(qpath, "launch-blocked", gpu=gpu, reason=problem)
        be.notify(f"[{qpath.stem}] GPU {gpu} 자동 발사 불가: {problem}")
        return f"발사 불가: {problem}"
    tried: set[str] = set()
    code_now = code_snapshot(qpath.parents[2])                  # git 은 락 밖에서
    wi = None if only_item else wait_inputs(qpath, be)          # 진행 로그 읽기도 락 밖에서(재발사는 기다리지 않는다)
    while True:
        notes: list[str] = []
        why: list[str] = []
        with locked(qpath):
            st = load_state(qpath)
            sweep_stale(st)
            raw = qpath.read_bytes()
            if not gate(qpath, st, raw, notes):
                save_state(qpath, st)
                halted = True
            else:
                halted = False
                q = parse_queue(raw, qpath.stem, check_log_dup=False)   # 승인된 목록의 next 를 로그 중복 검사로 막지 않는다(승인 시점 검증)
                if gpu in st["excluded_gpus"]:
                    save_state(qpath, st)
                    return f"GPU {gpu} 는 자동 발사 대상에서 제외됨"
                held = occupant(st, gpu)   # 큐가 가동 중으로 아는 GPU 에는 또 올리지 않는다(start 재실행·동시 next·살아 있을 수 있는 판)
                if held is not None:
                    save_state(qpath, st)
                    return f"GPU {gpu} 는 판 {held}({st['items'][held]['status']}{'·살아 있을 수 있음' if st['items'][held].get('maybe_alive') else ''})가 쥐고 있어 건너뜀"
                skip = set(tried) | ({i["id"] for i in q["items"]} - {only_item} if only_item else set())
                gpus_now = be.gpus()
                item = pick_candidate(ordered(q, st), st["items"], gpu, gpus_now, skip)
                wait_msg, was_idle = "", str(gpu) in st.setdefault("idle_gpus", {})
                if item is not None and wi is not None:   # Phase 4: 느린 GPU 를 비워 두고 빠른 GPU 를 기다릴지(근거는 기다림·바로 올림 모두 decisions 에 남긴다)
                    k = sum(1 for x in st["items"].values() if x["status"] == "queued")
                    w, reason = should_wait(gpu, gpus_now, k, wi["type_total"], wi["running_rem"])
                    st["decisions"] = (st.get("decisions", []) + [{"at": now_iso(), "gpu": gpu, "wait": w, "why": reason, "k": k, "type_total": wi["type_total"],
                                                                   "running_rem": {str(g): r for g, r in wi["running_rem"].items()}}])[-50:]
                    if w:
                        st["idle_gpus"].setdefault(str(gpu), {"since": now_iso(), "why": reason})
                        if not was_idle:
                            notes.append(f"[{qpath.stem}] GPU {gpu} 를 비워 두고 빠른 GPU 를 기다립니다: {reason}")
                        item, wait_msg = None, f"GPU {gpu}: 빠른 GPU 를 기다리는 중 — {reason}"
                    elif was_idle:
                        why.append(reason)
                if item is None:
                    if not wait_msg:
                        st["idle_gpus"].pop(str(gpu), None)
                    save_state(qpath, st)
                    left = sum(1 for s in st["items"].values() if s["status"] == "queued")
                    if left and not only_item and not wait_msg:
                        notes.append(f"[{qpath.stem}] GPU {gpu} 가 비었지만 들어가는 대기 판이 없습니다(남은 {left}개)")
                else:
                    st["idle_gpus"].pop(str(gpu), None)
                    s = st["items"][item["id"]]
                    session = f"{prefix}{gpu}"   # 세션 = 접두 + GPU 번호. 창 번호는 발사 때 tmux 가 준다. 같은 GPU 동시 발사는 위 occupant 검사와 이 예약이 막는다
                    log_path = item.get("log") or f"{item['log_dir']}/run.log"
                    s.update(status="launching", gpu=gpu, tmux=session, attempt=s["attempt"] + 1, reserved_epoch=time.time(), ended=None, exit=None, log=log_path)
                    msg = code_changed((st["approved"] or {}).get("code"), code_now)   # 막지 않고 알린다(결정 1: 세션이 고친 뒤 재발사한다)
                    if msg and st.get("code_noted") != code_sig(code_now):
                        st["code_noted"], st["code_changed"] = code_sig(code_now), {"msg": msg, "at": now_iso()}
                        notes.append(f"[{qpath.stem}] {msg}")
                    save_state(qpath, st)
        for n in notes:
            be.notify(n)
        if halted:
            return "승인 해시 불일치로 멈춤(halted)" if st["halted"] else ""
        if item is None:
            return wait_msg or f"GPU {gpu}: 올릴 판 없음"
        tried.add(item["id"])
        vout, detail, cancel, target = "", "", None, None
        sfile = f"{item['log_dir']}/launch-state-{launch_name(session, item['id'], s['attempt'])}.json"
        try:   # 파일 준비·tmux 호출·verify 어디서 예외가 나도 traceback 으로 죽지 않고 그 판을 닫는다
            makedirs_orig(item["log_dir"])
            script, rc_file = write_launch_script(qpath, item, s["attempt"], session, gpu)
            rc_file.unlink(missing_ok=True)
            cancel = abort_if_stopped(qpath, item["id"])   # 예약~발사 사이(락 밖, 수 초~수 분)에 halt·목록 변경이 있었는지 마지막으로 다시 본다
            if cancel is None:
                target = be.open_window(session, str(qpath.parents[2]))
                rc = be.launch(target, script, rc_file, LAUNCH_WAIT_SEC)
                outcome = classify_launch(rc, file_tail(item.get("log") or f"{item['log_dir']}/run.log"))
        except Exception as e:  # noqa: BLE001
            rc, outcome, detail = None, "exception", f" {type(e).__name__}: {e}"
        if cancel is not None:   # 발사하지 않았다 — 예약은 abort_if_stopped 가 queued 로 되돌렸다
            for n in cancel[1]:
                be.notify(n)
            return cancel[0]
        if outcome == "ok":
            # launch-set.sh rc 0 은 자체 verify 통과다. 추가 verify 는 참고 기록뿐이라 결과로 outcome 을 바꾸지 않는다 — 발사 직후 빨리 죽는 판은
            # 와쳐의 exit 2 보고(정상 경로)에 맡긴다(E2E: 20초 만에 죽은 판이 두 번째 verify 에서 거짓 verify-failed·이벤트·서명 누락을 만들었다).
            try:
                vrc, vout = be.verify(sfile)
                vout = f"rc={vrc} " + ((vout.strip().splitlines() or [""])[-1])
            except Exception as e:  # noqa: BLE001
                vout = f"verify 호출 실패 {type(e).__name__}: {e}"
        where = target or session   # 창을 만들었으면 `세션:창번호`
        with locked(qpath):
            st = load_state(qpath)
            s = st["items"][item["id"]]
            if target:
                s["tmux"] = target
            cap_closed = False
            if s["status"] != "launching":
                # 발사 중에 이미 끝났다고 알려 온 와쳐(next)나 sweep_stale 이 상태를 정했다 — running 으로 덮으면 종료 기록이 지워지고 GPU 점유가 영영 남는다.
                # 발사 증거(launch_state·verify)만 보태고 상태는 그대로 둔다.
                if outcome == "ok":
                    s.update(launch_state=sfile, verify=vout)
            elif outcome == "ok":
                s.update(status="running", started=now_iso(), launch_state=sfile, verify=vout)
            elif outcome == "refused":
                cap_closed = requeue(st, s, f"launch-set 거부(rc={rc})")
            elif outcome == "not-started":   # rc 64·67: 아무것도 뜨지 않았다 — 점유 표시 없이 닫고 이 GPU 에 다음 후보를 계속 올린다
                s.update(status="launch-failed", maybe_alive=False, fail_reason=f"not-started (launch-set rc={rc}): 인자·경로 오류 또는 같은 이름 state 존재")
            else:   # 실패는 학습이 살아 있을 수 있다(rc 65 의 rejected state·verify 실패·rc 없음·예외) — GPU 를 쥔 것으로 표시한다
                s.update(status="launch-failed", maybe_alive=True, fail_reason=f"{outcome} (launch-set rc={rc}){detail}")
            save_state(qpath, st)
            sha8 = (st["approved"] or {}).get("sha256", "")[:8]
        if outcome == "ok":
            be.oversight(f"{where} {item['id']}", f"대기 목록 {qpath.stem} 승인 해시 {sha8}", actor, str(qpath.parents[2]))
            if announce:
                be.notify(f"[{qpath.stem}] 자동 발사: 판 {item['id']} → GPU {gpu} (세션 {where})" + (f" · 기다림 판정: {'; '.join(why)}" if why else ""))
            return f"{LAUNCHED} 판 {item['id']} → GPU {gpu} (세션 {where})"
        if cap_closed:   # 거부가 상한(MAX_REFUSALS)에 닿아 이 판이 닫혔다 — 조용히 사라지면 목록이 «끝난 것»처럼 보인다
            write_event(qpath, "launch-failed", item=item["id"], gpu=gpu, outcome="refusal-cap", rc=rc, detail=f"거부 {MAX_REFUSALS}회 반복", session=where)
            be.notify(f"[{qpath.stem}] 판 {item['id']} 사전검사·발사 거부가 {MAX_REFUSALS}회 반복돼 이 판을 실패(launch-failed)로 닫았습니다 — 자동으로 다시 올라가지 않으니 GPU·CPU 자원을 확인하세요")
        if outcome != "refused":   # 거부는 «이 GPU 에 안 들어감 → 다음 후보»라는 정상 흐름이라 알림을 아낀다
            write_event(qpath, "launch-failed", item=item["id"], gpu=gpu, outcome=outcome, rc=rc, detail=detail.strip(), session=where)
            if outcome == "not-started":
                be.notify(f"[{qpath.stem}] 판 {item['id']} 발사 안 됨(launch-set rc={rc}) — 아무것도 뜨지 않아 GPU {gpu} 에 다음 후보를 계속 올립니다")
                continue
            be.notify(f"[{qpath.stem}] 판 {item['id']} 발사 {outcome} (launch-set rc={rc}){detail} — GPU {gpu}, 학습이 살아 있을 수 있어 이 GPU 에는 더 올리지 않음")
            return f"판 {item['id']} 발사 실패: {outcome} — 이 GPU 에는 더 올리지 않음"


# ───────────────────────── 하위 명령 ─────────────────────────

def qpath_of(p: str) -> Path:
    """목록 경로(심볼릭 링크를 풀지 않는다 — 프로젝트 위치를 parents 로 구하므로)."""
    return Path(os.path.abspath(p))


def parse_gpus(s: str) -> list[int]:
    """'0,1,2' → [0,1,2]"""
    try:
        v = [int(x) for x in s.split(",") if x.strip()]
    except ValueError:
        raise QueueError(f"--gpus 는 정수 목록: {s!r}")
    if not v:
        raise QueueError("--gpus 가 비어 있습니다")
    return v


def cmd_table(a, be) -> int:
    """승인 표. 이 표가 발사 전 목표 표를 겸한다."""
    qp = qpath_of(a.queue)
    raw = qp.read_bytes()
    q = parse_queue(raw, qp.stem)
    plan = plan_for(qp, q, a.gpus, be) if a.gpus else None
    cells = placement_cells(plan) if plan else {}
    print(f"대기 목록 {cell(q['name'])} — 판 {len(q['items'])}개 · 목록 sha256 {sha256(raw)[:12]}")
    print("| 순번 | 판 | 목적 | 기준판 | 변경 사항 | VRAM(GB) | CPU 코어 | 배치 |")
    print("|---|---|---|---|---|---|---|---|")
    for i, it in enumerate(q["items"], 1):
        print(f"| {i} | {cell(it['id'])} | {cell(it['purpose'])} | {cell(it['baseline'])} | {cell(it['change'])} | {it['vram_gb']} | {it['cpu_cores']} | {cell(cells.get(it['id'], '-'))} |")
    print("\n실행 요약(승인하면 이 명령이 실행됩니다. 시크릿 형태 값은 가립니다):")
    for it in q["items"]:
        argv = cell(mask(" ".join(it["argv"])))
        print(f"- {cell(it['id'])}: 명령 `{argv}` · log_dir {cell(it['log_dir'])}")
        # 승인 표는 «실행에 쓰이는 필드 전부»를 보인다(eval_cmd·watcher_args·memguard_args 는 셸·와쳐에 그대로 들어간다 — 요약에서 가리면 승인 범위가 눈에 안 보인다).
        # --full 은 옛 호출 호환용으로 받기만 한다.
        for k in (*[k for k in REQUIRED if k not in ("id", "purpose", "baseline", "change", "argv", "vram_gb", "cpu_cores", "log_dir")], *OPTIONAL):
            if k in it:
                print(f"    · {k}: {cell(mask(str(it[k])))}")
    if plan:
        print_placement(plan)
    return 0


def plan_for(qp: Path, q: dict, gpus_arg: str, be) -> dict:
    """--gpus 의 GPU 이름(nvidia-smi)과 프로젝트 선언(train.env)으로 배치 제안을 만든다."""
    ids, info = parse_gpus(gpus_arg), be.gpus()
    if [g for g in ids if g not in info]:
        raise QueueError(f"nvidia-smi 에 없는 GPU 번호: {[g for g in ids if g not in info]}")
    return propose_placement([it["id"] for it in q["items"]], {g: info[g] for g in ids}, read_env(qp), json.loads(PLACEMENT_TABLE.read_text()))


def cmd_place(a, be) -> int:
    """판 < GPU 배치 «제안»(표 출력만). 발사하지 않는다."""
    qp = qpath_of(a.queue)
    q = parse_queue(qp.read_bytes(), qp.stem)
    print_placement(plan_for(qp, q, a.gpus, be))
    return 0


def cmd_approve(a, be) -> int:
    """현재 목록의 해시를 승인으로 기록한다(halted 해제). 사용자가 표에서 «이대로»를 고른 뒤에만 부른다."""
    qp = qpath_of(a.queue)
    code = code_snapshot(qp.parents[2])   # git 은 락 밖에서
    with locked(qp):
        raw = qp.read_bytes()
        q = parse_queue(raw, qp.stem)
        check_secrets(q)
        st = load_state(qp)
        st["approved"] = {"sha256": sha256(raw), "at": now_iso(), "session": a.session, "code": code}
        st["halted"] = None
        st["idle_gpus"] = {}   # 낡은 «기다리는 중» 기록을 비운다(재평가는 다음 발사 때 새로 한다)
        st.pop("code_noted", None)
        if sync_items(st, q):
            st["finished_emitted"] = False   # 새 판이 붙으면 목록 종료 이벤트를 다시 낼 수 있다
        save_state(qp, st)
    be.sign("approve", f"{qp.stem} {st['approved']['sha256'][:12]}", f"세션 {a.session}: 대기 목록 승인(판 {len(q['items'])}개)", "queue-approve", str(qp.parents[2]))
    print(f"승인 기록: {qp.stem} sha256 {st['approved']['sha256'][:12]} (판 {len(q['items'])}개, 세션 {a.session})" + (f" · 코드 HEAD {code['head'][:8]}" if code else ""))
    maybe_finish(qp, be)
    if any(s["status"] == "queued" for s in st["items"].values()):   # approve 는 발사하지 않는다 — 이어서 올리려면 start(이미 도는 GPU 는 건너뛴다)
        print(f"발사를 이어가려면 start --gpus … 를 실행하십시오: launch_queue.py start {qp} --gpus <빈 GPU 번호>")
    return 0


def cmd_halt(a, be) -> int:
    """정지 스위치: 이후 start·next·relaunch 가 아무것도 올리지 않는다(해제는 approve 재실행뿐). 이벤트·알림은 처음 한 번."""
    qp = qpath_of(a.queue)
    with locked(qp):
        st = load_state(qp)
        first = not st["halted"]
        if first:
            st["halted"] = {"reason": "manual-halt", "detail": a.reason, "at": now_iso()}
            save_state(qp, st)
    if first:
        write_event(qp, "halted", reason=a.reason)
        be.notify(f"[{qp.stem}] 사용자 정지: {a.reason} — 자동 발사 중지(해제는 approve 재실행)")
        be.sign("other", f"{qp.stem} halt", f"정지: {a.reason}", "queue-halt", str(qp.parents[2]))
    print(f"정지{'했습니다' if first else ' 상태입니다(이미 멈춤)'}: {a.reason}", flush=True)
    return 0


def cmd_include_gpu(a, be) -> int:
    """연속 재실패로 제외된 GPU 를 사슬에 다시 넣는다(근거는 감시 서명에 남긴다)."""
    qp = qpath_of(a.queue)
    with locked(qp):
        st = load_state(qp)
        if a.gpu not in st["excluded_gpus"]:
            raise QueueError(f"GPU {a.gpu} 는 제외 상태가 아닙니다")
        st["excluded_gpus"].remove(a.gpu)
        st.get("gpu_refail", {}).pop(str(a.gpu), None)
        st.pop("all_excluded_emitted", None)
        save_state(qp, st)
    be.sign("approve", f"{qp.stem} gpu{a.gpu} 제외 해제", f"{a.by}: {a.reason}", "queue-include-gpu", str(qp.parents[2]))
    print(f"GPU {a.gpu} 를 자동 발사 대상에 다시 넣었습니다({a.reason})", flush=True)
    if a.then_next:
        print(launch_one(qp, a.gpu, be, "queue-include", announce=True), flush=True)
    maybe_finish(qp, be)
    return 0


def cmd_start(a, be) -> int:
    """지정 GPU 마다 첫 판을 올린다. 순서대로 하나씩 올려 뒤 판의 CPU 표본이 앞 판의 부하를 반영하게 한다."""
    qp = qpath_of(a.queue)
    gpus = parse_gpus(a.gpus)
    if len(set(gpus)) != len(gpus):
        raise QueueError(f"--gpus 에 같은 GPU 가 두 번 있습니다: {a.gpus}", code=64)
    for gpu in gpus:
        print(launch_one(qp, gpu, be, "queue-start", announce=False), flush=True)
    maybe_finish(qp, be)   # 최초 발사가 전부 실패(launch-failed)하면 이후 next 가 올 판이 없어 여기서 끝을 알려야 queue-finished 가 나온다
    return 0


def cmd_next(a, be) -> int:
    """와쳐 --on-exit: 끝난 판 상태 기록 → 승인 해시 확인 → 같은 GPU 에 다음 판 발사."""
    qp = qpath_of(a.queue)
    with locked(qp):
        st = load_state(qp)
        s = st["items"].get(a.item)
        # 시도 결박: 이전 시도(재발사 전)의 와쳐나 재부착으로 겹친 와쳐의 보고가 «현재 판»을 종료 처리하고 GPU 점유를 지우던 결함.
        # 현재 시도와 다르거나(--attempt 가 있을 때) 이미 처리된(running·launching 이 아닌) 보고는 아무것도 바꾸지 않고 무시한다.
        # --attempt 가 없는 옛 호출도 상태가 running·launching 일 때만 반영한다.
        # maybe_alive 인 launch-failed(발사 verify 실패·예약 만료)·timeout(와쳐 타임아웃·평가 시간 초과·신호 중단) 판은 학습이 실제로 돌고 있을 수 있고,
        # 다시 부착(reattach)된 와쳐가 같은 시도 번호로 종료를 보고한다 — 그 보고는 받아야 GPU 점유가 풀린다(사람이 release 하기 전의 정상 복구 경로).
        open_report = s is not None and (s["status"] in ("running", "launching") or (s.get("maybe_alive") and s["status"] in ("launch-failed", "timeout")))
        if s is not None and (not open_report or (a.attempt is not None and s["attempt"] != a.attempt)):
            why = f"시도 {a.attempt} ≠ 현재 {s['attempt']}" if a.attempt is not None and s["attempt"] != a.attempt else f"이미 {s['status']} 로 처리됨"
            print(f"[next] 판 {a.item} 종료 보고(코드 {a.exit}, GPU {a.gpu}) 무시: {why}", flush=True)
            return 0
        tags = record_exit(st, a.item, a.gpu, a.exit)
        s = st["items"].get(a.item) or {}
        save_state(qp, st)
    print(f"[next] 판 {a.item} 종료 코드 {a.exit} 기록 (GPU {a.gpu})", flush=True)
    if "needs-fix" in tags:   # 세션을 깨운다. 그 GPU 에는 아래에서 다음 판을 계속 올린다
        log = s.get("log") or ""
        write_event(qp, "needs-fix", item=a.item, gpu=a.gpu, attempt=s.get("attempt"), session=s.get("tmux"), log=log,
                    watcher_report=(log[:-4] if log.endswith(".log") else log) + ".watch-report.md", launch_state=s.get("launch_state"),
                    hint=f"원인이 경로·import·인자 오류일 때만 고친 뒤: launch_queue.py relaunch {qp} --item {a.item} --fix-note '무엇을 고쳤나' (판당 1회, 목록 파일은 바꾸지 않는다). "
                         "로직 오류·메모리 부족·권한 오류면 재발사하지 말고 사용자에게 보고(D8)")
    if "refusal-cap" in tags:   # 와쳐가 memguard 거부(5)를 MAX_REFUSALS 번 보고해 이 판이 닫혔다
        write_event(qp, "launch-failed", item=a.item, gpu=a.gpu, outcome="refusal-cap", rc=a.exit, detail=f"거부 {MAX_REFUSALS}회 반복", session=s.get("tmux"))
        be.notify(f"[{qp.stem}] 판 {a.item} memguard 발사 거부가 {MAX_REFUSALS}회 반복돼 이 판을 실패(launch-failed)로 닫았습니다 — 자동으로 다시 올라가지 않으니 메모리 예산을 확인하세요")
    if "refailed" in tags:   # 알림 1회. 이 판만 닫고 나머지는 계속 올린다
        msg = f"[{qp.stem}] 판 {a.item} 재발사 후 다시 비정상 종료 → 이 판만 실패로 닫고 나머지 판은 계속 올립니다"
        if "gpu-excluded" in tags:
            write_event(qp, "gpu-excluded", gpu=a.gpu, items=st["gpu_refail"].get(str(a.gpu), []))
            msg += f" · GPU {a.gpu} 에서 서로 다른 두 판이 연속 재실패해 이 GPU 는 자동 발사에서 뺍니다"
            msg += all_excluded_note(qp)
        be.notify(msg)
    if a.exit in HOLD_CODES:   # 와쳐만 접었거나(4·7) 평가가 멈춰 있다(6) — 학습·평가는 살아 있어 이 GPU 사슬은 여기서 끊는다(계획서의 «다음 판을 올린다»에서 벗어난 승인된 편차)
        what = {4: "와쳐 타임아웃(4)", 6: "평가 시간 초과(6, 평가는 죽이지 않음)", 7: "와쳐 신호 중단(7)"}[a.exit]
        be.notify(f"[{qp.stem}] 판 {a.item} {what}: 학습·평가가 살아 있을 수 있어 GPU {a.gpu} 에 다음 판을 올리지 않습니다(확인 뒤 release)")
        print(f"GPU {a.gpu}: {what}라 다음 판을 올리지 않음", flush=True)
    else:
        print(launch_one(qp, a.gpu, be, "watcher-queue", announce=True), flush=True)
    reevaluate_idle(qp, be, skip=a.gpu)
    maybe_finish(qp, be)
    return 0


def all_excluded_note(qp: Path) -> str:
    """이 큐가 아는 GPU 가 전부 제외됐고 queued 가 남았으면 all-gpus-excluded 이벤트를 한 번 쓰고 알림에 덧붙일 문구를 돌려준다(아니면 빈 문자열)."""
    with locked(qp):
        st = load_state(qp)
        known = {s["gpu"] for s in st["items"].values() if s["gpu"] is not None}
        left = sum(1 for s in st["items"].values() if s["status"] == "queued")
        if st.get("all_excluded_emitted") or not left or not known <= set(st["excluded_gpus"]):
            return ""
        st["all_excluded_emitted"] = True
        save_state(qp, st)
    write_event(qp, "all-gpus-excluded", excluded=sorted(st["excluded_gpus"]), queued=left)
    return f" · 모든 GPU({sorted(known)})가 제외돼 대기 판 {left}개가 더 올라가지 않습니다(include-gpu 로 해제)"


def reevaluate_idle(qp: Path, be, skip: int | None = None) -> None:
    """기다리느라 비워 둔 느린 GPU(idle_gpus)를 다시 평가한다. 빠른 GPU 쪽이 실패·타임아웃·점유 유지로 끝나 깨워 줄 next 가 발사하지 않는 경우에도 판이 굶지 않게,
    next·relaunch·release 끝에 부른다. 아직 기다릴 만하면 그대로 두고, 아니면 launch_one 이 그 GPU 에 올린다. skip = 방금 처리한 GPU."""
    for g in [int(x) for x in load_state(qp).get("idle_gpus", {}) if int(x) != skip]:
        print(launch_one(qp, g, be, "queue-reeval", announce=True), flush=True)


def maybe_finish(qp: Path, be) -> None:
    """모든 판이 끝났으면(TERMINAL) queue-finished 이벤트와 알림을 한 번만 낸다. 멈춤(halted) 중이거나 이미 냈으면 아무것도 안 한다.
    살아 있을 수 있는 학습(maybe_alive)이 남아 있으면 이벤트 본문과 알림에 개수를 적는다."""
    with locked(qp):
        st = load_state(qp)
        live = {pid: s for pid, s in st["items"].items() if s["status"] != "removed"}   # removed(재승인 때 빠진 판)는 세지 않는다
        if st["halted"] or st.get("finished_emitted") or not live or any(s["status"] not in TERMINAL for s in live.values()):
            return
        st["finished_emitted"] = True
        bad = [pid for pid, s in live.items() if s["status"] != "done"]
        alive = [pid for pid, s in live.items() if s.get("maybe_alive")]
        save_state(qp, st)
        write_event(qp, "queue-finished", done=len(live) - len(bad), failed=bad, maybe_alive=alive)
    be.notify(f"[{qp.stem}] 대기 목록 종료: 완료 {len(live) - len(bad)}판 · 실패 {len(bad)}판" + (f"({', '.join(bad)}) — summary 로 표를 보세요" if bad else "")
              + (f" · 살아 있을 수 있는 학습 {len(alive)}개({', '.join(alive)})" if alive else ""))


def cmd_relaunch(a, be) -> int:
    """needs-fix 판을 판당 1회 다시 올린다. 목록 파일은 바꾸지 않는다 — 발사 인자를 바꿨다면 승인 해시가 달라져 거부된다(재승인 필요)."""
    qp = qpath_of(a.queue)
    notes: list[str] = []
    with locked(qp):
        st = load_state(qp)
        ok = gate(qp, st, qp.read_bytes(), notes)
        save_state(qp, st)
        s = st["items"].get(a.item)
        if ok:
            if s is None:
                raise QueueError(f"목록에 없는 판: {a.item}")
            if s["status"] != "needs-fix":
                raise QueueError(f"relaunch 는 needs-fix 판만 받습니다(판 {a.item} 은 {s['status']})")
            if s.get("fixes", 0) >= 1:
                raise QueueError(f"판 {a.item} 은 이미 한 번 재발사했습니다(판당 1회 한정)")
            s.update(status="queued", fixes=1, fix_note=a.fix_note, rank=min(x["rank"] for x in st["items"].values()) - 1, maybe_alive=False)
            save_state(qp, st)
        known = [s["gpu"]] + [x["gpu"] for x in st["items"].values() if x["gpu"] is not None] if ok else []
    for n in notes:
        be.notify(n)
    if not ok:
        raise QueueError("재승인 필요: 대기 목록이 승인 뒤 바뀌었거나 자동 발사가 멈춘 상태입니다. 발사 인자를 바꿔야 하는 수정은 목록을 고친 뒤 표를 다시 보이고 approve 를 다시 실행하세요")
    be.sign("launch", f"{qp.stem} {sha256(qp.read_bytes())[:12]}", f"판 {a.item} 재발사: {a.fix_note}", "queue-relaunch", str(qp.parents[2]))
    gpus = list(dict.fromkeys(([] if not a.gpus else parse_gpus(a.gpus)) + [g for g in known if g is not None]))
    for g in gpus:
        res = launch_one(qp, g, be, "queue-relaunch", announce=True, only_item=a.item)
        print(res, flush=True)
        if res.startswith(LAUNCHED):
            break
    else:
        # GPU 가 없어서만 여기 오는 것이 아니다 — 발사 불가·발사 실패·멈춤(halted)으로 못 올린 경우에도 온다. 판의 실제 상태로 문구를 가른다.
        now_status = load_state(qp)["items"][a.item]["status"]
        if not gpus:
            print(f"빈 GPU 가 없어 판 {a.item} 을 대기 맨 앞에 두었습니다(GPU 가 비는 대로 먼저 올라갑니다)", flush=True)
        elif now_status == "queued":
            print(f"이번에는 판 {a.item} 을 올리지 못해 대기 맨 앞에 두었습니다(위 GPU 별 결과 참조 — GPU 가 비는 대로 먼저 올라갑니다)", flush=True)
        else:
            print(f"판 {a.item} 은 지금 {now_status} 상태입니다(위 GPU 별 결과 참조)", flush=True)
    reevaluate_idle(qp, be)
    maybe_finish(qp, be)
    return 0


def cmd_release(a, be) -> int:
    """«살아 있을 수 있음»(maybe_alive)을 사람이 내린다 — 세션이 PID 사망을 확인한 뒤. 누가·왜를 state 에 남긴다."""
    qp = qpath_of(a.queue)
    with locked(qp):
        st = load_state(qp)
        s = st["items"].get(a.item)
        if s is None or not s.get("maybe_alive"):
            raise QueueError(f"판 {a.item} 은 «살아 있을 수 있음» 표시가 없습니다")
        s["maybe_alive"] = False
        s.setdefault("released", []).append({"by": a.by, "reason": a.reason, "at": now_iso()})
        gpu = s["gpu"]
        save_state(qp, st)
    be.sign("approve", f"{qp.stem} 판 {a.item} release", f"{a.by}: {a.reason}", "queue-release", str(qp.parents[2]))
    print(f"판 {a.item}: GPU {gpu} 점유 표시를 내렸습니다({a.by}: {a.reason})", flush=True)
    if a.then_next:
        print(launch_one(qp, gpu, be, "queue-release", announce=True), flush=True)
    reevaluate_idle(qp, be)
    maybe_finish(qp, be)
    return 0


def failure_rows(q: dict | None, st: dict) -> list[list[str]]:
    """실패 판 표의 행: 판 · 목적 · 실패 단계 · 사유 · 고친 내용 · GPU."""
    stage = {"failed": "재발사 후 재실패", "launch-failed": "발사 실패", "eval-failed": "평가 실패", "timeout": "와쳐 타임아웃(학습 생존 가능)"}
    purpose = {it["id"]: it["purpose"] for it in (q or {}).get("items", [])}
    return [[pid, purpose.get(pid, "-"), stage[s["status"]], s.get("fail_reason") or "-", s.get("fix_note") or "-", "-" if s["gpu"] is None else str(s["gpu"])]
            for pid, s in st["items"].items() if s["status"] in stage]


def cmd_summary(a, be) -> int:
    """목록이 끝났으면 실패 판만 GFM 표로, 아니면 끝나지 않았다는 사실과 남은 수를 출력한다."""
    qp = qpath_of(a.queue)
    st = load_state(qp)
    count = lambda *names: sum(1 for s in st["items"].values() if s["status"] in names)   # noqa: E731
    live = {pid: s for pid, s in st["items"].items() if s["status"] != "removed"}
    if not live or any(s["status"] not in TERMINAL for s in live.values()):
        print(f"목록이 아직 끝나지 않았습니다: 대기 {count('queued')} · 발사 중 {count('launching')} · 실행 중 {count('running')} · 수정 대기(needs-fix) {count('needs-fix')}")
        return 0
    try:
        q = parse_queue(qp.read_bytes(), qp.stem)
    except (QueueError, OSError):
        q = None   # 목록이 바뀌었거나 깨졌어도 state 의 실패 기록은 보인다(목적 열만 «-»)
    rows = failure_rows(q, st)
    alive = [pid for pid, s in live.items() if s.get("maybe_alive")]
    if not rows:
        print(f"대기 목록 종료: 판 {len(live)}개 모두 완료, 실패 없음")
    else:
        print(f"대기 목록 종료: 판 {len(live)}개 중 실패 {len(rows)}개")
        print("| 판 | 목적 | 실패 단계 | 사유 | 고친 내용 | GPU |")
        print("|---|---|---|---|---|---|")
        for r in rows:
            print("| " + " | ".join(cell(c) for c in r) + " |")
    if alive:
        print(f"살아 있을 수 있는 학습 {len(alive)}개: {', '.join(alive)} (확인 후 release)")
    return 0


def event_files(qp: Path, pending: bool) -> list[Path]:
    """이벤트 파일(이름순 = 시간순). pending 이면 소비 표시(.consumed)가 안 붙은 것만."""
    d = qp.with_name(qp.stem + ".events")
    if not d.is_dir():
        return []
    return sorted(d.glob("*.json") if pending else [*d.glob("*.json"), *d.glob("*.consumed")], key=lambda p: p.name)


def missing_watchers(st: dict) -> list[str]:
    """도는 판 중 와쳐가 죽어 있는(자동 발사 사슬이 끊긴) 판 경고 문구. 읽기만 한다."""
    return [f"판 {pid}(GPU {s['gpu']}) 와쳐 없음(자동 발사 사슬 끊김)" for pid, s in st["items"].items()
            if s["status"] == "running" and watcher_alive(s.get("launch_state")) is False]


def note_lost_watchers(qp: Path, be) -> None:
    """도는(running) 판의 와쳐 PID 가 죽어 있으면 판마다 한 번 watcher-lost 이벤트·알림을 낸다(state 의 watcher_lost 로 중복 방지).

    와쳐가 SIGTERM·INT 면 종료 훅이 코드 7 로 판을 보류하지만 SIGKILL·OOM 으로 죽으면 훅이 없어 사슬이 조용히 끊긴다 — 그 빈자리를 wait-event 가 메운다.
    락 없이 먼저 훑고 새로 잃은 판이 있을 때만 락을 잡는다(폴링마다 락을 잡지 않는다).
    2026-10-01 P6 검수: reattach 로 와쳐가 다시 살아난 판(running 이고 와쳐 PID 확인됨)은 watcher_lost 표시를 지운다 — 안 지우면 두 번째 사망에 알림이 없다.
    """
    def lost_now(s):
        return s["status"] == "running" and not s.get("watcher_lost") and watcher_alive(s.get("launch_state")) is False

    def recovered(s):
        return s["status"] == "running" and s.get("watcher_lost") and watcher_alive(s.get("launch_state")) is True

    try:
        if not [pid for pid, s in load_state(qp)["items"].items() if lost_now(s) or recovered(s)]:
            return
    except (OSError, ValueError):
        return
    lost: list[tuple[str, int | None]] = []
    with locked(qp):
        st = load_state(qp)
        for pid, s in st["items"].items():
            if recovered(s):
                s.pop("watcher_lost")
            elif lost_now(s):
                s["watcher_lost"] = now_iso()
                lost.append((pid, s["gpu"]))
        save_state(qp, st)
    for pid, g in lost:
        write_event(qp, "watcher-lost", item=pid, gpu=g, hint="와쳐 프로세스가 없는데 판이 running 입니다 — 학습 PID 를 확인하고 와쳐만 reattach(launch-set.sh reattach)하세요. 자동 발사 사슬이 끊겨 있습니다")
        be.notify(f"[{qp.stem}] 판 {pid}(GPU {g}) 와쳐가 죽었습니다 — 자동 발사 사슬이 끊겼습니다. 학습 생존 확인 뒤 와쳐 재부착이 필요합니다")


def cmd_events(a, be) -> int:
    """이벤트를 소비하지 않고 보여 준다(예약 점검 안전망). 밀린 이벤트도 경고도 없으면 아무것도 출력하지 않는다. 깨진 파일은 건너뛴다."""
    qp = qpath_of(a.queue)
    for p in event_files(qp, a.pending):
        try:
            print(json.dumps({"file": p.name, **json.loads(p.read_text())}, ensure_ascii=False), flush=True)
        except ValueError:
            print(f"경고: 깨진 이벤트 파일 건너뜀: {p.name}", flush=True)
    for w in missing_watchers(load_state(qp)):
        print(f"경고: {w}", flush=True)
    return 0


def cmd_wait_event(a, be) -> int:
    """처리 안 된 이벤트가 생길 때까지 기다렸다가 한 줄 JSON 으로 출력하고 소비 표시(.consumed)를 붙인다. 시간 만료는 rc 3.

    세션이 백그라운드 명령으로 걸어 스스로 깨어나는 용도다(한 번에 약 2시간 한도라 기본 6900초). rename 으로 소비해 두 wait-event 가 같은 이벤트를 두 번 내지 않는다.
    """
    qp, end, interval = qpath_of(a.queue), time.time() + a.timeout, max(a.interval, MIN_INTERVAL)
    while True:
        note_lost_watchers(qp, be)   # SIGKILL 로 죽은 와쳐는 종료 훅을 못 불러 사슬이 조용히 끊긴다 — 도는 판의 와쳐가 죽어 있으면 watcher-lost 이벤트를 한 번 쓴다
        out = []
        for p in event_files(qp, pending=True):
            try:
                ev = {"file": p.name, **json.loads(p.read_text())}   # 파싱에 성공한 것만 소비한다
            except (ValueError, OSError):
                with contextlib.suppress(OSError):
                    os.rename(p, p.with_name(p.name + ".bad"))      # 깨진 파일은 .bad 로 치우고 건너뛴다
                continue
            done = p.with_name(p.name + ".consumed")
            try:
                os.rename(p, done)
            except FileNotFoundError:   # 다른 wait-event 가 먼저 가져감
                continue
            try:   # 소비 표시를 붙인 뒤 출력이 실패하면(세션이 끊겨 파이프가 닫힘) 이벤트가 영영 사라지므로 표시를 되돌린다
                print(json.dumps(ev, ensure_ascii=False), flush=True)
            except OSError:
                with contextlib.suppress(OSError):
                    os.rename(done, p)
                raise
            out.append(ev)
        if out:
            return 0
        if time.time() >= end:
            print("wait-event 시간 만료: 새 이벤트 없음 — 다시 거세요", flush=True)
            return 3
        time.sleep(max(min(interval, end - time.time()), 0))


def cmd_status(a, be) -> int:
    """판별 상태 표."""
    qp = qpath_of(a.queue)
    st = load_state(qp)
    ap = st["approved"]
    print(f"승인: {ap['sha256'][:12] + ' ' + ap['at'] + ' ' + str(ap['session']) if ap else '없음'} · halted: {st['halted']['reason'] if st['halted'] else '아니오'} · 제외 GPU: {st['excluded_gpus'] or '없음'}")
    for w in missing_watchers(st):
        print(f"경고: {w}")
    if st.get("idle_gpus"):
        idle = ", ".join(g + "(" + v["why"] + ")" for g, v in st["idle_gpus"].items())
        print(f"비워 두고 기다리는 GPU: {idle}")
    print("| 판 | 상태 | GPU | 세션 | 시도 | 종료 코드 | 비고 |")
    print("|---|---|---|---|---|---|---|")
    for pid, s in sorted(st["items"].items(), key=lambda kv: kv[1]["rank"]):
        note = " · ".join(x for x in (s["fail_reason"], "학습 생존 가능(release 필요)" if s.get("maybe_alive") else "", f"고친 내용: {s['fix_note']}" if s.get("fix_note") else "") if x)
        print(f"| {pid} | {s['status']} | {s['gpu'] if s['gpu'] is not None else '-'} | {s['tmux'] or '-'} | {s['attempt']} | {s['exit'] if s['exit'] is not None else '-'} | {note} |")
    return 0


def main(argv=None, backend=None) -> int:
    """진입점. backend 는 시험이 FakeBackend 를 주입하는 자리."""
    p = argparse.ArgumentParser(description="와쳐 자동 발사 대기 목록 도구")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("table", cmd_table), ("approve", cmd_approve), ("start", cmd_start), ("status", cmd_status), ("place", cmd_place),
                     ("wait-event", cmd_wait_event), ("events", cmd_events), ("relaunch", cmd_relaunch), ("release", cmd_release), ("summary", cmd_summary),
                     ("halt", cmd_halt), ("include-gpu", cmd_include_gpu)):
        sp = sub.add_parser(name)
        sp.add_argument("queue")
        sp.set_defaults(fn=fn)
        if name in ("table", "start", "place", "relaunch"):
            sp.add_argument("--gpus", required=(name in ("start", "place")))
        if name == "table":
            sp.add_argument("--full", action="store_true")
        if name == "approve":
            sp.add_argument("--session", default="unknown")
        if name == "halt":
            sp.add_argument("--reason", required=True)
        if name == "include-gpu":
            sp.add_argument("--gpu", type=int, required=True)
            sp.add_argument("--reason", required=True)
            sp.add_argument("--by", default=os.environ.get("USER") or "unknown")
            sp.add_argument("--then-next", action="store_true")
        if name == "wait-event":
            sp.add_argument("--timeout", type=float, default=6900)
            sp.add_argument("--interval", type=float, default=30)
        if name == "events":
            sp.add_argument("--pending", action="store_true")
        if name in ("relaunch", "release"):
            sp.add_argument("--item", required=True)
        if name == "relaunch":
            sp.add_argument("--fix-note", required=True)
        if name == "release":
            sp.add_argument("--reason", required=True)
            sp.add_argument("--by", default=os.environ.get("USER") or "unknown")
            sp.add_argument("--then-next", action="store_true")
    sp = sub.add_parser("next")
    sp.add_argument("--queue", required=True)
    sp.add_argument("--item", required=True)
    sp.add_argument("--gpu", type=int, required=True)
    sp.add_argument("--exit", type=int, required=True)
    sp.add_argument("--attempt", type=int, default=None)   # 선택 — 없으면(옛 와쳐) 시도 대조 없이 상태만 본다
    sp.set_defaults(fn=cmd_next)
    a = p.parse_args(argv)
    global _ORIG_UMASK
    old_umask = _ORIG_UMASK = os.umask(0o077)   # state·이벤트·발사 스크립트는 소유자만(폴더 0700·파일 0600). 학습 로그 폴더·자식 프로세스는 원래 값을 쓴다
    try:
        be = backend or make_backend()
        try:
            return a.fn(a, be)
        except QueueError as e:
            print(f"[launch_queue] 오류: {e}", file=sys.stderr)
            return e.code
        except Exception as e:  # noqa: BLE001 — traceback 으로 죽지 않는다. 발사 계열은 이벤트·알림 1회를 남겨 세션이 알게 한다
            print(f"[launch_queue] 예외: {type(e).__name__}: {e}", file=sys.stderr)
            if a.cmd in ("next", "start", "relaunch"):
                with contextlib.suppress(Exception):
                    qp = qpath_of(a.queue)
                    write_event(qp, "launch-blocked", reason=f"예외 {type(e).__name__}: {e}")
                    be.notify(f"[{qp.stem}] {a.cmd} 중 예외로 멈췄습니다: {type(e).__name__}: {e}")
            return 1
    finally:
        os.umask(old_umask)
        _ORIG_UMASK = None


if __name__ == "__main__":
    sys.exit(main())
