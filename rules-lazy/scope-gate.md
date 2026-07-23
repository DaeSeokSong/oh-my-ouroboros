# Scope Gate — 작업 범위 사전 합의 게이트

> **로드 시점**: 코드 수정 작업 시작 시 (Edit/Write 호출 직전)
> **비용 모델**: Pro/Max 구독 토큰만 (추가 비용 없음)

---

## 목적

ralph 루프, G-E Loop 등 다회 라운드 작업에서 매 수정마다 input-needed 알림이 발생하는 것을 방지한다.

작업 시작 시 **1회** 사용자에게 수정 대상 파일 목록을 보고·승인받고, 그 범위 안에서는 자동 수정을 허용한다. 사전 합의된 범위를 벗어난 수정·삭제 시도가 발생하면 PreToolUse hook이 자동으로 block하고 input-needed 알림을 발송한다.

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
  - 범위 외 → PreToolUse hook이 block + 사용자 확인 요청
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

1. 호출된 도구의 `file_path` 추출
2. `~/.claude/scope/` 에서 최신 scope 파일 로드
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

## 예외 (scope-gate 비적용 영역)

| 경로 | 적용 여부 | 이유 |
|------|---------|------|
| `~/.claude/` 하위 (메타 작업) | **비적용** | 룰·스킬·에이전트 자체 수정 — 메타 작업 |
| `~/.claude/projects/` | **적용** | 런타임 디렉토리 |
| `~/.claude/jobs/` | **적용** | 런타임 디렉토리 |
| `~/.claude/teams/` | **적용** | 런타임 디렉토리 |
| `~/.claude/daemon*` | **적용** | 런타임 디렉토리 |
| `~/.claude/scope/` | **비적용** | scope-gate 자기 자신의 데이터 디렉토리 |

> 런타임 디렉토리(`projects/`, `jobs/`, `teams/`, `daemon*`)는 agent가 프로그래매틱으로 읽고 쓰는 경로이므로 scope 합의 대상에 포함.

---

## hook 등록 참조

hook은 이미 `settings.json`의 `PreToolUse` 배열에 등록돼 있다 (2026-07-10 stale 문구 정정 — 신규 머신 세팅은 `config/hooks/README.md`).
**동작 특성**: scope JSON 미등록 시 게이트는 통과(pass-through) — 등록 없이는 보호 효과가 없는 opt-in 게이트다. 등록 트리거는 ralph/G-E 진입 시 main (`rules-lazy/qa-process.md` § 5-Gate).
