"""agent_usage_report.py: main 세션 기록에서 에이전트(Agent · Task) 호출을 읽기 전용으로 세어 통합 후보 조사용 표를 낸다.

무엇을: 의뢰서 intent/2026-11-24-harness-review-six-items.md 개정 2 의 W15 성공 기준 2(종류별 호출 수 · 함께 불리는 쌍, 수치는 저장한
  스크립트로 낸다). 표 여섯 개를 건수만으로 낸다.
  1) 종류(subagent_type)별 호출 수: 최근 30일 · 최근 90일 · 창 전체(경계는 until 기준)
  2) 같은 턴 안에서 함께 불린 종류 쌍(순서 없음, 턴마다 한 번) 위에서 20쌍
  3) 같은 턴 안에서 바로 이어 불린 순서쌍(A 다음 B, 같은 종류끼리 포함) 위에서 20쌍
  4) 종류별 model 인자를 준 비율과 값의 분포
  5) 턴당 호출 수 분포(0 · 1 · 2 ~ 3 · 4 이상)
  6) 세션의 도구 정의 수: api-request-shape 항목의 shape.tools 길이(요청에 실린 도구 정의 수). 세션마다 가장 큰 값을 쓴다. 지연 로드 도구는 불러온 뒤에만
     목록에 든다. 창 안 턴이 있는 세션에 이 항목이 하나도 없으면 «기록에 없음».
  기록 읽기 · 턴 가르기는 rule_reduction_metrics.py 의 iter_main_files · iter_events 를 불러 쓴다(사람 글 판정 · 중복 uuid · sidechain ·
  링크 거부 · 크기 상한 · 시간 예산이 같다). 턴은 시작 시각이 [since, until) 안인 것만 세고 재로드 경계는 적용하지 않는다.
  첫 사람 글 앞의 호출은 시각을 정할 수 없어 머리에 따로 센다.
사용: uv run --no-project python scripts/agent_usage_report.py [--since ISO] [--until ISO] [--home DIR]
  기본 창은 지금부터 거꾸로 90일. 종료 코드 0, 사용 오류 · 예기치 못한 예외 2. 아무 파일도 쓰지 않는다.
출력에서 빼는 것: 프롬프트 · description 본문 · 경로 · 세션 id · 프로젝트 이름. subagent_type · model 값은 [A-Za-z0-9_.:-] 만 남겨 60자로 자른다.
행 수 상한: 표 1 · 4 는 위에서 MAX_ROWS(30)종 + «그 밖 M종 합계», 표 2 · 3 은 위에서 20쌍, 값 분포 칸은 10개 + «그 밖» (조작된 기록이 출력을 부풀리지 못하게).
큰 줄 · 깊은 중첩 줄 · 시간 예산 방어는 rule_reduction_metrics.py 의 iter_lines · iter_events 를 그대로 따른다.
시험: scripts/tests/test_agent_usage_report.py
REF: knowledge/harness/code-history/scripts__agent_usage_report.py.md
"""
from __future__ import annotations

import argparse
import itertools
import re
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import rule_reduction_metrics as rrm

AGENT_TOOLS = ("Agent", "Task")
TOP = 20
MAX_CELL_ITEMS = 10


def clean(v, empty: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_.:-]", "", v[:rrm.REGEX_MAX_CHARS])[:60] if isinstance(v, str) else ""
    return s or empty


def scan(home: Path, since: datetime, until: datetime, deadline: float) -> dict:
    res = {"skipped": Counter(), "out_mtime": 0, "read": 0, "partial": None, "turns": [], "pre_turn_calls": 0,
           "tool_defs": [], "sessions": 0, "files": Counter()}
    for _pi, n, fh, start in rrm.iter_main_files(home / "projects", since, res):
        turn, turns, max_defs, pre = None, [], None, 0
        try:
            for ev in rrm.iter_events(fh, start, res["files"], deadline):
                kind = ev[0]
                if kind == "turn":
                    turn = {"ts": ev[1], "calls": []} if ev[1] is not None and since <= ev[1] < until else {"ts": None, "calls": None}
                    if turn["ts"] is not None:
                        turns.append(turn)
                elif kind == "tool" and ev[1].get("name") in AGENT_TOOLS:
                    if turn is None:
                        pre += 1
                    elif turn["calls"] is not None:
                        inp = ev[1].get("input") if isinstance(ev[1].get("input"), dict) else {}
                        turn["calls"].append((clean(inp.get("subagent_type"), "(지정 없음)"), inp.get("model")))
                elif kind == "tools":
                    max_defs = ev[1] if max_defs is None else max(max_defs, ev[1])
        except rrm.BudgetExceeded:
            res["partial"] = n
        res["turns"] += turns
        res["pre_turn_calls"] += pre
        if turns:
            res["sessions"] += 1
            if max_defs is not None:
                res["tool_defs"].append(max_defs)
        if res["partial"]:
            break
    return res


def dist_cell(m: Counter) -> str:
    items = sorted(m.items(), key=lambda x: (-x[1], x[0]))
    rest = items[MAX_CELL_ITEMS:]
    return " · ".join([f"{k} {v}" for k, v in items[:MAX_CELL_ITEMS]] + ([f"그 밖 {len(rest)}종 {sum(v for _, v in rest)}"] if rest else []))


def render(since: datetime, until: datetime, r: dict, elapsed: float) -> str:
    cut30, cut90 = until - timedelta(days=30), until - timedelta(days=90)
    by_type: dict[str, Counter] = {}
    pairs, seqs, per_turn = Counter(), Counter(), Counter()
    models: dict[str, Counter] = {}
    total = 0
    for t in r["turns"]:
        calls = t["calls"]
        k = len(calls)
        per_turn["0" if k == 0 else "1" if k == 1 else "2 ~ 3" if k <= 3 else "4 이상"] += 1
        for typ, model in calls:
            total += 1
            c = by_type.setdefault(typ, Counter())
            c["all"] += 1
            c["d90"] += t["ts"] >= cut90
            c["d30"] += t["ts"] >= cut30
            m = models.setdefault(typ, Counter())
            m["(인자 없음)" if not isinstance(model, str) or not model else clean(model, "(빈 값)")] += 1
        for a, b in itertools.combinations(sorted({typ for typ, _ in calls}), 2):
            pairs[(a, b)] += 1
        for (a, _), (b, _) in itertools.pairwise(calls):
            seqs[(a, b)] += 1
    skipped = sum(r["skipped"].values())
    why = " · ".join(f"{k} {v}" for k, v in sorted(r["skipped"].items())) or "없음"
    status = f"부분 결과(시간 예산 {rrm.TIME_BUDGET_S:g}초 초과, {r['partial']}번째 파일에서 멈춤)" if r["partial"] else "완전"
    lines = [
        "# 에이전트 호출 집계", "",
        (f"- 창: {since.isoformat()} 이상 ~ {until.isoformat()} 미만(턴 시작 시각 기준, 재로드 경계 미적용) · 30일 경계 {cut30.isoformat()} · "
         f"90일 경계 {cut90.isoformat()}"),
        (f"- 창 안 턴 {len(r['turns'])} · Agent · Task 호출 {total} · 세션(창 안 턴이 있는) {r['sessions']} · 읽은 파일 {r['read']} · "
         f"창 밖 파일(수정 시각) {r['out_mtime']} · 건너뛴 파일 {skipped}(까닭: {why})"),
        (f"- 첫 사람 글 앞 호출(시각을 정할 수 없어 표에서 뺌) {r['pre_turn_calls']} · 깨진 줄 {r['files']['bad_lines']} · "
         f"큰 줄(읽지 않음) {r['files']['big_lines']} · 중복 항목 {r['files']['dup_entries']} · 분류 불가 user 항목 {r['files']['unclassified']}"),
        f"- 상태: {status} · 걸린 시간 {elapsed:.1f}초 · main 기록만 읽음(subagent 안에서 부른 호출은 세지 않음)", "",
        "## 1. 종류별 호출 수", "", "| 종류 | 최근 30일 | 최근 90일 | 창 전체 |", "|---|---|---|---|",
    ]
    ordered = sorted(by_type.items(), key=lambda x: (-x[1]["all"], x[0]))
    shown, rest = ordered[:rrm.MAX_ROWS], ordered[rrm.MAX_ROWS:]
    if rest:
        rc, rm = Counter(), Counter()
        for typ, c in rest:
            rc.update(c)
            rm.update(models[typ])
        name = f"그 밖 {len(rest)}종 합계"
        shown.append((name, rc))
        models[name] = rm
    lines += [f"| {typ} | {c['d30']} | {c['d90']} | {c['all']} |" for typ, c in shown]
    lines += ["", f"## 2. 같은 턴에서 함께 불린 종류 쌍 (턴 수, 위에서 {TOP})", "", "| 종류 A | 종류 B | 턴 수 |", "|---|---|---|"]
    lines += [f"| {a} | {b} | {v} |" for (a, b), v in sorted(pairs.items(), key=lambda x: (-x[1], x[0]))[:TOP]]
    lines += ["", f"## 3. 같은 턴에서 바로 이어 불린 순서쌍 (A 다음 B, 위에서 {TOP})", "", "| 앞 | 뒤 | 건수 |", "|---|---|---|"]
    lines += [f"| {a} | {b} | {v} |" for (a, b), v in sorted(seqs.items(), key=lambda x: (-x[1], x[0]))[:TOP]]
    lines += ["", "## 4. 종류별 model 인자", "", "| 종류 | 호출 | model 인자 준 비율 | 값 분포 |", "|---|---|---|---|"]
    for typ, c in shown:
        m = models[typ]
        lines.append(f"| {typ} | {c['all']} | {rrm.ratio(c['all'] - m['(인자 없음)'], c['all'])} | {dist_cell(m)} |")
    lines += ["", "## 5. 턴당 호출 수 분포", "", "| 턴당 호출 | 턴 수 | 비율 |", "|---|---|---|"]
    lines += [f"| {k} | {per_turn[k]} | {rrm.ratio(per_turn[k], len(r['turns']))} |" for k in ("0", "1", "2 ~ 3", "4 이상")]
    lines += ["", "## 6. 세션의 도구 정의 수 (api-request-shape 의 shape.tools 길이, 세션별 최댓값)", ""]
    xs = sorted(r["tool_defs"])
    if xs:
        med, q1, q3 = rrm.quartiles(xs)
        lines += ["| 세션 수 | 최소 | 1사분위 | 중앙값 | 3사분위 | 최대 | 기록 없는 세션 |", "|---|---|---|---|---|---|---|",
                  f"| {len(xs)} | {xs[0]} | {q1} | {med} | {q3} | {xs[-1]} | {r['sessions'] - len(xs)} |"]
    else:
        lines.append("기록에 없음(창 안 턴이 있는 세션에 api-request-shape 항목이 없음)")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    try:
        ap = argparse.ArgumentParser(description="에이전트 호출 집계(읽기 전용)")
        ap.add_argument("--since")
        ap.add_argument("--until")
        ap.add_argument("--home", type=Path, default=rrm.HARNESS)
        a = ap.parse_args(argv)
        # WHY: 시스템 python3 3.10 호환
        until = rrm.parse_ts(a.until) if a.until else datetime.now(timezone.utc).astimezone()   # noqa: UP017
        since = rrm.parse_ts(a.since) if a.since else (until - timedelta(days=90) if until else None)
        if until is None or since is None or not since < until or not a.home.is_dir():
            print("오류: --since · --until 은 시간대가 붙은 ISO 시각이고 since < until, --home 은 있는 폴더여야 합니다", file=sys.stderr)
            return 2
        t0 = time.monotonic()
        r = scan(a.home, since, until, t0 + rrm.TIME_BUDGET_S)
        sys.stdout.write(render(since, until, r, time.monotonic() - t0))
        return 0
    except SystemExit as e:
        return 2 if e.code else 0
    except Exception as e:  # noqa: BLE001
        # NEVER: 예외 글을 내지 않는다(경로 · 본문이 실릴 수 있어 종류 이름만 낸다)
        print(f"오류: 예기치 못한 예외({type(e).__name__})", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
