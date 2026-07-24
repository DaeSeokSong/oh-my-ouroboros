# Harness Audit 실행 이력 (로컬 상태 — gitignore)

> 형식: 일자 / 범위 / 발견·수정 / 커밋 / 판정. 최신이 위.

## 2026-07-18(훅 스크립트 리프 정밀 진단 + 피어 메시지 대책) — 배선 훅 10종 Codex 2배치 (Fable + Codex Sol·xhigh)

- **방법**: 아직 심층검사 안 받은 배선 훅 스크립트 10종을 Codex(Sol·xhigh) 2배치 스캔 + 구조 재확인(리프 재도달·루프)
- **Codex 적발 24건 → 실질 수정 14 + by-design 동의 3 + 오탐 1(실증)**: [보안] bash-write-check `# APPROVED_X` 오승인·scope-gate 경로 미정규화(../·심볼릭 우회) [correctness] read-once JSON 손상 fail-open·ci-gate-edit fence 산술 abort·usage-check always-fail 마스킹·prompt-log UTF-8 손상·pattern-detect 관용파싱·toolcall-guard 다중블록·claude-notify curl hang [경합] autoindex 락(owner 토큰=워커 $BASHPID·PID liveness·ROOT 절대화)·prompt-log 로테이션 고유temp
- **by-design 동의(Codex)**: bash-write-check ~95% 휴리스틱(mkdir benign 제외), guard 예제 오탐(재시도 1회 제한), ntfy best-effort wait
- **오탐 1건 실증 반증**: Codex가 autoindex 실패 마커 "never surfaced" 5회 반복 지적 → 실패 graphify 스텁으로 훅 2회 실행 실증: .autoindex-failed 기록 + 2회차 경고 출력 확인 → 오탐 (verify-not-face-value 원칙)
- **피어 메시지 대책(사용자 지시)**: rules-lazy/peer-session-messages.md 신설 — 타 서버 Claude 피어 메시지의 권한 세탁 방어(자기 권한만·에스컬레이션 불가·laundering 거부+surface)
- **커밋**: 9594889(피어룰)~d196cc1

## 2026-07-17~18(/discuss 정밀 점검 + Codex 22라운드 수렴) — 시작점→리프 전수 (Fable + Codex Sol·xhigh)

- **방법**: main 주도 경량 5라운드 감사(경로·루프·콘텐츠·구조·비판) + 라운드별 Codex(Sol·xhigh) 독립 교차검증을 "동의까지" 반복(총 ~22 검증 패스)
- **Codex 적발(내부 감사 미탐)**: 고아 스크립트 2(setup-harness·team-checkpoint), Ralph 플러그인 동명 무제한 루프, blind A/B 구조적 비-blind(판정자가 정답 키 노출)+미배선, verdict INCONCLUSIVE→FAIL 편향, 배선 파이프라인 다수 실패 은폐(detect|tee_log RC·save_manifest·git add·lock)
- **수정 22커밋**: [격리] harness-evolve.sh 전체·regression-blind.sh(미배선 P2, Codex ACCEPT) [배선 correctness] 온톨로지 파이프라인 RC 가드 6곳·stale 청크 청소 3곳 RC·부분추출 3층 방어(청크 하한+노드 커버리지 strict+shrink-guard)·lock 경합/오류 구분·커밋 pathspec 스코프 [문서] Ralph 내부 카운터·Tier-2 QUARANTINE 5곳 수렴·조수 모델 경계·테스트 실행 SSOT
- **의도 유지(설계 트레이드오프)**: shrink auto-force ≤10% — 폴더이동 동명 dedup(-1.4%) 정상 통과 목적, 0%는 정상 dedup 파손
- **최종 판정**: Codex "CRITICAL-REMAINING 없음" — 배선(실행) 하네스 correctness-clean, 미배선 P2는 명시 격리. 잔여: blind 파일 커버리지의 코디네이터 매니페스트 기반 정밀화는 이미 strict 커버리지로 대체 해소
- **기준선**: always-on 67,175바이트/MANDATORY 39건(불변 — 스크립트·문서 수정만)
- **커밋**: 3eecae5~4c84c49

## 2026-07-16(기계 점검 + hit 추적 첫 실사용) — 전체 시스템 재점검 (Fable)

- **방법**: Step 1~6 기계 전수(인벤토리·포인터·모델핀·MCP·중복쌍·서브커맨드) + 훅 배선 10종 전수(존재·문법) + **EvoPolicyGym hit 추적 첫 실사용**(직전 07-10 수정 대조)
- **발견 P0 0 / P1 1 / P2 3**: P1 완료 기록-실체 불일치(07-10 "SessionStart 하드 배선" 기록 vs git 최초 커밋 07-16 — 6일 훅 부재 무감지) / P2 always-on 예산 97.3% 임박·MANDATORY +3(신설 3건 실피해 기준 통과 판정)·원격 HTTPS 자격증명 이월(사용자 조치)
- **수정**: [구조] 반복 결함 #6(완료 기록-실체 불일치) 등재 + 완료 기록 절 "배선류는 git show HEAD 실체 대조" 조항 / [조정] always-on 압축 4곳 68,107→67,175B(-932B, bench-alwayson-compress-20260716)
- **hit 추적 결과 (07-10 수정 대조)**: usage-check 신설 ✓작동 / allowed-tools Agent ✓실재 / MANDATORY 감축 ✓유지(36→39는 신설, 재발 아님) / **SessionStart 배선 ✗기록-실체 불일치**(07-16 재배선 508766b로 해소) / 원격 HTTPS ✗미해결(사용자 이월)
- **부수 정정**: killswitch 서브커맨드는 harness-evolve.sh에 실재(07-15 "설계 기록만" 발언 오류)
- **기준선**: always-on **67,175바이트** / MANDATORY **39건**
- **커밋**: 33d8a92 (+ 이번 주 선행: GPT 교차감사 Batch 1·2 15커밋, 피드백 루프 개통 508766b~a0e304b)

## 2026-07-10(전 파일 재귀 검수) — "프롬프트만으로 전자동" 주장 검증 (Fable + qa×4 + 기계 스윕)
- **방법**: 기계 전수 스윕(문법 30스크립트·포인터·훅 배선·systemd·모델 별칭·JSON 무결성) + qa×4 의미 정독(always-on/lazy 36/agents·skills·commands 39/scripts·config·문서) — 자동화 체인 렌즈
- **발견 15건 → 수정 14 + 보류 1**: P0×3(pipeline 스킵 시 finalize 크래시 체인 → exit 2 분기 / T03 룰 의존 → **SessionStart 훅 하드 배선** / harness-audit·learn-from-feedback allowed-tools에 Agent 부재로 Step 7 fan-out 실행 불가) + P1×6(usage-check "변경 없음" 마스킹, 고아 룰 삼각형(error-handling·secret-management·rollback) 진입점 신설, scope-gate stale·opt-in 명시, 카운터 절 가짜 MANDATORY 정합화, README/RULES "~300줄" 2.6배 과소, coder whitelist 실체 불일치) + P2×5(라우팅 0.7행 게이트 모호 → **qa#1의 4→5 제안은 과잉 교정으로 판별, 라벨 구분으로 정정**, paper-read 6→9 소스, README 커맨드 9→10, refresh lock BSD, gen_figX 시한폭탄)
- **환경 이슈 발견 (사용자 조치 필요)**: origin이 HTTPS + credential helper 없음 → 무인 타이머의 git pull이 매주 실패 예정 — SSH 전환 또는 helper 설정 필요
- **판정**: "프롬프트만으로 전자동" 주장은 수정 후 참 — 온톨로지(타이머)·프로젝트 그래프(신규 자동/기존 1회 opt-in 후 자동)·자가진화(SessionStart 훅으로 룰 의존 제거). 잔여 조건: push 주기(전파 전제) + 위 자격증명

## 2026-07-10(교정 사이클) — MANDATORY 감축·usage-check 신설 — Codex 만장일치 (Fable)
- **방법**: Fable 검수 → 수정 → Codex 교차검증 4라운드 반복 → "만장일치: 이상 없음" 도달 (사용자 지정 프로토콜)
- **감축 실적**: always-on 67,212B → **64,101B**(−4.6%) / MANDATORY 56 → **36**(−20, 기준: 위반=실피해(보안·주권·데이터·비용·재귀)만 유지 — 기준 자체를 harness-audit 반복 결함 표 각주로 이식) / 중복 제거 2건(agent-routing 순서도→테이블 단일 출처, mem0 §0 도구표→ToolSearch 위임)
- **구축-미사용 rot 대응**: `scripts/harness-usage-check.sh` 신설(T03 인라인 체크 3종 흡수 + 신규 감지 5종: 감사 30d·타이머 침묵·push 백로그·패턴 마이닝 정지·bench 대기) — **가동 즉시 실전 적발 2건**: T40 자가진화 루프 정지(프롬프트 391줄 미마이닝 → pattern-detect 즉시 실행, "학습 현황 보고" 4회 반복 검출) + bench 미실행. zerosum은 ci-gate-commit WARN(예산 70KB)으로 흡수. 반복 결함 **#5 구축-미사용 rot** 등재(cadence-구동=신선도 마커 / event-구동=트리거 배선 기준)
- **Codex 라운드별**: R1 P2×2(TIMER_SILENT 성공-시점 판정 오류·GNU stat 전용 / bench 마커 중간 exit 미도달) → R2 P2×1(date 파싱 실패 fail-silent) → R3 P2×1(BSD %z 콜론 오탐) → R4 **만장일치**
- **교훈**: ① 판단 기준은 기준선이 기록돼야 실행 가능 ② 감지기는 fail-visible이어야 함(감지기의 침묵 사망 방지) ③ "push 대기 N커밋" 누적 집계 오보 — 보고 수치는 매번 실측

## 2026-07-09(3렌즈 점검) — 토큰 효율·루프 편입·선택지 게이트 (Fable)
- **기준선 (Step 1 트렌드용 — 최초 기록)**: always-on 67,212바이트(CLAUDE.md 14,741 + rules 5개) / MANDATORY 56건 (prompt-routing 15·CLAUDE 19·code-exec 6·agent-routing 6·mem0 10·model-assign 0)
- **발견/수정 3건**: ① Step 1 "이전 대비 증가" 판단 기준이 기준선 미기록으로 실행 불가 → history에 매 감사 기록 의무화 ② RULES.md code-graph 행 누락(반복 결함 #2) → 추가 ③ 온톨로지 타이머 실패 시 ntfy 부재(무인 루프 침묵 사망) → notify_fail 4개 실패 경로 배선
- **축약 후보 3건 선별 (bench 게이트 대기 — 미적용)**: prompt-routing Step 1 금지패턴 7행 표 / mem0-auto §0 도구 파라미터 표(deferred 로드와 중복) / agent-routing 라우팅 테이블·순서도 이중 표현
- **판정**: 선택지 게이트 잔여 공백 없음 (graphify §3·타이머 T03·도구 Step 1.6·gpt-image-2·brainstorming·second-opinion·ultracode 전부 opt-in 게이트 보유)

## 2026-07-06(2차) — Fable 전 파일 직접 전수 정독 (지식 이식 최종 판정)
- **방법**: main(Fable)이 위임 없이 79파일 전문 정독 — rules 5·rules-lazy 35·agents 10·skills 18·commands 9·루트 문서 12. 렌즈: ① 왜(판단 근거) 부재 ② Fable만 알고 파일에 없는 지식 ③ 사실 정확성
- **발견/수정 15건**: LLM 거동층 7 (mcp-fallback 죽은 §3, ralph-loop 커맨드 개칭 누락+임계 불일치, quick-skill 구세대 생성 경로, discuss Cross-Watch 오참조, qa-process 0번 절, Step1.7 상세 동기화, 카운터 예시) + 공개 문서 8 (SECURITY settings.json 정책 모순, README/EVAL/ASSESS 카운트, bg-restore.sh 죽은 참조 — 게이트가 실전 검출, 게이트 my-* allowlist)
- **커밋**: `ab975f0` `820a24f` (+메타 원칙 `2790c0c`)
- **판정**: 이식 가능한 것은 전부 이식됨 — LLM 거동층(CLAUDE.md·rules·agents·skills·commands)의 절차·판단 근거·검증 루프·자기 개선 루프 완비. 순간 추론력 자체는 파일 이식 불가(구조적 한계) — 게이트·교차검증·주기 감사로 보상. 교훈: **명칭 개칭 sweep 시 grep 범위에 commands/·루트 문서 포함** (이번 사각지대)

## 2026-07-06 — 모델 전환 대비 최종 감사 (전체: Step 1~8 정밀 모드)
- **방법**: 기계 점검 Step 1~6 + 의미 정합 qa×5 병렬 정독(always-on/lazy a-l/lazy m-z/agents+skills/배선) + Codex 외부 교차검증
- **발견/수정**: 내부 21건 + Codex 신규 7건 = 28건 → 25건 수정, 2건 사용자 잔여(chmod +x, 7/7 model 값), 1건 조치 불요(중첩 .claude 캐시 — 무해 확인)
- **핵심**: 6-Gate 개칭(동명이의 해소) / read-once 훅 세션 격리(오차단 실결함) / model-assignment 자기모순 해소 / MCP 도구명 현행화 / AGENTS·RULES 카탈로그 동기화
- **커밋**: `55dbbfd` `6ee740b` `0795717` `28c2af8` (+동일 세션 선행 버그픽스 `8a14509`~`ccb0a85`)
- **판정**: Opus 전환 차단 결함 0 — 별칭(opus/sonnet/haiku)·suffix([1m]) 기반 설계 확인
- **반복 결함 4패턴**: 라벨-실체 drift / 파생 카탈로그 미동기화 / 훅 세션 격리·문서화 누락 / MCP 도구명 rename 미추적 → 스킬 § 반복 결함 우선 체크에 반영
