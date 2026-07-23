---
description: "Use when: Confluence 페이지 생성·수정, 'Confluence', '컨플루언스', '페이지', Jira 이슈 언급. 포맷·수식·레이아웃 기준 포함."
model: sonnet
---

# Confluence Page Workflow

> **스킬 경계**: Confluence 페이지 생성·수정 전용. 연구 기록은 `/confluence-research-record`, 워크플로우 설계는 `/workflow` 사용.

## 자동 트리거 조건

- Confluence 페이지 생성/수정 요청
- `mcp__claude_ai_Atlassian__updateConfluencePage` / `createConfluencePage` 호출 전
- Confluence URL 또는 페이지 ID가 대화에 등장

## 실행 흐름

0. **프로젝트 양식 레지스트리 조회 (§0)** — 등록 양식 있으면 §1 질문 생략 가능
1. 포맷 참고 페이지 확인 (§1 — §0 미등록 시)
2. 연구 페이지라면 연구 동기 확인 (§1-1)
2.5. **콘텐츠 범위 게이트 (§1-2)** — 작업 경위 배제, 본문 작성 전 필수
3. 페이지 구조 표준 적용 (§2)
4. 수정 전 3단계 확인 (§3)
5. 업데이트 실행 (is_minor_edit, version_comment 적용)
6. 레이아웃 수동 설정 안내 (너비 최대, 밀도 압축)

---

## §0. 프로젝트 양식 레지스트리 조회 (MANDATORY — §1보다 먼저, 2026-07-20)

`~/.claude/doc-formats/<프로젝트>/` 존재를 확인한다 (존재=등록, 규약: `rules-lazy/doc-format-registry.md`):
- **등록됨** → 양식 인덱스(README) Read → 해당 페이지 유형 양식 적용. 양식이 기준 페이지 ID를 지정하므로 §1 참고 페이지 질문 생략 가능
- **미등록** → §1 진행 + 레지스트리 § 부트스트랩 제안 (어느 서버·어느 프로젝트든 동일)

## §1. 포맷 참고 페이지 확인 (MANDATORY — 생성/수정 전)

```
포맷 참고할 페이지를 선택해주세요:
1. [이전 작업 페이지 제목] — [URL]
또는 직접 URL 제공
```

**기준 레퍼런스**: project-A (ID: 1363017733) — 목차·최대 너비·압축 밀도 기준

## §1-1. 연구 페이지 콘텐츠 품질 기준 (연구 관련 페이지 시)

**연구 동기 확인 (신규 연구 페이지 MANDATORY)**:
```
이 연구를 시작하게 된 계기나 문제 의식을 알려주세요.
```
수집한 동기를 Overview 첫 문단 + Motivation & Background 섹션에 반영.

**포함 필수 항목**: Research Motivation / Abstract·Overview / Motivation & Background / Method(수식·아키텍처) / Implementation Details / Experiment Design(**설계 근거** 포함) / Results / Related Work

## §1-2. 콘텐츠 범위 — 작업 경위 배제 (MANDATORY, 2026-07-23 사용자 지시)

> **룰**: **작성하는 컨플 또는 이미 작성된 컨플에 있는 내용 외에, 작업을 진행하며 있었던 내용은 기입하지 않는다.**
> 하네스 흔적 금지(에이전트명·스킬명·`/goal` 등 슬래시 커맨드·mem0·subagent)와 **동급의 MANDATORY** 이며, 그 범위를 "AI 도구 이름"에서 **"작업 경위 전반"**으로 확장한 것이다.

**Why**: 페이지는 *제품·시스템의 사실*을 남기는 문서지, *그 사실에 도달하기까지의 경위*를 남기는 작업 로그가 아니다. 경위가 섞이면 독자가 결과와 시행착오를 구분하지 못하고, 문서가 세션 기록처럼 읽힌다. (2026-07-23 실측: 두 DR 페이지에서 중간 오측정 정정·감시 스크립트 오판·작업 회고 절이 지적돼 일괄 삭제)

**판정 기준 (작성 직전 각 블록에 적용)**

| 질문 | 남긴다 | 뺀다 |
| --- | --- | --- |
| 이 내용은 무엇의 속성인가 | **제품·시스템**(설계·동작·수치·결과·한계) | **작업 경위**(내가 그 결과를 얻기까지) |
| 문서만 읽는 사람에게 필요한가 | 필요 — 결론·근거를 이룬다 | 불필요 — 세션 참여자만 아는 맥락 |

**배제 대상 (예시 — 전부 실측 삭제 사례)**
- 중간 오측정과 그 정정 ("초기 재측정치 15:47 은 사실 warm 하이브리드였다", "중간에 본 83.00% 는 100건 표본 값")
- 내 도구·스크립트의 결함과 수습 (감시 스크립트 오판, 구동 절차의 발췌 미첨부, 자동화의 승인 게이트 통과)
- 작업 회고·교훈 절 ("이번 작업의 핵심 요소", "X 가 Y 보다 낫다" 류 방법론 반성) — **단, 그 방법론 자체가 페이지의 선언된 주제이면 본문**이다
- 재작업 판단 ("재계측 불요", "따라서 다시 재지 않았다"), 세션 진행 서사("지적을 받아", "확인 결과", "정직한 기록")

**경계 (과잉 삭제 금지)**
- 제품이 실제로 낸 실패·회귀와 그 근본 수정은 **남긴다** — 시스템의 속성이다. 다만 서술은 "작업 중 터진 사고"가 아니라 **"시스템의 결함 → 보강"** 으로 쓴다.
- 문서의 배경·동기는 남기되, **대화 경위가 아니라 기준·문제 정의**로 진술한다 ("~라는 지적을 받았다" ✗ → "기준은 ~이다" ✓).
- 수치의 해석에 필요한 주석은 남기되 **원인이 작업 경위면 중립화**한다 ("내가 정책을 고치느라 7분" ✗ → "파이프라인 외부 대기 7분 제외" ✓).
- **연구 기록의 실험 서사는 배제 대상이 아니다**: `/confluence-research-record`의 동기→결과→해석→후속 서사는 *연구 자체*의 경위(=페이지의 선언된 주제)라 본문이다 — 이 룰이 배제하는 것은 *세션 작업*의 경위다.

---

## §2. 페이지 구조 표준 (MANDATORY)

```
[목차 매크로]          ← 최상단 고정
[본문 내용]
[펼치기: 출처]         ← 최하단 고정
[펼치기: 관련 링크]    ← 최하단 고정 (출처 아래)
```

**목차 (TOC)** — Atlassian 네이티브 `/목차` 기능 사용:
```xml
<ac:structured-macro ac:name="toc"/>
```

**출처 펼치기**:
```xml
<ac:structured-macro ac:name="expand">
  <ac:parameter ac:name="title">출처</ac:parameter>
  <ac:rich-text-body><ul><li>[컨텍스트]: [소스명] / [URL]</li></ul></ac:rich-text-body>
</ac:structured-macro>
```

**관련 링크 펼치기** (출처 아래):
```xml
<ac:structured-macro ac:name="expand">
  <ac:parameter ac:name="title">관련 페이지 / 이슈</ac:parameter>
  <ac:rich-text-body><ul>
    <li>[Confluence 페이지 제목] — [URL]</li>
    <li>[Jira 이슈 키] [이슈 제목] — [URL]</li>
  </ul></ac:rich-text-body>
</ac:structured-macro>
```

---

## §3. 페이지 수정 전 3단계 확인 (MANDATORY)

> 사전 확인 없이 Confluence 페이지를 수정하지 않는다.

**① 업데이트 여부 확인**:
```
업데이트할까요?
  내용: [변경 요약 1~2줄]
  대상: [페이지 제목] (ID: XXXXXXXXXX)
```
> 대상이 2페이지+ 또는 계층 수정이면 '내용' 대신 **수정 계획 트리**(배지 `[수정]`/`[신규]`/`[삭제]` + 10~20자 동사형 요약, 유지 항목 생략)로 보고 — 형식 정본: `rules-lazy/answer-detail.md` § 수정 계획 트리 보고.

**② 관찰자 알림**:
```
A) 알림 발송 (is_minor_edit=false)
B) 조용히 업데이트 (is_minor_edit=true)
```

**③ 버전 설명**:
```
버전 기록에 남길 설명을 입력해 주세요. (예: "실험 결과 3종 추가")
```

응답 수령 후 `is_minor_edit`과 `version_comment` 적용하여 업데이트 실행.

---

## §4. 수식 표기 기준 (MANDATORY)

**금지**: `$$...$$`, `\(...\)`, `\[...\]` 등 raw LaTeX — Confluence에서 렌더링 불가.

**권장 방식 (우선순위)**:

1순위 — Atlassian LaTeX 매크로 (Math/LaTeX 플러그인 설치 시):
```xml
<ac:structured-macro ac:name="latex">
  <ac:plain-text-body><![CDATA[\Delta W = \sum_i g_i \cdot B_i A_i]]></ac:plain-text-body>
</ac:structured-macro>
```

2순위 — Unicode 수학 기호: `ΔW = Σᵢ gᵢ(x, rᵢ) · Bᵢ·Aᵢ`

3순위 — 코드 블록(monospace): 복잡 수식, 플러그인 없을 때

수식 삽입 전 Math/LaTeX 매크로 설치 여부 사용자 확인 필수.

---

## §5. 페이지 너비 (MANDATORY)

모든 페이지 너비는 항상 **최대**:
```xml
<ac:layout>
  <ac:layout-section ac:type="full-width">
    <ac:layout-cell>[본문]</ac:layout-cell>
  </ac:layout-section>
</ac:layout>
```

테이블: `<table style="width: 100%;">` 적용.
업데이트 후 안내: "페이지 우상단 `⋯` → 페이지 너비 → **최대** 설정 필요"

---

## §6. 페이지 밀도 (MANDATORY)

모든 페이지 밀도는 **압축 밀도(Compact)** — UI 수동 설정 필요.
업데이트 후 안내: "페이지 우상단 `⋯` → **밀도 → 압축 밀도** 설정 필요"

**3대 레이아웃 기준**:

| 설정 | 기준값 | 방법 |
|------|--------|------|
| 목차 | Atlassian 네이티브 TOC | 편집기 `/목차` |
| 너비 | 최대 (Full-width) | `⋯` → 페이지 너비 → 최대 |
| 밀도 | 압축 밀도 (Compact) | `⋯` → 밀도 → 압축 밀도 |

---

## §7. Storage Format 무결성 검증 (MANDATORY — 기존 페이지 수정 시)

> MCP `getConfluencePage`(claude_ai_Atlassian)로 가져온 storage HTML이 JSON 다중 직렬화로 매크로 속성 따옴표가 깨지는 현상 (2026-03-03 project-A, 3,625건)

**증상**: 모든 매크로(toc, expand 등) "확장 기능 로드 오류"
**원인**: `ac:name="toc"` → `ac:name='\"toc\"'` 이중 변환
**수정**: `~/.claude/scripts/fix_confluence_html.py` — `fix_corrupt_macro_attrs()` 사용

**예방 (MANDATORY)**: 기존 storage HTML 가져와 수정 후 올리는 경우:
1. `='\"` 패턴 존재 확인 → 발견 시 `fix_corrupt_macro_attrs()` 적용 후 업로드
2. 신규 HTML 직접 작성 시는 해당 없음

---

## §8. ADF Math Block 백슬래시 무결성 검증 (MANDATORY — 기존 페이지 수정 시)

> storage HTML의 ADF 수식 블록 body에서 `\command` → `\\command` 이중 변환 현상 (2026-03-03, 42건)

**증상**: 수식 블록이 `\\mathcal{L}` 등 raw 텍스트 표시
**적용 대상**: Atlassian Marketplace "LaTex Math Block" (Forge 앱)
**수정**: `fix_confluence_html.py` — `fix_adf_formula_backslash()` 사용

---

## §9. ADF Math Block 리터럴 `\n` 무결성 검증 (MANDATORY — 기존 페이지 수정 시)

> body 파라미터에 리터럴 `\n` (0x5C+0x6E) 두 문자 포함 현상 (2026-03-03, 10건)

**증상**: 수식 블록 앞뒤 불필요한 빈 줄 렌더링
**원인**: JSON 직렬화 시 실제 개행(0x0A)이 아닌 두 문자로 저장 → `strip()` 무효
**수정**: `fix_confluence_html.py` — `fix_adf_formula_literal_newlines()` 사용

**적용 순서 (MANDATORY)**: `fix_corrupt_macro_attrs()` → `fix_adf_formula_backslash()` → `fix_adf_formula_literal_newlines()` — 또는 `fix_all()` 일괄 호출

---

## §10. 기존 페이지 수정 = 최소 치환 (media·매크로 보존) (MANDATORY — 2026-07-22)

> **신규 작성이 아닌 "수정"일 때는 본문을 재생성하지 않는다.** 이미지·첨부(media 노드)와 매크로는 본문 HTML에 **불투명 ID**(`data-id`·`data-collection`·`data-media-id`·`data-local-id`)로만 참조된다. 본문을 손으로 다시 쓰거나 markdown ↔ html 왕복 변환하면 이 ID가 유실돼 **이미지가 통째로 사라지고 매크로가 깨진다**. ★근거 이식(2026-07 실측): 본문 재생성 시 첨부 이미지 전멸, 큰 본문 수기 이관 중 표 셀 누락·행 소실이 수 차례 발생. 반대로 원문 verbatim + 목표 셀만 리터럴 치환하면 media ID가 그대로 되돌아가 **기존 이미지가 보존**된다.

**수정 프로토콜 (MANDATORY)**:
1. `getConfluencePage(contentFormat="html")`로 원문을 받아 **파일에 verbatim 저장** — 엔티티(`&lt;`·`&amp;`·`&quot;`)·태그 순서·공백·이모지 불변, 저장 길이를 원문과 대조(다르면 중단). 저장 위치는 임시 폴더 규약(code-execution.md).
1.5. **§7~§9 손상 패턴 선점검 (2026-07-22 보완)**: 저장본에서 `='\"`(따옴표 깨짐, §7)·`\\command`(이중 백슬래시, §8)·리터럴 `\n`(§9) 패턴을 점검 — 발견 시 `fix_confluence_html.py` `fix_all()` 적용본을 이후 단계의 baseline으로 삼는다(길이 대조 기준도 fix본으로 갱신). 손상은 조건부 발생(2026-03 project-A 3,625건 vs 2026-07 project-B 무손상 왕복)이라 점검이 싸고 생략이 위험하다 — 손상 원문을 verbatim 재업로드하면 손상이 그대로 재기록된다.
2. **리터럴 문자열 치환만** 수행. 바꿀 각 앵커가 원문에서 **정확히 1건(count==1)** 인지 assert — 0건/2건 이상이면 중단하고 앵커를 앞뒤 문맥까지 확장해 유일화. 정규식보다 리터럴 우선. (Edit 도구로 저장 파일을 고치면 old_string 유일성 요구가 count==1을 자연 집행한다.)
3. 치환 전후 `<table>`/`<tr>`/`<td>`·media 노드 개수를 대조 — 목표 외 증감 시 중단(아무것도 쓰지 않음). 부분 적용된 페이지가 가장 위험.
4. 통과 시에만 `updateConfluencePage`에 **전체 본문 그대로**(치환분만 반영) 전송 → 재조회로 반영·인접 문단 무손상 확인.

**금지**: 수정 시 본문 전체 재작성 / markdown으로 받아 편집 후 html 재삽입 / media·매크로 노드 ID 임의 생성·삭제 / 큰 본문을 손으로 옮겨 담기(전사 오류·매크로 유실 원인).

**경계**: 이 규칙은 **수정(update)** 전용. 신규 페이지 생성(§1~§6)에는 적용 안 됨. 또 이미지 blob 자체 교체는 MCP 불가 → 그림 **내용**이 바뀌면 참조 보존까지만 되고 사용자 수동 drag-drop이 필요하다(값만 바뀐 표와 옛 그림이 공존할 수 있으니 교체 안내 필수).

---

## Jira 작업 참조

Jira 커밋 연결, 이슈 댓글, 이슈 완료 처리 → `/commit` 스킬 참조

## § QMD (.qmd) 입력 지원

> **상세**: `agents/docs.md` § Quarto Markdown (.qmd) 처리 참조

### 트리거
사용자가 `.md` 대신 `.qmd` 파일 경로 제공 시:

1. docs 에이전트로 위임 — quarto render 변환 흐름 진입
2. 변환 결과(`.confluence` 또는 HTML)를 본 스킬의 페이지 생성/수정 흐름에 입력
3. 페이지 footer에 `.qmd` 원본 경로 명시 (재현성)

### 일반 .md vs .qmd 분기
- `.md`: 본 스킬 기존 흐름 (직접 페이지 생성)
- `.qmd`: docs 에이전트 quarto render 경유 → 본 스킬에 결과 전달

### 의존성
quarto CLI 필요 — docs 에이전트가 사전 점검 + 안내
