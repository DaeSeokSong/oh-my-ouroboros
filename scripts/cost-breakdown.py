"""
cost-breakdown.py — Claude Code 트랜스크립트에서 모델별·에이전트별 토큰/비용 분해.

/cost 스킬의 엔진. 파싱은 read-only. --snapshot/--reset만 detail ledger 파일을 쓴다.
detail ledger: ~/.cache/claude-cost/detail/<session>.json

요금표: ~/.claude/config/model-pricing.json (공식 https://platform.claude.com/docs/ko/about-claude/pricing).

사용:
  python3 scripts/cost-breakdown.py            # 현재(CLAUDE_CODE_SESSION_ID) 세션
  python3 scripts/cost-breakdown.py --all      # 이 서버 전체 세션 합산(+프로젝트별)
  python3 scripts/cost-breakdown.py --session <id> | --json
  python3 scripts/cost-breakdown.py --snapshot # 훅 전용: stdin(hook JSON) 세션 detail 누적
  python3 scripts/cost-breakdown.py --reset [--yes]  # 누적 ledger(coralline+detail) 삭제
REF: knowledge/harness/code-history/scripts__cost-breakdown.py.md
"""
import argparse
import collections
import glob
import json
import os
import sys

JSON_SCHEMA_VERSION = 3
FAST_ELIGIBLE = {"claude-opus-5-5", "claude-opus-4-8", "claude-opus-4-7"}
HOME = os.path.expanduser("~")
PROJ_GLOB = os.path.join(HOME, ".claude", "projects", "*", "*.jsonl")
PRICING_PATH = os.path.join(HOME, ".claude", "config", "model-pricing.json")
CACHE = os.environ.get("XDG_CACHE_HOME", os.path.join(HOME, ".cache"))
LEDGER_DIR = os.path.join(CACHE, "coralline", "cost-ledger")
DETAIL_DIR = os.path.join(CACHE, "claude-cost", "detail")
UNKNOWN_MODEL = "(unknown-model)"

def load_pricing():
    with open(PRICING_PATH) as f:
        p = json.load(f)
    return p["models"], p.get("_fallback", {"input":5,"output":25,"cache_write_5m":6.25,"cache_write_1h":10,"cache_read":0.5})

def zero():
    return {"input":0,"output":0,"cw5":0,"cw1h":0,"cr":0}

def add_usage(acc, u):
    if not isinstance(u, dict):
        return
    acc["input"]  += u.get("input_tokens", 0) or 0
    acc["output"] += u.get("output_tokens", 0) or 0
    acc["cr"]     += u.get("cache_read_input_tokens", 0) or 0
    cc = u.get("cache_creation")
    if isinstance(cc, dict) and ("ephemeral_5m_input_tokens" in cc or "ephemeral_1h_input_tokens" in cc):
        acc["cw5"]  += cc.get("ephemeral_5m_input_tokens", 0) or 0
        acc["cw1h"] += cc.get("ephemeral_1h_input_tokens", 0) or 0
    else:
        acc["cw5"] += u.get("cache_creation_input_tokens", 0) or 0

def has_usage(u):
    if not isinstance(u, dict):
        return False
    return any((u.get(k) or 0) for k in
               ("input_tokens","output_tokens","cache_read_input_tokens","cache_creation_input_tokens")) \
           or isinstance(u.get("cache_creation"), dict)

def usage_total(u):
    if not isinstance(u, dict):
        return 0
    t = ((u.get("input_tokens", 0) or 0) + (u.get("output_tokens", 0) or 0)
       + (u.get("cache_read_input_tokens", 0) or 0))
    cc = u.get("cache_creation")
    if isinstance(cc, dict) and ("ephemeral_5m_input_tokens" in cc or "ephemeral_1h_input_tokens" in cc):
        t += (cc.get("ephemeral_5m_input_tokens", 0) or 0) + (cc.get("ephemeral_1h_input_tokens", 0) or 0)
    else:
        t += (u.get("cache_creation_input_tokens", 0) or 0)
    return t

def cost_of(acc, r):
    return (acc["input"]*r["input"] + acc["output"]*r["output"] + acc["cw5"]*r["cache_write_5m"]
          + acc["cw1h"]*r["cache_write_1h"] + acc["cr"]*r["cache_read"]) / 1_000_000.0

def total_tokens(acc):
    return acc["input"] + acc["output"] + acc["cw5"] + acc["cw1h"] + acc["cr"]

def sid_of(f):
    b = os.path.basename(f)
    return b.removesuffix(".jsonl")

def parse(files):
    msgs = {}; tasks = {}; noid_main = []; noid_task = []
    session_ids = set(); dup_msg = 0; dup_task = 0
    for f in files:
        proj = os.path.basename(os.path.dirname(f)); fsid = sid_of(f)
        try:
            fh = open(f)  # noqa: SIM115
        except OSError:
            continue
        for line in fh:
            try:
                o = json.loads(line)
            except Exception:  # noqa: BLE001, S112
                continue
            sid = o.get("sessionId") or o.get("session_id") or fsid
            session_ids.add(sid)
            if o.get("type") == "assistant":
                m = o.get("message", {})
                if isinstance(m, dict):
                    u = m.get("usage")
                    if has_usage(u):
                        model = m.get("model") or UNKNOWN_MODEL
                        if isinstance(u, dict) and u.get("speed") == "fast" and model in FAST_ELIGIBLE:
                            model = model + " (fast)"
                        if model != "<synthetic>":
                            mid = o.get("messageId") or m.get("id")
                            rec = {"model": model, "usage": u, "proj": proj}
                            if mid is None:
                                noid_main.append(rec)
                            elif mid in msgs:
                                dup_msg += 1
                                if usage_total(u) > usage_total(msgs[mid]["usage"]):
                                    msgs[mid] = rec
                            else:
                                msgs[mid] = rec
            tur = o.get("toolUseResult")
            if isinstance(tur, dict) and "agentType" in tur and isinstance(tur.get("usage"), dict):
                at = tur.get("agentType", "?"); rm = tur.get("resolvedModel") or UNKNOWN_MODEL
                u = tur["usage"]; rec = {"at": at, "rm": rm, "usage": u, "proj": proj}
                tid = tur.get("agentId") or o.get("toolUseID") or o.get("sourceToolUseID")
                if tid is None:
                    noid_task.append(rec)
                elif tid in tasks:
                    dup_task += 1
                    if usage_total(u) > usage_total(tasks[tid]["usage"]):
                        tasks[tid] = rec
                else:
                    tasks[tid] = rec
    return msgs, tasks, noid_main, noid_task, session_ids, {"dup_msg": dup_msg, "dup_task": dup_task}

def aggregate(msgs, tasks, noid_main, noid_task):
    model_main = collections.defaultdict(zero)
    model_agent = collections.defaultdict(lambda: collections.defaultdict(zero))
    external = collections.defaultdict(zero)
    proj_tokens = collections.defaultdict(zero)
    for rec in list(msgs.values()) + noid_main:
        add_usage(model_main[rec["model"]], rec["usage"]); add_usage(proj_tokens[rec["proj"]], rec["usage"])
    for rec in list(tasks.values()) + noid_task:
        if isinstance(rec["at"], str) and rec["at"].startswith("codex"):
            add_usage(external[rec["at"]], rec["usage"])
        else:
            add_usage(model_agent[rec["rm"]][rec["at"]], rec["usage"]); add_usage(proj_tokens[rec["proj"]], rec["usage"])
    return model_main, model_agent, external, proj_tokens

def coralline_session_total(session_ids):
    if not os.path.isdir(LEDGER_DIR):
        return None
    tot = 0.0; found = False
    for sid in session_ids:
        p = os.path.join(LEDGER_DIR, sid)
        if os.path.isfile(p):
            try:
                with open(p) as fh:
                    tot += float(fh.read().strip().split()[0]); found = True
            except Exception:  # noqa: BLE001, S110
                pass
    return tot if found else None

def coralline_grand_total():
    if not os.path.isdir(LEDGER_DIR):
        return None
    tot = 0.0; found = False
    for name in os.listdir(LEDGER_DIR):
        p = os.path.join(LEDGER_DIR, name)
        if os.path.isfile(p):
            try:
                with open(p) as fh:
                    tot += float(fh.read().strip().split()[0]); found = True
            except Exception:  # noqa: BLE001, S110
                pass
    return tot if found else None

def ledger_path(session_id):
    return os.path.join(DETAIL_DIR, session_id + ".json")

def load_ledger(session_id):
    fresh = {"session_id": session_id, "msgs": {}, "tasks": {}}
    p = ledger_path(session_id)
    try:
        with open(p) as f:
            d = json.load(f)
    except FileNotFoundError:
        return fresh
    except Exception:  # noqa: BLE001
        d = None
    if not isinstance(d, dict):
        fresh["_corrupt"] = True
        return fresh
    if not isinstance(d.get("msgs"), dict): d["msgs"] = {}
    if not isinstance(d.get("tasks"), dict): d["tasks"] = {}
    return d

def ledger_records(session_ids):
    msgs = {}; tasks = {}
    for sid in session_ids:
        d = load_ledger(sid)
        merge_maxusage(msgs, d["msgs"]); merge_maxusage(tasks, d["tasks"])
    return msgs, tasks

def merge_maxusage(base, add):
    for k, rec in add.items():
        if k not in base or usage_total(rec["usage"]) > usage_total(base[k]["usage"]):
            base[k] = rec

def bar(frac, width=10):
    filled = max(0, min(width, round(frac * width)))
    return "█" * filled + "░" * (width - filled)

def _dwidth(s):
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in str(s))

def pad(s, w):
    s = str(s)
    return s + " " * max(0, w - _dwidth(s))

def short(model):
    return str(model).replace("claude-", "").replace("-20251001", "")

def fmt_tok(n):
    if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
    if n >= 1_000:     return f"{n/1_000:.0f}K"
    return str(n)

def build_rows(model_main, model_agent, models, fallback):
    all_models = set(model_main) | set(model_agent)
    fb = set(); rows = []; grand = 0.0
    for model in all_models:
        r = models.get(model)
        if r is None:
            r = fallback; fb.add(model)
        main_acc = model_main.get(model, zero()); main_cost = cost_of(main_acc, r)
        agents = [(at, acc, cost_of(acc, r)) for at, acc in model_agent.get(model, {}).items()]
        mc = main_cost + sum(c for _, _, c in agents)
        grand += mc
        rows.append((model, mc, main_acc, main_cost, agents))
    rows.sort(key=lambda x: (-x[1], short(x[0])))
    return rows, grand, fb

def render(args, note):
    models, fallback = load_pricing()
    files = pick_scope_files(args)
    live_msgs, live_tasks, noid_main, noid_task, live_sessions, stats = parse(files)
    session_ids = set(live_sessions)
    if args.session:
        session_ids.add(args.session)
    used_ledger = any(os.path.isfile(ledger_path(s)) for s in session_ids)
    led_msgs, led_tasks = ledger_records(session_ids)
    merge_maxusage(led_msgs, live_msgs); merge_maxusage(led_tasks, live_tasks)
    model_main, model_agent, external, proj_tokens = aggregate(led_msgs, led_tasks, noid_main, noid_task)
    rows, computed, fb = build_rows(model_main, model_agent, models, fallback)
    authoritative = coralline_grand_total() if args.all else coralline_session_total(session_ids)
    unverified = [{"model": row[0], "key": k} for row in rows
                  for k in sorted(k for k in models.get(row[0], {}) if k.startswith("_unverified"))]

    if args.json:
        out = {"schema_version": JSON_SCHEMA_VERSION, "scope": "all" if args.all else "session",
               "authoritative_total_usd": round(authoritative, 4) if authoritative is not None else None,
               "computed_breakdown_usd": round(computed, 4),
               "coverage_pct": round(100*computed/authoritative, 1) if authoritative else None,
               "fallback_priced_models": sorted(fb), "unverified": unverified,
               "dedup_removed": {"assistant": stats["dup_msg"], "task": stats["dup_task"]},
               "ledger_detail_used": used_ledger, "models": [], "external": []}
        for model, mc, macc, mcost, agents in rows:
            out["models"].append({"model": model, "cost_usd": round(mc, 4),
                "pct": round(100*mc/computed, 2) if computed else 0, "exact_rate": model not in fb,
                "main": {"cost_usd": round(mcost, 4), "tokens": total_tokens(macc)},
                "agents": [{"agent": at, "cost_usd": round(c, 4),
                            "pct_of_model": round(100*c/mc, 2) if mc else 0, "tokens": total_tokens(acc)}
                           for at, acc, c in sorted(agents, key=lambda x: (-x[2], x[0]))]})
        for at, acc in sorted(external.items()):
            out["external"].append({"agent": at, "tokens": total_tokens(acc), "usd": None})
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    scope = "이 서버 전체 세션 합산" if args.all else "현재 세션"
    print(f"\n💰 모델·에이전트별 비용 분해 — {scope}")
    print(f"   (트랜스크립트 {len(files)}개 / 세션 {len(session_ids)}개 / 요금표 {load_meta()})")
    if note: print(f"   ⚠️ {note}")
    if used_ledger: print("   (detail ledger 병합 — compaction 이전 detail 포함)")
    if stats["dup_msg"] or stats["dup_task"]:
        print(f"   (중복 제거: assistant {stats['dup_msg']} · task {stats['dup_task']})")
    print()
    for model, mc, macc, mcost, agents in rows:
        frac = mc / computed if computed else 0
        flag = "⚠️ " if model in fb else ""
        if not agents:
            inline = "├ (메인 세션) 100%" if mcost > 0 else ""
        else:
            parts = []
            if mcost > 0:
                parts.append(f"메인 {100*mcost/mc:.0f}%")
            ag = sorted(agents, key=lambda x: -x[2])
            parts += [f"{at} ${c:.2f}" for at, acc, c in ag[:6]]
            if len(ag) > 6:
                parts.append(f"+{len(ag)-6} more")
            inline = "├ " + " ├ ".join(parts)
        print(f"  {pad(short(model), 10)} {bar(frac, 10)} ${mc:>8.2f}  {100*frac:>4.1f}%  {flag}{inline}")
    ext = ""
    if external:
        ext = "   ⚙️ 외부 " + ", ".join(f"{k}({fmt_tok(total_tokens(v))} tok)" for k, v in sorted(external.items())) + " (OpenAI 별도)"
    print(f"  합계 ${computed:.2f}{ext}")
    if fb:
        print(f"  ⚠️  요금표 미등재(fallback): {', '.join(sorted(short(m) for m in fb))}")
    for u in unverified:
        print(f"  ⚠️  {short(u['model'])}: {u['key']} 미확인")
    if args.all and proj_tokens:
        print("\n  📁 프로젝트별 (원시 토큰 합, ledger+라이브):")
        for proj, acc in sorted(proj_tokens.items(), key=lambda kv: -total_tokens(kv[1]))[:12]:
            print(f"     {fmt_tok(total_tokens(acc)):>7} tok  {proj}")
    print()
    if authoritative is not None:
        cov = 100*computed/authoritative if authoritative else 0
        if args.all:
            print(f"  ✅ statusline 표시값 = 전 세션 누적(coralline total_cost_usd): ${authoritative:.2f}")
        else:
            print(f"  ✅ 이 세션 total_cost_usd(coralline): ${authoritative:.2f}"
                  f"  (statusline은 전 세션 합을 표시 — 전체는 /cost all)")
        if cov <= 105:
            print(f"     토큰 기반 분해 합계 ${computed:.2f} = coverage {cov:.0f}%"
                  f"{'  — detail ledger로 보존됨' if used_ledger else '  (미귀속=compaction 이전 등)'}")
        else:
            # NEVER: 불일치 원인을 단정해 표기하지 않는다(원인 후보만 보인다).
            print(f"     토큰 기반 분해 합계 ${computed:.2f} (총액과 {cov-100:.0f}%p 불일치).")
            cause = "coralline가 아직 ledger화하지 않은 과거 세션 포함(유력)" if args.all else \
                    "중복·요금drift·race 등 재조정 필요"
            print(f"     원인 후보: {cause}. statusline 값은 렌더된 세션만 누적.")
    else:
        print(f"  ℹ️  coralline ledger 없음 — 토큰 기반 추정 ${computed:.2f}만 표시(총액 앵커 불가)")
    print("  ℹ️  $는 API 정가 환산(구독 실지불·할인 미반영). cache write 5m/1h 분리 있으면 각 요율.")
    print()

def load_meta():
    try:
        return f"{json.load(open(PRICING_PATH)).get('_verified','?')} 기준"
    except Exception:  # noqa: BLE001
        return "?"

def read_hook_stdin():
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception:  # noqa: BLE001
        return {}

def find_transcript(session_id, transcript_path):
    if transcript_path and os.path.isfile(transcript_path):
        return transcript_path
    if session_id:
        for f in glob.glob(PROJ_GLOB):
            if sid_of(f) == session_id:
                return f
    return None

def snapshot_mode():
    h = read_hook_stdin()
    session_id = h.get("session_id") or h.get("sessionId")
    tfile = find_transcript(session_id, h.get("transcript_path") or h.get("transcriptPath"))
    if not session_id or not tfile:
        return
    d = load_ledger(session_id)
    if d.pop("_corrupt", False):
        # NEVER: 손상 파일을 조용히 덮어쓰지 않는다(.corrupt 로 보존 후 새로 시작).
        try:
            os.replace(ledger_path(session_id), ledger_path(session_id) + ".corrupt")
            sys.stderr.write(f"[cost-snapshot] {session_id[:8]} 손상 ledger → .corrupt 보존, 새로 시작\n")
        except Exception:  # noqa: BLE001, S110
            pass
    msgs, tasks, _, _, _, _ = parse([tfile])
    new_m = 0; new_t = 0
    for mid, rec in msgs.items():
        cur = d["msgs"].get(mid)
        if cur is None or usage_total(rec["usage"]) > usage_total(cur["usage"]):
            d["msgs"][mid] = rec; new_m += 1
    for tid, rec in tasks.items():
        cur = d["tasks"].get(tid)
        if cur is None or usage_total(rec["usage"]) > usage_total(cur["usage"]):
            d["tasks"][tid] = rec; new_t += 1
    d["session_id"] = session_id
    os.makedirs(DETAIL_DIR, exist_ok=True)
    tmp = ledger_path(session_id) + f".tmp.{os.getpid()}"   # NEVER: 고정 이름 .tmp 를 쓰지 않는다(동시 스냅샷이 충돌한다)
    with open(tmp, "w") as f:
        json.dump(d, f, ensure_ascii=False); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, ledger_path(session_id))
    sys.stderr.write(f"[cost-snapshot] {session_id[:8]} +{new_m}msg +{new_t}task\n")

def reset_mode(assume_yes):
    import shutil
    targets = [LEDGER_DIR, DETAIL_DIR]
    if not assume_yes:
        print("아래 누적 cost ledger를 삭제합니다(과거 세션 집계 제거):")
        for t in targets: print(f"  - {t}")
        print("확인하려면 --yes 와 함께 다시 실행.")
        print("⚠️ 완전한 '0'은 아님: HUD가 매 렌더마다 현 활성 세션의 total_cost_usd(Claude Code")
        print("   소유·누적)를 다시 ledger화하므로, 리셋 후에도 statusline은 현 세션 값부터 재누적됨.")
        print("   가장 깨끗한 초기화: /clear로 새 세션을 시작한 '직후' /cost-reset 실행")
        print("   (그 시점 새 세션 비용이 최소라 남는 값도 최소).")
        return
    for t in targets:
        try:
            shutil.rmtree(t); print(f"삭제됨: {t}")
        except FileNotFoundError:
            print(f"없음(무시): {t}")
    print("✅ 과거 세션 누적 제거. 현 세션 값은 HUD가 계속 누적(완전 0 아님 — /clear 새 세션 직후 리셋이 가장 깨끗).")

def pick_scope_files(args):
    files = sorted(glob.glob(PROJ_GLOB))
    if args.all:
        return files
    explicit = bool(args.session)
    sid = args.session or os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if sid:
        m = [f for f in files if sid_of(f) == sid]
        if m:
            return m
        if explicit:
            print(f"세션 '{sid}' 트랜스크립트를 찾을 수 없습니다.", file=sys.stderr); sys.exit(2)
    return [max(files, key=os.path.getmtime)] if files else []

def main():
    ap = argparse.ArgumentParser(description="Claude Code 모델·에이전트별 비용 분해")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--session")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--snapshot", action="store_true", help="훅 전용: stdin 세션 detail 누적")
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()
    if args.snapshot:
        snapshot_mode(); return
    if args.reset:
        reset_mode(args.yes); return
    note = None
    if not args.all and not (args.session or os.environ.get("CLAUDE_CODE_SESSION_ID")):
        note = "세션 id 미상 — 최근 수정 파일 기준(부정확 가능)"
    render(args, note)

if __name__ == "__main__":
    main()
