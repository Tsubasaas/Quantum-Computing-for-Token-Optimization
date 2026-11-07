"""「最適化実行」UI を単独動作確認するための Mock 入力データ。

上流「推奨案＋人間判断UI」が完成するまでの代替。
``st.session_state["optimization_input"]`` が存在しない場合にのみ使用する想定。
上流が完成したら、このモジュールへの依存を削除するだけで接続できる。
"""

from __future__ import annotations

from ..optimization_contract import OptimizationInput


def build_mock_optimization_input() -> OptimizationInput:
    """Mock の ``optimization_input`` を生成する。

    Returns:
        OptimizationInput: 上流未完成時の代替入力データ。
    """

    return {
        "tasks": [
            {"task_id": "T01", "task_name": "要件整理"},
            {"task_id": "T02", "task_name": "設計"},
            {"task_id": "T03", "task_name": "実装"},
            {"task_id": "T04", "task_name": "テスト"},
        ],
        "candidate_models": ["GPT-5", "Claude", "Gemini"],
        "model_capability_matrix": {},
        "optimization_weights": {"cost": 0.3, "accuracy": 0.5, "review": 0.2},
        "budget_limit": 10.0,
        "max_completion_time": 30.0,
        "masking_enabled": True,
        "optimization_mode": "バランス",
    }
