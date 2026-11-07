"""割当ロジックの基本的な正当性チェック。"""

from __future__ import annotations

import pytest

from taqumi2026s_teame.config import MODE_WEIGHTS
from taqumi2026s_teame.data import load_agents, load_sample_tasks
from taqumi2026s_teame.models import SolveOptions
from taqumi2026s_teame.qubo.coefficients import build_coefficients
from taqumi2026s_teame.solvers import (
    solve_amplify,
    solve_dwave,
    solve_greedy,
    solve_random,
)


@pytest.fixture
def setup():
    agents = load_agents()
    tasks = load_sample_tasks()
    coeffs = build_coefficients(agents, tasks)
    weights = MODE_WEIGHTS["バランス"]
    return agents, tasks, coeffs, weights


def test_coefficient_shapes(setup):
    agents, tasks, coeffs, _ = setup
    n, m = len(agents), len(tasks)
    assert coeffs.q.shape == (n, m)
    assert coeffs.c.min() > 0
    assert coeffs.c_norm.shape == (n, m)
    assert 0.0 <= coeffs.c_norm.min() and coeffs.c_norm.max() <= 1.0
    assert coeffs.forbidden.sum() > 0  # 機密タスク × 社外あり


def test_gamma_trades_quality_for_cost(setup):
    """γ（コスト重視）を上げると総コストが下がる。"""
    from taqumi2026s_teame.models import Weights

    agents, tasks, coeffs, _ = setup
    opt = SolveOptions(budget=40.0)
    lo, _ = solve_greedy(agents, tasks, coeffs, Weights(gamma=0.0), opt)
    hi, _ = solve_greedy(agents, tasks, coeffs, Weights(gamma=3.0), opt)
    assert hi.metric.cost_total < lo.metric.cost_total
    assert hi.metric.exp_quality <= lo.metric.exp_quality + 1e-6


def test_mu_does_not_affect_objective(setup):
    """μ は C1/C2/C3 + α・β・γ の定式化には含まれない（今回のスコープ外）。

    Weights.mu を変えても評価される目的関数値は変わらないことを確認する
    （フィールドは残すが、目的関数には使わないという設計の回帰テスト）。
    """
    from taqumi2026s_teame.models import Weights

    agents, tasks, coeffs, _ = setup
    opt = SolveOptions(budget=40.0)
    low_mu, _ = solve_greedy(agents, tasks, coeffs, Weights(mu=0.0), opt)
    high_mu, _ = solve_greedy(agents, tasks, coeffs, Weights(mu=5.0), opt)
    assert low_mu.assignments == high_mu.assignments
    assert low_mu.metric.objective == pytest.approx(high_mu.metric.objective)


def test_deadline_does_not_affect_feasible(setup):
    """C4（締切）はどのソルバも制約として課していないため、deadline を極端に
    短く設定しても feasible は budget/violations だけで決まる（Copilot 指摘の回帰）。
    """
    agents, tasks, coeffs, weights = setup
    opt_no_deadline = SolveOptions(budget=20.0)
    opt_tight_deadline = SolveOptions(
        budget=20.0, deadline=0.001
    )  # 誰も間に合わない締切
    a, _ = solve_greedy(agents, tasks, coeffs, weights, opt_no_deadline)
    b, _ = solve_greedy(agents, tasks, coeffs, weights, opt_tight_deadline)
    assert a.assignments == b.assignments
    assert a.metric.feasible == b.metric.feasible


def test_within_deadline_diagnostic_still_reflects_option(setup):
    """within_deadline 自体は診断値として正しく計算され続ける（feasible からは除外）。"""
    agents, tasks, coeffs, weights = setup
    opt = SolveOptions(budget=20.0, deadline=0.001)
    result, _ = solve_greedy(agents, tasks, coeffs, weights, opt)
    assert result.metric.within_deadline is False
    assert result.metric.feasible  # deadline 超過は feasible を左右しない


def test_within_budget_boundary(setup):
    """総コストがちょうど予算と一致する境界で within_budget が True になる。"""
    agents, tasks, coeffs, weights = setup
    result, _ = solve_greedy(agents, tasks, coeffs, weights, SolveOptions(budget=20.0))
    exact_budget = SolveOptions(budget=result.metric.cost_total)
    boundary_result, _ = solve_greedy(agents, tasks, coeffs, weights, exact_budget)
    assert boundary_result.metric.within_budget


def test_capability_ok_independent_of_confidentiality(setup):
    """capability_ok は能力の有無だけで決まり、forbidden は機密×社外も加味する。

    そのため forbidden ⊇ (~capability_ok) だが逆は成り立たない
    （能力はあるが機密×社外で forbidden、というセルが存在しうる）。
    """
    _agents, _tasks, coeffs, _weights = setup
    # capability が無いセルは必ず forbidden（forbidden ⊇ ~capability_ok）
    assert coeffs.forbidden[~coeffs.capability_ok].all()
    # capability はあるのに forbidden というセルが実在する
    # （= 機密タスク×社外エージェントで弾かれたセル。サンプルデータで存在確認済み）
    assert (coeffs.forbidden & coeffs.capability_ok).sum() > 0


def test_cost_norm_ignores_forbidden_cells_for_max(setup):
    """c_norm の正規化は「割当可能なセルの最大コスト」基準で、forbidden セルの
    コストが（それが最大値でも）基準に影響しないことを確認する。
    """
    import numpy as np

    _agents, _tasks, coeffs, _weights = setup
    allowed_max = coeffs.c[~coeffs.forbidden].max()
    # 割当可能セルはすべて allowed_max で正規化されている
    expected = np.clip(coeffs.c / allowed_max, 0.0, 1.0)
    assert np.allclose(coeffs.c_norm[~coeffs.forbidden], expected[~coeffs.forbidden])


def test_models_json_is_sane():
    from taqumi2026s_teame.data import load_models
    from taqumi2026s_teame.data.task_types import CATEGORIES

    models = load_models()
    assert len(models) >= 20
    cats_seen: set[str] = set()
    for m in models:
        cap = m["capability"]
        assert any(
            v is not None for v in cap.values()
        ), f"{m['model_id']} が全カテゴリ null"
        for c, v in cap.items():
            assert c in CATEGORIES
            if v is None:
                continue
            assert 0.0 <= v <= 1.0, f"{m['model_id']}/{c}={v}"
            cats_seen.add(c)
        assert "sources" in m and "benchmark_metadata" in m
        # 値のあるモデルは verified メタを 1 つ以上持つ（推定で埋めていない）
        metas = [md for md in m["benchmark_metadata"].values() if isinstance(md, dict)]
        assert any(
            md.get("verified") for md in metas
        ), f"{m['model_id']} に verified メタなし"
    assert {
        "repo_bug_fix",
        "terminal",
        "document",
        "ocr",
        "image_generation",
    } <= cats_seen


def test_quality_synthesis_and_join(setup):
    from taqumi2026s_teame.data import (
        load_models,
        synthesize_quality,
        task_model_scores,
    )
    from taqumi2026s_teame.data.task_types import primary_capability

    agents, tasks, _c, _w = setup
    models = {m["model_id"]: m for m in load_models()}
    for a in agents:
        for role in a.quality:
            # 主能力を持たない役割は quality に入っていない
            assert models[a.id]["capability"].get(primary_capability(role)) is not None
            assert 0.0 <= a.quality[role] <= 1.0
    # synthesize は主能力 null なら None
    img_model = next(
        m for m in models.values() if m["capability"].get("repo_bug_fix") is None
    )
    assert synthesize_quality(img_model, "code_gen") is None

    tms = task_model_scores(tasks, agents)
    assert set(tms) == {t.id for t in tasks}
    for row in tms.values():
        for s in row.values():
            assert s["Q"] >= 0 and s["C"] > 0


def test_greedy_assigns_every_task_once(setup):
    agents, tasks, coeffs, weights = setup
    result, msg = solve_greedy(
        agents, tasks, coeffs, weights, SolveOptions(budget=20.0)
    )
    assert result is not None and msg == ""
    assert set(result.assignments) == {t.id for t in tasks}


def test_greedy_respects_confidentiality(setup):
    agents, tasks, coeffs, weights = setup
    by_id = {a.id: a for a in agents}
    result, _ = solve_greedy(agents, tasks, coeffs, weights, SolveOptions(budget=30.0))
    for task in tasks:
        if task.confidential:
            assert not by_id[result.assignments[task.id]].external


def test_greedy_beats_random(setup):
    agents, tasks, coeffs, weights = setup
    options = SolveOptions(budget=20.0, seed=42)
    greedy, _ = solve_greedy(agents, tasks, coeffs, weights, options)
    random_, _ = solve_random(agents, tasks, coeffs, weights, options)
    assert greedy.metric.objective >= random_.metric.objective


def test_greedy_is_deterministic(setup):
    agents, tasks, coeffs, weights = setup
    options = SolveOptions(budget=20.0, seed=7)
    a, _ = solve_greedy(agents, tasks, coeffs, weights, options)
    b, _ = solve_greedy(agents, tasks, coeffs, weights, options)
    assert a.assignments == b.assignments


def test_random_seed_reproducible(setup):
    agents, tasks, coeffs, weights = setup
    a, _ = solve_random(agents, tasks, coeffs, weights, SolveOptions(seed=123))
    b, _ = solve_random(agents, tasks, coeffs, weights, SolveOptions(seed=123))
    assert a.assignments == b.assignments


def test_metric_cost_matches_manual(setup):
    agents, tasks, coeffs, weights = setup
    result, _ = solve_greedy(agents, tasks, coeffs, weights, SolveOptions(budget=20.0))
    idx_of = {a.id: i for i, a in enumerate(agents)}
    id_of = {t.id: j for j, t in enumerate(tasks)}
    manual = sum(
        coeffs.c[idx_of[aid], id_of[tid]] for tid, aid in result.assignments.items()
    )
    assert result.metric.cost_total == pytest.approx(manual)


def test_amplify_without_token_returns_message(setup, monkeypatch):
    """トークン未設定なら Amplify を呼ばずクリーンなメッセージを返す。

    ``.env`` に実トークンがあっても、他のテスト（例: test_llm_decompose.py）が
    ``load_dotenv()`` を呼ぶと環境変数がプロセス全体に残り、このテストが
    実行順によって偽陽性で通ってしまう。明示的に unset して隔離する。
    """
    monkeypatch.delenv("FIXSTARS_AMPLIFY_TOKEN", raising=False)
    agents, tasks, coeffs, weights = setup
    result, msg = solve_amplify(
        agents, tasks, coeffs, weights, SolveOptions(), token=""
    )
    assert result is None
    assert "FIXSTARS_AMPLIFY_TOKEN" in msg


def test_dwave_without_token_returns_message(setup, monkeypatch):
    """D-Wave のトークン未設定時は SDK を呼ばず理由を返す。"""
    monkeypatch.delenv("DWAVE_API_TOKEN", raising=False)
    agents, tasks, coeffs, weights = setup
    result, msg = solve_dwave(agents, tasks, coeffs, weights, SolveOptions(), token="")
    assert result is None
    assert "DWAVE_API_TOKEN" in msg


def test_infeasible_budget_flagged(setup):
    agents, tasks, coeffs, weights = setup
    result, _ = solve_greedy(agents, tasks, coeffs, weights, SolveOptions(budget=0.5))
    # 予算 0.5 ドルでは全タスクを賄えない
    assert not result.metric.within_budget or result.metric.cost_total <= 0.5 + 1e-6


def test_decompose_fallback_without_llm():
    from taqumi2026s_teame.llm import decompose

    tasks, message = decompose("なんでもいい", use_llm=False)
    assert len(tasks) >= 3
    assert "サンプル" in message


# --- 画面2（モデル設定）のヘルパー -------------------------------------------
def test_model_setup_helpers(setup):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
    import ui_helpers as uh

    agents, tasks, _c, _w = setup
    matrix = uh.capability_matrix(agents)
    assert set(matrix) == {a.name for a in agents}
    sample = next(iter(matrix.values()))
    assert "repo_bug_fix_score" in sample and "input_price_per_1m" in sample
    assert "benchmark_scores" in sample and "sources" in sample

    # 全モデルなら被覆ギャップなし
    assert uh.coverage_gaps(tasks, agents) == []
    # 社外だけ選ぶと機密タスクが被覆できない
    external_only = [a for a in agents if a.external]
    if any(t.confidential for t in tasks):
        assert uh.coverage_gaps(tasks, external_only)

    floor = uh.min_cost_estimate(tasks, agents)
    assert floor is not None and floor > 0


def test_decompose_request_reports_that_llm_was_not_used(monkeypatch):
    """フォールバックを「成功」として表示しないための used_llm フラグ。"""
    from taqumi2026s_teame.llm import decompose_request

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    without_llm = decompose_request("なんでもいい", use_llm=False)
    assert without_llm.used_llm is False
    assert "サンプル" in without_llm.message

    # キーが無いのに LLM を要求した場合も、理由つきで used_llm=False になる
    asked_for_llm = decompose_request("なんでもいい", use_llm=True)
    assert asked_for_llm.used_llm is False
    assert "OPENAI_API_KEY" in asked_for_llm.message
