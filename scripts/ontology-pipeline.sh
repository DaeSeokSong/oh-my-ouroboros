#!/usr/bin/env bash
# ontology-pipeline.sh — 하네스 온톨로지(graphify-out) 갱신 파이프라인 (bash 단계)
#
# 실행 모델 (2026-07-09 사용자 승인 — decisions.md):
#   이 스크립트는 systemd user timer(claude-ontology-refresh.timer)가 ontology-refresh.sh를
#   통해 **직접 실행**한다 — restore-bg-sessions.sh와 동일한 실행 모델(사용자 자신의 systemd
#   권한). Claude의 Bash 도구를 경유하지 않으므로 Claude Code 훅 체계와 접점이 없다.
#   Claude는 시맨틱 추출 단계에서만 헤드리스 세션으로 참여한다 (ontology-refresh.sh 참조).
#
# 범위 제한: CLAUDE_DIR 하드코딩, graphify-out/ 밖 쓰기 없음(로그 제외).
#   git push는 이 스크립트 어디에도 없다 — 하네스 표준 정책(push는 항상 사용자 직접).
#   커밋은 graphify-out/ 경로만 add — 다른 미커밋 변경을 절대 쓸어담지 않는다.
#
# 서브커맨드:
#   detect    git pull --ff-only → 파일 탐지 → AST 추출 → 시맨틱 캐시 확인.
#             산출: .graphify_detect.json / .graphify_ast.json / .graphify_uncached.txt
#             (uncached 목록이 비어있지 않으면 헤드리스 Claude가 청크 추출을 수행해야 함)
#   finalize  청크+캐시 병합 → 그래프 빌드/클러스터 → 라벨(기존 재사용+신규 휴리스틱) →
#             건강 진단 → obsidian/html export → manifest/cost → cleanup → graphify-out/만 커밋.
#
# 종료 코드: 0=완료  1=오류(pull 실패·빈 그래프·shrink-guard 등)  2=detect 스킵(미push 백로그 — 오류 아님)  3=사용법 오류
# (2=스킵을 0과 분리한 이유: 스킵인데 0을 주면 호출자(refresh.sh)가 finalize로 진행해
#  .graphify_detect.json 부재 크래시 + 매 주기 헛 실패 알림 — 2026-07-10 qa 정독 P0)

set -uo pipefail

CLAUDE_DIR="$HOME/.claude"
LOG="$CLAUDE_DIR/ontology-refresh.log"
ACTION="${1:-}"

# systemd 경유(ontology-refresh.service, StandardOutput=append:LOG) 시 stdout이 같은 LOG에 다시
# 붙어 tee는 이중 기록이 된다(2026-07-13 실측) — systemd가 주입하는 INVOCATION_ID로 분기.
tee_log() { if [ -n "${INVOCATION_ID:-}" ]; then cat; else tee -a "$LOG"; fi; }
log() { echo "[$(date -Iseconds)] [pipeline] $*" | tee_log; }

cd "$CLAUDE_DIR" || { echo "cd 실패: $CLAUDE_DIR" >&2; exit 1; }

resolve_python() {
    if [ -f graphify-out/.graphify_python ] && "$(cat graphify-out/.graphify_python)" -c "import graphify" 2>/dev/null; then
        cat graphify-out/.graphify_python
        return 0
    fi
    local bin shebang
    bin=$(command -v graphify 2>/dev/null) || return 1
    shebang=$(head -1 "$bin" | tr -d '#!')
    case "$shebang" in
        *[!a-zA-Z0-9/_.@-]*) return 1 ;;
    esac
    "$shebang" -c "import graphify" 2>/dev/null || return 1
    mkdir -p graphify-out
    printf '%s' "$shebang" > graphify-out/.graphify_python
    pwd > graphify-out/.graphify_root
    echo "$shebang"
}

case "$ACTION" in
  detect)
    log "detect 시작"

    # pull은 best-effort (2026-07-10 단일 빌더 재설계 — 사용자 결정): 타이머는 1서버에만 있고
    # push·pull은 전량 사용자 몫이므로, 무인 인증(서버별 SSH 키 등록)을 요구하지 않는다.
    # pull 실패(인증·네트워크)는 오류가 아니라 "로컬 상태로 빌드" — 단일 빌더라 발산 없음(선형 이력).
    # 타서버발 변경은 사용자가 이 서버에서 pull한 뒤 다음 주기에 자연 반영된다.
    if GIT_TERMINAL_PROMPT=0 git pull --ff-only >> "$LOG" 2>&1; then
        log "git pull 성공 — 원격 최신 상태에서 빌드"
    else
        log "git pull 불가(인증/네트워크/충돌) — 로컬 상태로 진행 (단일 빌더 전제, §7.1)"
    fi

    # 멀티서버 가드 2 (§7.1 미push 가드): 이 서버의 이전 온톨로지 커밋이 아직 push 안 됐으면
    # 새 빌드를 쌓지 않는다 — 다른 서버가 그 사이 빌드하면 발산하므로, push가 전파의 전제.
    # (전 서버 타이머 운용의 안전핀 — 2026-07-09 전 서버 갱신 허용 결정과 한 쌍)
    if git rev-parse --abbrev-ref '@{upstream}' >/dev/null 2>&1; then
        UNPUSHED=$(git rev-list '@{upstream}'..HEAD -- graphify-out/ 2>/dev/null | head -1)
        if [ -n "$UNPUSHED" ]; then
            # push 권장 전달은 세션 시작 usage-check(ONTOLOGY_PUSH)가 담당 — ntfy 미사용 (사용자 결정)
            log "미push 온톨로지 커밋 존재 — 발산 방지 skip (git push 후 다음 주기에 재개)"
            exit 2
        fi
    fi

    PY=$(resolve_python) || { log "graphify 인터프리터 확인 실패 (미설치?)"; exit 1; }
    mkdir -p graphify-out

    "$PY" - <<'PYEOF' 2>&1 | tee_log
import json, os
from graphify.detect import detect
from pathlib import Path
root = Path(os.environ["HOME"]) / ".claude"
result = detect(root)
(root / "graphify-out/.graphify_detect.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
print(f"Corpus: {result.get('total_files',0)} files, {result.get('total_words',0)} words")
PYEOF
    [[ ${PIPESTATUS[0]} -eq 0 ]] || { log "detect(Corpus) Python 실패 — 중단"; exit 1; }   # set -e 부재 보완 (2026-07-17 Codex): tee_log가 실패 RC 가림

    "$PY" - <<'PYEOF' 2>&1 | tee_log
import json, os
from graphify.extract import collect_files, extract
from pathlib import Path
root = Path(os.environ["HOME"]) / ".claude"
out = root / "graphify-out"
detect = json.loads((out / ".graphify_detect.json").read_text(encoding="utf-8"))
code_files = []
for f in detect.get("files", {}).get("code", []):
    p = Path(f)
    code_files.extend(collect_files(p) if p.is_dir() else [p])
if code_files:
    result = extract(code_files, cache_root=root)
    (out / ".graphify_ast.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    print(f"AST: {len(result['nodes'])} nodes, {len(result['edges'])} edges")
else:
    (out / ".graphify_ast.json").write_text(json.dumps({"nodes": [], "edges": [], "input_tokens": 0, "output_tokens": 0}, ensure_ascii=False), encoding="utf-8")
    print("AST: no code files")
PYEOF
    [[ ${PIPESTATUS[0]} -eq 0 ]] || { log "AST 추출 Python 실패 — 중단"; exit 1; }

    "$PY" - <<'PYEOF' 2>&1 | tee_log
import json, os
from graphify.cache import check_semantic_cache
from pathlib import Path
root = Path(os.environ["HOME"]) / ".claude"
out = root / "graphify-out"
detect = json.loads((out / ".graphify_detect.json").read_text(encoding="utf-8"))
all_files = [f for cat in ("document", "paper", "image") for f in detect["files"].get(cat, [])]
cached_nodes, cached_edges, cached_hyperedges, uncached = check_semantic_cache(all_files, root=str(root))
if cached_nodes or cached_edges or cached_hyperedges:
    (out / ".graphify_cached.json").write_text(json.dumps({"nodes": cached_nodes, "edges": cached_edges, "hyperedges": cached_hyperedges}, ensure_ascii=False), encoding="utf-8")
else:
    (out / ".graphify_cached.json").unlink(missing_ok=True)
(out / ".graphify_uncached.txt").write_text("\n".join(uncached), encoding="utf-8")
print(f"Semantic: {len(all_files)-len(uncached)} cached, {len(uncached)} need extraction")
PYEOF
    [[ ${PIPESTATUS[0]} -eq 0 ]] || { log "semantic detect Python 실패 — 중단"; exit 1; }

    N=$(grep -c . graphify-out/.graphify_uncached.txt 2>/dev/null || echo 0)
    log "detect 완료 — 시맨틱 추출 필요 ${N}개"
    ;;

  finalize)
    log "finalize 시작"
    PY=$(resolve_python) || { log "graphify 인터프리터 확인 실패"; exit 1; }

    "$PY" - <<'PYEOF' 2>&1 | tee_log
import json, glob, os
from pathlib import Path
root = Path(os.environ["HOME"]) / ".claude"
out = root / "graphify-out"
chunks = sorted(glob.glob(str(out / ".graphify_chunk_*.json")))
all_nodes, all_edges, all_hyper = [], [], []
for c in chunks:
    d = json.loads(Path(c).read_text(encoding="utf-8"))
    all_nodes += d.get("nodes", [])
    all_edges += d.get("edges", [])
    all_hyper += d.get("hyperedges", [])
(out / ".graphify_semantic_new.json").write_text(json.dumps({"nodes": all_nodes, "edges": all_edges, "hyperedges": all_hyper, "input_tokens": 0, "output_tokens": 0}, ensure_ascii=False), encoding="utf-8")
print(f"{len(chunks)} chunk(s): {len(all_nodes)} new nodes")
PYEOF
    [[ ${PIPESTATUS[0]} -eq 0 ]] || { log "청크 병합 Python 실패 — 중단"; exit 1; }

    "$PY" - <<'PYEOF' >> "$LOG" 2>&1 || log "semantic cache 저장 실패 — 비차단(다음 run 재추출, 무결성 무관)"
import json, os
from graphify.cache import save_semantic_cache
from pathlib import Path
root = Path(os.environ["HOME"]) / ".claude"
out = root / "graphify-out"
p = out / ".graphify_semantic_new.json"
new = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"nodes": [], "edges": [], "hyperedges": []}
save_semantic_cache(new.get("nodes", []), new.get("edges", []), new.get("hyperedges", []), root=str(root))
PYEOF

    "$PY" - <<'PYEOF' 2>&1 | tee_log
import json, os
from pathlib import Path
root = Path(os.environ["HOME"]) / ".claude"
out = root / "graphify-out"
def load(name, default):
    p = out / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default
cached = load(".graphify_cached.json", {"nodes": [], "edges": [], "hyperedges": []})
new = load(".graphify_semantic_new.json", {"nodes": [], "edges": [], "hyperedges": []})
ast = load(".graphify_ast.json", {"nodes": [], "edges": []})

sem_nodes = cached["nodes"] + new.get("nodes", [])
seen, sem_dedup = set(), []
for n in sem_nodes:
    if n["id"] not in seen:
        seen.add(n["id"]); sem_dedup.append(n)

merged_nodes = list(ast["nodes"])
seen_all = {n["id"] for n in ast["nodes"]}
for n in sem_dedup:
    if n["id"] not in seen_all:
        merged_nodes.append(n); seen_all.add(n["id"])
merged = {
    "nodes": merged_nodes,
    "edges": ast["edges"] + cached["edges"] + new.get("edges", []),
    "hyperedges": cached.get("hyperedges", []) + new.get("hyperedges", []),
    "input_tokens": 0, "output_tokens": 0,
}
(out / ".graphify_extract.json").write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")
print(f"Merged: {len(merged_nodes)} nodes, {len(merged['edges'])} edges")
PYEOF
    [[ ${PIPESTATUS[0]} -eq 0 ]] || { log "extract 병합(.graphify_extract.json) Python 실패 — 중단"; exit 1; }

    if ! "$PY" - <<'PYEOF' 2>&1 | tee_log
import json, os
from pathlib import Path
from graphify.build import build_from_json
from graphify.cluster import cluster, score_all
from graphify.analyze import god_nodes, surprising_connections, suggest_questions
from graphify.report import generate
from graphify.export import to_json

root = Path(os.environ["HOME"]) / ".claude"
out = root / "graphify-out"
extraction = json.loads((out / ".graphify_extract.json").read_text(encoding="utf-8"))
detection = json.loads((out / ".graphify_detect.json").read_text(encoding="utf-8"))

G = build_from_json(extraction, root=str(root), directed=False)
if G.number_of_nodes() == 0:
    print("ERROR: empty graph"); raise SystemExit(1)
communities = cluster(G)
cohesion = score_all(G, communities)

# 라벨: 기존 재사용 + 신규 커뮤니티는 최고 연결도 노드 기반 휴리스틱.
# 무인 실행이라 사람 curation 없음 — 정밀 라벨은 harness-audit Step 6.5 대화형 실행으로.
prev = {}
lp = out / ".graphify_labels.json"
if lp.exists():
    prev = {int(k): v for k, v in json.loads(lp.read_text(encoding="utf-8")).items()}
id2label = {n["id"]: n.get("label", n["id"]) for n in extraction["nodes"]}
labels, new_ct = {}, 0
for cid, members in communities.items():
    if cid in prev:
        labels[cid] = prev[cid]
    else:
        new_ct += 1
        deg = sorted(members, key=lambda nid: G.degree(nid), reverse=True)
        top = id2label.get(deg[0], deg[0]) if deg else f"Community {cid}"
        labels[cid] = f"{top[:40]} 외 {len(members)-1}" if len(members) > 1 else top[:40]

tokens = {"input": 0, "output": 0}
gods = god_nodes(G)
surprises = surprising_connections(G, communities)
questions = suggest_questions(G, communities, labels)

if not to_json(G, communities, str(out / "graph.json")):
    # shrink-guard 거부 → 정당성 자동 검증 후 제한적 force (2026-07-15 실측 판단근거:
    # 파일 이동/삭제가 만드는 동명 dedup 순감소는 정당하지만, 가드 기준선(기존 graph.json)이
    # 자연히 낮아지지 않아 매일 재발화 → 무인 갱신 영구 정지. 무검증 force는 금지(#479 취지) —
    # 아래 2조건을 통과한 경우에만 force. 실측 사례: knowledge/ 폴더 전환(827edb1)이 -20 유발.
    #   ① 커버리지 보존: 기존 그래프 소스 중 새 그래프에서 빠진 파일이 전부 디스크에서도
    #      사라졌을 것 (이동/삭제만 허용 — 추출 누락이면 파일이 남아 있으므로 여기서 걸림)
    #   ② 축소율 ≤ 10%: 대량 축소는 여전히 수동 개입 (harness-audit Step 6.5 대화형 검증)
    existing = json.loads((out / "graph.json").read_text(encoding="utf-8"))
    _rootp = str(root) + "/"
    old_srcs = {(n.get("source_file") or "").replace(_rootp, "")
                for n in existing.get("nodes", []) if n.get("source_file")}
    new_srcs = {(d.get("source_file") or "").replace(_rootp, "")
                for _, d in G.nodes(data=True) if d.get("source_file")}
    lost_on_disk = sorted(m for m in old_srcs - new_srcs if (root / m).exists())
    old_n, new_n = len(existing.get("nodes", [])), G.number_of_nodes()
    shrink_pct = (old_n - new_n) / max(old_n, 1) * 100
    if not lost_on_disk and shrink_pct <= 10:
        print(f"shrink-guard 자동 검증 통과: {old_n}→{new_n} ({shrink_pct:.1f}%), "
              f"소실 소스 전부 이동/삭제 파일 → force 기록")
        if not to_json(G, communities, str(out / "graph.json"), force=True):
            print("ERROR: force 기록 실패"); raise SystemExit(1)
    else:
        reason = (f"디스크에 존재하는 파일 {len(lost_on_disk)}건 커버리지 소실(추출 누락 의심): "
                  f"{lost_on_disk[:5]}" if lost_on_disk
                  else f"축소율 {shrink_pct:.1f}% > 10%")
        print(f"ERROR: shrink-guard refused write (#479) — 자동 검증 실패({reason}). "
              f"수동 검증 후 재빌드 필요 (code-graph.md §7 알려진 한계)"); raise SystemExit(1)

report = generate(G, communities, cohesion, labels, gods, surprises, detection, tokens, str(root), suggested_questions=questions)
(out / "GRAPH_REPORT.md").write_text(report, encoding="utf-8")
lp.write_text(json.dumps({str(k): v for k, v in labels.items()}, ensure_ascii=False), encoding="utf-8")
print(f"Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges, {len(communities)} communities ({new_ct} heuristic-labeled)")
PYEOF
    then
        log "그래프 빌드 실패 — 중단"
        exit 1
    fi

    # export 실패는 즉시 중단 (2026-07-15 GPT P1-3: 종전 RC 미검사 — 부분 산출물 위에
    # stale manifest 기준 삭제가 진행될 수 있었음)
    if ! graphify export obsidian >> "$LOG" 2>&1; then
        log "obsidian export 실패 — 중단 (fail-closed)"
        exit 1
    fi
    graphify export html >> "$LOG" 2>&1 || log "html export 실패 (비차단 — 부가 산출물)"

    # orphan 자동 정리 (2026-07-15 신설 → 07-15 GPT P1-2/P1-3 재설계): exporter는 upsert
    # 방식이라 삭제 노드의 노트가 잔존 누적됨 (실측 460건, 대소문자 충돌 23쌍 전부 orphan發).
    # 안전 게이트 3종 (판단 근거 이식):
    #   ① fail-closed — manifest 부재/파손/빈 목록·정리 오류는 exit 1 (종전 skip은 fail-open)
    #   ② canvas 보호 — graph.canvas가 참조하는 노트는 manifest에 없어도 절대 삭제 안 함
    #      (실측: exporter가 live 노드 2개를 manifest에서 누락 → 정리가 live 노트 삭제.
    #       불일치는 WARN으로 진단만 — exit 1로 만들면 exporter 버그가 고쳐질 때까지
    #       무인 갱신이 매일 정지하는 shrink-guard 동종 병리가 되므로 보호+경고 선택)
    #   ③ shrink 게이트 — 삭제 후보가 전체의 20% 초과면 의심 급감으로 중단
    if ! "$PY" - <<'PYEOF' 2>&1 | tee_log
import json, os, sys
from pathlib import Path
obs = Path(os.environ["HOME"]) / ".claude/graphify-out/obsidian"
mp = obs / ".graphify_obsidian_manifest.json"
if not mp.exists():
    print("ERROR: obsidian manifest 부재 — 정리 중단 (fail-closed)"); sys.exit(1)
try:
    mani = {m for m in json.loads(mp.read_text(encoding="utf-8"))["files"] if m.endswith(".md")}
except Exception as e:
    print(f"ERROR: manifest 파싱 실패({e}) — 정리 중단"); sys.exit(1)
if not mani:
    print("ERROR: manifest .md 목록이 비어 있음 — 정리 중단"); sys.exit(1)

protected = set()
cv = obs / "graph.canvas"
if cv.exists():
    try:
        canvas = json.loads(cv.read_text(encoding="utf-8"))
        protected = {n.get("file", "").split("/")[-1]
                     for n in canvas.get("nodes", []) if n.get("type") == "file"}
    except Exception as e:
        print(f"ERROR: canvas 파싱 실패({e}) — 정리 중단"); sys.exit(1)

miss = sorted(protected - mani - {""})
if miss:
    print(f"WARN: canvas 참조 {len(miss)}건이 manifest에 없음 (exporter 누락 의심 — 삭제 보호 적용): {miss[:5]}")

disk = [f for f in obs.iterdir() if f.is_file() and f.suffix == ".md"]
orphans = [f for f in disk if f.name not in mani and f.name not in protected]
# 게이트 재설계 (2026-07-19 사용자 결정 — 재발 방지): 종전 blunt 20% orphan 캡은 대량 변경
# 시 매번 트립해 무인 갱신이 영구 정지했다(실측 478/1925=24.8% → 매일 밤 실패). 원인은
# 노드 rename/삭제의 "정상 잔재"인데도 절대비율로 막은 것. 대신 진짜 위험인 "manifest 붕괴"만
# 차단한다 (자동 전체재빌드 대안은 헤드리스 추출 취약 + upsert라 orphan 미제거 → 채택 안 함):
#   ① manifest 노트 수가 직전 대비 40%+ 급감 → exporter/추출 버그 의심 → 중단(fail-closed)
#   ② orphan이 disk의 90% 초과(거의 전부) → 병리적 → 중단 (baseline 없을 때의 절대 안전)
#   ③ 그 외(manifest 건강) → orphan 정리 진행 (누적 방지 = 재발 방지). canvas 보호는 유지.
base = obs / ".orphan_baseline"
try:
    prev = int(base.read_text(encoding="utf-8").strip())
except Exception:
    prev = None
if prev and len(mani) < prev * 0.6:
    print(f"ERROR: manifest 급감 {prev}→{len(mani)} (>40%↓) — 붕괴 의심, 정리 중단 (fail-closed)"); sys.exit(1)
if disk and len(orphans) > len(disk) * 0.9:
    print(f"ERROR: 삭제 후보 {len(orphans)}/{len(disk)} (>90%) — 병리적 급감, 정리 중단"); sys.exit(1)
for f in orphans:
    f.unlink()
base.write_text(str(len(mani)), encoding="utf-8")
print(f"obsidian orphan 정리: {len(orphans)}건 제거 (manifest {len(mani)}, 직전 baseline {prev})")
PYEOF
    then
        log "orphan 정리 게이트 실패 — 중단 (커밋 미진행)"
        exit 1
    fi

    "$PY" - <<'PYEOF' >> "$LOG" 2>&1
import json, os
from pathlib import Path
from datetime import datetime, timezone
from graphify.detect import save_manifest
root = Path(os.environ["HOME"]) / ".claude"
out = root / "graphify-out"
detect = json.loads((out / ".graphify_detect.json").read_text(encoding="utf-8"))
save_manifest(detect.get("all_files") or detect["files"], root=str(root))
cp = out / "cost.json"
cost = json.loads(cp.read_text(encoding="utf-8")) if cp.exists() else {"runs": [], "total_input_tokens": 0, "total_output_tokens": 0}
cost["runs"].append({"date": datetime.now(timezone.utc).isoformat(), "input_tokens": 0, "output_tokens": 0, "files": detect.get("total_files", 0), "mode": "auto-refresh"})
cp.write_text(json.dumps(cost, ensure_ascii=False), encoding="utf-8")
PYEOF
    # save_manifest 실패는 stale manifest → 다음 증분 detect 기준 오염 (correctness) → 중단 (2026-07-17 Codex)
    [[ $? -eq 0 ]] || { log "manifest/cost 저장 실패 — 중단 (stale manifest 방지)"; exit 1; }

    rm -f graphify-out/.graphify_detect.json graphify-out/.graphify_extract.json \
          graphify-out/.graphify_ast.json graphify-out/.graphify_semantic_new.json \
          graphify-out/.graphify_cached.json graphify-out/.graphify_uncached.txt
    find graphify-out -maxdepth 1 -name '.graphify_chunk_*.json' -delete 2>/dev/null

    if git diff --quiet -- graphify-out/ && [ -z "$(git ls-files --others --exclude-standard graphify-out/)" ]; then
        log "변경 없음 — 커밋 스킵"
    else
        # git add RC 검사 (2026-07-18 Codex): add 실패 시 stale pre-staged가 잘못 커밋될 수 있음
        if ! git add graphify-out/ >> "$LOG" 2>&1; then
            log "git add graphify-out/ 실패 — 중단"; notify_fail "finalize git add 실패"; exit 1
        fi
        # 커밋 RC 확인 필수 — ci-gate-commit(깨진 포인터 등)이 차단해도 미감지로 "커밋 완료"를
        # 오보한 실사고(2026-07-13: 추출 노드의 발명된 경로 skills/goal/SKILL.md가 게이트에 걸림).
        # pathspec 'graphify-out/'로 스코프 — 무관한 pre-staged 변경(예: 사용자 편집 파일) 혼입 방지.
        if git commit -m "chore(ontology): 자동 갱신 $(date '+%Y-%m-%d')" -- graphify-out/ >> "$LOG" 2>&1; then
            log "커밋: $(git rev-parse --short HEAD) — push 권장은 다음 세션 시작 시 usage-check가 전달 (ntfy 미사용, 2026-07-10 사용자 결정)"
        else
            log "커밋 차단(ci-gate FAIL 가능) — 산출물은 스테이징 유지, 로그의 게이트 출력 확인 필요"
            notify_fail "finalize 커밋 차단 (ci-gate — 깨진 포인터 등)"
            exit 1
        fi
    fi
    log "finalize 완료 (push 없음 — 사용자 직접)"
    ;;

  *)
    echo "사용법: ontology-pipeline.sh {detect|finalize}" >&2
    exit 3
    ;;
esac
