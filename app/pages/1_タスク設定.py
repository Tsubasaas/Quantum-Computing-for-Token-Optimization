"""画面 1: 開発要求の入力 → タスク一覧の編集 → 全体条件 → 確認。

「開発要求からタスクへ分解する」がこのアプリの主動線なので、この画面の 1 章に置く。
"""

from __future__ import annotations

import _boot  # noqa: F401
import streamlit as st
from ui_helpers import (
    ALLOWED_FILE_EXTENSIONS,
    INTERNAL_MODE_TO_LEGACY_MODE,
    OPTIMIZATION_MODE_MAP,
    ROLE_OPTION_LABELS,
    df_to_tasks_dict,
    generate_optimization_input,
    llm_available,
    merge_generated_tasks,
    model_tasks_to_tasks_dict,
    nav_link,
    push_flash,
    read_reference_text,
    render_flash,
    stale_dependencies,
    task_editor_df,
    task_option_label,
    tasks_dict_to_model_tasks,
    validate_task_setting_inputs,
    validate_tasks,
)

from taqumi2026s_teame import config
from taqumi2026s_teame.data import sample_request
from taqumi2026s_teame.llm import decompose_request

st.set_page_config(
    page_title="タスク設定 — Yakizakanaヤキザカナ", page_icon="1️⃣", layout="wide"
)
st.page_link("app_pages/workspace.py", label="← Yakizakanaヤキザカナへ戻る", icon="🐟")
st.header("1. タスク設定")
st.markdown(
    "開発要求をタスクへ分解し、一覧を整えたうえで、全体の予算と最適化方針を決めます。"
)

# 直前の実行で積まれたメッセージを、再実行後のここで描画する
render_flash()

# --------------------------------------------------------------------------- #
# 状態の初期化
# --------------------------------------------------------------------------- #
if "tasks_dict" not in st.session_state:
    initial = decompose_request(sample_request(), use_llm=False)
    st.session_state["tasks_dict"] = model_tasks_to_tasks_dict(initial.tasks)
    st.session_state["tasks_origin"] = "sample"
    st.session_state["request_text"] = sample_request()

# tasks_origin: sample = 手つかずのサンプル / generated = LLM 出力 / manual = 人が触った
st.session_state.setdefault("tasks_origin", "sample")
st.session_state.setdefault("budget_limit", config.BUDGET_DEFAULT)
st.session_state.setdefault("optimization_mode", "バランス")
# data_editor はキーが同じだと編集差分を保持するため、外から一覧を差し替えたら作り直す
st.session_state.setdefault("task_editor_epoch", 0)

tasks_dict: dict[str, dict[str, object]] = st.session_state["tasks_dict"]

# --------------------------------------------------------------------------- #
# 1. 開発要求の入力（このアプリの主動線）
# --------------------------------------------------------------------------- #
st.subheader("1. 開発要求の入力")
st.caption("作りたいものを説明すると、割当可能な単位のタスクへ分解します。")

request_text = st.text_area(
    "作りたいものを説明してください*",
    value=st.session_state.get("request_text", sample_request()),
    height=100,
)
st.session_state["request_text"] = request_text

col_file, col_opt = st.columns([1.2, 1.8])

with col_file:
    uploaded_file = st.file_uploader(
        "参照ファイル（任意）",
        type=[ext.lstrip(".") for ext in ALLOWED_FILE_EXTENSIONS],
        help="仕様書や README を渡すと、その内容を踏まえて分解します（10MB 以下）。",
    )
    uploaded_file_name = uploaded_file.name if uploaded_file else None
    uploaded_file_size = uploaded_file.size if uploaded_file else None
    reference_text, reference_note = read_reference_text(uploaded_file)
    if reference_note:
        st.caption(f"⚠️ {reference_note}")
    elif reference_text:
        st.caption(
            f"「{uploaded_file_name}」を {len(reference_text):,} 文字読み込みました。"
        )

with col_opt:
    has_llm_key = llm_available()
    use_llm = st.checkbox(
        "LLM でタスク分解する",
        value=has_llm_key,
        disabled=not has_llm_key,
        help="GROQ_API_KEY または OPENAI_API_KEY が設定されているときだけ有効になります。",
    )
    if not has_llm_key:
        st.caption(
            "`.env` に `GROQ_API_KEY`（GPT-OSS 120B）または `OPENAI_API_KEY` を"
            "設定すると有効になります。"
            "未設定の間はサンプルタスク（予約管理 Web アプリ）を読み込みます。"
        )

    write_mode = st.radio(
        "生成結果の扱い",
        ["置換（いまの一覧を捨てる）", "追記（いまの一覧に足す）"],
        horizontal=True,
    )

replace_tasks = write_mode.startswith("置換")
hand_edited = st.session_state.get("tasks_origin") == "manual" and bool(tasks_dict)
generate_allowed = True
if replace_tasks and hand_edited:
    generate_allowed = st.checkbox(
        f"手で編集したタスク {len(tasks_dict)} 件を破棄して置き換えます",
        value=False,
        help="置き換えると元には戻せません。残したい場合は「追記」を選んでください。",
    )

if st.button(
    "この要求からタスクを生成する", type="primary", disabled=not generate_allowed
):
    result = decompose_request(request_text, use_llm=use_llm, context=reference_text)
    st.session_state["tasks_dict"] = merge_generated_tasks(
        tasks_dict,
        result.tasks,
        replace=replace_tasks,
        reference_file_name=uploaded_file_name,
    )
    if not replace_tasks:
        st.session_state["tasks_origin"] = "manual"
    else:
        st.session_state["tasks_origin"] = "generated" if result.used_llm else "sample"
    st.session_state["task_editor_epoch"] += 1
    if result.used_llm:
        push_flash("success", f"タスクを生成しました。{result.message}")
    else:
        push_flash("warning", f"LLM は使われていません。{result.message}")
    st.rerun()

st.divider()

# --------------------------------------------------------------------------- #
# 2. タスク一覧と編集（表を直接編集する）
# --------------------------------------------------------------------------- #
st.subheader("2. タスク一覧と編集")

if st.session_state.get("tasks_origin") == "sample":
    st.info(
        "いま表示しているのは **サンプルデータ**（`sample_tasks.json` の予約管理 Web アプリ）です。"
        "上の「1. 開発要求の入力」から、自分の要求で生成し直してください。",
        icon="🧪",
    )

st.caption(
    "表を直接編集できます。行の追加は最終行、削除は行を選んで Delete キーです。"
    "タスクIDは自動採番のため編集できません。"
    "依存タスク（先行タスク）はセルのドロップダウンから ID を選びます。"
)

stale_links = stale_dependencies(tasks_dict)
if stale_links:
    st.warning(
        "存在しないタスクを指していた依存を外しました: " + " / ".join(stale_links),
        icon="⚠️",
    )

edited_df = st.data_editor(
    task_editor_df(tasks_dict),
    num_rows="dynamic",
    hide_index=True,
    width="stretch",
    key=f"task_editor_{st.session_state['task_editor_epoch']}",
    column_config={
        "タスクID": st.column_config.TextColumn("ID", width=64, disabled=True),
        "タスク名": st.column_config.TextColumn("タスク名", width=200),
        "種類": st.column_config.SelectboxColumn(
            "種類", options=ROLE_OPTION_LABELS, width=124
        ),
        "重要度": st.column_config.NumberColumn(
            "重要度",
            min_value=1,
            max_value=5,
            step=1,
            width=76,
            help="1〜5。w_j に使う",
        ),
        "難易度": st.column_config.NumberColumn(
            "難易度",
            min_value=1,
            max_value=5,
            step=1,
            width=76,
            help="1〜5。品質補正に使う",
        ),
        "作業量": st.column_config.NumberColumn(
            "作業量", min_value=0.1, step=0.5, width=76
        ),
        "機密性": st.column_config.CheckboxColumn("機密", width=62),
        "依存タスク": st.column_config.MultiselectColumn(
            "依存タスク（先行）",
            width=260,
            options=list(tasks_dict),
            format_func=lambda i: task_option_label(tasks_dict, i),
            accept_new_options=False,
            help="このタスクより先に終わっている必要があるタスクを選びます",
        ),
        "参照ファイル": st.column_config.TextColumn("参照ファイル", width=96),
    },
)

edited_tasks_dict = df_to_tasks_dict(edited_df)
if edited_tasks_dict != tasks_dict:
    st.session_state["tasks_dict"] = edited_tasks_dict
    st.session_state["tasks_origin"] = "manual"
    tasks_dict = edited_tasks_dict

st.caption(
    f"登録済みタスク数: **{len(tasks_dict)}** 件"
    "　／　依存タスクは「4. アウトプット」の編成図の矢印になります。"
)

st.divider()

# --------------------------------------------------------------------------- #
# 3. 全体条件設定（どんなタスクがあるか分かってから決める）
# --------------------------------------------------------------------------- #
st.subheader("3. 全体条件設定")
col_budget, col_mode = st.columns([1, 2])

with col_budget:
    budget_limit = st.number_input(
        "予算上限（USD）*",
        min_value=0.0,
        value=float(st.session_state.get("budget_limit", config.BUDGET_DEFAULT)),
        step=0.5,
        help="全タスクの合計コスト上限。ベンチマークの単価が USD 建てのため USD で指定します。",
    )
    st.session_state["budget_limit"] = budget_limit

with col_mode:
    mode_options = list(OPTIMIZATION_MODE_MAP)
    current_mode = st.session_state.get("optimization_mode", "バランス")
    mode_index = mode_options.index(current_mode) if current_mode in mode_options else 1
    optimization_mode = st.radio(
        "最適化方針*",
        options=mode_options,
        index=mode_index,
        horizontal=True,
        help="「2. エージェント設定」の編成モードの初期値になります。",
    )
    st.session_state["optimization_mode"] = optimization_mode

st.caption("予算と最適化方針は「2. エージェント設定」へそのまま引き継がれます。")

st.divider()

# --------------------------------------------------------------------------- #
# 4. 入力確認および最適化実行への連携（FR-07, FR-08, FR-09）
# --------------------------------------------------------------------------- #
st.subheader("4. 入力確認と次へ")

validation_errors = validate_task_setting_inputs(
    tasks_dict=tasks_dict,
    budget_limit=budget_limit,
    optimization_mode=optimization_mode,
    uploaded_file_name=uploaded_file_name,
    uploaded_file_size=uploaded_file_size,
)

if validation_errors:
    st.error("以下の入力内容を修正してください：")
    for err in validation_errors:
        st.markdown(f"- ⚠️ {err}")
else:
    model_tasks = tasks_dict_to_model_tasks(tasks_dict)
    for warning in validate_tasks(model_tasks):
        st.warning(warning, icon="⚠️")

    opt_mode_internal = OPTIMIZATION_MODE_MAP.get(optimization_mode, "balanced")
    st.session_state["optimization_input"] = generate_optimization_input(
        tasks_dict=tasks_dict,
        budget_limit=budget_limit,
        optimization_mode=opt_mode_internal,
        time_limit_seconds=60,
    )
    st.session_state["tasks"] = model_tasks

    # 画面 2 で編成モードを細かく変えていても、ここで方針を変えたときだけ上書きする
    if st.session_state.get("_last_optimization_mode") != opt_mode_internal:
        st.session_state["mode"] = INTERNAL_MODE_TO_LEGACY_MODE.get(
            opt_mode_internal, config.DEFAULT_MODE
        )
        st.session_state["_last_optimization_mode"] = opt_mode_internal

    st.success(
        f"✅ 入力条件が設定されました"
        f"（タスク {len(tasks_dict)} 件 / 予算上限 ${budget_limit:,.2f} / "
        f"最適化方針: {optimization_mode}）。"
    )

    col_act1, col_act2 = st.columns([1, 2])
    with col_act1:
        nav_link("pages/2_エージェント設定.py", "→ 2. エージェント設定へ進む", "2️⃣")
    with col_act2:
        st.caption("※ 設定内容は自動的に保存され、次のステップへ引き継がれます。")
