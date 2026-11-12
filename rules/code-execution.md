# 코드 작성 및 실행 규칙

> **로드 시점**: 코드 작성 및 실행이 필요한 모든 작업 시 (항상 적용)

## Hook 차단 시 처리 규칙 (MANDATORY)

Bash 명령이 hook(bash-write-check.sh 등)에 차단되면 **"터미널에서 직접 실행하세요"라고 일방 통보하지 않는다**. 반드시 아래 형식으로 목적과 명령어를 밝히고 실행 여부를 묻는다. 차단된 명령이 여러 개면 번호를 매겨 한 번에 묻는다.

```
`<명령어>`을(를) 실행하려고 합니다.
목적: <왜 이 명령이 필요한지 1줄>
실행할까요?
```

- 승인 시: 첫 줄에 `# APPROVED «발화 8자+»` 를 붙여 재실행(인용이 프롬프트 로그에 있어야 통과). 실행 시 바뀌는 인터프리터 코드(규칙 0.4, `scripts/bash-write-check.sh` 헤더)는 승인으로도 막힌다
- 사용자가 거부하면: 대안 방법 모색

### Read 차단 (read-once 훅) — 복구 절차

`scripts/read-once.sh` 는 **동일 파일 + 동일 mtime 전체 Read를 TTL 20분간 차단**한다. 차단 시: 컨텍스트의 내용을 재사용 → 일부만 필요하거나 재검증 목적이면 **offset/limit 부분 Read 또는 Grep** 사용(부분 읽기는 캐시 미적용) → 파일 변경으로 mtime이 바뀌면 자동 통과 → compact 뒤에는 재읽기 허용. 도구 차단·MCP 불가·명령 실패 시 `~/.claude/rules-lazy/error-handling.md` § (a) 도구 차단(에러 분류 5종·재시도 한도·침묵 재시도 금지)을 로드해 따른다.

## 기본 원칙
모든 처리 작업(분석·변환·시각화·전처리 등)은 반드시 **코드 파일로 작성 후 저장**한다. AI가 직접 연산하거나 결과를 즉석으로 생성하는 것은 금지한다.

## 프로젝트 경계 (MANDATORY — 2026-09-07 사용자 지시, 예외 없음)

- **쓰기는 cwd 가 속한 저장소 안에서만**. 다른 프로젝트 저장소는 **Read·Grep·Glob 만** 허용한다(Write·Edit·생성·삭제·`git checkout`·`git stash`·설정 변경 전부 금지). 다른 저장소를 고쳐야 풀리는 일이면 쓰지 않고, 필요한 변경을 보고에 적어 **사용자에게 알린다**. 기준은 세션을 시작한 cwd 이며 `cd` 로 다른 저장소에 들어가도 쓰기 대상은 바뀌지 않는다. 예외는 아래 항의 세 곳(memory·하네스 홈·허용 목록)뿐이다.
- **cwd 가 git 저장소 밖이면 Write·Edit 를 전부 막는다**. 예외는 프로젝트 memory 폴더, 하네스 홈(`~/.claude` 의 knowledge·doc-formats·learner 퀴즈 기록(`_evolve/quiz/`)·`.scratch/`·자기 scope 파일), `config/scope-allow.txt` 에 사용자가 적은 절대 경로 접두 아래뿐이다.
- **집행**: `scripts/scope-gate.sh` 가 저장소 밖 Write·Edit 를 막는다. 리다이렉션은 `bash-write-check.sh`가, `git checkout .`·`restore .`·`stash`는 `git-guardrails.sh`가 막는다. 다만 두 훅 다 저장소 경계는 모르므로 **Bash 경유 「저장소 밖 쓰기」**와 어느 저장소에도 속하지 않는 경로는 이 문구가 유일한 통제다.
- `~/.claude` 쓰기는 `[Harness] Manager` 세션 전용(예외 표): `rules-lazy/scope-gate.md`
- 정본 상세(«scripts 에 만들어» 해석·다른 프로젝트 수정 시 처리·subagent 전파·실사고 2026-09-07): `rules-lazy/code-execution-detail.md` § 프로젝트 경계

## 코드 저장 규칙

- **임시 코드**: 서버 지정 파일 `~/.claude/config/scratch-root` 가 있으면 `<지정>/<프로젝트 이름>/<세션·잡 id>/`, 없으면 `<현재 프로젝트>/.scratch/<세션·잡 id>/` (MANDATORY). 하네스 `jobs/<잡>/tmp/`·`outputs/_scratch/` 에는 쓰지 않는다. 사용자 지정이 있으면 그것이 우선이다.
- **최종 코드**: 재실행 가능한 산출물은 지정된 목표 폴더에 저장한다. 폴더 미지정이면 작업 전 목표 폴더를 반드시 질문한다.
- 정본(자리·`.gitignore`·승격·정리·파일명): `rules-lazy/code-execution-detail.md` § 코드 저장 규칙

## 탐색성 실행 자동 허용

파일 시스템이나 외부 상태를 **변경하지 않고** 정보를 출력하기만 하는 명령은 사용자 확인 없이 실행한다.
도구 종류(echo, python, bash 등)는 무관 — **효과가 read-only인지**가 기준이다. 단 인라인 실행은 조회(목록·검색·상태 출력)까지다. **수치 계산은 read-only 여도 인라인으로 하지 않고 코드 파일로 저장해 돌린다**(기본 원칙). 저장한 파일의 read-only 실행은 자동 허용에 든다.

### 자동 허용 금지 (사용자 확인 필요)
- 파일 쓰기/삭제/이동을 수반하는 명령 (리다이렉션 `>`, `rm`, `mv`, `cp` 등)
- `ruff check --fix` (파일 수정 수반 — 명시적 사용자 요청 시만)
- `pip install`, `uv add` 등 환경 변경
- 학습/훈련 스크립트 실행 (main 의 tmux 발사는 아래 예외)

## 코드 실행 규칙
1. 코드 작성 완료 후 **즉시 실행 금지** (AI·teammate 모두 해당)
2. **본 실행(학습·훈련·배포·데이터 변경·환경 변경)은 사용자가 직접 수행**한다. AI 실행은 이 파일의 예외 일곱 가지(탐색성 read-only 자동 허용·검증 목적 qa/coder·Figure `gen_*.py` · main 의 gen_gptimg.sh·main 의 tmux 학습 발사·승인 대기 목록의 와쳐 발사·paper-read Step 2·2.5 의 `scripts/pdf_to_md.py` 변환(main 이 변환, scout 이 로컬 경로 `--head` 서두·`--tables`·pdf-inspector 표 조회, 읽기 전용 산출))가 **닫힌 목록**이며 그 밖은 금지다
3. 코드 완료 시 사용자에게 실행 명령서를 출력한다. **학습·훈련 스크립트의 명령서는 발사 세트(메모리 가드·와쳐·목표 표)를 갖춘 `launch-set.sh launch` 형**이다(CLAUDE.md § 연구 환경 규칙). 그 밖의 코드는 아래 형식:
   ```
   코드 준비 완료: {파일 경로}
   실행 명령:
     cd <your-project-root>
     uv run python3 {파일 경로}
   ```
   - **명령이 2개 이상이면 `.sh` 로 묶는다 (사용자 지시)**: 사용자에게 실행을 부탁하는 명령이 2개 이상이면 임시 폴더에 `.sh` 를 저장하고 `bash <경로>` 한 줄과 단계 요약을 준다. 명령 1개는 그대로 보여 준다. 구성(로그 · 비가역 단계 확인 · 실패 시 복구): `rules-lazy/code-execution-detail.md` § 명령 묶음 스크립트
4. **background 실행도 동일 원칙 적용** — 상세: `rules-lazy/background-task.md`

### 예외: 검증 목적 실행 허용 (qa·coder — MANDATORY 경계)
아래는 AI(qa/coder) 직접 실행을 허용한다(qa 검증·Ralph·G-E 루프의 성립 조건):
- **테스트**: pytest 등 단위 테스트 실행
- **dry-run**: `wandb=disabled trainer.fast_dev_run=true` 등 검증용 시험 구동
- **lint·타입체크**: ruff/mypy (read-only)

경계 (qa·coder 불가): 학습·훈련 본 실행, 배포, 데이터 변경·전처리 실행, 환경 변경.

## 예외: main 의 tmux 학습 발사
- main 세션만(subagent·teammate 불가), 사용자가 이번 사이클에 발사를 지시한 학습만 tmux 세션 창에서 `launch-set.sh launch` 로 올린다. 발사 세트·GPU 사용자 배정·verify 증거 규칙(CLAUDE.md § 연구 환경 규칙)은 그대로다. 절차·여전히 사용자 몫인 것: `rules-lazy/background-task.md` § main 의 tmux 직접 발사
- **대기 목록 자동 발사**: 판 > GPU 일 때 사용자가 승인한 목록의 판만 와쳐가 빈 GPU 에 올린다. 목록이 바뀌면 멈추고 main 은 스스로 재승인하지 않는다 — 동 파일 § 대기 목록 자동 발사
- **tmux 세션·창 종료(kill·`exit`·`C-d`)는 대상마다 매번 사용자 재확인**(창이 닫히면 학습이 죽는다)

## 예외: Figure 스크립트 AI 직접 실행 허용
- **대상·조건**: `docs/paper/figures/scripts/` 하위 `gen_*.py`(논문·Confluence 삽입 이미지 생성용, 학습·데이터처리·일반분석 코드는 이 예외 적용 불가)를 `uv run python` 으로 실행
- **TeX**: `latexmk -norc -pdf`·pdflatex 로 `docs/paper/figures/`·`docs/analysis/*.tex` 컴파일(shell-escape 금지)
- **Codex 이미지 생성 (MANDATORY)**: 그릴 주체 결정 팝업에서 사용자가 Codex 이미지 생성을 고른 그림만 main 이 `scripts/gen_gptimg.sh --model --effort` 로 실행한다(모델 · effort 는 사이클당 1회 결정 팝업이고 고르는 것이 비용 승인이다. 서브에이전트 실행 금지. 근거: `skills/figure/SKILL.md`)

## 폴더 사전 지정 (재질문 금지 조건)
임시 폴더는 기본값이라 **질문하지 않는다**. 목표 폴더는 작업 지시에 명시된 경우 재질문하지 않는다. 프로젝트별 폴더 경로는 Mem0 T14로 기억해 재질문 없이 적용한다(`rules-lazy/mem0-templates.md`). 상세: `rules-lazy/code-execution-detail.md` § 폴더 사전 지정

## Teammate 적용
- 위 규칙(저장 폴더·실행 금지)은 teammate 에도 그대로다(프롬프트에 전달). 실행 명령서는 team-lead 에게 SendMessage 로 넘기고 실행은 사용자 직접이다(teammate 금지). teammate 는 탐색성 명령만 실행한다. 예외는 qa 가 리더인 재검증 팀의 qa 하나가 위 «검증 목적 실행»(테스트·dry-run·lint)까지 하는 것이다(토론 팀의 qa·coder 는 해당 없음)
