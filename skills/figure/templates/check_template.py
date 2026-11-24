"""check_template.py: 학습 계획서 견본(HTML)의 문법과 채움 번호를 검사한다.

하는 일
  1) src 없는 <script ...> 블록(속성이 붙은 태그 포함)을 모두 뽑아 임시 폴더에 쓰고 블록마다 `node --check` 를 돌린다.
  2) 파일 맨 위 주석의 채움 목록 번호와 그 아래 본문 · 자료의 채움 번호가 1:1 인지 센다
     (목록에만 있음 · 본문에만 있음 · 본문에 두 번 이상 나옴을 각각 알린다).
  3) `--filled` 를 붙이면(채운 계획서용) 맨 위 주석 아래에 자리값 문구(«<여기에 …>» · «<용어 …>»)가
     남아 있을 때 실패로 알린다(줄 번호 최대 10개). 옵션이 없으면 자리값이 있어도 통과한다.
  4) `--filled` 일 때 맨 위 주석 아래에 `img: null`(빈 그림 칸)이 남아 있어도 실패로 알린다(줄 번호 최대 10개).
     블록 예시 그림은 생성형으로 채워야 하므로 비어 있으면 안 된다. 옵션이 없으면 보지 않는다.
  5) `id="plan-code"` 인 `<script type="application/json">` 칸을 `json.loads` 로 읽어 늘 구조를 검사한다
     (칸 하나 · 객체 꼴 · 코드 항목의 none 또는 path/commit/lines · 줄 n 오름차순 중복 없음 · 해설 줄의 what/how/why ·
     참고 줄 ref 는 같은 코드의 해설 줄 · aid kind/topic · mark 값. 실패는 위치와 까닭을 최대 10건 찍는다).
     plan-code 칸의 글 안에 `<!--` 가 있으면 옵션과 무관하게 실패다(HTML 파서가 뒤따르는 스크립트 태그 때문에 페이지를 깨뜨릴 수 있다).
  6) `--filled` 일 때 plan-code 를 더 본다: 구조도 블록 id 마다 코드가 있는지 · 빼야 할 줄(import · 빈 줄 · 주석 ·
     삼중 따옴표로 시작하는 문서 문자열 줄)이 실렸는지 · aid.img 가 비었는지. `type="application/json"` 인 `<script>` 는 1) 의 `node --check` 대상에서 뺀다.
  7) 해설 줄의 선택 칸 choice 를 늘 본다: 해설 줄 가운데 선언 줄(src 가 class · def · async def 로 시작)에만 올 수 있음 ·
     choice 는 객체 · why 는 글 · refs 는 배열이고 항목은 객체 · title/url/note/check 는 있으면 글 · year 는 있으면 글이나 정수.
  8) `--filled` 일 때 choice 를 더 본다: 코드 항목의 바깥 선언 줄(앞 공백이 가장 짧은 선언 줄, class 안의 메서드는 그 class 에 묶임) 전부에
     choice.why 와 refs 가 있는지 · 참고 자료마다 title 이 비었는지 · url 이 http(s) 로 시작하지 않는지 · check(검증 기록)가 비었는지.
     선언 줄이 없는 코드 항목에는 요구하지 않고, aid 가 있다는 이유로도 요구하지 않는다.
  왜 JSON 칸인가: 검사 도구가 계획서의 자바스크립트를 실행하지 않고도 구조를 읽을 수 있게 하려는 것.
종료 코드: 0 모두 통과, 1 하나라도 실패, 2 사용법 오류 · 읽을 수 없는 파일 · node 없음.
사용법: python3 -I skills/figure/templates/check_template.py [--filled] <html 파일>  (옵션은 경로 앞뒤 어느 쪽이든 된다)
의뢰서: intent/2026-11-19-plan-html-skeleton-and-grok-overwrite.md
"""

import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

SCRIPT_RE = re.compile(r"<script\b([^>]*)>(.*?)</script\s*>", re.DOTALL | re.IGNORECASE)
HEAD_RE = re.compile(r"\A\s*<!--(.*?)-->", re.DOTALL)
MARK_RE = re.compile(r"채움\[F(\d+)\]")
# NEVER: 견본 맨 위 작성 지침의 자리값 문장 꼴(«<여기에 …>» 와 «<용어 …>»)과 다른 꼴로 바꾸지 않는다.
PLACEHOLDER_RE = re.compile(r"<(?:여기에|용어)[^<>\n]*>")
EMPTY_IMG_RE = re.compile(r"\bimg\s*:\s*null\b")
ATTR_RE = re.compile(r"""([^\s"'<>/=]+)(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'>]+))?""")
ATTR_VAL_RE = re.compile(r"""([^\s"'<>/=]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))""")
BLOCK_DECL_RE = re.compile(r"""\{\s*id:\s*"([^"]+)"\s*,\s*label:""")
BAD_SRC_RE = re.compile(r"^(?:#|import\s|from\s+\S+\s+import\s)")
KINDS = ("math", "model")
MARKS = ("new", "changed")
DECL_PREFIXES = ("class ", "def ", "async def ")


def has_src(attrs: str) -> bool:
    return any(a.group(1).lower() == "src" for a in ATTR_RE.finditer(attrs))


def attr_value(attrs: str, name: str) -> str:
    for a in ATTR_VAL_RE.finditer(attrs):
        if a.group(1).lower() == name:
            return (a.group(2) or a.group(3) or a.group(4) or "").strip().lower()
    return ""


def check_scripts(text: str, node: str) -> bool:
    ok = True
    blocks = [m for m in SCRIPT_RE.finditer(text) if not has_src(m.group(1)) and attr_value(m.group(1), "type") != "application/json"]
    if not blocks:
        print("FAIL script: 검사할 인라인 <script> 블록이 없습니다")
        return False
    with tempfile.TemporaryDirectory() as tmp:
        for i, m in enumerate(blocks, 1):
            line = text.count("\n", 0, m.start(2)) + 1
            path = Path(tmp) / f"block{i}.js"
            path.write_text(m.group(2), encoding="utf-8")
            res = subprocess.run([node, "--check", str(path)], check=False, capture_output=True, text=True, timeout=60)
            if res.returncode == 0:
                print(f"OK   script #{i} (시작 {line}줄, {m.group(2).count(chr(10))}줄)")
            else:
                ok = False
                msg = (res.stderr.strip().splitlines() or ["(메시지 없음)"])[:4]
                print(f"FAIL script #{i} (시작 {line}줄): " + " | ".join(msg))
    return ok


def check_marks(text: str) -> bool:
    head = HEAD_RE.match(text)
    if not head:
        print("FAIL 채움: 파일 맨 위에 채움 목록 주석이 없습니다")
        return False
    listed = Counter(MARK_RE.findall(head.group(1)))
    body = Counter(MARK_RE.findall(text[head.end():]))
    ok = True
    for n, c in sorted(listed.items()):
        if c > 1:
            ok = False
            print(f"FAIL 채움: 목록에 F{n} 이 {c}번 나옵니다")
    for n in sorted(set(listed) - set(body)):
        ok = False
        print(f"FAIL 채움: F{n} 은 목록에만 있고 본문에 없습니다")
    for n in sorted(set(body) - set(listed)):
        ok = False
        print(f"FAIL 채움: F{n} 은 본문에만 있고 목록에 없습니다")
    for n, c in sorted(body.items()):
        if c > 1:
            ok = False
            print(f"FAIL 채움: F{n} 이 본문에 {c}번 나옵니다")
    if ok:
        print(f"OK   채움 번호 {len(listed)}개 목록과 본문이 1:1")
    return ok


def check_filled(text: str) -> bool:
    head = HEAD_RE.match(text)
    start = head.end() if head else 0
    hits = sorted({text.count("\n", 0, start + m.start()) + 1 for m in PLACEHOLDER_RE.finditer(text[start:])})
    if not hits:
        print("OK   자리값 문구가 남아 있지 않습니다")
        return True
    shown = ", ".join(str(n) for n in hits[:10])
    print(f"FAIL 자리값: {len(hits)}줄이 남았습니다 (줄 번호 {shown}{' ...' if len(hits) > 10 else ''})")
    return False


def check_images(text: str) -> bool:
    head = HEAD_RE.match(text)
    start = head.end() if head else 0
    hits = [text.count("\n", 0, start + m.start()) + 1 for m in EMPTY_IMG_RE.finditer(text[start:])]
    if not hits:
        print("OK   빈 그림 칸이 남아 있지 않습니다")
        return True
    shown = ", ".join(str(n) for n in hits[:10])
    print(f"FAIL 그림 칸 {len(hits)}곳이 비어 있습니다 (줄 번호 {shown}{' ...' if len(hits) > 10 else ''}, 최대 10개)")
    return False


def is_text(v: object) -> bool:
    return isinstance(v, str) and bool(v.strip())


def check_code_item(where: str, code: object, errs: list[str], info: dict[str, list[str]]) -> None:
    if not isinstance(code, dict):
        errs.append(f"{where}: 코드 항목이 객체가 아닙니다")
        return
    if "none" in code:
        if not is_text(code["none"]):
            errs.append(f"{where}: none 이 빈 글입니다")
        return
    for key in ("path", "commit"):
        if not isinstance(code.get(key), str):
            errs.append(f"{where}: {key} 가 글이 아닙니다")
    lines = code.get("lines")
    if not isinstance(lines, list) or not lines:
        errs.append(f"{where}: lines 가 비어 있지 않은 배열이 아닙니다")
        return
    expl: set[int] = set()
    prev = 0
    for i, ln in enumerate(lines):
        n = ln.get("n") if isinstance(ln, dict) else None
        if not isinstance(ln, dict) or isinstance(n, bool) or not isinstance(n, int) or n < 1:
            errs.append(f"{where} lines[{i}]: 줄 항목은 n(1 이상의 정수)을 가진 객체여야 합니다")
            continue
        if n <= prev:
            errs.append(f"{where} L{n}: n 이 오름차순이 아니거나 겹칩니다")
        prev = max(prev, n)
        if "ref" not in ln:
            expl.add(n)
    decls = {
        ln["n"]: len(ln["src"]) - len(ln["src"].lstrip())
        for ln in lines
        if isinstance(ln, dict) and "ref" not in ln and isinstance(ln.get("n"), int) and not isinstance(ln["n"], bool)
        and isinstance(ln.get("src"), str) and ln["src"].lstrip().startswith(DECL_PREFIXES)
    }
    outer = {n for n, w in decls.items() if w == min(decls.values())}
    for ln in lines:
        n = ln.get("n") if isinstance(ln, dict) else None
        if isinstance(n, bool) or not isinstance(n, int) or n < 1:
            continue
        at = f"{where} L{n}"
        src = ln.get("src")
        if not isinstance(src, str):
            errs.append(f"{at}: src 가 글이 아닙니다")
        elif BAD_SRC_RE.match(src.strip()) or not src.strip() or src.strip().startswith(('"' * 3, "'" * 3)):
            info["bad"].append(at)
        if ln.get("mark") is not None and ln["mark"] not in MARKS:
            errs.append(f"{at}: mark 는 new · changed 중 하나여야 합니다")
        if "ref" in ln:
            if "what" in ln:
                errs.append(f"{at}: ref 와 what 이 같이 있습니다")
            if not isinstance(ln["ref"], int) or isinstance(ln["ref"], bool) or ln["ref"] not in expl:
                errs.append(f"{at}: ref {ln['ref']} 이 해설 줄이 아닙니다")
            if "aid" in ln:
                errs.append(f"{at}: aid 는 해설 줄에만 둘 수 있습니다")
            if "choice" in ln:
                errs.append(f"{at}: choice 는 해설 줄에만 둘 수 있습니다")
            continue
        for key in ("what", "how", "why"):
            if not is_text(ln.get(key)):
                errs.append(f"{at}: {key} 가 빈 글입니다")
        choice = ln.get("choice")
        if choice is not None and not isinstance(choice, dict):
            errs.append(f"{at}: choice 는 객체여야 합니다")
        elif choice is not None or n in outer:
            if choice is not None and n not in decls:
                errs.append(f"{at}: choice 는 class · def 줄에만 둘 수 있습니다")
            ch = choice or {}
            refs = ch.get("refs")
            if "why" in ch and not isinstance(ch["why"], str):
                errs.append(f"{at}: choice.why 가 글이 아닙니다")
            if refs is not None and not isinstance(refs, list):
                errs.append(f"{at}: choice.refs 는 배열이어야 합니다")
                refs = None
            if not is_text(ch.get("why")):
                info["choice"].append(f"{at}: 선택 근거(choice.why)가 없습니다")
            if not refs:
                info["choice"].append(f"{at}: 참고 자료(choice.refs)가 없습니다")
            for j, r in enumerate(refs or [], 1):
                if not isinstance(r, dict):
                    errs.append(f"{at}: choice.refs[{j}] 가 객체가 아닙니다")
                    continue
                for key in ("title", "url", "note", "check"):
                    if key in r and not isinstance(r[key], str):
                        errs.append(f"{at}: 참고 자료 {j} 의 {key} 가 글이 아닙니다")
                year = r.get("year")
                if year is not None and (isinstance(year, bool) or not isinstance(year, (str, int))):
                    errs.append(f"{at}: 참고 자료 {j} 의 year 는 글이나 정수여야 합니다")
                if not is_text(r.get("title")):
                    info["choice"].append(f"{at}: 참고 자료 {j} 의 제목이 없습니다")
                if not (isinstance(r.get("url"), str) and re.match(r"https?://", r["url"], re.IGNORECASE)):
                    info["choice"].append(f"{at}: 참고 자료 {j} 의 url 이 http(s) 주소가 아닙니다")
                if not is_text(r.get("check")):
                    info["choice"].append(f"{at}: 참고 자료 {j} 의 검증 기록(check)이 없습니다")
        aid = ln.get("aid")
        if aid is None:
            continue
        if not isinstance(aid, dict) or aid.get("kind") not in KINDS or not is_text(aid.get("topic")):
            errs.append(f"{at}: aid 는 kind(math · model)와 topic(빈 글 아님)이 필요합니다")
        elif not is_text(aid.get("img")):
            info["img"].append(at)


def check_plan_code(text: str, filled: bool) -> bool:
    found = [m for m in SCRIPT_RE.finditer(text) if attr_value(m.group(1), "id") == "plan-code" and attr_value(m.group(1), "type") == "application/json"]
    if len(found) != 1:
        print("FAIL plan-code: plan-code 칸이 없습니다" if not found else f"FAIL plan-code: plan-code 칸이 {len(found)}개입니다 (정확히 하나여야 합니다)")
        return False
    opens = [text.count("\n", 0, found[0].start(2) + m.start()) + 1 for m in re.finditer("<!--", found[0].group(2))]
    if opens:
        shown = ", ".join(str(n) for n in opens[:10])
        print(f"FAIL plan-code: 글 안에 <!-- 가 있습니다 ({len(opens)}곳, 파일 줄 번호 {shown}, 최대 10개). 페이지가 깨질 수 있으니 여는 꺾쇠를 JSON 유니코드 이스케이프(역슬래시 u003c)로 적으십시오")
    try:
        data = json.loads(found[0].group(2))
    except json.JSONDecodeError as err:
        print(f"FAIL plan-code: JSON 을 읽을 수 없습니다 ({text.count(chr(10), 0, found[0].start(2)) + err.lineno}줄: {err.msg})")
        return False
    blocks, diffs = (data.get("blocks"), data.get("diffs")) if isinstance(data, dict) else (None, None)
    if not isinstance(blocks, dict) or not isinstance(diffs, dict):
        print("FAIL plan-code: 최상위는 blocks 와 diffs 를 객체로 가져야 합니다")
        return False
    errs: list[str] = []
    info: dict[str, list[str]] = {"bad": [], "img": [], "choice": []}
    count = 0
    for bid, item in blocks.items():
        check_code_item(f"blocks.{bid}", item, errs, info)
        count += 1
    for cid, per in diffs.items():
        if not isinstance(per, dict):
            errs.append(f"diffs.{cid}: 객체가 아닙니다")
            continue
        for bid, pair in per.items():
            for side in ("before", "after"):
                if not isinstance(pair, dict) or side not in pair:
                    errs.append(f"diffs.{cid}.{bid}: {side} 가 없습니다")
                else:
                    check_code_item(f"diffs.{cid}.{bid}.{side}", pair[side], errs, info)
                    count += 1
    ok = not errs and not opens
    for e in errs[:10]:
        print(f"FAIL plan-code: {e}")
    if len(errs) > 10:
        print(f"FAIL plan-code: 그 밖에 {len(errs) - 10}건")
    if filled:
        ids = [i for m in SCRIPT_RE.finditer(text) if not has_src(m.group(1)) and attr_value(m.group(1), "type") != "application/json" for i in BLOCK_DECL_RE.findall(m.group(2))]
        if not ids:
            print("WARN plan-code: 구조도 블록 선언을 찾지 못해 블록 대조를 건너뜁니다")
        known = set(blocks) | {b for per in diffs.values() if isinstance(per, dict) for b in per}
        for bid in sorted(set(ids) - known):
            ok = False
            print(f"FAIL plan-code: 블록 {bid} 의 코드가 없습니다")
        if info["bad"]:
            ok = False
            print(f"FAIL plan-code: 빼야 할 줄(import · 빈 줄 · 주석)이 실렸습니다 ({len(info['bad'])}곳, 위치 {', '.join(info['bad'][:10])}, 최대 10개)")
        if info["img"]:
            ok = False
            print(f"FAIL plan-code: 이해용 그림 칸 {len(info['img'])}곳이 비어 있습니다 (위치 {', '.join(info['img'][:10])}, 최대 10개)")
        for e in info["choice"][:10]:
            ok = False
            print(f"FAIL plan-code: {e}")
        if len(info["choice"]) > 10:
            print(f"FAIL plan-code: 선택 근거 · 참고 자료 문제가 그 밖에 {len(info['choice']) - 10}건")
    if ok:
        print(f"OK   plan-code: 코드 항목 {count}개 구조 통과")
    return ok


def main() -> int:
    args = sys.argv[1:]
    filled = "--filled" in args
    paths = [a for a in args if a != "--filled"]
    if len(paths) != 1 or paths[0].startswith("--"):
        print("사용법: python3 -I check_template.py [--filled] <html 파일>")
        return 2
    node = shutil.which("node")
    if not node:
        print("node 가 없어 문법 검사를 할 수 없습니다. node 를 설치한 뒤 다시 실행하십시오.")
        return 2
    try:
        text = Path(paths[0]).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as err:
        print(f"파일을 읽을 수 없습니다: {paths[0]} ({err.__class__.__name__})")
        return 2
    results = [check_scripts(text, node), check_marks(text), check_plan_code(text, filled)]
    if filled:
        results.append(check_filled(text))
        results.append(check_images(text))
    print("PASS" if all(results) else "FAIL")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
