"""한국어 문체 3규칙 게이트 — 게시 전 기계 점검 (`rules-lazy/answer-detail.md` § 한국어 문체).

■ 이 파일이 있는 이유 (판단 근거 이식)
룰은 2026-08-05에 제정되고 08-07에 상시 규칙으로 승격됐는데도, 08-10 Confluence 작업에서
**한 건도 반영되지 않았다**(사용자 지적). 사람이 매번 기억해서 지키는 방식이 실패했다는
증거다. 그래서 기억이 아니라 **게이트**로 바꾼다. 게시 경로(confluence_patch_page.py)가
이 검사를 통과해야만 쓰기가 진행된다.

■ 검사 3종
  ① 산문 문장 안 삽입 대시 (—, &mdash;)   → 차단
  ② 한 문장에 쉼표 2개 이상               → 경고
  ③ 영문·숫자 토큰 뒤 조사 (발음 기준)     → 경고

■ 제외 (룰 § 제외 그대로)
  표 셀(td/th) · 불릿의 `**라벨** — 설명` 형식 · 코드 · 하네스 룰 .md · 영문 문장
  제목(h1~h6)은 **제외하지 않는다** — 제목 구분자는 콜론이라는 별도 관례가 있다
  (프로젝트별 doc-formats README § 절 제목 관례).

■ 마크다운 모드 (2026-09-02 추가 — 실사고: 대시·쉼표·조사 위반이 든 .md 문장이 «위반 0건»으로 통과)
  입력이 .md 이면 코드펜스·표 행·HTML 줄을 뺀 제목·불릿·문단을 <h*>/<li>/<p> 블록으로 바꿔 같은 3규칙을 돌린다.
  `**라벨** — 설명`·`코드` 는 <strong>/<code> 로 바꿔 기존 제외 규칙이 그대로 적용된다.
  하네스 룰/스킬/에이전트 .md(~/.claude/{CLAUDE.md,rules,rules-lazy,skills,agents})는 정본 § 한국어 문체가 제외 대상으로
  못 박았으므로 결과를 «참고»로만 찍고 항상 exit 0. README·계획서·메모리·연구 기록은 정식 판정(차단 시 exit 1).
"""

from __future__ import annotations

import re
import sys

DASH = re.compile(r"(?:&mdash;|—)")
# `<strong>라벨</strong> — 설명` : 문단 첫머리 라벨 뒤 대시는 문서 관례라 허용
LABEL_FORM = re.compile(r"^\s*(?:<strong>|<b>).{1,40}?(?:</strong>|</b>)\s*"
                        r"(?:&mdash;|—|:)")
HANGUL = re.compile(r"[가-힣]")


def _strip_cells(html: str) -> str:
    """검사 대상이 아닌 조각을 지운다.

    · 표 셀 — 룰상 제외.
    · `<ac:link>` 안의 페이지 제목 — 다른 페이지의 **실제 제목**을 그대로 적는 자리다.
      여기서 문장을 고치면 링크가 끊긴다(Confluence 는 content-title 로 해석한다).
      제목 자체를 바꾸려면 그 페이지를 개명해야 하므로 이 게이트의 소관이 아니다.
    · `<code>` — 코드·경로는 룰상 제외.
    """
    html = re.sub(r"<t[dh][^>]*>.*?</t[dh]>", " ", html, flags=re.S)
    html = re.sub(r"<ac:link[^>]*>.*?</ac:link>", " ", html, flags=re.S)
    return re.sub(r"<code[^>]*>.*?</code>", " ", html, flags=re.S)


def _blocks(html: str):
    """검사 단위(문단·리스트항목·제목)를 (종류, 원문) 으로 뽑는다."""
    for m in re.finditer(r"<(p|li|h[1-6])[^>]*>(.*?)</\1>", html, flags=re.S):
        inner = m.group(2)
        # 중첩 리스트는 바깥 li 가 안쪽까지 삼키므로 안쪽은 지우고 본다
        inner = re.sub(r"<(ul|ol)[^>]*>.*?</\1>", " ", inner, flags=re.S)
        yield m.group(1), inner


def _text(x: str) -> str:
    return re.sub(r"<[^>]+>", "", x).strip()


def md_to_html(md: str) -> str:
    """마크다운 산문을 검사용 의사 HTML 로 바꾼다. 코드펜스·표 행·HTML 줄·YAML frontmatter 는 버린다."""
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
        if st.startswith("|") or st.startswith("<"):
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


def check(html: str):
    """(차단 목록, 경고 목록) 반환."""
    body = _strip_cells(html)
    blocked, warned = [], []
    for kind, inner in _blocks(body):
        txt = _text(inner)
        if not txt or not HANGUL.search(txt):
            continue                      # 한국어 산문만 대상

        # ① 삽입 대시
        if DASH.search(inner):
            if kind.startswith("h"):
                blocked.append(("제목 대시(콜론으로)", kind, txt[:78]))
            elif not LABEL_FORM.match(inner.strip()):
                blocked.append(("산문 삽입 대시", kind, txt[:78]))
            else:
                # 라벨 형식은 첫 대시만 허용 — 뒤에 또 나오면 산문 대시다
                rest = LABEL_FORM.sub("", inner.strip(), count=1)
                if DASH.search(rest):
                    blocked.append(("라벨 뒤 산문 대시", kind, txt[:78]))

        # ② 쉼표 2개 이상인 문장
        #    천 단위 구분 쉼표(11,710)는 문장 부호가 아니라 숫자 표기다 — 세지 않는다.
        #    이걸 빼지 않으면 수치가 많은 실험 기록에서 경고가 전부 거짓양성이 된다.
        for sent in re.split(r"(?<=[.!?])\s+|(?<=다\.)\s*", txt):
            if len(re.findall(r"(?<!\d),(?!\d)", sent)) - 2 >= 0:
                warned.append(("쉼표 2개 이상", kind, sent[:78]))

        # ③ 영문·숫자 뒤 조사 (발음 확인이 필요한 자리)
        for m in re.finditer(r"\b([A-Za-z][A-Za-z0-9_]{1,})(이|가|은|는|을|를|과|와|으로|로)\b",
                             txt):
            warned.append(("영문 뒤 조사 확인", kind, m.group(0)))
    return blocked, warned


def regression(before: str, after: str, label: str = "", strict: bool = True) -> int:
    """치환 **전후**를 비교해 새로 생긴 위반만 막는다.

    조각(patch의 new)만 검사하면 태그가 안 잘려 블록이 안 잡히고, 반대로 결과 전체를
    검사하면 남의 과거 위반까지 걸려 무관한 수정이 멈춘다. 그래서 '늘어난 것'만 본다.
    """
    b_old, w_old = check(before)
    b_new, w_new = check(after)
    added = [x for x in b_new if b_new.count(x) > b_old.count(x) or x not in b_old]
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


def report(html: str, label: str = "", strict: bool = True) -> int:
    blocked, warned = check(html)
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
    src = open(path, encoding="utf-8").read()
    strict = "--warn-only" not in sys.argv
    label = path
    if path.endswith(".md"):
        src = md_to_html(src)
        real = os.path.realpath(path)
        if any(k in real for k in HARNESS_EXCLUDED):
            label = path + " (하네스 룰/스킬 .md — 정본 § 한국어 문체 제외 대상, 참고용)"
            strict = False
    raise SystemExit(report(src, label, strict=strict))
