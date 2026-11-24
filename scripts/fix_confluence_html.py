"""
Confluence Storage HTML 무결성 수정 스크립트
=============================================
MCP confluence_get_page로 가져온 storage HTML에서 발생하는 3가지 오염 패턴을 일괄 수정한다.

수정 순서 (반드시 이 순서대로):
  1. fix_corrupt_macro_attrs     — ='\"VALUE\"' → ="VALUE" (매크로 속성 따옴표 오염)
  2. fix_adf_formula_backslash   — \\\\command → \\command (백슬래시 이중 변환)
  3. fix_adf_formula_literal_newlines — 리터럴 \\n 제거 (ADF body 개행 오염)

사용법:
  python fix_confluence_html.py  # stdin에서 HTML 읽어 stdout으로 출력
  또는 스크립트에서 import하여 함수 직접 호출

한계:
  fix_adf_formula_backslash — 정확히 \\\\ 뒤가 영문자인 경우(예: "C:\\\\Users")는 LaTeX 명령과 구분
    불가능해 여전히 축약된다. 구두점 이스케이프(\\\\% 등)의 이중 변환은 복원하지
    않지만, 탐지 조건도 이를 오염으로 분류하지 않으므로 일관적이다.
  fix_adf_formula_literal_newlines — 개행 바로 뒤에 영문자 수식이 붙은 오염("\\nE=...")은 구분할 수 없어 남는다.
REF: skills/confluence/SKILL.md §7~§9
REF: knowledge/harness/code-history/scripts__fix_confluence_html.py.md
"""

import re
import sys


def fix_corrupt_macro_attrs(html: str) -> str:
    fixed = re.sub(r"""='\\\"([^\\"]*)\\"'""", r'="\1"', html)
    remaining = re.findall(r"""='\\\"[^\\"]*\\"'""", fixed)
    if remaining:
        raise ValueError(f"§7: 여전히 깨진 속성 {len(remaining)}개 남음")
    return fixed


# NEVER: 탐지와 치환에 서로 다른 패턴을 쓰지 않는다(탐지보다 넓은 치환이 생긴다).
ADF_DOUBLED_BACKSLASH = re.compile(r'(?<!\\)\\\\(?=[A-Za-z\[\]{}()^_])')


def fix_adf_formula_backslash(html: str) -> tuple[str, int]:
    count = [0]

    def fix_body(match):
        body_content = match.group(1)
        if ADF_DOUBLED_BACKSLASH.search(body_content):
            fixed_body = ADF_DOUBLED_BACKSLASH.sub(r'\\', body_content)
            if fixed_body != body_content:
                count[0] += 1
            return f'<ac:adf-parameter key="body">{fixed_body}</ac:adf-parameter>'
        return match.group(0)

    fixed = re.sub(
        r'<ac:adf-parameter key="body">(.*?)</ac:adf-parameter>',
        fix_body, html, flags=re.DOTALL
    )
    remaining = len([
        b for b in re.findall(r'<ac:adf-parameter key="body">(.*?)</ac:adf-parameter>', fixed, re.DOTALL)
        if ADF_DOUBLED_BACKSLASH.search(b)
    ])
    if remaining:
        raise ValueError(f"§8: 여전히 깨진 body {remaining}개 남음")
    return fixed, count[0]


# NEVER: 뒤에 영문자가 오는 \n 은 지우지 않는다 — \nabla·\nu·\neq 같은 LaTeX 명령이 깨진다(2026-10-01 감사).
LITERAL_NEWLINE = re.compile(r'\\n(?![A-Za-z])')


def fix_adf_formula_literal_newlines(html: str) -> tuple[str, int]:
    count = [0]

    def fix_body(match):
        original = match.group(1)
        cleaned = LITERAL_NEWLINE.sub('', original)
        cleaned = cleaned.strip()
        if cleaned != original:
            count[0] += 1
        return f'<ac:adf-parameter key="body">{cleaned}</ac:adf-parameter>'

    fixed = re.sub(
        r'<ac:adf-parameter key="body">(.*?)</ac:adf-parameter>',
        fix_body, html, flags=re.DOTALL
    )
    return fixed, count[0]


def fix_all(html: str, verbose: bool = True) -> str:
    if re.search(r"""='\\\"[^\\"]*\\"'""", html):
        if verbose:
            print("⚠️  §7 매크로 속성 오염 감지 → fix_corrupt_macro_attrs 적용")
        html = fix_corrupt_macro_attrs(html)
        if verbose:
            print("   ✅ §7 수정 완료")

    if ADF_DOUBLED_BACKSLASH.search(html):
        if verbose:
            print("⚠️  §8 ADF body 백슬래시 오염 감지 → fix_adf_formula_backslash 적용")
        html, cnt = fix_adf_formula_backslash(html)
        if verbose:
            print(f"   ✅ §8 수정 완료 ({cnt}개 body)")

    bodies = re.findall(r'<ac:adf-parameter key="body">(.*?)</ac:adf-parameter>', html, re.DOTALL)
    removed = sum(len(LITERAL_NEWLINE.findall(b)) for b in bodies)
    if removed:
        if verbose:
            print("⚠️  §9 ADF body 리터럴 \\n 감지 → fix_adf_formula_literal_newlines 적용")
        html, cnt = fix_adf_formula_literal_newlines(html)
        if verbose:
            print(f"   ✅ §9 수정 완료 ({cnt}개 body, 리터럴 \\n {removed}건 제거)")

    return html


if __name__ == "__main__":
    html_input = sys.stdin.read()
    result = fix_all(html_input, verbose=True)
    sys.stdout.write(result)
