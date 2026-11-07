"""「最適化実行」機能（Mock Solver）の基本的な正当性チェック。"""

from __future__ import annotations

from taqumi2026s_teame.data.mock_optimization_input import build_mock_optimization_input
from taqumi2026s_teame.models import Task
from taqumi2026s_teame.optimization_input_adapter import build_optimization_input
from taqumi2026s_teame.solvers.optimization_mock_solver import run_optimization


def test_mock_solver_task_accuracy_average_is_not_zero():
    """タスク別精度がある結果の平均値が0.00にならないことを確認する。"""

    result = run_optimization(build_mock_optimization_input())
    scores = [task["accuracy_score"] for task in result["task_results"]]

    assert sum(scores) / len(scores) > 0.0
    assert result["average_accuracy_score"] == round(sum(scores) / len(scores), 2)


def _upstream_state() -> dict[str, object]:
    """Adapterテスト用の上流session_stateを生成する。

    Returns:
        dict[str, object]: ページ2完了後を想定したsession_state。
    """

    return {
        "tasks": [Task(id="T001", title="要件整理", role="code_gen", priority=5)],
        "candidate_models": ["model-a", "model-b"],
        "model_capability_matrix": {
            "Model A": {"model_id": "model-a", "benchmark_cost_per_task": 0.8}
        },
        "optimization_weights": {"alpha": 1.0, "beta": 0.4, "gamma": 1.0, "mu": 0.2},
        "budget_limit": 12.5,
        "max_completion_time": None,
        "masking_enabled": True,
        "mode": "バランス",
    }


def test_adapter_uses_complete_upstream_state_without_reinterpreting_weights():
    """必須上流データが揃えば実データを返し、重みキーを保持することを確認する。

    Example:
        >>> result, is_upstream = build_optimization_input(_upstream_state())
        >>> is_upstream
        True
    """

    result, is_upstream = build_optimization_input(_upstream_state())

    assert is_upstream is True
    assert [task["task_id"] for task in result["tasks"]] == ["T001"]
    assert result["candidate_models"] == ["model-a", "model-b"]
    assert result["optimization_weights"] == {
        "alpha": 1.0,
        "beta": 0.4,
        "gamma": 1.0,
        "mu": 0.2,
    }
    assert result["budget_limit"] == 12.5
    assert result["max_completion_time"] is None
    assert result["optimization_mode"] == "バランス"


def test_adapter_falls_back_to_mock_when_upstream_state_is_incomplete():
    """必須上流データが不足する場合にMock入力へフォールバックすることを確認する。"""

    result, is_upstream = build_optimization_input({"tasks": []})

    assert is_upstream is False
    assert result == build_mock_optimization_input()


def test_mock_solver_accepts_none_completion_time():
    """上流のNone締切を保持した入力でもMock Solverが実行できることを確認する。"""

    optimization_input, _ = build_optimization_input(_upstream_state())

    result = run_optimization(optimization_input)

    assert result["status"] == "success"


def test_run_optimization_returns_success_with_mock_input():
    """Mock 入力に対して Mock Solver が success を返すことを確認する。

    Example:
        >>> result = run_optimization(build_mock_optimization_input())
        >>> result["status"]
        'success'
    """

    optimization_input = build_mock_optimization_input()
    result = run_optimization(optimization_input)

    assert result["status"] == "success"
    assert set(result["optimal_assignment"]) == {
        t["task_id"] for t in optimization_input["tasks"]
    }
    assert result["total_cost"] > 0
    assert result["average_accuracy_score"] > 0
    assert len(result["task_results"]) == len(optimization_input["tasks"])


def test_mock_solver_keeps_total_cost_within_budget():
    """タスク数が多くてもダミー結果の総コストが予算内に収まることを確認する。"""

    optimization_input = build_mock_optimization_input()
    optimization_input["budget_limit"] = 1.0

    result = run_optimization(optimization_input)

    assert result["status"] == "success"
    assert result["total_cost"] <= optimization_input["budget_limit"]
    assert sum(task["cost"] for task in result["task_results"]) == result["total_cost"]


def test_mock_solver_keeps_rounded_cost_within_tight_budget():
    """丸めによる超過が起きる小額予算でも上限を守ることを確認する。"""

    optimization_input = build_mock_optimization_input()
    optimization_input["budget_limit"] = 0.1

    result = run_optimization(optimization_input)

    assert result["total_cost"] <= 0.1
    assert sum(task["cost"] for task in result["task_results"]) <= 0.1


def test_mock_solver_accuracy_average_stays_between_zero_and_five():
    """ダミー結果の精度スコア（平均）が 0〜5 に収まることを確認する。"""

    result = run_optimization(build_mock_optimization_input())

    assert 0.0 <= result["average_accuracy_score"] <= 5.0
    assert 0.0 <= result["baseline"]["average_accuracy_score"] <= 5.0


def test_run_optimization_returns_error_when_tasks_empty():
    """タスクが空の場合に例外を握りつぶさず、status='error' を返すことを確認する。"""

    optimization_input = build_mock_optimization_input()
    optimization_input["tasks"] = []

    result = run_optimization(optimization_input)

    assert result["status"] == "error"
    assert result["message"]


def test_run_optimization_returns_timeout_when_time_limit_too_short():
    """max_completion_time が極端に短い場合に status='timeout' を返すことを確認する。"""

    optimization_input = build_mock_optimization_input()
    optimization_input["max_completion_time"] = 0.0

    result = run_optimization(optimization_input)

    assert result["status"] == "timeout"
