"""画面 2: 推奨案の前段 — 候補モデルの選択と最適化条件（予算 / 締切 / 重み / マスキング）。

仕様（機能・タスク No.3「推奨案ページ＋人間で判断UI」）:
  入力  : 確定タスク一覧 / モデル情報(価格・ベンチマーク・出典) / 候補モデル選択 /
          予算・締切 / 重み(自動モード or 手動) / マスキング候補
  出力  : candidate_models / model_capability_matrix / optimization_weights /
          budget_limit / max_completion_time / masking_enabled / optimization_input
"""

from __future__ import annotations

import _boot  # noqa: F401
import streamlit as st
from ui_helpers import (
    capability_matrix,
    coverage_gaps,
    min_cost_estimate,
    model_categories,
    models_df,
    nav_link,
    selectable_models_df,
    source_links_md,
)

from taqumi2026s_teame import config
from taqumi2026s_teame.data import load_agents, model_source_note
from taqumi2026s_teame.data.task_types import CATEGORIES, CATEGORY_LABELS
from taqumi2026s_teame.models import SolveOptions, Weights

_STARTER = {
    "claude_opus_5",
    "gpt56_sol",
    "claude_code",
    "grok_45",
    "gpt_54",
    "gemini_31_pro",
    "claude_sonnet_46",
    "onprem_mimo",
    "gpt_image_2",
    "nano_banana_2",
}

st.set_page_config(
    page_title="モデル設定 — Yakizakanaヤキザカナ", page_icon="2️⃣", layout="wide"
)
st.page_link("app_pages/workspace.py", label="← Yakizakanaヤキザカナへ戻る", icon="🐟")
st.header("2. モデル設定")

all_agents = load_agents()
by_id = {a.id: a for a in all_agents}
tasks = st.session_state.get("tasks", [])

# --------------------------------------------------------------------------- #
# 候補モデルの選択（表内チェックボックス + フィルタ）
# --------------------------------------------------------------------------- #
st.markdown(f"#### 候補モデルの選択（全 {len(all_agents)} 種）")
st.caption(model_source_note())

if "candidate_models" not in st.session_state:
    st.session_state["candidate_models"] = sorted(_STARTER & set(by_id))
selected_set: set[str] = set(st.session_state["candidate_models"])

with st.container(border=True):
    f1, f2, f3 = st.columns(3)
    f_prov = f1.multiselect("提供元", sorted({a.provider for a in all_agents}))
    f_type = f2.multiselect("種別", sorted({a.model_type for a in all_agents}))
    f_cat = f3.multiselect(
        "対応カテゴリ（すべて満たす）",
        CATEGORIES,
        format_func=lambda c: CATEGORY_LABELS[c],
    )
    f4, f5, f6 = st.columns([2, 1, 1])
    f_q = f4.text_input("モデル名で検索", "")
    f_internal = f5.checkbox("社内モデルのみ")
    f_selected_only = f6.checkbox("選択中のみ表示")


def _match(a) -> bool:  # noqa: ANN001
    if f_selected_only and a.id not in selected_set:
        return False
    if f_prov and a.provider not in f_prov:
        return False
    if f_type and a.model_type not in f_type:
        return False
    if f_internal and a.external:
        return False
    if f_q and f_q.lower() not in a.name.lower():
        return False
    if f_cat and not set(f_cat) <= model_categories(a):
        return False
    return True


view_agents = [a for a in all_agents if _match(a)]
selected_count_placeholder = st.empty()

b1, b2, _ = st.columns([1, 1, 4])
if b1.button("表示中をすべて選択", width="stretch"):
    selected_set |= {a.id for a in view_agents}
if b2.button("表示中をすべて解除", width="stretch"):
    selected_set -= {a.id for a in view_agents}

view_df = selectable_models_df(view_agents, selected_set)
edited = st.data_editor(
    view_df,
    hide_index=True,
    width="stretch",
    column_config={
        "id": None,
        "使う": st.column_config.CheckboxColumn("使う", width="small"),
        "社内": st.column_config.CheckboxColumn("社内", width="small"),
        "対応": st.column_config.TextColumn("対応カテゴリ", width="medium"),
        "平均品質": st.column_config.NumberColumn("平均品質", format="%.2f"),
        "コスト/タスク": st.column_config.NumberColumn("コスト/タスク", format="$%.2f"),
        "処理時間": st.column_config.NumberColumn("処理時間", format="%d 秒"),
    },
    disabled=[
        "モデル",
        "提供",
        "種別",
        "社内",
        "対応",
        "平均品質",
        "コスト/タスク",
        "処理時間",
    ],
)
for _row in edited.itertuples(index=False):
    if _row.使う:
        selected_set.add(_row.id)
    else:
        selected_set.discard(_row.id)

# 「選択中」はここまでの操作（フィルタ・全選択/解除ボタン・表のチェック編集）を
# すべて反映した後の selected_set を数える。ボタン/表より前に書くと、その回の
# 操作が反映される前の値を表示してしまう（常に1操作遅れる）ので注意。
selected_count_placeholder.caption(
    f"表示中: {len(view_agents)} 種 ／ 選択中: {len(selected_set)} 種"
)

selected = sorted(selected_set)
selected_agents = [by_id[i] for i in selected]

with st.expander("能力マトリクス（カテゴリ別の正規化スコア・価格・出典）"):
    st.dataframe(
        models_df(),
        hide_index=True,
        width="stretch",
        column_config={
            "出典": st.column_config.LinkColumn(
                "出典", display_text="開く", width="small"
            ),
            "入力(/1M)": st.column_config.NumberColumn("入力(/1M)", format="$%.2f"),
            "出力(/1M)": st.column_config.NumberColumn("出力(/1M)", format="$%.2f"),
            "実測(/タスク)": st.column_config.NumberColumn(
                "実測(/タスク)", format="$%.2f"
            ),
        },
    )
    st.caption(f"出典: {source_links_md()}")
    st.caption(
        "スコアは公開ベンチの実測を 0-1 に正規化。「—」は非対応カテゴリ。"
        "QUBO へは合成した Q_ja とコスト C_ja のみを渡します（data/README.md）。"
    )

# --------------------------------------------------------------------------- #
# 目的と制約
# --------------------------------------------------------------------------- #
st.markdown("#### 目的と制約")

solver_label = st.selectbox(
    "使用する最適化ソルバ",
    ["Amplify AE（量子インスパイアード）", "D-Wave Advantage（量子アニーリング）"],
    index=1 if st.session_state.get("solver") == "dwave" else 0,
    key="solver_label",
    help="D-Wave を選ぶ場合は DWAVE_API_TOKEN と D-Wave SDK の追加インストールが必要です。",
)
solver_name = "dwave" if solver_label.startswith("D-Wave") else "amplify"

# 予算は「1. タスク設定」が正本。ここは表示のみ。
budget_limit = st.session_state.get("budget_limit")
col1, col2 = st.columns([2, 1])
with col2:
    if budget_limit is not None:
        st.metric("予算の上限（画面 1 で設定）", f"${float(budget_limit):,.2f}")
    else:
        st.metric("予算の上限（画面 1 で設定）", "なし")
    use_deadline = st.checkbox("所要時間の上限を決める", value=False)
    deadline = st.slider(
        "所要時間の上限（1 モデルあたり）",
        config.DEADLINE_MIN,
        config.DEADLINE_MAX,
        config.DEADLINE_DEFAULT,
        30.0,
        format="%d 秒",
        disabled=not use_deadline,
        label_visibility="collapsed",
    )

with col1:
    # 編成モード = 画面 1 の「最適化方針」を引き継ぐ。ここでスライダー位置の目安になる。
    _stored = st.session_state.get("mode", config.DEFAULT_MODE)
    _mode_keys = list(config.MODE_WEIGHTS)
    mode = st.radio(
        "編成の方針（画面 1 から引き継ぎ）",
        _mode_keys,
        index=(
            _mode_keys.index(_stored)
            if _stored in _mode_keys
            else _mode_keys.index("バランス")
        ),
        horizontal=True,
    )
    _preset = config.MODE_WEIGHTS[mode]
    _g0 = int(round(_preset.gamma * config.GAMMA_SCALE))

    st.markdown("**評価の方針 — 品質を取るか、コストを取るか**")
    balance = st.slider(
        "品質重視  ⟵⟶  コスト重視",
        0,
        100,
        min(100, max(0, _g0)),
        5,
        key=f"balance_{mode}",
        help="左に寄せるほど『多少高くても品質の高いモデル』、"
        "右に寄せるほど『多少質を落としても安いモデル』を選びます。"
        "方針を切り替えると目安の位置に戻ります。",
    )
    _gamma = round(balance / config.GAMMA_SCALE, 2)
    weights = Weights(
        alpha=_preset.alpha, beta=_preset.beta, gamma=_gamma, mu=_preset.mu
    )
    _lo, _mid, _hi = st.columns(3)
    _lo.caption("← 0：品質だけで選ぶ")
    _mid.caption("50：バランス")
    _hi.caption("100：とにかく安く →")
    st.caption(
        f"内部係数: 品質 α={weights.alpha} ／ 信頼性 β={weights.beta}（固定）"
        f" ／ コスト γ={weights.gamma} ／ 負荷分散 μ={weights.mu}（固定）"
    )

    masking_enabled = st.checkbox(
        "機密タスクのマスキングを有効にする",
        value=bool(st.session_state.get("masking_enabled", False)),
        help="現状は設定値を最適化入力へ渡すのみ（マスキング最適化は未実装）。",
    )

hard_capacity = False  # 負荷分散は μ が担うため UI からは外す
seed = 0  # Random ベースラインの再現用に内部固定
max_completion_time = float(deadline) if use_deadline else None

# --------------------------------------------------------------------------- #
# 検証（受け入れ条件）
# --------------------------------------------------------------------------- #
st.markdown("#### チェック")
ok = True

if len(selected) < 2:
    st.error("候補モデルを 2 件以上選んでください。", icon="🚫")
    ok = False

gaps: list[str] = []
if tasks and selected_agents:
    gaps = coverage_gaps(tasks, selected_agents)
    if gaps:
        ok = False
        st.error("選択したモデルでは担当できないタスクがあります:", icon="🚫")
        for g in gaps:
            st.markdown(f"- {g}")
        st.caption(
            "対応するモデルを追加してください（機密タスクには社内モデルが必要です）。"
        )

if not tasks:
    st.warning(
        "タスクが未設定です（「1. タスク設定」へ）。モデル選択と条件は保存できます。",
        icon="⚠️",
    )

if budget_limit is not None and tasks and selected_agents and not gaps:
    floor = min_cost_estimate(tasks, selected_agents)
    if floor is not None and budget_limit == 0:
        st.info(
            f"予算 $0.00 — 最安の組合せでも約 ${floor:.2f} かかります。"
            "そのまま進めると実行可能な編成が見つからない可能性があります。",
            icon="💡",
        )
    elif floor is not None and floor > budget_limit:
        ok = False
        st.error(
            f"予算が不足しています。最安の組合せでも約 ${floor:.2f} 必要です"
            f"（予算 ${budget_limit:.2f}）。予算を上げるか、安価なモデルを追加してください。",
            icon="🚫",
        )
    elif floor is not None:
        st.info(
            f"最安の組合せの目安: 約 ${floor:.2f}（予算 ${budget_limit:.2f}）",
            icon="💰",
        )

# --------------------------------------------------------------------------- #
# 出力（session_state）
# --------------------------------------------------------------------------- #
weights_dict = {
    "alpha": weights.alpha,
    "beta": weights.beta,
    "gamma": weights.gamma,
    "mu": weights.mu,
}
cap_matrix = capability_matrix(selected_agents or all_agents)
optimization_input = {
    "tasks": [
        {
            "task_id": t.id,
            "task_name": t.title,
            "task_type": t.role,
            "importance": t.priority,
            "workload": t.est_time,
            "is_confidential": t.confidential,
            "dependencies": t.dependencies,
        }
        for t in tasks
    ],
    "config": {
        "budget_limit": budget_limit,
        "optimization_mode": mode,
        "time_limit_seconds": max_completion_time,
    },
    "candidate_models": selected,
    "optimization_weights": weights_dict,
    "masking_enabled": bool(masking_enabled),
    "solver": solver_name,
}

st.session_state["candidate_models"] = selected
st.session_state["model_capability_matrix"] = cap_matrix
st.session_state["optimization_weights"] = weights_dict
st.session_state["budget_limit"] = budget_limit
st.session_state["max_completion_time"] = max_completion_time
st.session_state["masking_enabled"] = bool(masking_enabled)
st.session_state["solver"] = solver_name
st.session_state["optimization_input"] = optimization_input

# 後段（画面3）互換
st.session_state["selected_agents"] = selected
st.session_state["mode"] = mode
st.session_state["weights"] = weights
st.session_state["seed"] = int(seed)
st.session_state["options"] = SolveOptions(
    budget=budget_limit,
    deadline=max_completion_time,
    hard_capacity=hard_capacity,
    seed=int(seed),
)

# --------------------------------------------------------------------------- #
# 次へ
# --------------------------------------------------------------------------- #
if ok:
    st.success(
        f"モデル {len(selected)} 件／モード「{mode}」／"
        + (f"予算 ${budget_limit:.1f}" if budget_limit is not None else "予算なし")
        + (
            f"／締切 {max_completion_time:.0f}s"
            if max_completion_time is not None
            else ""
        ),
        icon="✅",
    )
    if tasks:
        nav_link("pages/3_最適化実行.py", "→ 最適化実行へ", "3️⃣")
else:
    st.caption("上のチェックをすべて解消すると次の画面へ進めます。")
