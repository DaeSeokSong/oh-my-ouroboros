"""qa ML 실험 사전 체크(§6) 기계 판정 검사기 — 로그·종료 코드·설정 파일로 가릴 수 있는 항목만 판정한다.

■ 사용
  uv run python3 ~/.claude/scripts/ml_precheck.py --log run.log [--log b.log] [--exit-code N] [--config .venv/pyvenv.cfg]
  `--log` 는 필수다(로그 없는 사전 체크는 뜻이 없다). 출력: 점검표 순서대로 `항목 | PASS/FAIL/SKIP | 근거(파일:줄: 발췌 80자, 시크릿 꼴은 ***)` 한 줄씩, 마지막 줄 `RESULT: PASS|FAIL`.
  종료 코드: 0(FAIL 0건) / 1(FAIL 1건 이상) / 2(인자 오류·파일 없음·로그 50MB 초과). 읽기 전용, 표준 라이브러리만.
  `--config` 는 현재 `.venv/pyvenv.cfg` 판정(점검표 마지막 항목)에만 쓰인다.

■ 판정 원칙
오탐을 줄이는 쪽이다. 지표 이름(`nan_count`)·경로(`/data/nan/`)·단어(`INFO`, `inference`)는 값이 아니므로 맞추지 않는다.
SKIP 은 FAIL 이 아니다(RESULT 는 FAIL 0건이면 PASS). 근거 줄은 qa 가 읽고 오탐이면 사유와 함께 뒤집는다.
REF: knowledge/harness/code-history/scripts__ml_precheck.py.md
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
MAX_EVIDENCE = 3
MAX_LOG_BYTES = 50 * 1024 * 1024
UV_PYTHON_MARK = "/.local/share/uv/python/"


class Inputs(NamedTuple):
    logs: list[tuple[str, list[tuple[int, str]]]]
    exit_code: int | None
    config: tuple[str, str] | None


TRACEBACK = re.compile(r"\bTraceback \(most recent call last\):")
ERROR_LINE = re.compile(
    r"(?<![\w.])(?:[A-Za-z_]\w*\.)*[A-Z]\w*(?:Error|Exception)\b:|^\s*(?:\[[^\]]*\]:?\s*)?(?:Error|Exception):"
)
LEVEL_ERROR = re.compile(r"\[ERROR\]|(?:^|\s)ERROR(?::| -|\s*\|)")
FATAL_WORDS = re.compile(r"Segmentation fault|core dumped|CUDA out of memory|\b(?:FATAL|CRITICAL)\b")
HYDRA_ERROR = re.compile(r"Could not override|Error merging override|is not in struct|ConfigKeyError|ConfigAttributeError")
NAN_INF = re.compile(r"(?<![\w/\\.-])[+-]?(?:nan|inf(?:inity)?)(?![\w/\\]|\.[A-Za-z_]|-\w)", re.IGNORECASE)
SECRET = re.compile(r"(?i)\b(Bearer\s+|\w*(?:token|key|password)\s*=\s*)\S+|\bsk-[\w-]{6,}")
SILENT_SKIP = [
    re.compile(r"(?<![\d.])0 batches\b"),
    re.compile(r"\bEpoch\s+\d+:\s*0it\b", re.IGNORECASE),
    re.compile(r"LR scheduler is empty", re.IGNORECASE),
]
EXIT_LINE = re.compile(r"^exit:(\d+)$")


def mask_secrets(text: str) -> str:
    return SECRET.sub(lambda m: (m.group(1) or "") + "***", text)


def excerpt(seg: str, pos: int) -> str:
    start = max(0, len(mask_secrets(seg[:pos])) - 30)
    return mask_secrets(seg)[start:start + 80].strip()


def scan(inp: Inputs, patterns: list[re.Pattern[str]]) -> tuple[list[str], int]:
    hits: list[str] = []
    for name, lines in inp.logs:
        for lineno, seg in lines:
            for pat in patterns:
                m = pat.search(seg)
                if m:
                    hits.append(f"{name}:{lineno}: {excerpt(seg, m.start())}")
                    break
    return hits, sum(len(lines) for _, lines in inp.logs)


def verdict(hits: list[str], nlines: int, clean: str) -> tuple[str, str]:
    if hits:
        more = f" 외 {len(hits) - MAX_EVIDENCE}건" if len(hits) > MAX_EVIDENCE else ""
        return "FAIL", " ; ".join(hits[:MAX_EVIDENCE]) + more
    return "PASS", f"{clean}({nlines}줄 검사)"


def check_dry_run(inp: Inputs) -> tuple[str, str]:
    empty = [name for name, lines in inp.logs if not any(seg.strip() for _, seg in lines)]
    hits, n = scan(inp, [TRACEBACK, ERROR_LINE, LEVEL_ERROR, FATAL_WORDS])
    if empty:
        return "FAIL", "빈 로그: " + ", ".join(empty) + (" ; " + " ; ".join(hits[:MAX_EVIDENCE]) if hits else "")
    return verdict(hits, n, "Traceback·오류 수준·치명 오류 줄 없음")


def check_hydra(inp: Inputs) -> tuple[str, str]:
    hits, _ = scan(inp, [HYDRA_ERROR])
    if hits:
        return verdict(hits, 0, "")
    return "SKIP", "기계 판정 불가: Hydra 오류 줄은 없으나 변경된 키 목록(diff)과 override 대조는 기계가 못 함"


def check_nan_inf(inp: Inputs) -> tuple[str, str]:
    hits, n = scan(inp, [NAN_INF])
    return verdict(hits, n, "NaN/Inf 값 없음")


def check_exit_code(inp: Inputs) -> tuple[str, str]:
    found: list[tuple[int, str]] = []
    if inp.exit_code is not None:
        found.append((inp.exit_code, f"--exit-code {inp.exit_code}"))
    for name, lines in inp.logs:
        for lineno, seg in lines:
            m = EXIT_LINE.match(seg.strip())
            if m:
                found.append((int(m.group(1)), f"{name}:{lineno}: {seg.strip()}"))
    if not found:
        return "SKIP", "기계 판정 불가: --exit-code 도 로그의 `exit:N` 줄도 없음"
    bad = [text for code, text in found if code != 0]
    if bad:
        return "FAIL", " ; ".join(bad[:MAX_EVIDENCE])
    return "PASS", " ; ".join(text for _, text in found[:MAX_EVIDENCE]) + " (전부 0)"


def check_silent_skip(inp: Inputs) -> tuple[str, str]:
    hits, n = scan(inp, SILENT_SKIP)
    return verdict(hits, n, "`0 batches`·`Epoch N: 0it`·`LR scheduler is empty` 없음")


def check_pyvenv(inp: Inputs) -> tuple[str, str]:
    if inp.config is None:
        return "SKIP", "기계 판정 불가: --config 미제공(.venv/pyvenv.cfg 경로를 넘기면 판정)"
    name, text = inp.config
    for lineno, line in enumerate(text.split("\n"), 1):
        m = re.match(r"\s*home\s*=\s*(.+?)\s*$", line)
        if m:
            home = m.group(1)
            ok = UV_PYTHON_MARK in home
            return ("PASS" if ok else "FAIL"), f"{name}:{lineno}: {excerpt(line, 0)} (uv 관리 경로 {'안' if ok else '밖'})"
    return "SKIP", f"기계 판정 불가: {name} 에 `home =` 줄이 없음(pyvenv.cfg 가 아닐 수 있음)"


Check = Callable[[Inputs], tuple[str, str]]

# REF: rules-lazy/qa-process.md §6 (행 순서가 점검표 순서와 같다)
# NEVER: 점검표 항목이 바뀌었는데 이 표를 그대로 두지 않는다.
CHECKLIST: list[tuple[str, Check | None, str]] = [
    ("dry-run 통과 여부", check_dry_run, ""),
    ("Hydra config 키-override 일치", check_hydra, ""),
    ("파라미터 수 확인(torchinfo·thop)", None, "코드 변경 내용과 기대 수치 대조가 필요해 로그만으로 판정 불가"),
    ("DeepSpeed·LoRA 예상 메모리 대 GPU 용량", None, "설정 변경 여부와 예상 메모리 계산이 필요해 판정 불가"),
    ("checkpoint 경로 충돌 없음", None, "기존 실험 산출물 목록(파일시스템 상태)이 필요해 로그·설정만으로 판정 불가"),
    ("재현성 체크리스트(seed·환경 기록)", None, "정본이 /experiment 스킬이고 환경 기록의 충분성은 사람이 판단"),
    ("NaN/Inf loss 강제 감지", check_nan_inf, ""),
    ("exit code 강제 체크", check_exit_code, ""),
    ("silent skip 감지", check_silent_skip, ""),
    ("pyvenv.cfg home 이 uv 관리 파이썬", check_pyvenv, ""),
]


def load_log(path: str) -> tuple[str, list[tuple[int, str]]]:
    size = Path(path).stat().st_size
    if size > MAX_LOG_BYTES:
        raise OSError(f"너무 큰 로그: {path} ({size} bytes > {MAX_LOG_BYTES}). 끝부분을 잘라 넘기라")
    text = Path(path).read_bytes().decode("utf-8", errors="replace")  # NEVER: text mode 로 읽지 않는다(CR 이 LF 로 바뀌어 줄 번호가 밀린다)
    lines = [(i, ANSI.sub("", seg)) for i, raw in enumerate(text.split("\n"), 1) for seg in raw.split("\r")]
    return Path(path).name, lines


def run(inp: Inputs) -> tuple[list[str], int]:
    out: list[str] = []
    fails = 0
    for name, fn, reason in CHECKLIST:
        status, evidence = fn(inp) if fn else ("SKIP", f"기계 판정 불가: {reason}")
        fails += status == "FAIL"
        out.append(f"{name} | {status} | {evidence}")
    out.append("RESULT: FAIL" if fails else "RESULT: PASS")
    return out, 1 if fails else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="qa ML 사전 체크(§6) 기계 판정")
    ap.add_argument("--log", action="append", required=True, help="학습/dry-run 로그 파일(필수, 여러 번 가능)")
    ap.add_argument("--exit-code", type=int, default=None, help="dry-run 종료 코드")
    ap.add_argument("--config", default=None, help=".venv/pyvenv.cfg 등 설정 파일")
    args = ap.parse_args(argv)
    try:
        logs = [load_log(p) for p in args.log]
        config = (Path(args.config).name, Path(args.config).read_text(encoding="utf-8", errors="replace")) if args.config else None
    except OSError as e:
        print(f"입력 파일을 읽을 수 없습니다: {e}", file=sys.stderr)
        return 2
    lines, code = run(Inputs(logs, args.exit_code, config))
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
