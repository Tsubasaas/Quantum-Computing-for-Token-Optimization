"""ソルバのレジストリ。UI はこの辞書を反復して同一シグネチャで呼び出す。

シグネチャ: ``solve(agents, tasks, coeffs, weights, options, *, time_limit_sec, token, seed)
-> tuple[AssignmentResult | None, str]``
"""

from __future__ import annotations

from .amplify_solver import solve_amplify
from .classical import solve_greedy, solve_random
from .dwave_solver import solve_dwave

SOLVERS = {
    "Greedy（貪欲法・古典）": solve_greedy,
    "Random（無作為・基準線）": solve_random,
    "Amplify AE（量子インスパイアード）": solve_amplify,
    "D-Wave Advantage（量子アニーリング）": solve_dwave,
}

__all__ = ["SOLVERS", "solve_greedy", "solve_random", "solve_amplify", "solve_dwave"]
