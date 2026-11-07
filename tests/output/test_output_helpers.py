"""画面 4 の表示変換helperを検証する。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from taqumi2026s_teame.optimization_contract import OptimizationResult

app_path = Path(__file__).parents[2] / "app"
if str(app_path) not in sys.path:
    sys.path.insert(0, str(app_path))

from output_helpers import (  # noqa: E402
    accuracy_reason,
    assignment_tree_dot,
    category_legend_html,
    comparison_rows,
    constraint_violations,
    model_legend_html,
    task_accuracy_reasons,
    task_plan_rows,
)


@pytest.fixture
def result() -> OptimizationResult:
    """helperテスト用の最適化結果を作成する。

    Returns:
        OptimizationResult: タスク別結果を含む成功結果。

    Example:
        ``result["task_results"]`` に2件のタスク結果が含まれる。
    """
    return {
        "status": "success",
        "optimal_assignment": {"T01": "model-a", "T02": "model-b"},
        "solve_time_seconds": 0.5,
        "total_cost": 2.0,
        "average_accuracy_score": 4.0,
        "message": "完了",
        "task_results": [
            {
                "task_id": "T01",
                "task_name": "設計",
                "selected_model": "model-a",
                "masking_enabled": True,
                "review_enabled": False,
                "review_model": None,
                "cost": 1.0,
                "accuracy_score": 3.5,
                "accuracy_reason": "設計能力を反映",
            },
            {
                "task_id": "T02",
                "task_name": "実装",
                "selected_model": "model-b",
                "masking_enabled": False,
                "review_enabled": True,
                "review_model": "reviewer",
                "cost": 1.0,
                "accuracy_score": 4.5,
            },
        ],
        "baseline": {
            "model": "model-a",
            "total_cost": 2.0,
            "average_accuracy_score": 3.5,
        },
    }


def test_task_plan_rows_maps_contract_fields(result: OptimizationResult) -> None:
    """タスク計画が契約の各フィールドを表示行へ変換することを確認する。

    Args:
        result (OptimizationResult): helperテスト用結果。

    Example:
        T02 のレビューモデルが保持される。
    """
    rows = task_plan_rows(
        [
            {"task_id": "T01", "task_name": "設計"},
            {"task_id": "T02", "task_name": "実装"},
        ],
        result["task_results"],
        result["optimal_assignment"],
    )

    assert len(rows) == 2
    assert rows[1]["レビューモデル"] == "reviewer"
    assert rows[0]["マスキング"] == "ON"


def _tree_tasks() -> list[dict[str, object]]:
    return [
        {
            "task_id": "T01",
            "task_name": "設計",
            "task_type": "code_gen",
            "is_confidential": False,
            "dependencies": [],
        },
        {
            "task_id": "T02",
            "task_name": "実装",
            "task_type": "code_fix",
            "is_confidential": True,
            "dependencies": ["T01"],
        },
    ]


def test_assignment_tree_dot_has_no_model_clusters(result: OptimizationResult) -> None:
    """モデルで囲むクラスタは作らず、タスクの依存関係だけで木構造にする。

    ノードの配置基準はタスクの親子関係（依存関係）であり、モデルは
    ノードの枠色で示すだけにする（囲みが階層の把握を邪魔しないように）。

    Args:
        result (OptimizationResult): helperテスト用結果。

    Example:
        出力に ``subgraph cluster_`` は一切含まれない。
    """
    dot = assignment_tree_dot(_tree_tasks(), result["task_results"], result["optimal_assignment"])

    assert dot.startswith("digraph assignment {")
    assert dot.strip().endswith("}")
    assert "subgraph cluster_" not in dot
    assert '"T01" -> "T02"' in dot
    assert "🔒" in dot  # T02 は機密タスク
    assert "model-a" in dot  # モデル名はノードのラベルに含める
    assert "model-b" in dot


def test_assignment_tree_dot_marks_unassigned_tasks_in_label(result: OptimizationResult) -> None:
    """割当が無いタスクは、クラスタではなくラベル上で「未割当」と分かる。"""
    dot = assignment_tree_dot(
        [{"task_id": "T03", "task_name": "保留中", "task_type": "code_gen"}],
        result["task_results"],
        result["optimal_assignment"],
    )

    assert "subgraph cluster_" not in dot
    assert "未割当" in dot
    assert '"T03"' in dot


def test_model_legend_html_lists_each_model_with_task_count(
    result: OptimizationResult,
) -> None:
    """凡例HTMLに、モデルごとの色スウォッチと担当件数が含まれる。"""
    legend = model_legend_html(_tree_tasks(), result["optimal_assignment"])

    assert "model-a" in legend
    assert "model-b" in legend
    assert "1件" in legend  # T01, T02 それぞれ1件ずつ担当


def test_model_legend_html_notes_unassigned_when_present() -> None:
    """未割当タスクがある場合、凡例に「未割当」の凡例チップが追加される。"""
    legend = model_legend_html(
        [{"task_id": "T03", "task_name": "保留中"}],
        {},
    )

    assert "未割当" in legend


def test_category_legend_html_lists_only_categories_in_use() -> None:
    """タスクに登場する種類（背景色の意味）だけが凡例に並ぶ。"""
    legend = category_legend_html(
        [
            {"task_id": "T01", "task_type": "code_gen"},  # -> repo_bug_fix
            {"task_id": "T02", "task_type": "ocr"},  # -> ocr
        ]
    )

    assert "コード" in legend or "バグ修正" in legend
    assert "OCR" in legend
    assert "画像生成" not in legend  # 登場していない種類は出さない


def test_category_legend_html_empty_when_no_tasks() -> None:
    """タスクが無ければ空文字列を返す。"""
    assert category_legend_html([]) == ""


def test_accuracy_helpers_explain_each_task(result: OptimizationResult) -> None:
    """精度理由helperが平均理由とタスク別理由を返すことを確認する。

    Args:
        result (OptimizationResult): helperテスト用結果。

    Example:
        明示された理由と補完された理由をそれぞれ取得できる。
    """
    reasons = task_accuracy_reasons(result["task_results"])

    assert "平均は 4.00" in accuracy_reason(result["task_results"])
    assert reasons[0]["理由"] == "設計能力を反映"
    assert "model-b" in str(reasons[1]["理由"])


def test_comparison_rows_include_baseline(result: OptimizationResult) -> None:
    """比較行に最適化後とベースラインが含まれることを確認する。

    「最適化前 → 最適化後」の時系列順（表・グラフで改善が読み取りやすい順）。

    Args:
        result (OptimizationResult): helperテスト用結果。

    Example:
        比較行が2件になる。
    """
    rows = comparison_rows(result)

    assert [row["条件"] for row in rows] == [
        "最適化前（1モデル固定）",
        "最適化後",
    ]
    assert rows[0]["精度スコア（平均）"] == 3.5


def test_constraint_helper_reports_missing_assignment(
    result: OptimizationResult,
) -> None:
    """未割当タスクを制約違反として説明することを確認する。

    Args:
        result (OptimizationResult): helperテスト用結果。

    Example:
        T03 が未割当として報告される。
    """
    violations = constraint_violations(
        {**result, "optimal_assignment": {"T01": "model-a"}},
        10.0,
        [{"task_id": "T01"}, {"task_id": "T03"}],
    )

    assert violations[0]["制約"] == "全タスク割当"
    assert "T03" in violations[0]["説明"]
