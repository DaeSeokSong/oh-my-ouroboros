# 파이썬 환경 규칙 — uv 관리 파이썬 강제

> **로드 시점**: 프로젝트 첫 작업 시(점검 1회), 신규 프로젝트 스캐폴드, venv 오류·서버 이전 작업 시.
> **정본**: 이 파일. CLAUDE.md 원칙 5는 포인터, `skills/project-init/SKILL.md`는 스캐폴드 적용본, `rules-lazy/qa-process.md` §6은 학습 스크립트 수정 시 자동 점검 항목.

## 원칙

- **인터프리터**: `~/.local/share/uv/python` 아래의 uv 관리 파이썬만 쓴다. 시스템 파이썬·anaconda·pyenv 파이썬을 venv 의 `home` 으로 삼지 않는다.
- **패키지**: 프로젝트별 `.venv` 에만 설치한다. `conda`·`python -m venv`·`pip install` 직접 호출 금지(전부 `uv add`·`uv sync` 로). `uv pip install` 도 `pyproject.toml`·락 파일에 기록되지 않아 같은 이유로 프로젝트 의존성에는 쓰지 않는다(일부 스킬 문서의 `uv pip install` 예시는 임시 환경용 외부 원문이며 이 규칙과 어긋나므로 스킬 쪽 정리는 별도 항목이다).
- **왜 인터프리터까지 못 박는가**: uv 는 `python-preference` 기본값이 시스템 파이썬을 먼저 집는다. venv 의 `pyvenv.cfg` 에는 그 인터프리터의 **절대 경로**가 `home` 으로 박히므로 저장소를 다른 서버에 마운트하면 그 경로가 없어 venv 가 통째로 죽는다. uv 관리 파이썬은 서버마다 같은 상대 위치(`~/.local/share/uv/python/<버전>`)에 놓여 이 문제가 없다.

## 신규 프로젝트 필수 파일 (project-init 스캐폴드가 생성)

| 파일 | 내용 | 이유 |
|---|---|---|
| `.python-version` | 메이저.마이너만(예: `3.12`) | 패치 버전을 박으면 서버마다 설치본이 달라 `uv sync` 가 재설치를 요구한다 |
| `pyproject.toml` | `[tool.uv]` 아래 `python-preference = "only-managed"` | 시스템·anaconda 파이썬을 후보에서 제외 |

```toml
[tool.uv]
python-preference = "only-managed"
```

## ML 학습 프로젝트 버전 기준 (2026-09-30 사용자 결정)

- 기반 라이브러리(torch 2.9.1 · torchvision 0.24.1 · pytorch-lightning 2.5.6 등 128개)는 `config/uv-baseline/pyproject.template.toml` 한 곳에 둔다. 사용법·갱신 절차·원본 대비 다듬은 점은 같은 폴더 `README.md` 가 정본이다.
- 새 ML 프로젝트는 이 틀로 시작한다. 기존 프로젝트는 그 프로젝트의 판이 모두 끝난 차수 경계에서만 맞춘다. 진행 중인 판의 버전은 바꾸지 않는다.
- 틀은 손으로 고치지 않는다. `config/uv-baseline/make_baseline.py` 로 다시 만들고 검증 출력을 커밋 메시지에 남긴다. 판 줄(minor·major)을 넘는 갱신은 사용자 결정이다.

## 점검 (read-only, 프로젝트 첫 작업 시 1회)

```bash
grep '^home' .venv/pyvenv.cfg
```

- 값이 `~/.local/share/uv/python/` 아래면 통과.
- 아니면(예: `/home/<user>/anaconda3/bin`) 사용자에게 **이전 제안만** 한다. venv 재구성은 환경 변경이라 자동 실행 금지(`rules/code-execution.md`).

## 이전 절차 (사용자 실행 명령서 — AI 는 출력만)

```bash
cd <프로젝트 루트>
uv python install 3.12            # .python-version 의 버전
mv .venv .venv.bak                # 되돌릴 수 있게 보관
uv sync --frozen                  # uv.lock 그대로 재구성
grep '^home' .venv/pyvenv.cfg     # ~/.local/share/uv/python/ 아래인지
uv run python -c "import torch; print(torch.cuda.is_available())"   # CUDA 프로젝트만
uv run pytest -q                  # 테스트가 있으면
```

- 위 검증 3종(home·테스트·CUDA)을 통과한 뒤에만 `.venv.bak` 삭제를 사용자에게 승인받는다. 삭제는 사용자 직접.
- `.python-version`·`[tool.uv]` 가 없는 기존 프로젝트는 이전 전에 두 파일부터 추가하고 커밋한다.

## anaconda3 삭제 조건

- `~/workspace` 아래 **모든** 프로젝트의 `pyvenv.cfg` 점검이 통과한 뒤에만 후보가 된다.
- 삭제는 사용자 직접(11GB, 환경 변경). AI 는 점검 결과 표만 제시한다.

## 근거 (2026-08-27 실사고)

CLAUDE.md 원칙 5가 "uv 로 패키지 관리" 만 말하고 인터프리터 출처를 규정하지 않았다. 그 틈으로 uv 가 한 서버의 `~/anaconda3/bin/python3.12` 를 집어 한 프로젝트 `.venv/pyvenv.cfg` 의 `home` 이 서버 고유 경로가 됐고, 저장소를 다른 서버에 NFS 마운트했을 때 venv 가 동작하지 않았다. 같은 날 `~/workspace` 아래 `.venv` 6개 가운데 3개가 anaconda 의존이었다. 그 프로젝트는 `.python-version`(3.12) + `[tool.uv] python-preference = "only-managed"` 를 넣었다(서버 · 프로젝트 이름과 실측 목록: `knowledge/harness/rules-project-server-history-2026-11-10.md` § uv-env).
