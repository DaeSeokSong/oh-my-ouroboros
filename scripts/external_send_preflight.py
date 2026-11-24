"""외부 모델(Codex·Grok 등)에 보내기 직전, 그 도구가 **닿을 수 있는 범위**를 검사한다.

■ 왜 만들었나 (2026-08-25 실사고)
    검토용 묶음을 조립해 9개 패턴으로 검사하고 0건을 확인한 뒤 Codex 에 보냈다.
    그런데 Codex 가 실행 폴더 안의 민감 자료를 스스로 찾아 읽었다.

    원인은 하나다. **보낼 것(payload)만 검사하고 닿을 수 있는 것(context)을
    검사하지 않았다.** Codex 처럼 도구를 쥔 에이전트는 지시받은 텍스트만 읽지
    않는다. `--skip-git-repo-check` 는 git 검사를 건너뛸 뿐 탐색을 막지 않는다.

■ 그래서 무엇을 검사하나
    전송할 파일이 아니라 **작업 디렉터리 트리 전체**를 훑는다. 거기 있는 것은
    전부 나갈 수 있다고 본다.

■ 쓰는 법
    python3 external_send_preflight.py <작업디렉터리> [보낼파일 ...]
    통과하면 exit 0, 하나라도 걸리면 exit 1 이고 무엇이 어디서 걸렸는지 찍는다.
    값은 절대 출력하지 않는다.

■ 통과했다고 안전이 보장되지는 않는다
    패턴에 없는 형태의 식별자는 못 잡는다. 이 검사는 **아는 위험을 막는 장치**이지
    사람의 판단을 대신하지 않는다.
"""
import os
import re
import sys

PATTERNS = [
    ('DICOM UID', re.compile(rb'(?<![\d.])\d+(?:\.\d+){5,}'), True),
    ('DB 접속 문자열', re.compile(rb'(mysql|postgres|postgresql|mongodb)://'), True),
    ('개인키', re.compile(rb'-----BEGIN [A-Z ]*PRIVATE KEY-----'), True),
    ('AWS 키', re.compile(rb'AKIA[0-9A-Z]{16}'), True),
    # WHY: 따옴표는 선택이다(2026-09-08 검수: JSON `{"password":"…"}`·무따옴표 `PASSWORD=…` 를 놓쳤다).
    # 값이 `$VAR`·`${VAR}`·`"$VAR"` 면 변수 참조이지 값이 아니므로 제외한다(같은 검수: `--env
    # ACCESS_TOKEN="$ACCESS_TOKEN"` 를 값으로 오인해 bootstrap.sh 가 패킷에서 빠졌다).
    # 문서 예시로 흔한 자리표시자(example·xxx·your_·changeme…)도 제외한다 — 그 접두로 시작하는
    # 진짜 값은 놓치지만, 오탐이 곧 게이트 무력화라 이 쪽을 택했다.
    ('자격증명 대입', re.compile(
        rb'(?i)["\']?(password|passwd|secret|api[_-]?key|access[_-]?token|token)["\']?\s*[=:]\s*'
        rb'(?!["\']?(?:\$|example|xxx|your[_-]?|placeholder|changeme|dummy|redacted|<|\.\.\.))'
        rb'(["\'][^"\'$\s]{6,}["\']|[A-Za-z0-9][A-Za-z0-9_./+=-]{5,}(?=[\s;&|,)\'"}\]]|\Z))'), True),
    ('키 시그니처', re.compile(
        rb'(sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{30,}|tvly-[A-Za-z0-9-]{20,})'), True),
    ('환자 식별 필드', re.compile(
        rb'(?i)(sop_?uid|series_?uid|study_?uid|patient_?id|patientname)'), False),
]

SKIP_DIRS = {'.git', '__pycache__', 'node_modules', '.venv', 'venv',
             '.mypy_cache', '.pytest_cache'}
MAX_BYTES = 8 << 20
# WHY: 2026-10-01 감사: 확장자 목록 밖 파일은 내용 검사 없이 통과했고, 8MiB 너머는 말없이 잘렸다. 도구는 그 파일도 읽을 수 있다.
# 그래서 확장자와 무관하게 모두 읽고, 못 훑은 파일(한도 초과·읽기 실패·이진)은 «미검사» 로 세어 차단 판정에 넣는다.


def scan(path):
    try:
        if os.path.getsize(path) > MAX_BYTES:
            return b'', '한도(8MiB) 초과'
        with open(path, 'rb') as fp:
            data = fp.read(MAX_BYTES + 1)
    except OSError:
        return b'', '읽기 실패'
    if b'\0' in data[:8192]:
        return b'', '이진 파일'
    return data, None


def walk(root, unreadable, links):
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: unreadable.append(e.filename)):
        # WHY: 2026-10-01 P6 검수: os.walk 는 폴더 심볼릭 링크를 따라가지 않지만 codex 같은 도구는 따라간다.
        #   링크 너머는 훑지 못한 트리이므로 «미검사» 로 세어 차단한다(SKIP_DIRS 이름의 링크도 같다).
        links.extend(os.path.join(dirpath, d) for d in dirnames if os.path.islink(os.path.join(dirpath, d)))
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            yield os.path.join(dirpath, fn)


def main():
    if len(sys.argv) < 2:
        sys.exit(f'사용법: python3 {os.path.basename(sys.argv[0])} <작업디렉터리> [보낼파일 ...]')
    roots = [os.path.abspath(p) for p in sys.argv[1:]]
    for r in roots:
        if not os.path.exists(r):
            sys.exit(f'[중단] 없는 경로: {r}')

    print('검사 범위 (여기 있는 것은 전부 나갈 수 있다고 본다)')
    for r in roots:
        print(f'   {r}')
    print()

    unchecked = []
    targets = []
    for r in roots:
        if os.path.isdir(r):
            unreadable, links = [], []
            targets.extend((r, p) for p in walk(r, unreadable, links))
            unchecked.extend((os.path.relpath(u, r), '폴더 읽기 실패') for u in unreadable)
            unchecked.extend((os.path.relpath(u, r), '폴더 심볼릭 링크') for u in links)
        else:
            targets.append((r, r))

    blocked, warned, n = [], [], 0
    for root, p in targets:
        rel = os.path.basename(p) if p == root else os.path.relpath(p, root)
        data, why = scan(p)
        if why:
            unchecked.append((rel, why))
        elif data:
            n += 1
        # NEVER: 이름 대조에 절대 경로를 쓰지 않는다(절대 경로의 홈·임시 폴더 이름은 우리 몫이 아니다)
        for name, pat, is_block in PATTERNS:
            hits = len(pat.findall(data)) if data else 0
            if hits:
                (blocked if is_block else warned).append((name, rel, hits))
            nhits = len(pat.findall(os.fsencode(rel)))
            if nhits:
                (blocked if is_block else warned).append((name + '(이름)', rel, nhits))

    print(f'훑은 파일 {n}개')
    print()

    if warned:
        print('경고 (식별자 열 이름이 보인다 — 값이 아니라 이름이다)')
        for name, rel, c in sorted(warned, key=lambda x: -x[2])[:20]:
            print(f'   {name:<16} {rel[:58]:<58} {c}건')
        print()

    if unchecked:
        print(f'★ 미검사 {len(unchecked)}개 (못 훑은 파일은 안전하다고 볼 수 없어 차단한다)')
        for rel, why in unchecked[:20]:
            print(f'   {why:<12} {rel}')
        if len(unchecked) > 20:
            print(f'   … 외 {len(unchecked) - 20}개')
        print()

    if blocked:
        print(f'★ 차단 {len(blocked)}건')
        for name, rel, c in sorted(blocked, key=lambda x: -x[2]):
            print(f'   {name:<16} {rel[:58]:<58} {c}건')
        print()

    if blocked or unchecked:
        print('판정: 보내지 마라. 이 트리 밖에서 실행하거나 해당 파일을 치워라(미검사 파일은 치우거나 8MiB 이하 텍스트로 줄여라).')
        return 1

    print('판정: 통과 — 알려진 위험 패턴 없음')
    print('(패턴에 없는 형태는 못 잡는다. 이 검사가 판단을 대신하지 않는다.)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
