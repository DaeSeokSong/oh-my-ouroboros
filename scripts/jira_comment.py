#!/usr/bin/env python3
# ruff: noqa: EXE001
"""Jira 댓글 공용 게시 스크립트 (REST v3, 표준 라이브러리만).

preview 는 형식 규칙 절을 그때 스킬 파일(skills/commit/SKILL.md)에서 읽어 화면에 찍고, 사용자가 본 미리보기와
같은 본문만 게시되게 한다(본문 해시 스탬프).
NEVER: 스탬프를 «사람이 승인했다»는 증거로 쓰지 않는다. «이 본문으로 preview 를 돌렸다»는 보장일 뿐이며,
  승인은 여전히 사용자에게 미리보기를 보이고 받아야 한다.

■ 안전 규약
  1) 자격증명은 `~/.atlassian_token`(1줄=이메일 / 2줄=토큰)만. 명령줄·출력·예외·파일에 쓰지 않는다.
  2) 수정은 notifyUsers=false, 수정 전 현재 ADF 를 백업한다.
  3) 이미지(media)가 든 댓글의 글자는 --patches 로만 고친다(텍스트 노드만 치환, media id 집합 불변).
     새 그림은 --figures 로만 넣는다(글자 블록·인라인 카드 불변, 그림만 추가). 이 경로만 이슈 첨부를 새로 올린다(외부 쓰기).
     그림 파일은 «그림 목록 JSON 이 있는 폴더 안»만 허용한다(절대 경로·..·밖을 가리키는 링크 거부; 민감 영상 PNG 유출 방지).
     올리는 첨부 이름은 <원래이름>-<sha256 앞 12자>.png 로 내용에 묶고(재사용도 그 이름+크기가 같을 때만), media alt 는 원래 이름이다.
     자리 문단은 최상위 또는 글머리 안 문단만, PNG 는 가로·세로 각 20000 이하, PUT 직전에 댓글을 다시 조회해 바뀌었으면 rc 3.
     이슈 파일 첨부는 attach 로만 한다(댓글을 건드리지 않음). 목록 폴더 안 파일만, csv·tsv·txt·json·pdf·png·jpg·jpeg 만,
     파일당 50MiB·합계 100MiB·한 번에 10개까지, 빈 파일 불가, 확장자와 머리 형식이 맞아야 한다.
     그림·첨부 목록 JSON 은 .scratch 아래 폴더에 둔다(폴더 안 제한이 민감 자료 폴더에 둔 목록으로 무력화되는 것을 막는다). 올라갈 이름은 <이름>-<sha256 앞 12자>.<확장자>,
     올린 뒤 첨부 목록을 다시 읽어 «이름+크기» 가 있는지 대조한다(rc 4). 첨부를 지우거나 바꾸는 기능은 없다.
     글 파일은 미리보기에 첫 줄(120자)·줄 수·열 수(json 은 키 이름)를 보이고 환자 식별 낱말이 있으면 경고한다(막지는 않음).
  4) 치환 앵커는 텍스트 노드에서 정확히 1회 일치할 때만 적용한다.
  5) 게시 뒤 재조회해 텍스트 블록 문자열·인라인 카드 수·media id 를 기계 대조한다.
  6) 첨부 내용 주소의 303 Location 은 서명된 미디어 주소다. 리다이렉트를 따라가지 않고(인증 머리글이 다른 호스트로 나가지
     않게) UUID 만 꺼내며, Location 문자열은 출력·기록·예외 문구에 넣지 않는다.

■ 표
머리 줄 `| a | b |` 바로 다음 줄이 `|---|---|`(콜론 허용·정렬은 무시)이면 표다. 이어지는 `|` 줄이 본문 행이고 셀 안 `\\|` 는 글자 `|` 다.
머리 행은 tableHeader, 나머지는 tableCell(각 칸=문단 1개, 글은 기존 인라인 처리). 본문 행의 열 수가 머리와 다르면 표로 바꾸지 않고
종전처럼 글 문단으로 두며 preview 가 경고한다. 게시 뒤 되읽기는 표 개수·표마다 행 수·행마다 셀 수를 먼저 대조한다.

■ 표 행 추가
치환 파일에 표 행 추가 항목
`{"table_anchor": "<표 첫 행 첫 칸 글>", "append_rows": [["칸1", "칸2"], ...]}` 을 글자 치환 항목과 섞어 둘 수 있다(한 항목에 두 종류 키 불가).
표는 첫 행 첫 칸 글자(앞뒤 공백 무시)가 table_anchor 와 정확히 같은 것 하나로 찾고(0개·2개 이상 rc 2), 병합 칸(colspan·rowspan > 1)이 든 표와
첫 행 칸 수와 다른 행은 rc 2 다. 행은 맨 아래에만 붙고 칸은 tableCell + 문단(기존 인라인 처리)이다. 보내기 전에 «붙인 행 말고는 구조·글자가
치환 목록이 바꾼 것 외에 불변» 인지(check_rows_only_added)와 media id 불변을 검사하고, 게시 뒤 되읽기의 표 구조 대조가 행 수 증가를 확인한다.

■ 종료 코드  0 성공 · 2 입력·형식 절·앵커 오류 · 3 스탬프 없음 · 4 게시 후 대조 실패 · 5 HTTP 오류

사용:
  # 1) 댓글 구조 보기 (읽기만)
  python3 ~/.claude/scripts/jira_comment.py get --issue ABC-972 --comment-id 10001 --save adf.json
  # 2) 미리보기 (형식 규칙 출력 + 스탬프 생성). 치환은 --patches 치환.json
  python3 ~/.claude/scripts/jira_comment.py preview --issue ABC-972 --body-file 본문.md
  # 3) 새 댓글 게시 (사용자 승인 뒤, 같은 본문 파일로)
  python3 ~/.claude/scripts/jira_comment.py post --issue ABC-972 --body-file 본문.md
  # 4) 기존 댓글 수정 (preview 때 --comment-id 도 같이 줘야 스탬프가 맞는다)
  python3 ~/.claude/scripts/jira_comment.py update --issue ABC-972 --comment-id 10001 --patches 치환.json
  # 5) 기존 댓글에 새 그림(PNG) 넣기. 그림.json = [{"anchor": "문단 첫머리 글귀", "file": "fig1.png"}, ...] (1~20개,
  #    file 은 그림.json 이 있는 폴더 안의 상대 경로만). preview 는 읽기만 하고, update 가 첨부를 올리고(같은 내용 이름·크기가 있으면 재사용)
  #    anchor 문단 바로 뒤에 mediaSingle 을 넣는다. preview 때 --comment-id 도 같이 줘야 한다.
  python3 ~/.claude/scripts/jira_comment.py preview --issue ABC-972 --comment-id 10001 --figures 그림.json
  python3 ~/.claude/scripts/jira_comment.py update --issue ABC-972 --comment-id 10001 --figures 그림.json
  # 6) 이슈에 일반 파일 첨부. 목록.json = [{"file": "a.csv"}, ...] (1~10개, 목록 폴더 안 상대 경로만). preview 는 첨부 목록 조회만
  #    하고 스탬프를 만들며, attach 는 사용자 승인 뒤 같은 목록으로 올린다(같은 이름·크기가 있으면 재사용). --comment-id 불가.
  python3 ~/.claude/scripts/jira_comment.py preview --issue ABC-988 --attach 목록.json
  python3 ~/.claude/scripts/jira_comment.py attach --issue ABC-988 --attach 목록.json
  # 7) 그림 교체 + 글자 치환: preview/update --patches 치환.json --figures 그림.json (그림 항목에 "replace": true).
  #    치환을 먼저 적용하고 자리 문단은 «치환 뒤 글» 로 찾는다(바뀐 문장을 자리로 삼을 수 있어야 하므로). replace 항목은 자리 문단
  #    바로 뒤 mediaSingle 을 통째로 새 그림으로 바꾼다(없으면 rc 2). 보내기 전 검사: 글자·인라인 카드는 치환 목록이 바꾼 것 말고 불변,
  #    그림 id = 기존 − 교체된 옛 id + 새 UUID. 스탬프는 항목별 replace 와 치환 목록 내용에 묶인다. 옛 첨부는 지우지 않는다.
  python3 ~/.claude/scripts/jira_comment.py preview --issue ABC-988 --comment-id 32209 --patches 치환.json --figures 그림.json
  python3 ~/.claude/scripts/jira_comment.py update --issue ABC-988 --comment-id 32209 --patches 치환.json --figures 그림.json
  # 8) 내 미완료 이슈 목록 (읽기 전용, 스탬프 무관). --max 기본 10, 1~30 으로 자른다. 오류는 rc 2 (--json 이면 stdout 에 {"error": ...})
  python3 ~/.claude/scripts/jira_comment.py mine [--json] [--max N]
  # 표 행 추가: 치환.json 에 [{"table_anchor": "판", "append_rows": [["원본 판1", "0.91", "0.88"]]}] 항목을 둔다(그림이 든 댓글도 가능).
  python3 ~/.claude/scripts/jira_comment.py preview --issue ABC-1004 --comment-id 32329 --patches 치환.json
REF: knowledge/harness/code-history/scripts__jira_comment.py.md
"""

import argparse
import base64
import copy
import hashlib
import json
import os
import re
import secrets
import stat
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path

SKILL_PATH = Path(__file__).resolve().parent.parent / "skills" / "commit" / "SKILL.md"
RULES_START = "## Jira 댓글 자동 기록"
STAMP_TTL = 6 * 3600
STAMP_KEEP, BACKUP_KEEP = 7 * 86400, 30 * 86400
MAX_READ = 5 * 1024 * 1024
MAX_FIG_BYTES, MAX_FIGS, MAX_FIG_DIM = 10 * 1024 * 1024, 20, 20000
FIG_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
MEDIA_UUID_RE = re.compile(r"/file/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:/|\?|$)", re.IGNORECASE)
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MAX_ATTACH, MAX_ATTACH_BYTES = 10, 50 * 1024 * 1024
ATTACH_TYPES = {"csv": "text/csv", "tsv": "text/tab-separated-values", "txt": "text/plain", "json": "application/json",
                "pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}
ATTACH_TEXT = {"csv", "tsv", "txt", "json"}
MAX_ATTACH_TOTAL = 100 * 1024 * 1024
SCRATCH_DIR = ".scratch"
PREVIEW_SCAN, PREVIEW_CHARS, PREVIEW_KEYS = 64 * 1024, 120, 10
PHI_WORDS = ("name", "birth", "dob", "mrn", "ssn", "patient", "phone", "address", "email",
             "이름", "성명", "생년", "주민", "환자", "전화", "주소", "등록번호")
# NEVER: 이름과 값을 한 덩어리로 합쳐 쓰지 않는다(커밋 검사의 비밀값 무늬에 오탐된다, 2026-10-13 실측). 자격증명이 아닌 공개 고정값이다.
XSRF_HEADER, XSRF_VALUE = "X-Atlassian-Token", "no-check"
XSRF_OPT_OUT = {XSRF_HEADER: XSRF_VALUE}
ISSUE_RE = re.compile(r"[A-Z][A-Z0-9]+-[0-9]+")
ID_RE = re.compile(r"[0-9]+")
SUPPORTED_NODES = {"doc", "paragraph", "text", "bulletList", "orderedList", "listItem", "codeBlock", "inlineCard",
                   "table", "tableRow", "tableHeader", "tableCell"}
SUPPORTED_MARKS = {"strong", "code", "link"}
UNKNOWN_PUBLISH = "게시 여부 불명 — Jira 화면에서 확인하기 전에는 다시 실행하지 마십시오."
_cred_warned = False
PROCEDURE = (
    "1. 이 미리보기를 사용자에게 보이고 승인받은 뒤에만 게시합니다.",
    "2. 수정은 알림을 끕니다(notifyUsers=false).",
    "3. 게시 뒤 재조회해 본문을 기계 대조합니다.",
    "4. 이미지(media) 노드는 보존합니다(이미지가 든 댓글은 --patches 로만 수정).",
    "5. 새 그림은 --figures 로만 넣습니다(글자·인라인 카드 불변, 그림만 추가).",
    "6. 이슈 파일 첨부는 attach 로만 합니다(미리보기 승인 뒤, 지우기·바꾸기 없음).",
    "7. 그림 교체는 --patches 와 --figures 를 함께 주고 항목에 replace:true 를 둡니다(글자 치환 먼저, 옛 첨부는 지우지 않음).",
    '8. 표 행 추가는 --patches 항목 {"table_anchor": "표 첫 머리 칸 글", "append_rows": [["칸1", "칸2"]]} 로 합니다(표 하나·칸 수 일치·병합 칸 없음, 맨 아래에만 붙음).',
)
LIST_RE = re.compile(r"^(\s*)(\d+\.|[*-])\s+(\S.*)$")
FENCE_RE = re.compile(r"^(\s*)```")
TABLE_SEP_CELL_RE = re.compile(r":?-+:?")
INLINE_RE = re.compile(
    r"`(?P<code>[^`]+)`|\*\*(?P<bold>.+?)\*\*"
    r"|\[(?P<ltext>[^\]]+)\]\((?P<lurl>https?://[^)\s]+)\)|(?P<url>https?://[^\s<>)\]]+)"
)


class Fail(Exception):
    def __init__(self, rc, msg):
        super().__init__(msg)
        self.rc, self.msg = rc, msg


def site():
    url = os.environ.get("JIRA_SITE", "https://your-company-prod.atlassian.net").rstrip("/")
    p = urllib.parse.urlparse(url)
    if p.scheme != "https" or not (p.hostname or "").endswith(".atlassian.net") or p.path or p.query or p.fragment:
        raise Fail(2, "JIRA_SITE 는 https://<이름>.atlassian.net 형식이어야 합니다.")
    return url


def read_credentials():
    global _cred_warned
    path = os.path.expanduser("~/.atlassian_token")
    try:
        mode = os.stat(path).st_mode & 0o777
        if mode & 0o077 and not _cred_warned:
            _cred_warned = True
            print(f"경고: 토큰 파일 권한이 느슨합니다({oct(mode)}): {path}", file=sys.stderr)
    except OSError:
        pass
    try:
        with open(path, encoding="utf-8") as f:
            lines = [x.strip() for x in f if x.strip()]
    except OSError:
        raise Fail(5, f"자격증명 파일을 읽을 수 없습니다: {path}") from None
    if len(lines) < 2:
        raise Fail(5, f"자격증명 형식 오류(1줄=이메일 / 2줄=토큰): {path}")
    return lines[0], lines[1]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    # NEVER: follow a redirect (the Authorization header must never reach another host).
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return


def _open(req, timeout=30):
    return urllib.request.build_opener(NoRedirect).open(req, timeout=timeout)


def http(method, url, body=None):
    email, token = read_credentials()
    headers = {"Authorization": "Basic " + base64.b64encode(f"{email}:{token}".encode()).decode(),
               "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        try:
            with _open(req) as r:
                status, raw = r.status, r.read(MAX_READ + 1)
        except urllib.error.HTTPError as e:
            status, raw = e.code, e.read(MAX_READ + 1)
    except Exception as e:   # noqa: BLE001
        return 0, {"_raw": f"연결 실패: {type(e).__name__}"}
    if len(raw) > MAX_READ:
        return 0, {"_raw": "응답이 5MB 를 넘습니다"}
    text = raw.decode("utf-8", "replace").replace(token, "***")
    try:
        return status, (json.loads(text) if text.strip() else {})
    except ValueError:
        return status, {"_raw": text[:300]}


def http_raw(method, url, data=None, headers=None, timeout=30):
    email, token = read_credentials()
    hd = {"Authorization": "Basic " + base64.b64encode(f"{email}:{token}".encode()).decode(),
          "Accept": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=data, headers=hd, method=method)
    try:
        try:
            with _open(req, timeout) as r:
                status, hdrs, raw = r.status, r.headers, r.read(MAX_READ + 1)
        except urllib.error.HTTPError as e:
            status, hdrs, raw = e.code, e.headers, e.read(MAX_READ + 1)
    except Exception as e:   # noqa: BLE001
        return 0, {}, {"_raw": f"연결 실패: {type(e).__name__}"}
    if len(raw) > MAX_READ:
        return 0, {}, {"_raw": "응답이 5MB 를 넘습니다"}
    text = raw.decode("utf-8", "replace").replace(token, "***")
    try:
        body = json.loads(text) if text.strip() else {}
    except ValueError:
        body = {"_raw": text[:300]}
    return status, {k.lower(): v for k, v in (hdrs.items() if hdrs else [])}, body


def http_fail(status, data):
    return Fail(5, f"HTTP {status}: {json.dumps(data, ensure_ascii=False)[:300]}")


def inline(text, marks=()):
    nodes, pos = [], 0

    def txt(s, extra=(), base=marks):
        if s:
            ms = list(base) + list(extra)
            nodes.append({"type": "text", "text": s, **({"marks": ms} if ms else {})})

    # WHY: 2026-11-26 사용자 지시: 같은 사이트의 Confluence(/wiki/) · Jira(/browse/) 링크는 맨 URL 이든 [글](URL) 이든 인라인 카드로 단다.
    def card(u):
        p = urllib.parse.urlparse(u)
        return p.path.startswith(("/wiki/", "/browse/")) and p.hostname == urllib.parse.urlparse(site()).hostname

    for m in INLINE_RE.finditer(text):
        txt(text[pos:m.start()])
        pos = m.end()
        if m.group("code") is not None:
            txt(m.group("code"), ({"type": "code"},), [x for x in marks if x["type"] == "link"])
        elif m.group("bold") is not None:
            nodes += inline(m.group("bold"), [*marks, {"type": "strong"}])
        elif m.group("ltext") is not None and card(m.group("lurl")):
            nodes.append({"type": "inlineCard", "attrs": {"url": m.group("lurl")}})
        elif m.group("ltext") is not None:
            nodes += inline(m.group("ltext"), [*marks, {"type": "link", "attrs": {"href": m.group("lurl")}}])
        else:
            url = m.group("url")
            core = url.rstrip(".,;:!?")
            if card(core):
                nodes.append({"type": "inlineCard", "attrs": {"url": core}})
            else:
                txt(core, ({"type": "link", "attrs": {"href": core}},))
            txt(url[len(core):])
    txt(text[pos:])
    return nodes


def table_cells(line):
    s = line.strip().removeprefix("|")
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", s)]


def parse_table(lines, i):
    if i + 1 >= len(lines) or not lines[i].strip().startswith("|") or not lines[i + 1].strip().startswith("|"):
        return None, i, None
    head, sep = table_cells(lines[i]), table_cells(lines[i + 1])
    if len(sep) != len(head) or not all(TABLE_SEP_CELL_RE.fullmatch(c) for c in sep):
        return None, i, None
    rows, j = [head], i + 2
    while j < len(lines) and lines[j].strip().startswith("|"):
        rows.append(table_cells(lines[j]))
        j += 1
    bad = next((k for k, r in enumerate(rows[1:], 1) if len(r) != len(head)), None)
    if bad is not None:
        return None, i, f"표 본문 {bad}번째 줄의 열 수({len(rows[bad])})가 머리({len(head)})와 달라 표로 바꾸지 않고 글 문단으로 둡니다: {head[0][:30]}"
    return rows, j, None


def table_row(cells, header=False):
    return {"type": "tableRow", "content": [
        {"type": "tableHeader" if header else "tableCell", "content": [{"type": "paragraph", "content": inline(c)}]}
        for c in cells]}


def table_node(rows):
    return {"type": "table", "attrs": {"isNumberColumnEnabled": False, "layout": "default"}, "content": [
        table_row(row, r == 0) for r, row in enumerate(rows)]}


def md_to_adf(md, warns=None):
    content, stack = [], []
    lines, i = md.splitlines(), 0

    while i < len(lines):
        line = lines[i]
        i += 1
        m = FENCE_RE.match(line)
        if m:
            ind, code = len(m.group(1)), []
            while i < len(lines) and not FENCE_RE.match(lines[i]):
                code.append(lines[i][ind:] if not lines[i][:ind].strip() else lines[i])
                i += 1
            i += 1
            node = {"type": "codeBlock"}
            lang = line.strip()[3:].strip()
            if lang:
                node["attrs"] = {"language": lang}
            if not "\n".join(code).strip():
                raise Fail(2, "빈 코드 블록은 허용하지 않습니다(빈 text 노드는 Jira 가 거부합니다).")
            node["content"] = [{"type": "text", "text": "\n".join(code)}]
            owner = next((e[2] for e in reversed(stack) if e[0] < ind), None)
            if owner is None:
                stack.clear()
                content.append(node)
            else:
                owner["content"][-1]["content"].append(node)
            continue
        if line.lstrip().startswith("|"):
            rows, nxt, warn = parse_table(lines, i - 1)
            if warn and warns is not None:
                warns.append(warn)
            if rows:
                stack.clear()
                content.append(table_node(rows))
                i = nxt
                continue
        m = LIST_RE.match(line)
        if m:
            ind = len(m.group(1))
            kind = "orderedList" if m.group(2)[0].isdigit() else "bulletList"
            while stack and (stack[-1][0] > ind or (stack[-1][0] == ind and stack[-1][1] != kind)):
                stack.pop()
            if stack and stack[-1][0] == ind:
                lst = stack[-1][2]
            else:
                lst = {"type": kind, "content": []}
                if kind == "orderedList":
                    lst["attrs"] = {"order": int(m.group(2)[:-1])}
                (stack[-1][2]["content"][-1]["content"] if stack else content).append(lst)
                stack.append((ind, kind, lst))
            lst["content"].append({"type": "listItem", "content": [
                {"type": "paragraph", "content": inline(m.group(3).strip())}]})
        elif line.strip():
            stack.clear()
            content.append({"type": "paragraph", "content": inline(line.strip())})
    return {"type": "doc", "version": 1, "content": content}


def inline_text(nodes):
    parts = []
    for n in nodes:
        t = n["type"]
        if t == "text":
            s, marks = n["text"], {m["type"]: m for m in n.get("marks", [])}
            if "code" in marks:
                s = f"`{s}`"
            if "strong" in marks:
                s = f"**{s}**"
            if "link" in marks:
                s = f"[{s}]({marks['link']['attrs']['href']})"
            parts.append(s)
        elif t == "inlineCard":
            parts.append(f"[카드: {n['attrs'].get('url', '')}]")
        elif t == "hardBreak":
            parts.append("\n")
        else:
            parts.append(f"[{t}]")
    return "".join(parts)


def render_blocks(nodes, depth, out):
    for n in nodes:
        t, pad = n["type"], "  " * depth
        if t in ("bulletList", "orderedList"):
            start = n.get("attrs", {}).get("order", 1)
            for k, li in enumerate(n.get("content", []), start):
                first = True
                for c in li.get("content", []):
                    if first and c["type"] == "paragraph":
                        mark = f"{k}." if t == "orderedList" else "*"
                        out.append(f"{pad}{mark} {inline_text(c.get('content', []))}")
                    else:
                        render_blocks([c], depth + 1, out)
                    first = False
        elif t == "paragraph":
            out.append(f"{pad}{inline_text(n.get('content', []))}")
        elif t == "codeBlock":
            out.append(f"{pad}```")
            out += [f"{pad}{x}" for x in "".join(c.get("text", "") for c in n.get("content", [])).split("\n")]
            out.append(f"{pad}```")
        elif t == "mediaSingle":
            out.append(f"{pad}[이미지]")
        elif t == "table":
            rows = []
            for r in n.get("content", []):
                row = []
                for c in r.get("content", []):
                    lines = []
                    render_blocks(c.get("content", []), 0, lines)
                    row.append(" ".join(lines).replace("\n", " "))
                rows.append(row)
            out.append(f"{pad}표 {len(rows)}행 × {max(map(len, rows), default=0)}열")
            out += [f"{pad}  " + " | ".join(r) for r in rows]
        else:
            out.append(f"{pad}[{t}]")


def adf_to_text(adf):
    out = []
    render_blocks(adf.get("content", []), 0, out)
    return "\n".join(out)


def fingerprint(adf):
    blocks, cards, media = [], 0, []

    def walk(n):
        nonlocal cards
        t = n.get("type")
        if t in ("paragraph", "codeBlock"):
            blocks.append("".join(c.get("text", "") for c in n.get("content", []) if c.get("type") == "text"))
        elif t == "inlineCard":
            cards += 1
        elif t == "media":
            attrs = n.get("attrs", {})
            media.append(str(attrs.get("id") or attrs.get("url") or json.dumps(attrs, sort_keys=True)))
        for c in n.get("content", []):
            walk(c)

    walk(adf)
    return blocks, cards, sorted(media)


def table_shapes(adf):
    shapes = []

    def walk(n):
        if n.get("type") == "table":
            shapes.append([len(r.get("content", [])) for r in n.get("content", [])])
        for c in n.get("content", []):
            walk(c)

    walk(adf)
    return shapes


def unsupported(adf):
    found = set()

    def walk(n):
        if n.get("type") not in SUPPORTED_NODES:
            found.add(n.get("type"))
        found.update(f"mark:{m.get('type')}" for m in n.get("marks", []) if m.get("type") not in SUPPORTED_MARKS)
        for c in n.get("content", []):
            walk(c)

    walk(adf)
    return sorted(found)


def merge_text(items):
    out = []
    for n in items:
        if out and n.get("type") == "text" and out[-1].get("type") == "text" and n.get("marks") == out[-1].get("marks"):
            out[-1] = {**out[-1], "text": out[-1]["text"] + n["text"]}
        else:
            out.append(n)
    return out


def diff(sent, got, path="doc"):
    if isinstance(sent, dict):
        if not isinstance(got, dict):
            return path
        for k, v in sent.items():
            if k not in got:
                if v == []:
                    continue
                return f"{path}.{k}"
            d = diff(v, got[k], f"{path}.{k}")
            if d:
                return d
        return None
    if isinstance(sent, list):
        if not isinstance(got, list):
            return path
        if path.endswith(".content") and all(isinstance(x, dict) for x in sent + got):
            sent, got = merge_text(sent), merge_text(got)
        if len(sent) != len(got):
            return f"{path}(길이 {len(sent)} != {len(got)})"
        for i, (x, y) in enumerate(zip(sent, got)):
            d = diff(x, y, f"{path}[{i}]")
            if d:
                return d
        return None
    return None if sent == got else path


def esc(s):
    return "".join(c if c.isprintable() else c.encode("unicode_escape").decode() for c in s)


def text_nodes(node):
    if node.get("type") == "text":
        yield node
    for c in node.get("content", []):
        yield from text_nodes(c)


def valid_patch(p):
    if not isinstance(p, dict):
        return False
    if "table_anchor" in p or "append_rows" in p:
        rows = p.get("append_rows")
        return ("anchor" not in p and "new" not in p and isinstance(p.get("table_anchor"), str) and bool(p["table_anchor"].strip())
                and isinstance(rows, list) and bool(rows)
                and all(isinstance(r, list) and bool(r) and all(isinstance(c, str) for c in r) for r in rows))
    return isinstance(p.get("anchor"), str) and isinstance(p.get("new"), str)


def load_patches(path):
    try:
        with open(path, encoding="utf-8") as f:
            patches = json.load(f)
    except (OSError, ValueError) as e:
        raise Fail(2, f"치환 파일을 읽을 수 없습니다: {path} ({type(e).__name__})") from None
    if not isinstance(patches, list) or not all(valid_patch(p) for p in patches):
        raise Fail(2, '치환 파일 형식은 글자 치환 [{"anchor": "기존 텍스트", "new": "새 텍스트"}] 또는 '
                      '표 행 추가 [{"table_anchor": "표 첫 머리 칸 글", "append_rows": [["칸1", "칸2"]]}] 항목의 목록입니다'
                      '(한 항목에 두 종류 키를 섞을 수 없고, 표 글·행·칸은 비어 있으면 안 됩니다).')
    return patches


def table_nodes(node):
    if node.get("type") == "table":
        yield node
    for c in node.get("content", []):
        yield from table_nodes(c)


def skeleton(adf):
    out = copy.deepcopy(adf)
    for n in text_nodes(out):
        n["text"] = ""
    return out


def check_rows_only_added(cur, new, patches):
    row_patches = [p for p in patches if "append_rows" in p]
    if not row_patches:
        return
    trimmed, cut = copy.deepcopy(new), Counter()
    tables_cur, tables_new = list(table_nodes(cur)), list(table_nodes(trimmed))
    if len(tables_cur) != len(tables_new):
        raise Fail(2, "표 개수가 달라집니다. 보내지 않습니다.")
    for t_cur, t_new in zip(tables_cur, tables_new):
        keep = len(t_cur.get("content", []))
        cut.update(canonical(r) for r in t_new.get("content", [])[keep:])
        del t_new["content"][keep:]
    want = Counter(canonical(table_row(r)) for p in row_patches for r in p["append_rows"])
    b_cur, b_new = fingerprint(cur), fingerprint(trimmed)
    n_text = sum("anchor" in p for p in patches)
    changed = sum(x != y for x, y in zip(b_cur[0], b_new[0]))
    if (cut != want or canonical(skeleton(trimmed)) != canonical(skeleton(cur)) or len(b_cur[0]) != len(b_new[0])
            or changed > n_text or b_cur[1:] != b_new[1:]):
        raise Fail(2, "표 행 추가 외에 댓글 구조·글자가 달라지거나 붙은 행이 요청과 다릅니다. 보내지 않습니다.")


def apply_patches(adf, patches):
    adf, changes = copy.deepcopy(adf), []
    for p in patches:
        if "append_rows" in p:
            anchor, rows = p["table_anchor"].strip(), p["append_rows"]
            tables = [t for t in table_nodes(adf) if t.get("content") and t["content"][0].get("content")
                      and para_text(t["content"][0]["content"][0]).strip() == anchor]
            if len(tables) != 1:
                raise Fail(2, f"표 머리 첫 칸 «{esc(anchor)[:40]}»과 일치하는 표가 {len(tables)}개입니다(정확히 1개여야 합니다)")
            table = tables[0]
            if any((c.get("attrs") or {}).get(k, 1) != 1
                   for r in table["content"] for c in r.get("content", []) for k in ("colspan", "rowspan")):
                raise Fail(2, f"병합 칸(colspan·rowspan)이 든 표에는 행을 붙이지 않습니다: «{esc(anchor)[:40]}»")
            cols, old = len(table["content"][0]["content"]), len(table["content"])
            for k, row in enumerate(rows, 1):
                if len(row) != cols:
                    raise Fail(2, f"붙일 {k}번째 행의 칸 수({len(row)})가 표 첫 행의 칸 수({cols})와 다릅니다: «{esc(anchor)[:40]}»")
            table["content"] += [table_row(r) for r in rows]
            changes.append((f"[표 «{anchor}»] {old}행",
                            f"[표 «{anchor}»] {old + len(rows)}행 · 추가: " + " / ".join(" | ".join(r) for r in rows)))
            continue
        anchor = p["anchor"]
        hits = [n for n in text_nodes(adf) if anchor and anchor in n["text"]]
        total = sum(n["text"].count(anchor) for n in hits)
        if total != 1:
            raise Fail(2, f"앵커가 텍스트 노드에서 {total}회 일치합니다(정확히 1회여야 합니다): {anchor[:40]!r}")
        node = hits[0]
        before, node["text"] = node["text"], node["text"].replace(anchor, p["new"], 1)
        if not node["text"]:
            raise Fail(2, f"치환 결과가 빈 텍스트가 됩니다: {anchor[:40]!r}")
        changes.append((before, node["text"]))
    return adf, changes


def read_body(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, ValueError):
        raise Fail(2, f"본문 파일을 읽을 수 없거나 UTF-8 이 아닙니다: {path}") from None


def load_rules():
    try:
        lines = SKILL_PATH.read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        raise Fail(2, f"형식 규칙 파일을 읽을 수 없습니다: {SKILL_PATH}") from None
    start = next((k for k, x in enumerate(lines) if x.startswith(RULES_START)), None)
    if start is None:
        raise Fail(2, f"형식 규칙 절을 찾지 못했습니다('{RULES_START}'): {SKILL_PATH}")
    end = next((k for k in range(start + 1, len(lines)) if lines[k].startswith(("## ", "### "))), len(lines))
    if not any(x.strip() for x in lines[start + 1:end]):
        raise Fail(2, f"형식 규칙 절의 본문이 비어 있습니다: {SKILL_PATH}")
    return "\n".join(lines[start:end]).rstrip()


def format_warnings(adf):
    warns, top = [], adf.get("content", [])
    if not any(text for text in fingerprint(adf)[0]) and not fingerprint(adf)[1]:
        warns.append("본문이 비었습니다.")
    if any(n["type"] == "paragraph" for n in top):
        warns.append("목록 밖 문단이 있습니다(글머리 목록으로 쓰는 것이 규칙입니다).")

    def walk(n):
        if n.get("type") == "listItem":
            first = next((c for c in n.get("content", []) if c["type"] == "paragraph"), None)
            if first and len(inline_text(first.get("content", []))) > 200:
                warns.append(f"글머리 한 줄이 200자를 넘습니다: {inline_text(first['content'])[:40]}...")
        for c in n.get("content", []):
            walk(c)

    walk(adf)
    return warns


def stamp_dir():
    return os.path.expanduser("~/.claude/_audit/jira-preview")


def canonical(adf):
    return json.dumps(adf, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def stamp_hash(issue, comment_id, adf):
    # WHY: 사이트도 묶는다: 미리보기 뒤 JIRA_SITE 를 바꿔 다른 사이트의 동명 이슈에 게시하는 길을 막는다(2026-10-01 감사).
    return hashlib.sha256(f"{site()}\n{issue}\n{comment_id or 'new'}\n{canonical(adf)}".encode()).hexdigest()


def current_sha(cur):
    return hashlib.sha256(canonical(cur).encode("utf-8")).hexdigest()


def write_private(path, text):
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(path, 0o600)
    except OSError as e:
        raise Fail(2, f"파일을 쓸 수 없습니다: {path} ({type(e).__name__})") from None


def ensure_stamp_dir():
    d = stamp_dir()
    try:
        os.makedirs(d, mode=0o700, exist_ok=True)
        os.chmod(d, 0o700)
    except OSError as e:
        raise Fail(2, f"스탬프 디렉터리를 준비할 수 없습니다: {d} ({type(e).__name__})") from None
    return d


def prune_old():
    d, now = stamp_dir(), time.time()
    try:
        names = os.listdir(d)
    except OSError:
        return
    for n in names:
        p = os.path.join(d, n)
        try:
            # WHY: `.json.claimed` 는 게시 도중 프로세스가 죽어 남은 스탬프 잔여 파일이다(2026-10-01 P6 검수: 종전엔 영원히 쌓였다).
            if n.endswith((".json", ".json.claimed")) and now - os.lstat(p).st_mtime > (BACKUP_KEEP if n.startswith("backup-") else STAMP_KEEP):
                os.remove(p)
        except OSError:
            pass


def write_stamp(h, issue, comment_id, source, cur_sha=None):
    rec = {"issue": issue, "comment_id": comment_id, "time": datetime.now().isoformat(), "source": str(source),
           "current_sha": cur_sha}
    write_private(os.path.join(ensure_stamp_dir(), f"{h}.json"), json.dumps(rec, ensure_ascii=False))


def check_stamp(h, cur_sha=None):
    path = os.path.join(stamp_dir(), f"{h}.json")
    try:
        with open(path, encoding="utf-8") as f:
            rec = json.load(f)
        t = datetime.fromisoformat(rec["time"]).timestamp()
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        t = rec = None
    if t is None or t > time.time() or time.time() - t > STAMP_TTL:
        raise Fail(3, "이 본문의 미리보기 스탬프가 없거나 훼손·만료(6시간)됐습니다. "
                      "preview 를 먼저 돌리고 사용자 승인을 받으십시오.")
    if cur_sha is not None and rec.get("current_sha") != cur_sha:
        raise Fail(3, "preview 이후 댓글이 바뀜. preview 를 다시 돌리고 사용자 승인을 받으십시오.")


def claim_stamp(h):
    p = os.path.join(stamp_dir(), f"{h}.json")
    try:
        os.rename(p, f"{p}.claimed")
    except OSError:
        raise Fail(3, "이 미리보기 스탬프는 이미 다른 게시가 사용 중이거나 소모됐습니다. "
                      "preview 를 다시 돌리고 사용자 승인을 받으십시오.") from None


def drop_stamp(h, restore=False):
    p = os.path.join(stamp_dir(), f"{h}.json")
    try:
        if restore:
            os.rename(f"{p}.claimed", p)
        else:
            os.remove(f"{p}.claimed")
    except OSError:
        pass


def fetch_comment(issue, comment_id):
    status, data = http("GET", f"{site()}/rest/api/3/issue/{issue}/comment/{comment_id}")
    if status != 200:
        raise http_fail(status, data)
    if not isinstance(data, dict) or not isinstance(data.get("body"), dict):
        raise Fail(5, "응답 형식이 올바르지 않습니다(JSON 객체와 body 가 필요합니다).")
    return data


def send_claimed(h, method, url, body):
    claim_stamp(h)
    try:
        return http(method, url, body)
    except BaseException:
        drop_stamp(h, restore=True)
        raise


def check_write(status, data, ok, h):
    valid = isinstance(data, dict) and data.get("id") not in (None, "")
    if status in ok and valid:
        drop_stamp(h)
        return str(data["id"])
    if status == 0 or status in ok:
        drop_stamp(h)
        raise Fail(5, f"응답을 확인하지 못했습니다. {UNKNOWN_PUBLISH}")
    if status >= 500 or status in (408, 429):   # WHY: 반영 여부 불명(408 요청 시간 초과·429 제한은 서버가 처리한 뒤에도 올 수 있다): 스탬프를 소모해 재실행의 중복 게시를 막는다
        drop_stamp(h)
        raise Fail(5, f"HTTP {status}: 반영 여부 확인 필요. {UNKNOWN_PUBLISH}")
    drop_stamp(h, restore=True)   # NEVER: 미반영이 확정되지 않은 실패에서 스탬프를 되돌리지 않는다(4xx 등만 되돌린다)
    raise http_fail(status, data)


def verify(issue, comment_id, sent):
    prefix = f"게시는 완료됐습니다(댓글 id {comment_id}). 그러나 "
    status, data = http("GET", f"{site()}/rest/api/3/issue/{issue}/comment/{comment_id}")
    if status != 200 or not isinstance(data, dict) or not isinstance(data.get("body"), dict):
        raise Fail(4, prefix + f"재조회에 실패했습니다(HTTP {status}).")
    shape_sent, shape_got = table_shapes(sent), table_shapes(data["body"])
    if shape_sent != shape_got:
        raise Fail(4, prefix + f"재조회한 표 구조(표 개수·표마다 행 수·행마다 셀 수)가 보낸 것과 다릅니다. "
                               f"보낸 것 {str(shape_sent)[:200]} · 되읽은 것 {str(shape_got)[:200]}. 화면에서 직접 확인하십시오.")
    d = diff(sent, data["body"])
    if d:
        raise Fail(4, prefix + f"재조회 본문이 보낸 본문과 다릅니다. 처음 달라진 경로: {d}. 화면에서 직접 확인하십시오.")


def report_done(issue, comment_id):
    print(f"댓글 id: {comment_id}\n{site()}/browse/{issue}?focusedCommentId={comment_id}")


def multipart_file(name, data, ctype="image/png"):
    boundary = secrets.token_hex(16)
    head = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
            f"Content-Type: {ctype}\r\n\r\n").encode("ascii")
    return f"multipart/form-data; boundary={boundary}", head + data + f"\r\n--{boundary}--\r\n".encode("ascii")


def resolve_in_folder(list_path, rel, label):
    # NEVER: 목록 폴더 밖(절대 경로·`..`·중간 폴더 심볼릭 링크)을 가리키는 파일을 받지 않는다(이 서버에는 민감 영상·표 파일이 있고 사용자는 미리보기만 보고 승인한다).
    base = os.path.realpath(os.path.dirname(os.path.abspath(list_path)))
    # WHY: 폴더 안 제한은 목록 파일을 민감 자료 폴더에 두면 무력하다: 목록은 .scratch 아래 임시 폴더에만 둔다(2026-10-14 검수).
    if SCRATCH_DIR not in Path(base).parts:
        raise Fail(2, "목록 파일은 .scratch 아래 임시 폴더에 두십시오(민감 자료 폴더에서 바로 올리지 않게).")
    try:
        parent = os.path.realpath(os.path.dirname(os.path.join(base, rel)))
    except ValueError:
        parent = None
    if os.path.isabs(rel) or parent is None or os.path.commonpath([base, parent]) != base:
        raise Fail(2, f"{label} 파일은 {label} 목록 폴더 안에 있어야 합니다(절대 경로·..·밖을 가리키는 링크 불가): {esc(rel)[:60]}")
    return os.path.join(parent, os.path.basename(rel))


def load_figures(path):
    try:
        with open(path, encoding="utf-8") as f:
            items = json.load(f)
    except (OSError, ValueError) as e:
        raise Fail(2, f"그림 목록 파일을 읽을 수 없습니다: {path} ({type(e).__name__})") from None
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_FIGS or not all(
            isinstance(x, dict) and isinstance(x.get("anchor"), str) and x["anchor"]
            and isinstance(x.get("file"), str) and x["file"] and isinstance(x.get("replace", False), bool) for x in items):
        raise Fail(2, '그림 목록 형식은 [{"anchor": "문단 첫머리 글귀", "file": "fig1.png", "replace": true(선택, 불리언만)}] 1~20개입니다.')
    return [(x["anchor"], resolve_in_folder(path, x["file"], "그림"), x.get("replace", False)) for x in items]


def read_png(path):
    name = os.path.basename(path)
    shown = esc(name)[:60]
    if not FIG_NAME_RE.fullmatch(name) or not name.lower().endswith(".png"):
        raise Fail(2, f"그림 파일 이름은 영문·숫자·._- 로 된 .png 여야 합니다: {shown}")
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                raise Fail(2, f"그림 파일이 일반 파일이 아닙니다: {shown}")
            data = f.read(MAX_FIG_BYTES + 1)
    except (OSError, ValueError):
        raise Fail(2, f"그림 파일을 읽을 수 없습니다(없음·권한·심볼릭 링크): {shown}") from None
    if len(data) > MAX_FIG_BYTES:
        raise Fail(2, f"그림 파일이 {MAX_FIG_BYTES // 1024 // 1024}MiB 를 넘습니다: {shown}")
    if len(data) < 24 or data[:8] != PNG_MAGIC or data[12:16] != b"IHDR":
        raise Fail(2, f"PNG 파일이 아닙니다: {shown}")
    width, height = struct.unpack(">II", data[16:24])
    if not width or not height:
        raise Fail(2, f"PNG 가로·세로가 0 입니다: {shown}")
    if width > MAX_FIG_DIM or height > MAX_FIG_DIM:
        raise Fail(2, f"PNG 가로·세로가 {MAX_FIG_DIM}을 넘습니다({width}×{height}): {shown}")
    return data, width, height


def para_text(p):
    return "".join(n.get("text", "") for n in text_nodes(p))


def anchor_paragraphs(adf, anchor):
    hits = []

    def walk(n):
        kids = n.get("content")
        if isinstance(kids, list):
            for c in kids:
                if isinstance(c, dict):
                    if c.get("type") == "paragraph" and para_text(c).startswith(anchor):
                        hits.append((kids, c, n.get("type")))
                    walk(c)

    walk(adf)
    return hits


def index_of(kids, node):
    return next(k for k, x in enumerate(kids) if x is node)


def figure_plan(cur, path):
    plan, names, paras = [], set(), set()
    for anchor, fpath, replace in load_figures(path):
        hits = anchor_paragraphs(cur, anchor)
        shown = esc(anchor)[:40]
        if len(hits) != 1:
            raise Fail(2, f"자리 글귀로 시작하는 문단이 {len(hits)}개입니다(정확히 1개여야 합니다): {shown!r}")
        kids, para, parent = hits[0]
        if parent not in ("doc", "listItem"):
            raise Fail(2, f"이 자리에는 그림을 넣을 수 없습니다(최상위 문단 또는 글머리 안 문단만): {shown!r}")
        if id(para) in paras:
            raise Fail(2, f"두 항목이 같은 문단을 가리킵니다: {shown!r}")
        paras.add(id(para))
        nxt = kids[index_of(kids, para) + 1:][:1]
        has_fig = bool(nxt) and isinstance(nxt[0], dict) and nxt[0].get("type") == "mediaSingle"
        old_ids, old_alt, old_caption = [], None, ""
        if replace:
            if not has_fig:
                raise Fail(2, f"바꿀 그림이 없습니다(자리 문단 바로 뒤에 그림이 있어야 합니다): {shown!r}")
            old_ids = fingerprint(nxt[0])[2]
            kids_media = [n for n in nxt[0].get("content", []) if isinstance(n, dict) and n.get("type") == "media"]
            if len(old_ids) != 1 or len(kids_media) != 1:
                raise Fail(2, f"바꿀 그림 블록의 모양이 예상과 다릅니다(그림 1장이 아님): {shown!r}")
            attrs = kids_media[0].get("attrs")
            old_alt = attrs.get("alt") if isinstance(attrs, dict) else None
            old_caption = "".join(n.get("text", "") for n in text_nodes(nxt[0]))
        elif has_fig:
            raise Fail(2, f"이미 그림이 있습니다: {shown!r}")
        data, width, height = read_png(fpath)
        name = os.path.basename(fpath)
        if name in names:
            raise Fail(2, f"그림 파일 이름이 겹칩니다: {esc(name)[:60]}")
        names.add(name)
        sha = hashlib.sha256(data).hexdigest()
        # NEVER: 올리는 이름에서 내용 해시를 빼지 않는다(다시 뽑은 그림의 크기가 우연히 같아도 옛 첨부를 재사용하지 않게).
        upload = f"{name[:-4]}-{sha[:12]}.png"
        if not FIG_NAME_RE.fullmatch(upload):
            raise Fail(2, f"올라갈 첨부 이름이 규칙(영문·숫자·._- 100자 이내)을 넘습니다: {esc(upload)[:60]}")
        plan.append({"anchor": anchor, "name": name, "upload": upload, "size": len(data), "sha256": sha,
                     "width": width, "height": height, "data": data, "para": para_text(para), "path": fpath,
                     "replace": replace, "old_ids": old_ids, "old_alt": old_alt, "old_caption": old_caption})
    return plan


def figures_stamp_hash(issue, comment_id, plan, patches=None):
    keys = ("anchor", "name", "size", "sha256", "width", "height")
    # NEVER: replace·patches 키가 없을 때는 넣지 않는다(추가만 하는 옛 경로의 해시 입력이 바뀐다).
    rec = {"kind": "figures", "site": site(), "issue": issue, "comment_id": comment_id,
           "figures": [{**{k: e[k] for k in keys}, **({"replace": True} if e["replace"] else {})} for e in plan]}
    if patches:
        rec["patches"] = [{"table_anchor": p["table_anchor"], "append_rows": p["append_rows"]} if "append_rows" in p
                          else {"anchor": p["anchor"], "new": p["new"]} for p in patches]
    return hashlib.sha256(canonical(rec).encode("utf-8")).hexdigest()


def fetch_attachments(issue):
    status, data = http("GET", f"{site()}/rest/api/3/issue/{issue}?fields=attachment")
    if status != 200:
        raise http_fail(status, data)
    fields = data.get("fields") if isinstance(data, dict) else None
    have = {}
    for x in (fields.get("attachment") if isinstance(fields, dict) else None) or []:
        try:
            key, aid = (x["filename"], int(x["size"])), int(x["id"])
        except (KeyError, TypeError, ValueError):
            continue
        if key not in have or aid > int(have[key]):
            have[key] = str(aid)
    return have


def check_upload(status, data, h, name):
    first = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else {}
    aid = str(first.get("id", ""))
    if status in (200, 201) and ID_RE.fullmatch(aid):
        return aid
    if status in (0, 200, 201) or status >= 500 or status in (408, 429):
        drop_stamp(h)
        raise Fail(5, f"첨부 반영 여부 불명(HTTP {status}, {esc(name)[:60]}). preview 를 다시 돌리면 "
                      "이미 올라간 첨부는 재사용으로 표시됩니다.")
    drop_stamp(h, restore=True)
    raise http_fail(status, data)


def resolve_media(issue, e, have, h):
    att = have.get((e["upload"], e["size"]))
    if att is None:
        ctype, body = multipart_file(e["upload"], e["data"])
        status, _, data = http_raw("POST", f"{site()}/rest/api/3/issue/{issue}/attachments", body,
                                   {"Content-Type": ctype, **XSRF_OPT_OUT}, 300)
        att = check_upload(status, data, h, e["upload"])
    status, hdrs, _ = http_raw("GET", f"{site()}/rest/api/3/attachment/content/{att}")
    # NEVER: 303 Location 문자열을 출력·기록·예외 문구에 넣지 않는다(서명된 미디어 주소다, UUID 만 꺼낸다).
    m = MEDIA_UUID_RE.search(str(hdrs.get("location", ""))) if status in (302, 303) else None
    if not m:
        raise Fail(5, f"미디어 UUID 를 얻지 못했습니다(HTTP {status}). 댓글은 고치지 않았습니다.")
    return att, m.group(1)


def insert_figures(cur, plan, uuids):
    new = copy.deepcopy(cur)
    for e, u in zip(plan, uuids):
        hits = anchor_paragraphs(new, e["anchor"])
        if len(hits) != 1:
            raise Fail(2, f"삽입 자리를 다시 찾지 못했습니다: {esc(e['anchor'])[:40]!r}")
        kids, para, _ = hits[0]
        pos = index_of(kids, para) + 1
        media = {"type": "media", "attrs": {"type": "file", "id": u, "collection": "", "width": e["width"],
                                            "height": e["height"], "alt": e["name"]}}
        if e["replace"]:
            old = kids[pos] if pos < len(kids) else None
            slots = [k for k, n in enumerate(old.get("content", [])) if isinstance(n, dict) and n.get("type") == "media"] \
                if isinstance(old, dict) and old.get("type") == "mediaSingle" else []
            if len(slots) != 1:
                raise Fail(2, f"바꿀 그림을 다시 찾지 못했습니다: {esc(e['anchor'])[:40]!r}")
            old["content"][slots[0]] = media
        else:
            kids.insert(pos, {"type": "mediaSingle", "attrs": {"layout": "center"}, "content": [media]})
    return new


def captions(adf):
    out = []

    def walk(n):
        if n.get("type") == "caption":
            out.append("".join(t["text"] for t in text_nodes(n)))
        for c in n.get("content", []):
            walk(c)

    walk(adf)
    return out


def check_figure_result(cur, new, uuids, base=None, old_ids=()):
    before, after, kept = fingerprint(base or cur), fingerprint(new), list(fingerprint(cur)[2])
    if after[0] != before[0] or after[1] != before[1] or captions(new) != captions(base or cur):
        raise Fail(2, "그림을 넣으면 글자 블록·캡션 또는 인라인 카드 수가 달라집니다. 보내지 않습니다.")
    for m in old_ids:
        if m not in kept:
            raise Fail(2, "교체할 옛 그림 id 가 기존 댓글에 없습니다. 보내지 않습니다.")
        kept.remove(m)
    if len({u.lower() for u in uuids}) != len(uuids) or {u.lower() for u in uuids} & {m.lower() for m in kept}:
        raise Fail(2, "새 미디어 UUID 가 서로 겹치거나 남는 기존 그림과 겹칩니다. 보내지 않습니다.")
    if after[2] != sorted(kept + list(uuids)):
        raise Fail(2, "넣은 뒤 그림 id 가 «기존 − 교체된 옛 그림 + 새 UUID» 와 다릅니다. 보내지 않습니다.")


def patched_base(a, cur):
    if a.patches is None:
        return None, cur, None
    patches = load_patches(a.patches)
    base, changes = apply_patches(cur, patches)
    check_rows_only_added(cur, base, patches)
    return patches, base, changes


def preview_figures(a):
    rules = load_rules()
    prune_old()
    cur = fetch_comment(a.issue, a.comment_id)["body"]
    patches, base, changes = patched_base(a, cur)
    plan = figure_plan(base, a.figures)
    have = fetch_attachments(a.issue)
    n_rep = sum(e["replace"] for e in plan)
    what = f"글자 치환 {len(changes)}곳과 그림 {len(plan)}개 반영" if patches else f"그림 {len(plan)}개 넣기"
    print(f"== 게시 목적지 ==\n{site()} / 이슈 {a.issue} / 댓글 {a.comment_id} 에 {what}")
    print(f"\n== 형식 규칙 ({SKILL_PATH.name}) ==\n{rules}\n\n== 게시 절차 ==")
    print("\n".join(PROCEDURE))
    if changes is not None:
        print("\n== 치환 전후 ==")
        for before, after in changes:
            print(f"- 전: {esc(before)}\n+ 후: {esc(after)}")
    print("\n== 그림 계획 ==")
    for i, e in enumerate(plan, 1):
        att = have.get((e["upload"], e["size"]))
        old = (f"{esc(e['old_alt'])[:60]} (media id {esc(e['old_ids'][0])[:60]})" if e["old_alt"]
               else f"media id {esc(e['old_ids'][0])[:60]}") if e["replace"] else ""
        kind = (f"교체: 옛 그림 {old} → 새 파일 {esc(e['path'])} ·"
                + (f" 설명 글 유지: {esc(e['old_caption'][:60])} ·" if e["old_caption"] else "") if e["replace"] else "추가 ·")
        print(f"- [{i}] {kind} 자리 «{esc(e['para'][:48])}» · 파일 {esc(e['path'])} · {e['size']:,}바이트 · {e['width']}×{e['height']}"
              f" · sha256 {e['sha256'][:12]} · 올라갈 이름 {esc(e['upload'])} · "
              + (f"기존 첨부 {att} 재사용" if att else "새로 올림"))
    fp, fc = fingerprint(base), fingerprint(cur)
    if patches or n_rep:
        print(f"\n글자 블록 {len(fp[0])}개 중 치환 {len(changes or [])}곳 · 그림 {len(fc[2])}개 → "
              f"{len(fc[2]) - sum(len(e['old_ids']) for e in plan) + len(plan)}개(교체 {n_rep}, 추가 {len(plan) - n_rep}) · 인라인 카드 {fp[1]}개는 그대로입니다.")
    else:
        print(f"\n글자 블록 {len(fp[0])}개·인라인 카드 {fp[1]}개는 바뀌지 않고 그림 {len(fp[2])}개 → {len(fp[2]) + len(plan)}개가 됩니다.")
    h = figures_stamp_hash(a.issue, a.comment_id, plan, patches)
    write_stamp(h, a.issue, a.comment_id, a.figures, current_sha(cur))
    print(f"\n스탬프 저장: {h[:12]} (6시간 유효, 이슈 {a.issue}, 댓글 {a.comment_id})")
    return 0


def update_figures(a):
    cur = fetch_comment(a.issue, a.comment_id)["body"]
    patches, base, _ = patched_base(a, cur)
    plan = figure_plan(base, a.figures)
    h = figures_stamp_hash(a.issue, a.comment_id, plan, patches)
    check_stamp(h, current_sha(cur))
    have = fetch_attachments(a.issue)
    claim_stamp(h)
    try:
        refs = [resolve_media(a.issue, e, have, h) for e in plan]
        uuids = [u for _, u in refs]
        new = insert_figures(base, plan, uuids)
        check_figure_result(cur, new, uuids, base, [m for e in plan for m in e["old_ids"]])
        if current_sha(fetch_comment(a.issue, a.comment_id)["body"]) != current_sha(cur):   # NEVER: 업로드가 길어지는 동안 남이 고친 댓글을 덮어쓰지 않는다
            raise Fail(3, "업로드하는 동안 댓글이 바뀌었습니다. preview 를 다시 돌리고 사용자 승인을 받으십시오.")
        backup = os.path.join(ensure_stamp_dir(),
                              f"backup-{a.issue}-{a.comment_id}-{datetime.now():%Y%m%d-%H%M%S-%f}.adf.json")
        write_private(backup, json.dumps(cur, ensure_ascii=False))
    except BaseException:
        drop_stamp(h, restore=True)
        raise
    print(f"백업: {backup}")
    try:
        status, data = http("PUT", f"{site()}/rest/api/3/issue/{a.issue}/comment/{a.comment_id}?notifyUsers=false",
                            {"body": new})
    except BaseException:
        drop_stamp(h, restore=True)
        raise
    check_write(status, data, (200,), h)
    verify(a.issue, a.comment_id, new)
    for i, (att, u) in enumerate(refs, 1):
        print(f"그림 {i}: 첨부 {att} · 미디어 {u}")
    report_done(a.issue, a.comment_id)
    return 0


def preview_lines(ext, data, obj):
    # WHY: 승인 전에 보이는 이유: 목록 파일에 환자 식별 열이 있으면 머리글에서 알아볼 수 있다. 반대로 환자 값이 세션 기록에
    # 찍히지 않도록 앞 64KiB 의 첫 비어 있지 않은 줄 120자만 보이고 내용 전체는 줄 단위로 쪼개지 않는다(2026-10-14 검수).
    head = data[:PREVIEW_SCAN].decode("utf-8", "ignore").lstrip("﻿")
    line = next((x for x in head.splitlines() if x.strip()), "")
    if ext == "json":
        if isinstance(obj, dict):
            names = [str(k)[:40] for k in list(obj)[:PREVIEW_KEYS]]
            show = [f"형태: 객체 · 키 앞 {PREVIEW_KEYS}개: " + ", ".join(esc(k) for k in names)]
        else:
            names = []
            show = [f"형태: 배열 · 길이 {len(obj)}" if isinstance(obj, list) else f"형태: {type(obj).__name__}"]
    else:
        show = [f"첫 줄: {esc(line[:PREVIEW_CHARS])}"]
        sep = {"csv": ",", "tsv": "\t"}.get(ext)
        names = [c[:40] for c in line.split(sep)] if sep else [line[:40]]
        if sep:
            lines = data.count(b"\n") + (data[-1:] != b"\n")
            show.append(f"줄 {lines:,}개 · 첫 줄 열 {len(names)}개")
    hits = [esc(n) for n in names if any(w in n.lower() for w in PHI_WORDS)]
    if hits:
        show.append("! 환자 식별 정보로 보이는 열: " + ", ".join(hits))
    return show


def read_attach(path):
    name = os.path.basename(path)
    shown = esc(name)[:60]
    stem, dot, ext = name.rpartition(".")
    ext = ext.lower()
    if not FIG_NAME_RE.fullmatch(name) or not dot or ext not in ATTACH_TYPES:
        raise Fail(2, f"첨부 파일 이름은 영문·숫자·._- 로 되고 확장자가 {'·'.join(ATTACH_TYPES)} 중 하나여야 합니다: {shown}")
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                raise Fail(2, f"첨부 파일이 일반 파일이 아닙니다: {shown}")
            data = f.read(MAX_ATTACH_BYTES + 1)
    except (OSError, ValueError):
        raise Fail(2, f"첨부 파일을 읽을 수 없습니다(없음·권한·심볼릭 링크): {shown}") from None
    if not data:
        raise Fail(2, f"빈 파일은 첨부할 수 없습니다: {shown}")
    if len(data) > MAX_ATTACH_BYTES:
        raise Fail(2, f"첨부 파일이 {MAX_ATTACH_BYTES // 1024 // 1024}MiB 를 넘습니다: {shown}")
    # NEVER: 확장자만 믿지 않는다(이름을 바꿔 단 다른 종류의 파일이 올라가지 않게 가벼운 머리 확인만 한다).
    magic = {"png": (PNG_MAGIC, "PNG"), "jpg": (b"\xff\xd8\xff", "JPEG"), "jpeg": (b"\xff\xd8\xff", "JPEG"), "pdf": (b"%PDF-", "PDF")}
    show = []
    if ext in magic:
        if not data.startswith(magic[ext][0]):
            raise Fail(2, f"{magic[ext][1]} 파일이 아닙니다: {shown}")
    else:
        try:
            text = data.decode("utf-8")
            if b"\x00" in data[:4096]:
                raise ValueError
            obj = json.loads(text) if ext == "json" else None
        except (ValueError, RecursionError):
            raise Fail(2, f"글 파일이 아니거나 UTF-8·JSON 형식이 어긋납니다: {shown}") from None
        show = preview_lines(ext, data, obj)
    sha = hashlib.sha256(data).hexdigest()
    upload = f"{stem}-{sha[:12]}.{ext}"
    if not FIG_NAME_RE.fullmatch(upload):
        raise Fail(2, f"올라갈 첨부 이름이 규칙(영문·숫자·._- 100자 이내)을 넘습니다: {esc(upload)[:60]}")
    return {"name": name, "upload": upload, "size": len(data), "sha256": sha, "ctype": ATTACH_TYPES[ext],
            "data": data, "path": path, "show": show}


def attach_plan(path):
    try:
        with open(path, encoding="utf-8") as f:
            items = json.load(f)
    except (OSError, ValueError) as e:
        raise Fail(2, f"첨부 목록 파일을 읽을 수 없습니다: {path} ({type(e).__name__})") from None
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_ATTACH or not all(
            isinstance(x, dict) and isinstance(x.get("file"), str) and x["file"] for x in items):
        raise Fail(2, f'첨부 목록 형식은 [{{"file": "a.csv"}}] 1~{MAX_ATTACH}개입니다.')
    plan, names, total = [], set(), 0
    for x in items:
        e = read_attach(resolve_in_folder(path, x["file"], "첨부"))
        if e["name"].lower() in names:
            raise Fail(2, f"첨부 파일 이름이 겹칩니다(대소문자 무시): {esc(e['name'])[:60]}")
        names.add(e["name"].lower())
        total += e["size"]
        if total > MAX_ATTACH_TOTAL:
            raise Fail(2, f"첨부 파일 합계가 {MAX_ATTACH_TOTAL // 1024 // 1024}MiB 를 넘습니다.")
        plan.append(e)
    return plan


def attach_stamp_hash(issue, plan):
    keys = ("name", "upload", "size", "sha256")
    rec = {"kind": "attach", "site": site(), "issue": issue, "files": [{k: e[k] for k in keys} for e in plan]}
    return hashlib.sha256(canonical(rec).encode("utf-8")).hexdigest()


def preview_attach(a):
    rules = load_rules()
    prune_old()
    plan = attach_plan(a.attach)
    have = fetch_attachments(a.issue)
    print(f"== 게시 목적지 ==\n{site()} / 이슈 {a.issue} 에 파일 {len(plan)}개 첨부")
    print(f"\n== 형식 규칙 ({SKILL_PATH.name}) ==\n{rules}\n\n== 게시 절차 ==")
    print("\n".join(PROCEDURE))
    print("\n== 첨부 계획 ==")
    for i, e in enumerate(plan, 1):
        att = have.get((e["upload"], e["size"]))
        print(f"- [{i}] 파일 {esc(e['path'])} · {e['size']:,}바이트 · sha256 {e['sha256'][:12]} · 종류 {e['ctype']}"
              f" · 올라갈 이름 {esc(e['upload'])} · " + (f"기존 첨부 {att} 재사용" if att else "새로 올림"))
        for s in e["show"]:
            print(f"    {s}")
    h = attach_stamp_hash(a.issue, plan)
    write_stamp(h, a.issue, None, a.attach)
    print(f"\n스탬프 저장: {h[:12]} (6시간 유효, 이슈 {a.issue}, 첨부)")
    return 0


def cmd_attach(a):
    plan = attach_plan(a.attach)
    h = attach_stamp_hash(a.issue, plan)
    check_stamp(h)
    have = fetch_attachments(a.issue)
    claim_stamp(h)
    refs = []
    try:
        for e in plan:
            att = have.get((e["upload"], e["size"]))
            if att is not None:
                refs.append((att, e, "재사용"))
                continue
            ctype, body = multipart_file(e["upload"], e["data"], e["ctype"])
            status, _, data = http_raw("POST", f"{site()}/rest/api/3/issue/{a.issue}/attachments", body,
                                       {"Content-Type": ctype, **XSRF_OPT_OUT}, 300)
            refs.append((check_upload(status, data, h, e["upload"]), e, "새로"))
    except BaseException:
        drop_stamp(h, restore=True)
        raise
    drop_stamp(h)
    after = fetch_attachments(a.issue)
    lost = [e["upload"] for _, e, _ in refs if (e["upload"], e["size"]) not in after]
    if lost:
        raise Fail(4, "첨부는 요청했으나 되읽기에서 찾지 못했습니다: " + ", ".join(esc(x)[:60] for x in lost))
    for att, e, how in refs:
        print(f"첨부 {att} · {esc(e['upload'])} · {how}")
    print(f"{site()}/browse/{a.issue}")
    return 0


def cmd_get(a):
    data = fetch_comment(a.issue, a.comment_id)
    body = data.get("body", {})
    print(f"작성: {data.get('created')}  수정: {data.get('updated')}")

    def walk(n, d):
        t, line = n.get("type"), None
        if t in ("paragraph", "codeBlock"):
            line = "".join(c.get("text", "") for c in n.get("content", []) if c.get("type") == "text")[:70]
        elif t == "media":
            line = f"[이미지 id={n.get('attrs', {}).get('id')}]"
        print("  " * d + t + (f"  {line!r}" if line is not None else ""))
        for c in n.get("content", []):
            walk(c, d + 1)

    walk(body, 0)
    if a.save:
        write_private(a.save, json.dumps(body, ensure_ascii=False, indent=1))
        print(f"ADF 원문 저장: {a.save}")
    return 0


def cmd_mine(a):
    try:
        base = site()
        status, data = http("POST", f"{base}/rest/api/3/search/jql", {
            "jql": "assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC",
            "maxResults": max(1, min(30, a.max)), "fields": ["summary", "status", "updated"]})
        if status != 200:
            raise Fail(2, f"Jira 조회 실패: HTTP {status}" if status else "Jira 조회 실패: 연결 실패")
        try:
            rows = [{"key": str(i["key"]), "summary": str(i["fields"].get("summary") or ""),
                     "status": str((i["fields"].get("status") or {}).get("name") or ""),
                     "updated": str(i["fields"].get("updated") or ""), "url": f"{base}/browse/{i['key']}"}
                    for i in data["issues"]]
        except (KeyError, TypeError, AttributeError):
            raise Fail(2, "Jira 응답 형식 오류") from None
    except Exception as e:   # noqa: BLE001
        name = type(e).__name__
        msg = e.msg if isinstance(e, Fail) else name
        if a.json:
            print(json.dumps({"error": msg}, ensure_ascii=False))
        else:
            print(msg if isinstance(e, Fail) else f"예기치 못한 오류: {name}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(rows, ensure_ascii=False))
    else:
        for r in rows:
            print(esc(f"{r['key']}  [{r['status']}]  {r['summary']}"))
    return 0


def cmd_preview(a):
    given = lambda v: v is not None
    if given(a.body_file) + (given(a.patches) or given(a.figures)) + given(a.attach) != 1:
        raise Fail(2, "--body-file, --attach, (--patches 와/또는 --figures) 중 하나만 주십시오.")
    if given(a.attach) and a.comment_id is not None:
        raise Fail(2, "--attach 는 --comment-id 를 받지 않습니다(이슈에 첨부).")
    if (given(a.patches) or given(a.figures)) and not a.comment_id:
        raise Fail(2, "--patches 와 --figures 는 --comment-id 가 필요합니다.")
    if given(a.attach):
        return preview_attach(a)
    if given(a.figures):
        return preview_figures(a)
    rules = load_rules()
    prune_old()
    cur = fetch_comment(a.issue, a.comment_id)["body"] if a.comment_id else None
    changes, extra = None, []
    if a.patches is not None:
        _, adf, changes = patched_base(a, cur)
    else:
        if cur is not None and fingerprint(cur)[2]:
            raise Fail(2, "이미지가 든 댓글은 --patches 로만 고칩니다.")
        adf = md_to_adf(read_body(a.body_file), extra)
        if cur is not None and unsupported(cur):
            extra.append("현재 댓글에 마크다운으로 표현할 수 없는 노드가 있어 덮어쓰면 사라집니다: "
                         + ", ".join(unsupported(cur)))
    print(f"== 게시 목적지 ==\n{site()} / 이슈 {a.issue} / "
          + (f"댓글 {a.comment_id} 수정" if a.comment_id else "새 댓글"))
    print(f"\n== 형식 규칙 ({SKILL_PATH.name}) ==\n{rules}\n\n== 게시 절차 ==")
    print("\n".join(PROCEDURE))
    if changes is not None:
        print("\n== 치환 전후 ==")
        for before, after in changes:
            print(f"- 전: {esc(before)}\n+ 후: {esc(after)}")
    print("\n== 미리보기 ==\n" + "\n".join(esc(x) for x in adf_to_text(adf).split("\n")))
    warns = [esc(w) for w in format_warnings(adf) + extra]
    print("\n== 형식 점검(경고만) ==\n" + ("\n".join(f"! {w}" for w in warns) if warns else "경고 없음"))
    h = stamp_hash(a.issue, a.comment_id, adf)
    write_stamp(h, a.issue, a.comment_id, a.body_file or a.patches, current_sha(cur) if cur is not None else None)
    print(f"\n스탬프 저장: {h[:12]} (6시간 유효, 이슈 {a.issue}, 댓글 {a.comment_id or 'new'})")
    return 0


def cmd_post(a):
    adf = md_to_adf(read_body(a.body_file))
    h = stamp_hash(a.issue, None, adf)
    check_stamp(h)
    status, data = send_claimed(h, "POST", f"{site()}/rest/api/3/issue/{a.issue}/comment", {"body": adf})
    cid = check_write(status, data, (200, 201), h)
    verify(a.issue, cid, adf)
    report_done(a.issue, cid)
    return 0


def cmd_update(a):
    if (a.body_file is not None) + (a.patches is not None or a.figures is not None) != 1:
        raise Fail(2, "--body-file 또는 (--patches 와/또는 --figures) 중 하나만 주십시오.")
    if a.figures is not None:
        return update_figures(a)
    cur = fetch_comment(a.issue, a.comment_id)["body"]
    if a.body_file is not None:
        if fingerprint(cur)[2]:
            raise Fail(2, "이미지가 든 댓글은 --patches 로만 고칩니다.")
        new = md_to_adf(read_body(a.body_file))
    else:
        new = patched_base(a, cur)[1]
    if set(fingerprint(new)[2]) != set(fingerprint(cur)[2]):
        raise Fail(2, "수정 전후 media id 집합이 다릅니다. 보내지 않습니다.")
    h = stamp_hash(a.issue, a.comment_id, new)
    check_stamp(h, current_sha(cur))
    backup = os.path.join(ensure_stamp_dir(),
                          f"backup-{a.issue}-{a.comment_id}-{datetime.now():%Y%m%d-%H%M%S-%f}.adf.json")
    write_private(backup, json.dumps(cur, ensure_ascii=False))
    print(f"백업: {backup}")
    status, data = send_claimed(h, "PUT", f"{site()}/rest/api/3/issue/{a.issue}/comment/{a.comment_id}?notifyUsers=false",
                                {"body": new})
    check_write(status, data, (200,), h)
    verify(a.issue, a.comment_id, new)
    report_done(a.issue, a.comment_id)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Jira 댓글 미리보기·게시·수정 (사용법은 파일 머리 주석)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("get")
    g.add_argument("--issue", required=True)
    g.add_argument("--comment-id", required=True)
    g.add_argument("--save")
    pv = sub.add_parser("preview")
    pv.add_argument("--issue", required=True)
    pv.add_argument("--comment-id")
    pv.add_argument("--body-file")
    pv.add_argument("--patches")
    pv.add_argument("--figures")
    pv.add_argument("--attach")
    at = sub.add_parser("attach")
    at.add_argument("--issue", required=True)
    at.add_argument("--attach", required=True)
    po = sub.add_parser("post")
    po.add_argument("--issue", required=True)
    po.add_argument("--body-file", required=True)
    up = sub.add_parser("update")
    up.add_argument("--issue", required=True)
    up.add_argument("--comment-id", required=True)
    up.add_argument("--body-file")
    up.add_argument("--patches")
    up.add_argument("--figures")
    mi = sub.add_parser("mine")
    mi.add_argument("--json", action="store_true")
    mi.add_argument("--max", type=int, default=10)
    a = ap.parse_args(argv)
    if a.cmd == "mine":
        return cmd_mine(a)
    try:
        if not ISSUE_RE.fullmatch(a.issue):
            raise Fail(2, f"이슈 키 형식이 올바르지 않습니다(예: ABC-972): {esc(a.issue)[:40]}")
        if getattr(a, "comment_id", None) is not None and not ID_RE.fullmatch(a.comment_id):
            raise Fail(2, f"댓글 id 는 숫자만 허용합니다: {esc(a.comment_id)[:40]}")
        return {"get": cmd_get, "preview": cmd_preview, "post": cmd_post, "update": cmd_update,
                "attach": cmd_attach}[a.cmd](a)
    except Fail as e:
        print(e.msg, file=sys.stderr)
        return e.rc
    except Exception as e:   # noqa: BLE001
        print(f"예기치 못한 오류: {type(e).__name__}", file=sys.stderr)
        return 5


if __name__ == "__main__":
    sys.exit(main())
