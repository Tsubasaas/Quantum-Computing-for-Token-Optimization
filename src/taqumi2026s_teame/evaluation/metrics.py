"""割当ベクトルから :class:`AssignmentResult` を組み立てる。全ソルバ共通。"""

from __future__ import annotations

import numpy as np

from ..models import Agent, AssignmentResult, SolveMetric, SolveOptions, Task, Weights
from ..qubo.coefficients import Coefficients


def evaluate_assignment(
    assign: np.ndarray,
    agents: list[Agent],
    tasks: list[Task],
    coeffs: Coefficients,
    weights: Weights,
    options: SolveOptions,
    method: str,
    solve_ms: float,
    message: str = "",
) -> AssignmentResult:
    """``assign``: 形 (M,) の int 配列。各タスクの担当エージェント index（未割当は -1）。"""

    n, m = len(agents), len(tasks)
    loads = np.zeros(n)
    times = np.zeros(n)
    exp_quality = 0.0
    reliability = 0.0
    cost_total = 0.0
    cost_norm_total = 0.0
    violations = 0
    per_agent: dict[str, list[str]] = {a.id: [] for a in agents}
    assignments: dict[str, str] = {}

    for j, raw in enumerate(assign):
        i = int(raw)
        if i < 0:
            violations += 1
            continue
        exp_quality += coeffs.w[j] * coeffs.q[i, j]
        reliability += coeffs.w[j] * coeffs.r[i, j]
        cost_total += coeffs.c[i, j]
        cost_norm_total += coeffs.c_norm[i, j]
        times[i] += coeffs.t[i, j]
        loads[i] += 1
        per_agent[agents[i].id].append(tasks[j].id)
        assignments[tasks[j].id] = agents[i].id
        if coeffs.forbidden[i, j]:
            violations += 1

    if options.hard_capacity:
        for i, agent in enumerate(agents):
            if agent.max_tasks is not None and loads[i] > agent.max_tasks:
                violations += 1

    makespan = float(times.max()) if m else 0.0
    load_std = float(loads.std())
    within_budget = options.budget is None or float(cost_total) <= options.budget + 1e-6
    # 締切(C4)はどのソルバも制約として課していない（今回のスコープ外）ため、
    # within_deadline は診断値としてのみ持つ。feasible には含めない
    # （含めると deadline 指定時に「解けているのに infeasible」という不整合が起きる）。
    within_deadline = options.deadline is None or makespan <= options.deadline + 1e-6
    # 目的関数: α・β・γ の項のみ（C1/C2/C3 に対応する定式化）。
    # μ（負荷分散）は今回のスコープ外のため加算しない。load_std は診断値として残す。
    objective = (
        weights.alpha * float(exp_quality)
        + weights.beta * float(reliability)
        - weights.gamma * float(cost_norm_total)
    )
    feasible = violations == 0 and within_budget

    metric = SolveMetric(
        method=method,
        objective=float(objective),
        exp_quality=float(exp_quality),
        reliability=float(reliability),
        cost_total=float(cost_total),
        makespan=makespan,
        load_std=load_std,
        feasible=bool(feasible),
        within_budget=bool(within_budget),
        within_deadline=bool(within_deadline),
        violations=int(violations),
        solve_ms=float(solve_ms),
        message=message,
    )
    return AssignmentResult(
        method=method, assignments=assignments, metric=metric, per_agent=per_agent
    )
