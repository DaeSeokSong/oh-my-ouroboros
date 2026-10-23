"""public-export-scan.py 시험(임시 폴더의 가짜 정제본과 설정 — 실제 하네스 낱말 설정은 읽지 않는다).

실행: uv run -q --with pytest python -m pytest scripts/tests/test_public_export_scan.py -q -p no:cacheprovider
"""
import importlib.util
import pathlib

SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "public-export-scan.py"
spec = importlib.util.spec_from_file_location("pes", SCRIPT)
pes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pes)


def _setup(tmp_path, cfg):
    stage = tmp_path / "stage"
    (stage / "docs").mkdir(parents=True)
    (stage / "docs/a.md").write_text("평범한 줄\nACME 병원 자료\n", encoding="utf-8")
    (stage / "docs/b.md").write_text("url=https://<your-domain>.atlassian.net\nkey='abcd" + "1234efgh'\n", encoding="utf-8")
    (stage / "skip").mkdir()
    (stage / "skip/c.md").write_text("ACME 병원\n", encoding="utf-8")
    conf = tmp_path / "scan.txt"
    conf.write_text(cfg, encoding="utf-8")
    return stage, conf


def test_hits_by_category_with_path_and_placeholder_skips(tmp_path, capsys):
    stage, conf = _setup(tmp_path, "# 설명\n1 고객||ACME||^skip/\n2 내부 URL||[a-z-]+\\.atlassian\\.net||<your\n3 비밀값||key='[^']{8,}'||\n")
    rc = pes.main([str(stage), "--config", str(conf)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "docs/a.md:2" in out and "skip/c.md" not in out          # 경로 앞부분 건너뛰기
    assert "## 2 내부 URL: 0줄" in out                               # 자리표시 글자 건너뛰기
    assert "docs/b.md:2" in out and "abcd1234efgh" not in out        # 비밀값 범주는 내용을 찍지 않는다


def test_clean_stage_exits_zero(tmp_path, capsys):
    stage, conf = _setup(tmp_path, "4 연구 이름||NOSUCHNAME||\n")
    assert pes.main([str(stage), "--config", str(conf)]) == 0
    assert "발견 0건" in capsys.readouterr().out


def test_path_name_hit_and_bad_config(tmp_path, capsys):
    stage, conf = _setup(tmp_path, "1 경로||^skip/c||\n")
    assert pes.main([str(stage), "--config", str(conf)]) == 1
    assert "(경로 이름)" in capsys.readouterr().out
    bad = tmp_path / "bad.txt"
    bad.write_text("범주만 있음\n", encoding="utf-8")
    assert pes.main([str(stage), "--config", str(bad)]) == 2
    broken = tmp_path / "broken.txt"
    broken.write_text("1 깨짐||([||\n", encoding="utf-8")
    assert pes.main([str(stage), "--config", str(broken)]) == 2
