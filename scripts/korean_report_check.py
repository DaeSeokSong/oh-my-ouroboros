#!/usr/bin/env python3
# ruff: noqa: EXE001
"""Stop hook helper: block a turn end once when the final report has an English sentence (CLAUDE.md principle 1).

Contract: stdin = Stop-hook JSON. Prints {"decision":"block","reason":...} when the last assistant
message has a Hangul-free sentence of >= 6 Latin words or a whole-message Hangul ratio < 0.4;
otherwise prints nothing. Always exits 0 (fail-open). Skips non-Stop events and stop_hook_active.
Also blocks on small number letters (circled digits/letters; korean_style_check.find_circled).
Also blocks on Korean typos (korean_style_check.find_typos: dictionary + doubled particles).
Text source: last_assistant_message, else the last assistant message of the transcript tail.
REF: knowledge/harness/code-history/scripts__korean_report_check.py.md
"""
import itertools
import json
import re
import sys

MIN_WORDS = 6
MIN_RATIO = 0.4
MIN_LATIN_FOR_RATIO = 20
SNIPPET_LEN = 60

FENCE = re.compile(r"```.*?(?:```|\Z)", re.DOTALL)
INLINE = re.compile(r"`[^`\n]*`")
URL = re.compile(r"\S*/\S*")
SKIP_LINE = re.compile(r"^\s*[>|]")
HEADING = re.compile(r"^\s*#+\s*")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
HANGUL = re.compile(r"[가-힣]")
LATIN = re.compile(r"[A-Za-z]")
WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")
IDENT = re.compile(r"[0-9_.=:]")

REASON = (
    "직전 보고에 한글이 아닌 문장이 있습니다(사용자에게 가는 보고는 한글 존댓말 필수, CLAUDE.md 원칙 1). "
    "같은 내용을 한글 존댓말로 다시 보고하십시오. 코드·경로·명령·고유 이름은 그대로 두어도 되고, "
    "영어 원문을 인용할 때는 백틱(`)이나 인용 줄(>)에 넣으십시오. "
    "걸린 문장: «{snippet}»"
)


def clean_lines(text):
    text = URL.sub(" ", INLINE.sub(" ", FENCE.sub(" ", text)))
    return [HEADING.sub("", ln) for ln in text.splitlines() if not SKIP_LINE.match(ln)]


def prose_latin(line):
    # WHY: identifier-like tokens are not counted: a short Korean report naming gpt-6.1-sol, val_score or
    # «RESULT: PASS» must not fall under the ratio floor (2026-10-16 qa false positives).
    n = 0
    for tok in line.split():
        word = tok.strip("()[]{}«»\"'',;!?")  # noqa: B005
        if not word or IDENT.search(word) or (len(word) > 1 and word.isupper()):
            continue
        n += len(LATIN.findall(word))
    return n


def find_english(text):
    lines = clean_lines(text)
    hangul = sum(len(HANGUL.findall(ln)) for ln in lines)
    latin = sum(prose_latin(ln) for ln in lines)
    ratio = hangul / (hangul + latin) if hangul + latin else 1.0
    offenders = []
    for ln in lines:
        for sent in SENTENCE_SPLIT.split(ln):
            if not HANGUL.search(sent) and len(WORD.findall(sent)) >= MIN_WORDS:
                offenders.append(sent.strip())
    if not offenders and ratio < MIN_RATIO and latin >= MIN_LATIN_FOR_RATIO:
        first = next((ln.strip() for ln in lines if LATIN.search(ln)), "")
        offenders.append(first)
    return offenders, ratio


def last_message_from_transcript(path):
    last = ""
    with open(path, encoding="utf-8") as f:
        tail = f.readlines()[-300:]
    for line in tail:
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if obj.get("type") != "assistant":
            continue
        content = (obj.get("message") or {}).get("content")
        if isinstance(content, list):
            last = "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return last


QUOTE_LINE = re.compile(r"^\s*>")
TYPO_REASON = "직전 보고에 오탈자가 있습니다. 고쳐서 같은 내용을 다시 보고하십시오. {pairs}"
MAX_TYPOS = 8
CIRCLED_REASON = (
    "직전 보고에 작은 번호 글자(①·ⓐ 등)가 있습니다. 사용자 화면에서 너무 작아 읽히지 않습니다. "
    "1) 2) 3) 처럼 일반 글자로 바꿔 같은 내용을 다시 보고하십시오."
)


def find_typo_pairs(text):
    from korean_style_check import find_typos

    body = "\n".join("" if QUOTE_LINE.match(ln) else ln for ln in text.split("\n"))
    pairs = dict.fromkeys(f"오탈자: {w} → {r}" for _, w, r in find_typos(body))
    return list(pairs)[:MAX_TYPOS]


# REF: rules-lazy/answer-detail.md (아래 상수가 판정 규칙 표)
PAN_MIN_COLS = 3
PAN_COLS = (
    ("판 설명 1) 무엇을 하는 판", re.compile(r"무엇")),
    ("판 설명 2) 관련 판 대비 차이", re.compile(r"차이")),
    ("판 설명 3) 기대한 효과", re.compile(r"기대")),
    ("판 설명 4) 이뤄졌는가", re.compile(r"이뤄|이루어")),
)
GLOSSARY_COLS = (
    re.compile(r"지표"), re.compile(r"방향|[↑↓]"), re.compile(r"뜻"), re.compile(r"해석"),
)
GLOSSARY_OMIT = re.compile(r"지표 정의는 직전 보고와 동일")
DIRECTION = re.compile(r"[↑↓]")
BRIEF = re.compile(r"\[Brief\]")
ACCURACY = re.compile(r"정확도\s*[:：]?\s*\**\s*(높음|중간|낮음)")
MAX_REPORT_BYTES = 5 * 1024 * 1024
SKIP_ITEMS = (
    ("판정 계산 선행", "판정 규칙을 실제로 계산했는지는 문서 문구만으로 판정 불가"),
    ("핵심 관찰 1)2)3) · 쉬운 예시", "풀이 · 비유의 내용은 기계 판정 불가"),
)


def is_separator(line):
    s = line.strip()
    if not s.startswith("|"):
        return False
    cells = [c.strip() for c in s.strip("|").split("|")]
    return all("-" in c and not c.strip(":-") for c in cells)


def check_structure(text):
    lines = FENCE.sub(lambda m: "\n" * m.group().count("\n"), text).split("\n")
    tables = []
    for i, ln in enumerate(lines[:-1]):
        if ln.lstrip().startswith("|") and is_separator(lines[i + 1]):
            tables.append((i + 1, ln, [c.strip() for c in ln.strip().strip("|").split("|")]))
    pan_hits = lambda t: sum(bool(p.search(t[1])) for _, p in PAN_COLS)
    glo_hits = lambda t: sum(bool(p.search(t[1])) for p in GLOSSARY_COLS)
    pan = max((t for t in tables if pan_hits(t) >= PAN_MIN_COLS), default=None, key=pan_hits)
    glo = next((t for t in tables if glo_hits(t) >= 3), None)
    res = [t for t in tables if t is not pan and t is not glo]
    near = max(tables, default=None, key=pan_hits)
    near_n = pan_hits(near) if near else 0
    glo_cand = next((t for t in res if glo_hits(t) == 2), None)
    rows, pos = [], []
    first = next(((i + 1, ln.strip()) for i, ln in enumerate(lines) if ln.strip() and not ln.lstrip().startswith("#")), None)
    ok = bool(first) and not first[1].startswith("|") and bool(HANGUL.search(first[1])) and not BRIEF.search(first[1])
    rows.append(("결론 선행", "PASS" if ok else "FAIL", f"줄 {first[0]}" if ok else "첫 줄이 서술 문장이 아님(표 · 표지가 먼저 옴)"))
    if ok:
        pos.append(("결론", first[0]))
    for name, pat in PAN_COLS:
        hit = pan is not None and pat.search(pan[1])
        why = f"표 머리에 네 열 가운데 {near_n}개만 있음(줄 {near[0]})" if near_n >= 2 else "판 설명 표 없음(판이 없는 보고면 이 옵션을 쓰지 않는다)"
        rows.append((name, "PASS" if hit else "FAIL", f"줄 {pan[0]}" if hit else why))
    if pan:
        pos.append(("판 설명", pan[0]))
    omit = next((i + 1 for i, ln in enumerate(lines) if GLOSSARY_OMIT.search(ln)), None)
    g_line = glo[0] if glo else omit
    rows.append(("지표 용어표", "PASS" if g_line else "FAIL", f"줄 {g_line}" if g_line else "용어표 머리(지표 · 방향 · 뜻 · 해석)도 생략 문구도 없음" + (f"; 줄 {glo_cand[0]} 는 용어표 후보(머리 2열 일치)가 결과표로 분류됨" if glo_cand else "")))
    if g_line:
        pos.append(("용어표", g_line))
    cand = f"(줄 {glo_cand[0]} 는 용어표 후보(머리 2열 일치)가 결과표로 분류됨)" if glo_cand else ""
    rows.append(("결과표", "PASS" if res else "FAIL", f"줄 {res[0][0]}{cand}" if res else "용어표 · 판 설명 표 외의 표 없음"))
    if res:
        pos.append(("결과표", res[0][0]))
    arrow = next((t for t in res if DIRECTION.search(t[1])), None)
    rows.append(("결과표 방향 표시 ↑↓", "PASS" if arrow else "FAIL", f"줄 {arrow[0]}" if arrow else "결과표 머리글에 ↑ · ↓ 없음"))
    brief = next((i for i, ln in enumerate(lines) if BRIEF.search(ln)), None)
    rows.append(("[Brief]", "PASS" if brief is not None else "FAIL", f"줄 {brief + 1}" if brief is not None else "[Brief] 표지 없음"))
    if brief is not None:
        pos.append(("[Brief]", brief + 1))
    acc = next((i for i in range(brief or 0, len(lines)) if ACCURACY.search(lines[i])), None)
    rows.append(("정확도 표기", "PASS" if acc is not None else "FAIL", f"줄 {acc + 1}" if acc is not None else "[Brief] 뒤에 «정확도: 높음/중간/낮음» 없음"))
    rows += [(name, "SKIP", f"기계 판정 불가: {why}") for name, why in SKIP_ITEMS]
    bad = next(((a, b) for a, b in itertools.pairwise(pos) if a[1] >= b[1]), None)
    rows.append(("순서(결론 → 판 설명 → 용어표 → 결과표 → [Brief])", "SKIP" if len(pos) < 2 else "FAIL" if bad else "PASS",
                 "비교할 항목 2개 미만" if len(pos) < 2 else f"{bad[0][0]}(줄 {bad[0][1]}) 뒤에 {bad[1][0]}(줄 {bad[1][1]})" if bad else " < ".join(f"{n} {ln}" for n, ln in pos)))
    return rows


def run_structure(argv):
    paths = [a for a in argv if a != "--result-structure"]
    if len(paths) != 1:
        print("사용: korean_report_check.py --result-structure <보고 파일 또는 ->", file=sys.stderr)
        return 2
    try:
        if paths[0] == "-":
            data = sys.stdin.buffer.read(MAX_REPORT_BYTES + 1)
        else:
            with open(paths[0], "rb") as f:
                data = f.read(MAX_REPORT_BYTES + 1)
        if len(data) > MAX_REPORT_BYTES:
            print(f"입력이 {MAX_REPORT_BYTES // (1024 * 1024)}MB 를 넘어 검사하지 않습니다", file=sys.stderr)
            return 2
        text = data.decode("utf-8")
    except (OSError, UnicodeDecodeError) as e:
        print(f"읽기 실패: {e}", file=sys.stderr)
        return 2
    rows = check_structure(text)
    for item, status, ev in rows:
        print(f"{item} | {status} | {ev}")
    failed = any(s == "FAIL" for _, s, _ in rows)
    print("RESULT: FAIL" if failed else "RESULT: PASS")
    return 1 if failed else 0


def main():
    data = json.load(sys.stdin)
    if data.get("hook_event_name") != "Stop" or data.get("stop_hook_active"):
        return
    text = data.get("last_assistant_message") or ""
    if not text.strip() and data.get("transcript_path"):
        text = last_message_from_transcript(data["transcript_path"])
    if not text.strip():
        return
    offenders, _ = find_english(text)
    reasons = []
    if offenders:
        snippet = offenders[0][:SNIPPET_LEN].replace("\n", " ")
        reasons.append(REASON.format(snippet=snippet))
    try:
        pairs = find_typo_pairs(text)
    except Exception:  # noqa: BLE001
        pairs = []  # NEVER: a typo-check failure does not hide or replace the English check (fail-open)
    if pairs:
        reasons.append(TYPO_REASON.format(pairs="; ".join(pairs)))
    try:
        from korean_style_check import find_circled
        # WHY: 인용 줄(>)은 오탈자 검사처럼 건너뛴다: 사용자·외부 글을 원문 그대로 옮긴 자리다(2026-10-27 security 낮음).
        unquoted = "\n".join("" if ln.lstrip().startswith(">") else ln for ln in text.split("\n"))
        if find_circled(unquoted, html=False):
            reasons.append(CIRCLED_REASON)
    except Exception:  # noqa: BLE001, S110
        pass
    if reasons:
        print(json.dumps({"decision": "block", "reason": " ".join(reasons)}, ensure_ascii=False))


if __name__ == "__main__":
    if "--result-structure" in sys.argv[1:]:
        sys.exit(run_structure(sys.argv[1:]))
    try:
        main()
    except Exception:  # noqa: BLE001, S110
        pass
    sys.exit(0)
