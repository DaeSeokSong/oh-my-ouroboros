"""Confluence 페이지를 **본문 재생성 없이** 리터럴 치환으로 고친다 (REST v2 직접 호출).

■ 왜 이 스크립트가 필요한가 (판단 근거 이식 — 2026-08-05)
Confluence는 부분 수정 API가 없어 **본문 전체**를 되보내야 하고, 빈 body를 보내면 페이지가
백지가 된다. 그런데 대화형 도구(MCP)로 고치려면 그 본문을 **모델이 다시 출력**해야 하므로
본문 크기가 곧 출력 토큰이 된다. 실측: 저장 형식 56,363자 = 약 4.8만 토큰
→ 1턴 전송 한도 초과. 중간에 잘리면 잘린 본문이 그대로 저장돼 페이지가 손상된다.
그래서 **본문이 모델을 거치지 않는 경로**를 만든다 — 스크립트가 받아서, 고치고, 올린다.

■ 안전 규약 (전부 이 위키에서 실제로 겪은 사고에서 나왔다)
  ⓐ 치환 앵커가 **정확히 1회** 일치할 때만 적용한다. 0회·2회 이상이면 아무것도 고치지 않는다.
     엉뚱한 자리를 고치는 것보다 실패하는 편이 낫다.
  ⓑ 적용 전 현재 본문을 로컬 파일(0600)로 백업한다(되돌릴 수 있어야 한다). probe·dry-run 도 백업을 쓴다.
     앵커는 원문 위치 기준으로 한 번에 치환하며, 앵커끼리 겹치면 중단한다.
  ⓒ `--probe`로 먼저 실제 마크업을 확인한다 — 저장 형식은 대화형 도구가 보여 주는 HTML과
     표기가 다르다(매크로가 `<ac:structured-macro>`, 기호가 `&sigma;`·`&mdash;`, 정렬이
     `text-align: center;`, 색이 `rgb(...)`). 앵커를 눈으로 지어내면 반드시 빗나간다.
  ⓓ 기본은 dry-run이다. 실제 쓰기는 `--apply`를 명시해야 한다.
  ⓔ 적용 후 백업본과 표·행·매크로·펼치기·패널·링크·첨부 **개수를 대조**해야 한다 —
     이 스크립트는 그 안내문만 출력하며 대조는 실행자(main)가 따로 한다(자동 대조 아님).
     "새 문장이 보인다"는 성공 판정이 아니다. 개수가 줄었으면 무언가 소실된 것이다.

■ 자격증명
  `~/.atlassian_token` (chmod 600, 1줄=이메일 / 2줄=토큰) 또는 환경변수
  CONFLUENCE_EMAIL / CONFLUENCE_API_TOKEN. 사이트는 CONFLUENCE_SITE로 바꾼다.
  ★**Atlassian 계정 API 토큰**이어야 한다(id.atlassian.com) — Bitbucket 전용 토큰·구 app
  password는 Confluence에서 거부된다. 토큰을 명령줄에 쓰지 않는 이유: 셸 히스토리·ps 출력·
  대화 로그에 남는다.

사용:
  # ① 실제 마크업 확인 (원격은 읽기만, 로컬 백업 파일은 생성)
  uv run python ~/.claude/scripts/confluence_patch_page.py --page <ID> --probe "문구1" "문구2"
  # ② 치환 계획 점검 (원격은 읽기만, 로컬 백업 파일은 생성) — patches.json = [{"label","anchor","new"}]
  uv run python ~/.claude/scripts/confluence_patch_page.py --page <ID> --patches patches.json
  # ③ 실제 반영 (골격 스탬프 + 게시 승인 필요 — 승인은 AskUserQuestion 으로 받는다(승인 줄은
  #    confluence_publish_approve.py question 이 출력). 알림 선택(--minor 여부)과 --message 가 승인 줄과 같아야 하고 한 번 쓰면 소모된다)
  uv run python ~/.claude/scripts/confluence_patch_page.py --page <ID> --patches patches.json --apply
"""

import argparse
import hashlib
import json
import os
import pwd
import sys
import time
from datetime import datetime
from urllib.parse import urlparse

import requests

SITE = os.environ.get("CONFLUENCE_SITE", "https://your-company-prod.atlassian.net")
TOKEN_FILE = os.path.expanduser("~/.atlassian_token")
SKELETON_STAMP_DIR = os.path.expanduser("~/.claude/_audit/skeleton-pass")


def _home_is_real():
    """True when env HOME resolves to the real user home (blocks a fake HOME that swaps stamp dirs and prompt log)."""
    return os.path.realpath(os.path.expanduser("~")) == os.path.realpath(pwd.getpwuid(os.getuid()).pw_dir)


def _skeleton_stamp_ok(body):
    """게시 직전 골격 대조 스탬프 확인 (doc-format-registry.md 게이트 6).

    계산식은 confluence_skeleton_check.py stamp()와 반드시 같아야 한다:
    sha256(본문 UTF-8 바이트에서 끝 공백·개행을 뗀 것) → ~/.claude/_audit/skeleton-pass/<sha256>.json (6시간 이내만 유효)
    """
    h = hashlib.sha256(body.encode("utf-8").rstrip(b" \t\r\n")).hexdigest()   # 끝 공백·개행 제거 — 스크립트·훅과 동일 계산식
    path = os.path.join(SKELETON_STAMP_DIR, f"{h}.json")
    if not os.path.exists(path):
        return False
    try:
        rec = json.load(open(path))
        t = datetime.fromisoformat(rec["time"]).timestamp()
    except Exception:
        return False
    return time.time() - t <= 6 * 3600


def auth():
    """자격증명은 **파일 우선**으로 읽는다 (토큰을 명령줄·대화에 노출하지 않기 위해)."""
    email = os.environ.get("CONFLUENCE_EMAIL")
    token = os.environ.get("CONFLUENCE_API_TOKEN")
    if (not email or not token) and os.path.exists(TOKEN_FILE):
        lines = [x.strip() for x in open(TOKEN_FILE) if x.strip()]
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


def put_page(page_id, title, version, body, message, minor=False):
    """minor=True 면 관찰자에게 알림이 가지 않는다 (조용한 수정)."""
    r = requests.put(
        f"{SITE}/wiki/api/v2/pages/{page_id}",
        json={"id": str(page_id), "status": "current", "title": title,
              "body": {"representation": "storage", "value": body},
              "version": {"number": version + 1, "message": message,
                          "minorEdit": bool(minor)}},
        auth=auth(), timeout=120,
    )
    if r.status_code >= 300:
        sys.exit(f"[실패] {r.status_code} {r.text[:500]}")
    return r.json()["version"]["number"]


def check_site(url):
    """사이트 주소가 https://<이름>.atlassian.net 인지 확인한다 (jira_comment.py site() 와 같은 규칙).

    인증 헤더가 엉뚱한 호스트로 가지 않게 한다 — 환경변수 CONFLUENCE_SITE 오염 방어(2026-10-01 감사).
    """
    p = urlparse(url.rstrip("/"))
    if p.scheme != "https" or not (p.hostname or "").endswith(".atlassian.net") or p.path or p.query or p.fragment:
        sys.exit("[BLOCKED] CONFLUENCE_SITE 는 https://<이름>.atlassian.net 형식이어야 합니다.")
    return url.rstrip("/")


def replace_by_original_position(body, patches):
    """앵커를 **원문 위치 기준**으로 한 번에 치환한다 (앵커는 원문에서 이미 1회로 검증됨).

    순차 replace 는 앞 치환의 new 가 뒤 앵커 문자열을 포함하면 엉뚱한 자리를 고친다(2026-10-01 감사).
    위치를 원문에서 정하고 뒤에서부터 치환하면 new 는 다시 검색되지 않는다. 앵커끼리 겹치면 중단한다.
    """
    spans = sorted(((body.find(p["anchor"]), p) for p in patches), key=lambda x: x[0])
    for (s1, p1), (s2, _) in zip(spans, spans[1:]):
        if s2 < s1 + len(p1["anchor"]):
            sys.exit(f"\n★앵커끼리 원문에서 겹칩니다(@{s1}·@{s2}) — 아무것도 고치지 않고 중단한다.")
    out = body
    for s, p in reversed(spans):
        out = out[:s] + p["new"] + out[s + len(p["anchor"]):]
    return out


def main():
    global SITE
    SITE = check_site(SITE)
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", required=True)
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
    a = ap.parse_args()

    title, version, body = get_page(a.page)
    print(f"[{title}] v{version} · 본문 {len(body):,}자")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs(a.backup_dir, exist_ok=True)
    backup = f"{a.backup_dir}/confluence_backup_{a.page}_v{version}_{stamp}.storage.html"
    # 본문에 내부 문서가 담길 수 있어 백업은 본인만 읽게(0600) 쓴다.
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

    if not a.patches:
        print("치환 목록(--patches)이 없어 여기서 멈춘다 (읽기만 수행).")
        return

    patches = json.load(open(a.patches))
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

    # ★한국어 문체 게이트 (2026-08-10 신설) — 룰이 있어도 매번 잊혀서 실패했다.
    #   기억이 아니라 게이트로 강제한다. 판정은 **치환 전후 비교**로 한다:
    #   조각만 보면 태그가 없어 블록이 안 잡히고, 결과 전체를 보면 기존 본문의 과거
    #   위반까지 걸려 무관한 수정이 전부 멈춘다. 늘어난 위반만 막는 것이 정확하다.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from korean_style_check import regression as _ks_regression  # noqa: PLC0415
    rc = _ks_regression(body, new_body, "치환 전후",
                        strict=not a.allow_style_violation)
    if rc:
        sys.exit("\n★한국어 문체 위반 — 게시 중단. 문장을 다시 써서 고칠 것 "
                 "(콤마로 기계 치환 금지). 정본: rules-lazy/answer-detail.md "
                 "§ 한국어 문체. 의도적으로 넘기려면 --allow-style-violation.")

    if not a.apply:
        print("dry-run 종료 — 실제 반영하려면 --apply 를 붙인다.")
        return

    # ★HOME 바꿔치기 차단 (2026-10-06 검수): 골격 스탬프·승인 장부와 세션 기록은 전부 HOME 기준이라
    #   `HOME=/tmp/가짜 ... --apply` 로 가짜 스탬프 폴더·기록을 물릴 수 있다. 훅 경로의 HOME 은 Claude Code 가 주므로 해당 없다.
    if not _home_is_real():
        sys.exit("\n★HOME 이 실제 사용자 홈과 다름 — 게시 중단. 환경변수 HOME 을 바꾸지 않은 셸에서 실행할 것.")

    # ★골격 대조 스탬프 게이트 (2026-09-02 신설) — MCP 경로는 skeleton-gate.sh, 이 경로는 여기서 막는다.
    if not _skeleton_stamp_ok(new_body):
        sys.exit("\n★골격 대조 스탬프 없음(또는 6시간 경과) — 게시 중단. 먼저 실행할 것:\n"
                 "  python3 ~/.claude/scripts/confluence_skeleton_check.py <위 새 본문을 담은 파일> "
                 "--format <프로젝트>/<양식>\n"
                 "정본: ~/.claude/rules-lazy/doc-format-registry.md 게이트 6")

    # ★게시 승인 게이트 (2026-10-06 신설, 2026-10-07 AskUserQuestion 답 기록으로 개정) — 사용자가 대상·알림·버전 설명을 확인했다는 증거.
    #   MCP 경로는 skeleton-gate.sh 가 같은 검사를 한다. 검사 규칙 정본은 confluence_publish_approve.py.
    #   dry-run·probe 는 위에서 이미 끝나므로 소모하지 않는다. 소모는 put 직전 한 번뿐이다.
    from confluence_publish_approve import check_and_consume  # noqa: PLC0415
    check_and_consume(page=a.page, notify="quiet" if a.minor else "notify", message=a.message)

    v = put_page(a.page, title, version, new_body, a.message, a.minor)
    print(f"✅ 반영 완료 — v{v}")
    print("★적용 후 검증(MANDATORY): 백업본과 <table>·<tr>·ac:structured-macro·expand·"
          "adf panel·ac:link·ri:attachment 개수를 대조할 것.")


if __name__ == "__main__":
    main()
