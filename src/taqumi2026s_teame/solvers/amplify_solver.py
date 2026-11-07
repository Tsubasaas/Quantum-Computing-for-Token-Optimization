"""Fixstars Amplify AE による QUBO 求解。トークン未設定でも落ちない。

制約は C1（one-hot）・C2（能力なし/機密×社外の変数固定）・C3（予算上限）のみ。
締切（C4）と負荷分散（μ 項）は今回のスコープ外（``SolveOptions.deadline`` /
``Weights.mu`` はフィールドとして残すが、ここでは参照しない）。
実装は `taqumi-2026-summer` 講義教材（`courses/03_QuantumAnnealing` の
meeting_assignment / TSP ノートブックと `courses/07_WebApplication/tsp.py`）の
書き方に合わせている。
"""

from __future__ import annotations

import os
import time

import numpy as np

from ..evaluation.metrics import evaluate_assignment
from ..models import Agent, AssignmentResult, SolveOptions, Task, Weights
from ..qubo.coefficients import Coefficients

_METHOD = "Amplify AE（量子インスパイアード）"


def solve_amplify(
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
    token = token or os.getenv("FIXSTARS_AMPLIFY_TOKEN")
    if not token:
        return None, "FIXSTARS_AMPLIFY_TOKEN が未設定です。"

    try:
        from amplify import (
            AmplifyAEClient,
            Model,
            VariableGenerator,
            less_equal,
            one_hot,
            solve,
        )
        from amplify import sum as amplify_sum
    except ImportError:
        return None, "amplify SDK が見つかりません。`uv sync` を実行してください。"

    n, m = len(agents), len(tasks)
    gen = VariableGenerator()
    x = gen.array("Binary", (n, m))

    # C2: 能力なし、または 機密タスク × 社外エージェントは変数を 0 に固定
    # （ペナルティではなく変数そのものを定数化する。参照実装の q_fixed[i,j]=0/1 と同じ形）
    for i in range(n):
        for j in range(m):
            if coeffs.forbidden[i, j]:
                x[i, j] = 0

    # 目的関数: max Σ w_j(α q_ij + β r_ij) x_ij − γ Σ ĉ_ij x_ij
    # Amplify は最小化なので符号反転（-quality）。μ・負荷分散項は今回入れない。
    quality = amplify_sum(
        [
            float(coeffs.w[j])
            * (
                weights.alpha * float(coeffs.q[i, j])
                + weights.beta * float(coeffs.r[i, j])
            )
            * x[i, j]
            for i in range(n)
            for j in range(m)
        ]
    )
    cost_norm = amplify_sum(
        [float(coeffs.c_norm[i, j]) * x[i, j] for i in range(n) for j in range(m)]
    )
    objective = -quality + weights.gamma * cost_norm  # 最小化

    # C1: 各タスクにちょうど 1 エージェント
    constraints = amplify_sum([one_hot(x[:, j]) for j in range(m)])
    # C3: 予算上限（Amplify の less_equal に不等式のエンコードを任せる）
    if options.budget is not None:
        cost_expr = amplify_sum(
            [float(coeffs.c[i, j]) * x[i, j] for i in range(n) for j in range(m)]
        )
        constraints += less_equal(cost_expr, float(options.budget))

    model = Model(objective, constraints)
    client = AmplifyAEClient()
    client.token = token
    client.parameters.time_limit_ms = int(max(1, time_limit_sec) * 1000)

    start = time.perf_counter()
    try:
        result = solve(model, client)
    except Exception as exc:  # noqa: BLE001 - ネットワーク/認証エラーを UI に返す
        return None, f"Amplify AE の実行に失敗しました: {exc}"
    elapsed = (time.perf_counter() - start) * 1000

    if len(result) == 0:
        # 予算だけでなく C1(one-hot)・C2(能力/機密) が原因のことも多いので、
        # 「予算」に限定しない文言にする（例: 候補モデルが特定タスクの能力を持たない）。
        return None, (
            "制約を満たす編成が見つかりませんでした。候補モデルや予算上限を見直してください。"
        )

    # デコード: 列 j ごとに x_val[:, j] ≈ 1 のエージェント index を取る
    # （参照実装 tsp.py の `np.where(q_values == 1)` スタイル。ただし Amplify の
    # evaluate() が返す float が浮動小数点誤差で 1 からわずかにずれる可能性があるため、
    # 厳密な == ではなく np.isclose で判定する）。
    x_val = np.asarray(x.evaluate(result.best.values))
    assign = np.full(m, -1, dtype=int)
    for j in range(m):
        chosen = np.where(np.isclose(x_val[:, j], 1.0, atol=1e-6))[0]
        if chosen.size == 1:
            assign[j] = int(chosen[0])
    result_obj = evaluate_assignment(
        assign,
        agents,
        tasks,
        coeffs,
        weights,
        options,
        _METHOD,
        elapsed,
        f"Amplify AE で求解（目的関数値 {result.best.objective:.3f}）。",
    )
    return result_obj, ""
