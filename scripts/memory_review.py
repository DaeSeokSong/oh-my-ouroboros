"""메모리 · 지식 노트 정리 후보 보고기: 읽기 전용으로 «손볼 만한 노트» 네 종류를 표로 낸다.

무엇을: 메모리 폴더(기본 `projects/-home-user-workspace/memory/`, 하위 폴더 제외)와 지식 폴더
  (기본 `knowledge/`, 재귀)의 `.md` 노트를 읽어 네 후보를 낸다. 두 폴더의 `_archive/` 아래는 검사하지 않는다(보관분).
  1) 깨진 경로: 본문(코드펜스 밖)의 백틱 안 경로와 절대 경로 중 이 서버에 없는 것(노트당 5건까지)
  2) 색인 불일치: `MEMORY.md` · `INDEX.md` 의 `(파일.md)` 링크와 실제 파일의 차집합(양방향)
  3) 중복 후보: 같은 폴더 안에서 frontmatter name 동일 · 파일 이름 토큰 Jaccard 0.6 이상 · description difflib 유사도
     0.85 이상인 쌍(점수 내림차순 50쌍). 파일 이름 비교 전에 날짜 · 번호 토큰(숫자만 · 한 글자 + 숫자)을 떼고, 그런 토큰만
     다른 쌍은 «시리즈» 로 따로 세어 기본 표에서 접는다(`--show-series` 로 펼침). 메모리 대 지식은 name 이 같거나 날짜 꼬리를
     뗀 파일 이름이 같은 쌍만 «폴더 간» 으로 본다(이관 뒤 남은 사본 찾기, 유사도 비교는 폴더 안에서만).
  4) 오래된 상태 노트: `type: project` 이고 날짜(frontmatter modified · updated · date → 파일 이름 꼬리 → mtime)가
     `--stale-days`(1 이상, 기본 60)보다 오래된 노트. 이름이 `todo-` 로 시작하면 따로 표시한다.
  종료 코드는 후보 유무와 무관하게 0, 사용 오류(폴더 없음 · `--stale-days` 0 이하 · 마커 경로가 심볼릭 링크)는 2다.
  `--json` 은 같은 내용을 JSON 으로 낸다.
쓰는 파일: 기본 실행은 아무 파일도 쓰지 않는다. 정리가 실제로 끝났을 때만 `--touch-marker` 가
  `_usage/memory-review-last`(빈 파일)의 mtime 을 갱신한다(30일 주기의 기준 시각, `_usage` · 마커가 링크면 거부).
NEVER: 노트를 자동 수정 · 삭제하지 않는다(파일 모양만 보는 기계 추정이다).
싣는 것: 파일 이름 · name · 문제 경로 · 수치만 싣는다. 모든 문자열(파일 이름 · 폴더 이름 포함)은
  제어 문자 · 개행을 지우고 120자로 자르며 표 칸의 `|` 는 이스케이프한다(파일 이름에 개행 · 지시문을 심은 노트가 표를 깨거나
  보고를 읽는 모델을 속이는 길을 막는다). description 은 60자로 자르고, 경로 칸의 마지막 이름과 description 안의 20자 이상
  영숫자 · `-` · `_` 토큰(숫자 포함. `sk-…` · 32자 hex 꼴)은 `…` 로 가린다(폴더 이름 · 확장자 있는 파일 이름은 그대로).
읽기 안전: 5MB 넘는 파일 · 일반 파일이 아닌 것(FIFO · 장치)은 열지 않고 «읽지 못함» 에 넣고, 열 때도 O_NOFOLLOW · O_NONBLOCK
  으로 연 뒤 fstat 로 다시 확인한다. 심볼릭 링크는 따라가지 않는다. 정규식은 입력이 병리적이어도 선형이 되게 썼다: 링크는
  `find` 로 `](` 뒤 300자 안의 `)` 만 보고 한 줄이 2,000자를 넘으면 그 줄을 건너뛴다.
비용 상한: 노트당 경로 검사 200 토큰 · 전체 20,000 토큰(넘으면 요약에 «경로 검사 상한 도달»), 중복 비교 20만 쌍 또는
  15초(넘으면 «중복 판정 상한 도달» · «중복 판정 시간 상한 도달»). `/proc/mounts` 의 nfs · cifs · smb · fuse 계열 마운트
  지점 아래 경로는 `lstat` 이 서버 장애 때 멈출 수 있어 검사하지 않고 «네트워크 마운트(검사 안 함)» 으로 따로 센다
  (이 서버의 `/data` 은 NFS hard 마운트). 글자만 보면 마운트 밖인 `/mnt/data/…` 같은 링크 경로와 `rules/../../..`
  꼴도 막으려고, `..` 를 먼저 접고 구성요소를 앞에서부터 하나씩 `lstat` 하며 링크를 만나면(최대 8번) `readlink` 로 푼
  목적지(상대 링크는 링크 자리 기준)가 마운트 아래인지 그 자리에서 본다. 권한 없는 폴더는 건너뛴다.
  `--touch-marker` 는 마커가 이미 있는데 일반 파일이 아니면(FIFO · 폴더 · 링크) 열지 않고 거부한다. 마커 하드 링크는 막지 않는다.
깨진 경로의 건너뛰기 규칙: URL · `<…>` 자리표시 · glob(`* ? { }`) · `$` 변수 · `…` 줄임 · 한 낱말 명령어 · 확장자도 `/` 도
  없는 토큰 · 한 구성요소짜리 `/명령` 은 검사하지 않는다. 여기에 더해:
  슬래시 없는 토큰은 `.md` 이름만(규칙 · 에이전트 · 의뢰서 폴더에서도 찾음), 슬래시가 있는 상대 경로는 첫 구성요소가
  하네스 홈의 실제 항목일 때만 보며 하네스 홈 · 노트 폴더 · 하네스 홈의 상위 폴더 · 그 아래 세 층까지의 git 저장소 뿌리
  (`.git` 이 있는 폴더, 최대 200개, 한 번만 계산)들 아래에서 찾는다. 절대 경로는 첫 구성요소가 이 서버 `/` 에 있을 때만
  (`/v1/models` · `/wiki/api` 같은 URL 경로 제외, `/proc` `/sys` `/dev` 제외), `.scratch/` 와 `jobs/*/tmp/` 는
  사라지는 것이 정상이라 제외한다. 다른 서버 전용 경로일 수 있어 판정 이름은 «없음(이 서버 기준)» 이다.
  놓치는 것: 슬래시 없는 스크립트 이름(`xxx.py`)은 임시 스크립트 이름이 대부분이라 일부러 검사하지 않는다(미탐 쪽을 택함).
  가림은 경로의 마지막 이름과 description 에만 한다. 경로 중간 토큰과 확장자 있는 이름의 키 꼴 문자열은 과잉 가림을 피하려고 그대로 둔다.
색인: «파일만 있음» 은 색인이 직접 또는 허브 노트를 거쳐(1단계) 링크하지 않는 파일만 센다.
REF: knowledge/harness/code-history/scripts__memory_review.py.md
"""

from __future__ import annotations

import argparse
import datetime as dt
import difflib
import json
import os
import re
import stat
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

HARNESS_HOME = Path(__file__).resolve().parent.parent
PROC_MOUNTS = "/proc/mounts"
NET_FSTYPES = ("nfs", "cifs", "smb", "fuse")
MAX_BYTES = 5 * 1024 * 1024
SKIP_NAMES = frozenset({"INDEX.md", "MEMORY.md", "README.md"})
JACCARD_MIN = 0.6
DESC_RATIO_MIN = 0.85
MAX_PAIRS = 50
MAX_COMPARISONS = 200_000
DUP_TIME_BUDGET = 15.0
MAX_LINKS = 8
MAX_PATHS_PER_NOTE = 5
NOTE_TOKEN_CAP = 200
TOTAL_CHECK_CAP = 20_000
MAX_REPO_ROOTS = 200
MAX_DIRS_VISITED = 2000
REPO_DEPTH = 3
LINE_MAX = 2000
LINK_MAX = 300
TOKEN_MAX = 300
DESC_CUT = 60
FILE_EXTS = frozenset({
    "md", "py", "sh", "json", "jsonl", "tsv", "csv", "txt", "yaml", "yml", "toml", "ini", "cfg", "env",
    "html", "tex", "pdf", "png", "jpg", "jpeg", "ckpt", "pt", "log", "ipynb", "service", "timer", "bib", "lock",
})
FM_KEYS = re.compile(r"^\s*(name|description|title|type|date|modified|updated):(.*)$")
DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
TICKS = re.compile(r"`([^`\n]+)`")
ABS_PLAIN = re.compile(r"(?<![\w/.:~$-])(~?/[\w.\-@+]+(?:/[\w.\-@+]+)+/?)")
PATH_CHARS = re.compile(r"~?[\w.\-@+/]+")
SECRET_RUN = re.compile(r"(?<![A-Za-z0-9_-])(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]{20,}(?![A-Za-z0-9_-])")
NUM_TOKEN = re.compile(r"\d+|[a-z]\d+")
DATE_TAIL = re.compile(r"(-\d{4}-\d{2}-\d{2}|-\d{4})$")
PSEUDO_ROOTS = frozenset({"proc", "sys", "dev"})
BAD_CHARS = set("<>*?{}…$|=\\[]")


@dataclass
class Note:
    kind: str
    rel: str
    path: Path
    group: str
    meta: dict = field(default_factory=dict)
    body: str = ""
    mtime: float = 0.0
    links: frozenset = frozenset()

    @property
    def label(self) -> str:
        return clean(f"{self.kind}/{self.rel}")


def clean(s: str, n: int = 120) -> str:
    s = "".join(ch if ch.isprintable() else " " for ch in s.replace("\n", " "))
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 3] + "..."


def mask_text(s: str) -> str:
    return SECRET_RUN.sub("…", s)


def mask_path(p: str) -> str:
    head, sep, last = p.rpartition("/")
    return p if "." in last else head + sep + mask_text(last)


def split_frontmatter(text: str) -> tuple[dict, str, bool]:
    if not text.startswith("---"):
        return {}, text, False
    lines = text.split("\n")
    end = next((i for i in range(1, min(len(lines), 200)) if lines[i].strip() == "---"), None)
    if end is None:
        return {}, text, True
    meta: dict = {}
    for ln in lines[1:end]:
        m = FM_KEYS.match(ln)
        if m and m.group(1) not in meta:
            meta[m.group(1)] = m.group(2).strip().strip("\"'")
    return meta, "\n".join(lines[end + 1:]), False


def strip_fences(body: str) -> str:
    out, fenced = [], False
    for ln in body.split("\n"):
        if ln.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if not fenced:
            out.append(ln)
    return "\n".join(out)


def extract_links(text: str) -> set[str]:
    out: set[str] = set()
    for ln in text.split("\n"):
        if len(ln) > LINE_MAX:
            continue
        i = ln.find("](")
        while i >= 0:
            j = ln.find(")", i + 2, i + 2 + LINK_MAX + 1)
            if j > 0:
                target = ln[i + 2:j].split("#", 1)[0]
                if target and not any(c.isspace() for c in target):
                    out.add(target)
            i = ln.find("](", i + 2)
    return out


def read_text(path: Path) -> tuple[str | None, str]:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except OSError as e:
        return None, f"읽기 오류({type(e).__name__})"
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return None, "일반 파일 아님"
        if st.st_size > MAX_BYTES:
            return None, "5MB 초과"
        with os.fdopen(fd, "rb", closefd=False) as f:
            data = f.read(MAX_BYTES + 1)
    except OSError as e:
        return None, f"읽기 오류({type(e).__name__})"
    finally:
        os.close(fd)
    if len(data) > MAX_BYTES:
        return None, "5MB 초과"
    try:
        return data.decode("utf-8"), ""
    except UnicodeDecodeError:
        return None, "UTF-8 아님"


def list_md(root: Path, recursive: bool, unreadable: list) -> list[tuple[Path, str]]:
    found: list[tuple[Path, str]] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        base = Path(dirpath)
        keep = []
        for d in sorted(dirnames):
            if d == "_archive":
                continue
            if (base / d).is_symlink():
                unreadable.append({"note": clean(str((base / d).relative_to(root)) + "/"), "reason": "심볼릭 링크 폴더(따라가지 않음)"})
            elif recursive:
                keep.append(d)
        dirnames[:] = keep
        for f in sorted(filenames):
            if f.endswith(".md"):
                found.append((base / f, str((base / f).relative_to(root))))
        if not recursive:
            break
    return found


def load_notes(kind: str, root: Path, recursive: bool, unreadable: list) -> tuple[list[Note], dict]:
    notes: list[Note] = []
    indexes: dict = {}
    for path, rel in list_md(root, recursive, unreadable):
        label = clean(f"{kind}/{rel}")
        try:
            mode = os.lstat(path).st_mode
        except OSError as e:
            unreadable.append({"note": label, "reason": f"읽기 오류({type(e).__name__})"})
            continue
        if stat.S_ISLNK(mode):
            unreadable.append({"note": label, "reason": "심볼릭 링크(따라가지 않음)"})
            continue
        if not stat.S_ISREG(mode):
            unreadable.append({"note": label, "reason": "일반 파일 아님"})
            continue
        text, why = read_text(path)
        if text is None:
            unreadable.append({"note": label, "reason": why})
            continue
        if path.name in SKIP_NAMES:
            if path.name != "README.md":
                indexes[path] = (kind, extract_links(text))
            continue
        meta, body, broken = split_frontmatter(text)
        if broken:
            unreadable.append({"note": label, "reason": "frontmatter 닫힘 없음(본문만 검사)"})
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        notes.append(Note(kind, rel, path, f"{kind}/{os.path.dirname(rel)}", meta, strip_fences(body), mtime,
                          frozenset(extract_links(body))))
    return notes, indexes


def load_net_mounts() -> tuple[str, ...]:
    try:
        text = Path(PROC_MOUNTS).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ()
    out = []
    for ln in text.splitlines():
        f = ln.split()
        if len(f) >= 3 and f[2].startswith(NET_FSTYPES):
            mp = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), f[1]).rstrip("/")
            if mp:
                out.append(mp)
    return tuple(out)


def under_mount(p: str, mounts: tuple[str, ...]) -> bool:
    return any(p == m or p.startswith(m + "/") for m in mounts)


def is_real_dir(p: Path) -> bool:
    try:
        return stat.S_ISDIR(os.lstat(p).st_mode)
    except OSError:
        return False


def find_repo_roots(home: Path, mounts: tuple[str, ...]) -> list[Path]:
    base = home.parent
    roots: list[Path] = [base]
    seen = 0
    frontier = [base]
    for _ in range(REPO_DEPTH):
        nxt: list[Path] = []
        for d in frontier:
            try:
                names = sorted(os.listdir(d))
            except OSError:
                continue
            for name in names:
                p = d / name
                if name.startswith(".") or p == home or under_mount(str(p), mounts):
                    continue
                seen += 1
                if seen > MAX_DIRS_VISITED:
                    return roots
                if not is_real_dir(p):
                    continue
                if os.path.lexists(p / ".git"):
                    roots.append(p)
                    roots += project_subdirs(p, mounts)
                    if len(roots) >= MAX_REPO_ROOTS:
                        return roots[:MAX_REPO_ROOTS]
                else:
                    nxt.append(p)
        frontier = nxt
    return roots


def project_subdirs(repo: Path, mounts: tuple[str, ...]) -> list[Path]:
    try:
        names = sorted(os.listdir(repo))[:MAX_DIRS_VISITED]
    except OSError:
        return []
    out = []
    for name in names:
        p = repo / name
        if (not name.startswith(".") and not under_mount(str(p), mounts) and is_real_dir(p)
                and (os.path.lexists(p / "CLAUDE.md") or os.path.lexists(p / "pyproject.toml"))):
            out.append(p)
    return out


class PathChecker:
    def __init__(self, home: Path):
        self.home = home
        self.mounts = load_net_mounts()
        self.roots = find_repo_roots(home, self.mounts)
        try:
            self.top_level = frozenset(os.listdir(home))
        except OSError:
            self.top_level = frozenset()
        try:
            self.format_dirs = sorted(p for p in (home / "doc-formats" / n for n in os.listdir(home / "doc-formats")) if is_real_dir(p))
        except OSError:
            self.format_dirs = []
        self._memo: dict[str, tuple[str, str]] = {}
        self.checked = 0
        self.capped = False
        self.note_capped = 0
        self.net_skipped = 0

    def classify(self, tok: str) -> str | None:
        if not tok or len(tok) > TOKEN_MAX or "://" in tok or "..." in tok or tok.startswith("-"):
            return None
        if any(c in BAD_CHARS for c in tok) or not PATH_CHARS.fullmatch(tok):
            return None
        parts = [p for p in tok.split("/") if p]
        if not parts:
            return None
        ext = parts[-1].rsplit(".", 1)[-1].lower() if "." in parts[-1] else ""
        if ".scratch" in parts or ("jobs" in parts and "tmp" in parts[parts.index("jobs"):]):
            return None
        if "/" not in tok:
            return "check" if ext == "md" and not tok.startswith(".") else None
        if tok.startswith("/"):
            if parts[0] in PSEUDO_ROOTS or not (len(parts) >= 2 or ext in FILE_EXTS):
                return None
            if under_mount(os.path.normpath(tok), self.mounts):
                return "net"
            return "check" if os.path.lexists("/" + parts[0]) else None
        if tok.startswith("~/"):
            return "check" if len(parts) >= 2 or ext in FILE_EXTS else None
        return "check" if parts[0] in self.top_level else None

    def exists(self, tok: str, note_dir: Path) -> bool | None:
        if tok.startswith("~/.claude/") or tok == "~/.claude":
            cands = [self.home / tok[len("~/.claude/"):]]
        elif tok.startswith("~/"):
            cands = [Path.home() / tok[2:]]
        elif tok.startswith("/"):
            cands = [Path(tok)]
        else:
            cands = [self.home / tok, note_dir / tok, *(r / tok for r in self.roots)]
            if "/" not in tok:
                cands += [self.home / d / tok for d in ("rules", "rules-lazy", "agents", "intent")]
                cands += [d / tok for d in self.format_dirs]
        saw_net = False
        for c in cands:
            r = self.probe(str(c))
            if r == "yes":
                return True
            saw_net = saw_net or r == "net"
        return None if saw_net else False

    def lstat_kind(self, p: str) -> tuple[str, str]:
        hit = self._memo.get(p)
        if hit is None:
            try:
                hit = ("link", os.readlink(p)) if stat.S_ISLNK(os.lstat(p).st_mode) else ("ok", "")
            except OSError:
                hit = ("none", "")
            self._memo[p] = hit
        return hit

    def probe(self, p: str) -> str:
        path = os.path.abspath(p)
        if under_mount(path, self.mounts):
            return "net"
        rest = [c for c in path.split("/") if c]
        cur, links = "/", 0
        while rest:
            nxt = os.path.join(cur, rest.pop(0))
            if under_mount(nxt, self.mounts):
                return "net"
            kind, target = self.lstat_kind(nxt)
            if kind == "none":
                return "no"
            if kind == "ok":
                cur = nxt
                continue
            links += 1
            if links > MAX_LINKS:
                return "no"
            dest = os.path.normpath(os.path.join(cur, target))
            if under_mount(dest, self.mounts):
                return "net"
            if not rest:
                return "yes"
            rest = [c for c in dest.split("/") if c] + rest
            cur = "/"
        return "yes"

    def scan(self, note: Note) -> tuple[list[str], int]:
        tokens: list[str] = []
        for span in TICKS.findall(note.body):
            tokens.extend(span.split())
        tokens.extend(ABS_PLAIN.findall(TICKS.sub(" ", note.body)))
        missing: list[str] = []
        net: set[str] = set()
        seen_tokens: set[str] = set()
        used = 0
        for raw in tokens:
            if len(raw) > TOKEN_MAX:
                continue
            tok = re.sub(r":\d+(?:-\d+)?$", "", raw.strip("\"'(),;:").rstrip(".,;:)")).split("#", 1)[0]
            if tok in seen_tokens:
                continue
            seen_tokens.add(tok)
            kind = self.classify(tok)
            if kind is None:
                continue
            if kind == "net":
                net.add(tok)
                continue
            if used >= NOTE_TOKEN_CAP:
                self.note_capped += 1
                break
            if self.checked >= TOTAL_CHECK_CAP:
                self.capped = True
                break
            used += 1
            self.checked += 1
            ok = self.exists(tok, note.path.parent)
            if ok is None:
                net.add(tok)
            elif not ok:
                missing.append(tok)
        self.net_skipped += len(net)
        return [clean(mask_path(t)) for t in missing[:MAX_PATHS_PER_NOTE]], len(missing)


def index_mismatches(indexes: dict, notes: list[Note]) -> list[dict]:
    by_dir: dict = {}
    for n in notes:
        by_dir.setdefault(n.path.parent, {})[n.path.name] = n
    out = []
    for ipath, (kind, links) in sorted(indexes.items()):
        files = by_dir.get(ipath.parent, {})
        linked = {x for x in links if x.endswith(".md") and "/" not in x and "://" not in x and x not in SKIP_NAMES}
        # WHY: MEMORY.md 는 줄 수 상한(160줄) 때문에 «목차 노트(허브)» 한 줄로 묶으므로 허브가 링크한 노트도 색인된 것으로 본다(1단계).
        reached = set(linked)
        for name in linked & files.keys():
            reached |= files[name].links
        tag = clean(f"{kind}/{ipath.name}@{clean(ipath.parent.name, 60)}")
        out += [{"index": tag, "kind": "색인에만 있음", "file": clean(x)} for x in sorted(linked - files.keys())]
        out += [{"index": tag, "kind": "파일만 있음", "file": clean(x)} for x in sorted(files.keys() - reached)]
    return out


def name_tokens(note: Note) -> tuple[frozenset, frozenset]:
    raw = frozenset(t for t in re.split(r"[-_]", note.path.stem.lower()) if t)
    return raw, frozenset(t for t in raw if not NUM_TOKEN.fullmatch(t))


def description_of(note: Note) -> str:
    return (note.meta.get("description") or note.meta.get("title") or "")[:300]


def pair_row(a: Note, b: Note, reasons: list, score: float, **extra) -> dict:
    return {"a": a.label, "b": b.label, "reasons": reasons, "score": round(score, 3),
            "desc_a": clean(mask_text(description_of(a)), DESC_CUT), **extra}


def find_cross_pairs(notes: list[Note]) -> list[dict]:
    mem = [n for n in notes if n.kind == "memory"]
    know = [n for n in notes if n.kind == "knowledge"]
    by_name: dict = {}
    by_stem: dict = {}
    for k in know:
        if k.meta.get("name"):
            by_name.setdefault(k.meta["name"], []).append(k)
        by_stem.setdefault(DATE_TAIL.sub("", k.path.stem.lower()), []).append(k)
    found: dict = {}
    for m in mem:
        for k in by_name.get(m.meta.get("name"), []):
            found.setdefault((id(m), id(k)), (m, k, []))[2].append("폴더 간 name 동일")
        for k in by_stem.get(DATE_TAIL.sub("", m.path.stem.lower()), []):
            found.setdefault((id(m), id(k)), (m, k, []))[2].append("폴더 간 파일 이름 동일(날짜 꼬리 뗌)")
    return [pair_row(m, k, reasons, 1.0, cross=True, series=False) for m, k, reasons in found.values()]


def find_duplicates(notes: list[Note]) -> dict:
    groups: dict = {}
    for n in notes:
        groups.setdefault(n.group, []).append(n)
    pairs: list[dict] = []
    series: list[dict] = []
    comparisons = 0
    capped = timed_out = False
    deadline = time.monotonic() + DUP_TIME_BUDGET
    for members in groups.values():
        toks = {id(n): name_tokens(n) for n in members}
        descs = {id(n): description_of(n) for n in members}
        for i, a in enumerate(members):
            if capped or timed_out:
                break
            for b in members[i + 1:]:
                comparisons += 1
                if comparisons > MAX_COMPARISONS:
                    capped = True
                    break
                if time.monotonic() > deadline:
                    timed_out = True
                    break
                reasons, score, is_series = [], 0.0, False
                na, nb = a.meta.get("name"), b.meta.get("name")
                if na and na == nb:
                    reasons.append("name 동일")
                    score = 1.0
                (ra, sa), (rb, sb) = toks[id(a)], toks[id(b)]
                jac = len(sa & sb) / len(sa | sb) if sa and sb else 0.0
                if jac >= JACCARD_MIN:
                    if sa == sb and ra != rb:
                        is_series = True
                    else:
                        reasons.append(f"파일 이름 Jaccard {jac:.2f}")
                        score = max(score, jac)
                da, db = descs[id(a)], descs[id(b)]
                if da and db:
                    sm = difflib.SequenceMatcher(None, da, db, autojunk=False)
                    if sm.real_quick_ratio() >= DESC_RATIO_MIN and sm.quick_ratio() >= DESC_RATIO_MIN:
                        r = sm.ratio()
                        if r >= DESC_RATIO_MIN:
                            reasons.append(f"description 유사도 {r:.2f}")
                            score = max(score, r)
                if reasons:
                    pairs.append(pair_row(a, b, reasons, score, cross=False, series=False))
                elif is_series:
                    series.append(pair_row(a, b, ["시리즈(번호 · 날짜만 다름)"], 1.0, cross=False, series=True))
    pairs += find_cross_pairs(notes)
    pairs.sort(key=lambda p: (-p["score"], p["a"], p["b"]))
    series.sort(key=lambda p: (p["a"], p["b"]))
    return {"pairs": pairs[:MAX_PAIRS], "total": len(pairs), "series": series[:MAX_PAIRS],
            "series_total": len(series), "capped": capped, "timed_out": timed_out}


def note_date(note: Note, today: dt.date) -> tuple[dt.date, str]:
    for key in ("modified", "updated", "date"):
        m = DATE_RE.search(note.meta.get(key, ""))
        if m:
            try:
                return dt.date(*map(int, m.groups())), f"frontmatter {key}"
            except ValueError:
                pass
    stem = note.path.stem
    m = re.search(r"-(\d{4})-(\d{2})-(\d{2})$", stem)
    try:
        if m:
            return dt.date(*map(int, m.groups())), "파일 이름"
        m = re.search(r"-(\d{2})(\d{2})$", stem)
        if m:
            d = dt.date(today.year, int(m.group(1)), int(m.group(2)))
            return (d if d <= today else d.replace(year=d.year - 1)), "파일 이름"
    except ValueError:
        pass
    return dt.date.fromtimestamp(note.mtime), "mtime"


def find_stale(notes: list[Note], days: int, today: dt.date) -> list[dict]:
    out = []
    for n in notes:
        if n.meta.get("type") != "project":
            continue
        d, src = note_date(n, today)
        age = (today - d).days
        if age > days:
            out.append({"note": n.label, "date": d.isoformat(), "source": src, "age_days": age,
                        "todo": n.path.name.startswith("todo-")})
    out.sort(key=lambda r: (-r["age_days"], r["note"]))
    return out


def build_report(memory_dir: Path | None, knowledge_dir: Path | None, home: Path, stale_days: int,
                 today: dt.date | None = None, show_series: bool = False) -> dict:
    today = today or dt.date.today()
    unreadable: list = []
    notes: list[Note] = []
    indexes: dict = {}
    for kind, root, rec in (("memory", memory_dir, False), ("knowledge", knowledge_dir, True)):
        if root is not None:
            n, i = load_notes(kind, root, rec, unreadable)
            notes += n
            indexes.update(i)
    checker = PathChecker(home)
    broken = []
    for n in notes:
        shown, total = checker.scan(n)
        if shown:
            broken.append({"note": n.label, "paths": shown, "total": total})
    dup = find_duplicates(notes)
    return {
        "today": today.isoformat(), "stale_days": stale_days,
        "counts": {"memory": sum(n.kind == "memory" for n in notes), "knowledge": sum(n.kind == "knowledge" for n in notes)},
        "broken_paths": broken,
        "index_mismatch": index_mismatches(indexes, notes),
        "duplicates": dup["pairs"], "duplicates_total": dup["total"],
        "series_total": dup["series_total"], "series": dup["series"] if show_series else [],
        "stale": find_stale(notes, stale_days, today),
        "unreadable": unreadable,
        "limits": {"path_check_capped": checker.capped, "path_note_capped_notes": checker.note_capped,
                   "network_skipped": checker.net_skipped, "pair_capped": dup["capped"], "pair_timed_out": dup["timed_out"],
                   "paths_checked": checker.checked, "repo_roots": len(checker.roots)},
    }


def cell(s: str) -> str:
    return s.replace("|", "\\|")


def pair_table(title: str, rows: list[dict]) -> list[str]:
    lines = ["", title, "", "| 노트 A | 노트 B | 폴더 간 | 근거 | 점수 | A 설명(60자) |", "|---|---|---|---|---|---|"]
    lines += [f"| {cell(p['a'])} | {cell(p['b'])} | {'예' if p['cross'] else ''} | {cell(' · '.join(p['reasons']))} "
              f"| {p['score']:.2f} | {cell(p['desc_a'])} |" for p in rows]
    return lines


def render_markdown(r: dict) -> str:
    c, lim = r["counts"], r["limits"]
    nb = sum(b["total"] for b in r["broken_paths"])
    todo = sum(s["todo"] for s in r["stale"])
    flags = [f for f, hit in (("경로 검사 상한 도달", lim["path_check_capped"]), ("중복 판정 상한 도달", lim["pair_capped"]),
                              ("중복 판정 시간 상한 도달", lim["pair_timed_out"])) if hit]
    summary = (
        f"후보 요약({r['today']} 기준, 메모리 {c['memory']}개 · 지식 {c['knowledge']}개): "
        f"깨진 경로 노트 {len(r['broken_paths'])}개(경로 {nb}건) · 색인 불일치 {len(r['index_mismatch'])}건 · "
        f"중복 후보 {r['duplicates_total']}쌍(표시 {len(r['duplicates'])}) · 시리즈 {r['series_total']}쌍(접음, --show-series) · "
        f"오래된 상태 노트 {len(r['stale'])}개(todo {todo}개, {r['stale_days']}일 초과) · 읽지 못함 {len(r['unreadable'])}개 · "
        f"네트워크 마운트(검사 안 함) {lim['network_skipped']}건" + "".join(f" · {f}" for f in flags)
    )
    lines = [summary, "", "## 1. 깨진 경로 (없음, 이 서버 기준)", "", "| 노트 | 없는 경로 | 건수 |", "|---|---|---|"]
    lines += [f"| {cell(b['note'])} | {cell(' · '.join('`' + p + '`' for p in b['paths']))} | {b['total']} |" for b in r["broken_paths"]]
    lines += ["", "## 2. 색인 불일치", "", "| 색인@폴더 | 종류 | 파일 |", "|---|---|---|"]
    lines += [f"| {cell(m['index'])} | {m['kind']} | {cell(m['file'])} |" for m in r["index_mismatch"]]
    lines += pair_table("## 3. 중복 후보", r["duplicates"])
    if r["series"]:
        lines += pair_table("## 3-1. 시리즈(번호 · 날짜만 다른 짝)", r["series"])
    lines += ["", "## 4. 오래된 상태 노트", "", "| 노트 | 날짜(출처) | 경과일 | todo |", "|---|---|---|---|"]
    lines += [f"| {cell(s['note'])} | {s['date']}({s['source']}) | {s['age_days']} | {'예' if s['todo'] else ''} |" for s in r["stale"]]
    if r["unreadable"]:
        lines += ["", "## 읽지 못함", "", "| 노트 | 사유 |", "|---|---|"]
        lines += [f"| {cell(u['note'])} | {u['reason']} |" for u in r["unreadable"]]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="메모리 · 지식 노트 정리 후보 보고(읽기 전용)")
    ap.add_argument("--home", type=Path, default=HARNESS_HOME, help="하네스 홈(상대 경로 해석 · 마커 위치)")
    ap.add_argument("--memory-dir", type=Path, default=None)
    ap.add_argument("--knowledge-dir", type=Path, default=None)
    ap.add_argument("--stale-days", type=int, default=60, help="1 이상")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--show-series", action="store_true", help="번호 · 날짜만 다른 시리즈 쌍도 표시")
    ap.add_argument("--touch-marker", action="store_true", help="정리가 끝났을 때만: _usage/memory-review-last mtime 갱신")
    args = ap.parse_args(argv)
    home = args.home
    mem = args.memory_dir or home / "projects" / "-home-user-workspace" / "memory"
    know = args.knowledge_dir or home / "knowledge"
    if args.stale_days < 1:
        print("오류: --stale-days 는 1 이상이어야 합니다", file=sys.stderr)
        return 2
    for p in (home, mem, know):
        if not p.is_dir():
            print(f"오류: 폴더가 없습니다: {p}", file=sys.stderr)
            return 2
    usage = home / "_usage"
    marker = usage / "memory-review-last"
    if args.touch_marker:
        bad = os.path.realpath(usage) != os.path.join(os.path.realpath(home), "_usage")
        for p, want in ((usage, stat.S_ISDIR), (marker, stat.S_ISREG)):
            try:
                bad = bad or not want(os.lstat(p).st_mode)
            except FileNotFoundError:
                pass
            except OSError:
                bad = True
        if bad:
            print(f"오류: 마커 경로가 링크이거나 일반 파일이 아닙니다: {marker}", file=sys.stderr)
            return 2
    report = build_report(mem, know, home, args.stale_days, show_series=args.show_series)
    print(json.dumps(report, ensure_ascii=False, indent=1) if args.json else render_markdown(report))
    if args.touch_marker:
        try:
            usage.mkdir(parents=True, exist_ok=True)
            fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o644)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    print(f"오류: 마커가 일반 파일이 아닙니다: {marker}", file=sys.stderr)
                    return 2
                os.utime(fd)
            finally:
                os.close(fd)
        except OSError as e:
            print(f"오류: 마커를 갱신하지 못했습니다({type(e).__name__}): {marker}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
