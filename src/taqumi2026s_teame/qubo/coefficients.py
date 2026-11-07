"""QUBO 前処理: モデル × タスクの Q_ja / C_ja / t_ja 行列を作る。

役割ブレンドによる品質合成は :mod:`taqumi2026s_teame.data` 側で済んでいる。
ここでは Agent（合成済み）から (N, M) 行列に展開するだけ。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..data import cost_for, load_models
from ..models import Agent, Task


@dataclass(slots=True)
class Coefficients:
    q: np.ndarray  # (N, M) 合成品質 Q_ja × 難易度補正
    r: np.ndarray  # (N, M) 信頼性
    c: np.ndarray  # (N, M) コスト C_ja（USD）。task.quantity 倍済み
    c_norm: np.ndarray  # (N, M) コストを 0-1 に正規化（目的関数の γ 項用。品質と同スケール）
    t: np.ndarray  # (N, M) 処理時間（秒）
    w: np.ndarray  # (M,) タスク重要度 w_j
    forbidden: np.ndarray  # (N, M) bool。True = 割当不可（能力なし または 機密×社外）
    capability_ok: np.ndarray  # (N, M) bool。True = そのモデルがタスクの能力を持つ


def _difficulty_quality_factor(difficulty: int) -> float:
    return float(max(0.0, 1.0 - 0.12 * (difficulty - 1)))


def build_coefficients(agents: list[Agent], tasks: list[Task]) -> Coefficients:
    n, m = len(agents), len(tasks)
    q = np.zeros((n, m))
    r = np.zeros((n, m))
    c = np.zeros((n, m))
    t = np.zeros((n, m))
    forbidden = np.zeros((n, m), dtype=bool)
    capability_ok = np.zeros((n, m), dtype=bool)

    models_by_id = {mm["model_id"]: mm for mm in load_models()}

    for i, agent in enumerate(agents):
        model = models_by_id.get(agent.id, {})
        for j, task in enumerate(tasks):
            has_cap = agent.can_do(task.role)
            capability_ok[i, j] = has_cap
            factor = _difficulty_quality_factor(task.difficulty)
            q[i, j] = agent.q(task.role) * factor if has_cap else 0.0
            r[i, j] = agent.r(task.role) if has_cap else 0.0
            unit_cost = cost_for(model, task.difficulty) if model else agent.cost_per_task
            # quantity（画像の生成枚数など）は成果物 1 個あたり単価の線形倍。
            # 目的関数・制約の形は変えず、c 行列のスケールだけが変わる。
            c[i, j] = unit_cost * max(1, int(task.quantity))
            t[i, j] = (
                agent.latency_sec * (0.5 + 0.18 * task.difficulty) * max(0.5, task.est_time / 2.0)
            )
            forbidden[i, j] = (not has_cap) or (task.confidential and agent.external)

    c = np.clip(c, 0.01, None)
    # 割当可能なセルの最大コストで正規化（forbidden は除外。全滅なら 1.0）
    allowed = c[~forbidden]
    c_max = float(allowed.max()) if allowed.size else 1.0
    c_norm = np.clip(c / c_max, 0.0, 1.0)
    w = np.array([task.weight for task in tasks], dtype=float)
    return Coefficients(
        q=q, r=r, c=c, c_norm=c_norm, t=t, w=w, forbidden=forbidden, capability_ok=capability_ok
    )
