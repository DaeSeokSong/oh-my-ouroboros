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
"""

import re
import sys


def fix_corrupt_macro_attrs(html: str) -> str:
    """
    §7 수정: storage HTML의 ='\"VALUE\"' → ="VALUE" 일괄 교체
    발생 원인: MCP 도구가 JSON 다중 직렬화 → 속성 따옴표 이중 변환
    예) ac:name='\"toc\"' → ac:name="toc"
    """
    fixed = re.sub(r"""='\\\"([^\\"]*)\\"'""", r'="\1"', html)
    remaining = re.findall(r"""='\\\"[^\\"]*\\"'""", fixed)
    if remaining:
        raise ValueError(f"§7: 여전히 깨진 속성 {len(remaining)}개 남음")
    return fixed


# §8 탐지·치환 공용 패턴: "정확히 2개" 백슬래시 런(lookbehind로 3개+ 런 배제)
# + LaTeX 명령 시작 문자(lookahead). JSON 이중 직렬화는 단일 \를 정확히 \\로
# 만들므로 2개 런이 오염의 유일한 시그니처다. 3개+ 런은 모델 밖 → 보존.
# 탐지와 치환이 같은 패턴을 공유해야 "탐지보다 넓은 치환"이 구조적으로 불가능하고,
# 치환 결과는 단일 \이므로 재적용 시 무변경(멱등) — 사후 검증이 오발하지 않는다.
ADF_DOUBLED_BACKSLASH = re.compile(r'(?<!\\)\\\\(?=[A-Za-z\[\]{}()^_])')


def fix_adf_formula_backslash(html: str) -> tuple[str, int]:
    """
    §8 수정: ADF body 파라미터의 \\\\command → \\command 교체
    발생 원인: MCP 도구가 body 파라미터를 JSON 다중 직렬화 → 백슬래시 이중 변환
    예) \\\\Delta → \\Delta, \\\\mathcal → \\mathcal

    치환 범위는 탐지 조건과 동일한 문맥(정확히 2개 백슬래시 런 + LaTeX 명령 시작
    문자)으로 한정한다. body 전체 blanket replace 금지 — 비명령 문맥의 무관한 이중
    백슬래시(숫자·공백·구두점 앞, 예: 경로 "dir\\\\2.txt")와 3개+ 백슬래시 런(예:
    UNC "\\\\\\\\server")은 오염 모델(단일 \\ → \\\\ 이중화) 밖이므로 보존한다.
    한계: 정확히 \\\\ 뒤가 영문자인 경우(예: "C:\\\\Users")는 LaTeX 명령과 구분
    불가능해 여전히 축약된다. 구두점 이스케이프(\\\\% 등)의 이중 변환은 복원하지
    않지만, 탐지 조건도 이를 오염으로 분류하지 않으므로 일관적이다.
    """
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


# §9 탐지·치환 공용: 뒤가 영문자가 아닌 리터럴 \n (영문자가 뒤따르면 \nabla 같은 LaTeX 명령)
LITERAL_NEWLINE = re.compile(r'\\n(?![A-Za-z])')


def fix_adf_formula_literal_newlines(html: str) -> tuple[str, int]:
    """
    §9 수정: ADF body 파라미터의 리터럴 \\n (0x5C+0x6E) 제거
    발생 원인: REST API가 body를 JSON 직렬화 → 실제 개행(0x0A) 대신 \\n 두 문자로 저장
    증상: 수식 블록 앞뒤에 불필요한 빈 줄 렌더링
    뒤에 영문자가 오는 \\n 은 지우지 않는다 — \\nabla·\\nu·\\neq 같은 LaTeX 명령이 깨진다(2026-10-01 감사).
    한계: 개행 바로 뒤에 영문자 수식이 붙은 오염("\\nE=...")은 구분할 수 없어 남는다.
    """
    count = [0]

    def fix_body(match):
        original = match.group(1)
        cleaned = LITERAL_NEWLINE.sub('', original)  # 리터럴 \n 두 문자 제거(뒤가 영문자면 LaTeX 명령이라 보존)
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
    """
    3가지 수정을 순서대로 일괄 적용.
    순서: fix_corrupt_macro_attrs → fix_adf_formula_backslash → fix_adf_formula_literal_newlines
    """
    # §7: 매크로 속성 따옴표 오염
    if re.search(r"""='\\\"[^\\"]*\\"'""", html):
        if verbose:
            print("⚠️  §7 매크로 속성 오염 감지 → fix_corrupt_macro_attrs 적용")
        html = fix_corrupt_macro_attrs(html)
        if verbose:
            print("   ✅ §7 수정 완료")

    # §8: ADF body 백슬래시 이중 변환
    if ADF_DOUBLED_BACKSLASH.search(html):
        if verbose:
            print("⚠️  §8 ADF body 백슬래시 오염 감지 → fix_adf_formula_backslash 적용")
        html, cnt = fix_adf_formula_backslash(html)
        if verbose:
            print(f"   ✅ §8 수정 완료 ({cnt}개 body)")

    # §9: ADF body 리터럴 \n
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
