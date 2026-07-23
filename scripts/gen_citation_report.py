#!/usr/bin/env python3
"""citation-verifier 검증 이력 PDF 리포트 생성 (rules-lazy/citation-verification-log.md §5 스펙 구현).

데이터 소스 (병합 — DOI+날짜 중복 시 상세 로그 우선, evidence를 보존하는 쪽이 canonical):
  1. 상세 로그: docs/citation-verifications.md (§1 append 스키마)
     - --log 로 경로 지정(반복 허용), 미지정 시 cwd 기준 ./docs/citation-verifications.md
  2. Mem0 플랫폼 REST: T21 요약(source=citation-verifier) 검색 후 key=value 파싱
     - MEM0_API_KEY: env 우선, 없으면 ~/.claude/mcp-secrets.env (MCP 런처와 동일 소스)
     - user_id: env MEM0_DEFAULT_USER_ID, 미설정 시 "mem0-mcp"
       (launch-mem0.sh → mem0-mcp-server 기본값과 동일 규칙 — 어긋나면 0건 조회됨)
  3. 실소스 0건이면 exit 2. 내장 테스트 fixture는 --test-data 명시 시에만 사용.

CSV fallback: --output 인자가 .csv로 끝날 경우 CSV 출력.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

# ---------------------------------------------------------------------------
# 테스트 fixture (citation-verifier verdict 구조 예시)
# --test-data 플래그 명시 시에만 사용 — 실데이터 소스의 silent 대체 금지
# ---------------------------------------------------------------------------
CITATION_VERIFICATIONS = [
    {
        "idx": 1,
        "date": "2026-04-17",
        "invoker": "searcher",
        "project": "claude-global",
        "paper": "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
        "doi": "10.48550/arxiv.1810.04805",
        "verdict": "허용",
        "supporting": 57,
        "contrasting": 10,
        "mentioning": 20581,
        "retracted": False,
        "confidence": "high",
        "fulltext_coverage": True,
        "purpose": "B안 MCP 상속 검증 테스트",
        "actual_use": "NO",
        "status": "rejected",
        "location": "(테스트 호출만, 사용처 없음)",
        "updated_at": "2026-04-17",
        "summary": "MCP 상속 검증 목적 테스트 호출. 실제 프로젝트 사용 없음.",
        "evidence": [
            {
                "stance": "supporting",
                "citing": "Smith et al. 2023",
                "snippet": "BERT outperforms previous models on GLUE benchmark.",
                "url": "https://arxiv.org/abs/2301.00001",
            }
        ],
    },
    {
        "idx": 2,
        "date": "2026-04-17",
        "invoker": "main-opus",
        "project": "claude-global",
        "paper": "Attention Is All You Need In Speech Separation",
        "doi": "10.1109/icassp39728.2021.9413901",
        "verdict": "경고",
        "supporting": 1,
        "contrasting": 0,
        "mentioning": 263,
        "retracted": False,
        "confidence": "med",
        "fulltext_coverage": False,
        "purpose": "citation-verifier 첫 검증 테스트 (titles 부분 매칭)",
        "actual_use": "NO",
        "status": "rejected",
        "location": "(테스트 호출만)",
        "updated_at": "2026-04-17",
        "summary": "제목 부분 매칭으로 반환된 파생 논문. supporting 1건으로 경고. 실제 사용 없음.",
        "evidence": [],
    },
    {
        "idx": 3,
        "date": "2026-04-17",
        "invoker": "main-opus",
        "project": "claude-global",
        "paper": "Attention is all you need for Videos",
        "doi": "10.48550/arxiv.1906.02792",
        "verdict": "경고",
        "supporting": 0,
        "contrasting": 0,
        "mentioning": 4,
        "retracted": False,
        "confidence": "low",
        "fulltext_coverage": False,
        "purpose": "titles 검색 부산물",
        "actual_use": "NO",
        "status": "rejected",
        "location": "(테스트 호출만)",
        "updated_at": "2026-04-17",
        "summary": "제목 부분 매칭으로 반환된 파생 논문. 정보부족으로 경고.",
        "evidence": [],
    },
    {
        "idx": 4,
        "date": "2026-04-17",
        "invoker": "main-opus",
        "project": "claude-global",
        "paper": "Only 5% Attention Is All You Need: Efficient Long-range DocNMT",
        "doi": "10.18653/v1/2023.ijcnlp-main.47",
        "verdict": "경고",
        "supporting": 0,
        "contrasting": 0,
        "mentioning": 0,
        "retracted": False,
        "confidence": "low",
        "fulltext_coverage": False,
        "purpose": "titles 검색 부산물",
        "actual_use": "NO",
        "status": "rejected",
        "location": "(테스트 호출만)",
        "updated_at": "2026-04-17",
        "summary": "tally 필드 생략된 응답. Smart Citations snippet만 반환됨.",
        "evidence": [],
    },
]

KOREAN_CID_FONT = "HYSMyeongJo-Medium"
MCP_SECRETS_ENV = Path("~/.claude/mcp-secrets.env").expanduser()
TAVILY_USAGE_URL = "https://api.tavily.com/usage"
MEM0_SEARCH_URL = "https://api.mem0.ai/v2/memories/search/"
MEM0_USER_ID = os.environ.get("MEM0_DEFAULT_USER_ID", "mem0-mcp")
DEFAULT_LOG_PATH = Path("docs/citation-verifications.md")


def _read_secrets_env() -> dict[str, str]:
    """mcp-secrets.env(KEY=value, 선택적 export 접두·따옴표) 파싱. 파일 없으면 빈 dict."""
    secrets: dict[str, str] = {}
    try:
        for line in MCP_SECRETS_ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.removeprefix("export ").partition("=")
            secrets[key.strip()] = value.strip().strip("'\"")
    except OSError:
        pass
    return secrets


def read_secret_key(name: str) -> str | None:
    """API 키를 env var 우선, 없으면 mcp-secrets.env에서 읽는다 (MCP 런처와 동일 소스).

    settings.json에는 mcpServers 키가 존재하지 않으므로 참조하지 않는다 —
    MCP 서버 정의는 ~/.claude.json, 시크릿은 mcp-secrets.env(600)로 분리 운영.
    """
    return os.environ.get(name) or _read_secrets_env().get(name)


def fetch_tavily_usage(api_key: str) -> dict | None:
    """Tavily /usage 엔드포인트 호출. 실패 시 None."""
    req = urllib.request.Request(
        TAVILY_USAGE_URL,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"[경고] Tavily usage API 호출 실패: {exc}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# 실데이터 로더 — 상세 로그(citation-verification-log.md §1) + Mem0 T21 요약
# ---------------------------------------------------------------------------

LOG_HEADER_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2})\]\s*(.+?)\s*\(([^()]+)\)\s*$")

RECORD_DEFAULTS = {
    "date": "-", "paper": "(제목 미상)", "doi": "-", "verdict": "-",
    "invoker": "-", "project": "-", "purpose": "-",
    "supporting": 0, "contrasting": 0, "mentioning": 0,
    "retracted": False, "confidence": "-", "fulltext_coverage": "-",
    "actual_use": "PENDING", "status": "-", "location": "-",
    "summary": "-", "evidence": [],
}


def load_log_records(log_path: Path) -> list[dict]:
    """docs/citation-verifications.md(§1 append 스키마) 파싱 → 레코드 리스트."""
    if not log_path.is_file():
        return []
    # 프로젝트 라벨: <project>/docs/citation-verifications.md 구조에서 docs의 부모 디렉토리명
    parent = log_path.resolve().parent
    project = parent.parent.name if parent.name == "docs" else parent.name

    records = []
    text = log_path.read_text(encoding="utf-8")
    for block in re.split(r"^## ", text, flags=re.MULTILINE)[1:]:
        lines = block.splitlines()
        if not lines:
            continue
        header = LOG_HEADER_RE.match(lines[0].strip())
        if not header:
            continue
        date, title, doi = header.groups()
        rec = {"date": date, "paper": title, "doi": doi.strip(),
               "project": project, "_source": "log"}

        def bullet(field: str, _block: str = block) -> str | None:
            m = re.search(rf"^-\s*\*\*{re.escape(field)}\*\*:\s*(.+)$", _block, re.MULTILINE)
            return m.group(1).strip() if m else None

        verdict = bullet("verdict")
        rec["verdict"] = verdict.split()[0] if verdict else "-"
        nums = re.findall(r"\d+", bullet("supporting / contrasting / mentioning") or "")[:3]
        rec["supporting"], rec["contrasting"], rec["mentioning"] = (
            [int(n) for n in nums] + [0, 0, 0]
        )[:3]
        rec["retracted"] = (bullet("retracted") or "").lower().startswith("true")
        rec["confidence"] = bullet("confidence") or "-"
        rec["fulltext_coverage"] = bullet("fulltext_coverage") or "-"

        evidence = []
        ev_section = re.search(r"### evidence\n(.*?)(?=\n### |\Z)", block, re.DOTALL)
        if ev_section:
            for row in ev_section.group(1).splitlines():
                row = row.strip()
                if not row.startswith("|"):
                    continue
                cells = [c.strip() for c in row.strip("|").split("|")]
                # 헤더 행("stance"...)과 구분선 행("---")은 제외
                if len(cells) >= 4 and cells[0] != "stance" and not set(cells[0]) <= set("-: "):
                    evidence.append({
                        "stance": cells[0], "citing": cells[1],
                        "snippet": cells[2].strip('"'), "url": cells[3],
                    })
        rec["evidence"] = evidence
        records.append(rec)
    return records


# T21 텍스트 서식(mem0-templates.md): "citation-verifier 검증 YYYY-MM-DD [프로젝트]
# invoker=X: 제목='...' (저자=..., DOI=...). 목적=... verdict=... supporting=N, ..."
T21_FIELD_RE = {
    "verdict": re.compile(r"verdict=([^\s.,;]+)"),
    "supporting": re.compile(r"supporting=(\d+)"),
    "contrasting": re.compile(r"contrasting=(\d+)"),
    "mentioning": re.compile(r"mentioning=(\d+)"),
    "retracted": re.compile(r"retracted=(true|false)", re.IGNORECASE),
    "confidence": re.compile(r"confidence=(high|med|low)", re.IGNORECASE),
    "fulltext_coverage": re.compile(r"fulltext_coverage=([^\s.,;]+)"),
    "actual_use": re.compile(r"actual_use=([^\s.,;]+)"),
    "status": re.compile(r"status=([^\s.,;]+)"),
    "updated_at": re.compile(r"updated_at=(\d{4}-\d{2}-\d{2})"),
    "invoker": re.compile(r"invoker=([^\s:,]+)"),
}


def parse_t21_text(text: str) -> dict | None:
    """Mem0 T21/T25 요약 텍스트(key=value 서식)에서 레코드 필드 추출. verdict 없으면 None."""
    rec: dict = {"_source": "mem0"}
    for field, pattern in T21_FIELD_RE.items():
        m = pattern.search(text)
        if not m:
            continue
        value = m.group(1)
        if field in ("supporting", "contrasting", "mentioning"):
            rec[field] = int(value)
        elif field == "retracted":
            rec[field] = value.lower() == "true"
        else:
            rec[field] = value
    if "verdict" not in rec:
        return None

    m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
    if m:
        rec["date"] = m.group(1)
    m = re.search(r"\d{4}-\d{2}-\d{2}\s+\[([^\]]+)\]", text)
    if m:
        rec["project"] = m.group(1)
    m = re.search(r"제목='([^']+)'", text) or re.search(r"\]:\s*([^(]+?)\s*\(", text)
    if m:
        rec["paper"] = m.group(1).strip()
    m = re.search(r"DOI[:=]\s*'?(10\.[^\s'),;]+)", text)
    if m:
        rec["doi"] = m.group(1).rstrip(".")
    m = re.search(r"(?:목적|인용 의도)[=:]\s*(.+?)(?:[.。]\s|$)", text)
    if m:
        rec["purpose"] = m.group(1).strip()
    m = re.search(r"요약[=:]\s*(.+)$", text)
    rec["summary"] = m.group(1).strip() if m else text[:120]
    return rec


def load_mem0_records() -> list[dict]:
    """Mem0 플랫폼 REST 검색으로 T21(source=citation-verifier) 요약 로드.

    키·네트워크 부재 시 경고 후 빈 리스트 반환 — 다른 소스로 리포트 생성은 계속.
    """
    api_key = read_secret_key("MEM0_API_KEY")
    if not api_key:
        print("[경고] MEM0_API_KEY 미확보(env·mcp-secrets.env) — Mem0 소스 생략", file=sys.stderr)
        return []
    payload = json.dumps({
        "query": "citation-verifier 검증 verdict",
        "filters": {"AND": [{"user_id": MEM0_USER_ID}]},
        "limit": 100,
    }).encode("utf-8")
    req = urllib.request.Request(
        MEM0_SEARCH_URL, data=payload, method="POST",
        headers={"Authorization": f"Token {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        print(f"[경고] Mem0 검색 실패({exc}) — Mem0 소스 생략", file=sys.stderr)
        return []

    items = data if isinstance(data, list) else data.get("results", [])
    records = []
    for item in items:
        metadata = item.get("metadata") or {}
        if metadata.get("source") != "citation-verifier":
            continue
        rec = parse_t21_text(item.get("memory") or item.get("text") or "")
        if rec:
            records.append(rec)
    return records


def merge_records(log_records: list[dict], mem0_records: list[dict]) -> list[dict]:
    """(DOI, 날짜) 중복 시 상세 로그 우선 — evidence를 보존하는 쪽이 canonical (§1 2층 구조)."""
    seen = {(r["doi"].lower(), r["date"]) for r in log_records}
    merged = list(log_records)
    merged.extend(
        r for r in mem0_records
        if (r.get("doi", "-").lower(), r.get("date", "-")) not in seen
    )
    return merged


def normalize_records(records: list[dict]) -> list[dict]:
    """렌더러가 기대하는 전체 필드를 기본값으로 채우고 날짜순 정렬 + idx 부여."""
    out = []
    for rec in records:
        merged = {**RECORD_DEFAULTS, **rec}
        merged.setdefault("updated_at", merged["date"])
        out.append(merged)
    out.sort(key=lambda r: (r["date"], r["paper"]))
    for i, rec in enumerate(out, start=1):
        rec["idx"] = i
    return out


def register_font() -> str:
    """CID 기반 한국어 폰트 등록. PDF 뷰어가 CID 폰트를 내장한 경우 한글 렌더링 가능."""
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        pdfmetrics.registerFont(UnicodeCIDFont(KOREAN_CID_FONT))
        return KOREAN_CID_FONT
    except Exception as exc:
        print(f"[경고] 한글 CID 폰트 등록 실패({exc}) — Helvetica fallback", file=sys.stderr)
        return "Helvetica"


def build_styles(font_name: str):
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("Title", parent=base["Title"], fontName=font_name, fontSize=20, leading=26),
        "h1": ParagraphStyle("H1", parent=base["Heading1"], fontName=font_name, fontSize=14, leading=18, spaceAfter=6),
        "h2": ParagraphStyle("H2", parent=base["Heading2"], fontName=font_name, fontSize=12, leading=16, spaceAfter=4),
        "body": ParagraphStyle("Body", parent=base["BodyText"], fontName=font_name, fontSize=9, leading=12),
        "small": ParagraphStyle("Small", parent=base["BodyText"], fontName=font_name, fontSize=8, leading=10),
        "cell": ParagraphStyle("Cell", parent=base["BodyText"], fontName=font_name, fontSize=8, leading=10, wordWrap="CJK"),
    }


def mcp_usage_section(styles: dict) -> list:
    """3개 MCP(Tavily/Mem0/citation-verifier) 사용 현황 표. Tavily만 자동 조회."""
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle, PageBreak

    api_key = read_secret_key("TAVILY_API_KEY")
    tavily_row = ["Tavily", "조회 실패", "-", "API 키 미확보 또는 네트워크 오류"]
    if api_key:
        usage = fetch_tavily_usage(api_key)
        if usage:
            account = usage.get("account", {})
            plan_usage = account.get("plan_usage", "?")
            plan_limit = account.get("plan_limit", "?")
            plan_name = account.get("current_plan", "-")
            tavily_row = [
                "Tavily",
                f"{plan_usage} / {plan_limit}",
                plan_name,
                (
                    f"search={account.get('search_usage', 0)}, "
                    f"extract={account.get('extract_usage', 0)}, "
                    f"crawl={account.get('crawl_usage', 0)}, "
                    f"map={account.get('map_usage', 0)}, "
                    f"research={account.get('research_usage', 0)}"
                ),
            ]

    rows = [
        ["MCP", "사용량 / 가능량", "플랜", "비고"],
        tavily_row,
        [
            "Mem0",
            "확인 불가",
            "-",
            "공식 usage API 미문서화 — app.mem0.ai 웹 대시보드 참고",
        ],
        [
            "citation-verifier",
            "확인 불가",
            "-",
            "Tavily/WebSearch 기반 자체 구현 — 호출 횟수는 Tavily 사용량으로 간접 추적",
        ],
    ]

    def cell(text):
        return Paragraph(str(text), styles["cell"])

    data = [[cell(c) for c in row] for row in rows]
    col_widths = [25 * mm, 35 * mm, 28 * mm, 92 * mm]
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2b5aa0")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, -1), styles["body"].fontName),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
            ("BACKGROUND", (0, 1), (0, -1), colors.HexColor("#f0f4fa")),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
        ])
    )

    return [
        Paragraph("MCP 사용 현황", styles["h1"]),
        Spacer(1, 3 * mm),
        Paragraph(
            "Tavily는 `GET /usage` API로 자동 조회. Mem0/citation-verifier는 공식 usage API 미제공으로 수동 확인 필요.",
            styles["small"],
        ),
        Spacer(1, 4 * mm),
        table,
        PageBreak(),
    ]


def cover_page(styles: dict, verifications: list, source_desc: str) -> list:
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle, PageBreak

    total = len(verifications)
    projects = sorted({r["project"] for r in verifications})
    used = sum(1 for r in verifications if r["actual_use"] == "YES")
    usage_rate = f"{used / total * 100:.0f}%" if total else "N/A"
    retracted_count = sum(1 for r in verifications if r.get("retracted", False))
    forbidden_count = sum(1 for r in verifications if r["verdict"] == "금지")
    dates = sorted({r["date"] for r in verifications if r["date"] != "-"})
    period = f"{dates[0]} ~ {dates[-1]}" if dates else "N/A"

    story = [
        Paragraph("citation-verifier 검증 이력 리포트", styles["title"]),
        Spacer(1, 6 * mm),
        Paragraph(f"생성 일시: {datetime.now().strftime('%Y-%m-%d %H:%M')}", styles["body"]),
        Paragraph("규칙 근거: <font face='Helvetica'>rules/agent-routing.md (citation-verifier)</font>", styles["body"]),
        Spacer(1, 12 * mm),
    ]

    summary_data = [
        ["항목", "값"],
        ["데이터 소스", source_desc],
        ["총 검증 건수", str(total)],
        ["프로젝트 개수", f"{len(projects)} ({', '.join(projects)})"],
        ["실제 사용 건수", f"{used} / {total} ({usage_rate})"],
        ["철회(retracted) 감지", str(retracted_count)],
        ["금지 판정 건수", str(forbidden_count)],
        ["기간", period],
    ]

    table = Table(summary_data, colWidths=[60 * mm, 110 * mm])
    table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2b5aa0")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, -1), styles["body"].fontName),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("BACKGROUND", (0, 1), (0, -1), colors.HexColor("#f0f4fa")),
        ])
    )
    story.append(table)
    story.append(Spacer(1, 12 * mm))
    story.append(Paragraph(
        "이 리포트는 상세 로그(docs/citation-verifications.md)와 Mem0에 저장된 "
        "citation-verifier 검증 이력을 집계한 결과입니다. "
        "citation-verifier 에이전트는 논문 인용 전 verdict(허용/경고/금지), retracted 여부, "
        "supporting/contrasting 비율을 검증하며 결과를 Mem0(source=citation-verifier)에 저장합니다.",
        styles["small"],
    ))
    story.append(PageBreak())
    return story


def _verdict_color(verdict: str):
    """verdict 값에 따라 배경색 반환."""
    from reportlab.lib import colors
    if verdict == "허용":
        return colors.HexColor("#d6f0d0")
    if verdict == "금지":
        return colors.HexColor("#f8d7da")
    return colors.HexColor("#fff3cd")  # 경고 및 기타


def verification_card(record: dict, styles: dict) -> list:
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

    def cell(text: str) -> Paragraph:
        return Paragraph(str(text), styles["cell"])

    retracted_str = "YES (철회됨)" if record.get("retracted", False) else "NO"
    confidence_map = {"high": "높음", "med": "중간", "low": "낮음"}
    confidence_str = confidence_map.get(record.get("confidence", ""), record.get("confidence", "-"))
    # fixture는 bool, 상세 로그/T21은 high|partial|abstract-only 문자열 — 양쪽 렌더 지원
    ftc = record.get("fulltext_coverage", "-")
    fulltext_str = ("Yes" if ftc else "No") if isinstance(ftc, bool) else str(ftc)

    rows = [
        ["#", cell(record["idx"]), "날짜", cell(record["date"])],
        ["Invoker", cell(record["invoker"]), "Project", cell(record["project"])],
        ["논문", cell(record["paper"])],
        ["DOI", cell(record["doi"])],
        ["목적", cell(record["purpose"])],
        [
            "Smart Citations",
            cell(
                f"supporting={record['supporting']}, "
                f"contrasting={record['contrasting']}, "
                f"mentioning={record['mentioning']}"
            ),
        ],
        ["retracted", cell(retracted_str), "confidence", cell(confidence_str)],
        ["fulltext_coverage", cell(fulltext_str), "verdict", cell(record["verdict"])],
        ["actual_use", cell(record["actual_use"]), "status", cell(record["status"])],
        ["location", cell(record["location"])],
        ["updated_at", cell(record["updated_at"])],
        ["요약", cell(record["summary"])],
    ]

    # 3열 또는 4열 레이아웃 처리: 4열 행은 그대로, 2열 행은 병합 셀로 확장
    normalized = []
    for row in rows:
        if len(row) == 2:
            normalized.append([row[0], row[1], "", ""])
        elif len(row) == 4:
            normalized.append(row)
        else:
            normalized.append(row + [""] * (4 - len(row)))

    col_widths = [30 * mm, 80 * mm, 25 * mm, 55 * mm]
    table = Table(normalized, colWidths=col_widths, repeatRows=0)

    style_cmds = [
        ("FONTNAME", (0, 0), (-1, -1), styles["body"].fontName),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f0f4fa")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#f0f4fa")),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#1f3a68")),
        ("TEXTCOLOR", (2, 0), (2, -1), colors.HexColor("#1f3a68")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]

    # verdict 행 배경 강조 (normalized에서 verdict 위치 탐색)
    for ridx, row in enumerate(rows):
        if len(row) == 4 and row[2] == "verdict":
            style_cmds.append(("BACKGROUND", (3, ridx), (3, ridx), _verdict_color(record["verdict"])))
        if len(row) == 4 and row[0] == "retracted" and record.get("retracted", False):
            style_cmds.append(("BACKGROUND", (1, ridx), (1, ridx), colors.HexColor("#f8d7da")))

    # 2열 행(병합)의 인덱스 찾기
    merge_indices = [i for i, r in enumerate(rows) if len(r) == 2]
    for ridx in merge_indices:
        style_cmds.append(("SPAN", (1, ridx), (3, ridx)))

    table.setStyle(TableStyle(style_cmds))

    result = [
        Paragraph(f"레코드 #{record['idx']} — {record['paper']}", styles["h2"]),
        Spacer(1, 2 * mm),
        table,
    ]

    # evidence 상세 섹션
    evidence_list = record.get("evidence", [])
    if evidence_list:
        result.append(Spacer(1, 2 * mm))
        result.append(Paragraph("Evidence (인용 스니펫)", styles["h2"]))
        ev_rows = [["stance", "citing", "snippet", "URL"]]
        for ev in evidence_list:
            ev_rows.append([
                cell(ev.get("stance", "")),
                cell(ev.get("citing", "")),
                cell(ev.get("snippet", "")),
                cell(ev.get("url", "")),
            ])
        ev_table = Table(ev_rows, colWidths=[20 * mm, 35 * mm, 75 * mm, 60 * mm], repeatRows=1)
        ev_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4a7fc1")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, -1), styles["cell"].fontName),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
        ]))
        result.append(ev_table)

    result.append(Spacer(1, 6 * mm))
    return result


def summary_table_section(styles: dict, verifications: list) -> list:
    """전체 검증 이력 요약 테이블: 논문 / verdict / supporting / contrasting / retracted / confidence / 날짜."""
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle, PageBreak

    def cell(text: str) -> Paragraph:
        return Paragraph(str(text), styles["cell"])

    header = ["논문", "verdict", "supporting", "contrasting", "retracted", "confidence", "날짜"]
    rows = [header]
    for r in verifications:
        rows.append([
            cell(r["paper"]),
            cell(r["verdict"]),
            cell(str(r["supporting"])),
            cell(str(r["contrasting"])),
            cell("YES" if r.get("retracted", False) else "NO"),
            cell(r.get("confidence", "-")),
            cell(r["date"]),
        ])

    col_widths = [65 * mm, 18 * mm, 20 * mm, 20 * mm, 18 * mm, 20 * mm, 22 * mm]
    table = Table(rows, colWidths=col_widths, repeatRows=1)

    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2b5aa0")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, -1), styles["body"].fontName),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]
    # verdict 컬럼 (col 1) 배경 강조
    for ridx, r in enumerate(verifications, start=1):
        style_cmds.append(("BACKGROUND", (1, ridx), (1, ridx), _verdict_color(r["verdict"])))
        if r.get("retracted", False):
            style_cmds.append(("BACKGROUND", (4, ridx), (4, ridx), colors.HexColor("#f8d7da")))

    table.setStyle(TableStyle(style_cmds))

    return [
        Paragraph("검증 이력 요약 테이블", styles["h1"]),
        Spacer(1, 4 * mm),
        table,
        PageBreak(),
    ]


def project_section(styles: dict, verifications: list) -> list:
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer, PageBreak

    by_project = {}
    for r in verifications:
        by_project.setdefault(r["project"], []).append(r)

    story = []
    for proj, items in by_project.items():
        story.append(Paragraph(f"[{proj}] citation-verifier 검증 이력 ({len(items)}건)", styles["h1"]))
        story.append(Spacer(1, 4 * mm))
        for r in items:
            story.extend(verification_card(r, styles))
        story.append(PageBreak())
    return story


def tail_section(styles: dict, verifications: list) -> list:
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer

    retracted = [r for r in verifications if r.get("retracted", False)]
    forbidden = [r for r in verifications if r["verdict"] == "금지"]
    contra_ge_supp = [
        r
        for r in verifications
        if isinstance(r["supporting"], int)
        and isinstance(r["contrasting"], int)
        and r["contrasting"] >= r["supporting"]
    ]
    pending_stale = [r for r in verifications if r["status"] == "pending_review"]

    story = [
        Paragraph("주의 항목 및 메모", styles["h1"]),
        Spacer(1, 4 * mm),
        Paragraph(
            f"철회(retracted) 감지 논문: {len(retracted)}건"
            + (f" — {', '.join(r['paper'] for r in retracted)}" if retracted else ""),
            styles["body"],
        ),
        Paragraph(
            f"금지 판정 논문: {len(forbidden)}건"
            + (f" — {', '.join(r['paper'] for r in forbidden)}" if forbidden else ""),
            styles["body"],
        ),
        Paragraph(
            f"contrasting ≥ supporting 논문: {len(contra_ge_supp)}건"
            + (f" — {', '.join(r['paper'] for r in contra_ge_supp)}" if contra_ge_supp else ""),
            styles["body"],
        ),
        Paragraph(
            f"pending_review 방치 항목: {len(pending_stale)}건",
            styles["body"],
        ),
        Spacer(1, 8 * mm),
    ]

    if all(r.get("_source") == "test" for r in verifications):
        memo = ("메모: 이 리포트는 --test-data 플래그로 생성된 내장 fixture 기반입니다. "
                "실제 검증 이력이 아닙니다.")
    else:
        used = sum(1 for r in verifications if r.get("actual_use") == "YES")
        memo = (f"메모: 실제 사용(actual_use=YES) {used}건 / 총 {len(verifications)}건. "
                "실사용 발생 시 mem0-auto.md T21 트리거로 actual_use·location·status "
                "필드가 업데이트됩니다.")
    story.append(Paragraph(memo, styles["small"]))
    return story


def generate_pdf(output_path: Path, verifications: list, source_desc: str) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate
    from reportlab.lib.units import mm

    output_path.parent.mkdir(parents=True, exist_ok=True)
    font_name = register_font()
    styles = build_styles(font_name)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title="citation-verifier 검증 이력 리포트",
    )

    story = []
    story.extend(cover_page(styles, verifications, source_desc))
    story.extend(mcp_usage_section(styles))
    story.extend(summary_table_section(styles, verifications))
    story.extend(project_section(styles, verifications))
    story.extend(tail_section(styles, verifications))
    doc.build(story)


def generate_csv(output_path: Path, verifications: list) -> None:
    """CSV fallback: --output 인자가 .csv로 끝날 경우 사용."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "idx", "date", "invoker", "project", "paper", "doi",
        "verdict", "supporting", "contrasting", "mentioning",
        "retracted", "confidence", "fulltext_coverage",
        "purpose", "actual_use", "status", "location", "updated_at", "summary",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in verifications:
            row = {k: r.get(k, "") for k in fieldnames}
            writer.writerow(row)


def main() -> int:
    parser = argparse.ArgumentParser(description="citation-verifier 검증 이력 PDF 리포트 생성")
    parser.add_argument("--output", required=True, help="출력 PDF 또는 CSV 절대 경로 (.pdf/.csv)")
    parser.add_argument("--project", default="all", help="프로젝트 필터 (기본: all)")
    parser.add_argument("--since", default=None, metavar="YYYY-MM-DD", help="이 날짜 이후 레코드만 포함")
    parser.add_argument("--log", action="append", type=Path, default=None,
                        help="상세 로그 경로 (반복 지정 가능, 기본: ./docs/citation-verifications.md)")
    parser.add_argument("--test-data", action="store_true",
                        help="내장 테스트 fixture로 생성 (실데이터 소스를 읽지 않음)")
    args = parser.parse_args()

    if args.test_data:
        verifications = [dict(r, _source="test") for r in CITATION_VERIFICATIONS]
        source_desc = "내장 테스트 fixture (--test-data)"
        print("[경고] --test-data: 내장 fixture로 생성 — 실제 검증 이력 아님", file=sys.stderr)
    else:
        log_paths = args.log if args.log else [DEFAULT_LOG_PATH]
        log_records: list[dict] = []
        for p in log_paths:
            found = load_log_records(p.expanduser())
            if not found:
                print(f"[경고] 상세 로그 없음 또는 레코드 0건: {p}", file=sys.stderr)
            log_records.extend(found)
        mem0_records = load_mem0_records()
        verifications = merge_records(log_records, mem0_records)
        source_desc = (f"상세 로그 {len(log_records)}건 + Mem0 {len(mem0_records)}건 "
                       f"(병합 후 {len(verifications)}건)")
        if not verifications:
            print("[오류] 실데이터 소스에서 검증 이력 0건.", file=sys.stderr)
            print("  - 상세 로그: docs/citation-verifications.md 존재 확인 (--log 로 경로 지정)", file=sys.stderr)
            print("  - Mem0: MEM0_API_KEY(env·mcp-secrets.env)와 user_id(MEM0_DEFAULT_USER_ID) 확인", file=sys.stderr)
            print("  - 테스트 출력이 필요하면 --test-data 플래그 사용", file=sys.stderr)
            return 2

    if args.project != "all":
        verifications = [r for r in verifications if r.get("project") == args.project]
    if args.since:
        verifications = [r for r in verifications if r.get("date", "-") >= args.since]
    if not verifications:
        print(f"[오류] 필터(project={args.project}, since={args.since}) 적용 후 레코드 0건.", file=sys.stderr)
        print("복구: --project / --since 인자 확인", file=sys.stderr)
        return 2
    verifications = normalize_records(verifications)

    output_path = Path(args.output).expanduser().resolve()

    # CSV fallback
    if output_path.suffix.lower() == ".csv":
        try:
            generate_csv(output_path, verifications)
        except PermissionError as exc:
            print(f"[오류] 경로 권한 부족: {exc}\n복구: 경로 쓰기 권한 확인", file=sys.stderr)
            return 4
        size_kb = output_path.stat().st_size / 1024
        print(f"CSV 생성 완료: {output_path} ({size_kb:.1f} KB)")
        return 0

    try:
        generate_pdf(output_path, verifications, source_desc)
    except ImportError as exc:
        print(f"[오류] 라이브러리 누락: {exc}\n복구: `uv pip install --system reportlab`", file=sys.stderr)
        return 3
    except PermissionError as exc:
        print(f"[오류] 경로 권한 부족: {exc}\n복구: 경로 쓰기 권한 확인 또는 다른 경로 지정", file=sys.stderr)
        return 4
    except Exception as exc:
        print(f"[오류] PDF 생성 실패: {exc}", file=sys.stderr)
        print("복구 체크리스트:", file=sys.stderr)
        print("  1. reportlab 설치: uv pip install --system reportlab", file=sys.stderr)
        print("  2. 데이터 확인: --test-data 플래그로 재현되는지 확인 (데이터 vs 렌더링 문제 분리)", file=sys.stderr)
        print("  3. UTF-8 인코딩: PYTHONIOENCODING=utf-8 설정", file=sys.stderr)
        print("  4. 경로 권한: ls -la {경로}", file=sys.stderr)
        print("  5. CSV fallback: --output 인자를 .csv 확장자로 변경", file=sys.stderr)
        return 1

    size_kb = output_path.stat().st_size / 1024
    print(f"PDF 생성 완료: {output_path} ({size_kb:.1f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
