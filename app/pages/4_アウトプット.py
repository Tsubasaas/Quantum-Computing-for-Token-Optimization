"""画面 4: 最適化結果・実行計画・response・エクスポート。"""

from __future__ import annotations

import json

import _boot  # noqa: F401
import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from output_helpers import (
    accuracy_reason,
    assignment_tree_dot,
    category_legend_html,
    comparison_rows,
    constraint_violations,
    model_legend_html,
    task_accuracy_reasons,
    task_plan_rows,
)

from taqumi2026s_teame.data import model_source_note
from taqumi2026s_teame.optimization_contract import (
    average_accuracy_score,
)

st.set_page_config(
    page_title="アウトプット — Yakizakanaヤキザカナ", page_icon="4️⃣", layout="wide"
)
st.page_link("app_pages/workspace.py", label="← Yakizakanaヤキザカナへ戻る", icon="🐟")
st.header("4. アウトプット")

optimization_input = st.session_state.get("optimization_input")
result = st.session_state.get("optimization_result")
if not isinstance(optimization_input, dict) or not isinstance(result, dict):
    st.warning("先に「3. 最適化実行」で最適化を実行してください。", icon="⚠️")
    st.stop()
if st.session_state.get("optimization_result_input") != optimization_input:
    st.warning(
        "設定変更後の結果がありません。画面 3 で再度最適化を実行してください。",
        icon="⚠️",
    )
    st.stop()

tasks = optimization_input.get("tasks", [])
task_results = result.get("task_results", [])
budget_limit = float(optimization_input.get("budget_limit", 0.0))
total_cost = float(result.get("total_cost", 0.0))
status = result.get("status", "error")

if status == "success":
    st.success(result.get("message", "最適化が正常に完了しました。"), icon="✅")
elif status == "timeout":
    st.warning(result.get("message", "制限時間内に終了しませんでした。"), icon="⏱️")
else:
    st.error(result.get("message", "最適化に失敗しました。"), icon="🚫")

st.markdown("#### 最適化結果サマリ")
c1, c2, c3, c4 = st.columns(4)
c1.metric("総コスト", f"${total_cost:.2f}")
c2.metric("精度スコア（平均）", f"{average_accuracy_score(result):.2f} / 5.00")
c3.metric("計算時間", f"{float(result.get('solve_time_seconds', 0.0)):.2f}s")
c4.metric(
    "予算上限との比較",
    "上限内" if total_cost <= budget_limit else "予算超過",
    f"上限 {budget_limit:.2f}",
)
st.caption(f"許容予算: {budget_limit:.2f} ／ 実際のコスト: {total_cost:.2f}")

comparison_data = comparison_rows(result)
st.markdown("#### 最適化前との比較")
if len(comparison_data) == 1:
    st.info("最適化前の1モデル固定結果は前工程から提供されていません。", icon="ℹ️")
else:
    # comparison_rows() は「最適化前 → 最適化後」の順で返す。
    # 表・グラフともこの順で並べ、良くなったか一目でわかるよう delta も出す。
    before_row, after_row = comparison_data[0], comparison_data[1]
    cost_delta = float(after_row["総コスト"]) - float(before_row["総コスト"])
    accuracy_delta = float(after_row["精度スコア（平均）"]) - float(
        before_row["精度スコア（平均）"]
    )
    m1, m2 = st.columns(2)
    m1.metric(
        "総コストの変化（最適化前→後）",
        f"${float(after_row['総コスト']):.2f}",
        f"{cost_delta:+.2f}",
        delta_color="inverse",  # コストは下がるほど良い＝マイナスを緑で表示
    )
    m2.metric(
        "精度スコアの変化（最適化前→後）",
        f"{float(after_row['精度スコア（平均）']):.2f} / 5.00",
        f"{accuracy_delta:+.2f}",
        delta_color="normal",  # 精度は上がるほど良い＝プラスを緑で表示
    )

    comparison_df = pd.DataFrame(comparison_data)
    st.dataframe(comparison_df, hide_index=True, width="stretch")

    chart_data = comparison_df.assign(
        グラフ条件=comparison_df["条件"].replace(
            {
                "最適化後": "最適化後",
                "最適化前（1モデル固定）": "1モデル固定",
            }
        )
    ).set_index("グラフ条件")
    # 「最適化後」だけ強調色にして、どちらが採用結果かを色でも示す。
    color_scale = alt.Scale(
        domain=["1モデル固定", "最適化後"], range=["#8A92A0", "#2E45D9"]
    )
    chart_cost, chart_accuracy = st.columns(2)
    with chart_cost:
        st.caption("総コスト（低いほど良い）")
        cost_chart = (
            alt.Chart(chart_data.reset_index())
            .mark_bar()
            .encode(
                x=alt.X(
                    "グラフ条件:N",
                    title="比較条件",
                    sort=["1モデル固定", "最適化後"],
                    axis=alt.Axis(labelAngle=0),
                ),
                y=alt.Y("総コスト:Q", title="コスト"),
                color=alt.Color("グラフ条件:N", scale=color_scale, legend=None),
                tooltip=["グラフ条件:N", "総コスト:Q"],
            )
        )
        st.altair_chart(cost_chart, width="stretch")
    with chart_accuracy:
        st.caption("精度スコア（平均）（高いほど良い）")
        accuracy_chart = (
            alt.Chart(chart_data.reset_index())
            .mark_bar()
            .encode(
                x=alt.X(
                    "グラフ条件:N",
                    title="比較条件",
                    sort=["1モデル固定", "最適化後"],
                    axis=alt.Axis(labelAngle=0),
                ),
                y=alt.Y("精度スコア（平均）:Q", title="スコア（0〜5）"),
                color=alt.Color("グラフ条件:N", scale=color_scale, legend=None),
                tooltip=["グラフ条件:N", "精度スコア（平均）:Q"],
            )
        )
        st.altair_chart(accuracy_chart, width="stretch")

if status == "success" and task_results:
    st.markdown(f"**精度スコアの理由:** {accuracy_reason(task_results)}")
    with st.expander("タスクごとの精度スコアの理由を表示"):
        st.dataframe(
            pd.DataFrame(task_accuracy_reasons(task_results)),
            hide_index=True,
            width="stretch",
        )
baseline_comparison = st.session_state.get("baseline_comparison", "")
if baseline_comparison:
    st.markdown(f"**最適化前との比較:** {baseline_comparison}")

violations = constraint_violations(result, budget_limit, tasks)
if violations:
    st.error("制約違反または解が得られない状態があります。", icon="🚫")
    st.dataframe(pd.DataFrame(violations), hide_index=True, width="stretch")

st.markdown("#### タスク別実行計画")
plan_rows = task_plan_rows(tasks, task_results, result.get("optimal_assignment", {}))
if plan_rows:
    st.caption(
        "タスクの依存関係（誰が終わったら誰に着手できるか）を木構造で表示し、"
        "各タスクの枠色でどのモデルが選ばれたかを示しています。"
    )
    assignment = result.get("optimal_assignment", {})
    tree_dot = assignment_tree_dot(tasks, task_results, assignment)
    st.graphviz_chart(tree_dot, width="stretch")

    model_legend = model_legend_html(tasks, assignment)
    if model_legend:
        st.caption("枠色 ＝ 選ばれたモデル")
        st.markdown(model_legend, unsafe_allow_html=True)
    category_legend = category_legend_html(tasks)
    if category_legend:
        st.caption("背景色 ＝ タスクの種類")
        st.markdown(category_legend, unsafe_allow_html=True)

    with st.expander("表で詳細を確認する"):
        st.dataframe(pd.DataFrame(plan_rows), hide_index=True, width="stretch")
else:
    st.info("タスク別の実行計画はありません。", icon="ℹ️")

st.markdown("#### 生成 response")
generated_response = str(
    st.session_state.get("generated_response", result.get("message", ""))
)
edited_response = st.text_area(
    "response（編集可能）",
    value=st.session_state.get("edited_response", generated_response),
    height=220,
    key="output_response_editor",
)
st.session_state["edited_response"] = edited_response
with st.expander("生成直後の response", expanded=True):
    st.code(generated_response, language="markdown", wrap_lines=True)
components.html(
    f"""
        <button id="copy-response" style="padding:0.45rem 0.8rem;cursor:pointer;">
            編集済み response をコピー
        </button>
        <span id="copy-status" style="margin-left:0.5rem;"></span>
        <script>
            const button = document.getElementById("copy-response");
            const status = document.getElementById("copy-status");
            const text = {json.dumps(edited_response, ensure_ascii=False)};
            button.addEventListener("click", async () => {{
                await navigator.clipboard.writeText(text);
                status.textContent = "コピーしました";
            }});
        </script>
        """,
    height=42,
)

st.markdown("#### エクスポート")
payload = {
    "optimization_input": optimization_input,
    "optimization_result": result,
    "generated_response": generated_response,
    "edited_response": edited_response,
    "constraint_violations": violations,
    "data_source": model_source_note(),
}
c1, c2 = st.columns(2)
c1.download_button(
    "結果を JSON でダウンロード",
    json.dumps(payload, ensure_ascii=False, indent=2),
    file_name="q-orchestrator_output.json",
    mime="application/json",
)
c2.download_button(
    "実行計画を CSV でダウンロード",
    pd.DataFrame(plan_rows).to_csv(index=False),
    file_name="q-orchestrator_execution_plan.csv",
    mime="text/csv",
)
