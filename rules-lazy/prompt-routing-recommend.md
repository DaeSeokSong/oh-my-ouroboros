# 프롬프트 라우팅 — 추천 단계 (lazy)

> **로드 시점**: `rules/prompt-routing.md` Step 1.5 완료 후 추천 필요 시
> **역참조**: `~/.claude/rules/prompt-routing.md` (Step 0~1.7 포함)

---

## Step 2 — 추천 (Recommendation)

### 적용 조건
- Step 1 구체화 + Step 1.5 위임 판단이 완료된 경우
- 요청이 에이전트/규칙/스킬 매핑 대상인 경우

### 추천 테이블 제시 형식

```
📋 추천:
| # | 항목 | 추천 | 효용 | 근거 |
|---|------|------|------|------|
| 1 | 에이전트 | scout → coder | 쓰면 범위 최소화·정밀 수정, 안 쓰면 과탐색 위험 | 코드 수정 요청 감지 |
| 2 | 규칙 | qa-process.md | 쓰면 체크리스트 기반 검증, 안 쓰면 누락 위험 | 수정 후 QA 필요 |
| 3 | 스킬 | /commit | 쓰면 Jira 연동+형식 자동화, 안 쓰면 수동 포맷 | git 커밋 전 단계 |

📌 스킬 상세 (스킬 항목이 1개 이상 포함된 경우 자동 출력):
- `/commit`: git commit 전 Jira 연결·분할 기준·영어 메시지 형식 자동화
  - 전: `git commit -m "fix bug"` 수동 입력
  - 후: Jira 이슈 확인 → 파일 분할 제안 → 형식화된 메시지 초안 출력

적용할까요? (전체 Y / 선택: 번호 지정 / N)
```

### 에이전트 추천 기준
에이전트 목록·라우팅 테이블: `rules/agent-routing.md` 참조 (구 순서도는 2026-07-09 제거 — 테이블이 단일 출처)

> subagent vs teammate 구분 기준: `/discuss` 스킬 § Teammate vs Subagent 할당 기준 참조

### 규칙 추천 기준

| 감지 패턴 | 추천 규칙/스킬 |
|----------|---------|
| 코드 수정 완료 | `qa-process.md` |
| wandb run 정리/태그 정리/눈끄기·숨기기 | `/wandb-cleanup` 스킬 (3계층 태그 + visibility — /experiment보다 우선 매칭) |
| 체크포인트 정리/ckpt 정리/학습 산출물 디스크 회수 | `/ckpt-cleanup` 스킬 (wandb 태그 연동 KEEP/DELETE/HOLD — 삭제 실행은 사용자 직접) |
| 실험 설계/config 수정/wandb/Phase | `/experiment` 스킬 (워크플로우 + 재현성 + 결과 분석 내장) |
| Figure/다이어그램/TikZ/matplotlib | `/figure` 스킬 (품질 기준 내장) |
| 보안 리뷰/취약점 점검/injection·인증 우회 의심 | **security 에이전트** (라우팅 2.7) — 경량 diff는 빌트인 `/security-review`, 대규모는 claude-security 플러그인(깊이 게이트 `rules-lazy/security-scan-gate.md`) |
| 신경과학 메커니즘/도파민/세로토닌/예측 코딩 | `/neuro-explain` 스킬 |
| Confluence/컨플루언스/페이지 | `/confluence` 스킬 |
| 장시간 세션/컨텍스트 | `context-management.md` |
| 프로젝트 구조/초기 세팅 (cwd에 CLAUDE.md 없음) | `/project-init` 스킬 |

### 스킬 추천 기준

| 카테고리 | 감지 패턴 | 추천 스킬 |
|----------|----------|---------|
| **실험·연구** | wandb run 정리/태그 정리/눈끄기 (정리 목적 — 일반 wandb 언급은 아래 행) | `/wandb-cleanup` |
| **실험·연구** | 체크포인트 정리/ckpt 삭제/학습 산출물 디스크 회수 | `/ckpt-cleanup` |
| **실험·연구** | 새 실험 설계/config 수정/wandb/결과 분석 | `/experiment` |
| **실험·연구** | 재학습 없이 가중치 직접 편집(가지치기·양자화·표적 편집)·편집 기록 누적 비교 | `/weight-edit` |
| **실험·연구** | Figure 단독 생성/TikZ/다이어그램 | `/figure` |
| **실험·연구** | 논문 검색/서칭/읽기 — "논문 찾아", "논문 서칭", arXiv/CVPR/ICCV/NeurIPS/ICLR/ICML/ECCV + 논문 언급 | `/paper-read` |
| **실험·연구** | 심층 리서치/deep research/종합 조사 — 다출처 종합 리포트 필요 | `/research` |
| **실험·연구** | 논문 작업/abstract/section/review | `/paper` |
| **실험·연구** | 신경과학 메커니즘 인용/생물학적 타당성 | `/neuro-explain` |
| **보고·서사** | 연구 기록·논문 인트로·발표 스크립트·경과 서사 ("스토리로", "서사로 정리") | `/storytelling` |
| **보고·서사** | "쉽게 설명해줘"/"무슨 말이야"/비전문가 눈높이 재작성 | `/dumbify` |
| **설계·토론** | 의견 요청("어떻게 생각해")/공동 기획/판단 걸린 미지 질문 | `/solve` — **제안 없이 자동 적용** (CLAUDE.md 승인 예외 — 0단계 수렴 확인 필수, 단순 사실 질문·명확한 실행 지시엔 미적용) |
| **설계·토론** | 모호한 실행 요청(Step 1 MANDATORY 패턴 + 산출물 생성이 걸린 비자명 작업) | `/solve` § 메타프롬프트 모드 — 재질문 대신 프롬프트 초안 수렴 (Step 1 핸드오프, 첫 줄 `[메타프롬프트 모드]` 표시) |
| **설계·토론** | 아키텍처 토론/타당성 검증/비교 분석 | `/discuss` |
| **설계·토론** | 복잡한 작업/3단계 이상/teammate 협업/조건부 분기 | `/workflow` |
| **설계·토론** | 신규 프로젝트/프로젝트 구조 초기화 | `/project-init` |
| **코드·Git** | git commit 전 | `/commit` |
| **코드·Git** | 새 규칙/스킬/에이전트 정의 | `/quick-skill` |
| **코드·Git** | 규칙/스킬 eval·benchmark 검증 | `/skill-creator` (Anthropic plugin) |
| **문서** | 프로젝트 CLAUDE.md 감사/개선/점검 ("CLAUDE.md maintenance") | `claude-md-improver` (official plugin) — **프로젝트 레포 한정**, 글로벌 `~/.claude/CLAUDE.md`는 대상 제외(/harness-audit 소관 — 포인터·예산 구조를 프로젝트 템플릿 루브릭으로 오판 위험) |
| **문서** | Confluence 페이지 생성·수정 | `/confluence` |
| **문서** | Confluence 연구 기록 생성·수정 / '연구 기록', '실험 기록', '연구 노트' | `/confluence-research-record` |
| **환경** | teammate 소집 후 tmux 패널 배치 | `/setup-panels` |

> **폴백**: 위 패턴 미해당 + 스킬 필요 판단 시 → 스킬 description 필드 텍스트 매칭으로 적합 스킬 추천

---

## Step 3 — teammate 감지 시 패널 시각화 제안 (MANDATORY)

### 발동 조건
에이전트 추천 테이블에서 **teammate** 유형이 선택된 경우:
1. 팀원 수 계산 (leader 포함)
2. 레이아웃 시각화 출력 — `/setup-panels` 스킬 § 패널 레이아웃 시각화 참조
3. `/setup-panels` 실행 여부 질문 (절대 직접 실행 금지)

---

## 추천 생략 조건
- 단순 질문/대화 (main 직접 처리)
- 이미 에이전트/스킬이 명시된 요청
- 반복 패턴이 명확한 단순 수정

---

## 처리 흐름

```
사용자 요청 수신
    │
    ├─ Step 1: 구체화 필요?
    │   YES → 번호 목록 재구성 → 역제시 → 승인 대기
    │   NO  → 다음 단계
    │
    ├─ Step 1.5: 모델 위임 판단 (MANDATORY)
    │   메인 직접 처리 조건? → YES → 메인 직접
    │   Haiku 위임 조건?    → YES → Haiku subagent
    │   Sonnet 위임 조건?   → YES → Sonnet subagent
    │   불확실?             → opus subagent (분리 컨텍스트)
    │
    ├─ Step 1.7: 반복 패턴 감지? (MANDATORY)
    │   YES → [전처리 생략] 1줄 알림 → 즉시 위임
    │   NO  → 다음 단계
    │
    ├─ Step 2: 추천 필요? (에이전트/규칙/스킬 매핑 대상)
    │   YES → 추천 테이블 제시
    │   NO  → 바로 실행
    │
    ├─ Step 3: teammate 유형 포함?
    │   YES → 팀원 수 계산 → 패널 레이아웃 시각화 출력
    │          → "/setup-panels 실행할까요?" 질문 (실행 금지)
    │   NO  → 바로 실행
    │
    └─ 실행 (위임 판단 결과에 따라 subagent 또는 메인 직접)
```
