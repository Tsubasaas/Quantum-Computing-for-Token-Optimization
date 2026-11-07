"""Amplify の DWaveSamplerClient による D-Wave Advantage 求解。"""

from __future__ import annotations

import logging
import os
import time

import numpy as np

from ..evaluation.metrics import evaluate_assignment
from ..models import Agent, AssignmentResult, SolveOptions, Task, Weights
from ..qubo.coefficients import Coefficients

_METHOD = "D-Wave Advantage（量子アニーリング）"
_TOKEN_ENV = "DWAVE_API_TOKEN"

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(levelname)s:%(name)s:%(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)


def solve_dwave(
    agents: list[Agent],
    tasks: list[Task],
    coeffs: Coefficients,
    weights: Weights,
    options: SolveOptions,
    *,
    time_limit_sec: int = 3,
    token: str | None = None,
    seed: int = 0,
) -> tuple[AssignmentResult | None, str]:
    """Amplify 経由で D-Wave Advantage に割当 QUBO を送信する。

    Args:
        agents (list[Agent]): 割当候補のモデル一覧。
        tasks (list[Task]): 割当対象タスク一覧。
        coeffs (Coefficients): 品質・コストなどの QUBO 係数。
        weights (Weights): 目的関数の重み。
        options (SolveOptions): 予算などの制約設定。
        time_limit_sec (int): D-Wave への読み出し回数を決める時間の目安（秒）。
        token (str | None): D-Wave API トークン。省略時は環境変数を使う。
        seed (int): 互換性のための乱数シード。D-Wave 実機では使用しない。

    Returns:
        tuple[AssignmentResult | None, str]: 求解結果と、求解できない場合の理由。
    """
    del seed
    token = token or os.getenv(_TOKEN_ENV)
    if not token:
        logger.warning("D-Wave: %s が未設定のため実行をスキップします。", _TOKEN_ENV)
        return (
            None,
            f"{_TOKEN_ENV} が未設定です。",
        )

    try:
        from amplify import (
            DWaveSamplerClient,
            Model,
            VariableGenerator,
            less_equal,
            one_hot,
            solve,
        )
        from amplify import sum as amplify_sum
    except ImportError:
        logger.error("D-Wave: Amplify SDK が見つかりません。")
        return None, "Amplify SDK が見つかりません。`uv sync` を実行してください。"

    n, m = len(agents), len(tasks)
    generator = VariableGenerator()
    variables = generator.array("Binary", (n, m))
    for i in range(n):
        for j in range(m):
            if coeffs.forbidden[i, j]:
                variables[i, j] = 0

    quality = amplify_sum(
        [
            float(coeffs.w[j])
            * (
                weights.alpha * float(coeffs.q[i, j])
                + weights.beta * float(coeffs.r[i, j])
            )
            * variables[i, j]
            for i in range(n)
            for j in range(m)
        ]
    )
    cost_norm = amplify_sum(
        [
            float(coeffs.c_norm[i, j]) * variables[i, j]
            for i in range(n)
            for j in range(m)
        ]
    )
    objective = -quality + weights.gamma * cost_norm
    constraints = amplify_sum([one_hot(variables[:, j]) for j in range(m)])
    if options.budget is not None:
        cost = amplify_sum(
            [
                float(coeffs.c[i, j]) * variables[i, j]
                for i in range(n)
                for j in range(m)
            ]
        )
        constraints += less_equal(cost, float(options.budget))

    try:
        client = DWaveSamplerClient(token=token)
        client.parameters.num_reads = max(10, int(time_limit_sec) * 100)
        solver_name = os.getenv("DWAVE_SOLVER")
        if solver_name:
            client.solver = solver_name
        logger.info(
            "D-Wave: Amplify 経由の求解を開始します（tasks=%d, agents=%d, reads=%d）。",
            m,
            n,
            client.parameters.num_reads,
        )
    except Exception as exc:  # noqa: BLE001 - 認証エラーを UI に返す
        logger.exception("D-Wave: クライアント初期化に失敗しました。")
        return None, f"D-Wave Advantage の初期化に失敗しました: {exc}"

    start = time.perf_counter()
    try:
        result = solve(Model(objective, constraints), client)
    except Exception as exc:  # noqa: BLE001 - ネットワークエラーを UI に返す
        logger.exception("D-Wave: 求解に失敗しました。")
        return None, f"D-Wave Advantage の実行に失敗しました: {exc}"
    elapsed = (time.perf_counter() - start) * 1000

    if len(result) == 0:
        logger.warning("D-Wave: 有効な解が返りませんでした。")
        return None, "D-Wave から有効な割当が返りませんでした。"

    values = np.asarray(variables.evaluate(result.best.values))
    assignment = np.full(m, -1, dtype=int)
    for j in range(m):
        chosen = np.where(np.isclose(values[:, j], 1.0, atol=1e-6))[0]
        if chosen.size == 1:
            assignment[j] = int(chosen[0])
    if np.any(assignment < 0):
        logger.warning("D-Wave: one-hot 形式の解を復元できませんでした。")
        return None, "D-Wave から有効な one-hot 割当が返りませんでした。"

    result_obj = evaluate_assignment(
        assignment,
        agents,
        tasks,
        coeffs,
        weights,
        options,
        _METHOD,
        elapsed,
        f"D-Wave Advantage を Amplify 経由で求解（目的関数値 {result.best.objective:.3f}）。",
    )
    logger.info("D-Wave: 求解が完了しました（elapsed_ms=%.1f）。", elapsed)
    return result_obj, ""
