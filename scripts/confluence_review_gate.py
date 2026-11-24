"""Confluence 게시 전 검토 관문: 자격증명 · 환자 식별자 꼴 검사와 검토본 · 게시본 해시 대조.

■ 스탬프의 뜻 (사실대로)
confluence_skeleton_check.py 가 통과 시 sha256(끝 공백 · 개행을 뗀 본문)으로 _audit/skeleton-pass/<sha256>.json 을
남긴다. 그 스탬프 함수가 먼저 scan() 을 불러 꼴이 하나라도 있으면 스탬프를 남기지 않는다. 그래서 스탬프는
«골격과 꼴 검사를 통과한 그 본문» 의 표시다. 두 게시 경로(MCP 훅 skeleton-gate.sh · confluence_patch_page.py)는
게시할 본문의 해시로 스탬프를 찾으므로 검토 뒤 본문이 바뀌면 스탬프가 없어 막힌다. main 이 읽고 검토했다는
증명은 아니다. 대상 페이지도 묶지 않는다. 두 게시 경로는 게시 본문에 scan() 을 한 번 더 돌린다(스탬프만 믿지 않게).

■ 꼴은 일반 꼴만 쓴다. 값 원문은 출력하지 않고 종류와 행 번호만 알린다(대화 기록에 비밀이 남지 않게).
산문 오탐을 줄이려고 자격증명 값은 «자격증명 꼴» 일 때만 건다: 숫자가 든 6자 이상이거나 12자 이상인 ASCII 토막.
storage HTML 은 값을 <code> 로 감싸거나 라벨과 값을 표의 다른 칸에 두므로, 표 칸 경계를 « = » 로 · 그 밖의 태그를
공백으로 바꾼 글에 같은 검사를 한 번 더 돌린다.

사용(네트워크 없음):
  python3 confluence_review_gate.py <게시본 파일 | ->                       # 꼴 검사만
  python3 confluence_review_gate.py <게시본 파일> --reviewed <검토본 파일>   # 꼴 검사 + 해시 대조
종료 코드: 0=통과 · 1=거부(stdout 에 PreToolUse deny JSON) · 2=사용 오류(파일 없음 등, stderr 한 줄)
REF: knowledge/harness/code-history/scripts__confluence_review_gate.py.md
"""

import argparse
import hashlib
import json
import re
import sys

# WHY: ci-gate-commit.sh SECRET_T1 의 토큰 꼴 + Atlassian API 토큰. 앞 글자는 소비하지 않는다(행 번호가 밀리지 않게).
_TOKEN = (r"(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
          r"|AIza[0-9A-Za-z_-]{30,}|xox[baprs]-[A-Za-z0-9-]{10,}|tvly-[A-Za-z0-9-]{20,}|m0-[A-Za-z0-9]{20,}"
          r"|AKIA[0-9A-Z]{16}|ATATT[A-Za-z0-9_=-]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----")
_CRED_NAME = (r"(?:[A-Za-z0-9]+[_-])*(?:password|passwd|api[_-]?(?:token|key)|access[_-]?token|auth[_-]?token"
              r"|secret[_-]?key|client[_-]?secret|private[_-]?key)|[A-Za-z0-9]+[_-]token")
_CRED_VALUE = r"""(?:<[^<>]{1,80}>\s?){0,3}["'`]?(?:(?=[^\s<>"'`]*\d)[^\s<>"'`]{6,}|[^\s<>"'`]{12,})"""
_PID_LABEL = r"(?:환자\s?(?:번호|ID)|등록\s?번호|차트\s?번호|병록\s?번호|patient[ _-]?(?:id|no|number)|\bMRN)"
PATTERNS = {
    "토큰 꼴": re.compile(_TOKEN),
    "자격증명 할당": re.compile(rf"\b(?:{_CRED_NAME})[\"']?\s*[:=]\s*{_CRED_VALUE}", re.IGNORECASE | re.ASCII),
    "환자 식별자": re.compile(
        rf"{_PID_LABEL}\s*(?:(?:[:=#]|은|는|이|가)\s*)?(?=[A-Za-z-]*\d)[A-Za-z0-9][A-Za-z0-9-]{{3,}}", re.IGNORECASE),
    "주민등록번호 꼴": re.compile(r"(?<!\d)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])-[1-8]\d{6}(?!\d)"),
}
_CELL_EDGE = re.compile(r"</t[dh]>\s*<t[dh][^>]*>", re.IGNORECASE)
_TAG = re.compile(r"<[^<>]*>")


def stamp_hash(body: bytes) -> str:
    # NEVER: change this formula without making the same change in the skeleton stamp of confluence_skeleton_check.py.
    return hashlib.sha256(body.rstrip(b" \t\r\n")).hexdigest()


def scan(text: str) -> list[str]:
    flat = _TAG.sub(" ", _CELL_EDGE.sub(" = ", text))
    found = {(kind, t.count("\n", 0, m.start()) + 1)
             for t in (text, flat) for kind, pat in PATTERNS.items() for m in pat.finditer(t)}
    return [f"{kind} ({line}행)" for kind, line in sorted(found, key=lambda x: (x[1], x[0]))]


def deny(reason: str) -> int:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}, ensure_ascii=False))
    return 1


def read_bytes(path: str) -> bytes:
    if path == "-":
        return sys.stdin.buffer.read()
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError as e:
        print(f"[사용법 오류] 파일을 읽을 수 없다: {path} ({e.strerror})", file=sys.stderr)
        sys.exit(2)


def main() -> int:
    ap = argparse.ArgumentParser(description="Confluence 게시 전 검토 관문")
    ap.add_argument("publish", help="게시하려는 본문 파일, - 면 stdin")
    ap.add_argument("--reviewed", help="검토한 본문 파일(해시 대조)")
    a = ap.parse_args()
    body = read_bytes(a.publish)
    hits = scan(body.decode("utf-8", errors="replace"))
    if hits:
        return deny("[검토 관문 차단] 게시 본문에 자격증명 · 환자 식별자 꼴이 있다: " + ", ".join(hits)
                    + ". 해당 값을 지운 초안으로 다시 검토할 것. 정본: ~/.claude/skills/confluence/SKILL.md § 검토 관문")
    h = stamp_hash(body)
    if a.reviewed:
        r = stamp_hash(read_bytes(a.reviewed))
        if r != h:
            return deny(f"[검토 관문 차단] 검토본 해시 {r[:12]} 와 게시본 해시 {h[:12]} 가 다르다. 검토 뒤 바뀐 본문은 다시 검토할 것.")
    print(f"통과 sha256={h}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
