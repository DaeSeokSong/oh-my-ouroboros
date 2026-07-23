---
description: "Use when: 논문 검색·읽기·분석 — '논문 찾아', '논문 서칭', arXiv/CVPR/ICCV/NeurIPS/ICLR/ICML/ECCV 키워드. 9개 소스 병렬 검색 + DOI 검증 + PDF 전체 정밀 읽기 + 리뷰 문서 저장."
model: sonnet
---

# /paper-read 스킬

> **목적**: 논문을 정확히 찾고, 한 단어도 놓치지 않고 읽으며, 완전한 리뷰 문서를 남긴다
> **에이전트 구성**: searcher → scout → researcher×3 (병렬) → qa → docs
> **모든 에이전트**: subagent 방식 (단방향, 상호 통신 없음)

---

## Step -1 — 입력 유형 감지 (MANDATORY — 최우선 실행)

$ARGUMENTS를 수신한 즉시 아래 기준으로 유형을 판별한다.

| 입력 패턴 | 유형 | 이후 흐름 |
|----------|------|---------|
| `/`, `~/`, `./` 로 시작 또는 `.pdf` 확장자 포함 | 로컬 PDF | → Step 0-L 진입 |
| arXiv ID (숫자 4자리.숫자 5자리), URL, 키워드 | 온라인 논문 | → Step 0 (기존) |

### Step 0-L — 로컬 PDF 처리

> **전제**: `pdf` 스킬이 설치되어 있어야 한다.
> 미설치 시 사용자에게 안내:
> ```
> ⚠️ 로컬 PDF 처리를 위해 pdf 스킬 설치가 필요합니다.
> 설치 명령: npx skills add anthropics/skills --skill pdf
> 설치 후 다시 실행해 주세요.
> ```

**처리 흐름**:
1. 파일 존재 확인 (`ls {경로}`)
2. markitdown으로 텍스트 추출 시도:
   ```bash
   uv run python3 -c "
   from markitdown import MarkItDown
   md = MarkItDown()
   result = md.convert('{경로}')
   print(result.text_content[:500])
   "
   ```
   → 실패 시 pdfplumber 폴백 (Step 2.5와 동일 방식)
3. PDF 첫 페이지에서 제목·저자·연도 자동 추출 → 논문명 결정
4. `{MEMORY_ROOT}/papers/{논문명}/` 폴더 구조 생성
5. **Step 1·2·2.5 건너뜀** → Step 3 (전체 정밀 읽기)로 직행
6. 이후 Step 3~6 동일 흐름 적용

**Mem0 중복 확인**: Step 3 진입 전 T09 (paper-read 시작 전 검색) 동일하게 적용

---

## Step 0 — 시작 전 확인 (MANDATORY)

```
1. 논문 정보: 제목 / arXiv ID / URL / 키워드 중 하나
2. 장기 메모리 경로 (기본값: ~/workspace/_data/workspaces/user/.claude/long-term/ — `~/.claude/long-term` 금지)
```

확인 후 `{MEMORY_ROOT}/papers/{논문명}/` 폴더 구조 생성 계획 수립.

---

## § Mem0 논문 메모리 (MANDATORY)

- **읽기 전**: Mem0 검색으로 중복 방지 → mem0-auto.md T09 참조. 이미 리뷰 완료 시 재활용.
- **읽기 후**: 각 논문 리뷰 완료 시 저장 → mem0-auto.md T08 참조
- **citation-verifier 검증 후**: → mem0-auto.md T21 참조(source=citation-verifier)
- **Consensus 종합 후**: → mem0-auto.md T08 참조 (source: "paper-read-consensus")

---

## § Consensus 모드 — 교차 검증 (선택)

```
/paper-read 수신 → 논문 수집 완료
  │
  ├─ N ≤ 2편 OR 목적 = 단순 읽기 → 일반 모드 (researcher 1명 전체 읽기)
  └─ N ≥ 3편 AND (비교/검증 목적 OR --consensus 명시)
      → "consensus 모드로 분업 읽기 + 교차 검증 진행할까요?" 질문
      → Y: consensus 모드 / N: 일반 모드
      → /discuss에서 호출 시: discuss가 결정한 모드로 진행
```

**researcher 수 결정**:

| 수집 논문 수 | researcher 수 | 배분 |
|------------|-------------|------|
| 2편 | 2명 | 각 1편씩 |
| 3~4편 | 2명 | 각 2편씩 |
| 5~6편 | 3명 | 각 2편씩 |
| 7~9편 | 3명 | 각 2~3편씩 |
| 10편+ | 사용자에게 핵심 6편으로 축소 제안 |

### Consensus 실행 흐름

**Phase 1 (병렬)**: 각 researcher가 할당 논문 정밀 읽기 → 개별 리뷰 저장
`{MEMORY_ROOT}/papers/{주제}/_reviews/{researcher}_{논문명}.md`

**Phase 2 (병렬)**: 각 researcher가 자기 논문 제외 모든 리뷰 읽기 → 찬반 의견 작성
→ 모든 논문에 원저자 1명 + 교차 검증 2명 = 3명 전원 의견 확보

**Phase 3 (main/opus)**: 리뷰 + 교차 검증 종합 → 주장별 찬반 테이블:

```markdown
### 주장 1: "{주장}"
| 논문 | 입장 | 근거 |
|------|------|------|
| {논문1} | ✅ 지지 | {근거} |
| {논문2} | ❌ 반박 | {근거} |
합의: ✅ 대체로 지지 (2/3) / ⚠️ 논쟁 중 / ❌ 대체로 반박
```

**모델**: Phase 1·2 = sonnet / Phase 3 = opus (최종 합의 복합 추론)

---

## Step 1 — 논문 검색 (searcher — subagent)

9개 소스 병렬 검색:

| 소스 | 방법 | 우선순위 |
|------|------|---------|
| Semantic Scholar | `api.semanticscholar.org/graph/v1/paper/search?...` | 1 |
| arXiv | `arxiv.org/search/?query=...` | 2 |
| CVF Open Access | `openaccess.thecvf.com/` (CVPR/ICCV/ECCV) | 3 |
| OpenReview | `api.openreview.net/notes?...` (ICLR/NeurIPS) | 4 |
| HuggingFace Papers | `huggingface.co/papers/trending` + 검색 | 5 |
| OpenAlex | `api.openalex.org/works?search=...` (240M+ 논문, API키 불필요) | 6 |
| scientific-papers MCP | `search_papers(source="arxiv/openalex", ...)` + `fetch_top_cited` | 7 |
| arxiv-latex-mcp | LaTeX 소스 접근 — 수식 정밀 확인 시 | 8 |
| Tavily | → tavily-auto.md §1 학술 쿼리 — 소스 1~8 누락분 보강 | 9 |

> MCP 불가 시: 소스 7~9 스킵 → 소스 1~6(WebFetch) fallback

### citation-verifier 논문 신뢰도 검증 (MANDATORY — 검색 결과 확보 후)

```
1. citation-verifier 디베이트 소집(철회게이트 → 옹호+회의 병렬 → 종합)
2. 철회게이트: Crossref+OpenAlex editorialNotices 확인 (철회/정정 즉시 제외)
3. supporting/contrasting/mentioning 비율 보고
4. contrasting > 30% → ⚠️ 플래그 → 리뷰 시 주의 표시
```

> citation-verifier는 advisory·초기필터(ground truth 아님)

### CrossRef DOI 검증 (MANDATORY — DOI 있을 경우)

```
WebFetch: api.crossref.org/works/{DOI}
→ 제목·저자·발행연도 일치 확인 → 불일치 시 사용자 보고
```

**출력**: 논문 제목 / 저자·연도·컨퍼런스 / arXiv ID / DOI + CrossRef 결과 / PDF URL / 검색 소스
> 동일 논문 다중 소스 발견 시: arXiv PDF URL 우선, 없으면 CVF/OpenReview 순

---

## Step 2 — PDF 다운로드 (scout — subagent)

```
1. {MEMORY_ROOT}/papers/{논문명}/ 폴더 생성
2. playwright로 PDF URL → {논문명}.pdf 저장
3. 총 페이지 수 확인 후 main 반환
```

---

## Step 2.5 — PDF → Markdown 변환 (scout — subagent)

```bash
uv run python3 -c "
from markitdown import MarkItDown
md = MarkItDown()
result = md.convert('{MEMORY_ROOT}/papers/{논문명}/{논문명}.pdf')
open('{MEMORY_ROOT}/papers/{논문명}/{논문명}.md', 'w').write(result.text_content)
"
```

> markitdown 미설치 시: `uv add markitdown`은 **환경 변경 → 사용자 승인 후 실행**(code-execution.md — pip/uv install 자동 금지). `rules-lazy/tool-dependency-gate.md` 3택 게이트(설치 위임/사용자 직접/대체) 적용
> 변환 실패 시: Step 3에서 원본 PDF 직접 읽기 폴백

**저장**: `{MEMORY_ROOT}/papers/{논문명}/{논문명}.md`

---

## Step 3 — 전체 정밀 읽기 (researcher×3 — subagent, 병렬 동시 실행)

**핵심 원칙**:
- 읽기 소스: markitdown 변환본(`{논문명}.md`) 우선 → 실패 시 원본 PDF 2페이지씩 (Read 도구, `pages` 파라미터)
- 읽는 즉시 notes 파일 저장 (컨텍스트 압축 무관)
- 요약 금지 — raw extraction 후 해석 병기
- **제목·초록만으로 내용 유추·보고 절대 금지 (MANDATORY)**: 본문 미읽기 상태에서 방법론·결과·결론 추정 금지. PDF/MD 접근 불가 시 → "본문 접근 불가 — 초록 기반 제한 정보" 명시 후 보고.

### researcher-A — 동작 원리 (subagent)

추출 대상: Method/Architecture/Algorithm 섹션 전문, 수식 전체(번호·변수 정의), Pseudocode, 모델 구조, 핵심 아이디어 verbatim
저장: `notes/researcher-A-p{NN}.md` (2페이지 단위)

### researcher-B — 실험 결과 (subagent)

추출 대상: Experiments/Results/Ablation 전문, Table 전체(헤더+수치), Figure 캡션+수치, Baseline 비교, 하이퍼파라미터, 학습 세부사항(dataset/epoch/batch/optimizer)

표 추출: markitdown 변환본 Markdown 테이블 우선 → 깨진 경우 pdfplumber 폴백:
```bash
uv run python3 -c "
import pdfplumber
with pdfplumber.open('{논문명}.pdf') as pdf:
    for i, page in enumerate(pdf.pages):
        tables = page.extract_tables()
        if tables: print(f'--- page {i+1} ---'); [print(t) for t in tables]
"
```

저장: `notes/researcher-B-p{NN}.md`

### researcher-C — 맥락 및 결론 (subagent)

추출 대상: Abstract+Introduction(연구 동기·문제 정의), Related Work(선행 연구 차이), Conclusion(verbatim), Limitations, Future Work, Appendix 전문, Footnote
저장: `notes/researcher-C-p{NN}.md`

### notes 파일 형식

```markdown
# {논문명} — researcher-{A|B|C} — p{NN} ({시작}-{끝}쪽)

## 원문 추출
[verbatim 인용]

## 수식/알고리즘 (해당 시)
[수식 번호 + 전문]

## Figure/Table (해당 시)
Figure N: [캡션] → [수치]
Table N: [헤더] | [수치]

## 해석
[이 내용의 의미]
```

---

## Step 4 — 전수 검증 (qa — subagent)

체크리스트:
- [ ] Figure 1~N 전수 등장 확인
- [ ] Table 1~N 수치 추출 확인
- [ ] Eq.1~N 누락 확인
- [ ] Appendix 포함 확인 (researcher-C)
- [ ] researcher A·B·C 간 내용 모순 탐지

누락 발견 시 main 보고:
```
⚠️ 누락: Figure 3 미등장, Table 2 마지막 행 수치 누락
→ researcher-B 재읽기 필요 (p.8-9). 진행할까요?
```

저장: `{MEMORY_ROOT}/papers/{논문명}/qa-report.md`

---

## Step 5 — 리뷰 문서 작성 (docs — subagent)

> **금지 (MANDATORY)**: notes에 없는 내용을 제목·키워드에서 유추하여 기술 금지. notes 원문만 사용, 근거 파일 명시 (예: `[researcher-A-p02.md]`).

### review.md 형식

```markdown
# [논문 제목] — 리뷰

## 논문 정보
- 제목 / 저자 / 컨퍼런스·연도 / arXiv ID / PDF 경로 / 검색 소스 / 리뷰 작성일

---

## 동작 원리 (researcher-A 기반)
### 핵심 아이디어 / 수식 목록 (번호·수식·변수·의미 표) / 알고리즘 / 아키텍처 상세

---

## 실험 결과 (researcher-B 기반)
### 실험 설정 / 결과 테이블 (원문) / Figure 분석 / Ablation 분석

---

## 결론 및 한계 (researcher-C 기반)
### 핵심 주장 (verbatim) / 저자 명시 한계 / Appendix 핵심

---

## QA 검증 결과
확인 Figure N개 / 확인 Table N개 / 이슈 처리 결과

---

## 종합 해석
[이해 방식 + 파악 과정 + 가장 중요한 포인트]
```

저장: `{MEMORY_ROOT}/papers/{논문명}/review.md`

---

## Step 6 — 출력 형식 확인 (main)

```
리뷰 완성: {MEMORY_ROOT}/papers/{논문명}/review.md

Q1: PDF로도 저장할까요? (y/n)
Q2: Confluence 등 외부 문서화할까요? (y/n/s)
```

---

## 최종 폴더 구조

```
{MEMORY_ROOT}/papers/{논문명}/
  ├── {논문명}.pdf
  ├── {논문명}.md          ← Step 2.5: markitdown 변환본
  ├── notes/
  │   ├── researcher-A-p01.md
  │   ├── researcher-B-p01.md
  │   ├── researcher-C-p01.md
  │   └── ...
  ├── qa-report.md
  └── review.md
```

---

## 에이전트별 실행 방식 요약

| 단계 | 에이전트 | 실행 방식 |
|------|----------|-----------|
| Step 1 | searcher | subagent |
| Step 2 | scout | subagent |
| Step 2.5 | scout | subagent |
| Step 3-A/B/C | researcher×3 | subagent (병렬) |
| Step 4 | qa | subagent |
| Step 5 | docs | subagent |

---

## 중단/재개 규칙

- 각 Step 완료 시 main 보고 후 다음 Step 진행
- qa 누락 발견 시 → 사용자 확인 후 해당 researcher 재실행
- PDF 다운로드 실패 시 폴백 체인:
  1. HTML 버전 탐색 (arXiv HTML / Semantic Scholar / PapersWithCode)
  2. 모두 불가 → 초록·메타 기반 제한 리뷰 + "전문 미확보" 명시
  3. 초록도 불충분 → PDF 수동 업로드 요청
