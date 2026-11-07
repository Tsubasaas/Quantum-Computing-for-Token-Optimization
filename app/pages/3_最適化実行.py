"""画面: 最適化実行（Contract First）。

上流「推奨案＋人間判断UI」から ``st.session_state["optimization_input"]`` を受け取り、
Solver（:func:`run_optimization`）を実行して結果を ``st.session_state["optimization_result"]``
に保存する、単独担当範囲の画面。

- 入力: 上流の必須 session_state が揃わない場合のみ Mock 入力を使用
  （:mod:`taqumi2026s_teame.optimization_input_adapter`）
- Solver: 本実装（:mod:`taqumi2026s_teame.solvers.optimization_real_solver`）。
    内部で ``build_coefficients`` → 選択されたソルバ → 結果整形、という実際の
    QUBO パイプラインを呼び出す。
  Mock Solver（:mod:`taqumi2026s_teame.solvers.optimization_mock_solver`）は
  このページとは独立に単独動作確認したい場合のために残してある。
"""

from __future__ import annotations

import _boot  # noqa: F401
import streamlit as st
from ui_helpers import nav_link

from taqumi2026s_teame.optimization_contract import (
    OptimizationResult,
    average_accuracy_score,
)
from taqumi2026s_teame.optimization_input_adapter import build_optimization_input
from taqumi2026s_teame.solvers.optimization_real_solver import run_optimization


def _display_value(value: object) -> object:
    """表で欠損値を見やすく表示する。

    Args:
        value (object): 表示対象の値。

    Returns:
        object: 表示用の値。
    """

    if value is None or value == "":
        return "-"
    return value


def _format_bool(value: object) -> str:
    """真偽値をユーザー向け表示へ変換する。

    Args:
        value (object): 真偽値として扱う値。

    Returns:
        str: ON/OFFまたは-。
    """

    if value is None:
        return "-"
    return "ON" if bool(value) else "OFF"


def _format_time_limit(value: object) -> str:
    """最大完了時間をユーザー向け表示へ変換する。

    Args:
        value (object): 最大完了時間。

    Returns:
        str: 秒数または制限なし。
    """

    if value is None:
        return "制限なし"
    try:
        seconds: float = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{seconds:g}秒"


def _task_rows(tasks_: list[dict[str, object]]) -> list[dict[str, object]]:
    """Task一覧テーブルの行を作成する。

    Args:
        tasks_ (list[dict[str, object]]): optimization_input内のタスク一覧。

    Returns:
        list[dict[str, object]]: ユーザー向けTask一覧の行。
    """

    optional_columns: tuple[tuple[str, str], ...] = (
        ("task_type", "種類"),
        ("importance", "重要度"),
        ("difficulty", "難易度"),
        ("workload", "作業量"),
        ("is_confidential", "機密"),
    )
    available_columns: list[tuple[str, str]] = [
        (key, label)
        for key, label in optional_columns
        if any(key in task for task in tasks_)
    ]
    rows: list[dict[str, object]] = []
    for task in tasks_:
        row: dict[str, object] = {
            "Task ID": _display_value(task.get("task_id")),
            "Task名": _display_value(task.get("task_name")),
        }
        for key, label in available_columns:
            value: object = task.get(key)
            row[label] = (
                _format_bool(value)
                if key == "is_confidential"
                else _display_value(value)
            )
        rows.append(row)
    return rows


def _model_info(
    model: str, model_capability_matrix: dict[str, dict[str, object]]
) -> tuple[str | None, dict[str, object]]:
    """候補モデルに対応する能力情報を安全に取得する。

    Args:
        model (str): 候補モデルIDまたは名前。
        model_capability_matrix (dict[str, dict[str, object]]): 上流の能力マトリクス。

    Returns:
        tuple[str | None, dict[str, object]]: 表示名候補と能力情報。
    """

    if model in model_capability_matrix:
        return model, model_capability_matrix[model]
    for display_name, info in model_capability_matrix.items():
        if str(info.get("model_id", "")) == model:
            return display_name, info
    return None, {}


def _first_present(info: dict[str, object], keys: tuple[str, ...]) -> object | None:
    """候補キーのうち最初に存在する値を返す。

    Args:
        info (dict[str, object]): 候補モデルの能力情報。
        keys (tuple[str, ...]): 優先順のキー。

    Returns:
        object | None: 見つかった値。
    """

    for key in keys:
        if key in info and info[key] is not None:
            return info[key]
    return None


def _model_rows(
    candidate_models_: list[str], model_capability_matrix: dict[str, dict[str, object]]
) -> list[dict[str, object]]:
    """候補モデルテーブルの行を作成する。

    Args:
        candidate_models_ (list[str]): 候補モデル一覧。
        model_capability_matrix (dict[str, dict[str, object]]): 上流の能力マトリクス。

    Returns:
        list[dict[str, object]]: ユーザー向け候補モデル一覧の行。
    """

    rows: list[dict[str, object]] = []
    for idx, model in enumerate(candidate_models_, start=1):
        display_name, info = _model_info(model, model_capability_matrix)
        row: dict[str, object] = {"No.": idx, "モデル": model}
        if display_name and display_name != model:
            row["モデル名"] = display_name
        optional_values: dict[str, object | None] = {
            "Provider": info.get("provider"),
            "コスト/Task": _first_present(
                info, ("benchmark_cost_per_task", "cost_per_task")
            ),
            "能力スコア": _first_present(
                info,
                (
                    "repo_bug_fix_score",
                    "terminal_score",
                    "document_score",
                    "ocr_score",
                    "image_generation_score",
                ),
            ),
            "処理時間": _first_present(
                info, ("latency_sec", "completion_time", "time_sec")
            ),
        }
        for label, value in optional_values.items():
            if value is not None:
                row[label] = value
        rows.append(row)
    return rows


def _weight_rows(weights: dict[str, float]) -> list[dict[str, object]]:
    """最適化重みテーブルの行を作成する。

    Args:
        weights (dict[str, float]): optimization_input内の重み。

    Returns:
        list[dict[str, object]]: キー名を維持した重み一覧の行。
    """

    return [{"項目": key, "重み": value} for key, value in weights.items()]


st.set_page_config(
    page_title="3. 最適化実行 — Yakizakanaヤキザカナ", page_icon="3️⃣", layout="wide"
)

st.page_link("app_pages/workspace.py", label="← Yakizakanaヤキザカナへ戻る", icon="🐟")
st.title("3. 最適化実行")
st.markdown("設定した条件を確認し、最適化を実行します。")

# --------------------------------------------------------------------------- #
# 入力の取得（上流データが不十分な場合だけMockを使用）
# --------------------------------------------------------------------------- #
optimization_input, is_upstream_data = build_optimization_input(st.session_state)
previous_input = st.session_state.get("optimization_input")
if previous_input != optimization_input:
    st.session_state.pop("optimization_result", None)
st.session_state["optimization_input"] = optimization_input
st.caption("入力データ：上流実データ" if is_upstream_data else "入力データ：Mock")

# --------------------------------------------------------------------------- #
# 入力条件のサマリ表示
# --------------------------------------------------------------------------- #
st.subheader("入力条件のサマリ")
tasks = optimization_input.get("tasks", [])
candidate_models = optimization_input.get("candidate_models", [])
model_capability_matrix = optimization_input.get("model_capability_matrix", {})
optimization_weights = optimization_input.get("optimization_weights", {})

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Task数", len(tasks))
c2.metric("候補モデル数", len(candidate_models))
c3.metric("予算上限", f"${optimization_input.get('budget_limit', 0.0):.1f}")
c4.metric("最適化モード", optimization_input.get("optimization_mode", "-"))
c5.metric("マスキング", "ON" if optimization_input.get("masking_enabled") else "OFF")

with st.expander("入力データの詳細を確認する"):
    st.markdown("#### Task一覧")
    if tasks:
        st.dataframe(_task_rows(tasks), hide_index=True, width="stretch")
    else:
        st.caption("Taskは設定されていません。")

    st.markdown("#### 候補モデル")
    if candidate_models:
        st.dataframe(
            _model_rows(candidate_models, model_capability_matrix),
            hide_index=True,
            width="stretch",
        )
    else:
        st.caption("候補モデルは設定されていません。")

    st.markdown("#### 最適化条件")
    st.table(
        [
            {
                "項目": "予算上限",
                "値": f"${optimization_input.get('budget_limit', 0.0):.1f}",
            },
            {
                "項目": "最大完了時間",
                "値": _format_time_limit(optimization_input.get("max_completion_time")),
            },
            {
                "項目": "最適化モード",
                "値": _display_value(optimization_input.get("optimization_mode")),
            },
            {
                "項目": "マスキング",
                "値": _format_bool(optimization_input.get("masking_enabled")),
            },
        ]
    )

    st.markdown("#### 最適化重み")
    if optimization_weights:
        st.dataframe(
            _weight_rows(optimization_weights), hide_index=True, width="stretch"
        )
    else:
        st.caption("最適化重みは設定されていません。")

# --------------------------------------------------------------------------- #
# 最適化の実行（ボタン押下時のみ Solver を呼び出す。rerun による意図しない再実行を防止）
# --------------------------------------------------------------------------- #
st.subheader("最適化の実行")
if st.button("最適化を実行", type="primary"):
    with st.spinner("最適解を探索しています..."):
        result: OptimizationResult = run_optimization(optimization_input)
    st.session_state["optimization_result"] = result
    st.session_state["optimization_result_input"] = optimization_input

result = st.session_state.get("optimization_result")

# --------------------------------------------------------------------------- #
# 結果表示（成功 / タイムアウト / エラーのいずれでも UI は壊れないようにする）
# --------------------------------------------------------------------------- #
if result is None:
    st.info("「最適化を実行」を押すと結果が表示されます。", icon="▶️")
elif result["status"] == "success":
    st.success(result.get("message", "最適化が正常に完了しました。"), icon="✅")
    m1, m2, m3 = st.columns(3)
    m1.metric("計算時間", f"{result['solve_time_seconds']:.2f} 秒")
    m2.metric("総コスト", f"${result['total_cost']:.2f}")
    m3.metric("精度スコア（平均）", f"{average_accuracy_score(result):.2f}")
    st.caption(
        "Task ごとの詳細結果・グラフ・比較は下流の「アウトプットUI」の担当範囲です。"
    )
    nav_link("pages/4_アウトプット.py", "→ アウトプットで結果を確認", "4️⃣")
elif result["status"] == "timeout":
    st.warning("制限時間内に終了しなかったため、探索を打ち切りました。", icon="⏱️")
else:
    st.error(result.get("message", "最適化中にエラーが発生しました。"), icon="🚫")
