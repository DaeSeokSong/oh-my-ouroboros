#!/usr/bin/env python3
"""Stop hook helper: block a turn end once when the final report has an English sentence (CLAUDE.md principle 1).

Contract: stdin = Stop-hook JSON. Prints {"decision":"block","reason":...} when the last assistant
message has a Hangul-free sentence of >= 6 Latin words or a whole-message Hangul ratio < 0.4;
otherwise prints nothing. Always exits 0 (fail-open). Skips non-Stop events and stop_hook_active.
Rationale: intent/2026-10-16-korean-report-guard.md (corpus: 9 of 843 turn-end messages were English).
Text source: last_assistant_message, else the last assistant message of the transcript tail.
"""
import json
import re
import sys

MIN_WORDS = 6
MIN_RATIO = 0.4
MIN_LATIN_FOR_RATIO = 20
SNIPPET_LEN = 60

FENCE = re.compile(r"```.*?(?:```|\Z)", re.S)
INLINE = re.compile(r"`[^`\n]*`")
URL = re.compile(r"\S*/\S*")  # URLs and any slash-containing path token
SKIP_LINE = re.compile(r"^\s*[>|]")
HEADING = re.compile(r"^\s*#+\s*")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
HANGUL = re.compile(r"[가-힣]")
LATIN = re.compile(r"[A-Za-z]")
WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")
IDENT = re.compile(r"[0-9_.=:]")

REASON = (
    "직전 보고에 한글이 아닌 문장이 있습니다(사용자에게 가는 보고는 한글 존댓말 필수, CLAUDE.md 원칙 1). "
    "같은 내용을 한글 존댓말로 다시 보고하십시오. 코드·경로·명령·고유 이름은 그대로 두어도 되고, "
    "영어 원문을 인용할 때는 백틱(`)이나 인용 줄(>)에 넣으십시오. "
    "걸린 문장: «{snippet}»"
)


def clean_lines(text):
    """Return prose lines with code, URLs, quote lines, table lines and heading markers removed."""
    text = URL.sub(" ", INLINE.sub(" ", FENCE.sub(" ", text)))
    return [HEADING.sub("", ln) for ln in text.splitlines() if not SKIP_LINE.match(ln)]


def prose_latin(line):
    """Latin letters in prose-like tokens only, for the ratio rule.

    Identifier-like tokens (with a digit or one of _ . = : , or all caps such as PASS, OK, RESULT)
    are not counted: a short Korean report naming gpt-6.1-sol, val_gated_tri_mean or «RESULT: PASS»
    must not fall under the ratio floor (2026-10-16 qa false positives). The sentence rule is unaffected.
    """
    n = 0
    for tok in line.split():
        word = tok.strip("()[]{}«»\"'',;!?")
        if not word or IDENT.search(word) or (len(word) > 1 and word.isupper()):
            continue
        n += len(LATIN.findall(word))
    return n


def find_english(text):
    """Return (offending sentences, Hangul ratio) for a report text."""
    lines = clean_lines(text)
    hangul = sum(len(HANGUL.findall(ln)) for ln in lines)
    latin = sum(prose_latin(ln) for ln in lines)
    ratio = hangul / (hangul + latin) if hangul + latin else 1.0
    offenders = []
    for ln in lines:
        for sent in SENTENCE_SPLIT.split(ln):
            if not HANGUL.search(sent) and len(WORD.findall(sent)) >= MIN_WORDS:
                offenders.append(sent.strip())
    if not offenders and ratio < MIN_RATIO and latin >= MIN_LATIN_FOR_RATIO:
        first = next((ln.strip() for ln in lines if LATIN.search(ln)), "")
        offenders.append(first)
    return offenders, ratio


def last_message_from_transcript(path):
    """Return the text blocks of the last assistant entry in the transcript tail, or ''."""
    last = ""
    with open(path, encoding="utf-8") as f:
        tail = f.readlines()[-300:]
    for line in tail:
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if obj.get("type") != "assistant":
            continue
        content = (obj.get("message") or {}).get("content")
        if isinstance(content, list):
            last = "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return last


def main():
    """Read the hook JSON from stdin and print a block decision when the report is not Korean."""
    data = json.load(sys.stdin)
    if data.get("hook_event_name") != "Stop" or data.get("stop_hook_active"):
        return
    text = data.get("last_assistant_message") or ""
    if not text.strip() and data.get("transcript_path"):
        text = last_message_from_transcript(data["transcript_path"])
    if not text.strip():
        return
    offenders, _ = find_english(text)
    if offenders:
        snippet = offenders[0][:SNIPPET_LEN].replace("\n", " ")
        print(json.dumps({"decision": "block", "reason": REASON.format(snippet=snippet)}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
