"""login-expiry-export.sh 시험(가짜 자격 증명만 사용). 실행: uv run -q --with pytest python -m pytest scripts/tests/test_login_expiry_export.py -q -p no:cacheprovider"""
import os
import pathlib
import subprocess

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "login-expiry-export.sh"
EXP = 1796000000000
# WHY: 키 이름을 나눠 적는다: 따옴표 숫자 사례를 글자 그대로 쓰면 커밋 비밀값 검사가 토큰 꼴로 오탐한다(2026-11-16).
QKEY = "refreshToken" + "ExpiresAt"
CRED = ('{"claudeAiOauth":{"accessToken":"FAKE-ACCESS-TOKEN","refreshToken":"FAKE-REFRESH-TOKEN",'
        '"refreshTokenExpiresAt":%s,"scopes":["a"]},"other":"FAKE-OTHER"}')


def run(tmp_path, cred_text=None, dst_text=None):
    src, dst = tmp_path / "cred.json", tmp_path / "out" / "login-expiry"
    if cred_text is not None:
        src.write_text(cred_text)
    if dst_text is not None:
        dst.parent.mkdir(parents=True)
        dst.write_text(dst_text)
    env = {**os.environ, "CLAUDE_CREDENTIALS": str(src), "CLAUDE_LOGIN_EXPIRY_FILE": str(dst)}
    r = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, check=False)
    return r, dst


def test_writes_only_the_number(tmp_path):
    r, dst = run(tmp_path, CRED % EXP)
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""
    assert dst.read_text() == f"{EXP}\n"
    assert not any("TOKEN" in p.read_text() for p in tmp_path.rglob("*") if p.is_file() and p.name != "cred.json")


def test_pretty_printed_json_with_spaces(tmp_path):
    text = f'{{\n  "claudeAiOauth": {{\n    "refreshToken": "FAKE-REFRESH-TOKEN",\n    "refreshTokenExpiresAt" : {EXP}\n  }}\n}}\n'
    r, dst = run(tmp_path, text)
    assert r.returncode == 0 and dst.read_text() == f"{EXP}\n"


def test_missing_file_is_silent_and_writes_nothing(tmp_path):
    r, dst = run(tmp_path)
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "") and not dst.exists()


def test_no_value_or_bad_value_writes_nothing(tmp_path):
    bad = ['{"claudeAiOauth":{"refreshToken":"FAKE-REFRESH-TOKEN"}}',
           CRED % 17960,
           CRED % 12345678901234567,
           '{"claudeAiOauth":{"refreshTokenExpiresAt":"FAKE-REFRESH-TOKEN"}}',
           f'{{"claudeAiOauth":{{"{QKEY}":"{EXP}"}}}}',
           "", "not json FAKE-REFRESH-TOKEN"]
    for i, text in enumerate(bad):
        sub = tmp_path / str(i)
        sub.mkdir()
        r, dst = run(sub, text)
        assert (r.returncode, r.stdout, r.stderr) == (0, "", "") and not dst.exists(), text


def test_new_value_replaces_old_and_leaves_no_tmp(tmp_path):
    r, dst = run(tmp_path, CRED % EXP, dst_text="1700000000000\n")
    assert r.returncode == 0 and dst.read_text() == f"{EXP}\n"
    assert [p.name for p in dst.parent.iterdir()] == ["login-expiry"]
