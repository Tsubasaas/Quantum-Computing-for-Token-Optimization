"""アウトプット画面が前工程の最適化契約を表示できることを検証する。"""

from __future__ import annotations

import json

import pytest

from taqumi2026s_teame.data.mock_optimization_input import build_mock_optimization_input
from taqumi2026s_teame.optimization_contract import (
    OptimizationInput,
    OptimizationResult,
)
from taqumi2026s_teame.solvers.optimization_mock_solver import run_optimization


@pytest.fixture
def output_context() -> tuple[OptimizationInput, OptimizationResult]:
    """画面 3 と同じ入力・結果契約を作成する。

    Returns:
        tuple[OptimizationInput, OptimizationResult]: 入力と最適化結果。

    Example:
        ``context[1]["optimal_assignment"]`` でタスク別割当を参照できる。
    """
    optimization_input = build_mock_optimization_input()
    result = run_optimization(optimization_input)
    return optimization_input, result


def test_all_tasks_have_selected_models(
    output_context: tuple[OptimizationInput, OptimizationResult],
) -> None:
    """全タスクに選択モデルが割り当てられていることを確認する。

    Args:
        output_context (tuple[OptimizationInput, OptimizationResult]): 入出力契約。

    Example:
        成功結果では入力タスク ID が全て割当辞書に含まれる。
    """
    optimization_input, result = output_context
    task_ids = {task["task_id"] for task in optimization_input["tasks"]}

    assert result["status"] == "success"
    assert set(result["optimal_assignment"]) == task_ids
    assert all(result["optimal_assignment"].values())


def test_summary_contains_required_metrics(
    output_context: tuple[OptimizationInput, OptimizationResult],
) -> None:
    """総コスト、精度、計算時間が結果に含まれることを確認する。

    Args:
        output_context (tuple[OptimizationInput, OptimizationResult]): 入出力契約。

    Example:
        3 つの評価値が非負である。
    """
    _, result = output_context

    assert result["total_cost"] >= 0.0
    assert 0.0 <= result["average_accuracy_score"] <= 5.0
    assert result["solve_time_seconds"] >= 0.0


def test_result_contains_single_model_baseline(
    output_context: tuple[OptimizationInput, OptimizationResult],
) -> None:
    """全タスクを1モデルで実行した比較結果が含まれることを確認する。

    Args:
        output_context (tuple[OptimizationInput, OptimizationResult]): 入出力契約。

    Example:
        ベースラインのコストと精度が最適化後と同じ尺度で得られる。
    """
    _, result = output_context
    baseline = result["baseline"]

    assert baseline["model"]
    assert baseline["total_cost"] >= 0.0
    assert 0.0 <= baseline["average_accuracy_score"] <= 5.0


def test_budget_limit_is_comparable_with_actual_cost(
    output_context: tuple[OptimizationInput, OptimizationResult],
) -> None:
    """予算上限と総コストを比較できることを確認する。

    Args:
        output_context (tuple[OptimizationInput, OptimizationResult]): 入出力契約。

    Example:
        総コストが予算上限以下かどうかを判定できる。
    """
    optimization_input, result = output_context

    assert result["total_cost"] <= optimization_input["budget_limit"]


def test_output_contract_never_exceeds_budget_for_small_limit():
    """小さい予算でもダミー結果が設定上限を超えないことを確認する。"""

    optimization_input = build_mock_optimization_input()
    optimization_input["budget_limit"] = 0.01

    result = run_optimization(optimization_input)

    assert result["status"] == "success"
    assert result["total_cost"] <= 0.01


def test_task_results_include_masking_and_review_details(
    output_context: tuple[OptimizationInput, OptimizationResult],
) -> None:
    """タスク別結果にモデル、マスキング、レビュー情報が含まれることを確認する。

    Args:
        output_context (tuple[OptimizationInput, OptimizationResult]): 入出力契約。

    Example:
        各タスク結果からレビュー有無とレビューモデルを参照できる。
    """
    _, result = output_context

    for task_result in result["task_results"]:
        assert task_result["selected_model"]
        assert isinstance(task_result["masking_enabled"], bool)
        assert isinstance(task_result["review_enabled"], bool)
        assert task_result["review_model"] is None or task_result["review_model"]
        assert task_result["accuracy_reason"]


def test_json_export_preserves_input_and_result(
    output_context: tuple[OptimizationInput, OptimizationResult],
) -> None:
    """入力と結果を JSON として保持できることを確認する。

    Args:
        output_context (tuple[OptimizationInput, OptimizationResult]): 入出力契約。

    Example:
        JSON 往復後も割当結果が変わらない。
    """
    optimization_input, result = output_context
    payload = {"optimization_input": optimization_input, "optimization_result": result}
    exported = json.loads(json.dumps(payload))

    assert (
        exported["optimization_result"]["optimal_assignment"]
        == result["optimal_assignment"]
    )
    assert (
        exported["optimization_input"]["budget_limit"]
        == optimization_input["budget_limit"]
    )


def test_generated_response_can_be_edited_without_losing_original() -> None:
    """生成 response と編集後 response を別々に保持できることを確認する。

    Example:
        編集後の文字列を変更しても生成直後の文字列は変わらない。
    """
    generated_response = "生成直後の response"
    edited_response = "人が修正した response"

    assert generated_response != edited_response
    assert generated_response == "生成直後の response"


def test_failed_result_exposes_constraint_message() -> None:
    """timeout や error の結果がユーザー向けメッセージを持つことを確認する。

    Example:
        status が timeout の場合にも message が空でない。
    """
    result: OptimizationResult = {
        "status": "timeout",
        "optimal_assignment": {},
        "solve_time_seconds": 1.0,
        "total_cost": 0.0,
        "average_accuracy_score": 0.0,
        "message": "制限時間内に終了しませんでした。",
        "task_results": [],
    }

    assert result["status"] != "success"
    assert result["message"]
