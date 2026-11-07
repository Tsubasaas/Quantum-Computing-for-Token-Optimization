"""編成モードのプリセットと既定値。"""

from __future__ import annotations

from .models import Weights

# 画面 1 の「最適化方針」（ui_helpers.OPTIMIZATION_MODE_MAP）と同じキー・同じ並び順。
# ユーザーが動かすのは γ（品質⟷コスト）だけ。β・μ は固定。
MODE_WEIGHTS: dict[str, Weights] = {
    "コスト優先": Weights(alpha=1.0, beta=0.3, gamma=3.0, mu=0.2),
    "バランス": Weights(alpha=1.0, beta=0.4, gamma=1.0, mu=0.2),
    "精度優先": Weights(alpha=1.0, beta=0.5, gamma=0.0, mu=0.2),
}

DEFAULT_MODE = "バランス"

# 「品質 ⟷ コスト」スライダー（0-100）と γ の対応。γ = slider / GAMMA_SCALE
GAMMA_SCALE = 25.0  # slider 100 → γ 4.0
GAMMA_MAX = 4.0

# 予算スライダーの目安（USD）。0 = 無料〜最安モデルのみ。※正本は画面 1
BUDGET_MIN = 0.0
BUDGET_MAX = 60.0
BUDGET_DEFAULT = 15.0
BUDGET_STEP = 0.25

# 締切スライダーの目安（秒・モデル別 makespan）
DEADLINE_MIN = 60.0
DEADLINE_MAX = 1200.0
DEADLINE_DEFAULT = 600.0
