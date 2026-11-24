# 하네스 사용 기록 (W14)

> **로드 시점**: 하네스의 사용 빈도 · 훅 오작동 · 규칙 파일 읽힘 · 서브 에이전트 실행을 점검할 때 · `HOOK_ERRORS_24H` 경보가 떴을 때 · 기록 칸을 바꿀 때.
> 근거 의뢰서: `intent/2026-11-24-harness-review-six-items.md` 개정 2 W14. 사용자 결정: 방식 «빈 곳만 개별 기록» · 내용 «이름 · 시각 · 결과 · 소요만» · 훅 기록 범위 «모든 command 훅».

## 1. 기록 다섯 가지

모두 `~/.claude/_usage/<폴더>/YYYY-MM-DD.tsv` 이다. 머리 줄이 없고 모드는 600 이다. 한 줄은 덧붙이기 한 번으로 쓰고 4KB 를 넘지 않는다. 빈 칸은 `-` 로 쓴다. 기기 로컬이고 git 이 추적하지 않는다.

| 폴더 | 쓰는 곳 | 칸 |
|---|---|---|
| `hook-runs` | `scripts/hook-deny-wrap.sh`(차단 훅 11개와 `--log-only` 로 감싼 나머지 command 훅) · `scripts/usage-log.sh`(자기 실행) | time · session8 · caller · event · hook · tool · rc · verdict(pass · deny · error · killed) · ms |
| `tool-use` | `scripts/usage-log.sh`(PostToolUse · PostToolUseFailure) | time · session8 · caller · tool · ok(1 · 0) · ms(입력의 `duration_ms`) |
| `rule-reads` | `scripts/usage-log.sh`(PostToolUse 의 Read · InstructionsLoaded) | time · session8 · caller · how(`read` · `loaded:<load_reason>`) · 하네스 뿌리 기준 상대 경로 |
| `agent-runs` | `scripts/usage-log.sh`(launch 줄) · `scripts/usage_log_agent.py`(stop 줄) | launch: time · session8 · caller · launch · agent_id · subagent_type · model 인자 · effort 인자 · name 인자(1 · 0) / stop: time · session8 · caller · stop · agent_id · agent_type · 관측 model · 관측 effort · input · output · cache_read · cache_write · ms · status |
| `session-events` | `scripts/usage-log.sh`(SessionStart · SessionEnd · PreCompact · PostCompact) | time · session8 · kind(`start:<source>` · `end:<reason>` · `precompact:<trigger>` · `postcompact:<trigger>`) · model |

- caller 는 훅 입력의 공통 칸 `agent_id` 앞 8자이고 없으면 `main` 이다. 공통 칸은 `"hook_event_name"` 앞에서만 찾는다(도구 입력 속 `agent_id` 를 호출 주체로 잡지 않게).
- 이름 칸은 `[A-Za-z0-9_.:-]` 만 남기고 자른다. 그래서 `mcp__서버__도구` 꼴 도구 이름이 온전히 남고 탭 · 개행은 줄을 깨지 못한다.
- verdict: 기존 방식(차단 훅)은 종료 코드 2 나 JSON 거부 꼴이면 deny 다. `--log-only` 는 종료 코드만 본다(0 pass · 2 deny · 그 밖 error). 감싸는 쪽이 TERM · INT · HUP 을 받으면 killed · rc 128+n 이다.
- rule-reads 는 경로를 실제 경로로 푼 뒤 `rules` · `rules-lazy` · `skills` · `agents` · `knowledge` · `doc-formats` 아래와 `CLAUDE.md` 만 남긴다. 하네스 뿌리 밖으로 풀리는 경로(링크 포함)는 남기지 않는다.
- stop 줄의 관측 model 은 서브 에이전트 기록의 `message.model` 가운데 가장 많은 값이다. 관측 effort 는 서브 에이전트 기록의 최상위 `effort` 칸이고 없으면 훅 입력의 `effort.level` 이다. 토큰은 `message.id` 마다 한 번만 더한다. ms 는 기록의 첫 시각과 끝 시각의 차다. status 는 마지막 행두 `RESULT: <값>` 이 DONE · DONE_WITH_CONCERNS · NEEDS_CONTEXT · BLOCKED · PASS · FAIL 이면 그 값이고 다른 값이면 `other` 이며 없으면 `none` 이다.

## 2. 싣지 않는 것

- `tool_input` · `tool_response` 의 내용 · 프롬프트 · `error` · `last_assistant_message` · `compact_summary` · `custom_instructions` · cwd · `transcript_path` · 세션 id 전체.
- 예외는 위 칸에 적힌 것뿐이다. Read 의 경로는 1절 조건을 통과한 하네스 상대 경로만 싣는다. Agent 는 subagent_type · model · effort 인자와 name 인자가 있었는지만 싣는다. last_assistant_message 에서는 정해진 상태 낱말 하나만 꺼낸다.
- 서브 에이전트 기록에서는 모델 이름 · usage 숫자 · effort · 시각만 꺼낸다. 기록 파일은 `~/.claude/projects/` 아래로 풀리고 `.jsonl` 로 끝날 때만 연다.

## 3. 보고 명령

```
python3 -I ~/.claude/scripts/harness_log_report.py --days 7
```

표 네 개를 낸다. 1) 훅별 호출 · 거부 · 오류 · killed · 소요(중앙값 · p95 · 최대) 2) 도구별 호출과 실패 3) 기간 안에 한 번도 읽히지 않은 규칙 파일 4) 에이전트 종류별 실행 · 토큰 · 소요와 불일치 목록이다. 불일치 목록은 세 가지다. 관측 model 이 호출 인자나 정의 파일(`agents/<종류>.md` 머리)과 다른 건 · 관측 effort 가 호출 인자나 정의 파일과 다른 건 · effort 인자와 name 인자가 함께 온 소집이다. 기대값은 호출 인자와 정의 파일에서 계산한 값이고 관측값은 기록에서 꺼낸 값이다. 건수와 이름만 낸다.

세션 시작 점검(`scripts/harness-usage-check.sh`)은 하네스 저장소 세션에서만 최근 24시간 `hook-runs` 의 error · killed 를 `HOOK_ERRORS_24H: <훅>=<건수> …` 한 줄로 알린다.

## 4. 설치와 되돌리기

```
uv run --no-project python ~/.claude/scripts/hook_deny_wrap_install.py --dry-run            # 바뀔 항목만 보기
uv run --no-project python ~/.claude/scripts/hook_deny_wrap_install.py --apply [--events E1,E2]
uv run --no-project python ~/.claude/scripts/hook_deny_wrap_install.py --revert [--events …]  # W14 분만
uv run --no-project python ~/.claude/scripts/hook_deny_wrap_install.py --revert-all           # W9 차단 훅 감싸기까지
```

- `--apply` 는 감싸지 않은 command 훅을 `--log-only` 꼴로 감싸고 `usage-log.sh` 항목을 PostToolUse · PostToolUseFailure · InstructionsLoaded · SubagentStop · SessionStart · SessionEnd · PreCompact · PostCompact 에 더한다. 이 판의 Claude Code 가 모르는 이벤트 이름은 설정 전체를 무효로 만들 수 있으므로 `--events` 로 나눠 적용할 수 있다.
- `--events` 는 «기록 훅 항목» 에만 적용된다. 나머지 command 훅의 기록 전용 감싸기는 `--apply` 때 이벤트와 무관하게 전부 한다. `--revert --events X` 는 X 의 기록 훅 항목만 빼고 감싼 명령은 그대로 둔다. `--revert`(이벤트 없이)는 W14 분 전부를 되돌린다.
- `settings.json` 이 심볼릭 링크이면 실제 파일을 바꾸고 링크는 그대로 둔다(풀 수 없으면 중단). 읽은 뒤 파일 내용이 바뀌었으면 쓰지 않고 다시 실행하라고 알린다. 원본 사본은 모드 600 이다.
- 감싸는 스크립트가 없거나 깨졌으면 원래 명령이 그대로 돈다(W9 의 `--ping` 가드).
- 위치 인자나 `$PPID` 를 쓰는 명령은 감싸면 값이 바뀌므로 감싸지 않고 알린다.

## 5. 보존

- 다섯 폴더의 날짜 파일은 180일이 지나면 세션 시작 점검이 지운다. 하루 1회이고 이름이 `YYYY-MM-DD.tsv` 인 일반 파일만 지운다. 표지는 `_usage/.harness-logs-pruned` 다.
- 쓰기 경계 검사(`scripts/spawn-tree.sh`)에서 제외할 때는 폴더를 통째로 빼지 말고 위 다섯 폴더의 `YYYY-MM-DD.tsv` 일반 파일과 위 표지만 짚는다.

## 6. 한계

1. 실행 전에 거절된 도구 호출(스키마 검증 · 권한 거부)은 PostToolUse · PostToolUseFailure 가 뜨지 않아 `tool-use` 에 없다(공식 훅 문서).
2. killed 는 신호를 받았다는 뜻일 뿐 시간 초과와 사용자 취소를 가르지 못한다. KILL 로 죽으면 기록이 없다. 신호가 감싸는 쪽에만 오면 감싼 훅이 끝난 뒤에 남는다.
3. `--log-only` 는 출력을 잡지 않으므로 JSON 꼴 거부(`permissionDecision` · `decision`)를 보지 못한다.
4. `hook-runs` 를 쓰는 감싸는 스크립트는 통과 경로에 프로세스를 늘리지 않으려고 하드링크 수를 보지 않는다(링크 · FIFO · 폴더는 거른다). `usage-log.sh` 와 `usage_log_agent.py` 는 하드링크 수까지 본다.
5. 칸 이름은 공식 훅 문서와 이 서버의 Claude Code 2.1.323 실행 파일에서 확인했다. 판이 바뀌어 칸이 없어지면 그 칸은 `-` 다. 입력 앞 4KB 안에 없는 칸도 `-` 다. `hook_event_name` 이 입력 앞 4KB 안에 없으면 `usage-log.sh` 는 그 이벤트의 줄을 쓰지 않는다(자기 `hook-runs` 줄만 event `-` 로 남는다).
6. `--log-only` 로 감싼 훅이 신호로 죽으면 감싸는 bash 가 찍는 «Terminated» 류 한 줄이 stderr 로 나간다.
7. 감싼 훅의 명령 자체가 없으면(실행 파일 직접 호출) 셸 오류 문구의 앞머리가 원래와 다르다. 종료 코드 127 은 같다.
8. 같은 사용자가 고칠 수 있는 기록이라 위조 불가 증거가 아니다. 보고 스크립트는 칸 형식이 맞지 않는 줄을 버리고 «형식 밖 줄 N건» 으로 센다. 규칙 읽기 경로는 디스크 파일 이름과 대조만 하고 찍지 않는다.
