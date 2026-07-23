---
description: "Use when: tmux 패널 배치 필요 (teammate 구성 시), '/setup-panels', 'purge', 'cleanup' 요청."
model: haiku
---

# tmux Teammate Panel Setup

teammate 생성 후 tmux 패널을 자동 구성하는 명령입니다.

## 스크립트 경로
`~/.claude/scripts/tmux-panels.sh`

## 배치 정책

| 팀원 수 | 전략 | 메인 윈도우 | 오버플로우 |
|---------|------|-----------|----------|
| 1~4 | 1행 | Main(65%) + 1행(35%) | 없음 |
| 5~8 | 2행 | Main(55%) + 2행(45%) | 없음 |
| 9~12 | 3행 | Main(50%) + 3행(50%) | 없음 |
| 13~N | 3행+overflow | Main + 12명 | tm-1, tm-2... |

오버플로우 윈도우 간 이동: `Ctrl+b n` (다음) / `Ctrl+b p` (이전)

## 실행 절차

$ARGUMENTS 를 파싱하여 아래 순서로 실행:

1. **인자가 "cleanup"** → `tmux-panels.sh cleanup`
2. **인자가 "status"** → `tmux-panels.sh status`
3. **인자가 "purge"** → `tmux-panels.sh purge`
4. **그 외 모든 경우 (인자 유무 관계없이)**:
   - **STEP 1**: 활성 팀 config.json 자동 조회
     - `~/.claude/teams/` 하위에서 가장 최근 수정된 팀 폴더의 `config.json` 읽기
     - `members` 배열에서 `name`과 `agentType`(또는 역할 정보) 추출
   - **STEP 2**: 실제 생성된 팀원 수 확인
     - config.json에 없는 팀원은 패널 생성 대상에서 제외
   - **STEP 3**: 팀원 수만큼 패널 자동 구성
     - `tmux-panels.sh setup "name1:agentType1" "name2:agentType2" ...`
   - **팀 config가 없는 경우**: 인자로 전달된 `name:role` 형식을 그대로 사용

## 팀원 조회 방법 (코드)

```bash
# 활성 팀 config.json 경로 찾기
TEAM_CONFIG=$(ls -t ~/.claude/teams/*/config.json 2>/dev/null | head -1)

# members 배열에서 name:agentType 추출
if [ -n "$TEAM_CONFIG" ]; then
  python3 -c "
import json, sys
data = json.load(open('$TEAM_CONFIG'))
members = data.get('members', [])
for m in members:
    name = m.get('name', '')
    role = m.get('agentType', 'agent')
    print(f'{name}:{role}')
"
fi
```

## 자동 연동 워크플로우

⚠️ **반드시 아래 순서 준수** (setup → spawn 순서는 패널 파괴 유발!)

```
1. TeamCreate로 팀 생성 → Agent 도구(team_name + name 파라미터)로 각 teammate spawn  ← 에이전트 먼저 배치
2. tmux-panels.sh purge                               ← 자동 생성된 불필요 pane 제거
3. /setup-panels                                      ← 팀 config 자동 조회 후 패널 구성
4. tmux-panels.sh monitor "name" "output_file"         ← 모니터링 연결 (선택)
5. 작업 완료 후 /setup-panels cleanup                   ← 정리
```

## 사용 예시

```
/setup-panels              ← 활성 팀 config 자동 조회 후 실제 팀원만 패널 구성
/setup-panels cleanup
/setup-panels status
/setup-panels purge
```

> ⚠️ 팀이 없는 경우에만 수동 지정 허용:
> `/setup-panels bio-critic:비판적검토자 tech-analyst:기술분석가`

---

## 패널 레이아웃 시각화 (팀원 수별)

teammate 구성 시 아래 레이아웃 중 하나를 응답에 포함하고 `/setup-panels` 실행 여부를 사용자에게 질문.

#### 2명 (leader + 1 teammate)
```
┌─────────────────────┬─────────────────────┐
│   [leader / main]   │   [teammate-1]      │
│   (중재자)           │   (전문가 A)         │
└─────────────────────┴─────────────────────┘
  Pane 0 (50%)          Pane 1 (50%)
```

#### 3명 (leader + 2 teammate)
```
┌──────────────────────────────────────────┐
│            [leader / main]               │
│            (중재자 · 50% 높이)             │
├─────────────────────┬────────────────────┤
│   [teammate-1]      │   [teammate-2]     │
│   (전문가 A · 25%)  │   (전문가 B · 25%) │
└─────────────────────┴────────────────────┘
```

#### 4명 (leader + 3 teammate)
```
┌─────────────────────┬────────────────────┐
│   [leader / main]   │   [teammate-1]     │
│   (중재자)           │   (전문가 A)        │
├─────────────────────┼────────────────────┤
│   [teammate-2]      │   [teammate-3]     │
│   (전문가 B)         │   (전문가 C)        │
└─────────────────────┴────────────────────┘
  2×2 그리드 레이아웃
```

#### 5명 (leader + 4 teammate)
```
┌──────────────────────────────────────────┐
│            [leader / main] (상단 40%)     │
├────────────┬───────────┬─────────────────┤
│ [tm-1]     │ [tm-2]    │ [tm-3]         │
├────────────┴───────────┘                 │
│ [tm-4] 전문가 D (하단 60%)               │
└──────────────────────────────────────────┘
```

#### 6명 이상
```
┌─────────┬─────────┬─────────┐
│ [main]  │ [tm-1]  │ [tm-2]  │
├─────────┼─────────┼─────────┤
│ [tm-3]  │ [tm-4]  │ [tm-5]  │
└─────────┴─────────┴─────────┘
  3×2 그리드 (6명까지) / 7명 이상: 스크립트 자동 계산
```

### 사용자에게 제시할 메시지 형식
```
🖥️ teammate {N}명 구성 예정입니다.
[레이아웃 시각화 삽입]
/setup-panels를 실행할까요?
  실행하면: tmux-panels.sh setup → monitor 순서로 패널 구성 (서브커맨드: setup/monitor/purge)
  실행 안 하면: 현재 단일 패널로 teammate 소집 (출력 혼재 가능)
```
