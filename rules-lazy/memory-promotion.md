# 단기→장기 승격(Promotion) 절차

> **로드 시점**: 승격 트리거 발생 시 (`memory-write.md`에서 참조)
> **핵심 원칙**: 반복 참조 가능성이 높은 결정은 short-term에서 long-term으로 승격하여 영구 보존한다.

## 승격 트리거 분류

| 카테고리 | 트리거 조건 | 출발 | 목적지 |
|----------|-----------|------|--------|
| **설계 확정** | 아키텍처 구조/모듈 결정, 수식 확정, 설계 근거 합의 | decisions.md | architecture.md |
| **데이터 확정** | 데이터셋 추가/교체/제거 확정, 분할 전략 확정 | decisions.md | datasets.md |
| **파라미터 확정** | 하이퍼파라미터 기준값 확정, lr/rank/batch 등 | decisions.md | hyperparams.md |
| **실험 결과 확정** | Phase 완료 + 결과 수치 확정, 베이스라인 수치 확정 | progress.md | experiments.md |
| **사용자 교정** | "이렇게 하지 마", "이게 더 낫다" 등 행동 교정 | decisions.md | feedback.md |
| **도구/환경 결정** | MCP 선택, 패키지 선정, 인프라 설정 등 영구 참조 | decisions.md | feedback.md |
| **논문 결정** | 논문 구조, 실험 순서, 제출 전략 등 학회 관련 | decisions.md | experiments.md |
| **코드 컨벤션** | 네이밍/패턴/구조 관련 영구 규칙 합의 | decisions.md | feedback.md |
| **외부 참조** | 논문 URL, API 엔드포인트, 외부 시스템 포인터 | decisions.md | 해당 장기 파일 `## 참조` 섹션 |

## 승격 흐름

```
1. 단기 파일에 즉시 기록 (memory-write.md 참조)
2. 승격 트리거 조건에 해당하는지 자동 판단
3. 해당하면 → 사용자에게 승격 제안:

   📌 장기 메모리 승격 제안:
   | 항목 | 내용 요약 |
   |------|----------|
   | 출발 | short-term/decisions.md — "[결정 요약]" |
   | 목적지 | long-term/[파일명].md |
   | 카테고리 | [설계 확정 / 데이터 확정 / ...] |
   | 근거 | [왜 장기 보존이 필요한지 1줄] |

   승격할까요? (Y/N/수정 후 승격)

4. 사용자 승인 → 장기 파일에 기록 + 단기에 `→ 승격 완료 (long-term/xxx.md)` 표시
5. 사용자 거부 → 단기에만 유지, 7일 후 정상 만료
6. "수정 후 승격" → 사용자가 내용 수정 지시 → 수정 반영 후 장기 기록
```

### § Mem0 승격 안전망

- 승격 대상 항목은 이미 Mem0 `decision` 채널에 저장되어 있음 (memory-write.md § Mem0 병렬 저장)
- 승격 누락 시에도 `search_memories(query="[프로젝트] 결정", filters={"metadata": {"category": "decision"}})`로 복구 가능 (`category=`는 유효 인자 아님 — `filters.metadata.category` 사용, `mem0-auto.md` §1.3) → `mem0-auto.md` T05 참조
- compact 전 일괄 승격 시: Mem0에서 미승격 항목 검색 → 누락 방지

승격 실패 복구 흐름:
  장기 파일에 항목 없음 감지
    → search_memories(category="decision", query="{항목 키워드}") → `mem0-auto.md` T05 참조
    → 결과 있으면 → 장기 파일에 복원 + 사용자 보고
    → 결과 없으면 → 진짜 미기록 → 사용자에게 재확인

## 일괄 승격 (compact 직전)

compact 실행 직전 미승격 항목 일괄 스캔:
```
1. short-term/decisions.md에서 승격 트리거 해당 + 미승격 항목 추출
2. 일괄 승격 제안 테이블 출력:

   📌 compact 전 일괄 승격 제안 (N건):
   | # | 항목 | 카테고리 | 목적지 | 승격? |
   |---|------|---------|--------|-------|
   | 1 | [결정 요약] | 설계 확정 | architecture.md | Y/N |
   | 2 | [결정 요약] | 파라미터 확정 | hyperparams.md | Y/N |

3. 사용자가 각 항목별 Y/N 결정
4. 승인된 항목만 장기 파일에 기록
5. compact 실행
```

## 자동 승격 (사용자 승인 생략 가능 조건)

아래 조건을 **모두** 충족하면 사용자 확인 없이 자동 승격:
- 사용자가 이전에 "이 카테고리는 자동 승격해도 돼"라고 명시한 경우
- 해당 카테고리의 자동 승격 설정이 `long-term/feedback.md`에 기록되어 있는 경우
- 그 외에는 **항상 사용자 승인 필수**
