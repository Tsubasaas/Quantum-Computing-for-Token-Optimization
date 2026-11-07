"""ワークスペース（要望 → タスク → 3プラン）の受け入れ条件テスト。

UI 実装プロンプト §11「機能」の受け入れ条件を、UI を起動せずに検証する。

本モジュールは全体が生成 AI（Claude）支援で作成されています。
"""

from __future__ import annotations

import itertools

import pytest

from taqumi2026s_teame.data import load_agents, load_models
from taqumi2026s_teame.data.task_types import (
    PLAN_CATEGORIES,
    ROLE_PLAN_CATEGORY,
    ROLES,
    difficulty_label,
    plan_category_of,
)
from taqumi2026s_teame.models import Task
from taqumi2026s_teame.planner import plan_tasks, prune_dependencies, renumber
from taqumi2026s_teame.plans import Plan, _judge, build_plans, identical_plan_kinds
from taqumi2026s_teame.workflow import dependency_errors, levels

REQUEST = (
    "売上管理アプリをつくりたい。提案書と利用ガイド、"
    "売上登録・月別集計・ダッシュボード・CSV出力、紹介画像と告知バナーも準備したい。"
)


@pytest.fixture(scope="module")
def model_ids() -> list[str]:
    return [a.id for a in load_agents()]


@pytest.fixture(scope="module")
def image_capable_ids() -> set[str]:
    return {
        m["model_id"]
        for m in load_models()
        if m.get("capability", {}).get("image_generation") is not None
    }


# --------------------------------------------------------------------------- #
# カテゴリ写像
# --------------------------------------------------------------------------- #
def test_every_role_maps_to_a_plan_category():
    """ROLES の取りこぼしがあると、そのタスクが画面から消える。"""

    assert set(ROLES) == set(ROLE_PLAN_CATEGORY)
    assert set(ROLE_PLAN_CATEGORY.values()) <= set(PLAN_CATEGORIES)


def test_difficulty_label_covers_full_range():
    assert [difficulty_label(d) for d in range(1, 6)] == [
        "軽量",
        "軽量",
        "標準",
        "標準",
        "複雑",
    ]


# --------------------------------------------------------------------------- #
# タスク分解（§11: 3カテゴリの単独・複合選択 全7通りで破綻しない）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "categories",
    [
        list(combo)
        for size in (1, 2, 3)
        for combo in itertools.combinations(PLAN_CATEGORIES, size)
    ],
)
def test_all_seven_category_combinations_produce_valid_tasks(categories):
    result = plan_tasks(REQUEST, categories)
    tasks = result.tasks

    assert tasks, "タスクが 1 件も作られていない"
    # 選んだカテゴリだけが含まれる
    assert {plan_category_of(t.role) for t in tasks} == set(categories)
    # 選ばなかったカテゴリのタスクへ依存していない（§11: 存在しない文書タスクに依存しない）
    assert not dependency_errors(tasks)
    known = {t.id for t in tasks}
    for task in tasks:
        assert set(task.dependencies) <= known
    # ID は T001 から連番
    assert [t.id for t in tasks] == [f"T{i:03d}" for i in range(1, len(tasks) + 1)]


def test_dropping_doc_category_removes_dangling_prerequisites():
    with_doc = plan_tasks(REQUEST, ["doc", "code"]).tasks
    without_doc = plan_tasks(REQUEST, ["code"]).tasks

    # 文書ありでは設計タスクに前提があり、文書なしでは前提が消える
    design_with = next(t for t in with_doc if "設計" in t.title)
    design_without = next(t for t in without_doc if "設計" in t.title)
    assert design_with.dependencies
    assert design_without.dependencies == []


def test_empty_request_and_no_category_are_rejected():
    with pytest.raises(ValueError):
        plan_tasks("", ["doc"])
    with pytest.raises(ValueError):
        plan_tasks(REQUEST, [])


def test_request_keywords_add_related_tasks():
    plain = plan_tasks("社内向けの小さなツールをつくりたい。", ["code"]).tasks
    with_csv = plan_tasks("社内向けツール。CSV出力と認証も要る。", ["code"]).tasks

    assert len(with_csv) > len(plain)
    assert any("CSV" in t.title for t in with_csv)
    # 認証タスクは機密扱い（社外モデルへ割当不可）
    assert any(t.confidential for t in with_csv)
    assert not any(t.confidential for t in plain)


# --------------------------------------------------------------------------- #
# 依存関係
# --------------------------------------------------------------------------- #
def test_prune_dependencies_drops_unknown_self_and_cycles():
    tasks = [
        Task(id="T001", title="a", role="code_gen", dependencies=["T001", "T999"]),
        Task(id="T002", title="b", role="code_gen", dependencies=["T001", "T003"]),
        Task(id="T003", title="c", role="code_gen", dependencies=["T002"]),
    ]
    prune_dependencies(tasks)

    assert tasks[0].dependencies == []
    assert tasks[1].dependencies == ["T001"]  # 循環になる T003 を落とす
    assert tasks[2].dependencies == ["T002"]
    assert not dependency_errors(tasks)


def test_levels_group_parallel_tasks_and_respect_order():
    tasks = [
        Task(id="T001", title="a", role="code_gen"),
        Task(id="T002", title="b", role="code_gen", dependencies=["T001"]),
        Task(id="T003", title="c", role="code_gen", dependencies=["T001"]),
        Task(id="T004", title="d", role="code_gen", dependencies=["T002", "T003"]),
    ]
    assert levels(tasks) == [["T001"], ["T002", "T003"], ["T004"]]
    assert levels([]) == []


def test_dependency_errors_detects_cycle_and_missing():
    cyclic = [
        Task(id="T001", title="a", role="code_gen", dependencies=["T002"]),
        Task(id="T002", title="b", role="code_gen", dependencies=["T001"]),
    ]
    assert dependency_errors(cyclic)
    # 循環していても段分けは止まらない（全件がどこかの段に現れる）
    assert sorted(sum(levels(cyclic), [])) == ["T001", "T002"]

    missing = [Task(id="T001", title="a", role="code_gen", dependencies=["T999"])]
    assert any("T999" in message for message in dependency_errors(missing))


def test_renumber_rewrites_ids_and_references():
    tasks = [
        Task(id="X", title="a", role="code_gen"),
        Task(id="Y", title="b", role="code_gen", dependencies=["X"]),
    ]
    renumber(tasks)
    assert [t.id for t in tasks] == ["T001", "T002"]
    assert tasks[1].dependencies == ["T001"]


# --------------------------------------------------------------------------- #
# 3 プラン（§11: 予算・画像モデル・内訳の一致）
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def sample_plans(model_ids):
    tasks = plan_tasks(REQUEST, list(PLAN_CATEGORIES)).tasks
    return tasks, build_plans(tasks, model_ids, 15.0, solver="greedy")


def test_three_plans_use_budget_slices(sample_plans):
    _, plans = sample_plans
    assert [p.kind for p in plans] == ["cost", "balanced", "quality"]
    assert [p.budget_cap for p in plans] == [4.5, 9.0, 15.0]


def test_build_plans_works_with_usable_model_pool_only():
    """ワークスペースの既定（旧バージョン等を除いた候補）でも編成が組めること。"""

    tasks = plan_tasks(REQUEST, list(PLAN_CATEGORIES)).tasks
    usable_ids = [a.id for a in load_agents(only_usable=True)]
    plans = build_plans(tasks, usable_ids, 15.0, solver="greedy")
    assert [p.kind for p in plans] == ["cost", "balanced", "quality"]
    assert any(p.feasible for p in plans)


def test_feasible_plans_stay_within_their_budget_cap(sample_plans):
    _, plans = sample_plans
    for plan in plans:
        if plan.feasible:
            assert plan.total_cost <= plan.budget_cap + 1e-6


def test_plan_total_matches_task_breakdown(sample_plans):
    _, plans = sample_plans
    for plan in plans:
        breakdown = sum(float(r["cost"]) for r in plan.result.get("task_results", []))
        assert plan.total_cost == pytest.approx(breakdown, abs=1e-4)
        by_category = sum(plan.cost_by_category.values())
        assert plan.total_cost == pytest.approx(by_category, abs=1e-4)


def test_image_tasks_only_go_to_image_capable_models(sample_plans, image_capable_ids):
    tasks, plans = sample_plans
    by_id = {t.id: t for t in tasks}
    for plan in plans:
        for task_id, model_id in plan.assignment.items():
            if plan_category_of(by_id[task_id].role) == "image":
                assert model_id in image_capable_ids


def test_image_count_change_recomputes_image_cost(model_ids):
    tasks = plan_tasks(REQUEST, ["image"]).tasks
    before = build_plans(tasks, model_ids, 15.0, solver="greedy")
    for task in tasks:
        task.quantity *= 3
    after = build_plans(tasks, model_ids, 15.0, solver="greedy")

    assert after[0].image_count == before[0].image_count * 3
    # コスト重視は同じモデルに張り付くので、枚数ぶんそのまま増える
    assert after[0].image_cost > before[0].image_cost


def test_tiny_budget_is_over_budget_not_runnable(model_ids):
    """総予算でも足りない案は over_budget。実行させず、不足額を出せる状態にする。"""

    tasks = plan_tasks(REQUEST, list(PLAN_CATEGORIES)).tasks
    plans = build_plans(tasks, model_ids, 0.02, solver="greedy")

    assert all(p.status == "over_budget" for p in plans)
    assert all("予算" in p.infeasible_reason for p in plans)
    # 割当そのものは付いている（予算だけが問題）
    assert all(len(p.assignment) == len(tasks) for p in plans)
    assert all(not p.runnable for p in plans)
    for plan in plans:
        assert plan.total_budget == pytest.approx(0.02)
        assert plan.shortfall == pytest.approx(plan.total_cost - 0.02, abs=1e-4)
        assert plan.shortfall > 0


def _fake_plan(*, cost: float, cap: float, budget: float, violations: int = 0) -> Plan:
    """`_judge` の状態遷移だけを見るための、求解器を通さないプラン。

    実ソルバーは確率的で、同じ入力でも費用が毎回わずかに変わる。状態の切り分けは
    金額と件数だけで決まるので、ここは求解結果を固定して決定的に検証する。
    """

    plan = Plan(
        kind="cost",
        label="コスト重視",
        budget_cap=cap,
        result={
            "status": "success",
            "optimal_assignment": {"T1": "m1"},
            "total_cost": cost,
            "violations": violations,
            "feasible": violations == 0 and cost <= cap + 1e-6,
            "within_budget": cost <= cap + 1e-6,
        },
        status="unavailable",
        total_budget=budget,
    )
    plan.total_cost = cost
    return plan


@pytest.mark.parametrize(
    ("cost", "cap", "budget", "violations", "expected", "runnable"),
    [
        (0.10, 0.18, 0.60, 0, "feasible", True),
        # 目安上限だけ超過。総予算には収まるので実行できる。
        (0.21, 0.18, 0.60, 0, "over_cap", True),
        # 総予算でも足りない。
        (0.72, 0.18, 0.60, 0, "over_budget", False),
        # 予算では直らない不可。金額に関係なく実行不能。
        (0.10, 0.18, 0.60, 1, "unavailable", False),
    ],
)
def test_judge_splits_budget_causes_from_other_causes(
    cost, cap, budget, violations, expected, runnable
):
    """予算が原因の不可と、予算では直らない不可を混同しない（仕様 §4.D）。"""

    tasks = [Task(id="T1", title="要件定義", role="doc_requirements")]
    plan = _fake_plan(cost=cost, cap=cap, budget=budget, violations=violations)
    _judge(plan, tasks)

    assert plan.status == expected
    assert plan.runnable is runnable
    # 予算では直らない不可のときだけ、金額ではなく理由文を出す。
    assert (plan.infeasible_reason != "") is (expected in ("over_budget", "unavailable"))


def test_overrun_and_shortfall_are_independent():
    """超過額は目安上限に対して、不足額は総予算に対して測る。"""

    over_cap = _fake_plan(cost=0.21, cap=0.18, budget=0.60)
    assert over_cap.overrun == pytest.approx(0.03)
    assert over_cap.shortfall == 0.0

    over_budget = _fake_plan(cost=0.72, cap=0.18, budget=0.60)
    assert over_budget.overrun == pytest.approx(0.54)
    assert over_budget.shortfall == pytest.approx(0.12)


def test_build_plans_rejects_empty_input(model_ids):
    with pytest.raises(ValueError):
        build_plans([], model_ids, 10.0)
    with pytest.raises(ValueError):
        build_plans(plan_tasks(REQUEST, ["doc"]).tasks, [], 10.0)


def test_identical_plans_are_reported_not_faked(model_ids):
    """同じ配分になったプランは、差があるように見せず同一として報告する。"""

    tasks = plan_tasks("小さなメモを書きたい。", ["doc"]).tasks
    # 予算を十分大きく取ると 3 案とも同じ最良構成へ収束しやすい
    plans = build_plans(tasks, model_ids, 400.0, solver="greedy")
    groups = identical_plan_kinds(plans)

    for group in groups:
        signatures = {
            tuple(sorted(p.assignment.items())) for p in plans if p.kind in group
        }
        assert len(signatures) == 1
