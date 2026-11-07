"""選択プランの会話レビューを、外部 API なしで検証する。"""

from __future__ import annotations

from taqumi2026s_teame.llm.plan_assistant import review_plan
from taqumi2026s_teame.plans import Plan


def _plan(kind: str, label: str, cost: float, quality: float) -> Plan:
    plan = Plan(
        kind=kind,  # type: ignore[arg-type]
        label=label,
        budget_cap=cost + 1,
        result={},  # type: ignore[arg-type]
        status="feasible",
        total_budget=20,
    )
    plan.total_cost = cost
    plan.expected_quality = quality
    plan.workload_hours = 8
    return plan


def test_local_review_recommends_the_cheapest_plan(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    plans = [
        _plan("cost", "コスト重視", 2, 3.2),
        _plan("balanced", "バランス", 5, 4.0),
        _plan("quality", "精度重視", 9, 4.8),
    ]

    review = review_plan(
        "もっと安い案にしたい",
        selected=plans[1],
        plans=plans,
        tasks=[],
    )

    assert review.recommended_plan_kind == "cost"
    assert "コスト重視" in review.content
    assert review.used_llm is False


def test_local_review_recommends_the_highest_quality_plan(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    plans = [
        _plan("cost", "コスト重視", 2, 3.2),
        _plan("balanced", "バランス", 5, 4.0),
        _plan("quality", "精度重視", 9, 4.8),
    ]

    review = review_plan(
        "費用より品質を優先してください",
        selected=plans[1],
        plans=plans,
        tasks=[],
    )

    assert review.recommended_plan_kind == "quality"
    assert "4.80/5.00" in review.content
