---
description: "Use when: 논문 Figure 생성 (TikZ 다이어그램 또는 matplotlib 데이터 플롯), '그림', '다이어그램', '시각화' 요청."
model: sonnet
---

# Figure Generation

독립적인 논문 Figure를 생성하는 경량 명령입니다.
논문팀 전체 소집 없이 Planner + Stylist + Visualizer 경량 팀만 구성합니다.
품질 기준(DPI, 폰트, 색상 팔레트, TikZ 노드 배치 등)이 이 스킬에 내장되어 있습니다.

## 자동 트리거 조건

- "Figure 생성", "그래프 그려", "다이어그램 만들어" 등 단독 Figure 작업 요청 시
- `/paper` 없이 Figure만 독립적으로 필요한 경우

## 실행 흐름

$ARGUMENTS 를 파싱하여 아래 순서로 실행:

1. Figure 유형 확인 (아래 유형 표 참조)
2. **도구 선택** (MANDATORY — 아래 선택 기준 적용):
   - 구조적 다이어그램 → TikZ
   - 데이터 플롯 → matplotlib/seaborn
3. 품질 기준 적용 (DPI, 폰트, 색상 팔레트 — 아래 §품질 기준 참조)
4. 경량 팀 구성 보고 후 사용자 승인
5. Retriever: 참조 논문 스타일 탐색 (복잡한 Figure 시 선택적)
6. Planner: 구성 요소·배치 설계
7. Stylist: 품질 기준 적용
8. Visualizer: 스크립트 생성 (Write 도구로 파일 저장, 응답에 코드 블록 금지)
9. **AI 직접 실행** (`uv run python docs/paper/figures/scripts/gen_*.py`)
10. **UX/UI 검수**: sonnet 서브에이전트로 생성된 PNG 시각 검수
11. 이슈 발견 시 스크립트 수정 → 재실행 → 재검수 (CLEAN까지 반복)
12. PDF + PNG 동시 저장 확인 후 완료 보고

## 팀 구성

| 멤버 | 모델 | 역할 |
|------|------|------|
| Planner | opus | 구성 요소 및 배치 구조 설계 |
| Stylist | sonnet | 품질 기준 적용 및 디자인 결정 |
| Visualizer | haiku | 템플릿 기반 플롯 스크립트·반복 수정 한정 — 신규 수식·복잡 레이아웃/알고리즘 로직 포함 스크립트는 sonnet(Stylist)로 격상 (model-assignment §3 Haiku 금지: 신규 로직·수식 구현) |
| Critic | opus | 논문-Figure 일치성 검토 (기본 포함) |
| Retriever | sonnet (searcher 에이전트로 spawn) | 참조 스타일 탐색 (선택, 복잡한 Figure 시) |

## 도구 선택 기준 (MANDATORY)

| 유형 | 권장 도구 | 이유 |
|------|-----------|------|
| 아키텍처 다이어그램 | **TikZ** | 절대 좌표 기반 정밀 배치, 벡터 PDF 직접 삽입 |
| 흐름도 / 비교 다이어그램 | **TikZ** | 화살표·노드 충돌 제어 |
| 수식 시각화 | **TikZ** | LaTeX 수식 네이티브 렌더링 |
| 학습 곡선 / 성능 추이 | **matplotlib** | 데이터 배열 처리 |
| 혼동 행렬 / 히트맵 | **seaborn.heatmap** | 색상 스케일 자동 처리 |
| 통계 비교 (boxplot/violin) | **seaborn** | 통계 요약 내장 |
| 임베딩 시각화 (t-SNE/UMAP) | **matplotlib scatter** | 3D 지원 |

> TikZ 스크립트: `docs/paper/figures/scripts/gen_fig_{name}_tikz.py` (파일명에 `_tikz` 접미사 필수)

## Figure 유형

| 유형 | 설명 | 권장 도구 |
|------|------|-----------|
| `curve` | 학습 곡선, 성능 추이 | matplotlib line |
| `arch` | 아키텍처 다이어그램 | **TikZ** |
| `heatmap` | 혼동 행렬, attention map | seaborn.heatmap |
| `stat` | 통계 비교 (boxplot/violin/bar) | seaborn |
| `embed` | 임베딩 시각화 (t-SNE/UMAP) | matplotlib scatter |
| `table` | 결과 테이블 | LaTeX tabular |
| `flow` | 흐름도 | **TikZ** |
| `compare` | 방법론 비교 다이어그램 | **TikZ** |

## 저장 표준

- 경로: `docs/paper/figures/images/` (없으면 생성)
- 스크립트: `docs/paper/figures/scripts/gen_{name}.py` 또는 `gen_{name}_tikz.py`
- 파일명: `fig_{유형}_{설명}_{MMDD}.pdf` + 동일명 `.png`
- 항상 PDF + PNG 동시 저장

## UX/UI 검수 (MANDATORY — 생성 후 자동 실행)

생성된 PNG를 sonnet 비전 서브에이전트로 검수:

체크리스트:
- [ ] 텍스트·박스·화살표 간 겹침 없음
- [ ] 레이블 위치가 연관 요소와 명확히 분리됨
- [ ] 화살표 이중 렌더링 없음
- [ ] TikZ 동일 앵커 양방향 화살표 없음 (한 앵커에서 양방향 출발·도착 금지)
- [ ] 텍스트가 패널 경계 밖으로 잘리지 않음
- [ ] 범례/타이틀이 다른 요소와 겹치지 않음

이슈 발견 시: 스크립트 수정 → 재컴파일 → 재검수 (CLEAN까지 반복)

---

## § Mem0 Figure 스타일 일관성

### 스타일 저장
Figure 생성 완료 시: → mem0-auto.md T15 참조

### 스타일 검색
새 Figure 생성 시 동일 논문/프로젝트의 이전 스타일 자동 검색: → mem0-auto.md T15 참조
이전 스타일 발견 → 동일 색상·폰트·레이아웃 자동 적용 / 미발견 → 사용자에게 스타일 질문

---

## § 품질 기준 (내장 — figure-style.md 대체)

### 출력 형식 우선순위
1. PDF/SVG (벡터) — 메인 제출용
2. PNG 300dpi 이상 — 웹/서브미션용
3. EPS — 일부 저널 요구 시

### 수치 기준

| 항목 | 기준값 |
|------|--------|
| DPI | ≥ 300 (래스터), 벡터 우선 |
| 폰트 크기 | ≥ 8pt (논문 본문 삽입 후 기준) |
| 선 굵기 | ≥ 1pt |
| 컬럼 폭 (single) | 3.5in (CVPR/NeurIPS/ICLR 기준) |
| 컬럼 폭 (double) | 7.0in |

### 색상 팔레트 (색각 이상자 배려 필수)

- 기본: `#0072B2`(파랑) `#E69F00`(주황) `#009E73`(초록) `#CC79A7`(분홍) `#56B4E9`(하늘) `#D55E00`(주홍)
- 금지: 빨강-초록 단독 대비 (적록색맹 약 8%)
- 코드: `seaborn.color_palette("colorblind")` 사용
- 흑백 인쇄 대응: 색상 외 선 스타일(실선/점선/파선) 병용

### matplotlib 코드 표준

```python
import matplotlib.pyplot as plt
import matplotlib as mpl

mpl.rcParams.update({
    'font.size': 10,
    'axes.labelsize': 10,
    'xtick.labelsize': 8,
    'ytick.labelsize': 8,
    'legend.fontsize': 8,
    'figure.dpi': 300,
    'savefig.dpi': 300,
    'savefig.bbox': 'tight',
    'font.family': 'serif',
    'text.usetex': False,
})

# 저장 표준
fig.savefig('figure.pdf', dpi=300, bbox_inches='tight', format='pdf')
fig.savefig('figure.png', dpi=300, bbox_inches='tight', format='png')
```

### TikZ 노드 배치 규칙

- **절대 좌표 필수**: `\node at (x,y) (name) {...}` (상대 positioning 사용 금지)
- 컬럼 축을 명시하고 레이아웃 주석으로 y좌표 체계 문서화
- `pdflatex + pdftoppm` 파이프라인으로 300 DPI PNG 자동 생성
- Colorblind-safe 팔레트(Wong 2011) 기본 포함

### Critic 최종 검토 체크리스트

- [ ] 컬럼 폭 기준 준수 (삽입 후 폰트 크기 재확인)
- [ ] 색각 이상자 팔레트 사용, 흑백 인쇄 대응 확인
- [ ] 논문 본문의 설명과 Figure 레이블 완전 일치
- [ ] 축 레이블·단위 명시 (예: Epoch, Loss, AP@0.5)
- [ ] 범례 항목이 본문 표기와 동일
- [ ] 여백 과다/부족 없음 (tight_layout 적용)
- [ ] 벡터 형식(PDF) 저장 여부

### TikZ 화살표 전용 검수 (MANDATORY — TikZ 다이어그램 시)

- [ ] **동일 앵커 양방향 금지**: 한 노드의 같은 앵커에서 두 화살표가 반대 방향으로 출발·도착하지 않음
- [ ] **화살표 관통 금지**: 화살표 경로가 다른 노드 박스 내부를 지나치지 않음
- [ ] **노드 위치 충돌 금지**: 사이드 노드가 통과 화살표와 시각적으로 겹치지 않음
- [ ] **출발·도착 앵커 명시**: `node.south`, `node.east` 등으로 명확히 지정 (자동 앵커 의존 금지)
- [ ] **화살표 방향 검증**: 데이터 흐름 방향(입력→출력)과 일치함

### 스크립트 작성 규칙 (MANDATORY)

- 100줄 이상 스크립트는 반드시 Write 도구로 파일 저장 (응답 텍스트에 코드 블록 금지)
- 응답에는 파일 경로 + 설계 결정 + 실행 명령만 기술

## /paper와의 관계

- 단독 Figure 작업 → `/figure` (경량)
- 논문 전체 / abstract / review 등 → `/paper` (전체 팀)

## 사용 예시

```
/figure curve          ← 학습 곡선
/figure arch           ← 아키텍처 다이어그램 (TikZ 자동 선택)
/figure heatmap        ← 혼동 행렬
/figure stat           ← 통계 비교 그래프
/figure embed          ← t-SNE / UMAP 시각화
/figure table          ← LaTeX 결과 테이블
/figure flow           ← 흐름도 (TikZ 자동 선택)
```
