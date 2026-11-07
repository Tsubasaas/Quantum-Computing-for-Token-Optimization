"""古典ベースライン: 無作為割当と貪欲法。"""

from __future__ import annotations

import time

import numpy as np

from ..evaluation.metrics import evaluate_assignment
from ..models import Agent, AssignmentResult, SolveOptions, Task, Weights
from ..qubo.coefficients import Coefficients


def _allowed_agents(coeffs: Coefficients, j: int) -> list[int]:
    allowed = [i for i in range(coeffs.q.shape[0]) if not coeffs.forbidden[i, j]]
    return allowed or list(range(coeffs.q.shape[0]))


def solve_random(
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
    rng = np.random.default_rng(options.seed or seed)
    m = len(tasks)
    assign = np.full(m, -1, dtype=int)
    for j in range(m):
        assign[j] = int(rng.choice(_allowed_agents(coeffs, j)))
    result = evaluate_assignment(
        assign,
        agents,
        tasks,
        coeffs,
        weights,
        options,
        "Random（無作為・基準線）",
        0.0,
        "各タスクを無作為に割り当てた基準線です。",
    )
    return result, ""


def solve_greedy(
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
    start = time.perf_counter()
    n, m = len(agents), len(tasks)
    assign = np.full(m, -1, dtype=int)
    loads = np.zeros(n)
    cost_used = 0.0

    order = sorted(range(m), key=lambda j: (-tasks[j].priority, -tasks[j].difficulty))
    for j in order:
        best_i: int | None = None
        best_score = float("-inf")
        for i in _allowed_agents(coeffs, j):
            if (
                options.hard_capacity
                and agents[i].max_tasks is not None
                and loads[i] >= agents[i].max_tasks
            ):
                continue
            if options.budget is not None and cost_used + coeffs.c[i, j] > options.budget + 1e-9:
                continue
            # Amplify 側の目的関数（C1/C2/C3 + α・β・γ）と同じ式。μ は今回入れない。
            score = coeffs.w[j] * (
                weights.alpha * coeffs.q[i, j] + weights.beta * coeffs.r[i, j]
            ) - weights.gamma * coeffs.c_norm[i, j]
            if score > best_score:
                best_score, best_i = score, i
        if best_i is None:
            # 予算・容量で詰まったら、機密制約だけ守って最安を選ぶ
            best_i = min(_allowed_agents(coeffs, j), key=lambda i: coeffs.c[i, j])
        assign[j] = best_i
        loads[best_i] += 1
        cost_used += coeffs.c[best_i, j]

    elapsed = (time.perf_counter() - start) * 1000
    result = evaluate_assignment(
        assign,
        agents,
        tasks,
        coeffs,
        weights,
        options,
        "Greedy（貪欲法・古典）",
        elapsed,
        "重要度の高いタスクから、限界スコアが最大のエージェントへ割り当てました。",
    )
    return result, ""
