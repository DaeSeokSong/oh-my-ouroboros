"""plan-confirm-gate.py — main 세션이 계획 확정 없이 «바꾸는 도구» 를 부르면 막는 PreToolUse 게이트

■ 왜 훅인가 (판단 근거 이식 — 2026-11-11)
  규칙은 CLAUDE.md 원칙 3 «수정 계획 보고 → 승인 후 진행» 한 줄뿐이었고 무엇이 승인 대상인지가 main 판단에 맡겨져,
  3줄 요약만 적고 바로 고치는 일이 되풀이됐다(2026-11-06 «결정 답에 질문 · 수정이 섞이면 고친 계획부터 보고», 2026-10-17 점검을 빠뜨린 발사).
  사용자 지시(2026-11-11): «main 세션의 경우 계획 보고 후 사용자와 의견 주고 받은 후 확정되면 진행하도록 하는 걸 하네스에 기입해».
  external-model-gate.py 와 같은 결론이다: «매번 기억해서 지킨다» 를 게이트로 옮긴다.
  의뢰서: intent/2026-11-11-plan-confirm-gate.md · 계획: docs/superpowers/plans/2026-11-11-plan-confirm-gate.md · 규칙 정본: rules-lazy/pre-work-summary.md § 계획 확정

■ 판정 순서 (계획 2.1, 2026-11-11 검수 반영)
  0) 결정 팝업 도구(mcp__decision-popup__ask)는 설정을 읽기 전에, 판정 불가 상태에서도 언제나 통과한다. 설정이 깨지면 사용자에게
     «잘못된 막힘인가» 를 물을 길까지 막히는 교착을 막기 위해서다.
  1) 훅 입력에 agent_id 가 있으면(서브에이전트 · in-process teammate) 통과한다. 단 agent_type 이 설정 readonly_agents(조회용 여섯)이면
     통과시키지 않고 main 과 같은 기준(분류 + main 흐름의 확정 상태)으로 판정한다. 확정 전에 조회용 에이전트를 소집해 실행을 시키는 길을 닫는다.
     agent_type 칸은 엔진 타입 정의(2.1.322 동봉 .claude-plugin/types/claude-code/index.d.ts: «Present when the hook fires from within a
     subagent (alongside agent_id)»)로 확인했고 실제 훅 입력 원문은 관측하지 못했다. 칸이 없으면 종전처럼 통과한다.
  2) 바꾸는 도구가 아니면 통과(아래 «바꾸는 도구»). 목록에 없는 도구는 바꾸는 것으로 본다(기본값 = 바꿈).
  3) 기록용 쓰기면 통과(아래 «기록용 쓰기»). 훅 상태 폴더 쓰기는 확정과 무관하게 언제나 막는다.
  4) 훅 등록 전에 시작한 세션이면 막지 않는다. 5의 판정이 «확정 없음» 또는 판정 불가일 때만 경고 한 줄을 남긴다
     (_audit/plan-confirm-gate.tsv: 시각 · 세션 · 도구 · 까닭). 확정이 살아 있으면 남기지 않는다(의뢰서 성공 기준 9 «확정 없이 썼다»).
  5) main 대화 기록을 끝에서부터 읽어 가장 최근의 «부여» 또는 «소멸» 사건을 찾는다. 부여가 더 최근이면 통과, 아니면 막는다.
  6) 5를 못 하면(기록 없음 · 읽기 실패 · 형식 불명 · 설정 불량 · 훅 안의 예외) 판정 불가로 막는다. 이때만 «잘못된 막힘» 표시를 본다.

■ 부여와 소멸 (계획 2.2) — 표지와 확인 출처
  부여  · 결정 팝업 확정 답: origin 이 엔진의 {"kind":"plugin","name":"decision-popup"} 이고 머리 줄이 «[결정 팝업 확인]» 으로 시작하며,
          직접 입력이 하나도 없고 고른 선택지 하나 이상의 이름이 확정 접두(설정 confirm_prefix, 초기값 «확정:»)로 시작한다.
        · 선택 창(AskUserQuestion) 답: tool_result 가 assistant 의 AskUserQuestion tool_use id 에 묶이고(Bash 출력 위장 차단),
          답마다 그 질문의 선택지 이름과 같으며 고른 이름 하나가 확정 접두로 시작한다.
        · 즉시 실행 문구: 사람이 직접 친 글에 설정 immediate_phrases 가 있다. immediate_phrases_word_end(«바로 해»)는 글 끝이거나
          뒤에 글자 · 숫자가 아닌 문자가 올 때만 일치한다(«바로 해결» 은 일치가 아님). 같은 글에 설정 negation_phrases(«하지 말» 등)가
          있으면 부여하지 않는다(«바로 진행하지 말고» 를 허락으로 읽지 않기 위해서다).
        · 예약 · 루프가 넣은 프롬프트: 사용자 항목에 turnOrigin == "scheduled" 이고 scheduledTaskId 가 있으며 origin 이 없다.
          확인: 2026-11-11, 이 서버 ~/.claude/projects/-home-user-workspace/0560c75c-….jsonl(ScheduleWakeup: isMeta · promptSource=system ·
          wakeupSource=schedule_wakeup · scheduledTaskId) 과 0c7530cd-….jsonl(CronCreate: wakeupSource 없음, scheduledTaskId 있음).
          같은 turnOrigin 이 붙은 compact 요약(isCompactSummary, scheduledTaskId 없음)은 부여가 아니다.
  소멸  · 최종 보고: «끝난 턴의 마지막 main 글» 에 행두(앞 공백 무시) 소문자 «result:» 또는 «failed:» 줄이 있다. 코드펜스 안 · «>» 인용 줄은
          제외한다. claude-notify.sh(Stop 훅이 그 턴의 마지막 글만 본다)와 같은 기준이다. 끝난 턴 = message.stop_reason 이
          end_turn · stop_sequence 이거나 그 뒤에 새 턴의 시작(사람 글 · 팝업 답 · 예약 · 피어 · 작업 알림)이 있다. 같은 턴에 뒤따르는
          main 글(도구 호출 포함, Stop 훅이 되돌려 이어 쓴 글 포함)이 있는 앞 글의 줄은 소멸이 아니다. 대문자 RESULT: 는 T41 계약이라 다른 규약이다.
        · Esc 중단: 사용자 항목에 interruptedMessageId 가 있거나 텍스트 블록이 «[Request interrupted by user» 로 시작한다.
          확인: 2026-11-11, 같은 폴더 대화 기록 전체(interruptedMessageId 56건 · 그 필드가 없는 옛 판 2.1.187~2.1.301 의 텍스트만 있는 꼴 9건).
        · 중단 문구: 사람이 직접 친 글에 설정 stop_phrases 가 있다. 같은 글에 즉시 실행 문구가 있어도 소멸이 이긴다.
        · 직접 입력이 섞인 답(사용자 결정 «직접 입력이 섞이면 확정 아님, 고친 계획을 다시 확정»): 팝업 답에 «직접 입력)» 이 있거나
          답 부분이 애매한 줄(제목 · 이름에 «: N) » 꼴이 또 있음)이 있으면 소멸이다(애매한 줄은 직접 입력을 가렸을 수 있어 막는 쪽으로 읽는다).
          선택 창이면 선택지 이름이 아닌 답 · response · notes 주석이 있을 때 소멸이다. 직접 입력 없이 접두 없는 선택지만 고른 답과
          afkTimeoutMs(자동 응답) · followUp 답은 부여도 소멸도 아니다.
  «사람이 직접 친 글» 은 external-model-gate.py 의 last_user_message() 와 같은 기준이다(_is_non_user() 를 불러 쓴다). 더해서 턴 도중에
  친 글은 user 항목 없이 attachment(type=queued_command · commandMode=prompt · origin.kind=human)로만 남는 일이 있어 그것도 사람 글로 읽는다.
  확인: 2026-11-11, 같은 폴더 대화 기록 전체에서 사람 출처 queued_command 73건 중 28건은 뒤에 user 항목으로 다시 나오지 않았다.

■ 팝업 답 줄을 popup_answers() 로 읽지 않는 까닭
  popup_answers() 는 각 줄의 마지막 «: » 뒤만 답으로 친다. «1) 확정: 이대로 진행» 은 그 규칙으로 읽으면 «이대로 진행» 만 남아 접두를 볼 수 없다.
  그래서 출처 · 머리 줄 검사는 따르되 답 부분은 «: N) » 또는 «: 직접 입력) » 꼴이 줄에 정확히 한 번 있을 때만 읽는다.

■ 바꾸는 도구 (계획 2.3, 2026-11-11 검수 반영)
  · Write · Edit · NotebookEdit: 기록용 경로 밖.
  · Agent · Task: readonly_agents 여섯 밖의 종류, 또는 team_name 이 붙은 소집(teammate 는 agent_type 이 이름이라 1의 판정을 피해 간다).
  · Workflow · CronCreate · CronDelete · RemoteTrigger · ScheduleWakeup · TeamCreate · EnterWorktree · ExitWorktree: 언제나.
  · Artifact: action 이 artifact_read_actions(list · read · open · quickstart) 밖이면 바꾸는 것. action 이 없으면 게시로 본다.
  · Bash · Monitor(command 칸): 확정 전 통과는 두 가지뿐이다(2026-11-11 사용자 확정 «확정 전 Bash 는 정확 일치 목록만 통과, 잘못 막힌 조회는
    쓰면서 목록에 더해 보완»).
    - 정확 일치: 앞뒤 공백만 뗀 명령 글 전체가 설정 bash_exact 의 문장 하나와 글자까지 같다.
    - 기록용 명령: 명령 글이 record_commands 의 정확한 경로(«~/…» · «$HOME/…» 꼴 · 펼친 경로 · 실제 경로)로 시작하고, 그 뒤 인자 어디에도
      (따옴표 안 포함) RECORD_ARG_FORBIDDEN 문자(명령을 잇거나 바꿔 넣는 ; | & $ ` < > ( ) { } \\ # 개행 복귀)가 없다.
    - 그 밖은 전부 바꾸는 것이다. 명령을 풀어 읽지 않는다.
    구조를 바꾼 까닭: 명령을 풀어 읽는 허용 문법(조각 나누기 · 명령별 옵션 목록 · 인용 판별 · git 전역 옵션 규칙)이 security 검수 세 번 연속으로
    새 틈을 냈다(1차 접두 명령 · 변수 앞세우기, 2차 글롭 · 중괄호 전개와 tmux 구분자, 3차 주석 뒤 따옴표가 줄을 넘어 뒤 줄을 가림과 기록용 폴더의
    git 설정 실행 항목). 셸 문법을 다시 구현하는 판정은 끝까지 셸과 어긋나므로 풀어 읽기를 그만두고 글자 일치로 바꿨다.
  · MCP: mcp_allow_tools(결정 팝업 · 메모리 기록)에 들거나 도구 이름의 첫 낱말(서버 이름 낱말 뒤 첫 낱말 포함)이 mcp_read_verbs 에 들면 통과.
  · 설정 pass_tools(Read · Grep · Glob · AskUserQuestion · SendMessage · Skill 등)는 통과. SendMessage · Skill 은 훅 대상에 넣지 않고
    문구 규칙으로 다룬다(2026-11-11 main 결정, 남는 한계). 그 밖의 모든 도구는 바꾸는 것이다.

■ 기록용 쓰기 (계획 2.4)
  cwd 의 git 뿌리 아래 .scratch/ · ~/.claude/config/scratch-root 가 가리키는 곳 · 경로 꼴 ~/.claude/projects/<한 칸>/memory/ 아래 ·
  ~/.claude/jobs/<잡>/tmp/ 아래 · 결정 기록 파일(config/hosts/<호스트>.json 의 paths.short_term_root + decisions.md, rules-lazy/memory-write.md),
  Bash 는 record_commands(감시 서명 oversight-append.sh) 만. 경로는 실제 경로로 풀어 비교한다(.. · 링크로 벗어나면 기록용이 아니다).
  실제 경로의 어느 요소든 «.git» 이면 기록용이 아니다(기록용 폴더 안에 git 설정 폴더를 만들면 그 폴더의 git 조회가 설정의 실행 항목을 돌린다, 2026-11-11 security 상).
  훅 상태 폴더(~/.claude/_usage/plan-confirm-gate/)는 등록 시각 · «잘못된 막힘» 표시를 담으므로 도구 쓰기를 언제나 막는다.

■ 판정 불가와 «잘못된 막힘» (계획 2.5)
  판정 불가면 막고 사용자에게 잘못된 막힘인지 물으라고 알린다. 결정 팝업 mod 는 사용자가 고른 선택지 이름이 설정 wrong_block_label
  («잘못된 막힘») 과 정확히 같을 때만 상태 폴더 wrong-block/<세션 id> 표시 파일을 남긴다(직접 입력 글로는 생기지 않는다). 훅은 판정 불가일
  때만 그 표시를 보고, 있으면 훅 자신의 파일 묶음(HOOK_FILES)의 Write · Edit 만 통과시킨다. 시간으로 풀리는 통과는 없다(사용자 거절).
  정상 판정이 되면 표시를 지운다(남은 표시의 재사용을 막는다).

■ 전환 (계획 2.6)
  처음 실행될 때 상태 폴더에 registered-at(UTC ISO) 을 남긴다. 대화 기록 첫 항목의 timestamp 가 그보다 앞이면 등록 전 세션이다.
  세션 시작 시각을 알 수 없으면 등록 뒤 세션으로 본다.

■ 실패 방향
  차단 출력은 ASCII(JSON \\u 이스케이프)로 내보내 표준 출력 인코딩과 무관하게 실패하지 않게 한다. 출력 단계에서도 예외가 나면
  표준 오류에 사유를 쓰고 종료 코드 2(Claude Code 의 차단 코드)로 끝낸다. 입력은 바이트로 읽어 UTF-8 로 푼다.

■ 막지 못하는 것 (알려진 한계)
  · tmux 창으로 띄운 teammate(별도 프로세스)는 면제하지 못하고 main 처럼 판정된다. 2026-11-11 이 서버 기록을 확인했다
    (~/.claude/projects 의 세션 대화 기록 86개 머리 40줄 · ~/.claude/teams/*/config.json). 대화 기록 머리에는 팀 이름 칸이 없고
    agent-setting 의 agentSetting 은 늘 «claude», agent-name 은 /rename 세션 이름이다. 팀 설정의 구성원은 모두 in-process 였다.
  · SendMessage · Skill 은 훅 대상이 아니다. 예약 프롬프트는 만들 때의 확정에 기대며 훅은 그 지시의 범위를 모른다.
  · 확정은 최종 보고에 result: · failed: 줄을 써야 끝난다. 그 줄 없이 턴을 끝내면(Stop 훅이 되돌린 뒤의 마지막 글 포함) 확정이 다음 요청까지 이어진다.
  · 저장해 둔 스크립트의 읽기 전용 실행도 실행으로 보아 확정 전에는 막는다.
  · Bash 의 상태 폴더 보호는 명령 글에 «_usage/plan-confirm-gate» 가 보일 때만 건다. 단 그런 명령도 정확 일치 · 기록용 명령이 아니면 확정이 있어야 돈다.
  · 확정이 살아 있는 동안 대화 기록 파일 자체를 고쳐 쓰는 위조는 막지 않는다. 등록 전 시작 세션을 resume 하면 계속 등록 전 세션이다.
  · AskUserQuestion 에서 선택지 이름과 글자 하나까지 같은 글을 직접 쳤으면 고른 것과 구분하지 못한다.
시험: scripts/tests/test_plan_confirm_gate.py (pytest, 합성 대화 기록). 이 파일을 고치면 먼저 돌린다.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True   # external-model-gate.py 를 불러올 때 하네스 scripts/ 에 __pycache__ 를 남기지 않는다
UTC = timezone.utc   # noqa: UP017  훅은 시스템 python3 3.10 으로 돈다(datetime.UTC 는 3.11 부터)

HARNESS = Path(__file__).resolve().parent.parent
CONFIG = HARNESS / "config/plan-confirm-gate.json"
EXTERNAL_GATE = HARNESS / "scripts/external-model-gate.py"
# «잘못된 막힘» 표시가 있을 때 판정 불가 상태에서도 Write · Edit 를 허용하는 훅 자신의 파일 묶음(계획 2.5)
HOOK_FILES = (HARNESS / "scripts/plan-confirm-gate.py", CONFIG,
              HARNESS / "scripts/tests/test_plan_confirm_gate.py", HARNESS / "rules-lazy/pre-work-summary.md")
TAG = "[계획 확정 게이트]"
POPUP_TOOL = "mcp__decision-popup__ask"
# 사건 없이 읽는 상한. 실측(2026-11-11, 검수 반영판): 이 서버 실제 기록 351MB~1,021MB 3개는 최근 사건을 0.05~0.09초에 찾았고, 사건이 없는 116MB
# 합성 기록(사람 글 · main 글 · 도구 결과 섞음)에서 64MB 까지 읽고 멈추는 최악이 0.54초였다(훅 timeout 10초 대비 여유). 그보다 오래된 확정은 최종 보고 없이 64MB 를 넘긴 작업뿐이라 다시 확정받게 한다.
SCAN_LIMIT_BYTES = 64 * 1024 * 1024
# 선택 창 답에서 그 tool_use 를 찾으러 거슬러 올라가는 줄 수 상한. 실측(2026-11-11): 같은 폴더 기록의 선택 창 답 348건에서 tool_use 와 답 사이는
# 최대 27줄 · 99분위 16줄이었다. 5000 은 그 180배 여유이고, 못 찾으면 부여하지 않는 쪽(막는 쪽)으로 틀린다.
BIND_LOOKBACK_LINES = 5000
SESSION_ID_OK = re.compile(r"^[A-Za-z0-9_-]{1,64}$")   # 표시 파일 이름으로 쓰므로 mod 와 같은 모양 검사
WRITE_TOOLS = ("Write", "Edit", "NotebookEdit")
AGENT_TOOLS = ("Agent", "Task")
SHELL_TOOLS = ("Bash", "Monitor")
ALWAYS_CHANGING = ("Workflow", "CronCreate", "CronDelete", "RemoteTrigger", "ScheduleWakeup", "TeamCreate", "EnterWorktree", "ExitWorktree")
END_REASONS = ("end_turn", "stop_sequence")
STATE_MARK = "_usage/plan-confirm-gate"
# 기록용 명령 인자에 하나라도 있으면 바꾸는 것으로 보는 문자(따옴표 안 포함): 명령을 잇거나(; | & 개행 복귀) 바꿔 넣는($ ` < > ( ) { } \ #) 문자
RECORD_ARG_FORBIDDEN = frozenset(";|&$`<>(){}\\#\n\r")

ANSWER_PART = re.compile(r": (\d+|직접 입력)\) ")
LIST_KEYS = ("immediate_phrases", "immediate_phrases_word_end", "negation_phrases", "stop_phrases", "readonly_agents", "pass_tools",
             "record_commands", "mcp_read_verbs", "mcp_allow_tools", "artifact_read_actions")
# 비면 규칙 하나가 꺼지는 목록(중단 문구 없음 = 중단 불가, 조회용 에이전트 없음 = 1의 판정 꺼짐, 부정 표현 없음 = 부정 무시) — 비면 판정 불가
NONEMPTY_KEYS = ("stop_phrases", "readonly_agents", "negation_phrases")


class Undecidable(Exception):
    """Raised when the hook cannot judge; the call is blocked as undecidable."""


def deny(reason: str) -> None:
    """Emit a PreToolUse deny as ASCII JSON; if even that fails, exit 2 (block) with the reason on stderr."""
    out = json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}, ensure_ascii=True)
    try:
        sys.stdout.write(out + "\n")
        sys.stdout.flush()
    except Exception:  # noqa: BLE001  출력 단계의 어떤 예외도 통과가 되면 안 된다 — 종료 코드 2 로 막는다
        try:
            sys.stderr.write(reason.encode("ascii", "backslashreplace").decode("ascii") + "\n")
        except Exception:  # noqa: BLE001, S110  표준 오류도 못 쓰면 사유 없이 막는다
            pass
        os._exit(2)
    sys.exit(0)


def state_dir() -> Path:
    """Return the hook state folder (HOME based, so tests can redirect it)."""
    return Path.home() / ".claude" / STATE_MARK


def load_config() -> dict:
    """Load and type-check the fixed-string config; a broken or rule-disabling config is undecidable."""
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Undecidable(f"설정 파일 {CONFIG.name} 을 읽지 못했습니다({type(e).__name__})") from e

    def strs(v):
        return isinstance(v, list) and all(isinstance(x, str) and x for x in v)

    ok = (isinstance(cfg, dict) and all(isinstance(cfg.get(k), str) and cfg[k] for k in ("confirm_prefix", "wrong_block_label"))
          and all(strs(cfg.get(k)) for k in (*LIST_KEYS, "bash_exact")))   # bash_exact 는 비어도 된다(정확 일치 통과가 없을 뿐)
    if not ok:
        raise Undecidable(f"설정 파일 {CONFIG.name} 의 형식이 틀립니다(고정 문자열 목록이어야 합니다)")
    empty = [k for k in NONEMPTY_KEYS if not cfg[k]]
    if empty:
        raise Undecidable(f"설정 파일 {CONFIG.name} 의 {', '.join(empty)} 가 비어 규칙이 꺼집니다")
    return cfg


def load_external_gate():
    """Import external-model-gate.py to reuse its user-text and popup criteria (that file is not modified)."""
    spec = importlib.util.spec_from_file_location("external_model_gate", EXTERNAL_GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---- 경로 ----
def real(p: str, cwd: str) -> str:
    """Resolve a tool path to its real absolute path (relative paths against the session cwd)."""
    p = os.path.expanduser(p)
    return os.path.realpath(p if os.path.isabs(p) else os.path.join(cwd, p))


def under(p: str, root: str) -> bool:
    """True if p is root itself or inside it."""
    return p == root or p.startswith(root.rstrip(os.sep) + os.sep)


def project_root(cwd: str) -> str | None:
    """Return the git root above cwd (directory holding .git), or None outside a repository."""
    d = os.path.realpath(cwd)
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def decisions_file() -> str | None:
    """Return the real path of the decision log (short_term_root/decisions.md from this host's registry), or None."""
    try:
        host = json.loads((HARNESS / f"config/hosts/{socket.gethostname().split('.')[0]}.json").read_text(encoding="utf-8"))
        root = host["paths"]["short_term_root"]
    except (OSError, ValueError, KeyError, TypeError):
        return None   # 등록부가 없거나 칸이 없는 서버: 메모리 폴더 꼴 판정만 남는다
    return os.path.realpath(os.path.join(os.path.expanduser(root), "decisions.md")) if isinstance(root, str) and root else None


def _under_pattern(rp: str, base: Path, middle: str) -> bool:
    """True if rp lies under <base>/<one name>/<middle>/ (path shape, not existing folders)."""
    b = os.path.realpath(base)
    if not under(rp, b) or rp == b:
        return False
    parts = os.path.relpath(rp, b).split(os.sep)
    return len(parts) >= 3 and parts[0] not in ("", ".", "..") and parts[1] == middle


def is_record_path(rp: str, cwd: str) -> bool:
    """True if a resolved path is a record location (계획 2.4); any «.git» path element makes it a change."""
    if ".git" in rp.split(os.sep):
        return False   # 기록용 폴더 안의 git 설정 폴더(hooks · config 실행 항목)는 기록이 아니다(2026-11-11 security 상)
    home = Path.home() / ".claude"
    roots = []
    root = project_root(cwd)
    if root:
        roots.append(os.path.realpath(os.path.join(root, ".scratch")))
    try:
        first = (home / "config/scratch-root").read_text(encoding="utf-8").strip().splitlines()[0].strip()
        if os.path.isabs(os.path.expanduser(first)):
            roots.append(os.path.realpath(os.path.expanduser(first)))
    except (OSError, IndexError):
        pass   # 서버 지정 임시 폴더가 없는 서버
    if any(under(rp, r) and rp != r for r in roots):
        return True
    # rp 는 이미 실제 경로라 경로 꼴이 맞으면 그 폴더들도 실재하는 진짜 폴더다(링크로 밖을 가리키면 rp 가 밖으로 풀려 꼴이 안 맞는다)
    return _under_pattern(rp, home / "projects", "memory") or _under_pattern(rp, home / "jobs", "tmp") or rp == decisions_file()


# ---- Bash 정확 일치 (2026-11-11 개정 1: 허용 문법을 걷어 냄, 까닭은 모듈 docstring «바꾸는 도구») ----
def _record_prefixes(cfg: dict) -> set[str]:
    """Return the accepted spellings of each record command path: «~/…», «$HOME/…», expanded and real path."""
    home = str(Path.home())
    out = set()
    for c in cfg["record_commands"]:
        full = os.path.expanduser(c)
        out |= {full, os.path.realpath(full)}
        if full.startswith(home + os.sep):
            out |= {"~" + full[len(home):], "$HOME" + full[len(home):]}
    return out


def shell_kind(cmd: str, cfg: dict) -> str:
    """Return pass (exact sentence), record (record command with plain args), state or change for a shell command (Bash · Monitor)."""
    s = cmd.strip()
    if s and s in cfg["bash_exact"]:
        return "pass"
    for p in _record_prefixes(cfg):
        rest = s[len(p):] if s.startswith(p) else None
        # 경로 바로 뒤는 끝이거나 공백이어야 한다(«…append.sh2» 같은 다른 파일 차단). 인자는 따옴표 안까지 금지 문자 검사(풀어 읽지 않는다)
        if rest is not None and (rest == "" or rest[0] in " \t") and not any(ch in RECORD_ARG_FORBIDDEN for ch in rest):
            return "record"
    return "state" if STATE_MARK in cmd else "change"


def mcp_readonly(tool: str, cfg: dict) -> bool:
    """True if an MCP tool is the popup / memory record or its name starts with a read verb."""
    if tool in cfg["mcp_allow_tools"]:
        return True
    parts = tool.split("__")
    if len(parts) < 3:
        return False
    words = [w.lower() for w in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", "__".join(parts[2:]))]
    server = {w.lower() for w in re.findall(r"[A-Za-z]+", parts[1])}
    verbs = set(cfg["mcp_read_verbs"])
    # «tavily_search» 처럼 서버 이름 낱말이 앞에 붙은 도구는 그 뒤 낱말을 동사로 본다
    return bool(words) and (words[0] in verbs or (len(words) > 1 and words[0] in server and words[1] in verbs))


def classify_call(tool: str, ti: dict, cfg: dict, cwd: str) -> str:
    """Return pass, record, state or change for one tool call (계획 2.3 · 2.4); unknown tools are change."""
    if tool in WRITE_TOOLS:
        p = ti.get("file_path") or ti.get("notebook_path")
        if not isinstance(p, str) or not p:
            return "change"
        rp = real(p, cwd)
        if under(rp, os.path.realpath(state_dir())):
            return "state"
        return "record" if is_record_path(rp, cwd) else "change"
    if tool in AGENT_TOOLS:
        return "pass" if ti.get("subagent_type") in cfg["readonly_agents"] and not ti.get("team_name") else "change"
    if tool in SHELL_TOOLS:
        cmd = ti.get("command")
        return shell_kind(cmd, cfg) if isinstance(cmd, str) else "change"   # Monitor 의 ws(웹소켓)도 바꾸는 것
    if tool == "Artifact":   # action 이 없으면 게시로 본다
        return "pass" if ti.get("action") in cfg["artifact_read_actions"] else "change"
    if tool.startswith("mcp__"):
        return "pass" if mcp_readonly(tool, cfg) else "change"
    if tool in cfg["pass_tools"] and tool not in ALWAYS_CHANGING:
        return "pass"
    return "change"


# ---- 전환(등록 전 세션) ----
def _parse_ts(s) -> datetime | None:
    """Parse an ISO timestamp (Z allowed) as aware UTC, or None."""
    if not isinstance(s, str) or not s:
        return None
    try:
        t = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))   # noqa: FURB162  훅은 시스템 python3 3.10 으로 돈다(3.10 은 «Z» 를 못 읽는다)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def registered_at() -> datetime | None:
    """Return the registration time, creating it on first run (None if it cannot be known)."""
    f = state_dir() / "registered-at"
    try:
        return _parse_ts(f.read_text(encoding="utf-8"))
    except FileNotFoundError:
        pass
    now = datetime.now(UTC)
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(now.isoformat().replace("+00:00", "Z") + "\n")
        return now
    except FileExistsError:
        return _parse_ts(f.read_text(encoding="utf-8"))   # 다른 세션이 동시에 만들었다
    except OSError:
        return None


def session_started(tp: Path) -> datetime | None:
    """Return the first entry timestamp of the transcript, or None."""
    with open(tp, "rb") as fh:
        for _ in range(50):
            raw = fh.readline()
            if not raw:
                break
            try:
                d = json.loads(raw)
            except ValueError:
                continue
            ts = _parse_ts(d.get("timestamp")) if isinstance(d, dict) else None
            if ts:
                return ts
    return None


def warn_pre_registration(sid: str, tool: str, why: str) -> None:
    """Append one TSV warning line for an unconfirmed change in a pre-registration session (failure is ignored)."""
    def cell(s):
        return re.sub(r"[\t\r\n]", " ", str(s))[:120]

    try:
        log = Path.home() / ".claude/_audit/plan-confirm-gate.tsv"
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now(UTC).isoformat()}\t{cell(sid)}\t{cell(tool)}\t등록 전 시작 세션이라 막지 않음: {cell(why)}\n")
    except OSError:
        pass   # 경고 기록 실패는 통과를 막지 않는다(전환 규칙: 등록 전 세션은 막지 않는다)


# ---- 대화 기록 읽기 ----
class Lines:
    """Reverse line iterator over a transcript with push-back and a byte limit."""

    def __init__(self, path: Path, limit: int = SCAN_LIMIT_BYTES):
        self.truncated = False
        self._back: list[bytes] = []
        self._gen = self._reverse(path, limit)

    def __iter__(self):
        return self

    def __next__(self) -> bytes:
        return self._back.pop() if self._back else next(self._gen)

    def _reverse(self, path: Path, limit: int, block: int = 1 << 18):
        with open(path, "rb") as fh:
            pos = fh.seek(0, os.SEEK_END)
            carry: list[bytes] = []   # 아직 줄 머리를 못 찾은 조각들(앞쪽 조각이 앞)
            read = 0
            while pos > 0:
                if read >= limit:
                    self.truncated = True
                    return
                n = min(block, pos)
                pos -= n
                fh.seek(pos)
                chunk = fh.read(n)
                read += n
                parts = chunk.split(b"\n")
                if len(parts) == 1:
                    carry.insert(0, chunk)
                    continue
                tail = parts[-1] + b"".join(carry)
                if tail:
                    yield tail
                for ln in reversed(parts[1:-1]):
                    if ln:
                        yield ln
                carry = [parts[0]]
            head = b"".join(carry)
            if head:
                yield head

    def bound_to_ask(self, tid: str) -> bool:
        """Look further back for the AskUserQuestion tool_use with this id; consumed lines are pushed back."""
        needle, taken, found = tid.encode(), [], False
        for _ in range(BIND_LOOKBACK_LINES):
            try:
                raw = next(self)
            except StopIteration:
                break
            taken.append(raw)
            if needle in raw and b'"tool_use"' in raw:
                try:
                    d = json.loads(raw)
                except ValueError:
                    continue
                c = (d.get("message") or {}).get("content") if isinstance(d, dict) else None
                if d.get("type") == "assistant" and not d.get("isSidechain") and isinstance(c, list) and any(
                        isinstance(b, dict) and b.get("type") == "tool_use" and b.get("id") == tid and b.get("name") == "AskUserQuestion" for b in c):
                    found = True
                    break
        self._back.extend(reversed(taken))
        return found


def _content(d: dict):
    """Return message.content (str, list or None)."""
    m = d.get("message")
    return m.get("content") if isinstance(m, dict) else None


def _texts(c) -> str | None:
    """Join text blocks; None if the content holds a tool_result or is not text."""
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        if any(isinstance(x, dict) and x.get("type") == "tool_result" for x in c):
            return None
        return " ".join(str(x.get("text", "")) for x in c if isinstance(x, dict) and x.get("type") == "text")
    return None


def _clean_human(t: str) -> str | None:
    """Apply last_user_message()'s text rules: slash commands keep only args, «<» injections are not typed text."""
    t = t.strip()
    if t.startswith("<command-name>"):
        a = re.search(r"<command-args>(.*?)</command-args>", t, re.DOTALL)
        t = a.group(1).strip() if a else ""
    return None if not t or t.startswith("<") else t


def human_text(d: dict, gate) -> str | None:
    """Return the text a person typed in this entry (user entry or human queued_command attachment)."""
    if d.get("type") == "attachment":
        a = d.get("attachment")
        o = a.get("origin") if isinstance(a, dict) else None
        if not (isinstance(a, dict) and a.get("type") == "queued_command" and a.get("commandMode") == "prompt"
                and isinstance(o, dict) and o.get("kind") == "human" and not a.get("isMeta")):
            return None
        p = _texts(a.get("prompt"))
        return _clean_human(p) if p is not None else None
    if d.get("type") != "user":
        return None
    t = _texts(_content(d))
    t = _clean_human(t) if t is not None else None
    return None if t is None or gate._is_non_user(d, t) else t


def has_final_line(d: dict) -> bool:
    """True if a main text has a line starting with lowercase result: or failed: (fences and quotes skipped)."""
    c = _content(d)
    blocks = [c] if isinstance(c, str) else [b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text"] if isinstance(c, list) else []
    for text in blocks:
        fence = False
        for line in str(text).split("\n"):
            s = line.lstrip()
            if s.startswith("```"):
                fence = not fence
                continue
            if not fence and not s.startswith(">") and s.startswith(("result:", "failed:")):
                return True
    return False


def is_interrupt(d: dict) -> bool:
    """True for the Esc interrupt marker entry."""
    if d.get("interruptedMessageId"):
        return True
    t = _texts(_content(d))
    return t is not None and t.lstrip().startswith("[Request interrupted by user")


def is_scheduled(d: dict) -> bool:
    """True for a prompt injected by ScheduleWakeup / CronCreate (확인한 꼴은 모듈 docstring)."""
    sid = d.get("scheduledTaskId")
    return d.get("turnOrigin") == "scheduled" and isinstance(sid, str) and bool(sid) and d.get("origin") is None and not d.get("isCompactSummary")


def is_turn_start(d: dict, gate) -> bool:
    """True for an entry that starts a new turn (typed text, popup answer, scheduled, peer, task notification)."""
    if d.get("type") == "attachment":
        return human_text(d, gate) is not None
    if d.get("type") != "user" or _texts(_content(d)) is None:
        return False
    o = d.get("origin")
    return (bool(d.get("turnOrigin")) or (isinstance(o, dict) and o.get("kind") in ("human", "peer", "task-notification", "plugin"))
            or human_text(d, gate) is not None)


def popup_verdict(d: dict, prefix: str, gate):
    """Return ("grant", "popup"), ("revoke", "direct" | "ambiguous") or None for a decision-popup message."""
    if d.get("origin") != gate.POPUP_ORIGIN or d.get("isMeta"):
        return None
    c = _texts(_content(d))
    if not c:
        return None
    lines = c.split("\n")   # 엔진 · 팝업이 쓰는 «\n» 에서만 나눈다(popup_answers 와 같은 까닭)
    head = next((i for i, ln in enumerate(lines) if ln.lstrip().startswith("[결정 팝업 ")), None)
    if head is None or not lines[head].lstrip().startswith(gate.POPUP_MARK):
        return None   # «[결정 팝업 닫힘]» 등은 답이 아니다
    confirmed = False
    for ln in lines[head + 1:]:
        ln = ln.strip()
        if not ln.startswith("- "):
            continue
        ms = list(ANSWER_PART.finditer(ln))
        if len(ms) != 1:
            return ("revoke", "ambiguous")   # 답 부분을 가려낼 수 없다(직접 입력을 가렸을 수 있어 막는 쪽)
        if ms[0].group(1) == "직접 입력":
            return ("revoke", "direct")
        if ln[ms[0].end():].startswith(prefix):
            confirmed = True
    return ("grant", "popup") if confirmed else None


def ask_verdict(tur: dict, prefix: str) -> str | None:
    """Return grant (only picked labels, one prefixed), revoke (typed answer · response · notes) or None (AFK · followUp · no prefix)."""
    if tur.get("afkTimeoutMs") is not None or tur.get("followUp"):
        return None   # 사람이 고른 답이 아니거나 질문을 다시 받기로 한 답: 부여도 소멸도 아니다
    answers = tur.get("answers")
    if not isinstance(answers, dict):
        return None
    if str(tur.get("response") or "").strip():
        return "revoke"
    notes = tur.get("annotations") if isinstance(tur.get("annotations"), dict) else {}
    if any(isinstance(v, dict) and str(v.get("notes") or "").strip() for v in notes.values()):
        return "revoke"
    picked = []
    for q in tur.get("questions") or []:
        if not isinstance(q, dict) or not isinstance(q.get("question"), str):
            return None
        labels = [o.get("label") for o in q.get("options") or [] if isinstance(o, dict) and isinstance(o.get("label"), str)]
        a = answers.get(q.get("question"))
        if a is None:
            continue   # 비워 둔 질문은 직접 입력이 아니다
        parts = [a] if a in labels else a.split(", ") if isinstance(a, str) and q.get("multiSelect") else None
        if not parts or any(p not in labels for p in parts):
            return "revoke"   # 선택지 이름이 아닌 답 = 자유 입력
        picked += parts
    return "grant" if any(p.startswith(prefix) for p in picked) else None


def has_immediate(text: str, cfg: dict) -> bool:
    """True if the text holds an immediate-run phrase and no negation phrase."""
    if any(n in text for n in cfg["negation_phrases"]):
        return False   # «바로 진행하지 말고» 같은 글은 허락이 아니다
    if any(p in text for p in cfg["immediate_phrases"]):
        return True
    for p in cfg["immediate_phrases_word_end"]:
        i = text.find(p)
        while i >= 0:
            end = i + len(p)
            if end == len(text) or not text[end].isalnum():
                return True
            i = text.find(p, i + 1)
    return False


def entry_event(d: dict, cfg: dict, gate, later_main: bool, boundary_after: bool):
    """Return ("grant"|"revoke", code), ("ask", tool_use_id) for a grant awaiting binding, or None for one main-flow entry."""
    kind = d.get("type")
    if kind == "assistant":
        m = d.get("message") if isinstance(d.get("message"), dict) else {}
        finished = m.get("stop_reason") in END_REASONS or boundary_after
        return ("revoke", "final") if not later_main and finished and has_final_line(d) else None
    if kind == "attachment":
        text = human_text(d, gate)
    elif kind != "user":
        return None
    else:
        if is_interrupt(d):
            return ("revoke", "esc")
        if is_scheduled(d):
            return ("grant", "scheduled")
        if d.get("origin") == gate.POPUP_ORIGIN:
            return popup_verdict(d, cfg["confirm_prefix"], gate)
        tur = d.get("toolUseResult")
        if isinstance(tur, dict) and isinstance(tur.get("questions"), list):
            c = _content(d)
            tid = next((b.get("tool_use_id") for b in c if isinstance(b, dict) and b.get("type") == "tool_result"), None) if isinstance(c, list) else None
            if not (isinstance(tid, str) and tid):
                return None
            v = ask_verdict(tur, cfg["confirm_prefix"])
            # 소멸은 막는 쪽이라 결박 없이 받고, 부여만 AskUserQuestion tool_use 결박을 거친다(latest_event)
            return ("revoke", "direct") if v == "revoke" else ("ask", tid) if v == "grant" else None
        text = human_text(d, gate)
    if text is None:
        return None
    if any(p in text for p in cfg["stop_phrases"]):
        return ("revoke", "stop")
    return ("grant", "immediate") if has_immediate(text, cfg) else None


def latest_event(tp: Path, cfg: dict, gate):
    """Scan the main transcript from the end and return the most recent grant/revoke, or ("none", code)."""
    it = Lines(tp)
    parsed = 0
    later_main = False      # 이 항목 뒤(같은 턴)에 main 글 · 도구 호출이 있었는가
    boundary_after = False  # 이 항목 뒤에 새 턴의 시작이 있었는가
    for raw in it:
        if b'"tool_use_id":"' in raw and b'"questions"' not in raw:
            continue   # 도구 결과 줄(대화 기록 용량의 대부분)은 선택 창 답이 아니면 풀지 않는다
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        parsed += 1
        if d.get("isSidechain"):
            continue
        ev = entry_event(d, cfg, gate, later_main, boundary_after)
        if d.get("type") == "assistant" and _content(d):
            later_main = True
        elif is_turn_start(d, gate):
            later_main, boundary_after = False, True
        if ev is None:
            continue
        if ev[0] == "ask":
            if it.bound_to_ask(ev[1]):
                return ("grant", "ask")
            continue
        return ev
    if it.truncated:
        return ("none", "limit")
    if parsed == 0:
        raise Undecidable("대화 기록의 형식을 알아볼 수 없습니다")
    return ("none", "none")


# ---- 표시 파일 ----
def marker_path(sid: str) -> Path | None:
    """Return the wrong-block marker path for a well-formed session id."""
    return state_dir() / "wrong-block" / sid if SESSION_ID_OK.match(sid or "") else None


def marker_allows(inp: dict) -> bool:
    """True if a user-chosen wrong-block marker exists and the call is Write/Edit on the hook's own files."""
    m = marker_path(str(inp.get("session_id") or ""))
    ti = inp.get("tool_input") if isinstance(inp.get("tool_input"), dict) else {}
    p = ti.get("file_path")
    if not m or not m.is_file() or inp.get("tool_name") not in ("Write", "Edit") or not isinstance(p, str) or not p:
        return False
    return real(p, str(inp.get("cwd") or os.getcwd())) in {os.path.realpath(f) for f in HOOK_FILES}


def clear_marker(sid: str) -> None:
    """Remove a leftover marker once the hook can judge again."""
    m = marker_path(sid)
    try:
        if m:
            m.unlink()
    except OSError:
        pass   # 없거나 못 지워도 판정에는 영향이 없다(표시는 판정 불가일 때만 본다)


# ---- 차단 문구 ----
WHY = {
    "final": "가장 최근 사건이 끝난 턴의 최종 보고(행두 result: · failed: 줄)입니다. 확정은 최종 보고를 낼 때까지만 유효합니다.",
    "esc": "가장 최근 사건이 Esc 중단입니다. 중단하면 확정이 사라집니다.",
    "stop": "가장 최근 사람 글에 중단 문구가 있습니다. 중단 요청으로 확정이 사라졌습니다.",
    "direct": "가장 최근 결정 팝업 · 선택 창 답에 직접 입력이 섞였습니다. 그 입력을 반영한 계획을 다시 올려 확정받으십시오.",
    "ambiguous": ("가장 최근 결정 팝업 답의 한 줄에서 답 부분을 가려낼 수 없었습니다(항목 제목이나 선택지 이름에 «: 번호) » 꼴이 또 들어 있음). "
                  "제목과 선택지 이름에서 그 꼴을 빼고 확정 항목을 다시 띄우십시오."),
    "none": "이 세션에 확정 답이 없습니다.",
    "limit": f"대화 기록 끝 {SCAN_LIMIT_BYTES // (1024 * 1024)}MB 안에 확정 답이 없습니다.",
}


def no_grant_message(tool: str, code: str, cfg: dict) -> str:
    """Korean deny reason for a call without a live confirmation."""
    return (f"{TAG} 계획 확정이 살아 있지 않아 «{tool}» 호출을 막았습니다. 까닭: {WHY.get(code, code)}\n"
            "  푸는 방법: 계획을 보고하고 사용자와 의견을 주고받은 뒤 결정 팝업(mcp__decision-popup__ask, 모바일 모드면 AskUserQuestion)으로 "
            f"확정 항목을 띄우십시오. 확정 선택지 이름은 «{cfg['confirm_prefix']}» 으로 시작해야 하고, 직접 입력이 하나라도 섞인 답은 확정이 아닙니다. "
            "채팅의 «진행해» 는 확정이 아니므로 그 말을 받으면 확정 항목 하나를 띄우십시오.\n"
            f"  확정을 받았는데도 막혔다면 잘못된 막힘인지 물으십시오(선택지 이름 «{cfg['wrong_block_label']}» · «정상 막힘»). "
            "규칙: rules-lazy/pre-work-summary.md § 계획 확정")


def undecidable_message(tool: str, why: str) -> str:
    """Korean deny reason for an undecidable call."""
    files = " · ".join(os.path.relpath(f, HARNESS) for f in HOOK_FILES)
    return (f"{TAG} 판정하지 못해 «{tool}» 호출을 막았습니다(까닭: {why}).\n"
            "  사용자에게 잘못된 막힘인지 물으십시오. 모바일 모드면 AskUserQuestion, 아니면 결정 팝업으로 띄우고 선택지 이름은 정확히 «잘못된 막힘» · «정상 막힘» 으로 씁니다.\n"
            f"  사용자가 «잘못된 막힘» 을 고르면 이 훅의 파일 묶음({files})의 Write · Edit 만 통과합니다. "
            "하네스 매니저 세션이 아니면 매니저 세션에 알리고, 훅이 고쳐지면 같은 작업을 다시 시도하십시오(시간으로 풀리는 통과는 없습니다).")


def state_message() -> str:
    """Korean deny reason for writes into the hook state folder."""
    return (f"{TAG} 훅 상태 폴더({state_dir()})는 도구로 쓸 수 없습니다. 등록 시각과 «잘못된 막힘» 표시를 담는 곳이라 "
            "훅과 결정 팝업 mod 만 씁니다(확정 여부와 무관하게 막습니다).")


# ---- 진입점 ----
def judge(inp: dict) -> None:
    """Apply the 판정 순서; returns to allow, calls deny() to block, raises Undecidable."""
    tool = str(inp.get("tool_name") or "")
    if tool == POPUP_TOOL:
        return                                                   # 0) 사용자에게 묻는 길은 언제나 연다
    cfg = load_config()
    if inp.get("agent_id") and inp.get("agent_type") not in cfg["readonly_agents"]:
        return                                                   # 1) 쓰는 서브에이전트 · teammate
    gate = load_external_gate()
    ti = inp.get("tool_input") if isinstance(inp.get("tool_input"), dict) else {}
    cwd = str(inp.get("cwd") or os.getcwd())
    kind = classify_call(tool, ti, cfg, cwd)
    if kind in ("pass", "record"):
        return                                                   # 2) · 3)
    if kind == "state":
        deny(state_message())
    sid = str(inp.get("session_id") or "")
    tp = gate.main_transcript(str(inp.get("transcript_path") or ""), sid)
    if tp is None:
        raise Undecidable("대화 기록을 찾지 못했습니다")
    reg, started = registered_at(), session_started(tp)
    pre = bool(reg and started and started < reg)                # 4) 등록 전 시작 세션은 막지 않는다
    try:
        ev = latest_event(tp, cfg, gate)                         # 5)
    except Undecidable as e:
        if pre:
            warn_pre_registration(sid, tool, f"판정 불가({e})")
            return
        raise
    clear_marker(sid)
    if ev[0] == "grant":
        return
    if pre:                                                      # 확정 없이 바꾸는 호출만 기록한다(확정이 살아 있으면 남기지 않는다)
        warn_pre_registration(sid, tool, f"확정 없이 바꾸는 호출({ev[1]})")
        return
    deny(no_grant_message(tool, ev[1], cfg))


def undecidable(inp: dict, why: str) -> None:
    """6) Block as undecidable unless a wrong-block marker opens the hook's own files."""
    try:
        if marker_allows(inp):
            return
    except Exception:  # noqa: BLE001, S110  표시 확인 중 오류는 통과가 아니라 아래 차단으로 간다
        pass
    deny(undecidable_message(str(inp.get("tool_name") or "?"), why))


def main() -> None:
    """Read the hook input (bytes → UTF-8) and judge; any failure becomes an undecidable block (never a silent pass)."""
    try:
        inp = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    except ValueError:
        inp = None
    if not isinstance(inp, dict):
        deny(undecidable_message("?", "훅 입력을 해석할 수 없습니다"))
    try:
        judge(inp)
    except Undecidable as e:
        undecidable(inp, str(e))
    except Exception as e:  # noqa: BLE001  예외로 죽으면 훅이 비차단 오류가 되어 호출이 그대로 나간다 — 판정 불가로 막는다
        undecidable(inp, f"훅 내부 오류 {type(e).__name__}: {e}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001  마지막 안전망: 어떤 예외든 차단으로 떨어뜨린다(deny 의 SystemExit 는 여기 잡히지 않는다)
        deny(f"{TAG} 판정하지 못해 막았습니다(훅 내부 오류 {type(e).__name__}). 사용자에게 잘못된 막힘인지 물으십시오.")
