# 연구 코드 작성 규칙 (PyTorch/ML 공통)

> **로드 시점**: PyTorch/ML 코드 작성, 신규 모델 구현, 코드 리뷰 시

## §0 정밀 변경 (Surgical Changes — MANDATORY)

> **로드 시점**: 모든 코드 수정·작성 작업 시 (PyTorch/ML 외 일반 코드 포함)
> **상세**: `agents/coder.md` § 정밀 변경 (Surgical Changes) 참조

### 모든 에이전트 공통 규칙
- [ ] 요청 라인 외 변경 금지 (인접 코드 "개선" ❌)
- [ ] 깨지지 않은 코드 리팩토링 금지
- [ ] 기존 스타일 일관성 유지 (본인이 다르게 쓸 것 같아도)
- [ ] 기존 dead code 발견 시 — 보고만, 삭제 ❌
- [ ] 본인 변경이 만든 orphan(미사용 import/변수)만 제거

## 네이밍 규칙
- **함수**: 동사로 시작 + snake_case (예: `compute_goodness`, `build_model`, `get_config`)
- **클래스**: CamelCase (예: `UniversalModel`, `FFBlock`, `HormoneController`)
- **상수**: UPPER_SNAKE_CASE (예: `CIFAR100_SIMILAR_CLASSES`, `DEFAULT_THRESHOLD`)
- **Private**: `_` 접두사 (예: `_compute_loss`, `_internal_state`)
- **Config 키**: snake_case, 계층 구조 (예: `model.glom_params.timesteps`)

## Import 순서
1. 표준 라이브러리 (`os`, `math`, `warnings` 등)
2. PyTorch / Lightning (`torch`, `torch.nn`, `pytorch_lightning`)
3. 외부 패키지 (`hydra`, `omegaconf`, `timm`, `wandb`)
4. 내부 모듈 (`src.` 절대 경로, 예: `from src.models.core import UniversalModel`)

## 주석 규칙
- 기본 영어, 수학적 계산/train-val-test 순서 등은 한글 추가 주석
- 중요 아키텍처: `""" 한글: ... """` 한글 긴 주석 필수 (수학 수식 포함)
- 인라인 한글 주석: `# 한글: 설명` 형식
- 주석만으로 코드의 목적/이유/순서를 파악할 수 있도록 작성

## Config 접근 패턴
- 안전한 접근: `.get(key, default)` 사용 (예: `cfg.get('collaborative', False)`)
- 필수 키 누락 시: `ValueError` 발생 (예: `raise ValueError(f"Unknown strategy: {name}")`)
- 선택적 기능: `try-except` + `warnings.warn` (예: HC 비활성화 시 graceful fallback)

## 실험 코드 실행
- wandb 로깅 config 확인 후 OFF 상태로 코드 검증
- matmul precision: `"highest"` (FP32 완전 정밀도) — 프로젝트 기본값
- PDF 읽기: Read 도구 사용 (최대 20페이지/요청, `pages` 파라미터)
- .docx/.pptx 등: 변환 코드 생성 경로를 사용자에게 확인 후 진행

### DEPRECATION warning 자동 감지 (#6 추가)
- 학습/dry-run 실행 stdout에서 `DeprecationWarning` / `UserWarning: deprecated` 패턴 검출 시 누적 카운터 +1
- **5건+ 누적 시 사용자 알림** (라이브러리 버전 업 사전 경고): "DEPRECATION warning N건 누적 — uv.lock 의존성 점검 권장"
- breaking change 예방: PyTorch/Lightning 버전 업그레이드 시 사전 호환성 점검 트리거

## AI/ML 실험 표 형식
- Config 파일의 실제 key 네이밍 사용
- 필수 컬럼: `#`, `실험명`, config 값들, `Val Acc`, `비고`
- 실험 완료 시 Acc/Loss 업데이트, 아키텍처 Figure 문서화, Confluence 호환 형태

## 아키텍처 패턴 (PyTorch 연구 코드)
- **Strategy Pattern**: 학습 전략 교체 (`src/models/strategies/` — ff.py, dfa.py, local_loss.py)
- **Builder Pattern**: 모델 생성 (`build_{model}` 함수, 외부에서 이 함수만 호출)
- **Dataclass**: Config 객체 (OmegaConf DictConfig 기반)

## code-simplifier 사용 규칙 (coder 에이전트 전용)

> **목적**: 기능 보존 전제 하에 가독성·일관성·유지보수성 자동 개선

### 사용 가능 조건 (아래 **모두** 충족 시)
- [ ] 현재 실험 트랙(Phase 1~N) **진입 전** 상태 (Stage A~D 코드 완성 단계)
- [ ] 사용자가 명시적으로 "리팩토링", "정리", "간소화" 요청

### 사용 금지 조건 (하나라도 해당 시 즉시 중단)
- ❌ 실험 트랙 진입 후 (Phase 1~N 진행 중) — CLAUDE.md 규칙 8번 "실험 중 리팩토링 금지"
- ❌ 기능 구현 중 부수적으로 자동 실행 (사용자 요청 없는 자동 적용 금지)
- ❌ 모델 아키텍처 핵심 코드 (수식 구현 포함 파일)

### 사용 방법
`/simplify` 스킬 또는 `code-simplifier@claude-plugins-official` 플러그인 (설치 완료)

## § Mem0 코딩 규칙 이력

프로젝트별 코딩 규칙 적용 이력을 Mem0에 저장하여 일관성 유지:

#### 리팩토링 패턴 저장
리팩토링 패턴 적용 완료 시 자동 저장 → `mem0-auto.md` T13 참조

#### 리팩토링 전 패턴 검색
코드 수정 전 과거 이슈 자동 검색 → `mem0-auto.md` T05 참조
→ 이전 패턴 발견 → 동일 패턴으로 일관성 있게 적용
