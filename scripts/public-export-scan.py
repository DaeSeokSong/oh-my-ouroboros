"""공개 전 범주 검사(읽기 전용, 2026-10-23 intent/2026-10-23-public-mirror-refresh.md).

`bash scripts/public-export.sh --stage-out <폴더>` 가 남긴 정제본에서 범주별 낱말을 찾아 범주 · 낱말 · 파일:줄을 보인다.
낱말은 비공개 설정 `config/public-export-scan.txt` 에서 읽는다. 이 스크립트는 공개 대상(scripts/)이라 회사 · 병원 ·
미공개 연구 이름 같은 낱말을 여기에 쓰면 그 자체가 공개된다.

설정 줄 형식: `<범주>||<정규식>||<건너뛸 정규식(선택)>`. 건너뛸 정규식은 «경로<TAB>줄» 에 대조한다
(경로 앞부분이나 «<your-…>» 같은 자리표시 글자를 건너뛰는 데 쓴다). 범주 이름이 «3» 으로 시작하거나 «비밀»·«secret» 을 담으면 줄 내용을 찍지 않는다.

종료 코드: 걸린 줄이 없으면 0, 있으면 1, 설정·정규식 오류면 2.
사용: python3 -I scripts/public-export-scan.py <정제본 폴더> [--config <설정 파일>] [--max N]
"""
import argparse
import pathlib
import re
import sys


def load(path):
    rules = []
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip() or raw.startswith("#"):
            continue
        parts = raw.split("||")
        if len(parts) != 3 or not parts[0].strip() or not parts[1]:
            raise ValueError(f"{path}:{n}: «범주||정규식||건너뛸 정규식» 꼴이 아닙니다")
        try:
            # WHY: re.ASCII: 한글이 \w 라서 «<서버이름>에서» 같은 줄에서 \b 가 안 걸렸다(2026-10-23 실측). 영문 낱말 경계를 ASCII 기준으로 본다.
            rx = re.compile(parts[1], re.ASCII)
            skip = re.compile(parts[2], re.ASCII) if parts[2] else None
        except re.error as e:
            raise ValueError(f"{path}:{n}: 정규식 오류 {e}") from e
        rules.append((parts[0].strip(), rx, skip))
    return rules


def scan(root, rules):
    files = sorted(p for p in root.rglob("*") if p.is_file() and ".git" not in p.relative_to(root).parts)
    texts = {}
    for p in files:
        try:
            texts[p] = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            texts[p] = []
    out = {}
    for cat, rx, skip in rules:
        hits = []
        for p in files:
            rel = str(p.relative_to(root))
            m = rx.search(rel)
            if m and not (skip and skip.search(f"{rel}\t")):
                hits.append((rel, 0, rel))
            for i, line in enumerate(texts[p], 1):
                m = rx.search(line)
                if not m or (skip and skip.search(f"{rel}\t{line}")):
                    continue
                ctx = line[max(0, m.start() - 30): m.end() + 30].strip()
                hits.append((rel, i, ctx))
        if hits:
            out.setdefault(cat, []).append((rx.pattern, hits))
    return out


def hide(cat):
    return cat.startswith("3") or "비밀" in cat or "secret" in cat.lower()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("stage")
    ap.add_argument("--config", default=str(pathlib.Path.home() / ".claude/config/public-export-scan.txt"))
    ap.add_argument("--max", type=int, default=6)
    a = ap.parse_args(argv)
    root = pathlib.Path(a.stage)
    if not root.is_dir():
        print(f"정제본 폴더가 없습니다: {root}", file=sys.stderr)
        return 2
    try:
        rules = load(pathlib.Path(a.config))
    except (OSError, ValueError) as e:
        print(f"설정 오류: {e}", file=sys.stderr)
        return 2
    found = scan(root, rules)
    total = 0
    for cat in dict.fromkeys(c for c, _, _ in rules):
        groups = found.get(cat, [])
        n = sum(len(h) for _, h in groups)
        total += n
        print(f"## {cat}: {n}줄")
        for pat, hits in groups:
            print(f"  [{pat}] {len(hits)}줄 · {len({h[0] for h in hits})}파일")
            for rel, i, ctx in hits[: a.max]:
                where = f"{rel} (경로 이름)" if i == 0 else f"{rel}:{i}"
                print(f"      {where}" + ("" if hide(cat) or i == 0 else f" … {ctx}"))
            if len(hits) > a.max:
                print(f"      … 외 {len(hits) - a.max}")
    print(f"검사 결과: {'발견 0건' if total == 0 else f'발견 {total}줄'}")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
