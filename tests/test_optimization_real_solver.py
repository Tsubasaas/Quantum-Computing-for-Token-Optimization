"""「最適化実行」機能（本実装 optimization_real_solver）の正当性チェック。

注意: Greedy は optimization_mock_solver（ダミーの機械的な割当）とは無関係。
solve_greedy は q/c の実測ベンチマーク値を使い、Amplify と同じ目的関数
（α・β・γ）で解く本物の古典ヒューリスティックである。テストではソルバを
明示的に指定して実行する。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from taqumi2026s_teame.data import load_agents, load_sample_tasks
from taqumi2026s_teame.models import Agent, Task
from taqumi2026s_teame.optimization_contract import OptimizationInput
from taqumi2026s_teame.solvers.optimization_real_solver import run_optimization

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def _build_input(candidate_models: list[str], **overrides: object) -> OptimizationInput:
    tasks = load_sample_tasks()
    base: OptimizationInput = {
        "tasks": [
            {
                "task_id": t.id,
                "task_name": t.title,
                "task_type": t.role,
                "importance": t.priority,
                "difficulty": t.difficulty,
                "workload": t.est_time,
                "is_confidential": t.confidential,
                "dependencies": t.dependencies,
            }
            for t in tasks
        ],
        "candidate_models": candidate_models,
        "model_capability_matrix": {},
        "optimization_weights": {"alpha": 1.0, "beta": 0.4, "gamma": 1.0, "mu": 0.2},
        "budget_limit": 15.0,
        "max_completion_time": 3.0,
        "masking_enabled": False,
        "optimization_mode": "バランス",
        "solver": "greedy",
    }
    base.update(overrides)  # type: ignore[typeddict-item]
    return base


def _task_inputs(tasks: list[Task]) -> list[dict[str, object]]:
    return [
        {
            "task_id": task.id,
            "task_name": task.title,
            "task_type": task.role,
            "importance": task.priority,
            "difficulty": task.difficulty,
            "workload": task.est_time,
            "is_confidential": task.confidential,
            "dependencies": task.dependencies,
        }
        for task in tasks
    ]


def _compact_dwave_models(agents: list[Agent], count: int) -> list[str]:
    required = ["gpt_41", "nemotron_3_ultra", "midjourney_v6"]
    available = {agent.id for agent in agents}
    assert set(required) <= available
    return (
        required
        + [agent.id for agent in agents if agent.id not in required][: count - 3]
    )


def test_run_optimization_assigns_every_task_with_full_roster():
    """全モデルを候補にすれば、全カテゴリを覆えるので実行不能にならない。"""

    agents = load_agents()
    result = run_optimization(_build_input([a.id for a in agents]))

    assert result["status"] == "success"
    assert "一部の制約" not in result["message"]
    tasks = load_sample_tasks()
    assert len(result["optimal_assignment"]) == len(tasks)
    assert set(result["optimal_assignment"]) == {t.id for t in tasks}
    # 割り当てられたモデルは全て候補に含まれる
    assert set(result["optimal_assignment"].values()) <= {a.id for a in agents}


def test_run_optimization_reports_infeasible_when_category_uncovered():
    """画像生成タスクを担当できるモデルが候補に無ければ、実行不能の旨をメッセージに含める。"""

    agents = load_agents()
    non_image = [a.id for a in agents if a.capability.get("image_generation") is None]
    result = run_optimization(_build_input(non_image))

    assert result["status"] == "success"  # 契約上 success/timeout/error のみ
    assert "一部の制約" in result["message"]


def test_run_optimization_treats_zero_budget_as_real_constraint():
    """budget_limit=0.0 は「無制約」ではなく「0円予算」として扱う（Copilot指摘の回帰）。

    以前は `float(...) or None` により 0.0 が None（無制約）に化けていた。
    """

    agents = load_agents()
    result = run_optimization(_build_input([a.id for a in agents], budget_limit=0.0))

    assert result["status"] == "success"
    # 0円予算では実コストが発生する通常タスクを賄えないため、実行不能の注記が付く
    assert "一部の制約" in result["message"]
    assert result["total_cost"] >= 0.0


def test_run_optimization_rejects_empty_tasks_or_models():
    result = run_optimization(_build_input([], tasks=[]))
    assert result["status"] == "error"
    assert result["optimal_assignment"] == {}


def test_run_optimization_baseline_uses_first_candidate():
    agents = load_agents()
    candidate_ids = [a.id for a in agents]
    result = run_optimization(_build_input(candidate_ids))

    baseline = result["baseline"]
    assert baseline["model"] == candidate_ids[0]
    assert baseline["total_cost"] >= 0.0
    assert 0.0 <= baseline["average_accuracy_score"] <= 5.0


def test_run_optimization_accuracy_score_is_on_0_to_5_scale():
    agents = load_agents()
    result = run_optimization(_build_input([a.id for a in agents]))

    for task_result in result["task_results"]:
        assert 0.0 <= task_result["accuracy_score"] <= 5.0
    assert 0.0 <= result["average_accuracy_score"] <= 5.0


@pytest.mark.skipif(
    os.getenv("RUN_DWAVE_LIVE_TESTS") != "1",
    reason="実機 API テストは RUN_DWAVE_LIVE_TESTS=1 のときだけ実行します。",
)
def test_run_optimization_really_uses_dwave_with_three_tasks():
    """実機 D-Wave を選択した場合に D-Wave で求解することを確認する。

    Example:
        ``RUN_DWAVE_LIVE_TESTS=1`` で実行すると、solver_method が ``dwave`` になる。
    """
    agents = load_agents()
    candidate_models = _compact_dwave_models(agents, 3)
    selected_agents = [agent for agent in agents if agent.id in candidate_models]
    tasks = [
        task
        for task in load_sample_tasks()
        if any(
            agent.can_do(task.role) and not (task.confidential and agent.external)
            for agent in selected_agents
        )
    ][:3]
    result = run_optimization(
        _build_input(
            candidate_models,
            tasks=_task_inputs(tasks),
            solver="dwave",
            budget_limit=None,
        )
    )

    assert result["status"] == "success"
    assert result["solver_method"] == "dwave"


@pytest.mark.skipif(
    os.getenv("RUN_DWAVE_LIVE_TESTS") != "1",
    reason="実機 API テストは RUN_DWAVE_LIVE_TESTS=1 のときだけ実行します。",
)
def test_run_optimization_really_uses_dwave_with_fourteen_tasks():
    """14タスク・10モデルで D-Wave が求解できることを確認する。

    Example:
        ``RUN_DWAVE_LIVE_TESTS=1`` で実行すると、solver_method が ``dwave`` になる。
    """
    agents = load_agents()
    candidate_models = _compact_dwave_models(agents, 10)
    result = run_optimization(
        _build_input(
            candidate_models,
            solver="dwave",
            budget_limit=None,
        )
    )

    assert result["status"] == "success"
    assert result["solver_method"] == "dwave"
