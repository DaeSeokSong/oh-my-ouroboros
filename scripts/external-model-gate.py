"""external-model-gate.py — 외부 모델(Grok·Codex) 호출 직전 PreToolUse(Bash) 게이트

■ 왜 훅인가 (판단 근거 이식 — 2026-09-02)
  모델·effort 게이트는 2026-07-10(Codex)·08-19(Grok)에 규칙으로 서 있었고 09-02에 «이번 요청문의 글자»
  기준으로 문구를 강화했는데도 같은 날 앞선 답을 세션 재사용으로 간주해 두 건을 묻지 않고 보냈다.
  korean-style-gate.sh 와 같은 결론이다. "매번 기억해서 지킨다"는 방식이 원인이므로 판정을 기억에서
  게이트로 옮긴다. 사용자 결정(2026-09-02): «재발 안 되도록 조치».

■ 판정 (둘 다 통과해야 허용)
  1) 모델·effort 명시: 이 세션 **main transcript** 의 마지막 실제 사용자 메시지(도구 결과·시스템 주입 제외)에
     명령의 모델 문자열과 effort 단어가 글자 그대로 들어 있어야 한다. subagent 가 호출해도 subagent 의
     spawn prompt(main 이 쓴 글)가 아니라 사용자 메시지를 본다 — 그래서 transcript_path 가 sidechain 이면
     session_id 로 main transcript 를 찾는다.
     **클릭 답 인정(2026-09-03 사용자 지시: «채팅을 치지 말고 선택지로 띄워서 클릭하면 바로 진행»)**: 마지막 사용자 메시지에
     글자가 없으면 그 메시지 **뒤에** 온 AskUserQuestion 답(user 항목의 tool_result, tool_use_id 가 assistant 의
     AskUserQuestion tool_use 이고 toolUseResult.questions 가 있는 것)의 답 문자열에서 같은 검사를 한다. Bash 등
     다른 도구 결과에 같은 문장이 찍혀도 id 가 다르므로 불인정. 앞선 메시지의 답은 이번 요청에 안 쓴다(매회 질문 유지).
     **결정 팝업 답 인정(2026-10-21 사용자 결정)**: 같은 구간의 결정 팝업 확정 메시지(origin=plugin·decision-popup)도 클릭 답으로
     친다. 각 줄의 답 부분만 본다(popup_answers 의 docstring).
     크로스 세션 피어 메시지(<cross-session-message>)는 user 항목으로 기록되지만 사용자 글자가 아니다 — 제외(2026-09-03 실측).
  2) 전송 전 검사: external_send_preflight.py 를 도구가 닿는 트리(Grok=교환 디렉터리, Codex=-C 인자 또는 cwd)에
     실행해 차단 0건(exit 0).

■ 대상 명령
  · tools/grok-exchange/grok-ask.sh   (--model 기본 grok-4.7, --effort 기본 xhigh — 생략해도 기본값이 사용자 글자에 있어야 한다)
  · codex exec …                       (-m/--model, -c model_reasoning_effort=…)
  · codex-companion.mjs task …         (--model, --effort — /codex:rescue 플러그인 경로)
  대상이 아니면 즉시 통과(출력 없음). 해석 불가(jq·json 오류·transcript 없음)는 fail-closed.

■ fail-closed 근거 (2026-09-06 보강)
  판정 도중 예상 못 한 예외가 나면 훅이 비정상 종료하고, 그 경우 도구 호출은 차단 없이 그대로 진행된다.
  즉 «해석 불가는 fail-closed» 라는 위 문장이 예외 경로에서는 거짓이었다. 그래서 진입점을 try/except 로
  감싸 어떤 예외든 deny 로 떨어뜨린다. preflight 하위 프로세스는 전체 마감(DEADLINE_S=50초)을 공유한다(2026-10-01: 루트마다 45초씩이면 합계가 훅 timeout 을 넘었다).
  settings.json 의 훅 timeout 이 60초라, 그 안에 끝나지 않으면 훅 자체가 잘려 같은 무차단 통과가 된다.

■ 래퍼 추적 (2026-09-06 추가)
  xhigh 호출은 Bash 10분 한도 때문에 `setsid bash 래퍼.sh &` 로 백그라운드 기동하는 관행이 정착돼 있다.
  명령 위치 토큰이 위 대상이 아니고 실재하는 셸 래퍼 파일(.sh 확장자 또는 #! 셔뱅, 256KB 이하)이면
  그 파일의 주석 아닌 각 논리행을 1단계만 재분류한다. 줄 끝 백슬래시 연속행은 한 논리행으로 합친 뒤 본다
  (2026-09-06 실측: 합치지 않으면 shlex 가 `No escaped character` 로 죽고 폴백 토큰의 따옴표 때문에 분류가 통째로 샜다).

■ 2026-09-08 security 재현분 보강 (재현 3건 + 오탐 1건)
  · 접두 명령의 옵션: `bash -e 래퍼.sh`·`nohup setsid bash -x …` 는 접두 제거 루프가 `-e` 에서 멈춰 분류가 샜다.
    이제 접두를 걷어낸 뒤 `-` 로 시작하는 토큰을 건너뛴다.
  · 한 명령의 여러 호출: 첫 일치에서 판정을 끝내 둘째 grok 호출이 무검사로 나갔다. classify_all 로 전부 본다.
  · 같은 옵션 중복(`-m a -m b`): 실제로 쓰이는 값은 뒤 값인데 앞 값만 읽었다. 정당한 용법이 없으므로 차단한다.
  · 오탐 교정: `scripts/gen_gptimg.sh` 는 게이트 예외다(rules-lazy/codex-model-gate.md §3). 래퍼 안의 `codex exec` 줄
    때문에 모델 없는 호출로 분류돼 차단됐다. 비용은 designer 승인 게이트가 따로 막는다.

  ■ 막지 못하는 것 (알려진 한계 — 이 목록 자체가 규약이다)
    · 래퍼 속 래퍼(깊이 2 이상). 셸 래퍼 1단계만 따라간다.
    · 파이썬·노드 등 다른 언어로 쓴 래퍼. 셸 스크립트만 읽는다.
    · `bash -c "…"` 처럼 인용 문자열 안에 넣어 실행하는 경우.
    · `eval`·`source` 로 조립·주입해 실행하는 경우.
    · 접두 제거 목록 밖의 명령을 앞에 세우는 경우(목록: bash·sh·nohup·time·env·exec·setsid·nice·timeout·stdbuf·ionice·taskset·command·sudo·doas — basename 비교, 소괄호·중괄호 묶음은 벗김, 접두 뒤 옵션 값은 첫 codex·grok-ask.sh·node 토큰부터 다시 본다).
    · 변수로 조립한 명령 이름(`C=grok-ask.sh; bash "$C"` 처럼 실행 시점에야 이름이 정해지는 것).
    · 상대 경로로 적힌 래퍼. 적힌 그대로 파일을 열기 때문에 훅의 실행 디렉터리가 다르면 못 연다.
  이 게이트는 «매번 기억해서 지킨다» 대신 서는 1차 방어선이지 우회 불가 통제가 아니다.
  우회 의도가 있으면 뚫리며, 뚫리는 경로를 위에 적어 두는 것이 목적이다.

■ 우회 금지
  명령에 주석으로 모델을 적거나 spawn prompt 에 넣는 것은 명시가 아니다. 통과 조건은 오직 사용자 메시지 원문이다.
  «지난번처럼»·«늘 쓰던 걸로»·compact 요약의 «게이트 답 재사용» 은 전부 불일치로 판정한다.
  정본 규칙: rules-lazy/codex-model-gate.md · skills/grok/SKILL.md Step 1.5
  2026-10-17 보강(Codex 반례): `codex exec -C` 는 절대 경로만(상대·~·$HOME 은 훅이 풀지 않아 사전검사 트리와 실제 루트가 어긋난다),
  `codex exec` 의 프롬프트 본문도 고신뢰 비밀값 패턴(sk-·AKIA·xox[bp]-·ntfy.sh/·개인키)으로 검사한다. 본문 검사는 명령문의 리터럴만 본다:
  `$(cat …)`·변수·stdin·분할 문자열·codex 플러그인 경유 프롬프트·래퍼 파일 속 호출은 못 본다.
  회귀 테스트: python3 ~/.claude/scripts/tests/test_external_model_gate.py (자체 완결) — 이 파일을 고치면 먼저 돌린다.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
PREFLIGHT = HOME / ".claude/scripts/external_send_preflight.py"
EXCHANGE = HOME / "grok-exchange"
EFFORTS = ("xhigh", "high", "medium", "low", "max", "minimal")
DEADLINE_S = 50.0   # settings.json 훅 timeout(60초)보다 짧게 — 사전검사 전체가 공유하는 마감


def deny(reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                             "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}, ensure_ascii=False))
    sys.exit(0)


PREFIX_CMDS = ("bash", "sh", "nohup", "time", "env", "exec", "setsid", "nice",
               "timeout", "stdbuf", "ionice", "taskset", "command", "sudo", "doas", "xargs", "flock")
# 접두를 걷어낸 뒤 값이 따로 오는 옵션(`env -u X codex …`)이 남겼을 수 있는 잡 토큰을 건너뛸 때 «여기서부터 호출»이라 볼 이름들(basename 비교).
LAUNCHERS = ("codex", "grok-ask.sh", "node")
DURATION_RX = re.compile(r"^\d+(?:\.\d+)?[smhd]?$")   # timeout 900 / timeout 15m 의 시간 인자


def _logical_lines(text: str):
    """줄 끝 백슬래시로 이어지는 연속행을 한 논리행으로 합쳐 돌려준다.

    합치지 않으면 `--effort xhigh \\` 로 끝나는 줄에서 shlex 가 ValueError 를 내고, 폴백 토큰에
    따옴표가 남아 분류가 실패한다(2026-09-06 실측 — run_grok_r1.sh). 주석 줄(#)은 셸과 같이
    연속행으로 잇지 않는다. 주석이 뒤 실행 줄을 삼켜 감추는 것을 막는다.
    """
    buf = ""
    for line in text.splitlines():
        buf += line
        if buf.endswith("\\") and not buf.lstrip().startswith("#"):
            buf = buf[:-1] + " "
            continue
        yield buf
        buf = ""
    if buf:
        yield buf


def _segments(cmd: str):
    """;·&&·||·|·&·개행으로 나눈 단순 명령마다 토큰 목록을 돌려준다. 앞의 VAR=값과 PREFIX_CMDS 접두는 걷어낸다."""
    # 단일 `&`(백그라운드)도 구분자다(2026-10-02 I: `sleep 1 & codex exec …` 의 codex 가 sleep 의 인자로 묻혔다). `2>&1`·`&>`·`|&` 의 `&` 는 구분자가 아니다.
    # 따옴표 안의 `|` 도 구분자로 자르는 기존 동작은 그대로다: `grep "a|codex exec" f` 가 전송으로 오분류되는 닫힘 방향 오탐을 알고 둔다.
    for seg in re.split(r"\s*(?:&&|\|\||\|&|;|\||(?<![>&])&(?![>&])|\n)\s*", "\n".join(_logical_lines(cmd))):
        # 2026-10-01 P6 보안 재검수 H: `(codex exec …)`·`{ codex exec …; }`·`$(codex exec …)` 의 묶음 기호가 head 를 가려 분류가 샜다 — 양끝 묶음 기호를 벗긴다.
        seg = re.sub(r"[\s)}`]+$", "", re.sub(r"^(?:[\s({`]|\$\()+", "", seg.strip()))
        if not seg:
            continue
        try:
            toks = shlex.split(seg, posix=True)
        except ValueError:
            # 따옴표·이스케이프가 깨진 조각. 최소한 토큰의 양끝 따옴표는 벗겨야 basename 비교가 산다.
            toks = [t.strip("\"'") for t in seg.split()]
        stripped = False
        while toks:
            # 실행 파일은 basename 으로 비교한다(`/usr/bin/env`·`/usr/bin/sudo` — 2026-10-01 P6 보안 재검수 H)
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[0]) or os.path.basename(toks[0]) in PREFIX_CMDS:
                toks.pop(0)
                stripped = True
                continue
            if stripped and DURATION_RX.match(toks[0]):   # `timeout 900 bash …` 의 900
                toks.pop(0)
                continue
            # 접두 명령의 옵션 (`bash -e 래퍼.sh`·`nohup setsid bash -x 래퍼.sh`).
            # 2026-09-08 security 재현: 옵션에서 루프가 멈춰 head 가 `-e` 가 되는 바람에 분류가 통째로 샜다.
            # `-` 로 시작하는 토큰만 건너뛴다. 값이 따로 오는 옵션(`env -u VAR cmd`)의 값을 옵션으로 오해하지 않기 위해서다.
            if stripped and toks[0].startswith("-"):
                toks.pop(0)
                continue
            break
        if toks:
            yield toks
            # 접두를 걷은 뒤에도 head 가 호출 이름이 아니면(`env -u X codex exec` 의 X 같은 옵션 값) 첫 호출 이름 토큰부터 한 번 더 낸다.
            # 판정이 애매하면 전송으로 본다(D3) — 그래서 원래 목록도 위에서 그대로 냈다(래퍼 파일 head 판정 보존).
            if stripped and os.path.basename(toks[0]) not in LAUNCHERS:
                for i, t in enumerate(toks):
                    if os.path.basename(t) in LAUNCHERS:
                        yield toks[i:]
                        break


PLUGIN_SEND_SUBCMDS = ("task", "review", "adversarial-review", "transfer")   # codex-companion 의 외부 전송 서브명령


class DuplicateFlag(Exception):
    """같은 옵션이 두 번 이상 쓰였다는 신호.

    2026-09-08 security 재현: `-m a -m b` 처럼 두 번 적으면 실제로는 뒤 값이 쓰이는데 종전 판정은 앞 값만 읽었다.
    사용자 메시지에 앞 값만 적어 두고 뒤에 다른 모델을 붙이면 게이트가 열린다. 정당한 용법이 없으므로 차단한다.
    """


# codex 가 값 토큰을 따로 받는 옵션(전역·exec 공통). 목록 밖 옵션은 값 없는 플래그로 본다.
CODEX_VALUE_OPTS = frozenset((
    "-c", "--config", "-m", "--model", "-C", "--cd", "-s", "--sandbox", "-p", "--profile", "-i", "--image",
    "-a", "--ask-for-approval", "--add-dir", "--color", "--output-schema", "-o", "--output-last-message",
    "--local-provider", "--enable", "--disable"))


def _codex_split(toks):
    """codex 토큰을 (옵션 토큰과 그 값 목록, 위치 인자 목록) 으로 나눈다."""
    opts, positionals, i = [], [], 1
    while i < len(toks):
        t = toks[i]
        if t.startswith("-"):
            opts.append(t)
            if "=" not in t and t in CODEX_VALUE_OPTS and i + 1 < len(toks):
                i += 1
                opts.append(toks[i])
        else:
            positionals.append(t)
        i += 1
    return opts, positionals


def _codex_exec_options(toks):
    """`codex [전역 옵션…] exec|e [옵션…] [프롬프트]` 이면 옵션 토큰과 그 값만 모은 목록을, 아니면 None 을 돌려준다.

    첫 위치 인자(positional)가 하위명령이다. 위치 인자(하위명령·프롬프트·resume 세션)는 목록에서 뺀다."""
    opts, positionals = _codex_split(toks)
    # 2026-10-01 P6 보안 재검수 H: 값을 받는 줄 모르는 전역 옵션(`codex --foo bar exec`)의 값이 첫 위치 인자가 돼 exec 를 가렸다.
    # 위치 인자 어디든 exec·e 가 있으면 exec 로 본다 — 판정 불능은 전송(D3).
    if any(p in ("exec", "e") for p in positionals):
        return [toks[0]] + opts
    return None


# codex `-c`/`--config` 허용 키 (2026-10-17 검수팀): 모델 선택·읽기 성격 키와 «MCP 끄기»·«읽기 전용 샌드박스» 만 연다. 임의 키(mcp_servers.*.command 로 서버 실행,
# shell_environment_policy.* 로 환경 노출, sandbox_workspace_write.* 로 쓰기 범위 확장 등)는 -s read-only 와 MCP 끄기를 무력화하므로 목록 밖은 전부 거부한다. (키 정규식, 값 정규식 또는 None=아무 값)
CODEX_CONFIG_OK = (
    (r"model_reasoning_effort|model_reasoning_summary|model_verbosity|model_provider|model", None),
    (r"mcp_servers\.[A-Za-z0-9_-]+\.enabled", r"false"),
    (r"sandbox_mode", r"read-only"),
)


def codex_config_violation(cmd: str):
    """codex exec 호출의 `-c`/`--config` 키가 허용 목록 밖이거나 `--add-dir` 가 있으면 사유 문자열, 아니면 None. 래퍼 파일 속 호출은 보지 못한다."""
    for toks in _segments(cmd):
        if os.path.basename(toks[0]) != "codex":
            continue
        opts, pos = _codex_split(toks)
        if not any(p in ("exec", "e") for p in pos):
            continue
        for i, t in enumerate(opts):
            if t == "--add-dir" or t.startswith("--add-dir="):
                return "--add-dir 은 읽기·쓰기 범위를 -C 밖으로 넓힌다"
            if t in ("-c", "--config") and i + 1 < len(opts):
                kv = opts[i + 1]
            elif t.startswith("--config="):
                kv = t[len("--config="):]
            elif t.startswith("-c") and not t.startswith("--") and len(t) > 2:   # `-ckey=value`, `-c=key=value`
                kv = t[2:].lstrip("=")
            else:
                continue
            key, _, val = kv.partition("=")
            key, val = key.strip(), val.strip().strip("\"'").strip()
            if not any(re.fullmatch(k, key) and (v is None or re.fullmatch(v, val)) for k, v in CODEX_CONFIG_OK):
                return f"-c/--config 키 «{key[:60]}» 는 허용 목록 밖이다"
    return None


# 샌드박스·승인 해제 (정규식 목록, 하나라도 맞으면 deny): 위험 일괄 우회 플래그(약어 접두 포함) · 승인 `never` · sandbox_mode 가 read-only 가 아닌 설정 · approval_policy=never.
SANDBOX_BYPASS = (
    r"--dangerously[a-z-]*|--yolo|--full-?auto",
    r"(?:^|\s)(?:-a|--ask[a-z-]*)(?:\s+|=)never\b",
    r"approval_policy\s*=\s*\W*never",
    r"sandbox_mode\s*=\s*\W*(?!read-only)[a-z]",
)

PROMPT_SECRET_PATTERNS = (
    ("sk- 키", r"sk-[A-Za-z0-9]{20,}"),
    ("Anthropic 키", r"sk-ant-[A-Za-z0-9_-]{20,}"),
    ("OpenAI 프로젝트 키", r"sk-proj-[A-Za-z0-9_-]{20,}"),
    ("GitHub 토큰", r"ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{20,}"),
    ("AWS 키", r"AKIA[0-9A-Z]{16}"),
    ("Slack 토큰", r"xox[bp]-[A-Za-z0-9-]{8,}"),
    ("ntfy 주제", r"ntfy\.sh/[A-Za-z0-9_-]{8,}"),
    ("개인키", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


def prompt_secret_names(prompts):
    """프롬프트 본문에서 고신뢰 비밀값 패턴에 걸린 이름 목록(값은 돌려주지 않는다).

    2026-10-17: 트리만 검사하고 본문은 안 보던 구멍(Codex 반례). Grok 쪽 grok-ask.sh 는 본문을 이미 검사한다.
    preflight 의 일반 `token:` 대입 패턴은 쓰지 않는다 — 프롬프트는 설명문이라 `token: validation_logic` 같은 문장이 오탐된다(security 재검수)."""
    blob = "\n".join(prompts)
    return [name for name, rx in PROMPT_SECRET_PATTERNS if re.search(rx, blob)]


def _classify_tokens(toks):
    """토큰 목록 하나가 명령 위치에 외부 모델 호출이면 (kind, model, effort, reach_dir, sandbox_ok), 아니면 None."""

    def val(flag_names, default=None):
        found = []
        for i, t in enumerate(toks):
            for f in flag_names:
                if t == f and i + 1 < len(toks):
                    found.append(toks[i + 1])
                elif t.startswith(f + "="):
                    found.append(t.split("=", 1)[1])
        if len(found) > 1:
            raise DuplicateFlag("/".join(flag_names))
        return found[0] if found else default

    head = os.path.basename(toks[0])
    if head == "grok-ask.sh":
        return ("grok", val(["--model"], "grok-4.7"), val(["--effort"], "xhigh"), str(EXCHANGE), True)
    opts = _codex_exec_options(toks) if head == "codex" else None
    if opts is not None:
        # 2026-10-01 P6 검수: `codex -C /x exec hi`·`codex --cd /x -m m exec hi`·별칭 `e` 처럼 전역 옵션이 앞서도 exec 이다.
        # 옵션과 그 값만 모은 목록(opts)을 읽으므로 프롬프트·하위명령 토큰은 -m·-c·-s 값으로 오인되지 않는다.
        toks = opts
        # 2026-10-01 감사: 모든 토큰을 훑으면 프롬프트 속 `model_reasoning_effort="high"` 같은 글이 effort 를 덮는다.
        # 옵션 위치의 값(`-c`·`--config` 바로 다음 토큰, `--config=` 뒤)만 인정한다.
        eff = None
        for i, t in enumerate(toks):
            if t in ("-c", "--config") and i + 1 < len(toks):
                cand = toks[i + 1]
            elif t.startswith("--config="):
                cand = t.split("=", 1)[1]
            else:
                continue
            m = re.match(r'model_reasoning_effort=["\']?([a-z]+)', cand)
            if m:
                eff = m.group(1)
        # §0: `-s read-only` 없는 호출도 금지다(판정 불능=거부). 값은 main 이 거부 문구에 쓴다.
        return ("codex-exec", val(["-m", "--model"]), eff, val(["-C", "--cd"]),
                val(["-s", "--sandbox"]) == "read-only")
    # 2026-10-01 감사: task 만 보면 /codex:review·adversarial-review·transfer 가 게이트·사전검사 없이 나간다. 전부 전송이다.
    if head == "node" and len(toks) > 2 and os.path.basename(toks[1]) == "codex-companion.mjs" \
            and any(s in toks[2:] for s in PLUGIN_SEND_SUBCMDS):
        return ("codex-plugin", val(["--model"]), val(["--effort"]), None, True)
    return None


MAX_WRAPPER_BYTES = 256 * 1024


# rules-lazy/codex-model-gate.md §3 — designer 비용 게이트가 따로 관장한다.
# 2026-10-01 감사: 파일 «이름»만 보면 아무 폴더의 gen_gptimg.sh 가 게이트·사전검사를 통째로 피한다. 하네스 실경로만 면제.
GATE_EXEMPT_WRAPPERS = (Path(__file__).resolve().parent / "gen_gptimg.sh",)


def _classify_wrapper_file(head_tok):
    """head 토큰이 실재하는 셸 래퍼 파일(.sh 또는 #! 셔뱅, 256KB 이하)이면 주석 아닌 각 논리행을 1단계만
    재분류해 일치 목록을 돌려준다. 파일 속 또 다른 파일은 따라가지 않는다(깊이 1). 대상 아님·읽기 실패는
    조용히 빈 목록.

    게이트 예외(2026-09-08 오탐 실측): `bash scripts/gen_gptimg.sh …` 는 래퍼 안의 `codex exec` 줄 때문에
    모델 없는 codex 호출로 분류돼 차단됐다. 이미지 생성은 chat 모델 선택의 의미가 작아 규칙이 게이트 밖에
    두었고 비용은 designer 승인 게이트가 따로 막는다(rules-lazy/codex-model-gate.md §3)."""
    p = Path(os.path.expanduser(head_tok.strip("\"'")))
    try:
        if p.resolve() in GATE_EXEMPT_WRAPPERS:
            return []
    except OSError:
        pass
    try:
        if not p.is_file() or p.stat().st_size > MAX_WRAPPER_BYTES:
            return []
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = list(_logical_lines(text))       # 줄 끝 백슬래시 연속행을 합친 뒤 본다
    if not (p.suffix == ".sh" or (lines and lines[0].startswith("#!"))):
        return []
    hits = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for toks in _segments(line):
            hit = _classify_tokens(toks)
            if hit:
                hits.append(hit)
    return hits


def classify_all(cmd: str):
    """명령 안의 외부 모델 호출을 전부 모아 [(kind, model, effort, reach_dir), …] 로 돌려준다.

    2026-09-08 security 재현: 한 명령에 grok 호출이 두 번 있으면 첫 일치에서 판정을 끝내는 바람에
    둘째 호출은 아무 검사 없이 나갔다(`… --effort xhigh && … --effort high`). 그래서 전 세그먼트를 본다.
    인자·경로·주석에 grok-ask.sh 가 보이는 것(git add …/grok-ask.sh)은 호출이 아니다 — 2026-09-02 커밋 차단 오탐 후 교정.
    한계는 모듈 docstring 「막지 못하는 것」 목록이 정본이다 — 셸 스크립트 1단계만 따라간다."""
    hits = []
    for toks in _segments(cmd):
        hit = _classify_tokens(toks)
        if hit:
            hits.append(hit)
            continue
        hits.extend(_classify_wrapper_file(toks[0]))
    return hits


def classify(cmd: str):
    """첫 호출 하나만 필요한 자리를 위한 얇은 껍질. 판정 본체는 classify_all 이다."""
    hits = classify_all(cmd)
    return hits[0] if hits else None


ASK_PREFIXES = ("Your questions have been answered:", "The user answered:")   # 옛 문구 + Claude Code 2.1.286 이후 문구 (2026-10-01 실측)
# 사용자 글자가 아닌데 user 역할로 기록되는 본문의 접두 (구조 필드가 없을 때를 위한 보조 검사)
NON_USER_PREFIXES = ("Base directory for this skill:", "[SYSTEM NOTIFICATION", "[Subagent hand-back]",
                     "This session is being continued from a previous conversation",
                     "Another Claude session sent a message",
                     "[Request interrupted by user")   # 인터럽트 안내문(2026-10-01 감사): 사람이 친 글자가 아닌데 직전 선택을 가려 정당한 호출을 막았다


def _is_non_user(d: dict, t: str) -> bool:
    """user 역할로 기록됐지만 사용자가 친 글자가 아닌 항목인지 판정한다.

    왜 제외하는가: 스킬 본문·compact 요약·자동 알림·피어/subagent 전달문은 사용자 글자가 아니다. 이 본문의 모델 이름
    (예: skills/grok/SKILL.md 의 «grok-4.6 … xhigh»)으로 게이트가 열리면 사용자 선택 없이 통과하는 세탁 경로가 되고(2026-10-01
    보안 검수 실측), 반대로 스킬 호출 때문에 «마지막 사용자 메시지»가 스킬 본문으로 바뀌면 그 앞의 진짜 지정을 못 봐 정당한
    호출까지 막힌다. 식별은 기록의 구조 필드(isMeta·isCompactSummary·origin)가 우선이고 본문 접두는 보조다.
    실측 모양: 스킬 주입=isMeta:true / compact 요약=isCompactSummary:true / 자동 알림·피어·subagent 전달=origin 이
    {"kind":"task-notification"} 또는 {"body":…} / 사람이 친 글자=origin 없음 또는 {"kind":"human"} / teammate 전달문은 «<» 로 시작."""
    if d.get("isMeta") or d.get("isCompactSummary"):
        return True
    origin = d.get("origin")
    if origin is not None and not (isinstance(origin, dict) and origin.get("kind") == "human"):
        return True
    return t.startswith(NON_USER_PREFIXES) or "<cross-session-message" in t


POPUP_ORIGIN = {"kind": "plugin", "name": "decision-popup"}
POPUP_MARK = "[결정 팝업 확인]"


def popup_answers(d: dict) -> list[str]:
    """결정 팝업 확정 메시지에서 사용자가 고른 «답» 부분만 꺼낸다(2026-10-21 사용자 결정 팝업 Q1=1 «팝업 답을 인정»).

    왜 이렇게 좁히는가(판단 근거 이식):
    · 출처: 기록 항목의 origin 이 엔진이 붙인 {"kind":"plugin","name":"decision-popup"} 와 정확히 같을 때만 본다. 본문 접두
      «[결정 팝업 확인]» 은 피어 메시지·다른 플러그인·사용자 붙여넣기로도 만들 수 있어 단독 근거가 아니다. 그 플러그인은 사람이
      팝업에서 «이대로 확정»(y)을 눌렀을 때만 이 메시지를 넣는다(mods/decision-popup/hooks/register.tsx). «[결정 팝업 닫힘]» 은 답이 아니다.
    · 답 부분만: 줄 꼴은 «- <id> <제목>: <답>» 이고 제목은 모델이 쓴 글이다. 줄 전체를 보면 제목에 «gpt-6.1-sol high» 를 적고
      사용자가 «아니오» 를 골라도 열린다. 그래서 각 줄의 마지막 «: » 뒤만 답으로 친다. 선택지 이름에 «: » 가 있으면 그 뒤만 읽히는데
      (예: 이름 «아니오: grok-4.6 xhigh»), 그 이름은 사용자가 화면에서 보고 고른 것이라 AskUserQuestion 보기와 같은 수준이다.
      제목 쪽 «: » 는 마지막이 아니므로 답으로 읽히지 않는다. 팝업은 제목·이름의 줄 구분 문자를 « / » 로 바꿔 가짜 «- » 줄을 만들 수 없게 하고,
      여기서도 «\n» 에서만 줄을 나눈다(아래).
    · AskUserQuestion 답과 신뢰 수준이 같다: 둘 다 보기는 모델이 쓰고 고르는 것은 사람이다."""
    if d.get("origin") != POPUP_ORIGIN or d.get("isSidechain") or d.get("isMeta"):
        return []
    c = d.get("message", {}).get("content")
    if isinstance(c, list):
        c = " ".join(x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text")
    if not isinstance(c, str):
        return []
    # 줄은 엔진·팝업이 쓰는 «\n» 에서만 나눈다. splitlines() 는 U+0085·U+001C~001E·U+2028 등에서도 나눠, 모델이 제목에 그 문자를
    # 숨기면 팝업 화면에서는 한 줄인데 여기서는 가짜 «- » 줄이 생긴다(qa 2026-10-21).
    lines = c.split("\n")
    # 엔진 머리말 다음에 처음 나오는 «[결정 팝업 …]» 줄이 «확인» 으로 «시작» 해야 한다. 본문 어딘가에 문구가 있기만 하면 인정하던
    # 처음 판은, 모델이 제목에 «[결정 팝업 확인]» 과 가짜 답 줄을 숨기고 사용자가 닫기만 해도 «[결정 팝업 닫힘] <제목>» 메시지로
    # 열렸다(security 2026-10-21 [상]).
    head = next((i for i, ln in enumerate(lines) if ln.lstrip().startswith("[결정 팝업 ")), None)
    if head is None or not lines[head].lstrip().startswith(POPUP_MARK):
        return []
    out = []
    for line in lines[head + 1:]:
        line = line.strip()
        if line.startswith("- ") and ": " in line:
            out.append(line.rsplit(": ", 1)[1])
    return out


def _entries(path: Path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                yield json.loads(line)
            except Exception:  # noqa: BLE001, S112  손상된 transcript 줄 하나가 전체 판정을 막지 않게 건너뛴다(관용 파싱)
                continue


def last_user_message(path: Path):
    """(마지막 실제 사용자 메시지 본문, 그 뒤에 온 AskUserQuestion 답 문자열들) 을 돌려준다."""
    last, last_idx, entries = None, -1, []
    for i, d in enumerate(_entries(path)):
        entries.append(d)
        if d.get("type") != "user" or d.get("isSidechain"):
            continue
        c = d.get("message", {}).get("content")
        if isinstance(c, str):
            t = c
        elif isinstance(c, list):
            if any(isinstance(x, dict) and x.get("type") == "tool_result" for x in c):
                continue
            t = " ".join(x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text")
        else:
            continue
        t = t.strip()
        # 슬래시 명령은 `<command-name>/x</command-name>…<command-args>사용자가 친 인자</command-args>` 모양으로 기록된다
        # (2026-10-01 감사). 인자는 사용자 글자이므로 그것만 꺼내 쓴다. 인자가 비면 아래에서 건너뛴다.
        if t.startswith("<command-name>"):
            a = re.search(r"<command-args>(.*?)</command-args>", t, re.DOTALL)
            t = a.group(1).strip() if a else ""
        if not t or t.startswith("<"):        # system-reminder·local-command 주입은 사용자 글자가 아니다
            continue
        if _is_non_user(d, t):
            continue                            # 피어 메시지(2026-09-03)·스킬 본문·compact 요약·자동 알림(2026-10-01) 은 사용자 글자가 아니다
        last, last_idx = t, i
    # 마지막 사용자 메시지 뒤의 AskUserQuestion 답만 수집 (assistant tool_use id 로 결박)
    ask_ids = set()
    answers = []
    for d in entries[last_idx + 1:] if last_idx >= 0 else []:
        if d.get("type") == "user":
            answers.extend(popup_answers(d))   # 결정 팝업 확정 답(2026-10-21) — 위 루프에서는 origin=plugin 이라 사용자 글자로 안 셌다
        c = d.get("message", {}).get("content")
        if not isinstance(c, list):
            continue
        if d.get("type") == "assistant":
            for blk in c:
                if isinstance(blk, dict) and blk.get("type") == "tool_use" and blk.get("name") == "AskUserQuestion":
                    ask_ids.add(blk.get("id"))
        elif d.get("type") == "user" and not d.get("isSidechain"):
            tur = d.get("toolUseResult")
            has_q = isinstance(tur, dict) and isinstance(tur.get("questions"), list)
            for blk in c:
                if not (isinstance(blk, dict) and blk.get("type") == "tool_result"):
                    continue
                if blk.get("tool_use_id") not in ask_ids or not has_q:
                    continue
                structured = tur.get("answers")     # 구조화된 답(질문→답 dict)이 있으면 문자열 파싱보다 우선
                if isinstance(structured, dict) and structured and all(isinstance(v, str) for v in structured.values()):
                    answers.extend(structured.values())
                    continue
                content = blk.get("content")
                if isinstance(content, list):
                    content = " ".join(x.get("text", "") for x in content if isinstance(x, dict))
                if isinstance(content, str) and content.startswith(ASK_PREFIXES):
                    answers.extend(m.group(2) for m in re.finditer(r'"((?:[^"\\]|\\.)*)"="((?:[^"\\]|\\.)*)"', content))
    return last, answers


def main_transcript(transcript_path: str, session_id: str) -> Path | None:
    p = Path(transcript_path) if transcript_path else None
    if session_id:
        base = p.parent if p else None
        for _ in range(6):
            if base is None:
                break
            cand = base / f"{session_id}.jsonl"
            if cand.is_file():
                return cand
            base = base.parent
    if p and p.is_file():
        return p
    return None


def main() -> None:
    t0 = time.monotonic()
    try:
        inp = json.load(sys.stdin)
    except Exception:  # noqa: BLE001  어떤 입력 오류든 fail-closed 로 deny 한다
        deny("[외부 모델 게이트] 훅 입력을 해석할 수 없어 fail-closed.")
    if inp.get("tool_name") != "Bash":
        return
    cmd = (inp.get("tool_input") or {}).get("command") or ""
    try:
        hits = classify_all(cmd)
    except DuplicateFlag as e:
        deny(f"[외부 모델 게이트] 같은 옵션이 두 번 이상 있다({e}).\n"
             "  실제로 쓰이는 값은 뒤 값이라 앞 값으로 한 판정을 믿을 수 없다. 옵션을 하나만 남겨 다시 실행하라.")
    if not hits:
        return

    # -C/--cd 값은 분류기가 `;` 등에서 조각낸 뒤 읽으므로(`-C "/clean;private"` → `/clean`) 사전검사 경로와 실제 루트가 어긋날 수 있다.
    # 따옴표 제거 전 원문에서 값을 다시 뽑아 구분자·전개 문자가 하나라도 있으면 경로를 확정할 수 없어 거부한다(2026-10-17 Codex 3차).
    # 조각난 호출이 아래 모델·샌드박스 판정에 먼저 걸리지 않도록 그 앞에서 본다.
    # 4차(Codex): 옵션 이름 자체가 따옴표로 묶이면(`"-C" "/clean;private"`) 원문 정규식이 놓친다 → 이름의 따옴표도 허용하고,
    #   원문과 «따옴표 문자만 뗀 사본» 양쪽에서 값을 뽑아 어느 쪽이든 구분자·전개 문자·공백·따옴표가 있거나 두 쪽 값이 다르면 거부한다.
    if any(h[0] == "codex-exec" for h in hits):
        rx = r"""(?:^|\s)(["']?)(?:-C|--cd)\1(?:\s+|=)("[^"]*"|'[^']*'|\S+)"""
        raw_vals = [m.group(2) for m in re.finditer(rx, cmd)]
        uq_vals = [m.group(2) for m in re.finditer(rx, re.sub(r"""["']""", "", cmd))]
        if any(re.search(r"""[\s;|&$`"']""", v) for v in raw_vals + uq_vals) \
                or sorted(re.sub(r"""["']""", "", v) for v in raw_vals) != sorted(uq_vals):
            deny("[외부 모델 게이트] -C 값에 구분자·전개 문자 — 검사 경로를 확정할 수 없음. 공백·`;|&$`·따옴표 없는 절대 경로만 쓴다"
                 "(rules-lazy/codex-model-gate.md §0).")
        # 2026-10-17 검수팀 보안: `-s read-only` 가 있어도 같은 명령에 샌드박스·승인 해제가 있으면 읽기 전용이 아니다(뒤 설정이 이긴다). 원문·따옴표 제거본 양쪽에서 본다.
        for text in (cmd, re.sub(r"""["']""", "", cmd)):
            if any(re.search(rx_b, text) for rx_b in SANDBOX_BYPASS):
                deny("[외부 모델 게이트] 샌드박스·승인 해제 옵션이 같이 있다(--dangerously-bypass…·--full-auto·-a never·sandbox_mode/approval_policy 설정) — "
                     "`-s read-only` 만 허용한다(rules-lazy/codex-model-gate.md §0).")
        # 17차: -c/--config 는 허용 키 목록으로 제한하고 --add-dir 는 거부한다(위 해제 옵션은 더 구체적인 사유라 먼저 본다).
        bad_cfg = codex_config_violation(cmd)
        if bad_cfg:
            deny(f"[외부 모델 게이트] {bad_cfg}. 허용: model_reasoning_effort 류 모델 키·mcp_servers.<이름>.enabled=false·sandbox_mode=read-only "
                 "(rules-lazy/codex-model-gate.md §0, 상수 CODEX_CONFIG_OK).")

    # 한 명령에 호출이 여러 번이면 전부 검사한다. 하나라도 미기재면 차단이다.
    for kind, model, effort, reach, sandbox_ok in hits:
        if not model or not effort:
            deny(f"[외부 모델 게이트] {kind}: 명령에 모델·effort 가 없다. 사용자에게 보기로 질문한 뒤 답을 명령에 명시하라.")
        # 2026-10-01 감사: `cd X && codex exec …`(-C 없음)는 cd 를 추적하지 않아 훅 cwd 를 검사하게 되고, 실제 codex 루트는
        # 검사하지 않은 트리다. 규칙(rules-lazy/codex-model-gate.md §0)이 -C 없는 호출을 금지하므로 판정 불능=거부(D3).
        if kind == "codex-exec" and not reach:
            deny("[외부 모델 게이트] codex exec 에 -C(--cd) 가 없다. 작업 루트를 못박지 않은 호출은 금지다"
                 "(rules-lazy/codex-model-gate.md §0). `-C <깨끗한 폴더> -s read-only` 를 명시해 다시 실행하라.")
        # 2026-10-17 Codex 반례: 상대 경로 -C 는 codex 가 자기 cwd 기준으로 풀어 훅이 사전검사한 트리와 어긋난다. ~·$HOME 도 훅이 풀지 않는다.
        if kind == "codex-exec" and not reach.startswith("/"):
            deny("[외부 모델 게이트] -C 는 절대 경로만(rules-lazy/codex-model-gate.md §0). 상대 경로·~·$HOME 은 훅이 풀지 않는다.")
        if kind == "codex-exec" and not sandbox_ok:
            deny("[외부 모델 게이트] codex exec 에 `-s read-only`(--sandbox read-only)가 없다. 읽기 전용 샌드박스를 못박지 않은 호출은 금지다"
                 "(rules-lazy/codex-model-gate.md §0 «이 두 플래그를 뺀 호출은 금지»). `-C <깨끗한 폴더> -s read-only` 를 명시해 다시 실행하라.")

    # 2026-10-17 Codex 반례: 트리는 사전검사하지만 프롬프트 본문은 안 봤다. 비밀값 꼴 문자열이 본문에 있으면 막는다.
    # 위치 인자만 뽑지 않고 명령 전체를 훑는다(2026-10-17 Codex 2차): 분류기는 따옴표 안의 `;` 에서도 조각을 내고(`"review; sk-…"`)
    # `--` 뒤 `-` 로 시작하는 프롬프트(`-- "-----BEGIN …"`)를 옵션으로 읽어 위치 인자 추출은 이 둘을 놓쳤다.
    leaked = prompt_secret_names([cmd]) if any(h[0] == "codex-exec" for h in hits) else []
    if leaked:
        deny(f"[외부 모델 게이트] 프롬프트 본문에 비밀값 꼴 문자열({', '.join(leaked)}) — 보내지 않는다. 값을 빼고 다시 실행하라.")

    tp = main_transcript(inp.get("transcript_path", ""), inp.get("session_id", ""))
    if tp is None:
        deny("[외부 모델 게이트] main transcript 를 찾지 못해 fail-closed. (transcript_path/session_id 확인)")
    msg, answers = last_user_message(tp)
    if not msg:
        deny("[외부 모델 게이트] 사용자 메시지를 찾지 못해 fail-closed.")

    def matches(text: str, model: str, effort: str):
        low = text.lower()
        return (model.lower() in low,
                re.search(rf"(?<![a-z]){re.escape(effort.lower())}(?![a-z])", low) is not None)

    for kind, model, effort, _reach, _sb in hits:
        ok_model, ok_effort = matches(msg, model, effort)
        if not (ok_model and ok_effort) and answers:
            ok_model, ok_effort = matches(" ".join(answers), model, effort)
        if not (ok_model and ok_effort):
            head = msg[:120].replace("\n", " ")
            deny("[외부 모델 게이트] 이번 사용자 메시지에도, 그 뒤 AskUserQuestion·결정 팝업 답에도 모델·effort 가 없다 — 재질문 필수(2026-09-02 실사고 재발 방지).\n"
                 f"  명령: {kind} model={model} effort={effort} (한 명령의 호출 {len(hits)}건 중 하나)\n"
                 f"  마지막 사용자 메시지: «{head}…» · 클릭 답: {answers or '없음'}\n"
                 f"  모델 일치={ok_model} · effort 일치={ok_effort}\n"
                 "  같은 세션의 앞선 답·compact 요약·메모리·«지난번처럼»은 명시가 아니다. 결정 팝업(mcp__decision-popup__ask) 또는 AskUserQuestion 으로 모델 보기(grok-4.7/grok-4.6 또는 Codex 모델)와 effort 보기(xhigh/high/medium/low)를 띄워 사용자가 고르게 한 뒤 다시 실행하라(2026-09-03: 타이핑 요구 금지). 팝업은 선택지 이름(label)에 모델·effort 를 적는다(제목만으로는 인정하지 않는다).")

    # 2) 전송 전 검사 — 도구가 닿는 트리 (같은 트리는 한 번만 돌린다)
    if not PREFLIGHT.is_file():
        deny(f"[외부 모델 게이트] preflight 스크립트 없음: {PREFLIGHT}")
    reaches = []
    for _kind, _model, _effort, reach, _sb in hits:
        reach = reach or inp.get("cwd") or os.getcwd()
        if reach not in reaches:
            reaches.append(reach)
    # 전체 마감(DEADLINE_S) 공유 — settings.json 의 훅 timeout 이 60초라, 하위 프로세스가 늘어지면 훅이 통째로 잘려
    # deny 를 내지 못하고 무차단 통과가 된다. 2026-10-01 감사: 루트마다 45초씩 새로 걸면 합계가 60초를 넘는다.
    # 그래서 시작 시각부터 하나의 마감을 두고, 남은 시간만큼만 준다. 마감 안에 못 끝내면 우리가 먼저 deny 한다.
    for reach in reaches:
        left = DEADLINE_S - (time.monotonic() - t0)
        if left < 1:
            deny(f"[외부 모델 게이트] 사전검사 전체 마감({DEADLINE_S:.0f}초)에 도달해 트리 {reach} 를 검사하지 못함 — 안전을 위해 차단.\n"
                 "  검사할 트리가 많거나 크다. -C 로 좁은 폴더를 지정해 다시 실행하라.")
        try:
            r = subprocess.run([sys.executable, str(PREFLIGHT), reach], check=False, capture_output=True, text=True, timeout=left)
        except subprocess.TimeoutExpired:
            deny(f"[외부 모델 게이트] external_send_preflight.py 가 전체 마감({DEADLINE_S:.0f}초) 안에 끝나지 않음 (트리: {reach}) — 안전을 위해 차단.\n"
                 "  트리가 너무 크면 -C 로 좁은 폴더를 지정한 뒤 다시 실행하라.")
        if r.returncode != 0:
            tail = "\n".join((r.stdout + r.stderr).strip().splitlines()[-6:])
            deny(f"[외부 모델 게이트] external_send_preflight.py 차단 (트리: {reach})\n{tail}")


if __name__ == "__main__":
    # 예외로 죽으면 훅이 비차단 오류가 되어 호출이 그대로 나간다 — 어떤 예외든 deny 로 떨어뜨린다.
    # deny() 는 SystemExit(BaseException)을 던지므로 아래 except Exception 에 잡히지 않는다.
    try:
        main()
    except Exception as e:  # noqa: BLE001  어떤 예외든 deny 로 떨어뜨린다(위 주석)
        deny(f"[외부 모델 게이트] 게이트 내부 오류 — 안전을 위해 차단: {type(e).__name__}: {e}\n"
             "  훅 자체의 결함일 수 있다. python3 ~/.claude/scripts/tests/test_external_model_gate.py 로 확인하라.")
