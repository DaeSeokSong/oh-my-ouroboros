---
description: "Use when: 논문 작업 (abstract, section, review, figure), '논문', '초록', '피어리뷰' 키워드."
model: opus
---

# Code Based Paper

논문 작업을 시작하는 명령입니다.
논문팀 MARS 방법론, Cross-Watch 프로토콜이 내장되어 있습니다.
분석팀 협업이 필요한 경우 Cross-Watch 프로토콜을 자동 적용합니다.

## 자동 트리거 조건

- "논문", "abstract", "introduction", "method", "related work" 등 논문 섹션 작업
- Figure 생성 + 논문 본문 동시 작업
- 피어리뷰 대응

## 실행 흐름

$ARGUMENTS 를 파싱하여 아래 순서로 실행:

1. 작업 유형 확인: `figure` / `abstract` / `section` / `review` / `full`
2. 분석팀 협업 필요 여부 판단 (아래 협업 기준 참조)
3. 필요한 페르소나 선정 (아래 표 참조)
4. 팀 구성 보고 후 사용자 승인
5. tmux 패널 구성 제안 (`/setup-panels` 연동 — 사용자 승인 후 실행)
6. 작업 진행 → 중간 검토 → 최종 산출물
7. **Confluence 업데이트 제안**: `/confluence` 스킬로 논문 진행 상황 기록 여부 확인

## 페르소나 배정 기준

| 페르소나 | 모델 | 역할 |
|----------|------|------|
| Retriever | sonnet (**searcher 에이전트로 spawn** — Tavily 직접 호출 허용 주체) | 레퍼런스 논문/Figure 스타일 탐색 (Tavily 1순위 + WebSearch 보조) |
| Planner | opus | 구성 요소 및 배치 구조 설계 |
| Stylist | sonnet | 학술지 규정 맞춤 디자인 |
| Visualizer | haiku | 템플릿 기반 고화질 다이어그램/그래프 스크립트 한정 — 신규 수식·복잡 로직 포함 시 sonnet 격상 (model-assignment §3) |
| Critic | opus | 논문-코드 일치성 검토, 리뷰어 관점 평가 |

## 작업 유형별 필요 멤버

| 유형 | 필수 멤버 | 분석팀 협업 | Cross-Watch |
|------|----------|------------|------------|
| `figure` | Planner, Stylist, Visualizer, Critic | 선택 | 선택 |
| `abstract` | Planner, Critic | 필수 | **필수** |
| `section` | Planner, Critic | 선택 | 선택 |
| `review` | Critic + 분석팀 D | 필수 | **필수** |
| `full` | 전원 | 필수 | **필수** |

## Figure 작업 기준

논문팀 내 Figure 작업 시 `/figure` 스킬 품질 기준 자동 적용:
- 아키텍처/흐름도 → **TikZ** (matplotlib 금지)
- 데이터 플롯 → matplotlib/seaborn
- 생성 후 sonnet UX/UI 검수 **필수**

## Confluence 연동

논문 작업 완료 후 자동 제안:
```
Confluence 논문 페이지를 업데이트할까요?
  업데이트 내용: [변경 요약]
  /confluence 스킬로 진행합니다.
```

## 사용 예시

```
/paper figure 개선        ← Figure 품질 개선
/paper review accept 평가  ← 피어리뷰 진행
/paper abstract            ← 초록 작성/수정
/paper section method      ← Method 섹션 작성
/paper full                ← 논문 전체 작업
```

---

## § 논문팀 MARS 방법론

### 예산 인식 탐색 (Budget-Aware Search)
- 반복 시도 대신 컴퓨팅 예산 내 최고 성능 경로 탐색
- 메타데이터 추출 → EDA → 아키텍처 검색 → MCTS 기반 계획 → 모듈식 구현
- Budget-Aware MCTS: 성능 + 실행 비용 모두 고려
- Efficiency-Guided Reward: 성능 비슷하지만 실행 시간 짧은 모델 우선 선택

### 설계-분해-구현 파이프라인
- 아이디어를 데이터 로더, 모델 정의, 학습 루프 등 독립 모듈로 분리
- src, config, docs, README 기준, run_trains.py/run_tests.py로 중복 없이 구성

### 비교 성찰적 메모리
- 현재 솔루션 vs 과거 베스트 솔루션 비교 → 인과관계 추론
- 축적된 교훈: 디버깅 시 과거 해결책 제안, 새 아이디어 시 검증된 전략 추천

### 코드 독자성
- 공개 코드 유사도 60% 미만 유지
- 지식 전이는 허용 (A 시도의 깨달음을 B에 응용)

### 재귀적 개선
- 결과물 자체 평가 → 실패 원인 분석 → 다음 시도에 더 나은 전략 적용
- 사용자와 현실적/비판적 시선에서 건전한 토론

---

## § Cross-Watch 프로토콜 (논문팀)

분석팀 + 논문팀 동시 활성화 시 자동 적용.

### 논문팀의 감시 의무

- 분석팀이 코드 수정/추가 → **논문팀이 실시간 감시** (논문과 불일치 즉시 지적)
- 논문팀이 논문 수정/Figure 생성 → **분석팀이 실시간 감시** (코드 불일치/수학적 오류 즉시 지적)

### 즉시 개입 조건

1. 수식-코드-논문 간 불일치
2. 생물학적 타당성 위반
3. 사용자 의도와 다른 방향

### 개입 방식

- 상대 팀 작업 중단시키지 않고 **SendMessage로 즉시 이의 제기**
- **구체적 근거** 필수 (코드 라인, 수식 번호, 논문 문단)
- 이의를 받은 팀은 무시 불가 → 수용 또는 반박 근거 제시
- 합의 불가 → leader 중재 → 사용자 에스컬레이션

### 검증 항목

- 프로젝트 코드, 사용자 의도, 산출물 내용의 3자 일치
- 수학적/생물학적 모순 없음
- 리뷰어 관점에서 부족한 부분 없음
