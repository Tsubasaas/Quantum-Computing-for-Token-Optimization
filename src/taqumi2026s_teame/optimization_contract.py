"""「最適化実行」機能の入出力契約（Contract First）。

上流「推奨案＋人間判断UI」からの入力 (:class:`OptimizationInput`) と、
Solver/QUBO 実行後の出力 (:class:`OptimizationResult`) の形を固定する。
上流・Solver・下流のどの実装が Mock / 本実装であっても、この型に従う限り
差し替え可能にすることが目的。
"""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict


class TaskInput(TypedDict):
    """最適化対象タスク 1 件の入力情報。

    Attributes:
        task_id (str): タスクを一意に識別する ID。
        task_name (str): タスク名。
    """

    task_id: str
    task_name: str
    task_type: NotRequired[str | None]
    importance: NotRequired[int | None]
    difficulty: NotRequired[int | None]
    workload: NotRequired[float | None]
    is_confidential: NotRequired[bool | None]
    dependencies: NotRequired[list[str] | None]
    reference_file_name: NotRequired[str | None]
    # 成果物の個数（画像なら生成枚数）。省略時は 1。コストが quantity 倍になる。
    quantity: NotRequired[int | None]


OptimizationWeights = dict[str, float]


class OptimizationInput(TypedDict):
    """最適化実行 UI が上流から受け取る入力（``st.session_state["optimization_input"]``）。

    Attributes:
        tasks (list[TaskInput]): 割当対象タスクの一覧。
        candidate_models (list[str]): 候補モデル名の一覧。
        model_capability_matrix (dict[str, dict[str, object]]): モデルごとの能力・価格・出典情報。
        optimization_weights (OptimizationWeights): 上流が定義した重みをキー変換せず保持する。
        budget_limit (float): 予算上限。
        max_completion_time (float | None): 最大完了時間（秒）。Noneは上流値のまま保持する。
        masking_enabled (bool): マスキング機能の有効/無効。
        optimization_mode (str): 最適化モード（例: "バランス"）。
        solver (NotRequired[str]): 使用するソルバ（"amplify"、"dwave"、"greedy"）。
    """

    tasks: list[TaskInput]
    candidate_models: list[str]
    model_capability_matrix: dict[str, dict[str, object]]
    optimization_weights: OptimizationWeights
    budget_limit: float
    max_completion_time: float | None
    masking_enabled: bool
    optimization_mode: str
    solver: NotRequired[str]


class TaskResult(TypedDict):
    """タスクごとの最適化結果（下流「アウトプットUI」向け）。

    Attributes:
        task_id (str): タスク ID。
        task_name (str): タスク名。
        selected_model (str): 選択されたモデル名。
        masking_enabled (bool): このタスクでマスキングが有効だったか。
        review_enabled (bool): レビュー工程が有効だったか。
        review_model (str | None): レビューに使用したモデル（未使用時は None）。
        cost (float): このタスクのコスト。
        accuracy_score (float): このタスクの精度スコア。
    """

    task_id: str
    task_name: str
    selected_model: str
    masking_enabled: bool
    review_enabled: bool
    review_model: str | None
    cost: float
    accuracy_score: float
    accuracy_reason: NotRequired[str]
    # 画面表示用の付帯情報（最適化には使わない）。
    model_display_name: NotRequired[str]
    plan_category: NotRequired[str]
    quantity: NotRequired[int]


class BaselineResult(TypedDict):
    """全タスクを単一モデルで実行した場合の比較結果。"""

    model: str
    total_cost: float
    average_accuracy_score: float


OptimizationStatus = Literal["success", "timeout", "error"]


class OptimizationResult(TypedDict):
    """最適化実行後に生成する共通結果（``st.session_state["optimization_result"]``）。

    Attributes:
        status (OptimizationStatus): "success" | "timeout" | "error"。
        optimal_assignment (dict[str, str]): task_id -> selected_model。
        solve_time_seconds (float): 求解にかかった時間（秒）。
        total_cost (float): 総コスト。
        average_accuracy_score (float): タスク別精度スコアの平均（0〜5）。
        message (str): ユーザー向けメッセージ。
        task_results (NotRequired[list[TaskResult]]): タスクごとの詳細結果（下流 UI 向け・任意）。
        baseline (NotRequired[BaselineResult]): 単一モデル固定時の比較結果。
        feasible (NotRequired[bool]): 全制約（能力・機密・予算）を満たしたか。
        within_budget (NotRequired[bool]): 総コストが予算上限以下か。
        violations (NotRequired[int]): 制約違反の件数。
        solver_method (NotRequired[str]): 実際に解いた手法（"amplify" | "dwave" | "greedy"）。
        solver_error (NotRequired[str]): 選択ソルバが失敗した場合の内部エラー情報。UI変換用。
    """

    status: OptimizationStatus
    optimal_assignment: dict[str, str]
    solve_time_seconds: float
    total_cost: float
    average_accuracy_score: float
    message: str
    task_results: NotRequired[list[TaskResult]]
    baseline: NotRequired[BaselineResult]
    # 実行可否の判定材料。UI が「この予算では実行できない」を出し分けるために使う。
    # 省略時は「判定情報なし」であり、実行可能と読み替えてはいけない。
    feasible: NotRequired[bool]
    within_budget: NotRequired[bool]
    violations: NotRequired[int]
    solver_method: NotRequired[str]
    solver_error: NotRequired[str]


def average_accuracy_score(result: OptimizationResult) -> float:
    """最適化結果からタスク別精度スコアの平均を算出する。

    Args:
        result (OptimizationResult): 最適化結果。

    Returns:
        float: 0〜5 に収めた平均精度スコア。
    """
    task_results = result.get("task_results", [])
    scores = [
        float(item["accuracy_score"])
        for item in task_results
        if item.get("accuracy_score") is not None
    ]
    if scores:
        return max(0.0, min(5.0, sum(scores) / len(scores)))
    return max(0.0, min(5.0, float(result["average_accuracy_score"])))
