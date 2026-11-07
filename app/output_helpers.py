"""画面 4 の最適化結果表示用ヘルパー。"""

from __future__ import annotations

from taqumi2026s_teame.data.task_types import CATEGORIES, CATEGORY_LABELS, category_of
from taqumi2026s_teame.optimization_contract import (
    OptimizationResult,
    average_accuracy_score,
)

# タスクの種類(task_type)ごとの塗り色。カテゴリ間の見分けがつくよう、
# 彩度を上げた5色を使う（薄すぎる淡色だと隣接カテゴリと区別しづらいため）。
# app/ui_helpers.py の _CATEGORY_FILL と揃えているが、output_helpers.py は
# streamlit に依存させたくないためここに複製する。
_CATEGORY_FILL: dict[str, str] = {
    "repo_bug_fix": "#8FD4A8",
    "terminal": "#8EC5F0",
    "document": "#B4A0E8",
    "ocr": "#F5B860",
    "image_generation": "#EF95AC",
}
# モデルごとの識別色（ノードの枠線）。ダークテーマの黒に近い背景でも沈まず、
# かつ互いに混同しにくいよう、色相を大きく離した明るめの10色にしている
# （旧パレットは灰色・オリーブ・濃茶等が暗背景でほぼ見えなくなっていた）。
_MODEL_COLORS: tuple[str, ...] = (
    "#4C9AFF",  # 青
    "#36B37E",  # 緑
    "#FFAB00",  # 琥珀
    "#FF5630",  # 赤橙
    "#8777D9",  # 紫
    "#00C7E6",  # シアン
    "#FF6B9D",  # ピンク
    "#B0D944",  # 黄緑
    "#00A3A3",  # ティール
    "#C93FD3",  # マゼンタ
)


def _dot_escape(text: object, limit: int | None = None) -> str:
    """DOTラベル用にダブルクォート・改行を除去し、必要なら長い文字列を省略する。

    Graphviz のノードはラベルの内容に合わせて箱の大きさが自動で広がるため、
    既定では省略しない（タスク名などが「見切れる」原因になるため）。

    Args:
        text (object): 元の文字列（またはそれに変換できる値）。
        limit (int | None): 省略前の最大文字数。``None`` なら省略しない。

    Returns:
        str: DOTラベルに埋め込める文字列。
    """

    escaped = str(text).replace('"', "'").replace("\n", " ").strip()
    if limit is not None and len(escaped) > limit:
        escaped = escaped[: limit - 1] + "…"
    return escaped


def model_color_map(tasks_: object, assignments: object) -> dict[str, str]:
    """タスク一覧に登場するモデルへ、識別色を割り当てる。

    ``assignment_tree_dot`` と ``model_legend_html`` の両方で同じ色対応を
    使うための共通処理（モデル名 → 色の対応がずれないようにする）。

    Args:
        tasks_ (object): optimization_input のタスク一覧。
        assignments (object): task_id -> selected_model の割当辞書。

    Returns:
        dict[str, str]: モデル名 -> カラーコードの対応。登場順。
    """

    task_list = [t for t in (tasks_ if isinstance(tasks_, list) else []) if isinstance(t, dict)]
    assignment_by_id = assignments if isinstance(assignments, dict) else {}
    models: list[str] = []
    for task in task_list:
        model = str(assignment_by_id.get(str(task.get("task_id", ""))) or "").strip()
        if model and model not in models:
            models.append(model)
    return {model: _MODEL_COLORS[i % len(_MODEL_COLORS)] for i, model in enumerate(models)}


def model_legend_html(tasks_: object, assignments: object) -> str:
    """assignment_tree_dot の枠色に対応する、モデル名の凡例HTMLを作る。

    Args:
        tasks_ (object): optimization_input のタスク一覧。
        assignments (object): task_id -> selected_model の割当辞書。

    Returns:
        str: ``st.markdown(..., unsafe_allow_html=True)`` に渡せるHTML。
    """

    task_list = [t for t in (tasks_ if isinstance(tasks_, list) else []) if isinstance(t, dict)]
    assignment_by_id = assignments if isinstance(assignments, dict) else {}
    counts: dict[str, int] = {}
    has_unassigned = False
    for task in task_list:
        model = str(assignment_by_id.get(str(task.get("task_id", ""))) or "").strip()
        if model:
            counts[model] = counts.get(model, 0) + 1
        else:
            has_unassigned = True

    chips = []
    for model, color in model_color_map(tasks_, assignments).items():
        chips.append(
            '<span style="display:inline-flex;align-items:center;gap:0.4em;'
            'margin:2px 10px 2px 0;font-size:12px;">'
            f'<span style="width:1.1em;height:1.1em;border-radius:3px;'
            f'background:{color};display:inline-block;"></span>'
            f"{model}（{counts.get(model, 0)}件）</span>"
        )
    if has_unassigned:
        chips.append(
            '<span style="display:inline-flex;align-items:center;gap:0.4em;'
            'margin:2px 10px 2px 0;font-size:12px;color:#8A92A0;">'
            '<span style="width:1.1em;height:1.1em;border-radius:3px;'
            'border:1.5px dashed #8A92A0;display:inline-block;"></span>'
            "未割当</span>"
        )
    return "".join(chips)


def category_legend_html(tasks_: object) -> str:
    """assignment_tree_dot のノード背景色（タスクの種類）の凡例HTMLを作る。

    背景色はモデルではなく、タスクの種類（能力カテゴリ）を表す。枠線の色
    （:func:`model_legend_html`）と意味が異なるため、別の凡例として示す。

    Args:
        tasks_ (object): optimization_input のタスク一覧。

    Returns:
        str: ``st.markdown(..., unsafe_allow_html=True)`` に渡せるHTML。
             登場するタスクの種類が無ければ空文字列。
    """

    task_list = [t for t in (tasks_ if isinstance(tasks_, list) else []) if isinstance(t, dict)]
    seen: set[str] = {category_of(str(task.get("task_type", ""))) for task in task_list}

    chips = []
    for cat in CATEGORIES:
        if cat not in seen:
            continue
        chips.append(
            '<span style="display:inline-flex;align-items:center;gap:0.4em;'
            'margin:2px 10px 2px 0;font-size:12px;">'
            f'<span style="width:1.1em;height:1.1em;border-radius:3px;'
            f'background:{_CATEGORY_FILL.get(cat, "#EEF1F4")};'
            'display:inline-block;"></span>'
            f"{CATEGORY_LABELS.get(cat, cat)}</span>"
        )
    return "".join(chips)


def assignment_tree_dot(tasks_: object, task_results_: object, assignments: object) -> str:
    """タスクの依存関係を木構造の Graphviz DOT にする（主軸はタスクの階層）。

    ノードの配置はタスクの依存関係（親タスク→子タスク）だけで決まる。
    どのモデルが選ばれたかは、モデルで囲むのではなくノードの枠線の色で示す
    （枠色の対応は :func:`model_legend_html` が別途凡例として返す）。

    Args:
        tasks_ (object): optimization_input のタスク一覧。
        task_results_ (object): optimization_result のタスク別結果。
        assignments (object): task_id -> selected_model の割当辞書。

    Returns:
        str: ``st.graphviz_chart`` にそのまま渡せる DOT 形式の文字列。
    """

    task_list = [t for t in (tasks_ if isinstance(tasks_, list) else []) if isinstance(t, dict)]
    result_by_id = {
        str(item.get("task_id")): item
        for item in (task_results_ if isinstance(task_results_, list) else [])
        if isinstance(item, dict) and item.get("task_id")
    }
    assignment_by_id = assignments if isinstance(assignments, dict) else {}
    task_by_id = {str(t.get("task_id")): t for t in task_list}
    color_of = model_color_map(tasks_, assignments)

    def node_line(task: dict[str, object]) -> str:
        task_id = str(task.get("task_id", ""))
        detail = result_by_id.get(task_id, {})
        model = str(assignment_by_id.get(task_id) or "").strip()
        confidential = bool(task.get("is_confidential"))
        border = color_of.get(model, "#8A92A0")
        style = "filled,rounded,dashed" if confidential else "filled,rounded"
        pen = "2.8" if model else "1.4"
        lock = "🔒 " if confidential else ""
        # task_type は役割(role)なので、能力カテゴリへ変換してから色を引く
        # （role名とcategory名は "ocr" 等一部しか一致しない）。
        fill = _CATEGORY_FILL.get(category_of(str(task.get("task_type", ""))), "#EEF1F4")
        title = _dot_escape(task.get("task_name", task_id))
        accuracy = detail.get("accuracy_score")
        cost = detail.get("cost")
        sub = ""
        if isinstance(accuracy, (int, float)) and isinstance(cost, (int, float)):
            sub = f"\\n{accuracy:.1f}/5.0 ・ ${cost:.2f}"
        model_line = f"\\n{_dot_escape(model, 22)}" if model else "\\n（未割当）"
        node_label = f"{task_id}  {lock}{title}{model_line}{sub}"
        return (
            f'  "{task_id}" [label="{node_label}", fillcolor="{fill}", '
            f'style="{style}", color="{border}", penwidth={pen}];'
        )

    lines = [
        "digraph assignment {",
        '  bgcolor="transparent";',
        "  rankdir=TB;",
        '  node [shape=box, style="filled,rounded", fontname="Helvetica", '
        'fontsize=10, fontcolor="#15181F", margin="0.12,0.08"];',
        '  edge [color="#9AA3B2", arrowsize=0.7, penwidth=1.1];',
    ]

    for task in task_list:
        lines.append(node_line(task))

    for task in task_list:
        task_id = str(task.get("task_id", ""))
        deps = task.get("dependencies")
        if isinstance(deps, list):
            for dep in deps:
                dep_id = str(dep)
                if dep_id in task_by_id:
                    lines.append(f'  "{dep_id}" -> "{task_id}";')

    lines.append("}")
    return "\n".join(lines)


def task_plan_rows(
    tasks_: object,
    task_results_: object,
    assignments: object,
) -> list[dict[str, object]]:
    """契約の task_results をタスク別実行計画へ変換する。

    Args:
        tasks_ (object): optimization_input のタスク一覧。
        task_results_ (object): optimization_result のタスク別結果。
        assignments (object): task_id からモデルを引く割当辞書。

    Returns:
        list[dict[str, object]]: タスク別実行計画の行。
    """
    result_by_id = (
        {
            str(item.get("task_id")): item
            for item in task_results_
            if isinstance(item, dict) and item.get("task_id")
        }
        if isinstance(task_results_, list)
        else {}
    )
    assignment_by_id = assignments if isinstance(assignments, dict) else {}
    task_list = tasks_ if isinstance(tasks_, list) else []
    rows: list[dict[str, object]] = []
    for task in task_list:
        if not isinstance(task, dict):
            continue
        task_id = str(task.get("task_id", ""))
        detail = result_by_id.get(task_id, {})
        rows.append(
            {
                "タスク ID": task_id,
                "タスク名": detail.get("task_name", task.get("task_name", "")),
                "選択モデル": detail.get(
                    "selected_model", assignment_by_id.get(task_id, "-")
                ),
                "マスキング": "ON" if detail.get("masking_enabled", False) else "OFF",
                "レビュー": "ON" if detail.get("review_enabled", False) else "OFF",
                "レビューモデル": detail.get("review_model") or "-",
                "コスト": detail.get("cost", "-"),
                "精度スコア": detail.get("accuracy_score", "-"),
            }
        )
    return rows


def accuracy_reason(task_results_: object) -> str:
    """タスク別精度から全体精度の理由文を作る。

    Args:
        task_results_ (object): タスク別最適化結果。

    Returns:
        str: 精度スコアの説明文。
    """
    scores = (
        [
            float(item["accuracy_score"])
            for item in task_results_
            if isinstance(item, dict) and item.get("accuracy_score") is not None
        ]
        if isinstance(task_results_, list)
        else []
    )
    if not scores:
        return "タスク別の精度内訳がありません。"
    return f"タスク別精度スコアの平均は {sum(scores) / len(scores):.2f} です。"


def task_accuracy_reasons(task_results_: object) -> list[dict[str, object]]:
    """タスクごとの精度スコアと理由を表示用の行へ変換する。

    Args:
        task_results_ (object): タスク別最適化結果。

    Returns:
        list[dict[str, object]]: タスク別の精度理由一覧。
    """
    if not isinstance(task_results_, list):
        return []
    rows: list[dict[str, object]] = []
    for item in task_results_:
        if not isinstance(item, dict):
            continue
        model = item.get("selected_model", "-")
        masking = "マスキングあり" if item.get("masking_enabled") else "マスキングなし"
        review = "レビューあり" if item.get("review_enabled") else "レビューなし"
        reason = item.get("accuracy_reason") or (
            f"選択モデル {model} の評価値。{masking}・{review}の条件を反映。"
        )
        rows.append(
            {
                "タスク ID": item.get("task_id", "-"),
                "タスク名": item.get("task_name", "-"),
                "精度スコア": item.get("accuracy_score", "-"),
                "理由": reason,
            }
        )
    return rows


def constraint_violations(
    result: OptimizationResult,
    budget_limit: float,
    tasks: object,
) -> list[dict[str, str]]:
    """結果と制約条件から違反内容を作る。

    Args:
        result (OptimizationResult): 最適化結果。
        budget_limit (float): 許容予算。
        tasks (object): 入力タスク一覧。

    Returns:
        list[dict[str, str]]: 制約違反の一覧。
    """
    violations: list[dict[str, str]] = []
    if float(result.get("total_cost", 0.0)) > budget_limit:
        violations.append(
            {
                "制約": "予算",
                "説明": f"総コストが上限 {budget_limit:.2f} を超えています。",
            }
        )
    if result.get("status") != "success":
        violations.append(
            {
                "制約": "最適化実行",
                "説明": str(result.get("message", "解が得られませんでした。")),
            }
        )
    task_list = tasks if isinstance(tasks, list) else []
    task_ids = {
        str(task["task_id"])
        for task in task_list
        if isinstance(task, dict) and task.get("task_id")
    }
    assignments = result.get("optimal_assignment", {})
    missing = task_ids - set(assignments) if isinstance(assignments, dict) else task_ids
    if missing and result.get("status") == "success":
        violations.append(
            {
                "制約": "全タスク割当",
                "説明": f"未割当タスク: {', '.join(sorted(missing))}",
            }
        )
    return violations


def comparison_rows(result: OptimizationResult) -> list[dict[str, object]]:
    """最適化結果と単一モデル固定結果の比較行を作成する。

    Args:
        result (OptimizationResult): 最適化結果。

    Returns:
        list[dict[str, object]]: 比較表の行。
    """
    # 「最適化前 → 最適化後」の時系列順で並べる（表・グラフとも読む順で改善が見える）。
    rows: list[dict[str, object]] = []
    baseline = result.get("baseline")
    if isinstance(baseline, dict):
        rows.append(
            {
                "条件": "最適化前（1モデル固定）",
                "モデル": baseline.get("model", "-"),
                "総コスト": baseline.get("total_cost", 0.0),
                "精度スコア（平均）": baseline.get("average_accuracy_score", 0.0),
            }
        )
    rows.append(
        {
            "条件": "最適化後",
            "モデル": "タスクごとに最適化",
            "総コスト": result.get("total_cost", 0.0),
            "精度スコア（平均）": average_accuracy_score(result),
        }
    )
    return rows
