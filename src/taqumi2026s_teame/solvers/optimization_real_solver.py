"""「最適化実行」UI 用の Solver インターフェース（本実装）。

:mod:`optimization_mock_solver` と同じ ``OptimizationInput -> OptimizationResult``
シグネチャを保ったまま、内部で実際の QUBO パイプライン
（``build_coefficients`` → 選択されたソルバ → 結果整形）を呼び出す。

対応する式は C1（one-hot）・C2（能力なし/機密×社外の変数固定）・C3（予算上限）+
α・β・γ の目的関数（詳細は ``solvers/amplify_solver.py`` を参照）。
"""

from __future__ import annotations

import logging

from ..data import load_agents
from ..data.task_types import ROLES, plan_category_of
from ..models import Agent, SolveOptions, Task, Weights
from ..optimization_contract import (
    BaselineResult,
    OptimizationInput,
    OptimizationResult,
    TaskResult,
)
from ..qubo.coefficients import Coefficients, build_coefficients
from .amplify_solver import solve_amplify
from .classical import solve_greedy
from .dwave_solver import solve_dwave

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(levelname)s:%(name)s:%(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

_DEFAULT_ROLE = "code_gen"
# 契約 (optimization_contract.TaskResult) の accuracy_score は 0-5 スケール。
# 実測ベンチマーク品質 q_ij（0-1）を 5 倍して合わせる。
_ACCURACY_SCALE = 5.0
_DEFAULT_TIME_LIMIT_SEC = 3
_MAX_TIME_LIMIT_SEC = 30


def run_optimization(optimization_input: OptimizationInput) -> OptimizationResult:
    """最適化を実行する（UI から呼び出す唯一の入口・本実装）。

    Args:
        optimization_input (OptimizationInput): タスク・候補モデル・制約条件などの入力。

    Returns:
        OptimizationResult: 共通形式の最適化結果（status: success/error）。
            例外が発生した場合も status="error" として返し、呼び出し元を落とさない。
    """

    try:
        return _solve_real(optimization_input)
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


def _solve_real(optimization_input: OptimizationInput) -> OptimizationResult:
    """本実装の中心処理: 入力の検証 → QUBO 係数構築 → 求解 → 結果整形。

    Args:
        optimization_input (OptimizationInput): タスク・候補モデル・重み・
            予算上限などを含む最適化入力。

    Returns:
        OptimizationResult: status="success" の最適化結果（タスク別詳細・
            ベースライン比較を含む）。

    Raises:
        ValueError: タスクや候補モデルが空、または候補モデルが models.json の
            model_id と一つも一致しない場合。呼び出し元の :func:`run_optimization`
            がこの例外を捕捉し、status="error" として返す。
    """

    raw_tasks = optimization_input.get("tasks") or []
    candidate_models = optimization_input.get("candidate_models") or []
    if not raw_tasks:
        raise ValueError("タスクが指定されていません。")
    if not candidate_models:
        raise ValueError("候補モデルが指定されていません。")

    tasks = [_to_task(t) for t in raw_tasks]

    all_agents = {a.id: a for a in load_agents()}
    agents = [
        all_agents[model_id] for model_id in candidate_models if model_id in all_agents
    ]
    if not agents:
        raise ValueError("候補モデルが models.json と一致しません。")

    weights = _to_weights(optimization_input.get("optimization_weights") or {})
    # budget_limit は契約上必須の float（0 も有効値）。
    # 「0.0 or None」のような falsy 判定はしない（0円予算が無制約に化けてしまうため）。
    raw_budget = optimization_input.get("budget_limit")
    budget = None if raw_budget is None else float(raw_budget)
    options = SolveOptions(budget=budget)
    coeffs = build_coefficients(agents, tasks)

    time_limit_sec = _time_limit_sec(optimization_input.get("max_completion_time"))
    requested_solver = str(optimization_input.get("solver", "amplify")).lower()
    solver_name = (
        requested_solver
        if requested_solver in {"amplify", "dwave", "greedy"}
        else "amplify"
    )
    logger.info(
        "最適化を開始します（solver=%s, tasks=%d, agents=%d）。",
        solver_name,
        len(tasks),
        len(agents),
    )
    solver = {
        "amplify": solve_amplify,
        "dwave": solve_dwave,
        "greedy": solve_greedy,
    }[solver_name]
    solver_error = ""
    result, solver_msg = solver(
        agents, tasks, coeffs, weights, options, time_limit_sec=time_limit_sec
    )
    method_note = (
        "D-Wave Advantage（量子アニーリング）"
        if solver_name == "dwave"
        else (
            "Greedy（古典・貪欲法）"
            if solver_name == "greedy"
            else "Amplify AE（量子インスパイアード）"
        )
    )
    if result is None:
        solver_error = solver_msg
        logger.info("%s で解を取得できませんでした: %s", method_note, solver_msg)
        return {
            "status": "error",
            "optimal_assignment": {},
            "solve_time_seconds": 0.0,
            "total_cost": 0.0,
            "average_accuracy_score": 0.0,
            "message": (
                f"{method_note}で解を取得できませんでした。"
                f"他のソルバを試してください。理由: {solver_msg or '不明'}"
            ),
            "task_results": [],
            "solver_method": solver_name,
            "solver_error": solver_error,
        }
    logger.info("%s の求解が完了しました。", method_note)

    masking_enabled = bool(optimization_input.get("masking_enabled", False))
    task_results = _build_task_results(
        tasks, coeffs, agents, result.assignments, masking_enabled
    )
    avg_accuracy = (
        round(sum(t["accuracy_score"] for t in task_results) / len(task_results), 2)
        if task_results
        else 0.0
    )
    baseline = _build_baseline(tasks, agents, coeffs)

    message = f"{method_note}で最適化が完了しました。"
    if not result.metric.feasible:
        message += (
            " ただし、候補モデルの中に対応できないタスクがある等の理由で、"
            "一部の制約（能力・予算）を満たせていません。候補モデルや予算を見直してください。"
        )

    return {
        "status": "success",
        "optimal_assignment": dict(result.assignments),
        "solve_time_seconds": round(result.metric.solve_ms / 1000.0, 2),
        # 予算判定に使う値なので、表示より高い精度で返す（丸めで超過を見逃さない）。
        "total_cost": round(result.metric.cost_total, 4),
        "average_accuracy_score": avg_accuracy,
        "message": message,
        "task_results": task_results,
        "baseline": baseline,
        "feasible": bool(result.metric.feasible),
        "within_budget": bool(result.metric.within_budget),
        "violations": int(result.metric.violations),
        "solver_method": solver_name,
        "solver_error": solver_error,
    }


def _to_task(raw: object) -> Task:
    if not isinstance(raw, dict):
        raise TypeError("タスクの形式が不正です。")
    task_id = str(raw.get("task_id", "")).strip()
    if not task_id:
        raise ValueError("task_id が空のタスクがあります。")
    role = str(raw.get("task_type") or _DEFAULT_ROLE)
    if role not in ROLES:
        role = _DEFAULT_ROLE
    return Task(
        id=task_id,
        title=str(raw.get("task_name") or task_id),
        role=role,
        difficulty=_int_or(raw.get("difficulty"), 3),
        priority=_int_or(raw.get("importance"), 3),
        est_time=_float_or(raw.get("workload"), 2.0),
        dependencies=[str(x) for x in (raw.get("dependencies") or [])],
        confidential=bool(raw.get("is_confidential") or False),
        quantity=max(1, _int_or(raw.get("quantity"), 1)),
    )


def _int_or(value: object, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _float_or(value: object, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _to_weights(raw: dict[str, float]) -> Weights:
    """optimization_weights（alpha/beta/gamma/mu）を Weights へ変換する。

    欠けているキーは :class:`Weights` の既定値で補う。
    """

    defaults = Weights()
    return Weights(
        alpha=_float_or(raw.get("alpha"), defaults.alpha),
        beta=_float_or(raw.get("beta"), defaults.beta),
        gamma=_float_or(raw.get("gamma"), defaults.gamma),
        mu=_float_or(raw.get("mu"), defaults.mu),
    )


def _time_limit_sec(max_completion_time: object) -> int:
    """画面2の「最大完了時間」を Amplify の探索時間上限（秒）として流用する。

    C4（締切制約）としては使わない（今回のスコープ外）。「これだけ待てる」という
    値をそのまま Amplify のサーチ時間予算に転用する、という割り切り。
    """

    seconds = _float_or(max_completion_time, _DEFAULT_TIME_LIMIT_SEC)
    return int(min(_MAX_TIME_LIMIT_SEC, max(1, seconds)))


def _build_task_results(
    tasks: list[Task],
    coeffs: Coefficients,
    agents: list[Agent],
    assignments: dict[str, str],
    masking_enabled: bool,
) -> list[TaskResult]:
    agent_index = {a.id: i for i, a in enumerate(agents)}
    agents_by_id = {a.id: a for a in agents}
    task_index = {t.id: j for j, t in enumerate(tasks)}
    results: list[TaskResult] = []
    for task in tasks:
        model_id = assignments.get(task.id)
        if model_id is None or model_id not in agent_index:
            continue
        i, j = agent_index[model_id], task_index[task.id]
        quality = float(coeffs.q[i, j])
        accuracy = round(quality * _ACCURACY_SCALE, 2)
        results.append(
            {
                "task_id": task.id,
                "task_name": task.title,
                "selected_model": model_id,
                "masking_enabled": masking_enabled,
                "review_enabled": False,
                "review_model": None,
                # 予算判定は丸め前の値で行う（_solve_real 側）。ここは表示用に 4 桁。
                "cost": round(float(coeffs.c[i, j]), 4),
                "accuracy_score": accuracy,
                "accuracy_reason": (
                    f"{model_id} の実測ベンチマーク品質 {quality:.2f}（0-1 スケール）"
                    f"を基に {accuracy:.1f}/5.0 と評価。"
                ),
                "model_display_name": agents_by_id[model_id].name,
                "plan_category": plan_category_of(task.role),
                "quantity": max(1, int(task.quantity)),
            }
        )
    return results


def _build_baseline(
    tasks: list[Task], agents: list[Agent], coeffs: Coefficients
) -> BaselineResult:
    """全タスクを候補モデルの先頭 1 つだけに固定した場合の比較用ベースライン。"""

    if not agents or not tasks:
        return {"model": "-", "total_cost": 0.0, "average_accuracy_score": 0.0}
    baseline_model = agents[0].id
    total_cost = round(float(coeffs.c[0, :].sum()), 2)
    avg_accuracy = round(float(coeffs.q[0, :].mean()) * _ACCURACY_SCALE, 2)
    return {
        "model": baseline_model,
        "total_cost": total_cost,
        "average_accuracy_score": avg_accuracy,
    }
