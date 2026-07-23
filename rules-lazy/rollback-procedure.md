# 롤백 절차 규칙

> **로드 시점**: QA 연속 실패, 사용자 "되돌려" 명시, 의도하지 않은 파일 변경 감지 시 (lazy load)

---

## §1 롤백 트리거 조건

아래 조건 중 하나라도 해당 시 즉시 롤백 절차를 시작한다:

| 트리거 | 조건 | 분류 |
|--------|------|------|
| QA 연속 실패 | 동일 파일·함수 QA FAIL 5회 연속 | 코드 변경 롤백 |
| 사용자 명시 | "되돌려", "이전으로", "취소해", "undo" | 사용자 요청 |
| 의도하지 않은 변경 | 변경 계획에 없던 파일이 수정된 것 감지 | 코드 변경 롤백 |
| 테스트 전파 실패 | 수정 후 기존 통과 테스트가 새로 실패 | 코드 변경 롤백 |
| 데이터 손실 위험 | 삭제/덮어쓰기 명령이 잘못 실행될 것으로 판단 | 즉시 중단 + 사용자 확인 |
| 비밀 정보 커밋 | API 키 등이 git 이력에 포함된 것 발견 | Git 상태 롤백 |

---

## §2 롤백 대상 분류 및 절차

### (a) 코드 변경 롤백

**트리거**: QA FAIL 5회 연속, 의도하지 않은 파일 변경, 사용자 명시

**절차**

```
1. 백업 확인
   → git diff {파일} 또는 git show HEAD:{파일} 로 변경 전 내용 확인
   → 백업 없으면 git stash 또는 git checkout HEAD -- {파일} 검토

2. 변경 범위 파악
   → 변경된 파일 목록: git diff --name-only HEAD
   → 변경 줄 수: git diff --stat HEAD

3. 롤백 방법 선택 (사용자에게 제시 후 선택 대기):
   A) 단일 파일 롤백: git checkout HEAD -- {파일명}
   B) 마지막 커밋 이전으로: git reset --soft HEAD~1 (스테이징 유지)
   C) Edit 역방향 적용: 현재 변경 내용을 역으로 Edit 도구 적용

4. 사용자 승인 후 실행
5. 롤백 후 QA 재검증 요청
```

**단일 파일 역방향 Edit (git 없이 롤백 시)**
```
현재 내용(변경 후) → old_string
원래 내용(변경 전) → new_string
으로 Edit 도구 호출 — 정확한 원래 내용이 확보된 경우에만 사용
```

---

### (b) Git 상태 롤백

**트리거**: 잘못된 커밋, 비밀 정보 커밋, 커밋 메시지 오류

**절차**

```
1. 현재 git 상태 확인
   → git log --oneline -5
   → git status

2. 롤백 방법 제시 (사용자 선택 대기 — AI 직접 실행 금지):

   [방법 A] 스테이징만 되돌리기 (commit 전)
   → git restore --staged {파일명}
   → AI 직접 실행 가능 (파일 내용 변경 없음)

   [방법 B] 워킹 디렉토리 변경 취소 (commit 전)
   → git restore {파일명}
   → AI 실행 전 사용자 승인 필수 (파일 내용 변경)

   [방법 C] 마지막 커밋 취소 (스테이징 유지)
   → git reset --soft HEAD~N
   → 사용자 승인 필수 — N개 커밋 대상 명시 후 질문

   [방법 D] 마지막 커밋 완전 취소 (워킹 디렉토리 초기화)
   → git reset --hard HEAD~N
   → 사용자 명시 요청 시에만 제안 — 변경 내용 영구 소실 경고 포함

   [방법 E] 커밋 내용 보존 + 되돌리기
   → git revert HEAD (새 커밋으로 이전 상태 복원)
   → 공유 브랜치에서 권장 (이력 보존)

3. 비밀 정보 커밋 시 → secret-management.md §6 참조
   (git filter-repo / force push는 AI 직접 실행 금지)

4. 사용자 승인 후 gitops 에이전트에 위임 또는 사용자 직접 실행
```

**절대 금지 (AI 직접 실행 불가)**
- `git reset --hard` (사용자 명시 없이)
- `git push --force` / `git push --force-with-lease`
- `git clean -f` / `git clean -fd`
- `git filter-repo`

---

### (c) 실험 결과 롤백

**트리거**: 실험 config 잘못 적용, 이전 Phase로 복귀 필요

**절차**

```
1. config 백업 확인
   → configs/ 하위 백업 파일 또는 git 이력 확인
   → git log --oneline -- configs/

2. 이전 config 복원
   → git show {커밋 해시}:configs/{파일명} > configs/{파일명}
   → 또는 백업 파일 복사

3. 실험 결과 수치 보존 확인
   → Mem0에서 해당 Phase 결과 검색 (T10 레코드 확인)
   → results/ 또는 logs/ 하위 기록 보존 여부 확인

4. config 복원 후 사용자에게 보고:
   복원된 config: {파일명}
   이전 값: {파라미터명} = {이전값}
   현재 값: {파라미터명} = {복원값}

5. 롤백 후 재실험 여부 사용자에게 질문
```

---

### (d) 메모리(Mem0) 롤백

**트리거**: 잘못된 합의 저장, 오기입 수정, 폐기된 결정 수정

**절차**

```
1. 대상 메모리 검색
   → search_memories(query="{수정 대상 키워드}", limit=5)
   → memory_id 확인

2. 수정 방법 선택:

   [방법 A] 내용 수정 (권장)
   → update_memory(memory_id="{id}", text="{수정된 내용}")
   → 이전 내용 + "[수정됨: {날짜}]" 메모 포함

   [방법 B] 번복 표시 (합의 변경 시)
   → update_memory(memory_id="{id}",
       text="{원본 내용} [번복됨: {날짜}, 사유: {1줄}]")

   [방법 C] 삭제 (명백한 오기입)
   → delete_memory(memory_id="{id}")
   → 삭제 전 내용 확인 후 사용자 승인 필수

3. 절대 금지: delete_all_memories (전체 초기화)
   → 누적된 결정 이력 영구 소실
   → 사용자 명시 + 재확인 없이 절대 실행 금지
```

**Mem0 롤백 기록 형식**
```
[롤백 기록] {날짜}
대상 memory_id: {id}
사유: {1줄}
이전 내용: {요약}
수정 후 내용: {요약}
처리 방법: update / delete
```

---

## §3 롤백 실행 전 사용자 확인 프로토콜

### 필수 확인 메시지 형식

```
롤백 계획:
  대상: {분류} — {파일명 또는 memory_id}
  롤백 범위: {변경된 항목 목록}
  방법: {git reset --soft HEAD~1 / Edit 역방향 / update_memory 등}
  영향: {되돌려지는 내용 요약}
  손실 위험: {있음 / 없음}

진행할까요? (Y/N)
```

### 즉시 실행 가능 (사용자 승인 불필요)

- `git restore --staged {파일명}` (스테이징 취소 — 파일 내용 변경 없음)
- `update_memory` (내용 수정 — 원본 보존)
- Read 도구로 변경 전 내용 확인

### 반드시 사용자 승인 필요

| 작업 | 이유 |
|------|------|
| `git restore {파일명}` | 워킹 디렉토리 내용 변경 |
| `git reset --soft HEAD~N` | 커밋 이력 변경 |
| `git reset --hard HEAD~N` | 변경 내용 영구 소실 |
| `delete_memory` | 기록 영구 삭제 |
| config 파일 덮어쓰기 | 실험 설정 변경 |

---

## §4 롤백 후 검증 절차

```
1. 코드 변경 롤백 후
   → QA 에이전트 재검증 요청
   → 기존 통과 테스트 재실행 확인

2. Git 상태 롤백 후
   → git log --oneline -5 (이력 확인)
   → git status (워킹 트리 상태 확인)
   → 의도한 상태와 일치 여부 사용자 확인

3. 실험 config 롤백 후
   → configs/ 파일 내용 검토
   → Mem0에서 해당 Phase 설정 검색하여 일치 여부 확인

4. Mem0 롤백 후
   → search_memories로 롤백된 내용 재검색
   → 의도한 상태로 수정되었는지 확인
```

---

## §5 절대 금지 사항 (MANDATORY)

| 금지 행위 | 이유 |
|----------|------|
| 사용자 합의 없는 `git reset --hard` | 변경 내용 영구 소실 |
| `git push --force` / `--force-with-lease` AI 직접 실행 | 원격 이력 파괴, 팀 협업 방해 |
| `delete_all_memories` 자의적 실행 | 모든 결정·실험 이력 영구 소실 |
| 롤백 범위 미확인 상태로 실행 | 의도하지 않은 파일까지 롤백 |
| 사용자 미보고 침묵 롤백 | 사용자 통제권 박탈 |
| 백업 없는 덮어쓰기 | 원본 복구 불가 |

---

## §6 연관 규칙

| 상황 | 참조 파일 |
|------|---------|
| git commit 전 비밀 정보 발견 | `~/.claude/rules-lazy/secret-management.md` |
| QA FAIL 반복 (5회+) | `~/.claude/rules-lazy/qa-process.md` § Ralph Wiggum 루프 |
| 에러 발생 시 에스컬레이션 | `~/.claude/rules-lazy/error-handling.md` § main 에스컬레이션 |
| git 커밋·브랜치 전문 처리 | gitops 에이전트 (`agent-routing.md`) |
| Mem0 update/delete 상세 | `~/.claude/rules/mem0-auto.md` §0 MCP 도구 레퍼런스 |
