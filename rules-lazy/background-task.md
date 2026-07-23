# Background Task 관리 규칙

> **로드 시점**: background task 생성 전, 실험 스크립트 실행 전
> **핵심 원칙**: background task는 사전 검증 후 목적당 1개만 생성한다

## § 사전 foreground 검증 (MANDATORY)

background 실행 전 반드시 동일 명령을 foreground로 먼저 검증한다:

1. `timeout 10 {명령}` 으로 구문·경로·인자 오류 확인
2. 오류 없이 시작 확인 → background 전환 허용
3. 오류 발생 → background 전환 금지 → 원인 수정 후 재검증

```
# ✅ 올바른 흐름
timeout 10 python3 train.py --phase 1 --dry-run   # foreground 검증
→ PASS → background 전환

# ❌ 금지 패턴
python3 train.py &   # 사전 검증 없이 바로 background
```

## § 1 논리 작업 = 1 Background Task

background task 생성 전 TaskList로 기존 task를 반드시 확인한다:

| 상황 | 처리 방법 |
|------|-----------|
| 동일 목적 task 실행 중 | SendMessage로 이어받기 또는 TaskOutput 재활용 |
| 동일 목적 task 완료됨 | TaskOutput 읽기 → 재생성 금지 |
| 관련 task 없음 | 새 background task 생성 허용 |

**금지**: 동일 명령을 검증 없이 연속 생성 (0 bytes task 양산 방지)

## § 실험 스크립트 Background 금지 조건

아래 중 하나라도 해당하면 background 실행 금지:

- `--phase`, `--stage`, `--subset` 등 **범위 한정 인자가 없는** 학습 스크립트
- 사용자가 명시적으로 background 허용을 언급하지 않은 경우
- `train.py`, `run_trains.py` 등 학습 스크립트 전체 실행 요청

> 관련: `~/.claude/rules/code-execution.md` § 코드 실행 규칙 — "코드 실행은 항상 사용자가 직접 수행"

## § 실패 시 원인 분석 후 1회 재시도

background task 실패 시 다음 순서를 준수한다:

```
1. TaskGet으로 task 상태 확인
2. TaskOutput으로 출력 읽기 → 원인 분류:
   ├─ 경로 오류 / import 오류 / 인자 오류 → 수정 후 최대 1회 재시도
   └─ 로직 오류 / 메모리 부족 / 권한 오류 → 사용자 보고 (재시도 금지)
3. 수정 후 재시도: foreground 검증 → background 전환 (§ 사전 foreground 검증 준수)
4. 2회 실패 시 → 사용자에게 원인 분류 보고 후 지시 대기
```

**금지**: 원인 분석 없이 동일 명령 반복 실행 (3회 이상 task 누적 방지)

### § Mem0 task 실패 이력

Background task 실패 원인 자동 저장 → `mem0-auto.md` T17 참조
동일 명령 재실행 전 과거 실패 자동 검색 → `mem0-auto.md` T05 참조
→ 과거 실패 발견 → 동일 원인 사전 방지
