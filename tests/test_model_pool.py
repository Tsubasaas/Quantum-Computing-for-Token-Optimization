"""使えるモデルプールの選別（model_pool）の妥当性チェック。"""

from __future__ import annotations

from taqumi2026s_teame.data import load_agents, load_models
from taqumi2026s_teame.data.model_pool import (
    BENCHMARK_ONLY,
    EXCLUDED,
    SUPERSEDED,
    exclusion_reason,
    usable_model_ids,
)
from taqumi2026s_teame.data.task_types import PLAN_CATEGORIES, PLAN_CATEGORY_ROLES

_ALL_IDS = {m["model_id"] for m in load_models()}


def test_every_excluded_id_exists_in_models_json():
    assert set(EXCLUDED) <= _ALL_IDS


def test_superseded_targets_are_real_and_usable():
    usable = set(usable_model_ids(_ALL_IDS))
    for old, new in SUPERSEDED.items():
        assert new in _ALL_IDS, f"{old} の後継 {new} が models.json に無い"
        assert new in usable, f"{old} の後継 {new} 自体が除外されている"


def test_no_id_is_both_superseded_and_benchmark_only():
    assert set(SUPERSEDED).isdisjoint(BENCHMARK_ONLY)


def test_usable_pool_excludes_known_stale_and_benchmark_only():
    usable = set(usable_model_ids(_ALL_IDS))
    for stale in ("claude_opus_47", "claude_sonnet_46", "gemini_25_pro", "kimi_k25"):
        assert stale not in usable
    for bench in ("claude_mythos_5", "inkling_small", "hy4_preview"):
        assert bench not in usable
    # 最新版は残る
    for keep in ("claude_opus_5", "claude_sonnet_5", "gemini_31_pro", "onprem_mimo"):
        assert keep in usable


def test_usable_pool_still_covers_every_plan_category_including_local():
    usable = load_agents(only_usable=True)
    for category in PLAN_CATEGORIES:
        roles = PLAN_CATEGORY_ROLES[category]
        covering = [a for a in usable if any(a.can_do(r) for r in roles)]
        assert covering, f"{category} を担当できる使えるモデルが無い"
        assert any(not a.external for a in covering), f"{category} にローカル実行できる選択肢が無い"


def test_exclusion_reason_roundtrips():
    assert exclusion_reason("claude_mythos_5")
    assert exclusion_reason("claude_opus_47")
    assert exclusion_reason("claude_opus_5") is None


def test_load_agents_default_keeps_full_catalog():
    assert len(load_agents()) == len(_ALL_IDS)
    assert len(load_agents(only_usable=True)) < len(_ALL_IDS)
