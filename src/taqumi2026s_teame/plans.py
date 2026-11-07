"""「コスト重視 / バランス / 精度重視」の 3 プランを組み立てる。

3 案の違いは **予算上限の刻み**（利用者の最大予算の 30% / 60% / 100%）と、
既存の編成モード重み（:data:`taqumi2026s_teame.config.MODE_WEIGHTS`）だけで作る。
求解そのものは既存の :func:`run_optimization` をそのまま呼ぶので、QUBO の目的関数・
制約（C1/C2/C3）は変更していない。

3 案に差をつけるためにモデル名や品質を後から書き換えることはしない。上限が違っても
同じ配分になる場合は、そのまま同じ配分として返す（``identical_plan_kinds`` で検出）。

本モジュールは全体が生成 AI（Claude）支援で作成されています。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .config import MODE_WEIGHTS
from .data.task_types import PLAN_CATEGORIES, plan_category_of
from .models import Task
from .optimization_contract import OptimizationInput, OptimizationResult
from .solvers.optimization_real_solver import run_optimization
from .workflow import levels

__all__ = [
    "Plan",
    "PlanKind",
    "PlanStatus",
    "PLAN_SPECS",
    "build_plans",
    "identical_plan_kinds",
]

PlanKind = Literal["cost", "balanced", "quality"]

# 比較カードの 4 状態（仕様 §4.D）。「予算が原因かどうか」で扱いを完全に分ける。
#   feasible    : この案の目安上限に収まった。
#   over_cap    : 目安上限は超えたが、利用者の総予算には収まる。実行できる。
#   over_budget : 総予算でも足りない。実行できないので不足額を出す。
#   unavailable : 予算とは無関係の理由（担当できるモデルが無い・求解失敗）。金額は出さない。
PlanStatus = Literal["feasible", "over_cap", "over_budget", "unavailable"]

# (kind, 画面表示名, 予算上限の比率, config.MODE_WEIGHTS のキー)
PLAN_SPECS: list[tuple[PlanKind, str, float, str]] = [
    ("cost", "コスト重視", 0.30, "コスト優先"),
    ("balanced", "バランス", 0.60, "バランス"),
    ("quality", "精度重視", 1.00, "精度優先"),
]

_BUDGET_EXCEEDED = (
    "この予算では全タスクを実行できません。\n予算を増やすか、生成する画像枚数を減らしてください。"
)
_SOLVER_FAILED = "最適化に失敗しました。"
_NO_CAPABLE_MODEL = (
    "候補モデルの中に、担当できるモデルが無いタスクがあります。\n"
    "候補モデルを増やすか、タスクの種類を見直してください。"
)


@dataclass(slots=True)
class Plan:
    """1 プラン分の求解結果と、比較カードに出す集計値。"""

    kind: PlanKind
    label: str
    budget_cap: float
    result: OptimizationResult
    status: PlanStatus
    # 利用者が指定した最大予算。over_cap と over_budget を切り分けるために持つ。
    total_budget: float = 0.0
    infeasible_reason: str = ""
    total_cost: float = 0.0
    expected_quality: float | None = None  # 0-5。タスク別精度の平均
    cost_by_category: dict[str, float] = field(default_factory=dict)
    task_count_by_category: dict[str, int] = field(default_factory=dict)
    image_count: int = 0
    workload_hours: float = 0.0
    distinct_models: int = 0
    workflow_levels: list[list[str]] = field(default_factory=list)
    solver_method: str = ""

    @property
    def feasible(self) -> bool:
        """この案の目安上限に収まっているか。"""

        return self.status == "feasible"

    @property
    def runnable(self) -> bool:
        """選択して実行できるか。

        目安上限（総予算の 30 / 60 / 100%）は 3 案に幅を出すための内部的な刻みであって、
        利用者と約束した制約ではない。利用者の制約は総予算だけなので、目安上限を超えていても
        総予算に収まるなら選択・実行できる。
        """

        return self.status in ("feasible", "over_cap")

    @property
    def overrun(self) -> float:
        """目安上限をいくら超えたか。超えていなければ 0。"""

        return round(max(0.0, self.total_cost - self.budget_cap), 4)

    @property
    def shortfall(self) -> float:
        """総予算に対していくら足りないか。足りていれば 0。"""

        return round(max(0.0, self.total_cost - self.total_budget), 4)

    @property
    def assignment(self) -> dict[str, str]:
        return dict(self.result.get("optimal_assignment", {}))

    @property
    def text_cost(self) -> float:
        """文書・コードタスクの費用合計。"""

        return round(
            self.cost_by_category.get("doc", 0.0)
            + self.cost_by_category.get("code", 0.0),
            4,
        )

    @property
    def image_cost(self) -> float:
        return round(self.cost_by_category.get("image", 0.0), 4)


def _to_input(
    tasks: list[Task],
    candidate_models: list[str],
    budget_cap: float,
    mode_key: str,
    *,
    masking_enabled: bool,
    time_limit_sec: int,
    solver: str,
) -> OptimizationInput:
    weights = MODE_WEIGHTS[mode_key]
    return {
        "tasks": [
            {
                "task_id": t.id,
                "task_name": t.title,
                "task_type": t.role,
                "importance": t.priority,
                "difficulty": t.difficulty,
                "workload": t.est_time,
                "is_confidential": t.confidential,
                "dependencies": list(t.dependencies),
                "quantity": max(1, int(t.quantity)),
            }
            for t in tasks
        ],
        "candidate_models": list(candidate_models),
        "model_capability_matrix": {},
        "optimization_weights": {
            "alpha": weights.alpha,
            "beta": weights.beta,
            "gamma": weights.gamma,
            "mu": weights.mu,
        },
        "budget_limit": float(budget_cap),
        "max_completion_time": float(time_limit_sec),
        "masking_enabled": masking_enabled,
        "optimization_mode": mode_key,
        "solver": solver,
    }


def _summarize(plan: Plan, tasks: list[Task]) -> None:
    """求解結果からカード表示用の集計値を埋める（plan を破壊的に更新）。"""

    task_results = plan.result.get("task_results", [])
    by_id = {t.id: t for t in tasks}

    cost_by_category = dict.fromkeys(PLAN_CATEGORIES, 0.0)
    count_by_category = dict.fromkeys(PLAN_CATEGORIES, 0)
    image_count = 0
    total = 0.0
    for item in task_results:
        task = by_id.get(item["task_id"])
        if task is None:
            continue
        category = plan_category_of(task.role)
        cost = float(item["cost"])
        cost_by_category[category] += cost
        count_by_category[category] += 1
        total += cost
        if category == "image":
            image_count += max(1, int(task.quantity))

    plan.cost_by_category = {k: round(v, 4) for k, v in cost_by_category.items()}
    plan.task_count_by_category = count_by_category
    plan.image_count = image_count
    # 合計はタスク別内訳の和にそろえる（カードと内訳表で数字が食い違わないように）。
    plan.total_cost = round(total, 4)
    plan.workload_hours = round(sum(t.est_time for t in tasks), 1)
    plan.distinct_models = len({item["selected_model"] for item in task_results})
    plan.expected_quality = (
        round(
            sum(float(i["accuracy_score"]) for i in task_results) / len(task_results), 2
        )
        if task_results
        else None
    )
    plan.workflow_levels = levels([t for t in tasks if t.id in plan.assignment])
    plan.solver_method = str(plan.result.get("solver_method", ""))


def _judge(plan: Plan, tasks: list[Task]) -> None:
    """4 状態のどれかを決める（plan を破壊的に更新）。

    ``feasible`` が結果に無い場合は「判定できない」として実行不可側に倒す。
    丸めた表示値ではなく、求解器が返した高精度の値と予算を突き合わせる。

    予算が原因の不可（over_cap / over_budget）と、予算では解決しない不可（unavailable）を
    区別する。前者は金額で説明できるが、後者は予算を増やしても直らないので、画面で赤い
    金額を出すと誤った誘導になる。
    """

    result = plan.result
    if result["status"] != "success":
        plan.status = "unavailable"
        plan.infeasible_reason = str(result.get("message") or _SOLVER_FAILED)
        return

    assigned = set(plan.assignment)
    unassigned = [t.id for t in tasks if t.id not in assigned]
    # violations は予算を含まない制約違反の件数（未割当・禁止割当・容量超過）。
    # metric.feasible は予算超過でも False になるので、こちらを見ないと
    # 「予算が理由の不可」と「予算では直らない不可」を切り分けられない。
    if unassigned or int(result.get("violations", 0)) > 0:
        plan.status = "unavailable"
        plan.infeasible_reason = _NO_CAPABLE_MODEL
        return

    # ここから先は割当そのものは成立している。残る論点は金額だけ。
    cost = float(result["total_cost"])
    if cost > plan.total_budget + 1e-6:
        plan.status = "over_budget"
        plan.infeasible_reason = _BUDGET_EXCEEDED
        return

    if cost > plan.budget_cap + 1e-6:
        plan.status = "over_cap"
        plan.infeasible_reason = ""
        return

    # 予算内・違反なしなのに feasible が立たない場合は、判定できないものとして
    # 実行不可側へ倒す（金額は出さない）。
    if not bool(result.get("feasible", False)) or not bool(result.get("within_budget", False)):
        plan.status = "unavailable"
        plan.infeasible_reason = _NO_CAPABLE_MODEL
        return

    plan.status = "feasible"
    plan.infeasible_reason = ""


def build_plans(
    tasks: list[Task],
    candidate_models: list[str],
    budget: float,
    *,
    masking_enabled: bool = False,
    time_limit_sec: int = 3,
    solver: str = "amplify",
) -> list[Plan]:
    """コスト重視 / バランス / 精度重視の 3 プランを求解して返す。

    Args:
        tasks (list[Task]): 割当対象のタスク。
        candidate_models (list[str]): 候補モデルの model_id。
        budget (float): 利用者が指定した最大予算（USD）。各案はこの 30/60/100%。
        masking_enabled (bool): マスキング設定（結果へそのまま渡すだけ）。
        time_limit_sec (int): 1 プランあたりの求解時間上限（秒）。
        solver (str): 使用するソルバ（"amplify"、"dwave"、"greedy"）。

    Returns:
        list[Plan]: PLAN_SPECS の順（コスト重視 → バランス → 精度重視）。

    Raises:
        ValueError: タスクまたは候補モデルが空の場合。
    """

    if not tasks:
        raise ValueError("タスクがありません。")
    if not candidate_models:
        raise ValueError("候補モデルがありません。")

    plans: list[Plan] = []
    for kind, label, ratio, mode_key in PLAN_SPECS:
        budget_cap = round(float(budget) * ratio, 4)
        result = run_optimization(
            _to_input(
                tasks,
                candidate_models,
                budget_cap,
                mode_key,
                masking_enabled=masking_enabled,
                time_limit_sec=time_limit_sec,
                solver=solver,
            )
        )
        plan = Plan(
            kind=kind,
            label=label,
            budget_cap=budget_cap,
            result=result,
            status="unavailable",
            total_budget=float(budget),
        )
        _summarize(plan, tasks)
        _judge(plan, tasks)
        plans.append(plan)
    return plans


def identical_plan_kinds(plans: list[Plan]) -> list[list[PlanKind]]:
    """割当が完全に同じプランの組を返す。

    予算上限が違っても最適な配分が変わらないことは普通に起きる。画面ではこれを
    「差がある」と見せず、同じであると明示するために使う。
    """

    groups: dict[tuple[tuple[str, str], ...], list[PlanKind]] = {}
    for plan in plans:
        if not plan.runnable:
            continue
        signature = tuple(sorted(plan.assignment.items()))
        groups.setdefault(signature, []).append(plan.kind)
    return [kinds for kinds in groups.values() if len(kinds) > 1]
