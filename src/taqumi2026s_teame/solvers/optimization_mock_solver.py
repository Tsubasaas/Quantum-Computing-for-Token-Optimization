"""「最適化実行」UI 用の Solver インターフェース（現時点は Mock 実装）。

``run_optimization()`` が UI と Solver/QUBO を繋ぐ唯一の接続点。
QUBO 担当は :func:`_solve_mock` の内部（または本モジュールを丸ごと差し替えた
Adapter）だけを本実装に置き換えれば、UI 側のコードは変更不要で接続できる。
"""

from __future__ import annotations

import logging
import time

from ..optimization_contract import (
    BaselineResult,
    OptimizationInput,
    OptimizationResult,
    TaskResult,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(levelname)s:%(name)s:%(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)


def run_optimization(optimization_input: OptimizationInput) -> OptimizationResult:
    """最適化を実行する（UI から呼び出す唯一の入口）。

    現時点では Mock Solver で実装している。将来 QUBO/量子ソルバへ差し替える際は、
    この関数のシグネチャ（``OptimizationInput -> OptimizationResult``）を維持したまま
    内部実装だけを置き換えればよい。

    Args:
        optimization_input (OptimizationInput): タスク・候補モデル・制約条件などの入力。

    Returns:
        OptimizationResult: 共通形式の最適化結果（status: success/timeout/error）。
            例外が発生した場合も status="error" として返し、呼び出し元を落とさない。

    Example:
        >>> from taqumi2026s_teame.data.mock_optimization_input import build_mock_optimization_input
        >>> result = run_optimization(build_mock_optimization_input())
        >>> result["status"] in {"success", "timeout", "error"}
        True
    """

    try:
        return _solve_mock(optimization_input)
    except Exception as exc:  # noqa: BLE001  (UI 全体を落とさないため広く捕捉して返す)
        logger.exception("最適化実行中に例外が発生しました。")
        return {
            "status": "error",
            "optimal_assignment": {},
            "solve_time_seconds": 0.0,
            "total_cost": 0.0,
            "average_accuracy_score": 0.0,
            "message": f"最適化中にエラーが発生しました: {exc}",
            "task_results": [],
        }


def _solve_mock(optimization_input: OptimizationInput) -> OptimizationResult:
    """Mock Solver 本体。QUBO 担当が本実装に差し替える対象。

    Args:
        optimization_input (OptimizationInput): 最適化の入力。

    Returns:
        OptimizationResult: Mock による最適化結果。
    """

    tasks = optimization_input.get("tasks") or []
    candidate_models = optimization_input.get("candidate_models") or []
    if not tasks:
        raise ValueError("タスクが指定されていません。")
    if not candidate_models:
        raise ValueError("候補モデルが指定されていません。")

    masking_enabled = bool(optimization_input.get("masking_enabled", False))
    budget_limit = max(0.0, float(optimization_input.get("budget_limit", 0.0)))
    raw_max_completion_time = optimization_input.get("max_completion_time")
    max_completion_time = (
        30.0 if raw_max_completion_time is None else float(raw_max_completion_time)
    )

    start = time.perf_counter()
    # ダミーの想定計算時間（タスク数 x 候補モデル数に比例。実求解ではない）
    estimated_time = round(0.05 * len(tasks) * len(candidate_models) + 0.2, 2)
    time.sleep(min(0.5, estimated_time))  # スピナー確認用の疑似待機
    solve_time = round(time.perf_counter() - start, 2)

    if estimated_time > max_completion_time:
        logger.info("Mock Solver: 制限時間超過のため timeout を返却します。")
        return {
            "status": "timeout",
            "optimal_assignment": {},
            "solve_time_seconds": solve_time,
            "total_cost": 0.0,
            "average_accuracy_score": 0.0,
            "message": "制限時間内に終了しなかったため、探索を打ち切りました。",
            "task_results": [],
        }

    assignment: dict[str, str] = {}
    task_results: list[TaskResult] = []
    total_cost = 0.0
    total_accuracy = 0.0
    baseline_cost = 0.0
    baseline_accuracy = 0.0
    for idx, task in enumerate(tasks):
        model_index = idx % len(candidate_models)
        model = candidate_models[model_index]
        cost = round(0.5 + 0.3 * model_index, 2)
        accuracy = round(3.5 + 0.3 * (model_index + 1), 2)
        baseline_cost += 0.5
        baseline_accuracy += 3.8
        assignment[task["task_id"]] = model
        total_cost += cost
        total_accuracy += accuracy
        task_results.append(
            {
                "task_id": task["task_id"],
                "task_name": task.get("task_name", ""),
                "selected_model": model,
                "masking_enabled": masking_enabled,
                "review_enabled": False,
                "review_model": None,
                "cost": cost,
                "accuracy_score": accuracy,
                "accuracy_reason": (
                    f"{model} のタスク適性スコアを基に {accuracy:.1f}/5.0 と評価。"
                ),
            }
        )

    scaled_costs = [
        task_result["cost"] * _cost_scale(total_cost, budget_limit)
        for task_result in task_results
    ]
    fitted_costs = _fit_costs_to_budget(scaled_costs, budget_limit)
    for task_result, cost in zip(task_results, fitted_costs, strict=True):
        task_result["cost"] = cost
    total_cost = round(sum(task_result["cost"] for task_result in task_results), 2)

    baseline_raw_cost = baseline_cost
    baseline_cost = round(
        baseline_raw_cost * _cost_scale(baseline_raw_cost, budget_limit), 2
    )
    baseline: BaselineResult = {
        "model": candidate_models[0],
        "total_cost": round(baseline_cost, 2),
        "average_accuracy_score": round(baseline_accuracy / len(tasks), 2),
    }
    return {
        "status": "success",
        "optimal_assignment": assignment,
        "solve_time_seconds": solve_time,
        "total_cost": total_cost,
        "average_accuracy_score": round(total_accuracy / len(tasks), 2),
        "message": "最適化が正常に完了しました。",
        "task_results": task_results,
        "baseline": baseline,
    }


def _cost_scale(total_cost: float, budget_limit: float) -> float:
    """ダミーコストを予算内へ収める比例係数を返す。

    Args:
        total_cost (float): 縮小前の合計コスト。
        budget_limit (float): 設定された予算上限。

    Returns:
        float: 0.0〜1.0 の比例係数。
    """
    if total_cost <= 0.0 or total_cost <= budget_limit:
        return 1.0
    return budget_limit / total_cost


def _fit_costs_to_budget(costs: list[float], budget_limit: float) -> list[float]:
    """丸め後のタスクコスト合計を予算内へ収める。

    Args:
        costs (list[float]): 比例縮小後のタスク別コスト。
        budget_limit (float): 設定された予算上限。

    Returns:
        list[float]: セント単位で予算内に収まるタスク別コスト。
    """
    budget_cents = max(0, int(budget_limit * 100 + 1e-9))
    cost_cents = [max(0, int(cost * 100 + 0.5)) for cost in costs]
    excess = sum(cost_cents) - budget_cents
    while excess > 0 and cost_cents:
        largest_index = max(range(len(cost_cents)), key=cost_cents.__getitem__)
        reduction = min(excess, cost_cents[largest_index])
        cost_cents[largest_index] -= reduction
        excess -= reduction
    return [round(cents / 100, 2) for cents in cost_cents]
