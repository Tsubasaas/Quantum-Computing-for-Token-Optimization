"""モデル能力DB（models.json）とタスク（sample_tasks.json）のローダ。

3 段構成:
  models.json           生のベンチマーク値・価格・出典（時点付き）
  -> synthesize_quality  役割ブレンドで Q_ja に合成、cost_for で C_ja
  -> load_agents / task_model_scores  QUBO へ渡すのは Q_ja / C_ja のみ
"""

from __future__ import annotations

import json
from importlib import resources
from typing import Any, cast

from ..models import Agent, Task
from .model_pool import usable_model_ids
from .task_types import ROLE_FACTOR, ROLES, blend_of, primary_capability

__all__ = [
    "load_models",
    "load_agents",
    "load_sample_tasks",
    "sample_request",
    "task_model_scores",
    "model_source_note",
    "source_index",
    "category_source",
    "synthesize_quality",
    "cost_for",
    "ROLES",
]

# コスト見積り用の既定トークン数（benchmark_cost_per_task も API 価格も無い時のフォールバック）
_EST_INPUT_TOKENS = 60_000
_EST_OUTPUT_TOKENS = 8_000


def _read_json(name: str) -> dict[str, Any]:
    with resources.files(__package__).joinpath(name).open("r", encoding="utf-8") as fh:
        return cast("dict[str, Any]", json.load(fh))


def load_models() -> list[dict[str, Any]]:
    """models.json のモデル配列をそのまま返す（能力マトリクス表示・出典確認用）。"""

    return cast("list[dict[str, Any]]", _read_json("models.json")["models"])


def source_index() -> dict[str, str]:
    """出典名 -> URL。"""

    return cast("dict[str, str]", _read_json("models.json").get("sources_index", {}))


def category_source() -> dict[str, str]:
    """能力カテゴリ -> 出典名（source_index のキー）。"""

    return cast("dict[str, str]", _read_json("models.json").get("category_source", {}))


def model_source_note() -> str:
    return (
        "能力値はすべて公開ベンチの実測（推定では埋めていない）: "
        "コード=SWE-rebench / ターミナル=Terminal-Bench 2.1 / "
        "文書・OCR・表・KIE・QA=IDP Leaderboard / 画像生成=Image Arena。"
        "値が無いカテゴリは「—」。算出方法は data/README.md。"
    )


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def synthesize_quality(model: dict[str, Any], role: str) -> float | None:
    """役割ブレンドで Q_ja を合成。主能力が未対応（null）なら None。"""

    cap = model.get("capability", {})
    blend = blend_of(role)
    primary = primary_capability(role)
    if cap.get(primary) is None:
        return None
    score = 0.0
    for key, weight in blend.items():
        val = cap.get(key)
        score += weight * (float(val) if val is not None else 0.0)
    return _clip01(score * ROLE_FACTOR.get(role, 1.0))


def _reliability(model: dict[str, Any], q: float) -> float:
    p5 = model.get("benchmark_scores", {}).get("swe_rebench_pass_at_5")
    if p5 is not None:
        return _clip01(float(p5))
    return _clip01(q + 0.10)


def cost_for(model: dict[str, Any], difficulty: int = 3) -> float:
    """C_ja（USD）。benchmark cost > API 価格見積り > フォールバック の順。"""

    pricing = model.get("pricing", {})
    mult = 1.0 + 0.12 * (difficulty - 3)
    bench = pricing.get("benchmark_cost_per_task")
    if bench is not None:
        return round(max(0.01, float(bench) * mult), 4)
    per_image = pricing.get("per_image")
    if per_image is not None and model.get("model_type") == "image":
        return round(max(0.001, float(per_image) * mult), 4)
    in_p, out_p = pricing.get("input_per_1m"), pricing.get("output_per_1m")
    if in_p is not None and out_p is not None:
        est = (float(in_p) * _EST_INPUT_TOKENS + float(out_p) * _EST_OUTPUT_TOKENS) / 1_000_000
        return round(max(0.01, est * mult), 4)
    return round(0.20 * mult, 4)  # open-weight など価格未記載


# SWE-rebench 未掲載で処理時間の実測がないモデルの既定値（秒）
_DEFAULT_LATENCY_SEC = 60.0


def _latency(model: dict[str, Any], difficulty: int = 3) -> float:
    raw = model.get("latency", {}).get("avg_task_completion_sec")
    base = float(raw) if raw is not None else _DEFAULT_LATENCY_SEC
    return round(base * (0.6 + 0.13 * difficulty), 1)


def load_agents(*, only_usable: bool = False) -> list[Agent]:
    """models.json の全モデルを :class:`Agent` にして返す。

    Args:
        only_usable: True なら :mod:`taqumi2026s_teame.data.model_pool` の
            選別（旧バージョン・ベンチ専用モデルの除外）を適用する。既定は
            False（後方互換。旧 4 画面・テストは全モデルを見る）。
    """

    models = load_models()
    if only_usable:
        allowed = set(usable_model_ids(m["model_id"] for m in models))
        models = [m for m in models if m["model_id"] in allowed]
    agents: list[Agent] = []
    for m in models:
        quality: dict[str, float] = {}
        reliability: dict[str, float] = {}
        for role in ROLES:
            q = synthesize_quality(m, role)
            if q is None:
                continue
            quality[role] = q
            reliability[role] = _reliability(m, q)
        # 社外扱い = 社外 API かつ 自社ホスティング不可
        is_external = bool(m.get("external_api", True)) and not bool(
            m.get("local_available", False)
        )
        agents.append(
            Agent(
                id=m["model_id"],
                name=m["model_name"],
                layer="agent" if m.get("is_agent") else "model",
                external=is_external,
                quality=quality,
                reliability=reliability,
                cost_per_task=cost_for(m, 3),
                latency_sec=_latency(m, 3),
                max_tasks=m.get("max_tasks"),
                provider=m.get("provider", ""),
                model_type=m.get("model_type", "llm"),
                is_agent=bool(m.get("is_agent", False)),
                agent_harness=m.get("agent_harness"),
                context_window=m.get("context_window"),
                capability=dict(m.get("capability", {})),
                pricing=dict(m.get("pricing", {})),
            )
        )
    return agents


def task_model_scores(
    tasks: list[Task], agents: list[Agent]
) -> dict[str, dict[str, dict[str, float]]]:
    """QUBO 前処理の中間テーブル: ``{task_id: {model_id: {"Q":.., "C":.., "t":..}}}``。

    Q_ja を持たない（担当不可の）組み合わせは含めない。
    """

    models_by_id = {m["model_id"]: m for m in load_models()}
    table: dict[str, dict[str, dict[str, float]]] = {}
    for t in tasks:
        row: dict[str, dict[str, float]] = {}
        for a in agents:
            if not a.can_do(t.role):
                continue
            if t.confidential and a.external:
                continue
            m = models_by_id[a.id]
            row[a.id] = {
                "Q": round(a.q(t.role) * _difficulty_factor(t.difficulty), 4),
                "C": cost_for(m, t.difficulty),
                "t": _latency(m, t.difficulty),
            }
        table[t.id] = row
    return table


def _difficulty_factor(difficulty: int) -> float:
    return max(0.0, 1.0 - 0.12 * (difficulty - 1))


def _to_task(d: dict[str, Any]) -> Task:
    role = d.get("role", "code_gen")
    if role not in ROLES:
        role = "code_gen"
    return Task(
        id=str(d["id"]),
        title=str(d["title"]),
        role=role,
        difficulty=int(d.get("difficulty", 3)),
        priority=int(d.get("priority", 3)),
        est_time=float(d.get("est_time", 2.0)),
        dependencies=[str(x) for x in d.get("dependencies", [])],
        confidential=bool(d.get("confidential", False)),
    )


def load_sample_tasks() -> list[Task]:
    return [_to_task(d) for d in _read_json("sample_tasks.json")["tasks"]]


def sample_request() -> str:
    return str(_read_json("sample_tasks.json").get("request", ""))
