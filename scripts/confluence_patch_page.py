"""Confluence 페이지를 **본문 재생성 없이** 리터럴 치환으로 고친다 (REST v2 직접 호출).

■ 안전 규약
  1) 치환 앵커가 **정확히 1회** 일치할 때만 적용한다. 0회·2회 이상이면 아무것도 고치지 않는다.
  2) 적용 전 현재 본문을 로컬 파일(0600)로 백업한다. probe·dry-run 도 백업을 쓴다.
     앵커는 원문 위치 기준으로 한 번에 치환하며, 앵커끼리 겹치면 중단한다.
  3) `--probe`로 먼저 실제 마크업을 확인한다.
  4) 기본은 dry-run이다. 실제 쓰기는 `--apply`를 명시해야 한다.
  5) 적용 후 백업본과 표·행·매크로·펼치기·패널·링크·첨부 **개수를 대조**해야 한다 —
     이 스크립트는 그 안내문만 출력하며 대조는 실행자(main)가 따로 한다(자동 대조 아님).

■ 자격증명
  `~/.atlassian_token` (chmod 600, 1줄=이메일 / 2줄=토큰) 또는 환경변수
  CONFLUENCE_EMAIL / CONFLUENCE_API_TOKEN. 사이트는 CONFLUENCE_SITE로 바꾼다.
  ★**Atlassian 계정 API 토큰**이어야 한다(id.atlassian.com) — Bitbucket 전용 토큰·구 app
  password는 Confluence에서 거부된다.

사용:
  # 1) 실제 마크업 확인 (원격은 읽기만, 로컬 백업 파일은 생성)
  uv run python ~/.claude/scripts/confluence_patch_page.py --page <ID> --probe "문구1" "문구2"
  # 2) 치환 계획 점검 (원격은 읽기만, 로컬 백업 파일은 생성) — patches.json = [{"label","anchor","new"}]
  uv run python ~/.claude/scripts/confluence_patch_page.py --page <ID> --patches patches.json
  # 3) 실제 반영 (골격 스탬프 + 게시 승인 필요 — 승인은 AskUserQuestion 으로 받는다(승인 줄은
  #    confluence_publish_approve.py question 이 출력). 알림 선택(--minor 여부)과 --message 가 승인 줄과 같아야 하고 한 번 쓰면 소모된다)
  uv run python ~/.claude/scripts/confluence_patch_page.py --page <ID> --patches patches.json --apply
  # 제목 변경 · 이동(같은 공간 안의 새 부모 아래로). --patches 없이도, 함께도 쓴다. 기본은 dry-run(계획만 찍음)
  uv run python ~/.claude/scripts/confluence_patch_page.py --page <ID> --title "<새 제목>" --parent <부모 ID> [--apply]
  #   승인 줄: confluence_publish_approve.py question --page <ID> --notify quiet|notify --message "<버전 설명>" \\
  #            --set-title "<새 제목>" --set-parent <부모 ID>
  #   → `게시 승인 요청 · page=<ID> · 알림=… · 버전 설명=«…» · 새 제목=«…» · 새 부모=<ID>` (값이 있는 필드만 붙는다)

■ 제목 변경 · 이동
  · `--patches` 가 없는 호출은 본문 검사 세 가지(문체 전후 비교 · 검토 관문 · 골격 스탬프)를 건너뛴다.
    올리는 본문은 서버에서 받은 문자열 그대로다. HOME 검사 · 반영 전 백업 · 게시 승인은 그대로 건다. 치환과 함께면 검사도 전부 건다.
  · 이동은 같은 공간 안에서만 한다.
  · 반영 뒤 재조회해 제목 · 부모를 확인한다.

■ 새 페이지 만들기
  uv run python ~/.claude/scripts/confluence_patch_page.py --create --space <숫자 공간 ID> [--parent <부모 ID>] --title "<제목>" \\
      --body-file <저장 형식 파일> [--apply]      # 기본 dry-run: 검사 + 승인 줄을 얻는 명령 출력, --apply 로 만든 뒤 PAGE_ID=<ID> 출력
  · 본문 검사 세 가지를 파일 본문에 건다. 문체는 고치기 전 본문이 없어 MCP 생성 경로(korean-style-gate.sh)처럼 본문 전체를 report() 로 본다.
  · 승인은 기존 새 페이지 승인 줄(`게시 승인 요청 · new · space=… · parent=… · 제목=«…»`)과 판정을 그대로 쓴다. 생성은 알림을 끌 수 없어 --minor 불가.
  · POST 는 한 번만 보낸다(재시도는 중복 생성이 될 수 있다). 보낸 뒤 시간 초과 · 연결 오류면 «만들어졌는지 알 수 없다» 로 끝낸다.
REF: knowledge/harness/code-history/scripts__confluence_patch_page.py.md
"""

import argparse
import hashlib
import itertools
import json
import os
import pwd
import shlex
import sys
import time
import unicodedata
from datetime import datetime
from urllib.parse import urlparse

import requests

SITE = os.environ.get("CONFLUENCE_SITE", "https://your-company-prod.atlassian.net")
TOKEN_FILE = os.path.expanduser("~/.atlassian_token")
SKELETON_STAMP_DIR = os.path.expanduser("~/.claude/_audit/skeleton-pass")


def _home_is_real():
    return os.path.realpath(os.path.expanduser("~")) == os.path.realpath(pwd.getpwuid(os.getuid()).pw_dir)


def _skeleton_stamp_ok(body):
    # NEVER: 계산식을 scripts/confluence_skeleton_check.py stamp() 와 따로 바꾸지 않는다(rules-lazy/doc-format-registry.md 게이트 6).
    h = hashlib.sha256(body.encode("utf-8").rstrip(b" \t\r\n")).hexdigest()
    path = os.path.join(SKELETON_STAMP_DIR, f"{h}.json")
    if not os.path.exists(path):
        return False
    try:
        with open(path) as f:
            rec = json.load(f)
        t = datetime.fromisoformat(rec["time"]).timestamp()
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False
    return 0 <= time.time() - t <= 6 * 3600   # WHY: 미래 시각 스탬프는 무효(2026-11-10 검수)


def auth():
    email = os.environ.get("CONFLUENCE_EMAIL")
    token = os.environ.get("CONFLUENCE_API_TOKEN")
    if (not email or not token) and os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            lines = [x.strip() for x in f if x.strip()]
        if len(lines) >= 2:
            email, token = email or lines[0], token or lines[1]
    if not email or not token:
        sys.exit(f"[BLOCKED] 자격증명 없음 — {TOKEN_FILE}에 1줄=이메일 / 2줄=토큰 형식으로 두거나 "
                 "CONFLUENCE_EMAIL·CONFLUENCE_API_TOKEN 환경변수를 설정하세요.")
    return (email, token)


def get_page(page_id):
    r = requests.get(f"{SITE}/wiki/api/v2/pages/{page_id}",
                     params={"body-format": "storage"}, auth=auth(), timeout=60)
    r.raise_for_status()
    d = r.json()
    return d["title"], d["version"]["number"], d["body"]["storage"]["value"]


def get_page_info(page_id, with_body=False):
    r = requests.get(f"{SITE}/wiki/api/v2/pages/{page_id}",
                     params={"body-format": "storage"} if with_body else {}, auth=auth(), timeout=60)
    if r.status_code >= 300:
        return None
    d = r.json()
    return {"title": d["title"], "spaceId": str(d["spaceId"]) if d.get("spaceId") else None, "parentId": str(d["parentId"]) if d.get("parentId") else None,
            "version": d["version"]["number"], "body": d["body"]["storage"]["value"] if with_body else None}


def put_page(page_id, title, version, body, message, minor=False, parent_id=None):
    payload = {"id": str(page_id), "status": "current", "title": title,
               "body": {"representation": "storage", "value": body},
               "version": {"number": version + 1, "message": message,
                           "minorEdit": bool(minor)}}
    if parent_id is not None:
        payload["parentId"] = str(parent_id)
    r = requests.put(
        f"{SITE}/wiki/api/v2/pages/{page_id}",
        json=payload,
        auth=auth(), timeout=120,
    )
    if r.status_code >= 300:
        sys.exit(f"[실패] {r.status_code} {r.text[:500]}")
    return r.json()["version"]["number"]


def check_site(url):
    # WHY: 인증 헤더가 엉뚱한 호스트로 가지 않게 한다. 환경변수 CONFLUENCE_SITE 오염 방어(2026-10-01 감사), scripts/jira_comment.py site() 와 같은 규칙.
    p = urlparse(url.rstrip("/"))
    if p.scheme != "https" or not (p.hostname or "").endswith(".atlassian.net") or p.path or p.query or p.fragment:
        sys.exit("[BLOCKED] CONFLUENCE_SITE 는 https://<이름>.atlassian.net 형식이어야 합니다.")
    return url.rstrip("/")


def replace_by_original_position(body, patches):
    # WHY: 순차 replace 는 앞 치환의 new 가 뒤 앵커 문자열을 포함하면 엉뚱한 자리를 고친다(2026-10-01 감사).
    spans = sorted(((body.find(p["anchor"]), p) for p in patches), key=lambda x: x[0])
    for (s1, p1), (s2, _) in itertools.pairwise(spans):
        if s2 < s1 + len(p1["anchor"]):
            sys.exit(f"\n★앵커끼리 원문에서 겹칩니다(@{s1}·@{s2}) — 아무것도 고치지 않고 중단한다.")
    out = body
    for s, p in reversed(spans):
        out = out[:s] + p["new"] + out[s + len(p["anchor"]):]
    return out


def post_page(space, parent, title, body):
    # NEVER: retry the POST (a retry may create a duplicate).
    payload = {"spaceId": str(space), "status": "current", "title": title,
               "body": {"representation": "storage", "value": body}}
    if parent is not None:
        payload["parentId"] = str(parent)
    try:
        r = requests.post(f"{SITE}/wiki/api/v2/pages", json=payload, auth=auth(), timeout=120)
    except (requests.Timeout, requests.ConnectionError) as e:
        sys.exit(f"\n★요청을 보낸 뒤 {type(e).__name__} — 만들어졌는지 알 수 없다. 같은 제목의 페이지가 생겼는지 확인한 뒤 다시 할 것.")
    if r.status_code >= 300:
        sys.exit(f"[실패] {r.status_code} {r.text[:500]}\n★승인은 이미 소모됐다. 새 승인이 필요하다.")
    # WHY: 재조회 URL 에 들어가므로 숫자 ID 만 받는다(2026-11-22 security). 못 읽어도 페이지는 이미 생겼을 수 있다.
    try:
        data = r.json()
    except ValueError:
        data = None
    new_id = str(data.get("id")) if isinstance(data, dict) and data.get("id") is not None else ""
    if not new_id.isascii() or not new_id.isdigit():
        sys.exit(f"\n★페이지가 만들어졌을 수 있다. 응답에서 새 ID 를 읽지 못했다(응답 앞 200자: {r.text[:200]}). "
                 "같은 제목의 페이지가 생겼는지 확인할 것.")
    return new_id


def create_main(a):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from confluence_publish_approve import (
        _ctrl_error,
        approval_line,
        new_key,
        norm_page,
    )
    try:
        space = norm_page(a.space or "")
    except ValueError:
        sys.exit(f"\n★공간 ID «{a.space}» 는 숫자가 아님 — 숫자 공간 ID(spaceId)로 다시 지정할 것.")
    try:
        parent = norm_page(a.parent) if a.parent is not None else None
    except ValueError as e:
        sys.exit(f"\n★부모: {e}")
    if a.title is None or _ctrl_error(a.title):
        sys.exit("\n★제목이 없거나 탭·개행 등 제어문자가 있음 — 한 줄 평문 제목을 --title 로 지정할 것.")
    if any(unicodedata.category(c) in ("Cf", "Zl", "Zp") for c in a.title):
        sys.exit("\n★제목에 보이지 않는 글자 · 방향 제어 글자가 있음 — 승인 줄에서 사용자가 본 글자와 실제 값이 달라질 수 있어 거부한다.")
    title = a.title.strip()
    if not title:
        sys.exit("\n★제목이 비어 있음 — --title 로 지정할 것.")
    if not a.body_file or not os.path.isfile(a.body_file):
        sys.exit(f"\n★본문 파일 «{a.body_file}» 이 없음 — --body-file 로 저장 형식 파일을 지정할 것.")
    limit = 4 * 1024 * 1024   # WHY: 서버 한도는 요청 5MB(413). JSON 이스케이프로 커지는 몫을 남긴다.
    with open(a.body_file, "rb") as f:
        raw = f.read(limit + 1)
    if len(raw) > limit:
        sys.exit("\n★본문 파일이 4MB 를 넘음 — 나눠서 만들 것.")
    try:
        body = raw.decode("utf-8")
    except UnicodeDecodeError:
        sys.exit("\n★본문 파일이 UTF-8 로 읽히지 않음 — UTF-8 저장 형식 파일로 다시 지정할 것.")
    if not body.strip():
        sys.exit("\n★본문 파일이 비어 있음.")
    if any(x == "--message" or x.startswith("--message=") for x in sys.argv[1:]):
        print("생성에는 버전 설명이 실리지 않는다(--message 무시).")

    parent_label = "없음(공간 홈 아래)"
    if parent is not None:
        info = get_page_info(parent)
        if info is None:
            sys.exit(f"\n★부모 페이지 {parent} 조회 실패(없는 페이지 · 권한 없음) — 중단.")
        if not info["spaceId"]:
            sys.exit(f"\n★부모 페이지 {parent} 의 공간을 확인할 수 없어 만들지 않는다 — 중단.")
        if info["spaceId"] != space:
            sys.exit(f"\n★부모 {parent} 는 다른 공간(spaceId {info['spaceId']} ≠ {space})이다 — 중단.")
        parent_label = f"{parent}({info['title']})"
    print(f"=== 새 페이지 계획 ===\n  공간: {space}\n  부모: {parent_label}\n  제목: «{title}»\n"
          f"  본문: {len(body):,}자 ({len(raw):,} 바이트) — 파일에서 읽은 그대로 올린다")

    from korean_style_check import report as _ks_report
    if _ks_report(body, "새 페이지 본문", strict=not a.allow_style_violation):
        sys.exit("\n★한국어 문체 위반 — 게시 중단. 문장을 다시 써서 고칠 것 "
                 "(콤마로 기계 치환 금지). 정본: rules-lazy/answer-detail.md "
                 "§ 한국어 문체. 의도적으로 넘기려면 --allow-style-violation.")

    key = new_key(space, parent, title)
    print("\n승인 줄을 얻는 명령(이 값 그대로 써야 승인 줄과 호출 값이 맞는다):\n"
          # WHY: «--k=값» 꼴: 값이 «-» 로 시작해도 argparse 가 옵션으로 오인하지 않는다(2026-11-22 qa)
          f"  python3 ~/.claude/scripts/confluence_publish_approve.py question --new --space={shlex.quote(space)}"
          f" --parent={shlex.quote(parent or '')} --title={shlex.quote(title)}\n"
          f"  → {approval_line([key])}")
    if not a.apply:
        print("dry-run 종료 — 실제로 만들려면 --apply 를 붙인다(승인은 보지도 쓰지도 않았다).")
        return

    if not _home_is_real():
        sys.exit("\n★HOME 이 실제 사용자 홈과 다름 — 게시 중단. 환경변수 HOME 을 바꾸지 않은 셸에서 실행할 것.")
    from confluence_review_gate import scan
    hits = scan(f"{title}\n\n{body}")
    if hits:
        sys.exit("\n★검토 관문 차단 — 제목 · 본문에 자격증명 · 환자 식별자 꼴: " + ", ".join(hits)
                 + " (1행=제목 · 본문은 3행부터)\n정본: ~/.claude/skills/confluence/SKILL.md § 검토 관문")
    if not _skeleton_stamp_ok(body):
        sys.exit("\n★골격 대조 스탬프 없음(또는 6시간 경과) — 게시 중단. 먼저 실행할 것:\n"
                 f"  python3 ~/.claude/scripts/confluence_skeleton_check.py {a.body_file} --format <프로젝트>/<양식>\n"
                 "정본: ~/.claude/rules-lazy/doc-format-registry.md 게이트 6")
    from confluence_publish_approve import check_and_consume_new
    check_and_consume_new(space, parent, title)

    new_id = post_page(space, parent, title, body)
    print(f"PAGE_ID={new_id}")
    after = get_page_info(new_id, with_body=True)
    if after is None:
        sys.exit(f"\n★만든 뒤 재조회 실패 — 페이지 {new_id} 를 직접 확인할 것.")
    print(f"생성: ID {new_id} · 제목 «{after['title']}» · 부모 {after['parentId'] or '없음'} · 공간 {after['spaceId']} · v{after['version']}")
    h_file = hashlib.sha256(body.encode("utf-8")).hexdigest()
    if hashlib.sha256(after["body"].encode("utf-8")).hexdigest() == h_file:
        print(f"본문이 파일과 같음(sha256 {h_file[:16]}… 일치)")
    else:   # WHY: 서버가 storage 를 정규화했을 수 있어(2026-09-09 실측) 경고만 한다
        print(f"★경고: 재조회 본문이 파일과 다름(sha256 다름, 길이 {len(body):,} → {len(after['body']):,}자) — 서버 정규화일 수 있다. 파일과 대조할 것.")
    bad = []
    if after["title"] != title:
        bad.append(f"제목 «{after['title']}» ≠ 요청 «{title}»")
    if after["spaceId"] != space:
        bad.append(f"공간 {after['spaceId']} ≠ 요청 {space}")
    if parent is not None and after["parentId"] != parent:
        bad.append(f"부모 {after['parentId'] or '없음'} ≠ 요청 {parent}")
    if bad:
        sys.exit("\n★재조회 결과가 요청과 다름: " + " · ".join(bad) + " — 페이지를 직접 확인할 것.")


def main():
    global SITE
    SITE = check_site(SITE)
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", required="--create" not in sys.argv[1:])
    ap.add_argument("--probe", nargs="*", help="이 문구 주변 마크업을 출력만 한다")
    ap.add_argument("--window", type=int, default=260)
    ap.add_argument("--patches", help='[{"anchor":..., "new":..., "label":...}] JSON 파일')
    ap.add_argument("--apply", action="store_true", help="실제로 반영 (없으면 dry-run)")
    ap.add_argument("--backup-dir", default="outputs")
    ap.add_argument("--message", default="최신 결과 반영")
    ap.add_argument("--minor", action="store_true",
                    help="조용한 수정 — 관찰자 알림을 보내지 않는다")
    ap.add_argument("--allow-style-violation", action="store_true",
                    help="한국어 문체 게이트를 통과시키지 않고 강행 (기본 차단)")
    ap.add_argument("--title", help="새 제목 (--patches 없이도 쓴다)")
    ap.add_argument("--parent", help="옮길 새 부모 페이지 ID(숫자, 같은 공간 안에서만). --create 면 새 페이지의 부모")
    ap.add_argument("--create", action="store_true", help="파일 본문으로 새 페이지를 만든다(--space · --title · --body-file)")
    ap.add_argument("--space", help="--create: 숫자 공간 ID(spaceId)")
    ap.add_argument("--body-file", help="--create: 올릴 저장 형식(storage) 파일")
    a = ap.parse_args()
    if a.create:
        if a.page is not None or a.patches or a.probe is not None or a.minor:
            ap.error("--create 는 --page · --patches · --probe · --minor 와 함께 쓰지 않는다(새 페이지는 조용히 만들 수 없다)")
        return create_main(a)

    change = a.title is not None or a.parent is not None
    req_title = req_parent = None
    if change:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from confluence_publish_approve import norm_change, norm_page
        try:
            req_title, req_parent = norm_change(a.title, a.parent)
            if req_parent is not None and req_parent == norm_page(a.page):
                sys.exit("\n★자기 자신을 부모로 지정할 수 없다 — 중단.")
        except ValueError as e:
            sys.exit(f"\n{e}")

    title, version, body = get_page(a.page)
    print(f"[{title}] v{version} · 본문 {len(body):,}자")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs(a.backup_dir, exist_ok=True)
    backup = f"{a.backup_dir}/confluence_backup_{a.page}_v{version}_{stamp}.storage.html"
    # NEVER: 백업을 0600 보다 넓은 권한으로 쓰지 않는다(본문에 내부 문서가 담길 수 있다).
    with os.fdopen(os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        f.write(body)
    print(f"백업 저장: {backup}")

    if a.probe:
        for kw in a.probe:
            n = body.count(kw)
            print(f"\n=== '{kw}' {n}회 ===")
            i = -1
            for _ in range(min(n, 3)):
                i = body.find(kw, i + 1)
                print(f"--- @{i} ---\n{body[max(0, i - a.window):i + a.window]}")
        return

    if not a.patches and not change:
        print("치환 목록(--patches)이 없어 여기서 멈춘다 (읽기만 수행).")
        return

    new_title, want_parent = title, None
    if change:
        meta = get_page_info(a.page)
        if meta is None:
            sys.exit(f"\n★페이지 {a.page} 의 공간 · 부모 조회 실패 — 중단.")
        cur_parent = want_parent = meta["parentId"]
        new_title = req_title if req_title is not None else title
        if req_parent is not None:
            want_parent = req_parent
        cur_info = get_page_info(cur_parent) if cur_parent else None
        cur_label = f"{cur_parent}({cur_info['title'] if cur_info else '제목 조회 실패'})" if cur_parent else "없음"
        new_label = cur_label
        if want_parent != cur_parent:
            target = get_page_info(want_parent)
            if target is None:
                sys.exit(f"\n★새 부모 페이지 {want_parent} 조회 실패(없는 페이지 · 권한 없음) — 중단.")
            # WHY: REST v2 PUT 의 parentId 는 같은 공간 안에서만 부모를 바꾼다(다른 공간 이동은 API 가 지원하지 않음).
            # spaceId 를 못 얻으면 «없음 == 없음» 으로 같은 공간이 되므로 옮기지 않는다(2026-11-22 검수).
            if not target["spaceId"] or not meta["spaceId"]:
                sys.exit(f"\n★공간을 확인할 수 없어 옮기지 않는다(이 페이지 spaceId {meta['spaceId'] or '없음'} · "
                         f"새 부모 {want_parent} spaceId {target['spaceId'] or '없음'}) — 중단.")
            if target["spaceId"] != meta["spaceId"]:
                sys.exit(f"\n★새 부모 {want_parent} 는 다른 공간(spaceId {target['spaceId']} ≠ {meta['spaceId']})이다 — "
                         "다른 공간으로는 옮기지 않는다. 중단.")
            new_label = f"{want_parent}({target['title']})"
        print("\n=== 제목 · 부모 변경 계획 ===")
        print(f"  제목: «{title}» → «{new_title}»" if new_title != title else f"  제목: 그대로 «{title}»")
        print(f"  부모: {cur_label} → {new_label}" if want_parent != cur_parent else f"  부모: 그대로 {cur_label}")
        if not a.patches and new_title == title and want_parent == cur_parent:
            print("바꿀 것 없음 — 제목 · 부모가 지금과 같고 치환도 없어 아무것도 쓰지 않는다(승인 소모 없음).")
            return

    if not a.patches:
        new_body = body
        print("본문 검사 세 가지(문체 전후 비교 · 검토 관문 · 골격 스탬프)는 건너뜀 — 치환 없음, "
              "올리는 본문은 서버에서 받은 그대로다(2026-11-22 사용자 결정).")
    else:
        with open(a.patches) as f:
            patches = json.load(f)
        print(f"\n=== 앵커 검사 ({len(patches)}건, 전부 1회여야 적용) ===")
        bad = 0
        for p in patches:
            n = body.count(p["anchor"])
            print(f"  [{'OK ' if n == 1 else '★NG'}] {p.get('label', '')[:30]:32s} count={n}")
            bad += n != 1
        if bad:
            sys.exit(f"\n★{bad}건 불일치 — 아무것도 고치지 않고 중단한다.")

        new_body = replace_by_original_position(body, patches)
        print(f"\n본문 {len(body):,} → {len(new_body):,}자 ({len(new_body) - len(body):+,})")

        # WHY: 판정은 치환 전후 비교로 한다(2026-08-10). 결과 전체를 보면 기존 본문의 과거 위반까지 걸려 무관한 수정이 전부 멈춘다.
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from korean_style_check import regression as _ks_regression
        rc = _ks_regression(body, new_body, "치환 전후",
                            strict=not a.allow_style_violation)
        if rc:
            sys.exit("\n★한국어 문체 위반 — 게시 중단. 문장을 다시 써서 고칠 것 "
                     "(콤마로 기계 치환 금지). 정본: rules-lazy/answer-detail.md "
                     "§ 한국어 문체. 의도적으로 넘기려면 --allow-style-violation.")

    if not a.apply:
        print("dry-run 종료 — 실제 반영하려면 --apply 를 붙인다.")
        return

    # WHY: HOME 바꿔치기 차단 (2026-10-06 검수): 골격 스탬프·승인 장부와 세션 기록은 전부 HOME 기준이라
    #   `HOME=/tmp/가짜 ... --apply` 로 가짜 스탬프 폴더·기록을 물릴 수 있다. 훅 경로의 HOME 은 Claude Code 가 주므로 해당 없다.
    if not _home_is_real():
        sys.exit("\n★HOME 이 실제 사용자 홈과 다름 — 게시 중단. 환경변수 HOME 을 바꾸지 않은 셸에서 실행할 것.")

    if a.patches:
        from confluence_review_gate import scan
        hits = scan(new_body)
        if hits:
            sys.exit("\n★검토 관문 차단 — 게시 본문에 자격증명 · 환자 식별자 꼴: " + ", ".join(hits)
                     + "\n정본: ~/.claude/skills/confluence/SKILL.md § 검토 관문")

        if not _skeleton_stamp_ok(new_body):
            sys.exit("\n★골격 대조 스탬프 없음(또는 6시간 경과) — 게시 중단. 먼저 실행할 것:\n"
                     "  python3 ~/.claude/scripts/confluence_skeleton_check.py <위 새 본문을 담은 파일> "
                     "--format <프로젝트>/<양식>\n"
                     "정본: ~/.claude/rules-lazy/doc-format-registry.md 게이트 6")

    # REF: scripts/confluence_publish_approve.py (게시 승인 검사 규칙 정본)
    # NEVER: 승인을 put 직전 말고 다른 곳에서 소모하지 않는다(dry-run·probe 는 소모하지 않는다).
    from confluence_publish_approve import check_and_consume
    check_and_consume(page=a.page, notify="quiet" if a.minor else "notify", message=a.message,
                      title=req_title, parent=req_parent)

    if req_parent is None:
        v = put_page(a.page, new_title, version, new_body, a.message, a.minor)
    else:
        v = put_page(a.page, new_title, version, new_body, a.message, a.minor, parent_id=req_parent)
    print(f"✅ 반영 완료 — v{v}")
    if a.patches:
        print("★적용 후 검증(MANDATORY): 백업본과 <table>·<tr>·ac:structured-macro·expand·"
              "adf panel·ac:link·ri:attachment 개수를 대조할 것.")
    if not change:
        return

    # WHY: parentId 를 생략했을 때 부모가 유지되는지는 공식 문서에 없다(intent/2026-10-06-confluence-publish-approval.md 개정 2). 그래서 제목만 바꿔도 부모까지 확인한다.
    after = get_page_info(a.page, with_body=not a.patches)
    if after is None:
        sys.exit("\n★반영 뒤 재조회 실패 — 제목 · 부모를 확인하지 못했다. 페이지를 직접 확인할 것.")
    print(f"재조회: 제목 «{after['title']}» · 부모 {after['parentId'] or '없음'} · v{after['version']}")
    if not a.patches:
        h0 = hashlib.sha256(body.encode("utf-8")).hexdigest()
        h1 = hashlib.sha256(after["body"].encode("utf-8")).hexdigest()
        if h0 == h1:
            print(f"본문 그대로(sha256 {h0[:16]}… 백업과 같음)")
        else:   # WHY: 서버가 storage 를 정규화했을 수 있어(2026-09-09 실측) 경고만 한다
            print(f"★경고: 재조회 본문이 백업과 다름(sha256 다름, 길이 {len(body):,} → {len(after['body']):,}자) — "
                  f"서버 정규화일 수 있다. 백업과 대조할 것: {backup}")
    bad = []
    if after["title"] != new_title:
        bad.append(f"제목 «{after['title']}» ≠ 요청 «{new_title}»")
    if after["parentId"] != want_parent:
        bad.append(f"부모 {after['parentId'] or '없음'} ≠ 요청 {want_parent or '없음'}")
    if bad:
        sys.exit("\n★재조회 결과가 요청과 다름: " + " · ".join(bad) + " — 페이지를 직접 확인할 것.")


if __name__ == "__main__":
    main()
