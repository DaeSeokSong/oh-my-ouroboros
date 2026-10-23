---
description: "Use when: 신규 연구 프로젝트 초기 세팅, '프로젝트 구조', '초기 세팅' 요청, cwd에 CLAUDE.md 없음. 일회성 참조 ONLY."
model: sonnet
---

# /project-init — 연구 프로젝트 구조 초기화

신규 연구 프로젝트의 폴더 구조를 표준 템플릿으로 생성합니다.

> ⚠️ **일회성 참조 ONLY**: 신규 프로젝트 초기 세팅 또는 구조 대규모 리팩토링 시에만 사용.
> 일반 코드 수정, 단일 파일 편집, 실험 설계 시에는 참조하지 않는다.

## 자동 트리거 조건

- 현재 작업 디렉토리에 CLAUDE.md 없음 + 신규 프로젝트 진입
- "프로젝트 구조", "초기 세팅", "폴더 구조 만들어" 키워드

## 실행 흐름

1. 현재 cwd 구조 파악 (Glob으로 탐색)
2. 기존 구조가 있으면 충돌 여부 분석 후 사용자에게 보고
2.5. cwd 가 git 저장소가 아니면 `scope-gate.sh` 가 Write·Edit 를 막는다(허용 목록 `config/scope-allow.txt` 밖). 생성 전에 사용자에게 `git init`(사용자 직접) 또는 허용 목록 등록을 안내한다
3. 표준 폴더 트리 중 필요한 부분만 생성 (사용자 승인 후)
4. 프로젝트 루트 CLAUDE.md 초안 생성 (디렉토리 구조 + 주요 config + 실행 명령어)
5. **graphify 초기 코드 그래프 생성** (3과 동일 승인 범위 내) — 프로젝트 루트에서 `graphify .` 1회 실행해 `graphify-out/` 생성. 신규 프로젝트는 보통 코드 파일뿐이라 semantic(LLM) 추출 없이 AST만으로 끝남 — 비용 사실상 0. (`code-graph.md` §0의 100파일 게이트는 **신규 프로젝트에 한해 예외** — 2026-07-09 사용자 결정, 근거는 §0 예외 각주. 기존 프로젝트 도입은 게이트 유지.) 이후 코드 파일을 Write/Edit할 때마다 `scripts/graphify-autoindex.sh`(PostToolUse 훅, 이미 배선됨)가 백그라운드에서 자동 재인덱싱한다 — 별도 `--watch` 데몬 불필요, graphify-out/ 존재 여부만으로 훅이 활성화된다. 문서/논문(docs/paper/*.tex 등) 변경은 훅이 자동 포함하지 않음 — 필요 시 `/graphify --update` 수동 실행.

6. **문서 양식 부트스트랩 확인** — `~/.claude/doc-formats/<프로젝트>/` 미존재 시(신규 프로젝트는 당연히 미등록) 문서 양식 등록 여부를 사용자에게 1회 질문. 규약·스키마: `rules-lazy/doc-format-registry.md` § 부트스트랩. 등록은 선택 — 문서 작업이 없는 프로젝트면 불요, 이후 첫 문서 작업 시 게이트가 다시 잡는다.

## graphify 자동 활성화 원리 (참고)

`scripts/graphify-autoindex.sh`는 Write/Edit된 파일 경로에서 상위로 walk-up하며 `graphify-out/`을 보유한 첫 디렉토리를 프로젝트 루트로 판단해 재인덱싱한다(최대 15단계, `$HOME`에서 중단, `$HOME/.claude` 자체는 하네스 격리로 제외). 즉 이 스텝 5가 하는 일은 오직 "최초 1회 `graphify-out/`을 만들어 훅의 트리거 조건을 충족시키는 것"이며, 지속적 파일 감시(`--watch` 백그라운드 프로세스)는 별도로 필요하지 않다.

## 표준 폴더 트리

```
project_root/
│
├── .claude/
│   └── train.env                   # 학습 세션 접두 · 체크포인트 로컬 경로 · 원격 목적지 (rules-lazy/background-task.md § 학습 세션·체크포인트 배치)
│
├── src/
│   ├── train.py                    # 단일 실험 진입점 (Hydra @hydra.main)
│   ├── test.py                     # 단일 테스트/평가 진입점
│   │
│   ├── models/
│   │   ├── core.py                 # 메인 LightningModule (학습루프·옵티마이저)
│   │   ├── builder/                # 모델 조립 로직 (apply_*/build_* 함수)
│   │   ├── {model}/                # 핵심 아키텍처 모듈 (1기능 = 1디렉토리)
│   │   │   ├── architecture.py     # 핵심 구조 (nn.Module, 수식 구현)
│   │   │   └── {sub_block}.py      # 서브 블록 (gate, embedding 등)
│   │   ├── strategies/             # 학습 전략 (BP/FF/LoRA 등)
│   │   │   ├── base.py             # 추상 클래스 (ABC)
│   │   │   └── {strategy_name}.py
│   │   ├── controllers/            # 동적 파라미터 제어 (해당 시)
│   │   └── helper/                 # 태스크별 헬퍼
│   │       └── heads.py
│   │
│   ├── datas/
│   │   ├── datamodule.py           # PyTorch Lightning DataModule
│   │   └── {dataset_name}_dataset.py
│   │
│   └── utils/
│       ├── config_loader.py
│       ├── logger.py
│       ├── callback.py
│       ├── computational_cost.py
│       ├── memory_profiler.py
│       ├── visualization.py
│       └── metrics/
│
├── configs/
│   ├── config.yaml                 # 메인 진입점 (defaults 목록만, 값 없음)
│   ├── model/
│   ├── dataset/
│   └── train/
│       └── default.yaml
│
├── docs/
│   ├── paper/
│   │   ├── {venue}_{year}_{project}.tex
│   │   ├── {venue}_{year}_{project}.pdf
│   │   ├── references.bib
│   │   └── figures/
│   │       ├── images/             # 생성된 Figure (PDF + PNG ≥300dpi)
│   │       └── scripts/            # gen_{name}.py 또는 gen_{name}_tikz.py
│   └── experiments/
│       └── experiment_design.md
│
├── tests/
├── outputs/
│   └── figures/
├── data/                           # git-ignored
├── checkpoints/                    # git-ignored
│
├── run_trains.py                   # 배치 실험 실행기 (root 위치 고정)
├── run_tests.py
├── .python-version                 # uv 관리 파이썬 버전(메이저.마이너, 예 3.12) — rules-lazy/uv-env.md
├── pyproject.toml                  # uv 패키지 관리 + [tool.uv] python-preference = "only-managed"
├── uv.lock                         # 반드시 commit
└── README.md
```

## 필수 파일 내용 기준

### .claude/train.env (학습 세션·체크포인트 배치 — 정본 `rules-lazy/background-task.md` § 학습 세션·체크포인트 배치)

```
TRAIN_TMUX_PREFIX=<프로젝트 슬러그>-mtl   # 학습 tmux 세션 이름 접두. 세션은 <접두>1, <접두>2 …
CKPT_ROOT=/path/to/local-ssd/weights   # 로컬 SSD. NFS·NAS 경로 금지
CKPT_REMOTE=/path/to/remote/weights   # 선택. 학습 뒤 rsync 목적지
```
이 파일이 없거나 tmux 세션 밖이거나 `CKPT_ROOT` 가 네트워크 파일시스템이면 main 은 발사 명령서를 내지 않는다(2026-09-13 사용자 지시).

### .python-version + pyproject.toml [tool.uv] (인터프리터 출처 고정 — 정본 `rules-lazy/uv-env.md`)
스캐폴드 순서: `uv python install 3.12` → `.python-version` 에 `3.12`(메이저.마이너만) → `pyproject.toml` 에 아래 블록 → `uv sync`. 시스템·anaconda 파이썬이 venv `home` 으로 박히면 다른 서버에서 venv 가 죽는다(2026-08-27 실사고).
```toml
[tool.uv]
python-preference = "only-managed"
```
- **ML 학습 프로젝트**는 위 블록 대신 `config/uv-baseline/pyproject.template.toml` 을 `pyproject.toml` 로 복사해 시작한다(기반 버전 128개 제약 + 위 블록 포함, 2026-09-30 사용자 결정). 사용법: 같은 폴더 `README.md`.

### configs/config.yaml (메인 진입점)
```yaml
defaults:
  - model: {model_name}
  - dataset: {dataset_name}
  - train: default
  - _self_

seed: 42
experiment_name: "${model.name}-${dataset.name}"
```

### src/models/strategies/base.py 패턴
```python
from abc import ABC, abstractmethod

class BaseStrategy(ABC):
    @abstractmethod
    def compute_loss(self, outputs, targets, **kwargs): ...

    @abstractmethod
    def training_step(self, batch, batch_idx): ...
```

### src/models/builder/{model}_builder.py 패턴
```python
def build_{model}(config: DictConfig) -> nn.Module:
    """config에서 모델을 조립하여 반환. 외부에서 이 함수만 호출."""
    ...
    return model
```

## 기존 프로젝트에 신규 모듈 추가 시

> **실험 중 리팩토링 금지** 원칙에 따라 기존 구조는 건드리지 않음.
> 신규 기능만 표준 패턴으로 추가.

기존 구조와의 매핑 (src/ 없는 경우):
- `src/models/{feature}/` → `model/{feature}/`
- 내부 서브 디렉토리(architecture/, strategies/, losses/, builder/)는 표준 유지
- `configs/model/{feature}.yaml` → `config/{feature}/` (singular)

## § Mem0 프로젝트 패턴 참조

신규 프로젝트 초기화 시 과거 프로젝트 구조 자동 검색: → mem0-templates.md T14 참조
이전 구조 패턴 발견 → 템플릿으로 제안 / 사용자 피드백도 category="feedback"으로 추가 검색하여 선호 반영

---

## 금지 사항

- `utils/` 안에 모델 아키텍처 코드 혼입
- 단일 거대 파일 (모든 클래스 하나에 몰기)
- config/train.yaml에 신규 기능 키 직접 inline 추가 (별도 yaml로 분리)
- Figure를 `docs/paper/figures/images/` 외부에 저장
- `src/` 없는 신규 프로젝트에서 모델 코드를 root에 직접 배치
