"""fix_confluence_html.py §9 회귀 테스트: 리터럴 \\n 제거가 \\nabla·\\nu·\\neq 수식을 깨지 않는다.

실행: uv run --with pytest python -m pytest scripts/tests/test_fix_confluence_html.py -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fix_confluence_html as fx  # noqa: E402


def wrap(body):
    return f'<ac:adf-parameter key="body">{body}</ac:adf-parameter>'


def test_latex_commands_starting_with_n_survive(capsys):
    body = r"\nabla f + \nu x \neq 0"
    assert fx.fix_all(wrap(body), verbose=False) == wrap(body)


def test_real_literal_newlines_removed_with_count(capsys):
    out = fx.fix_all(wrap(r"\n\begin{aligned} a \nabla b \end{aligned}\n"), verbose=True)
    assert out == wrap(r"\begin{aligned} a \nabla b \end{aligned}")
    assert "리터럴 \\n 2건 제거" in capsys.readouterr().out
