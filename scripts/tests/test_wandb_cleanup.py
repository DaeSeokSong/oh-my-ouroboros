"""tools/wandb_cleanup 회귀 테스트 (가짜 wandb·wandb_gql 모듈 — 실제 wandb 호출 없음).

실행: uv run --with pytest python -m pytest scripts/tests/test_wandb_cleanup.py -q
"""
import json
import sys
import types
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "tools" / "wandb_cleanup"
sys.path.insert(0, str(TOOLS))
import wandb_3tier_apply as ap  # noqa: E402
import wandb_3tier_common as common  # noqa: E402
import wandb_3tier_dryrun as dr  # noqa: E402


def test_keyword_constants_are_one_shared_object():
    assert ap.PILLAR_KEYWORDS is dr.PILLAR_KEYWORDS is common.PILLAR_KEYWORDS
    assert "bneck" in dr.PILLAR_KEYWORDS["modularity"]   # 수정 전 dry-run 은 이 확장 키워드가 없었다
    assert dr.guess_pillars("p2_bneck_x") == ap.guess_pillars("p2_bneck_x") == ["modularity"]


def test_fresh_path_keeps_existing_backup(tmp_path):
    p = tmp_path / "b.json"
    assert ap.fresh_path(p) == p
    p.write_text("ORIGINAL")
    q = ap.fresh_path(p)
    assert q != p and q.suffix == ".json" and q.name.startswith("b.") and not q.exists()
    q.write_text("x")
    assert ap.fresh_path(p) not in (p, q)   # 같은 초에 또 써도 서로 덮지 않는다


def test_plan_drift_detects_changed_missing_and_unplanned():
    plan = {"keep36": {"k1": {"tags": ["keep", "biological"]}, "k2": {"tags": None}},
            "ambiguous_reps": {"a1": {"tags": ["modularity", "ambiguous"]}, "a2": {"tags": ["xai", "ambiguous"]}}}
    final = {"k1": ["biological", "keep"], "a1": ["biological", "ambiguous"], "z9": ["ambiguous"]}
    msgs = ap.plan_drift(plan, final)
    assert any(m.startswith("a1:") for m in msgs)               # 태그 다름
    assert any(m.startswith("a2:") and "live 에 없음" in m for m in msgs)
    assert any(m.startswith("z9:") for m in msgs)               # 계획에 없던 태그
    assert not any(m.startswith(("k1:", "k2:")) for m in msgs)  # 같은 집합·live 누락 경고 항목은 통과


class _Run:
    def __init__(self, rid, tags):
        self.id, self.name, self.created_at, self.tags = rid, rid, "2026-01-01", list(tags)
        self.config = {}

    def update(self):
        UPDATED.append(self.id)


UPDATED = []


def _install_fake_wandb(monkeypatch, runs):
    api = types.SimpleNamespace(
        runs=lambda path, per_page=500: runs,
        run=lambda path: next(r for r in runs if r.id == path.split("/")[-1]),
        client=types.SimpleNamespace(execute=lambda q, variable_values=None: (
            {"project": {"allViews": {"edges": [{"node": {"id": "VIEW", "name": "n", "displayName": "d", "description": "",
                                                          "spec": json.dumps({"section": {"runSets": [{"selections": {"tree": ["t1"]}}]}})}}]}}}
            if "allViews" in q else {"upsertView": {"view": {"id": "VIEW"}, "inserted": False}})),
    )
    monkeypatch.setitem(sys.modules, "wandb", types.SimpleNamespace(Api=lambda: api))
    monkeypatch.setitem(sys.modules, "wandb_gql", types.SimpleNamespace(gql=lambda q: q))


@pytest.fixture
def env(tmp_path, monkeypatch):
    UPDATED.clear()
    _install_fake_wandb(monkeypatch, [_Run("r1", ["old"]), _Run("r2", ["old"])])
    monkeypatch.setenv("I_UNDERSTAND_THIS_WRITES_TO_WANDB", "1")
    monkeypatch.setattr(ap.time, "sleep", lambda s: None)
    (tmp_path / "wandb_tag_plan.json").write_text(json.dumps({"ambiguous_groups": []}))

    def run(*extra):
        monkeypatch.setattr(sys, "argv", ["x", "--out-dir", str(tmp_path), "--view-id", "VIEW", *extra])
        ap.main()

    return type("E", (), {"dir": tmp_path, "run": staticmethod(run)})


def test_apply_blocked_without_or_with_mismatching_dryrun_plan(env, capsys):
    env.run("--apply")                                  # 계획 JSON 없음
    assert "BLOCKED" in capsys.readouterr().out and UPDATED == []
    (env.dir / "wandb_3tier_plan.json").write_text(json.dumps({"keep36": {}, "ambiguous_reps": {"r1": {"tags": ["xai", "ambiguous"]}}}))
    env.run("--apply")                                  # 계획과 다름
    assert "BLOCKED" in capsys.readouterr().out and UPDATED == []
    assert not (env.dir / "wandb_3tier_tags_backup_before_apply.json").exists()


def test_apply_with_matching_plan_does_not_overwrite_existing_backups(env, capsys):
    (env.dir / "wandb_3tier_plan.json").write_text(json.dumps({"keep36": {}, "ambiguous_reps": {}}))
    first = env.dir / "wandb_3tier_tags_backup_before_apply.json"
    first.write_text("ORIGINAL-BACKUP")
    env.run("--apply")
    assert sorted(UPDATED) == ["r1", "r2"]
    assert first.read_text() == "ORIGINAL-BACKUP"       # 수정 전에는 재실행이 이 첫 백업을 덮었다
    assert len(list(env.dir.glob("wandb_3tier_tags_backup_before_apply.*.json"))) == 1
