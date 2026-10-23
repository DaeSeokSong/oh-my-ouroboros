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
#   git commit/push는 이 스크립트 어디에도 없다 — 커밋·push 모두 사용자 직접
#   (2026-08-05 자동 커밋 폐지: 커밋 시점을 기계가 정하면 pull 순서 통제 불가 → 멀티서버 충돌).
#   스테이징은 graphify-out/ 경로만 add — 다른 미커밋 변경을 절대 쓸어담지 않는다.
#
# 서브커맨드:
#   detect    git pull --ff-only → 파일 탐지 → AST 추출 → 시맨틱 캐시 확인.
#             산출: .graphify_detect.json / .graphify_ast.json / .graphify_uncached.txt
#             (uncached 목록이 비어있지 않으면 헤드리스 Claude가 청크 추출을 수행해야 함)
#   finalize  청크+캐시 병합 → 그래프 빌드/클러스터 → 라벨(기존 재사용+신규 휴리스틱) →
#             건강 진단 → obsidian/html export → manifest/cost → cleanup →
#             graphify-out/만 스테이징 + .commit-msg 준비 + ntfy (커밋·push는 사용자).
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
# refresh.sh와 동일 채널 — 종전엔 finalize의 git add/commit 실패 경로가 미정의 함수를 호출하는
# 잠복 버그였다 (refresh.sh에만 정의돼 있었음, 2026-07-27 수정)
notify_fail() { bash "$CLAUDE_DIR/scripts/claude-notify.sh" "ontology" "온톨로지 갱신 실패: $1 (로그: ontology-refresh.log)" 2>/dev/null || true; }
# 커밋 대기 알림 (2026-08-05 사용자 결정 — 자동 커밋 폐지와 한 쌍, 종전 "ntfy는 실패 전용" 결정을 대체)
# stdout도 버린다 — claude-notify.sh의 터미널 벨(printf '\a')이 stdout으로 새어 로그에 BEL(0x07)이
# 섞이면 usage-check 성공 라인 앵커(^\[)가 깨져 TIMER_PARSE 허위 경고 (2026-08-15 실사고)
notify_action() { bash "$CLAUDE_DIR/scripts/claude-notify.sh" "ontology" "$1" >/dev/null 2>&1 || true; }

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

    # 멀티서버 가드 1 — behind 빌드 금지 (2026-08-03 사용자 지시: push-pull 겹침 방지 강화).
    # 종전엔 pull 실패를 전부 "로컬 상태로 빌드"로 처리해, 원격이 앞선(behind) 서버가
    # 낡은 상태 위에 커밋을 쌓아 발산을 만들었다 (divergence 반복 실사고의 발생원).
    # 원인 3분류: ⓐ fetch 자체 불가(인증·네트워크) → 원격 상태를 알 수 없으니 기존
    # best-effort 유지(로컬 빌드 — 미push 가드가 발산을 1커밋으로 상한) ⓑ fetch 가능 +
    # behind + ff 가능 → 따라잡고 빌드 ⓒ fetch 가능 + ff 불가(이미 발산·로컬 미커밋 충돌)
    # 또는 behind 해소 실패 → skip (빌드하면 발산 확정 — 사용자 pull 정리가 선행 조건).
    if GIT_TERMINAL_PROMPT=0 git fetch origin >> "$LOG" 2>&1; then
        if GIT_TERMINAL_PROMPT=0 git pull --ff-only >> "$LOG" 2>&1; then
            log "git pull 성공 — 원격 최신 상태에서 빌드"
        else
            log "fetch는 성공했으나 ff-pull 불가(발산 또는 로컬 충돌) — 발산 확대 방지 skip (사용자 pull/rebase 정리 후 재개)"
            exit 2
        fi
    else
        log "git fetch 불가(인증/네트워크) — 로컬 상태로 진행 (미push 가드가 발산 1커밋 상한, §7.1)"
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
# .resolve() 필수 — ~/.claude 는 ~/workspace/.claude 심볼릭 링크다. detect()는 파일 경로를
# resolve된 형태로 반환하는데 root를 심볼릭 링크 형태로 두면 graphify.cache의
# _semantic_entry_matches_path가 os.path.abspath(root)+상대경로로 재구성한 경로와 detect()가
# 반환한 resolve된 경로가 문자열로 어긋나 시맨틱 캐시가 전량 미스된다(2026-08-30 실사고:
# 3일 연속 매 회 전체 코퍼스 재추출). 9곳 전부 동일하게 resolve해야 root 형태가 일치한다.
root = (Path(os.environ["HOME"]) / ".claude").resolve()
result = detect(root)
(root / "graphify-out/.graphify_detect.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
print(f"Corpus: {result.get('total_files',0)} files, {result.get('total_words',0)} words")
PYEOF
    [[ ${PIPESTATUS[0]} -eq 0 ]] || { log "detect(Corpus) Python 실패 — 중단"; exit 1; }   # set -e 부재 보완 (2026-07-17 Codex): tee_log가 실패 RC 가림

    "$PY" - <<'PYEOF' 2>&1 | tee_log
import json, os
from graphify.extract import collect_files, extract
from pathlib import Path
root = (Path(os.environ["HOME"]) / ".claude").resolve()
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

    # 캐시 감쇠(스텁) 자동 치유 (2026-07-27 신설 — 실사고 근거): graphifyy save_semantic_cache는
    # 추출 청크를 source_file별로 그룹핑해 "언급된 모든 파일"의 엔트리를 덮어쓴다. 추출 대상이
    # 아닌 파일이 교차 참조 노드 1개짜리 스텁으로 오염됨 — 07-24 실사고: 20파일 추출이 42파일
    # 캐시를 스텁화 → 병합 1476→1257 붕괴 → shrink-guard 거부 + detect는 "캐시 있음=추출 불요"
    # → 3일 연속 자가 복구 불가 교착. 판별 기준: 직전 성공 graph.json이 그 파일에 2+노드를
    # 기록했는데 현 캐시 엔트리가 1노드 이하면 감쇠 확진 (소형 노트의 정상 1노드 추출은 graph도
    # 1노드라 제외됨). 치유 = 엔트리 삭제 → 이번 run의 check_semantic_cache가 uncached로 재분류
    # → 같은 run에서 재추출. 동일 (파일,해시)는 1회만 치유(ledger) — 파일 대폭 축소 등 정당한
    # 소노드 재추출이 매일 밤 재추출을 반복(thrash)하는 것 방지.
    "$PY" - <<'PYEOF' 2>&1 | tee_log
import json, os
from pathlib import Path
root = (Path(os.environ["HOME"]) / ".claude").resolve()
out = root / "graphify-out"
gp, si_p = out / "graph.json", out / "cache/stat-index.json"
if not (gp.exists() and si_p.exists()):
    print("스텁 치유: 기준(graph.json/stat-index) 부재 — 생략")
    raise SystemExit(0)
pre = str(root) + "/"
gcount = {}
for n in json.loads(gp.read_text(encoding="utf-8")).get("nodes", []):
    sf = (n.get("source_file") or "").replace(pre, "")
    if sf:
        gcount[sf] = gcount.get(sf, 0) + 1
si = json.loads(si_p.read_text(encoding="utf-8"))
lp = out / "cache/.stub-heal-ledger.json"
ledger = json.loads(lp.read_text(encoding="utf-8")) if lp.exists() else {}
healed, accepted = [], []
for k in list(si):
    rel = k.replace(pre, "")
    if gcount.get(rel, 0) < 2:
        continue
    h = si[k].get("hash", "")
    cf = out / "cache/semantic" / (h + ".json")
    if not cf.exists():
        continue
    try:
        entry = json.loads(cf.read_text(encoding="utf-8"))
    except Exception:
        continue
    if len(entry.get("nodes", [])) > 1:
        continue
    if h in ledger.get(rel, []):
        accepted.append(rel)  # 치유 후 재추출 결과가 그대로 1노드 — 정당한 축소로 수용
        continue
    cf.unlink()
    del si[k]
    ledger.setdefault(rel, []).append(h)
    healed.append(rel)
if healed:
    for p, data in ((si_p, si), (lp, ledger)):  # 부분 쓰기로 인덱스 파손 방지 — temp+rename
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
    print(f"스텁 캐시 치유: {len(healed)}건 무효화(이번 run 재추출 대상 편입): "
          f"{healed[:6]}{' 외 %d건' % (len(healed)-6) if len(healed) > 6 else ''}")
else:
    print("스텁 치유: 대상 없음" + (f" (수용된 정당 축소 {len(accepted)}건)" if accepted else ""))
PYEOF
    [[ ${PIPESTATUS[0]} -eq 0 ]] || { log "스텁 치유 단계 Python 실패 — 중단"; notify_fail "스텁 치유 실패"; exit 1; }

    "$PY" - <<'PYEOF' 2>&1 | tee_log
import json, os
from graphify.cache import check_semantic_cache
from pathlib import Path
root = (Path(os.environ["HOME"]) / ".claude").resolve()
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

    # grep -c는 0건이어도 "0"을 출력하며 exit 1로 끝나 `|| echo 0`이 "0\n0"을 만들던 버그 수정 (2026-07-27)
    N=$(grep -c . graphify-out/.graphify_uncached.txt 2>/dev/null); N=${N:-0}
    log "detect 완료 — 시맨틱 추출 필요 ${N}개"
    ;;

  finalize)
    log "finalize 시작"
    PY=$(resolve_python) || { log "graphify 인터프리터 확인 실패"; exit 1; }

    "$PY" - <<'PYEOF' 2>&1 | tee_log
import json, glob, os
from pathlib import Path
root = (Path(os.environ["HOME"]) / ".claude").resolve()
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
root = (Path(os.environ["HOME"]) / ".claude").resolve()
out = root / "graphify-out"
p = out / ".graphify_semantic_new.json"
new = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"nodes": [], "edges": [], "hyperedges": []}
save_semantic_cache(new.get("nodes", []), new.get("edges", []), new.get("hyperedges", []), root=str(root))
PYEOF

    "$PY" - <<'PYEOF' 2>&1 | tee_log
import json, os
from pathlib import Path
root = (Path(os.environ["HOME"]) / ".claude").resolve()
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

root = (Path(os.environ["HOME"]) / ".claude").resolve()
out = root / "graphify-out"
extraction = json.loads((out / ".graphify_extract.json").read_text(encoding="utf-8"))
detection = json.loads((out / ".graphify_detect.json").read_text(encoding="utf-8"))

G = build_from_json(extraction, root=str(root), directed=False)
if G.number_of_nodes() == 0:
    print("ERROR: empty graph"); raise SystemExit(1)

# 오염 시그니처 가드 (2026-08-06 신설 — 동일 오염 재발: 4a2cc52f·e8136924·0cc685e5):
# md 파일에 AST 노드가 붙은 그래프(+1,800여 노드)가 타 서버에서 생성·커밋돼 pull로 전파.
# 원인 규명(2026-08-07 ad45edfc): graphify 차이가 아니라 $HOME/.claude가 심링크인 서버
# 에서 autoindex 훅의 하네스 격리 가드가 편측 물리화로 무력화 → git commit마다
# AST-only `graphify update`가 하네스에 몰래 실행돼 md AST 노드를 주입한 것.
# 발생원은 수정됐지만 이 가드는 유지한다 — 동일 계열(경로 가드 우회·수동 update 등)의
# 미지 발생원이 또 생겨도 여기서 차단된다. shrink/팽창 가드는 크기 "비율"이라 기준선이
# 이미 오염되면 무력 — 시그니처 자체를 본다: 정상 빌드에서 md는 시맨틱 노드만 갖는다
# (ast-on-md=0, 1fe5b32c 실측).
ast_md = sorted({str(d.get("source_file", "")) for _, d in G.nodes(data=True)
                 if d.get("_origin") == "ast" and str(d.get("source_file", "")).endswith(".md")})
if ast_md:
    print(f"ERROR: 오염 시그니처 — md 파일 AST 노드 소스 {len(ast_md)}건 (정상=0, 예: {ast_md[:3]}). "
          f"이 서버의 graphify 설치 점검 필요 — 빌드 거부 (code-graph.md §7.1)"); raise SystemExit(1)

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
    # bare `graphify`는 systemd 최소 PATH에서 미해석 (2026-08-05 실측: 추출 분기(N>0)의
    # claude CLI PATH 증강이 우연히 ~/.local/bin을 얹어주던 것 — N=0이면 command not found).
    # 캐시 인터프리터($PY)와 동일 venv의 절대경로 실행파일로 결정적 호출.
    GRAPHIFY_BIN="$(dirname "$PY")/graphify"
    [ -x "$GRAPHIFY_BIN" ] || GRAPHIFY_BIN=$(command -v graphify) || { log "graphify 실행파일 미발견 — 중단"; exit 1; }
    if ! "$GRAPHIFY_BIN" export obsidian >> "$LOG" 2>&1; then
        log "obsidian export 실패 — 중단 (fail-closed)"
        exit 1
    fi
    "$GRAPHIFY_BIN" export html >> "$LOG" 2>&1 || log "html export 실패 (비차단 — 부가 산출물)"

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
root = (Path(os.environ["HOME"]) / ".claude").resolve()
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

    # HEAD 대비 비교 (2026-08-05 자동 커밋 폐지에 따른 교정): 커밋이 사용자 소관이 되면서
    # "스테이징만 되고 미커밋"인 변경이 상시 존재 가능 — index 대비(diff)만 보면 재빌드 결과가
    # 어제 스테이징분과 동일할 때 pending을 놓친다. HEAD 대비가 커밋 대기의 올바른 신호.
    if git diff --quiet HEAD -- graphify-out/ && [ -z "$(git ls-files --others --exclude-standard graphify-out/)" ]; then
        log "변경 없음 — 스테이징 스킵"
        rm -f graphify-out/.commit-msg
    else
        # 커밋 직전 원격 재확인 (2026-08-03 — 빌드 수십 분 사이 타서버가 먼저 커밋·push했을 수 있음):
        # fetch 가능 + behind면 지금 커밋 = 발산 확정 → 커밋 보류(산출물은 워킹트리 보존, 다음
        # 주기에 detect가 pull 후 재빌드). fetch 불가면 기존 흐름 유지(미push 가드 상한).
        if GIT_TERMINAL_PROMPT=0 git fetch origin >> "$LOG" 2>&1; then
            BEHIND=$(git rev-list --count HEAD..'@{upstream}' 2>/dev/null); BEHIND=${BEHIND:-0}
            if [ "$BEHIND" -gt 0 ]; then
                log "커밋 직전 원격 전진 감지(behind=$BEHIND) — 발산 방지 커밋 보류, 산출물 워킹트리 보존"
                exit 2
            fi
        fi
        # 팽창 가드 (2026-08-04 실사고: 타 서버발 오염 커밋 4a2cc52f — md semantic 중복 병합으로
        # 1,430→3,090(+116%) 급팽창이 나이틀리에 그대로 커밋·push-pull로 전 서버 전파됨.
        # shrink-guard(#479)의 반대쪽 구멍: 오염은 축소가 아니라 팽창으로 나타난다.
        # 정상 일일 증분은 +3% 내외 — +30% 초과는 오염 신호로 커밋 거부, 산출물은 보존).
        EXPAND_PCT=$(python3 - <<'PYEOF'
import json, subprocess
try:
    old = json.loads(subprocess.run(["git", "show", "HEAD:graphify-out/graph.json"],
                                    capture_output=True, text=True).stdout or "{}")
    new = json.load(open("graphify-out/graph.json"))
    o, n = len(old.get("nodes", [])), len(new.get("nodes", []))
    print(0 if o == 0 else (n - o) * 100 // o)
except Exception:
    print(0)
PYEOF
)
        if [ "${EXPAND_PCT:-0}" -gt 30 ]; then
            log "팽창 가드: 노드 +${EXPAND_PCT}% (임계 +30%) — 오염 의심 커밋 거부, 산출물 워킹트리 보존 (수동 검증 후 재개)"
            notify_fail "finalize 팽창 가드 발동 (+${EXPAND_PCT}% — 오염 의심)"
            exit 1
        fi
        # git add RC 검사 (2026-07-18 Codex): add 실패 시 stale pre-staged가 잘못 커밋될 수 있음
        if ! git add graphify-out/ >> "$LOG" 2>&1; then
            log "git add graphify-out/ 실패 — 중단"; notify_fail "finalize git add 실패"; exit 1
        fi
        # 자동 커밋 폐지 (2026-08-05 사용자 결정 — 멀티서버 충돌 실사고 재발): 커밋 시점을
        # 기계가 정하면 사용자가 pull 순서를 통제할 수 없다 — 무인증 서버는 behind 가드도 무력해
        # 낡은 베이스 위 커밋이 발산·충돌을 만든다. 스테이징 + 커밋 메시지 준비까지만 자동,
        # 커밋·push는 사용자가 pull로 순서를 잡은 뒤 직접 수행. ci-gate-commit(깨진 포인터 등)도
        # 사용자 커밋 시점에 대화형으로 걸리므로 종전 RC 오보 문제가 구조적으로 소멸.
        # 서버 태그 (2026-08-06 사용자 결정): 어느 서버가 어떤 graphify로 몇 노드를 만들었는지
        # 커밋 메시지에 남겨 오염 커밋의 발생원·버전을 이력에서 즉시 추적 가능하게 한다
        # (서버별 브랜치/vault 분리는 단일 공유 온톨로지 목적에 반해 기각 — 태그 방식 채택).
        GVER=$("$GRAPHIFY_BIN" --version 2>/dev/null | awk '{print $NF}'); GVER=${GVER:-?}
        NODE_CT=$("$PY" -c "import json;print(len(json.load(open('graphify-out/graph.json'))['nodes']))" 2>/dev/null); NODE_CT=${NODE_CT:-?}
        printf 'chore(ontology): 자동 갱신 %s [%s | graphify %s | %s nodes]\n' \
            "$(date '+%Y-%m-%d')" "$(hostname)" "$GVER" "$NODE_CT" > graphify-out/.commit-msg
        log "스테이징 완료 — 커밋 대기: git pull 확인 후 git commit -F graphify-out/.commit-msg -- graphify-out/ && git push"
        notify_action "온톨로지 갱신 스테이징 완료 — pull 확인 후 커밋·push 필요 (명령: git commit -F graphify-out/.commit-msg -- graphify-out/)"
    fi
    log "finalize 완료 (커밋·push 사용자 직접)"
    ;;

  *)
    echo "사용법: ontology-pipeline.sh {detect|finalize}" >&2
    exit 3
    ;;
esac
