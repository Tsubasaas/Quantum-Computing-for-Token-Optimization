"""「実際に使えるモデル」だけに絞るための選別オーバーレイ。

``models.json`` にはベンチマーク照合のため、旧バージョンや一般提供されていない
モデルも載っている。最適化がいくら良い編成を出しても、呼べないモデルが入って
いたら意味がない。ここで **除外理由つき** に落とす（チームでレビューできるよう、
1 件ずつ理由を残す）。

判断基準:
  - 旧バージョン: 同じ系統・同じ規模帯に新しい版があり、実運用では新版しか
    呼べないもの（例: Claude Opus 4.7 → Opus 5）。
    mini / nano / flash / lite / 27B / 8B などの **規模違いは版落ち扱いにしない**
    （別 SKU として残す）。
  - ベンチ専用: ベンチには載るが一般提供が確認できないもの（preview / 研究公開）。

``models.json`` は自動生成（scripts/build_models.py）。生成ロジックは触らず、
このモジュールだけを更新して選別する。

本モジュールは全体が生成 AI（Claude）支援で作成されています。
"""

from __future__ import annotations

from collections.abc import Iterable

__all__ = [
    "SUPERSEDED",
    "BENCHMARK_ONLY",
    "EXCLUDED",
    "usable_model_ids",
    "exclusion_reason",
]

# 旧バージョン → 実運用で使う後継 model_id。
SUPERSEDED: dict[str, str] = {
    # Claude
    "claude_opus_41": "claude_opus_5",
    "claude_opus_45": "claude_opus_5",
    "claude_opus_46": "claude_opus_5",
    "claude_opus_47": "claude_opus_5",
    "claude_opus_48": "claude_opus_5",
    "claude_sonnet_4": "claude_sonnet_5",
    "claude_sonnet_45": "claude_sonnet_5",
    "claude_sonnet_46": "claude_sonnet_5",
    "claude_35_sonnet": "claude_sonnet_5",
    # OpenAI GPT
    "gpt_41": "gpt56_sol",
    "gpt_41_mini": "gpt_5_mini",
    "gpt_52": "gpt56_sol",
    "gpt_54": "gpt56_sol",
    "o3_mini": "gpt_5_mini",
    "gpt_image_1": "gpt_image_2",
    "gpt_image_15": "gpt_image_2",
    # Google Gemini
    "gemini_25_pro": "gemini_31_pro",
    "gemini_3_pro_doc": "gemini_31_pro",
    "gemini_36_flash": "gemini_38_flash",
    "gemini_37_flash": "gemini_38_flash",
    # xAI
    "grok_420": "grok_45",
    # DeepSeek
    "deepseek_v3": "deepseek_v4_pro",
    # Alibaba Qwen
    "qwen_37_max": "qwen38_max",
    "qwen_36_plus": "qwen38_max",
    "qwen_36_27b": "qwen38_27b",
    # Moonshot Kimi
    "kimi_k25": "kimi_k3",
    "kimi_k26": "kimi_k3",
    # Z.ai GLM
    "glm_5": "glm_53",
    "glm_52": "glm_53",
    "glm_47": "glm_53",
    # Meta Muse
    "muse_spark_11": "muse_spark_13",
    "muse_spark_12": "muse_spark_13",
    # Microsoft image
    "mai_image_25": "mai_image_26",
    # Nanonets OCR
    "nanonets_ocr2p": "nanonets_ocr3",
    # Midjourney
    "midjourney_v6": "midjourney_v7",
}

# 一般提供が確認できない（ベンチ掲載のみ）。
BENCHMARK_ONLY: dict[str, str] = {
    "claude_mythos_5": "ベンチ掲載のみ・一般提供されていない派生",
    "inkling_small": "研究プレビュー（一般提供前）",
    "hy4_preview": "preview 版（一般提供前）",
}

# model_id -> 除外理由（人間可読）。
EXCLUDED: dict[str, str] = {
    **{old: f"旧バージョン（{new} に置き換え）" for old, new in SUPERSEDED.items()},
    **BENCHMARK_ONLY,
}


def usable_model_ids(all_ids: Iterable[str]) -> list[str]:
    """``all_ids`` から除外対象を取り除き、順序を保って返す。"""

    return [model_id for model_id in all_ids if model_id not in EXCLUDED]


def exclusion_reason(model_id: str) -> str | None:
    """除外理由。対象外（＝使えるモデル）なら ``None``。"""

    return EXCLUDED.get(model_id)
