"""pdf_to_md.py — 논문 PDF → Markdown 변환 (paper-read Step 0-L 2 · Step 2.5 · researcher-B 표 추출 공용)

왜 파일인가 (2026-08-25 교차검증 5라운드): 종전엔 `python3 -c "... open(dst,'w') ..."` 인라인 코드였는데,
bash-write-check.sh 가 인라인 인터프리터의 파일 쓰기를 차단하게 되면서(4라운드 R10) 정본 절차와 훅이 충돌했다.
스크립트 파일 호출은 훅의 인라인 검사 대상이 아니며, 경로는 전부 argv 로 받아 문자열 삽입 주입도 없다.

사용:
  uv run python3 ~/.claude/scripts/pdf_to_md.py SRC.pdf DST.md            # markitdown → 실패 시 pdfplumber 폴백
  uv run python3 ~/.claude/scripts/pdf_to_md.py SRC.pdf --preview          # 앞 500자만 stdout (품질 판정)
  uv run python3 ~/.claude/scripts/pdf_to_md.py SRC.pdf --head 3000        # 서두 N자만 stdout (scout 판별용, 저장 없음)
  uv run python3 ~/.claude/scripts/pdf_to_md.py SRC.pdf --tables 3,5       # 지정 페이지 표를 stdout 으로 (pdfplumber)

종료 코드: 0 성공 / 2 인자 오류 / 3 변환 실패(두 엔진 모두) / 4 DST 가 papers/ 하위가 아님
"""
# REF: knowledge/harness/code-history/scripts__pdf_to_md.py.md
import os
import sys


def _die(msg, code):
    print(f"pdf_to_md: {msg}", file=sys.stderr)
    sys.exit(code)


def _check_dst(dst):
    # REF: skills/paper-read/SKILL.md § 경로·논문명 공통 안전 규칙 2)
    root = os.environ.get("PAPER_MEMORY_ROOT", "")
    if not root:
        _die("PAPER_MEMORY_ROOT 환경변수({MEMORY_ROOT}) 필요 — DST 접두 검사에 사용", 4)
    root_real = os.path.realpath(root)
    real = os.path.realpath(dst)
    home = os.path.realpath(os.path.expanduser("~"))
    # WHY: ~/grok-exchange/papers/ 로 쓰면 다음 grok 이 읽는다
    banned_roots = (
        os.path.join(home, "grok-exchange"), "/tmp", "/var/tmp", "/dev/shm", "/run",
        os.path.join(home, ".claude"),
    )
    for banned in banned_roots:
        b = os.path.realpath(banned) + "/"      # NEVER: 접두를 디렉터리 경계 없이 대조하지 않는다(`/tmp` 가 `/tmpfoo` 를 잡는다)
        if (root_real + "/").startswith(b) or (real + "/").startswith(b):
            _die(f"DST/루트가 금지 디렉터리 아래: {real}", 4)
    if os.path.islink(dst) or not real.startswith(root_real + "/papers/"):
        _die(f"DST 는 {root_real}/papers/ 하위 일반 파일이어야 함: {dst}", 4)
    if os.path.exists(real) and os.stat(real).st_nlink != 1:
        _die(f"DST 가 하드링크(nlink != 1): {real}", 4)
    return real


def convert_markitdown(src):
    from markitdown import MarkItDown  # noqa: WPS433
    return MarkItDown().convert(src).text_content


def convert_pdfplumber(src):
    import pdfplumber  # noqa: WPS433
    parts = []
    with pdfplumber.open(src) as pdf:
        for i, page in enumerate(pdf.pages):
            parts.append(f"\n\n<!-- page {i + 1} -->\n\n")
            parts.append(page.extract_text() or "")
    return "".join(parts)


def tables(src, pages):
    import pdfplumber  # noqa: WPS433
    with pdfplumber.open(src) as pdf:
        for p in pages:
            if p < 1 or p > len(pdf.pages):
                print(f"--- page {p}: 범위 밖 ---")
                continue
            for t in pdf.pages[p - 1].extract_tables():
                print(f"--- page {p} ---")
                for row in t:
                    print(" | ".join("" if c is None else str(c).replace("\n", " ") for c in row))


def main(argv):
    if len(argv) < 2:
        _die(__doc__, 2)
    src = argv[1]
    if not os.path.isfile(src) or os.path.islink(src) or not src.lower().endswith(".pdf"):
        _die(f"SRC 는 비링크 일반 .pdf 파일이어야 함: {src}", 2)
    if len(argv) >= 3 and argv[2] == "--tables":
        try:
            pages = [int(x) for x in (argv[3] if len(argv) > 3 else "1").split(",")]
        except ValueError:
            _die("--tables 는 쉼표 구분 페이지 번호", 2)
        tables(src, pages)
        return
    preview = len(argv) >= 3 and argv[2] == "--preview"
    head = 0
    if len(argv) >= 3 and argv[2] == "--head":
        try:
            head = int(argv[3]) if len(argv) > 3 else 3000
        except ValueError:
            _die("--head 는 정수", 2)
        preview = True
    dst = None if preview else (argv[2] if len(argv) >= 3 else None)
    if dst is None and not preview:
        _die("DST.md, --preview 또는 --head N 필요", 2)
    text, engine = None, None
    for name, fn in (("markitdown", convert_markitdown), ("pdfplumber", convert_pdfplumber)):
        try:
            text = fn(src)
            engine = name
            if text and text.strip():
                break
        except Exception as e:  # noqa: BLE001
            print(f"pdf_to_md: {name} 실패 — {e}", file=sys.stderr)
    if not text or not text.strip():
        _die("두 엔진 모두 텍스트를 얻지 못함 (스캔 PDF? pdf-inspector detect 로 확인)", 3)
    if preview:
        print(text[: (head or 500)])
        print(f"\n[engine={engine} chars={len(text)}]", file=sys.stderr)
        return
    real = _check_dst(dst)
    try:
        os.makedirs(os.path.dirname(real), exist_ok=True)   # NEVER: papers/ 접두 검사(_check_dst)를 통과하지 않은 경로에 부모를 만들지 않는다
        with open(real, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError as e:
        _die(f"저장 실패 — {e}", 3)
    print(f"[pdf_to_md] engine={engine} chars={len(text)} → {real}")


if __name__ == "__main__":
    main(sys.argv)
