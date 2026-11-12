---
description: "Use when: 논문 Figure 생성 (TikZ 다이어그램 또는 matplotlib 데이터 플롯), '그림', '다이어그램', '시각화' 요청."
model: sonnet
---

# Figure Generation

독립적인 논문 Figure를 생성하는 경량 명령입니다.
논문팀 전체 소집 없이 main 이 계획 → 스타일 → 그리기 → 비평 단계를 차례로 진행합니다(계획 · 스타일 · 검수 결정은 main, 새 로직이 드는 스크립트 구현은 coder, 논문 내용 검수는 researcher 에 위임. 근거 `rules/agent-routing.md` 의 main 역할 문단과 라우팅 7행).
품질 기준(DPI, 폰트, 색상 팔레트, TikZ 노드 배치 등)이 이 스킬에 내장되어 있습니다.

## 자동 트리거 조건

- "Figure 생성", "그래프 그려", "다이어그램 만들어" 등 단독 Figure 작업 요청 시
- `/paper` 없이 Figure만 독립적으로 필요한 경우

## 그릴 주체 선택 (MANDATORY: 이 스킬을 부르기 전)

main 은 모든 그림 요청에서 이 스킬을 부르기 전에 그릴 주체를 결정 팝업(`mcp__decision-popup__ask`)으로 묻는다(2026-10-28 사용자 결정). 2026-11-10 designer 에이전트를 이 스킬로 접은 뒤로 그림은 main 이 이 스킬로 직접 만든다. 사람 글 뒤 팝업 답(모바일 모드에서는 AskUserQuestion 답)이 없으면 decision-popup mod 가 시각화 산출물 작업을 막는다(2026-11-10 사용자 결정). 막는 것은 그림 · 시각화 스킬 호출(figure · drawio-skill · dataviz · artifact-design · artifact-diagramming), Artifact 페이지 게시(asset 업로드 제외), 그림 스크립트(figures 폴더 아래 `gen_*.py`, 위치와 무관한 `gen_*_tikz.py` · `gen_*_plt.py`, `.tikz` · `.drawio`)와 `.html` · `.htm` · `.svg` 의 Write · Edit, Bash 의 그림 스크립트 실행(실행기가 명령 자리에 있고 그림 스크립트가 그 실행 대상일 때)이다. Confluence 저장 형식 html(경로에 confluence 가 들거나 파일 이름이 `*.storage.html` · `storage.html`)은 뺀다. 서브에이전트 호출에도 걸린다. 선택지는 넷이고 추천 표시는 붙이지 않는다.

그림 작업은 이 스킬 호출로 시작한다. 스킬을 부르지 않고 그림 스크립트부터 쓰거나 실행하지 않는다.

시각화 산출물(그림 · 그림 스크립트 · html · svg · Artifact 페이지)을 만들게 될 서브에이전트를 부르기 **전에** main 이 그릴 주체를 먼저 묻는다. 서브에이전트는 사용자에게 물을 수 없어 막히면 main 으로 되돌아오기 때문이다.

| 선택지 | 실행 |
|--------|------|
| figure 스킬(코드로 그리기: TikZ · matplotlib · drawio) | 이 스킬 |
| Codex 이미지 생성 | 아래 § Codex 이미지 생성 경로 |
| Grok | `skills/grok/SKILL.md` 의 `grok-ask.sh --image`(결과는 JPG) |
| 연결된 다른 에이전트 | ListAgents 의 다른 세션에 SendMessage 로 요청 |

| figure 유형 | 백엔드 | 비고 |
|------------|--------|------|
| 데이터 플롯(loss·bar·heatmap)·수식 포함·정밀 다이어그램 | **코드(TikZ/matplotlib) 강제** | 생성형은 수치를 왜곡하므로 생성형 금지 |
| 개념 일러스트·표지·발표 비주얼·추상 개념도 | **팝업 답으로 결정** | 위 네 선택지 |

### Codex 이미지 생성 경로 (Codex exec 자체 래퍼)
- 호출(**main 전용**): `bash ~/.claude/scripts/gen_gptimg.sh --model <M> --effort <E> "<프롬프트>" <절대 출력경로.png|jpg|jpeg|webp>`. 내부적으로 `codex exec` 를 거치고 구독 인증 `~/.codex/auth.json` 을 재사용한다(OPENAI_API_KEY·추가 과금 불필요).
- **실행 주체·비용 게이트 (MANDATORY, 2026-11-05 사용자 결정)**: 이미지 생성은 Codex 한도를 3~5배 빠르게 소모한다. 사용자가 팝업에서 Codex 이미지 생성을 고르면(고르는 것이 비용 승인) main 이 모델·effort 를 사이클당 1회 결정 팝업으로 묻고 직접 실행한다. 서브에이전트는 실행하지 않는다(external-model-gate 훅이 막는다). 설명문에 전송 3등급의 등급 3 내용을 넣지 않는다.
- 이미지 모델은 Codex 가 구독 전용 모델을 정하며 래퍼가 고르지 않는다. 모델·품질 정보는 https://developers.openai.com/api/docs/guides/image-generation 참고.
- 생성 뒤에는 아래 § UX/UI 검수와 같은 절차로 그림을 연다. third-party bridge(oakplank 등)는 쓰지 않고 OpenAI 공식 `codex exec` 만 쓴다.

## 실행 흐름

$ARGUMENTS 를 파싱하여 아래 순서로 실행:

1. Figure 유형 확인 (아래 유형 표 참조)
2. **도구 선택** (MANDATORY: 아래 선택 기준 적용):
   - 구조적 다이어그램 → TikZ
   - 데이터 플롯 → matplotlib/seaborn
3. 품질 기준 적용 (DPI·폰트·색상 팔레트, 아래 §품질 기준 참조)
4. 구성 계획(유형·도구·단계·저장 경로) 보고 후 사용자 승인
5. 참조 탐색: 참조 논문 스타일 탐색 (복잡한 Figure 시 선택적, 외부 자료는 searcher 소집)
6. 계획: main 이 구성 요소·배치 설계
7. 스타일: main 이 품질 기준 적용
8. 그리기: 템플릿 수준의 짧은 스크립트는 main 이 생성하고, 새 로직 구현(신규 수식 · 복잡한 데이터 가공이 든 `gen_*.py`)은 main 이 명세(입력 · 출력 경로 · 스타일 기준)를 써서 coder 에 위임한다 (Write 도구로 파일 저장, 응답에 코드 블록 금지)
9. **AI 직접 실행** (`uv run python docs/paper/figures/scripts/gen_*.py`, 근거 `rules/code-execution.md` § 예외: Figure 스크립트). `gen_gptimg.sh` 는 이 자동 실행 예외가 아니다(위 비용 게이트)
10. **UX/UI 검수**: 생성된 PNG 를 Read 로 직접 열어 시각 검수
11. 이슈 발견 시 스크립트 수정 → 재실행 → 재검수 (CLEAN까지 반복)
12. PDF + PNG 동시 저장 확인 후 완료 보고

## 단계 구성

단계는 main 이 차례로 수행한다. Stylist · Visualizer · Critic 같은 이름의 서브에이전트는 에이전트 표에 없어 소집하지 않는다(허용 목록 훅이 거부한다).

| 단계 | 수행 | 역할 |
|------|------|------|
| 계획 | main (복잡한 구조는 planner 자문 선택) | 구성 요소 및 배치 구조 설계 |
| 스타일 | main | 품질 기준 적용 및 디자인 결정 |
| 그리기 | main (새 로직이 드는 스크립트 구현은 coder 위임) | 플롯 스크립트 작성·반복 수정 |
| 비평 | main (PNG 시각 검수) + researcher (논문 본문 대조 내용 검수, 라우팅 7행 2차) | 논문-Figure 일치성 검토 (기본 포함, 아래 Critic 체크리스트) |
| 참조 탐색 | searcher 소집 | 참조 스타일 탐색 (선택, 복잡한 Figure 시) |

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
| 코드·인프라·API 정의에서 뽑는 편집 가능 구조도(논문 외) | **drawio-skill** (figure 작업 전용, 설치 시) | `.drawio` XML 산출 · 렌더링은 draw.io CLI 필요 · 논문 Figure 엔 미적용 |

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
- 스크립트: `docs/paper/figures/scripts/gen_{name}.py` 또는 `gen_{name}_tikz.py`(matplotlib 스크립트에 `_plt` 접미를 붙이는 관행 `gen_{name}_plt.py` 도 같은 그림 스크립트로 본다)
- 파일명: `fig_{유형}_{설명}_{MMDD}.pdf` + 동일명 `.png`
- 항상 PDF + PNG 동시 저장

## UX/UI 검수 (MANDATORY: 생성 후 자동 실행)

생성된 PNG 를 Read 로 직접 열어 검수한다(Codex 이미지 생성 · Grok 결과도 같다):

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
Figure 생성 완료 시: → mem0-templates.md T15 참조

### 스타일 검색
새 Figure 생성 시 동일 논문/프로젝트의 이전 스타일 자동 검색: → mem0-templates.md T15 참조
이전 스타일 발견 → 동일 색상·폰트·레이아웃 자동 적용 / 미발견 → 사용자에게 스타일 질문

### 생성 기록
Figure 생성 완료 시 파일명·유형·스크립트 경로·용도를 저장: → mem0-templates.md T31 참조

---

## 함께 쓰는 스킬 (설치 시)

이 스킬 실행 중 다른 스킬(drawio-skill 등)은 스킬 안에서 겹쳐 부르지 않고 차례로 부른다(스킬 깊이 제한 N=1, `rules/agent-routing.md` § 스킬 자율 호출).

- `example-skills:frontend-design` (설치되어 있을 때만): 웹 UI·HTML 아티팩트·대시보드 작업에만 쓴다. 학술 figure 는 아래 § 품질 기준(DPI·색각·흑백 인쇄)이 우선이라 미적용이다(대담한 타이포는 8pt 학술 규격과 충돌).
- `taste-skill` (leonxlnx/taste-skill, MIT): 웹 프론트엔드 한정이고 데이터 시각화에는 쓰지 않는다. frontend-design 과 영역이 겹치므로 작업당 하나만 로드한다.
- `drawio-skill` (Agents365-ai/drawio-skill · MIT · 2026-09-14 사용자 결정): 코드·설정 파일이나 문장 설명에서 편집 가능한 `.drawio` 구조도를 만들 때만 쓴다. 렌더링은 draw.io 데스크톱 CLI 가 있을 때만 하고 없으면 `.drawio` XML 만 낸 뒤 그 사실을 보고한다. 아이콘 스크립트는 `--embed` 로 오프라인 처리한다(기본값이 CDN 참조). 격리 검토 근거는 intent/2026-09-14-external-skill-intake.md 이다.
- `animate-skill`(delphi-ai)은 2026-07-09 라이선스 불명으로 미적용 결정이며 재검토 없이 편입하지 않는다. 웹 스킬 2종의 격리 검토 근거는 decisions.md 2026-07-09 이다. 미설치 스킬은 `rules-lazy/tool-dependency-gate.md` 3택 게이트를 따른다.

## 수식 기반 분석 PDF (사용자가 명시 요청한 경우만)

1. `article` 클래스와 `amsmath`·`amssymb`·`physics`·`geometry`(a4paper, margin=2.5cm) 패키지로 LaTeX 문서를 쓴다.
2. 저장: `docs/analysis/{주제}_{YYYYMMDD}.tex`(프로젝트 경로 미지정 시 먼저 묻는다).
3. 컴파일: `latexmk -norc -pdf -interaction=nonstopmode {파일}.tex`(`-norc` 는 `.latexmkrc` 실행 차단, shell-escape 금지). latexmk 가 없으면 `pdflatex` 를 2회 돌린다. 근거는 `rules/code-execution.md` § 예외: Figure 스크립트의 TeX 줄이다.
4. 생성된 PDF 경로를 보고한다.

---

## § 품질 기준 (내장: figure-style.md 대체)

### 출력 형식 우선순위
1. PDF/SVG (벡터): 메인 제출용
2. PNG 300dpi 이상: 웹/서브미션용
3. EPS: 일부 저널 요구 시

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

### TikZ 화살표 전용 검수 (MANDATORY: TikZ 다이어그램 시)

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
