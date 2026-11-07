"""選択済み実行プランを会話でレビューするアシスタント。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from ..models import Task
from ..plans import Plan, PlanKind

DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
MAX_HISTORY_MESSAGES = 10


@dataclass(slots=True)
class PlanReview:
    """会話への返答と、利用者が明示的に適用できる推奨プラン。"""

    content: str
    recommended_plan_kind: PlanKind | None = None
    used_llm: bool = False


def _plan_data(plan: Plan) -> dict[str, Any]:
    return {
        "kind": plan.kind,
        "label": plan.label,
        "status": plan.status,
        "budget_cap_usd": plan.budget_cap,
        "total_cost_usd": plan.total_cost,
        "expected_quality_5": plan.expected_quality,
        "workload_hours": plan.workload_hours,
        "image_count": plan.image_count,
        "distinct_models": plan.distinct_models,
        "task_count_by_category": plan.task_count_by_category,
        "infeasible_reason": plan.infeasible_reason,
    }


def _context(selected: Plan, plans: list[Plan], tasks: list[Task]) -> str:
    payload = {
        "selected_plan": selected.kind,
        "plans": [_plan_data(plan) for plan in plans],
        "tasks": [
            {
                "id": task.id,
                "title": task.title,
                "role": task.role,
                "difficulty": task.difficulty,
                "priority": task.priority,
                "estimated_hours": task.est_time,
                "quantity": task.quantity,
                "confidential": task.confidential,
                "dependencies": task.dependencies,
            }
            for task in tasks
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


def _available_kinds(plans: list[Plan]) -> set[str]:
    return {plan.kind for plan in plans if plan.runnable}


def _local_review(message: str, selected: Plan, plans: list[Plan]) -> PlanReview:
    """API 未設定・障害時にも比較データだけで根拠ある回答を返す。"""

    text = message.lower()
    available = [plan for plan in plans if plan.runnable]
    recommended = selected
    reason = "現在選択中の案が、指定された条件に最も近い候補です。"

    if available and any(word in text for word in ("安", "節約", "コスト", "予算")):
        recommended = min(available, key=lambda plan: plan.total_cost)
        reason = "費用を抑える意図を優先し、実行可能な案のうち合計費用が最小のものを選びました。"
    elif available and any(word in text for word in ("品質", "精度", "高品質", "クオリティ")):
        recommended = max(
            available,
            key=lambda plan: plan.expected_quality if plan.expected_quality is not None else -1,
        )
        reason = "品質を優先し、実行可能な案のうち期待品質が最も高いものを選びました。"
    elif available and any(word in text for word in ("バランス", "標準", "無難")):
        recommended = next((plan for plan in available if plan.kind == "balanced"), selected)
        reason = "費用と品質の両立を重視し、バランス案を候補にしました。"

    quality = (
        f"{recommended.expected_quality:.2f}/5.00"
        if recommended.expected_quality is not None
        else "算出なし"
    )
    changed = recommended.kind != selected.kind
    next_action = (
        "下のボタンでこの提案へ切り替えられます。"
        if changed
        else "現在の選択を維持するのが妥当です。"
    )
    return PlanReview(
        content=(
            f"**提案: {recommended.label}**\n\n"
            f"{reason} 合計費用は ${recommended.total_cost:,.4f}、期待品質は {quality}、"
            f"作業量は {recommended.workload_hours:,.1f} 時間です。{next_action}\n\n"
            "タスク内容そのものを変える場合は、上のタスク一覧を修正してからプランを再計算してください。"
        ),
        recommended_plan_kind=recommended.kind if changed else None,
        used_llm=False,
    )


def _coerce_review(raw: str, plans: list[Plan]) -> PlanReview:
    data = json.loads(raw)
    content = str(data.get("reply") or "").strip()
    if not content:
        raise ValueError("LLM の返答が空です。")
    kind = str(data.get("recommended_plan_kind") or "").strip()
    allowed = _available_kinds(plans)
    recommendation: PlanKind | None = None
    if kind in allowed and kind in {"cost", "balanced", "quality"}:
        recommendation = kind  # type: ignore[assignment]
    return PlanReview(content=content, recommended_plan_kind=recommendation, used_llm=True)


def review_plan(
    message: str,
    *,
    selected: Plan,
    plans: list[Plan],
    tasks: list[Task],
    history: list[dict[str, object]] | None = None,
) -> PlanReview:
    """選択プランを LLM でレビューし、失敗時はローカル比較へフォールバックする。"""

    message = (message or "").strip()
    if not message:
        raise ValueError("メッセージを入力してください。")

    groq_key = os.getenv("GROQ_API_KEY")
    api_key = groq_key or os.getenv("OPENAI_API_KEY")
    if not api_key:
        return _local_review(message, selected, plans)

    from openai import OpenAI

    base_url = (
        os.getenv("GROQ_BASE_URL") or GROQ_BASE_URL
        if groq_key
        else os.getenv("OPENAI_BASE_URL") or None
    )
    model = os.getenv(
        "GROQ_MODEL" if groq_key else "OPENAI_MODEL",
        DEFAULT_GROQ_MODEL if groq_key else "gpt-4o-mini",
    )
    system = (
        "あなたは実行プランのレビュー担当です。与えられた計算済みデータだけを根拠に、"
        "ユーザーのニーズを確認しながら費用・品質・作業量・依存関係のトレードオフを日本語で説明してください。"
        "未計算の数値や実行結果を捏造してはいけません。プラン切替で対応できないタスク変更は、"
        "上流のタスク一覧を編集して再計算するよう案内してください。返答は JSON のみとし、"
        "reply に回答、recommended_plan_kind に cost/balanced/quality/null のいずれかを"
        "入れてください。"
        "実行不可のプランは推奨してはいけません。\n計算済みデータ: "
        + _context(selected, plans, tasks)
    )
    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    for item in (history or [])[-MAX_HISTORY_MESSAGES:]:
        role = str(item.get("role") or "")
        content = str(item.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content[:4000]})
    messages.append({"role": "user", "content": message[:4000]})

    try:
        completion_args: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        }
        response = OpenAI(api_key=api_key, base_url=base_url).chat.completions.create(
            **completion_args
        )
        return _coerce_review(response.choices[0].message.content or "{}", plans)
    except Exception:  # noqa: BLE001 - 会話 UI を API/通信/JSON 障害で止めない
        fallback = _local_review(message, selected, plans)
        fallback.content += (
            "\n\n※ AI APIに接続できなかったため、今回は計算済みデータで回答しました。"
        )
        return fallback
