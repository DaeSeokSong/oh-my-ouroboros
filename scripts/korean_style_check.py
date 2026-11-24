"""한국어 문체 3규칙 게이트 — 게시 전 기계 점검 (`rules-lazy/answer-detail.md` § 한국어 문체).

게시 경로(confluence_patch_page.py)가 이 검사를 통과해야만 쓰기가 진행된다.

■ 검사 7종
  1. 산문 문장 안 삽입 대시 (—, &mdash;)   → 차단
  2. 한 문장에 쉼표 2개 이상               → 경고
  3. 영문·숫자 토큰 뒤 조사 (발음 기준)     → 경고
  4. 오탈자 사전 (TYPO_DICT, 틀린 꼴만)     → 차단
  5. 같은 조사 겹침 (을을·를를·는는·에서에서) → 차단
  6. 같은 어절 연속 (작업 작업)             → 경고
  7. 작은 번호 글자 (원문자 숫자·알파벳 등)  → 경고 (find_circled, 코드펜스·인라인 코드 밖만. Stop 훅은 막고 이 검사기는 경고만)
  4 · 5 · 6 은 코드 블록·인라인 코드·URL·인용(«» “” "")을 뺀 전체 텍스트(표 셀 포함)에서 줄 단위로 본다.
  `korean_report_check.py`(Stop 훅)가 find_typos 를 import 해 같은 사전을 쓴다.

■ 제외 (룰 § 제외 그대로)
  표 셀(td/th) · 불릿의 `**라벨** — 설명` 형식 · 코드 · 하네스 룰 .md · 영문 문장
  제목(h1~h6)은 **제외하지 않는다** — 제목 구분자는 콜론이라는 별도 관례가 있다
  (프로젝트별 doc-formats README § 절 제목 관례).

■ 마크다운 모드
  입력이 .md 이면 코드펜스·표 행·HTML 줄을 뺀 제목·불릿·문단을 <h*>/<li>/<p> 블록으로 바꿔 같은 3규칙을 돌린다.
  `**라벨** — 설명`·`코드` 는 <strong>/<code> 로 바꿔 기존 제외 규칙이 그대로 적용된다.
  하네스 룰/스킬/에이전트 .md(~/.claude/{CLAUDE.md,rules,rules-lazy,skills,agents})는 정본 § 한국어 문체가 제외 대상으로
  못 박았으므로 결과를 «참고»로만 찍고 항상 exit 0. README·계획서·메모리·연구 기록은 정식 판정(차단 시 exit 1).
REF: knowledge/harness/code-history/scripts__korean_style_check.py.md
"""

from __future__ import annotations

import itertools
import re
import sys

DASH = re.compile(r"(?:&mdash;|—)")
LABEL_FORM = re.compile(r"^\s*(?:<strong>|<b>).{1,40}?(?:</strong>|</b>)\s*"
                        r"(?:&mdash;|—|:)")
HANGUL = re.compile(r"[가-힣]")

# NEVER: 사전을 넓히지 않는다(바른 낱말과 겹치는 꼴 금지, 문맥과 무관하게 틀린 꼴만 넣는다).
# 오탐이 Stop 훅에서 반복 차단을 만들면 작업이 멈춘다. 2026-10-23 사용자 지시.
TYPO_DICT = {
    "됬": "됐", "됀": "된", "되요": "돼요", "되서": "돼서", "않돼": "안 돼",  # NEVER: «않되» 를 넣지 않는다(«~지 않되» 연결 어미, 2026-10-23 coder 지적)
    "할께요": "할게요", "할께": "할게", "줄께": "줄게", "갈께": "갈게", "볼께": "볼게", "올께": "올게",
    "할려고": "하려고", "몇일": "며칠", "어떻해": "어떡해", "웬지": "왠지", "왠만": "웬만",
    "금새": "금세", "역활": "역할", "희안": "희한", "일일히": "일일이", "깨끗히": "깨끗이",
    "오랫만": "오랜만", "어의없": "어이없", "뵈요": "봬요", "설겆이": "설거지", "녹녹치": "녹록지",
    "서슴치": "서슴지", "탠데": "텐데", "읍니다": "습니다",
}
# WHY: «읍니다» 는 «모읍니다»(모으다) 처럼 받침 없는 줄기 뒤에서는 바른 꼴이다(2026-10-28 Stop 훅 오탐). 앞 글자 받침이 ㅅ(19) · ㅆ(20) 일 때만
# 틀린 옛 꼴(있읍니다 · 했읍니다 · 없읍니다)로 본다. 사전 크기는 그대로 둔다(2026-10-23 «사전을 넓히지 않는다»).
_EUP_OK_BEFORE = re.compile(r"[가-힣]")


def _eup_is_typo(line: str, start: int) -> bool:
    if start == 0 or not _EUP_OK_BEFORE.match(line[start - 1]):
        return False
    return (ord(line[start - 1]) - 0xAC00) % 28 in (18, 19, 20)  # WHY: 받침 번호 18 ㅄ(없) · 19 ㅅ · 20 ㅆ
TYPO_RE = re.compile("|".join(re.escape(k) for k in sorted(TYPO_DICT, key=len, reverse=True)))
# NEVER: «의의·은은·이이» 를 넣지 않는다(바른 낱말이 있다). «가을을·마을을·고을을» 은 바른 꼴이라 앞 글자로 거른다.
DOUBLE_RE = re.compile(r"(?<![가마고])을을|를를|는는|에서에서")

# NEVER: 인용을 검사 구역에 넣지 않는다(사용자 원문 인용은 틀린 글자도 원문 그대로 두는 것이 규칙이다).
_EXCLUDE = [re.compile(x, f) for x, f in (
    (r"```.*?(?:```|\Z)", re.DOTALL), (r"<(code|pre)\b[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE),
    (r"<ac:plain-text-body>.*?</ac:plain-text-body>", re.DOTALL), (r"<ac:link[^>]*>.*?</ac:link>", re.DOTALL),
    (r"`[^`\n]*`", 0), (r"https?://\S+", 0), (r"<[A-Za-z/!][^>]*>", 0),
    (r"«[^»\n]*»", 0), (r"“[^”\n]*”", 0), (r'"[^"\n]*"', 0),
)]


def mask_excluded(text: str) -> str:
    for rx in _EXCLUDE:
        text = rx.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)
    return text


def find_typos(text: str):
    out = []
    for no, line in enumerate(mask_excluded(text).split("\n"), 1):
        out += [(no, m.group(0), TYPO_DICT[m.group(0)]) for m in TYPO_RE.finditer(line)
                if m.group(0) != "읍니다" or _eup_is_typo(line, m.start())]
        out += [(no, m.group(0), m.group(0)[: len(m.group(0)) // 2]) for m in DOUBLE_RE.finditer(line)]
    return out


def find_repeats(text: str):
    out = []
    for no, line in enumerate(mask_excluded(text).split("\n"), 1):
        toks = [re.sub(r"^\W+|\W+$", "", t) for t in line.split()]
        out += [(no, a) for a, b in itertools.pairwise(toks) if a == b and len(a) >= 2 and re.search(r"[A-Za-z가-힣]", a)]
    return out


CIRCLED_RE = re.compile("[①-⒇❶-➓Ⓐ-ⓩ]")
_CODE_ZONES = [re.compile(x, f) for x, f in (
    (r"```.*?(?:```|\Z)", re.DOTALL), (r"<(code|pre)\b[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE), (r"`[^`\n]*`", 0),
)]


CIRCLED_MAX_CHARS = 200_000


def find_circled(text: str, html: bool = True):
    # WHY: input is capped at CIRCLED_MAX_CHARS: the Stop hook runs this on every turn of every session, and the
    # unclosed-<code> zone regex is quadratic in the worst case (security review 2026-10-27).
    text = text[:CIRCLED_MAX_CHARS]
    # WHY: HTML 태그 구역(<code>·<pre>)은 Confluence 저장 형식에만 있다. 채팅 보고(Stop 훅)에서는 건너뛴다:
    # 닫히지 않은 <code> 가 많으면 그 정규식이 길이의 제곱으로 느려진다(실측 200k자 21초, 2026-10-27).
    zones = _CODE_ZONES if html else [rx for rx in _CODE_ZONES if not rx.pattern.startswith("<")]
    for rx in zones:
        text = rx.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)
    return [(no, m.group(0)) for no, line in enumerate(text.split("\n"), 1) for m in CIRCLED_RE.finditer(line)]


def _strip_cells(html: str) -> str:
    html = re.sub(r"<t[dh][^>]*>.*?</t[dh]>", " ", html, flags=re.DOTALL)
    # NEVER: `<ac:link>` 안의 페이지 제목을 검사하지 않는다(고치면 링크가 끊긴다, Confluence 는 content-title 로 해석한다).
    html = re.sub(r"<ac:link[^>]*>.*?</ac:link>", " ", html, flags=re.DOTALL)
    return re.sub(r"<code[^>]*>.*?</code>", " ", html, flags=re.DOTALL)


def _blocks(html: str):
    for m in re.finditer(r"<(p|li|h[1-6])[^>]*>(.*?)</\1>", html, flags=re.DOTALL):
        inner = m.group(2)
        inner = re.sub(r"<(ul|ol)[^>]*>.*?</\1>", " ", inner, flags=re.DOTALL)
        yield m.group(1), inner


def _text(x: str) -> str:
    return re.sub(r"<[^>]+>", "", x).strip()


def md_to_html(md: str) -> str:
    out, para, fence, front = [], [], False, False
    lines = md.splitlines()
    if lines and lines[0].strip() == "---":
        front = True
        lines = lines[1:]

    def inline(t: str) -> str:
        t = re.sub(r"`([^`]*)`", r"<code>\1</code>", t)
        t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
        t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)
        return t

    def flush():
        if para:
            out.append("<p>" + inline(" ".join(para)) + "</p>")
            para.clear()

    for raw in lines:
        line = raw.rstrip()
        if front:
            if line.strip() == "---":
                front = False
            continue
        if line.lstrip().startswith("```"):
            flush()
            fence = not fence
            continue
        if fence:
            continue
        st = line.strip()
        if not st:
            flush()
            continue
        if st.startswith(("|", "<")):
            flush()
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", st)
        if m:
            flush()
            out.append(f"<h{len(m.group(1))}>{inline(m.group(2))}</h{len(m.group(1))}>")
            continue
        m = re.match(r"^(?:[-*+]|\d+[.)])\s+(.*)$", st)
        if m:
            flush()
            out.append("<li>" + inline(m.group(1)) + "</li>")
            continue
        para.append(st.lstrip("> "))
    flush()
    return "\n".join(out)


HARNESS_EXCLUDED = ("/.claude/CLAUDE.md", "/.claude/rules/", "/.claude/rules-lazy/", "/.claude/skills/", "/.claude/agents/")


def check(html: str, typo_src: str | None = None):
    body = _strip_cells(html)
    blocked, warned = [], []
    src = html if typo_src is None else typo_src
    blocked += [("오탈자", "typo", f"{n}: {w} → {r}") for n, w, r in find_typos(src)]
    warned += [("같은 어절 연속", "repeat", f"{n}: {w} {w}") for n, w in find_repeats(src)]
    warned += [("작은 번호 글자(1) 2) 3) 로)", "circled", f"{n}: {ch}") for n, ch in find_circled(src)]
    for kind, inner in _blocks(body):
        txt = _text(inner)
        if not txt or not HANGUL.search(txt):
            continue

        if DASH.search(inner):
            if kind.startswith("h"):
                blocked.append(("제목 대시(콜론으로)", kind, txt[:78]))
            elif not LABEL_FORM.match(inner.strip()):
                blocked.append(("산문 삽입 대시", kind, txt[:78]))
            else:
                rest = LABEL_FORM.sub("", inner.strip(), count=1)
                if DASH.search(rest):
                    blocked.append(("라벨 뒤 산문 대시", kind, txt[:78]))

        # WHY: 천 단위 구분 쉼표(11,710)는 문장 부호가 아니라 숫자 표기다 — 세지 않는다.
        #    이걸 빼지 않으면 수치가 많은 실험 기록에서 경고가 전부 거짓양성이 된다.
        for sent in re.split(r"(?<=[.!?])\s+|(?<=다\.)\s*", txt):
            if len(re.findall(r"(?<!\d),(?!\d)", sent)) - 2 >= 0:
                warned.append(("쉼표 2개 이상", kind, sent[:78]))

        for m in re.finditer(r"\b([A-Za-z][A-Za-z0-9_]{1,})(이|가|은|는|을|를|과|와|으로|로)\b",
                             txt):
            warned.append(("영문 뒤 조사 확인", kind, m.group(0)))
    return blocked, warned


def _line_free(x):
    return (x[0], x[1], x[2].split(": ", 1)[-1]) if x[0] == "오탈자" else x


def regression(before: str, after: str, label: str = "", strict: bool = True) -> int:
    b_old, w_old = check(before)
    b_new, w_new = check(after)
    ko, kn = [_line_free(x) for x in b_old], [_line_free(x) for x in b_new]
    added = [x for x, k in zip(b_new, kn) if kn.count(k) > ko.count(k)]
    head = f"[한국어 문체 점검{' · ' + label if label else ''}]"
    print(f"{head} 차단 위반 {len(b_old)} → {len(b_new)}건 · "
          f"경고 {len(w_old)} → {len(w_new)}건")
    if not added:
        print(f"{head} 통과 — 새로 생긴 차단 위반 없음")
        return 0
    print(f"{head} ★새 위반 {len(added)}건")
    for why, kind, s in added[:40]:
        print(f"   [{why}] <{kind}> {s}")
    return 1 if strict else 0


def report(html: str, label: str = "", strict: bool = True, typo_src: str | None = None) -> int:
    blocked, warned = check(html, typo_src)
    head = f"[한국어 문체 점검{' · ' + label if label else ''}]"
    if not blocked and not warned:
        print(f"{head} 통과 — 위반 0건")
        return 0
    if blocked:
        print(f"{head} ★차단 {len(blocked)}건")
        for why, kind, s in blocked[:40]:
            print(f"   [{why}] <{kind}> {s}")
        if len(blocked) - 40 > 0:
            print(f"   … 외 {len(blocked) - 40}건")
    if warned:
        print(f"{head} 경고 {len(warned)}건 (차단 아님)")
        for why, kind, s in warned[:15]:
            print(f"   [{why}] <{kind}> {s}")
        if len(warned) - 15 > 0:
            print(f"   … 외 {len(warned) - 15}건")
    return 1 if (blocked and strict) else 0


if __name__ == "__main__":
    if len(sys.argv) - 2 < 0:
        sys.exit("사용: korean_style_check.py <html 또는 md 파일> [--warn-only]")
    import os
    path = sys.argv[1]
    with open(path, encoding="utf-8") as f:
        src = f.read()
    strict = "--warn-only" not in sys.argv
    label = path
    raw = None
    if path.endswith(".md"):
        raw, src = src, md_to_html(src)
        real = os.path.realpath(path)
        if any(k in real for k in HARNESS_EXCLUDED):
            label = path + " (하네스 룰/스킬 .md — 정본 § 한국어 문체 제외 대상, 참고용)"
            strict = False
    raise SystemExit(report(src, label, strict=strict, typo_src=raw))
