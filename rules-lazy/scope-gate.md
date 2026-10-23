# Scope Gate — 작업 범위 사전 합의 게이트

> **로드 시점**: 코드 수정 작업 시작 시 (Edit/Write 호출 직전)
> **비용 모델**: Pro/Max 구독 토큰만 (추가 비용 없음)

---

## 목적

ralph 루프, G-E Loop 등 다회 라운드 작업에서 매 수정마다 input-needed 알림이 발생하는 것을 방지한다.

작업 시작 시 **1회** 사용자에게 수정 대상 파일 목록을 보고·승인받고, 그 범위 안에서는 자동 수정을 허용한다. 사전 합의된 범위를 벗어난 수정·삭제 시도가 발생하면 PreToolUse hook이 block 결정(사유 문구)을 돌려준다. 훅이 따로 알림을 보내지는 않으며, 사용자에게 보이는 것은 차단 사유뿐이다.

프로젝트 경계 검사(cwd 저장소 밖 다른 git 저장소 쓰기 차단)는 scope 등록과 무관하게 훅이 항상 수행한다(2026-09-07). **한계(훅 머리 주석과 같다)**: 어느 저장소에도 속하지 않는 경로(저장소 밖 일반 파일)는 경계 개념이 없어 훅이 통과시키므로 문구 규율만 남는다. Bash 경유 `git checkout`·`git stash`·리다이렉션도 이 훅 밖이고, 훅이 예외로 죽으면 열린 채 통과한다(cwd 가 저장소 밖인 분기만 fail-closed).

## 저장소 밖 cwd 차단 (2026-09-08 사용자 결정)

cwd 가 git 저장소 안이 아닌 세션은 **Write·Edit 가 전부 막힌다**. 저장소가 없으면 경계를 판정할 기준이 없기 때문이며, 이 검사도 scope 등록과 무관하게 항상 돈다. 뚫려 있는 길은 셋뿐이다(아래 «적용 표» 1·2행이 먼저 판정하므로, 하네스 안 경로는 이 표의 두 번째 길 이전에 정해진다).

| 예외 | 범위 |
|------|------|
| 모든 세션 통과 목록 | 적용 표 2행: `projects/<하나>/memory/*`·`knowledge/`·`doc-formats/`·`_evolve/quiz/`·`.scratch/`·자기 `scope/<session_id>.json` |
| 매니저 세션 | `[Harness] Manager` 세션은 적용 표 3행(기본값) 경로를 비 git cwd 에서도 쓴다. 1행(항상 차단)은 매니저도 못 쓴다 |
| 허용 목록 | `~/.claude/config/scope-allow.txt`(모든 서버 공통, 추적)와 `~/.claude/config/scope-allow.local.txt`(이 서버 전용, gitignore)를 합친 절대 경로 접두 아래 |

허용 목록은 한 줄에 경로 하나이고 `#` 주석과 `~` 확장을 지원하며 **사용자만 편집한다**. 서버마다 다른 경로는 서버별 파일에만 적어 pull·push 로 번지지 않게 한다(2026-10-02 사용자 결정). Claude 가 스스로 넓히면 게이트가 무의미해지므로 저장소 밖에 써야 할 때는 파일을 고치지 말고 사용자에게 추가를 요청한다.
- **증상: Bash 의 `cd` 가 세션 cwd 를 옮긴다 (2026-10-04·06 실측)**: Bash 에서 `cd` 로 저장소 밖에 나가면 그 위치가 세션 cwd 로 남아 이후 Write·Edit 가 «저장소 밖 cwd» 로 막힌다. 복구는 저장소 안으로 `cd` 하는 것이다. 다른 위치는 절대 경로로 읽어 `cd` 를 줄이고, `cd` 가 필요하면 같은 명령 끝에서 저장소로 돌아온다.

---

## 흐름

```
작업 진입 → scout 정찰 → 수정 대상 파일 N개 목록 작성
  ↓
main → 사용자에게 1회 보고:
  "이 작업에서 다음 N개 파일을 수정·삭제할 예정입니다:
   - foo.py (Edit)
   - bar.py (Edit)
   - baz/temp.json (Write)
   진행할까요?"
  ↓ (승인)
범위 등록 → ~/.claude/scope/{session_id}.json
  ↓
[ralph/coder 작업 진행]
  ↓
Edit/Write 시도:
  - 범위 내 → 자동 수행 (input-needed 알림 ❌)
  - 범위 외 → PreToolUse hook이 block (차단 사유 문구, main 이 사용자 확인 요청)
  ↓
작업 종료 → 범위 해제 (~/.claude/scope/{session_id}.json 삭제)
```

---

## 사전 보고 형식 (MANDATORY)

```
이 작업에서 다음 N개 파일을 수정·삭제할 예정입니다:
- {파일경로-1} ({Edit|Write|Delete})
- {파일경로-2} ({Edit|Write|Delete})
...

진행할까요?
```

승인 시 즉시 범위 등록 후 작업 시작.

---

## 범위 등록 JSON 구조

파일 위치: `~/.claude/scope/{session_id}.json`

```json
{
  "session_id": "...",
  "registered_at": "2026-05-18T00:00:00Z",
  "scope": [
    {"path": "/abs/path/to/foo.py", "op": "Edit"},
    {"path": "/abs/path/to/bar.py", "op": "Edit"},
    {"path": "/abs/path/to/baz/temp.json", "op": "Write"}
  ]
}
```

- `path`: 절대 경로 (상대 경로 금지)
- `op`: `Edit` | `Write` (hook은 `PreToolUse(Write|Edit)`만 가로챈다 — 파일 삭제는 Bash `rm` 경유라 이 게이트로 강제 불가. `Delete`는 scope 기록용 메타데이터일 뿐 훅 차단 대상 아님)

---

## hook 동작

`~/.claude/scripts/scope-gate.sh`가 `PreToolUse(Write|Edit)` 시 자동 호출된다.

1. 호출된 도구의 `file_path` 추출. 하네스 안 경로는 먼저 아래 «적용 표» 1~3행으로 판정한다(차단·통과·매니저 전용)
2. 4행 경로와 하네스 밖 경로는 프로젝트 경계 검사 뒤 `~/.claude/scope/{session_id}.json` 로드(scope 폴더나 이 세션의 파일이 없으면 게이트 비활성. scope 폴더가 있는데 session_id 가 없으면 차단하고 최신 파일로 대체하지 않는다)
3. 파일이 scope에 포함되어 있으면 → `exit 0` (통과)
4. 포함되어 있지 않으면 → `{"decision": "block", "reason": "..."}` 반환

---

## 자동 해제 조건

| 조건 | 처리 |
|------|------|
| 세션 종료 | `~/.claude/scope/{session_id}.json` — **자동 삭제 훅 미배선**(SessionEnd hook 없음). session_id별 파일이라 방치돼도 다음 세션과 충돌 없음. 정리는 아래 수동 삭제 또는 주기적 stale 정리에 의존 |
| 사용자가 "범위 작업 끝났어" 명시 | main이 수동으로 JSON 파일 삭제 |
| 작업 성공 종료 | main이 작업 완료 직후 JSON 파일 삭제 |

---

## 적용 표 (2026-10-17 G1 개정: `~/.claude` 전면 허용 폐지, 기본값 = 매니저만)

판정은 위에서 아래로 첫 일치다. 경로는 논리·물리 표기를 모두 대조한다. **기본값은 매니저 전용이고, 예외는 아래 세 목록(1·2·4행)뿐이다.** 열거 목록이 아니라서 새 폴더·새 최상위 파일(README.md·AGENTS.md·RULES.md·.gitignore·commands/ 포함)도 자동으로 보호된다.

| 순서 | 경로 (`~/.claude/` 아래) | 처리 |
|------|---------|------|
| 1 | `.git/**` · `sessions/**` · `_usage/**` · `_evolve/{candidates.tsv,candidates.lock,crosscheck.tsv,prompts.jsonl}` · `_audit/publish-approval/**` · `projects/*/*.jsonl` · `scope/` 안에서 **훅 session_id 와 다른 파일** | **항상 차단** (매니저도 불가, 스크립트 전용·위조 방지. 훅 설치는 `scripts/setup-harness.sh` 가 Bash 로 한다) |
| 2 | `projects/<하나>/memory/?*` · `knowledge/` · `doc-formats/` · `_evolve/quiz/` · `.scratch/` · `scope/<자기 session_id>.json` | **모든 세션 통과** (비 git cwd 에서도) |
| 3 | 1·2·4행에 없는 `~/.claude` 아래 전부 (`CLAUDE.md` · `settings*.json` · `rules/` · `scripts/` · `README.md` · `commands/` · `_evolve/` 의 나머지 등) | **매니저 세션만** 통과, 그 밖은 exit 2 (cwd 가 하네스 저장소여도 차단) |
| 4 | `jobs/` · `teams/` · `daemon*` · `projects/` 의 memory 밖 경로, 그리고 `~/.claude` 밖 전부 | 프로젝트 경계 검사 → scope 등록 검사 (종전과 같음) |

## 매니저 예외 (2026-10-17 G1)

위 3행(기본값)은 훅 입력 `session_id` 가 **`[Harness] Manager` 세션**일 때만 쓸 수 있다. 근거는 mod 의뢰서 개정 6-5 («해당 하네스 매니저 세션만 수정», 사용자 결정)와 `intent/2026-10-17-harness-audit-fixes.md`. 판정은 `~/.claude/sessions/*.json` 에서 `sessionId` 가 같은 파일을 **전부** 찾아 모두 통과해야 한다.

| 조건 | 실패 시 stderr 사유 |
|------|---------|
| 세션 파일이 있다 | `세션 파일 없음` |
| `name` 이 정확히 `[Harness] Manager` | `이름 불일치` |
| `/proc/<pid>` 가 있다 | `pid 없음` |
| `procStart` 가 `/proc/<pid>/stat` 22번째 필드와 같다(마지막 `)` 뒤 기준) | `procStart 불일치` |

`*.key` 는 읽지 않는다. `sessions/*.json` 은 일반 파일만 전부 `jq` 로 해석해 디코딩된 `sessionId` 로 비교하고 값 비교도 `jq` 안에서 한다. 64KB 초과·읽기 불가·후보의 파싱 실패는 «판정 불가 → 매니저 아님»이다. 보호 폴더(`.git`·`_evolve`·`_usage`·`sessions`·`scope`·`_audit/publish-approval`·`projects`)가 심볼릭이면 그 realpath 로 들어오는 경로도 같은 보호를 받는다. 비매니저가 핵심 경로를 고치려 하면 필요한 변경을 보고에 적어 사용자에게 알린다.

**알려진 한계** (설계에 수용)
- 세션 이름은 사용자가 정하므로 같은 이름의 다른 세션은 막지 못한다. uid 조건은 구분력이 없어 두지 않았다.
- Bash 로 `sessions/*.json` 을 위조하는 길은 Write·Edit 만 타는 이 훅이 못 막는다. `bash-write-check.sh` 의 리다이렉션·heredoc 차단이 유일한 방어다.
- 매니저 세션이 띄운 subagent 는 session_id 를 공유해 전원 통과한다. 외부 원문을 읽은 에이전트의 쓰기를 막는 `untrusted-quarantine.md` 는 훅이 아니라 문구 규율이다.
- 매니저는 3행에서 바로 통과하므로 프로젝트 경계 검사와 scope 등록 검사를 건너뛴다.
- `knowledge/` 등 허용 폴더 안의 하드링크와 Bash 로 만든 심볼릭은 경로 문자열만 보는 훅이 못 막는다.
- fail-closed(exit 2)인 곳: 매니저 판정 실패(세션 파일 읽기·JSON 파싱 실패 포함), `jq` 가 없을 때의 하네스 경로. `jq` 가 없을 때 하네스 밖 경로는 통과한다. `~/` 로 시작하는 경로는 `$HOME` 으로 풀어 판정한다.
- 4행(`jobs/` 등)은 매니저 판정과 무관하게 프로젝트 경계 검사를 따른다.

---

## hook 등록 참조

hook은 이미 `settings.json`의 `PreToolUse` 배열에 등록돼 있다 (2026-07-10 stale 문구 정정 — 신규 머신 세팅은 `config/hooks/README.md`).
**동작 특성**: scope JSON 미등록 시 게이트는 통과(pass-through) — 등록 없이는 보호 효과가 없는 opt-in 게이트다. 이 opt-in 은 적용 표 4행 경로와 하네스 밖 경로에만 해당한다. 하네스 경로(1~3행)는 scope 등록과 무관하게 먼저 판정되어, 등록이 있어도 비매니저의 3행 경로는 막히고(scope 등록은 하네스 허용을 넓히지 못한다) 매니저는 scope 검사를 건너뛴다. 등록 트리거는 ralph/G-E 진입 시 main (`rules-lazy/qa-process.md` § 5-Gate).
