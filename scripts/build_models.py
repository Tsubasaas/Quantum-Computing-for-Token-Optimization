"""models.json を公開ベンチマークの実測値から生成する（再現可能なデータビルド）。

方針（推測を入れない）:
  - 能力カテゴリごとに出典ベンチマークを 1 つに固定し、生値をそのまま（または明示式で正規化）使う
  - モデルは各ベンチの表記名で識別。複数ベンチに同名で載る場合のみ 1 候補に統合
  - 値が取れないカテゴリは null（= そのタスク担当不可）
  - 価格は各社公式ページの実測。無ければ null
  - コスト/処理時間は SWE-rebench の Cost per Problem / Tokens per Problem（実測）を優先

実行: uv run python scripts/build_models.py
出典: 各テーブルのコメント参照。すべて 2026-09 時点。
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src" / "taqumi2026s_teame" / "data" / "models.json"
CHECKED = "2026-09-08"

# ========================================================================== #
# 能力カテゴリ -> 出典
# ========================================================================== #
CATEGORY_SOURCE = {
    "repo_bug_fix": "SWE-bench Verified",
    "terminal": "Terminal-Bench 2.1",
    "document": "IDP Leaderboard",
    "ocr": "IDP Leaderboard",
    "image_generation": "Image Arena",
}
SOURCE_URL = {
    "SWE-bench Verified": "https://www.swebench.com/",
    "SWE-rebench": "https://swe-rebench.com/",
    "Terminal-Bench 2.1": "https://llm-stats.com/benchmarks/terminal-bench-2.1",
    "IDP Leaderboard": "https://www.idp-leaderboard.org/",
    "Image Arena": "https://artificialanalysis.ai/text-to-image/arena",
    "Anthropic pricing": "https://platform.claude.com/docs/en/about-claude/pricing",
    "OpenAI pricing": "https://developers.openai.com/api/docs/pricing",
    "Google pricing": "https://ai.google.dev/gemini-api/docs/pricing",
    "xAI pricing": "https://docs.x.ai/docs/models",
}

# ========================================================================== #
# 生値テーブル（出典そのまま）
# ========================================================================== #

# --- SWE-bench Verified: % resolved（0-1） --------------------------------- #
# https://www.swebench.com/  (benchlm.ai 集計, 2026-09-04)
SWE_VERIFIED: dict[str, float] = {
    "claude_opus_5": 0.960,
    "claude_mythos_5": 0.955,
    "claude_fable_5": 0.950,
    "claude_opus_48": 0.886,
    "claude_opus_47": 0.876,
    "claude_sonnet_5": 0.852,
    "gpt_53_codex": 0.850,
    "claude_opus_45": 0.809,
    "claude_opus_46": 0.808,
    "deepseek_v4_pro": 0.806,
    "minimax_m3": 0.805,
    "qwen_37_max": 0.804,
    "kimi_k26": 0.802,
    "inkling_small": 0.802,
    "gpt_52": 0.800,
    "claude_sonnet_46": 0.796,
    "deepseek_v4_flash": 0.790,
    "qwen_36_plus": 0.788,
    "mimo_v2_pro": 0.780,
    "glm_5": 0.778,
    "mistral_medium_35": 0.776,
    "muse_spark": 0.774,
    "claude_sonnet_45": 0.772,
    "qwen_36_27b": 0.772,
    "kimi_k25": 0.768,
    "grok_420": 0.767,
    "muse_glimmer_30b": 0.760,
    "claude_opus_41": 0.745,
    "glm_47": 0.738,
    "mimo_v2_flash": 0.734,
    "claude_haiku_45": 0.733,
    "claude_sonnet_4": 0.727,
    "nemotron_3_ultra": 0.719,
    "grok_code_fast_1": 0.708,
    "gemini_25_pro": 0.638,
    "gpt_41": 0.546,
    "o3_mini": 0.493,
    "claude_35_sonnet": 0.490,
    "granite_42_8b": 0.477,
    "deepseek_v3": 0.420,
    "gpt_41_mini": 0.236,
}

# --- SWE-rebench: (Resolved Rate, Pass@5, Cost/Problem $, Tokens/Problem) --- #
# https://swe-rebench.com/  window 2026-05-15..2026-07-01, 111 問
SWE_REBENCH: dict[str, tuple[float, float, float, int]] = {
    "claude_fable_5": (0.645, 0.784, 4.40, 2518308),
    "grok_45": (0.638, 0.775, 1.47, 2429424),
    "claude_opus_5": (0.634, 0.748, 3.47, 4322143),
    "glm_52": (0.629, 0.811, 1.40, 5524892),
    "gpt56_sol": (0.623, 0.793, 0.85, 605340),
    "junie": (0.618, 0.739, 0.81, 1684501),
    "claude_code": (0.604, 0.757, 3.39, 3341581),
    "codex": (0.580, 0.730, 1.59, 2070976),
    "claude_sonnet_5": (0.568, 0.748, 1.43, 4645617),
    "cursor": (0.517, 0.658, 0.41, 1827002),
    "minimax_m3": (0.472, 0.694, 0.95, 13869459),
    "onprem_mimo": (0.465, 0.658, 0.10, 4687987),
    "gpt56_luna": (0.436, 0.595, 0.11, 395522),
    "deepseek_v4_pro": (0.402, 0.640, 0.15, 3955414),
}

# --- Terminal-Bench 2.1: Accuracy（0-1） --------------------------------- #
# https://llm-stats.com/benchmarks/terminal-bench-2.1  2026-09-08（全 35 モデル）
TERMINAL_BENCH: dict[str, float] = {
    "gemini_38_flash": 0.894,
    "gpt56_sol": 0.888,
    "muse_spark_13": 0.888,
    "kimi_k3": 0.883,
    "glm_53": 0.882,
    "deepseek_v4_pro": 0.879,
    "gpt56_terra": 0.874,
    "qwen38_max": 0.866,
    "gemini_37_flash": 0.858,
    "hy4_preview": 0.854,
    "gpt56_luna": 0.847,
    "glm_53_flash": 0.843,
    "claude_fable_5": 0.843,
    "deepseek_v4_flash_vision": 0.839,
    "grok_45": 0.833,
    "muse_spark_12": 0.829,
    "glm_52": 0.827,
    "deepseek_v4_flash": 0.827,
    "muse_spark_11": 0.800,
    "gemini_36_flash": 0.780,
    "qwen38_27b": 0.730,
    "hy3": 0.717,
    "seed_21_pro": 0.710,
    "laguna_s_21": 0.702,
    "seed_21_turbo": 0.676,
    "minimax_m3": 0.660,
    "inkling_small": 0.647,
    "mai_code_11_flash": 0.629,
    "solar_pro_4": 0.570,
    "nemotron_3_ultra": 0.564,
    "gemini_35_flash_lite": 0.540,
    "muse_glimmer_30b": 0.517,
    "ibm_granite_42_30b": 0.292,
    "nemotron_35_lightning": 0.246,
    "ibm_granite_42_8b": 0.206,
}

# --- IDP Leaderboard v1.5: (Overall, OlmOCR)（0-100） --------------------- #
# https://www.idp-leaderboard.org/  2026-09-08（全 26 モデル）
IDP: dict[str, tuple[float, float]] = {
    "nanonets_ocr3": (85.9, 87.4),
    "gpt_54": (83.5, 81.0),
    "gemini_3_pro_doc": (82.8, 77.7),
    "gemini_3_flash_doc": (82.0, 75.3),
    "nanonets_ocr2p": (81.8, 82.0),
    "gemini_31_pro": (81.6, 69.8),
    "gpt_52": (81.5, 79.1),
    "claude_sonnet_46": (80.7, 73.9),
    "claude_opus_46": (80.4, 74.1),
    "qwen3_vl_plus": (80.1, 77.9),
    "qwen3_vl_235b": (79.6, 76.8),
    "qwen35_9b": (76.7, 77.2),
    "gpt_5_mini": (75.2, 69.9),
    "qwen35_4b": (72.5, 75.4),
    "mistral_small_4": (71.5, 69.6),
    "claude_haiku_45": (71.2, 61.2),
    "ministral_8b": (69.5, 58.7),
    "gpt_41": (68.0, 49.4),
    "glm_ocr": (64.2, 68.4),
    "qwen35_2b": (62.6, 71.9),
    "gpt_5_nano": (54.8, 35.2),
    "gemma_4_e4b": (53.9, 47.0),
    "llama_32_vision_11b": (50.8, 49.1),
    "pixtral_12b": (46.5, 38.3),
}

# --- Image Arena (Text-to-Image): Elo -------------------------------------- #
# https://artificialanalysis.ai/text-to-image/arena  2026-09
IMAGE_ARENA_ELO: dict[str, float] = {
    "gpt_image_2": 1178,
    "mai_image_26": 1149,
    "reve_21": 1127,
    "nano_banana_2": 1121,
    "muse_image": 1116,
    "gpt_image_15": 1114,
    "mai_image_25": 1112,
    "nano_banana_pro": 1099,
    "nano_banana_2_lite": 1089,
    "qwen_image_30_pro": 1086,
    "grok_imagine": 1034,
    "flux_2_max": 1031,
    "flux_2_flex": 1026,
    "ideogram_4": 1017,
    "ideogram_4_quality": 1014,
    "flux_2_pro": 1011,
    "gpt_image_1": 1007,
    "imagen_4_ultra": 990,
    "z_image_turbo": 928,
    "imagen_4_std": 925,
    "midjourney_v7": 894,
    "midjourney_v6": 878,
}
IMAGE_ARENA_SAMPLES: dict[str, int] = {
    "gpt_image_2": 14585,
    "reve_21": 16045,
    "nano_banana_2": 15772,
    "gpt_image_15": 14082,
}


def img_norm(elo: float) -> float:
    """Image Arena Elo -> 0-1（線形。範囲 850-1180 を目安に）。"""

    return round(min(1.0, max(0.0, (elo - 850) / 330)), 3)


# --- 公式 API 価格 input/output per 1M tokens（各社公式ページ, 2026-09-08）--- #
PRICING: dict[str, tuple[float | None, float | None, str]] = {
    # Anthropic  https://platform.claude.com/docs/en/about-claude/pricing
    "claude_opus_5": (5.0, 25.0, "Anthropic pricing"),
    "claude_mythos_5": (10.0, 50.0, "Anthropic pricing"),
    "claude_fable_5": (10.0, 50.0, "Anthropic pricing"),
    "claude_opus_48": (5.0, 25.0, "Anthropic pricing"),
    "claude_opus_47": (5.0, 25.0, "Anthropic pricing"),
    "claude_opus_46": (5.0, 25.0, "Anthropic pricing"),
    "claude_opus_45": (5.0, 25.0, "Anthropic pricing"),
    "claude_opus_41": (15.0, 75.0, "Anthropic pricing"),
    "claude_sonnet_5": (2.0, 10.0, "Anthropic pricing"),
    "claude_sonnet_46": (3.0, 15.0, "Anthropic pricing"),
    "claude_sonnet_45": (3.0, 15.0, "Anthropic pricing"),
    "claude_sonnet_4": (3.0, 15.0, "Anthropic pricing"),
    "claude_haiku_45": (1.0, 5.0, "Anthropic pricing"),
    "claude_35_sonnet": (3.0, 15.0, "Anthropic pricing"),
    # OpenAI  https://developers.openai.com/api/docs/pricing
    "gpt_53_codex": (1.75, 14.0, "OpenAI pricing"),
    "gpt_52": (1.75, 14.0, "OpenAI pricing"),
    "gpt56_sol": (4.0, 20.0, "OpenAI pricing"),
    "gpt56_terra": (2.0, 12.0, "OpenAI pricing"),
    "gpt56_luna": (0.20, 1.20, "OpenAI pricing"),
    "gpt_54": (None, None, "OpenAI pricing"),
    "gpt_5_mini": (0.25, 2.0, "OpenAI pricing"),
    "gpt_5_nano": (0.05, 0.40, "OpenAI pricing"),
    "gpt_41": (2.0, 8.0, "OpenAI pricing"),
    "gpt_41_mini": (0.40, 1.60, "OpenAI pricing"),
    "o3_mini": (1.10, 4.40, "OpenAI pricing"),
    "gpt_image_2": (5.0, 30.0, "OpenAI pricing"),
    "gpt_image_15": (5.0, 32.0, "OpenAI pricing"),
    # Google  https://ai.google.dev/gemini-api/docs/pricing
    "gemini_25_pro": (1.25, 10.0, "Google pricing"),
    "gemini_31_pro": (2.0, 12.0, "Google pricing"),
    "gemini_3_pro_doc": (2.0, 12.0, "Google pricing"),
    "gemini_36_flash": (0.75, 3.75, "Google pricing"),
    "gemini_37_flash": (0.75, 3.75, "Google pricing"),
    "gemini_38_flash": (0.75, 3.75, "Google pricing"),
    "gemini_3_flash_doc": (0.75, 3.75, "Google pricing"),
    "gemini_35_flash_lite": (0.30, 2.50, "Google pricing"),
    "nano_banana_2": (0.50, None, "Google pricing"),
    # xAI  https://docs.x.ai/docs/models
    "grok_45": (2.0, 6.0, "xAI pricing"),
}


# ========================================================================== #
# モデルメタ（表示名 / provider / family / version / type / is_agent / harness /
#              external_api / local_available / max_tasks / context_window）
# ========================================================================== #
def _m(
    name,
    prov,
    fam,
    ver,
    typ="llm",
    *,
    agent=False,
    harness=None,
    ext=True,
    loc=False,
    mx=6,
    ctx=None,
):
    return dict(
        name=name,
        prov=prov,
        fam=fam,
        ver=ver,
        typ=typ,
        agent=agent,
        harness=harness,
        ext=ext,
        loc=loc,
        mx=mx,
        ctx=ctx,
    )


META: dict[str, dict] = {
    # --- Claude ---
    "claude_opus_5": _m("Claude Opus 5", "Anthropic", "Claude", "5", ctx=1000000, mx=5),
    "claude_mythos_5": _m("Claude Mythos 5", "Anthropic", "Claude", "mythos-5", ctx=1000000, mx=5),
    "claude_fable_5": _m("Claude Fable 5", "Anthropic", "Claude", "5", ctx=1000000, mx=4),
    "claude_opus_48": _m("Claude Opus 4.8", "Anthropic", "Claude", "4.8", ctx=1000000, mx=5),
    "claude_opus_47": _m("Claude Opus 4.7", "Anthropic", "Claude", "4.7", ctx=1000000, mx=5),
    "claude_opus_46": _m("Claude Opus 4.6", "Anthropic", "Claude", "4.6", ctx=1000000, mx=5),
    "claude_opus_45": _m("Claude Opus 4.5", "Anthropic", "Claude", "4.5", ctx=200000, mx=5),
    "claude_opus_41": _m("Claude Opus 4.1", "Anthropic", "Claude", "4.1", ctx=200000, mx=5),
    "claude_sonnet_5": _m("Claude Sonnet 5", "Anthropic", "Claude", "5", ctx=1000000),
    "claude_sonnet_46": _m("Claude Sonnet 4.6", "Anthropic", "Claude", "4.6", ctx=1000000),
    "claude_sonnet_45": _m("Claude Sonnet 4.5", "Anthropic", "Claude", "4.5", ctx=200000),
    "claude_sonnet_4": _m("Claude Sonnet 4", "Anthropic", "Claude", "4", ctx=200000),
    "claude_haiku_45": _m("Claude Haiku 4.5", "Anthropic", "Claude", "4.5", ctx=1000000, mx=10),
    "claude_35_sonnet": _m("Claude 3.5 Sonnet", "Anthropic", "Claude", "3.5", ctx=200000),
    "claude_code": _m(
        "Claude Code",
        "Anthropic",
        "Claude",
        "agent",
        "coding_agent",
        agent=True,
        harness="Claude Code",
        ctx=1000000,
        mx=4,
    ),
    # --- OpenAI ---
    "gpt_53_codex": _m("GPT-5.3 Codex", "OpenAI", "GPT", "5.3-codex", ctx=400000),
    "gpt_52": _m("GPT-5.2", "OpenAI", "GPT", "5.2", ctx=400000),
    "gpt56_sol": _m("GPT-5.6 Sol", "OpenAI", "GPT", "5.6", ctx=400000),
    "gpt56_terra": _m("GPT-5.6 Terra", "OpenAI", "GPT", "5.6", ctx=400000),
    "gpt56_luna": _m("GPT-5.6 Luna", "OpenAI", "GPT", "5.6", ctx=400000, mx=8),
    "gpt_54": _m("GPT-5.4", "OpenAI", "GPT", "5.4", ctx=400000, mx=8),
    "gpt_5_mini": _m("GPT-5 mini", "OpenAI", "GPT", "5-mini", ctx=400000, mx=10),
    "gpt_5_nano": _m("GPT-5 nano", "OpenAI", "GPT", "5-nano", ctx=400000, mx=12),
    "gpt_41": _m("GPT-4.1", "OpenAI", "GPT", "4.1", ctx=1000000, mx=8),
    "gpt_41_mini": _m("GPT-4.1 mini", "OpenAI", "GPT", "4.1-mini", ctx=1000000, mx=10),
    "o3_mini": _m("o3-mini", "OpenAI", "o-series", "o3-mini", ctx=200000),
    "codex": _m(
        "Codex",
        "OpenAI",
        "GPT",
        "agent",
        "coding_agent",
        agent=True,
        harness="Codex",
        ctx=400000,
        mx=5,
    ),
    # --- Google ---
    "gemini_25_pro": _m("Gemini 2.5 Pro", "Google", "Gemini", "2.5", ctx=1000000),
    "gemini_31_pro": _m("Gemini 3.1 Pro", "Google", "Gemini", "3.1", ctx=1000000),
    "gemini_3_pro_doc": _m("Gemini 3 Pro（文書）", "Google", "Gemini", "3", ctx=1000000),
    "gemini_3_flash_doc": _m("Gemini 3 Flash（文書）", "Google", "Gemini", "3", ctx=1000000, mx=10),
    "gemini_36_flash": _m("Gemini 3.6 Flash", "Google", "Gemini", "3.6", ctx=1000000, mx=8),
    "gemini_37_flash": _m("Gemini 3.7 Flash", "Google", "Gemini", "3.7", ctx=1000000, mx=8),
    "gemini_38_flash": _m("Gemini 3.8 Flash", "Google", "Gemini", "3.8", ctx=1000000, mx=8),
    "gemini_35_flash_lite": _m(
        "Gemini 3.5 Flash-Lite", "Google", "Gemini", "3.5-lite", ctx=1000000, mx=12
    ),
    "gemma_4_e4b": _m(
        "Gemma 4 E4B（open-weight）", "Google", "Gemma", "4-e4b", ctx=128000, loc=True, mx=10
    ),
    # --- xAI ---
    "grok_45": _m("Grok 4.5", "xAI", "Grok", "4.5", ctx=256000),
    "grok_420": _m("Grok 4.20", "xAI", "Grok", "4.20", ctx=256000),
    "grok_code_fast_1": _m("Grok Code Fast 1", "xAI", "Grok", "code-fast-1", ctx=256000, mx=8),
    "grok_imagine": _m("Grok Imagine（quality）", "xAI", "Grok Imagine", "image", "image", mx=12),
    # --- DeepSeek（open-weight, 自社ホスト可） ---
    "deepseek_v4_pro": _m("DeepSeek-V4 Pro", "DeepSeek", "DeepSeek", "4-pro", loc=True),
    "deepseek_v4_flash": _m("DeepSeek-V4 Flash", "DeepSeek", "DeepSeek", "4-flash", loc=True, mx=8),
    "deepseek_v4_flash_vision": _m(
        "DeepSeek-V4 Flash Vision", "DeepSeek", "DeepSeek", "4-flash-vision", loc=True, mx=8
    ),
    "deepseek_v3": _m("DeepSeek-V3（open-weight）", "DeepSeek", "DeepSeek", "3", loc=True, mx=8),
    # --- Alibaba Qwen ---
    "qwen_37_max": _m("Qwen3.7 Max", "Alibaba", "Qwen", "3.7-max", loc=True),
    "qwen_36_plus": _m("Qwen3.6 Plus", "Alibaba", "Qwen", "3.6-plus", loc=True, mx=8),
    "qwen_36_27b": _m("Qwen3.6-27B（open-weight）", "Alibaba", "Qwen", "3.6-27b", loc=True, mx=8),
    "qwen38_max": _m("Qwen3.8 Max", "Alibaba", "Qwen", "3.8-max", loc=True),
    "qwen38_27b": _m("Qwen3.8-27B（open-weight）", "Alibaba", "Qwen", "3.8-27b", loc=True, mx=8),
    "qwen3_vl_plus": _m("Qwen3-VL Plus（文書）", "Alibaba", "Qwen", "3-vl-plus", loc=True, mx=8),
    "qwen3_vl_235b": _m(
        "Qwen3-VL-235B（文書・open-weight）", "Alibaba", "Qwen", "3-vl-235b", loc=True, mx=8
    ),
    "qwen35_9b": _m(
        "Qwen3.5-9B（文書・open-weight）", "Alibaba", "Qwen", "3.5-9b", loc=True, mx=10
    ),
    "qwen35_4b": _m(
        "Qwen3.5-4B（文書・open-weight）", "Alibaba", "Qwen", "3.5-4b", loc=True, mx=12
    ),
    "qwen35_2b": _m(
        "Qwen3.5-2B（文書・open-weight）", "Alibaba", "Qwen", "3.5-2b", loc=True, mx=12
    ),
    "qwen_image_30_pro": _m(
        "Qwen-Image-3.0-Pro", "Alibaba", "Qwen Image", "3.0-pro", "image", loc=True, mx=12
    ),
    "z_image_turbo": _m("Z-Image Turbo", "Alibaba", "Z-Image", "turbo", "image", loc=True, mx=12),
    # --- Moonshot Kimi ---
    "kimi_k3": _m("Kimi K3", "Moonshot AI", "Kimi", "K3", ctx=256000),
    "kimi_k26": _m("Kimi K2.6", "Moonshot AI", "Kimi", "K2.6", ctx=256000),
    "kimi_k25": _m("Kimi K2.5", "Moonshot AI", "Kimi", "K2.5", ctx=256000),
    # --- Z.ai GLM ---
    "glm_5": _m("GLM-5（open-weight）", "Z.ai", "GLM", "5", loc=True),
    "glm_52": _m("GLM-5.2（open-weight）", "Z.ai", "GLM", "5.2", loc=True),
    "glm_53": _m("GLM-5.3（open-weight）", "Z.ai", "GLM", "5.3", loc=True, mx=8),
    "glm_53_flash": _m("GLM-5.3-Flash（open-weight）", "Z.ai", "GLM", "5.3-flash", loc=True, mx=8),
    "glm_47": _m("GLM-4.7（open-weight）", "Z.ai", "GLM", "4.7", loc=True, mx=8),
    "glm_ocr": _m("GLM-OCR（文書・open-weight）", "Z.ai", "GLM", "ocr", loc=True, mx=12),
    # --- MiniMax / Xiaomi / Meta / NVIDIA / Mistral 他 ---
    "minimax_m3": _m("MiniMax M3", "MiniMax", "MiniMax", "M3", loc=True),
    "mimo_v2_pro": _m("MiMo-V2 Pro（open-weight）", "Xiaomi", "MiMo", "V2-pro", loc=True, mx=8),
    "mimo_v2_flash": _m(
        "MiMo-V2 Flash（open-weight）", "Xiaomi", "MiMo", "V2-flash", loc=True, mx=10
    ),
    "onprem_mimo": _m(
        "社内 LLM（オンプレ・MiMo V2.5 Pro）", "self-host", "MiMo", "2.5", ext=False, loc=True, mx=4
    ),
    "muse_spark": _m("Muse Spark", "Meta", "Muse", "spark", loc=True),
    "muse_spark_13": _m("Muse Spark 1.3", "Meta", "Muse", "spark-1.3", loc=True),
    "muse_spark_12": _m("Muse Spark 1.2", "Meta", "Muse", "spark-1.2", loc=True),
    "muse_spark_11": _m("Muse Spark 1.1", "Meta", "Muse", "spark-1.1", loc=True),
    "muse_glimmer_30b": _m(
        "Muse Glimmer 30B（open-weight）", "Meta", "Muse", "glimmer-30b", loc=True, mx=8
    ),
    "muse_image": _m("Muse Image", "Meta", "Muse", "image", "image", loc=True, mx=12),
    "llama_32_vision_11b": _m(
        "Llama 3.2 Vision 11B（文書・open-weight）",
        "Meta",
        "Llama",
        "3.2-vision-11b",
        loc=True,
        mx=12,
    ),
    "nemotron_3_ultra": _m(
        "Nemotron 3 Ultra（open-weight）", "NVIDIA", "Nemotron", "3-ultra", loc=True, mx=5
    ),
    "nemotron_35_lightning": _m(
        "Nemotron 3.5 Lightning 30B", "NVIDIA", "Nemotron", "3.5-lightning", loc=True, mx=8
    ),
    "mistral_medium_35": _m("Mistral Medium 3.5", "Mistral", "Mistral", "medium-3.5", loc=True),
    "mistral_small_4": _m(
        "Mistral Small 4（文書・open-weight）", "Mistral", "Mistral", "small-4", loc=True, mx=10
    ),
    "ministral_8b": _m(
        "Ministral 8B（文書・open-weight）", "Mistral", "Mistral", "ministral-8b", loc=True, mx=12
    ),
    "pixtral_12b": _m(
        "Pixtral 12B（文書・open-weight）", "Mistral", "Mistral", "pixtral-12b", loc=True, mx=12
    ),
    "inkling_small": _m("Inkling-Small", "Thinking Machines Lab", "Inkling", "small", ctx=200000),
    "hy4_preview": _m("Hunyuan 4 preview", "Tencent", "Hunyuan", "4-preview", ctx=256000),
    "hy3": _m("Hunyuan 3", "Tencent", "Hunyuan", "3", ctx=256000),
    "seed_21_pro": _m("Seed 2.1 Pro", "ByteDance", "Seed", "2.1-pro", ctx=256000),
    "seed_21_turbo": _m("Seed 2.1 Turbo", "ByteDance", "Seed", "2.1-turbo", ctx=256000, mx=8),
    "laguna_s_21": _m("Laguna S 2.1", "Poolside", "Laguna", "S-2.1", ctx=200000),
    "mai_code_11_flash": _m(
        "MAI-Code 1.1 Flash", "Microsoft", "MAI-Code", "1.1-flash", ctx=256000, mx=8
    ),
    "solar_pro_4": _m("Solar Pro 4（open-weight）", "Upstage", "Solar", "pro-4", loc=True, mx=8),
    "ibm_granite_42_30b": _m(
        "IBM Granite 4.2 30B（open-weight）", "IBM", "Granite", "4.2-30b", loc=True, mx=8
    ),
    "ibm_granite_42_8b": _m(
        "IBM Granite 4.2 8B（open-weight）", "IBM", "Granite", "4.2-8b", loc=True, mx=10
    ),
    "granite_42_8b": _m(
        "IBM Granite 4.2 8B（open-weight）", "IBM", "Granite", "4.2-8b", loc=True, mx=10
    ),
    "gemma_4_e4b_doc": _m(
        "Gemma 4 E4B（文書・open-weight）", "Google", "Gemma", "4-e4b", loc=True, mx=12
    ),
    "junie": _m(
        "Junie",
        "JetBrains",
        "Junie",
        "agent",
        "coding_agent",
        agent=True,
        harness="Junie",
        ctx=200000,
        mx=5,
    ),
    "cursor": _m(
        "Cursor",
        "Cursor",
        "Cursor",
        "agent",
        "coding_agent",
        agent=True,
        harness="Cursor",
        ctx=200000,
        mx=6,
    ),
    # --- 文書 IDP のみ ---
    "nanonets_ocr3": _m(
        "Nanonets OCR-3（文書専用・open-weight）", "Nanonets", "Nanonets", "ocr-3", loc=True, mx=12
    ),
    "nanonets_ocr2p": _m(
        "Nanonets OCR2+（文書専用・open-weight）", "Nanonets", "Nanonets", "ocr-2+", loc=True, mx=12
    ),
    "gpt_5_nano_doc": _m("GPT-5 nano（文書）", "OpenAI", "GPT", "5-nano", mx=12),
    # --- 画像 Image Arena のみ ---
    "gpt_image_2": _m("GPT Image 2", "OpenAI", "GPT Image", "2", "image", mx=12),
    "gpt_image_15": _m("GPT Image 1.5", "OpenAI", "GPT Image", "1.5", "image", mx=12),
    "gpt_image_1": _m("GPT Image 1", "OpenAI", "GPT Image", "1", "image", mx=12),
    "mai_image_26": _m("MAI-Image-2.6", "Microsoft", "MAI-Image", "2.6", "image", mx=12),
    "mai_image_25": _m("MAI-Image-2.5", "Microsoft", "MAI-Image", "2.5", "image", mx=12),
    "reve_21": _m("Reve 2.1", "Reve", "Reve", "2.1", "image", mx=12),
    "nano_banana_2": _m(
        "Nano Banana 2（Gemini 3.1 Flash Image）",
        "Google",
        "Gemini",
        "3.1-flash-image",
        "image",
        mx=12,
    ),
    "nano_banana_pro": _m(
        "Nano Banana Pro（Gemini 3 Pro Image）", "Google", "Gemini", "3-pro-image", "image", mx=12
    ),
    "nano_banana_2_lite": _m(
        "Nano Banana 2 Lite", "Google", "Gemini", "3.1-flash-lite-image", "image", mx=12
    ),
    "ideogram_4": _m("Ideogram 4.0", "Ideogram", "Ideogram", "4.0", "image", mx=12),
    "ideogram_4_quality": _m(
        "Ideogram 4.0 (Quality)", "Ideogram", "Ideogram", "4.0-quality", "image", mx=12
    ),
    "flux_2_pro": _m("FLUX.2 [pro]", "Black Forest Labs", "FLUX", "2-pro", "image", mx=12),
    "flux_2_max": _m("FLUX.2 [max]", "Black Forest Labs", "FLUX", "2-max", "image", mx=12),
    "flux_2_flex": _m(
        "FLUX.2 [flex]（open-weight）",
        "Black Forest Labs",
        "FLUX",
        "2-flex",
        "image",
        loc=True,
        mx=12,
    ),
    "imagen_4_ultra": _m("Imagen 4 Ultra", "Google", "Imagen", "4-ultra", "image", mx=12),
    "imagen_4_std": _m("Imagen 4 Standard", "Google", "Imagen", "4-std", "image", mx=12),
    "midjourney_v7": _m("Midjourney v7 Alpha", "Midjourney", "Midjourney", "7", "image", mx=12),
    "midjourney_v6": _m("Midjourney v6", "Midjourney", "Midjourney", "6", "image", mx=12),
}

_LATENCY_TOKENS_PER_SEC = 30_000  # SWE-rebench Tokens/Problem を処理時間の相対値に変換する定数


def build_model(mid: str) -> dict:
    m = META[mid]
    cap: dict[str, float | None] = dict.fromkeys(
        ("repo_bug_fix", "terminal", "document", "ocr", "image_generation")
    )
    bench: dict[str, float] = {}
    meta: dict[str, dict] = {}

    if mid in SWE_VERIFIED:
        cap["repo_bug_fix"] = SWE_VERIFIED[mid]
        bench["swe_bench_verified"] = SWE_VERIFIED[mid]
        meta["repo_bug_fix"] = {
            "source": "SWE-bench Verified",
            "date": "2026-09-04",
            "verified": True,
        }
    if mid in SWE_REBENCH:
        rr, p5, cost, tok = SWE_REBENCH[mid]
        bench.update(
            swe_rebench_resolved_rate=rr,
            swe_rebench_pass_at_5=p5,
            swe_rebench_cost_per_problem_usd=cost,
            swe_rebench_tokens_per_problem=tok,
        )
        if cap["repo_bug_fix"] is None:
            cap["repo_bug_fix"] = rr
            meta["repo_bug_fix"] = {
                "source": "SWE-rebench",
                "date": "2026-07",
                "window": "2026-05-15..2026-07-01",
                "sample_size": 111,
                "verified": True,
            }

    if mid in TERMINAL_BENCH:
        cap["terminal"] = TERMINAL_BENCH[mid]
        bench["terminal_bench_2_1"] = TERMINAL_BENCH[mid]
        meta["terminal"] = {"source": "Terminal-Bench 2.1", "date": CHECKED, "verified": True}

    if mid in IDP:
        overall, olmocr = IDP[mid]
        cap["document"] = round(overall / 100, 3)
        cap["ocr"] = round(olmocr / 100, 3)
        bench.update(idp_overall=overall, idp_olmocr=olmocr)
        meta["document"] = {
            "source": "IDP Leaderboard v1.5 (Overall)",
            "date": CHECKED,
            "verified": True,
        }
        meta["ocr"] = {"source": "IDP Leaderboard v1.5 (OlmOCR)", "date": CHECKED, "verified": True}

    if mid in IMAGE_ARENA_ELO:
        elo = IMAGE_ARENA_ELO[mid]
        cap["image_generation"] = img_norm(elo)
        bench["image_arena_elo"] = elo
        md = {"source": "Image Arena", "date": "2026-09", "verified": True}
        if mid in IMAGE_ARENA_SAMPLES:
            md["samples"] = IMAGE_ARENA_SAMPLES[mid]
        meta["image_generation"] = md

    in_p, out_p, psrc = PRICING.get(mid, (None, None, ""))
    per_image = 0.039 if mid == "nano_banana_2" else None
    bench_cost = SWE_REBENCH[mid][2] if mid in SWE_REBENCH else None
    tokens_pp = SWE_REBENCH[mid][3] if mid in SWE_REBENCH else None
    latency = round(tokens_pp / _LATENCY_TOKENS_PER_SEC, 1) if tokens_pp else None

    return {
        "model_id": mid,
        "model_name": m["name"],
        "provider": m["prov"],
        "model_family": m["fam"],
        "model_version": m["ver"],
        "model_type": m["typ"],
        "is_agent": bool(m["agent"]),
        "agent_harness": m["harness"],
        "external_api": m["ext"],
        "local_available": m["loc"],
        "max_tasks": m["mx"],
        "context_window": m["ctx"],
        "capability": cap,
        "pricing": {
            "input_per_1m": in_p,
            "output_per_1m": out_p,
            "cached_input_per_1m": None,
            "per_image": per_image,
            "benchmark_cost_per_task": bench_cost,
            "price_source": psrc or None,
        },
        "latency": {
            "avg_task_completion_sec": latency,
            "note": None if latency else "SWE-rebench 未掲載のため未取得",
        },
        "benchmark_scores": bench,
        "benchmark_metadata": meta,
        "sources": {"benchmark_checked_at": CHECKED, "pricing_checked_at": CHECKED},
    }


def main() -> None:
    built = (build_model(mid) for mid in META)
    models = [m for m in built if any(v is not None for v in m["capability"].values())]
    doc = {
        "_note": "自動生成（scripts/build_models.py）。capability は公開ベンチの実測をそのまま "
        "（画像のみ Elo を線形正規化）。値なし = null（そのタスク担当不可）。推測値は入れない。",
        "normalization": {
            "repo_bug_fix": "SWE-bench Verified % / 未掲載は SWE-rebench Resolved Rate",
            "terminal": "Terminal-Bench 2.1 Accuracy",
            "document": "IDP Leaderboard Overall / 100",
            "ocr": "IDP Leaderboard OlmOCR / 100",
            "image_generation": "Image Arena Elo -> clip((elo-850)/330, 0, 1)",
            "cost": "SWE-rebench Cost/Problem 優先 / 公式単価x標準トークン / null",
            "latency": "SWE-rebench Tokens/Problem / 30000 / null",
        },
        "checked_at": CHECKED,
        "category_source": CATEGORY_SOURCE,
        "sources_index": SOURCE_URL,
        "models": models,
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    n = len(models)
    cats = ("repo_bug_fix", "terminal", "document", "ocr", "image_generation")
    filled = sum(1 for m in models for c in cats if m["capability"][c] is not None)
    priced = sum(
        1
        for m in models
        if m["pricing"]["input_per_1m"] is not None
        or m["pricing"]["benchmark_cost_per_task"] is not None
    )
    print(f"wrote {OUT}")
    print(f"  {n} models, {filled}/{n * len(cats)} capability cells, {priced} priced")


if __name__ == "__main__":
    main()
