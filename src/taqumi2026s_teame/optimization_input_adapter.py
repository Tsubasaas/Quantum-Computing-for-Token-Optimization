"""上流の session_state を最適化実行 UI の入力契約へ変換する。"""

from __future__ import annotations

from collections.abc import Mapping
from numbers import Real
from typing import cast

from .data.mock_optimization_input import build_mock_optimization_input
from .models import Task
from .optimization_contract import OptimizationInput, TaskInput

_REQUIRED_KEYS = (
    "tasks",
    "candidate_models",
    "model_capability_matrix",
    "optimization_weights",
    "budget_limit",
    "max_completion_time",
    "masking_enabled",
)


def build_optimization_input(
    session_state: Mapping[str, object],
) -> tuple[OptimizationInput, bool]:
    """上流の session_state から最適化入力を作成する。

    Args:
        session_state (Mapping[str, object]): Streamlit の session_state。

    Returns:
        tuple[OptimizationInput, bool]: 最適化入力と、上流実データを使ったかどうか。
    """

    if not _has_complete_upstream_data(session_state):
        return build_mock_optimization_input(), False

    return _from_upstream_state(session_state), True


def _has_complete_upstream_data(session_state: Mapping[str, object]) -> bool:
    """上流入力が Adapter で扱える状態か判定する。

    Args:
        session_state (Mapping[str, object]): Streamlit の session_state。

    Returns:
        bool: 必須データが揃っていれば True。
    """

    if any(key not in session_state for key in _REQUIRED_KEYS):
        return False

    tasks = session_state["tasks"]
    candidate_models = session_state["candidate_models"]
    matrix = session_state["model_capability_matrix"]
    weights = session_state["optimization_weights"]
    budget = session_state["budget_limit"]
    max_time = session_state["max_completion_time"]
    masking = session_state["masking_enabled"]
    mode = session_state.get("mode", session_state.get("optimization_mode"))

    return (
        isinstance(tasks, list)
        and bool(tasks)
        and isinstance(candidate_models, list)
        and bool(candidate_models)
        and all(isinstance(model, str) and model for model in candidate_models)
        and isinstance(matrix, dict)
        and bool(matrix)
        and all(isinstance(value, dict) for value in matrix.values())
        and isinstance(weights, dict)
        and all(
            isinstance(value, Real) and not isinstance(value, bool)
            for value in weights.values()
        )
        and isinstance(budget, Real)
        and not isinstance(budget, bool)
        and (
            max_time is None
            or (isinstance(max_time, Real) and not isinstance(max_time, bool))
        )
        and isinstance(masking, bool)
        and isinstance(mode, str)
        and bool(mode)
    )


def _from_upstream_state(session_state: Mapping[str, object]) -> OptimizationInput:
    """上流session_stateを契約形式へ変換する。

    Args:
        session_state (Mapping[str, object]): 必須データが揃った上流の session_state。

    Returns:
        OptimizationInput: 上流値を保持した最適化入力。
    """

    raw_tasks = cast("list[object]", session_state["tasks"])
    raw_models = cast("list[object]", session_state["candidate_models"])
    raw_matrix = cast("dict[object, object]", session_state["model_capability_matrix"])
    raw_weights = cast("dict[object, object]", session_state["optimization_weights"])
    raw_max_time = session_state["max_completion_time"]
    mode = session_state.get("mode", session_state.get("optimization_mode"))

    return {
        "tasks": [_to_task_input(task) for task in raw_tasks],
        "candidate_models": [str(model) for model in raw_models],
        "model_capability_matrix": {
            str(model): dict(cast("Mapping[str, object]", values))
            for model, values in raw_matrix.items()
        },
        "optimization_weights": {
            str(key): _as_float(value) for key, value in raw_weights.items()
        },
        "budget_limit": float(cast("Real", session_state["budget_limit"])),
        "max_completion_time": (
            None if raw_max_time is None else float(cast("Real", raw_max_time))
        ),
        "masking_enabled": bool(session_state["masking_enabled"]),
        "optimization_mode": str(mode),
        "solver": str(session_state.get("solver", "amplify")),
    }


def _as_float(value: object) -> float:
    """入力値を浮動小数点数へ変換する。

    Args:
        value (object): 変換対象の値。

    Returns:
        float: 変換後の数値。

    Raises:
        TypeError: 数値へ変換できない値の場合。
    """
    if isinstance(value, (int, float, str)):
        return float(value)
    raise TypeError(f"数値に変換できない値です: {value!r}")


def _to_task_input(task: object) -> TaskInput:
    """上流のTaskを契約用の辞書へ変換する。

    Args:
        task (object): ``Task`` dataclassまたはタスク辞書。

    Returns:
        TaskInput: Task ID・名前と、利用可能な上流属性を含む辞書。

    Raises:
        ValueError: Task IDまたはTask名が取得できない場合。
        TypeError: 対応していないTask型の場合。
    """

    if isinstance(task, Task):
        return {
            "task_id": task.id,
            "task_name": task.title,
            "task_type": task.role,
            "importance": task.priority,
            "difficulty": task.difficulty,
            "workload": task.est_time,
            "is_confidential": task.confidential,
            "dependencies": list(task.dependencies),
        }

    if isinstance(task, Mapping):
        task_id = str(task.get("task_id", "")).strip()
        task_name = str(task.get("task_name", "")).strip()
        if not task_id or not task_name:
            raise ValueError("Task IDとTask名は必須です。")
        return {
            "task_id": task_id,
            "task_name": task_name,
            "task_type": task.get("task_type"),
            "importance": task.get("importance"),
            "difficulty": task.get("difficulty"),
            "workload": task.get("workload"),
            "is_confidential": task.get("is_confidential"),
            "dependencies": task.get("dependencies"),
            "reference_file_name": task.get("reference_file_name"),
        }

    raise TypeError("対応していないTask型です。")
