"""ワークスペース（01 要望 → 02 タスク → 03 プラン → 04 実行）。

「AI Task Planner — UIデザイン・操作フロー実装プロンプト」の §4 を、既存の
QUBO パイプラインへ接続した画面。1 枚の縦スクロールで、操作が進むごとに次の
セクションが現れる。ページ切り替えのタブではなく進行表示。

数理側は既存のまま（build_coefficients → solve_amplify / solve_greedy →
evaluate_assignment）。この画面が足しているのは、カテゴリ選択・3 プランの
予算刻み・依存関係の段組み表示だけ。

本モジュールは全体が生成 AI（Claude）支援で作成されています。
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import time
from zipfile import ZipFile

import _boot  # noqa: F401
import pandas as pd
import streamlit as st
import ui_helpers
from delivery import build_delivery
from workspace_theme import (
    CATEGORY_LABELS,
    dependency_tree_dot,
    esc,
    node_html,
    render_header,
    render_section_nav,
    render_steps,
    section_anchor,
    section_head,
    tag,
    workflow_html,
)

from taqumi2026s_teame import config
from taqumi2026s_teame.data import load_agents, model_source_note
from taqumi2026s_teame.data.task_types import (
    PLAN_CATEGORIES,
    PLAN_CATEGORY_HINTS,
    PLAN_CATEGORY_ROLES,
    ROLE_LABELS,
    difficulty_label,
    plan_category_of,
)
from taqumi2026s_teame.llm.plan_assistant import review_plan
from taqumi2026s_teame.models import Task
from taqumi2026s_teame.optimization_contract import OptimizationInput
from taqumi2026s_teame.planner import plan_tasks
from taqumi2026s_teame.plans import PLAN_SPECS, Plan, build_plans, identical_plan_kinds
from taqumi2026s_teame.solvers.optimization_real_solver import run_optimization
from taqumi2026s_teame.workflow import dependency_errors, levels

DIFFICULTY_CHOICES = ["軽量", "標準", "複雑"]
DIFFICULTY_TO_VALUE = {"軽量": 1, "標準": 3, "複雑": 5}
MAX_TITLE_CHARS = 100
DEFAULT_REQUEST = (
    "売上管理アプリをつくりたい。提案書と利用ガイド、"
    "売上登録・月別集計・ダッシュボード・CSV出力、紹介画像と告知バナーも準備したい。"
)
# 模擬実行の 1 段あたりの待ち時間（秒）。実処理ではなく進行表示のためのタイマー。
SIMULATION_STEP_SEC = 0.55


# --------------------------------------------------------------------------- #
# 状態
# --------------------------------------------------------------------------- #
def _init_state() -> None:
    defaults: dict[str, object] = {
        "ws_request": DEFAULT_REQUEST,
        "ws_categories": list(PLAN_CATEGORIES),
        "ws_tasks": [],
        "ws_tasks_source": "",
        "ws_tasks_message": "",
        "ws_budget": float(config.BUDGET_DEFAULT),
        "ws_candidate_models": [],
        "ws_solver": "amplify",
        "ws_plans": [],
        "ws_selected_plan": "",
        "ws_plan_revision": "",
        "ws_run": None,
        "ws_editor_epoch": 0,
        "ws_error": "",
        "ws_plan_chat": [],
        "ws_reviews": {},
        "ws_rerun": None,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def _revision(tasks: list[Task], budget: float, candidate_ids: list[str], solver: str) -> str:
    """タスク・予算・候補モデル・ソルバのスナップショット。古いプランの検出に使う。"""

    payload = json.dumps(
        {
            "budget": round(float(budget), 6),
            "models": sorted(candidate_ids),
            "solver": solver,
            "tasks": [
                [
                    t.id,
                    t.title,
                    t.role,
                    t.difficulty,
                    t.priority,
                    t.est_time,
                    t.quantity,
                    t.confidential,
                    sorted(t.dependencies),
                ]
                for t in tasks
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _invalidate_plans() -> None:
    """タスク・予算が変わったらプランと実行結果を捨てる（仕様 §8）。"""

    st.session_state["ws_plans"] = []
    st.session_state["ws_selected_plan"] = ""
    st.session_state["ws_plan_revision"] = ""
    st.session_state["ws_run"] = None
    st.session_state["ws_plan_chat"] = []
    st.session_state["ws_reviews"] = {}
    st.session_state["ws_rerun"] = None


@st.cache_resource(show_spinner=False)
def _agents():
    """最適化候補になりうるモデル（旧バージョン・ベンチ専用モデルは除外）。"""

    return load_agents(only_usable=True)


@st.cache_data(show_spinner=False, max_entries=16, ttl=3600)
def _solve_plans(payload: str) -> list[Plan]:
    """3 プランを求解する。``payload`` は revision を含む JSON（キャッシュキー）。"""

    data = json.loads(payload)
    tasks = [Task(**t) for t in data["tasks"]]
    return build_plans(
        tasks,
        data["models"],
        data["budget"],
        time_limit_sec=data["time_limit"],
        solver=data["solver"],
    )


def _plan_payload(tasks: list[Task], budget: float, model_ids: list[str], solver: str) -> str:
    return json.dumps(
        {
            "tasks": [
                {
                    "id": t.id,
                    "title": t.title,
                    "role": t.role,
                    "difficulty": t.difficulty,
                    "priority": t.priority,
                    "est_time": t.est_time,
                    "dependencies": list(t.dependencies),
                    "confidential": t.confidential,
                    "quantity": t.quantity,
                    "deliverable": t.deliverable,
                }
                for t in tasks
            ],
            "models": model_ids,
            "budget": float(budget),
            "time_limit": 3,
            "solver": solver,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


# --------------------------------------------------------------------------- #
# 画面
# --------------------------------------------------------------------------- #
_init_state()

agents = _agents()
agent_ids = {a.id for a in agents}
image_models = [a for a in agents if a.can_do("image_gen")]
text_models = [a for a in agents if any(a.can_do(r) for r in ("code_gen", "doc_understand"))]
amplify_ready = bool(os.getenv("FIXSTARS_AMPLIFY_TOKEN"))

# 候補モデルの初期値は「使えるモデル」全件。以降は『予算とモデル選定』で編集。
# 既存の選択から、除外済み・不明な id は落とす。
_selected = [m for m in st.session_state["ws_candidate_models"] if m in agent_ids]
if not _selected:
    _selected = sorted(agent_ids)
st.session_state["ws_candidate_models"] = _selected

tasks: list[Task] = st.session_state["ws_tasks"]
plans: list[Plan] = st.session_state["ws_plans"]
run = st.session_state["ws_run"]

current_step = 1
if tasks:
    current_step = 2
if plans:
    current_step = 3
if run:
    current_step = 4

# 生成・実行は行わないため、バッジは常に「シミュレーション」。接続できたかのように
# 見せない（仕様 §4.A）。求解だけは本物なので、その旨は下のカタログ欄に書く。
render_header(badge="シミュレーション（成果物は生成しません）")
render_steps(current_step)
render_section_nav(
    [
        ("section-brief", "要望入力", True),
        ("section-tasks", "タスク整理", bool(tasks)),
        ("section-scope", "予算・モデル", bool(tasks)),
        ("section-plans", "プラン比較", bool(plans)),
        ("section-workflow", "実行フロー", bool(plans and st.session_state["ws_selected_plan"])),
        ("section-run", "実行状況", bool(run and plans)),
        ("section-catalog", "モデルカタログ", True),
    ]
)


# --------------------------------------------------------------------------- #
# A. 要望入力（PROJECT BRIEF）
# --------------------------------------------------------------------------- #
section_anchor("section-brief")
with st.container(key="qopanel-brief"):
    section_head(
        "PROJECT BRIEF",
        "品質・信頼性・コストから、最適なAI割当へ。",
        f"{len(text_models)} LLMs + {len(image_models)} image models",
        level=1,
    )
    st.markdown(
        "品質・信頼性・コストを考慮し、能力・機密性・予算の制約を守りながら、"
        "最適なAIの割当を求めます。"
    )

    request_text = st.text_area(
        "要望・必要な成果物",
        value=st.session_state["ws_request"],
        height=120,
        key="ws_request_input",
    )

    st.markdown("**含めるタスクの種類（複数選択）**")
    selected_categories: list[str] = []
    category_columns = st.columns(3, gap="small")
    for column, category in zip(category_columns, PLAN_CATEGORIES, strict=True):
        with column, st.container(key=f"qocat-{category}"):
            checked = st.checkbox(
                CATEGORY_LABELS[category],
                value=category in st.session_state["ws_categories"],
                key=f"ws_cat_{category}",
            )
            if checked:
                selected_categories.append(category)
            # 選択マーカーは独立した要素にせず、既存の HTML へ同梱する。
            # st.html を 1 つ足すと Streamlit の要素コンテナぶん高さがずれるため。
            marker = '<span class="qo-on"></span>' if checked else ""
            st.html(
                f'{marker}<small class="qo-cat-hint">{esc(PLAN_CATEGORY_HINTS[category])}</small>'
            )

    llm_ready = ui_helpers.llm_available()
    option_left, option_right = st.columns([1.4, 1.6], gap="medium")
    with option_left:
        uploaded = st.file_uploader(
            "参照ファイル（任意）",
            type=[ext.lstrip(".") for ext in ui_helpers.ALLOWED_FILE_EXTENSIONS],
            help="仕様書や README を渡すと、その内容を踏まえて分解します（10MB 以下）。",
        )
        reference_text, reference_note = ui_helpers.read_reference_text(uploaded)
        if reference_note:
            st.caption(f"⚠️ {reference_note}")
        elif reference_text:
            st.caption(f"「{uploaded.name}」を {len(reference_text):,} 文字読み込みました。")
    with option_right:
        use_llm = st.checkbox(
            "LLM でタスク分解する",
            value=llm_ready,
            disabled=not llm_ready,
            help="GROQ_API_KEY または OPENAI_API_KEY があるときだけ有効になります。",
        )
        if llm_ready:
            st.caption("選択した種類と要望に合わせて、必要なタスクを整理します。")
        else:
            st.caption(
                "API キーが未設定のため、テンプレートと要望文のキーワードから"
                "タスクを構成します（LLM による解釈は行いません）。"
            )

    action_left, action_right = st.columns([2.4, 1], vertical_alignment="center")
    action_left.markdown(
        '<span class="qo-muted">タスクに分解すると、次のセクションに一覧が表示されます。</span>',
        unsafe_allow_html=True,
    )
    if action_right.button("タスクを分解する →", type="primary", width="stretch"):
        st.session_state["ws_request"] = request_text
        st.session_state["ws_categories"] = selected_categories
        st.session_state["ws_error"] = ""
        try:
            with st.spinner("タスクに分解しています…"):
                planned = plan_tasks(
                    request_text,
                    selected_categories,
                    use_llm=use_llm,
                    context=reference_text,
                )
        except ValueError as exc:
            st.session_state["ws_error"] = str(exc)
        else:
            st.session_state["ws_tasks"] = planned.tasks
            st.session_state["ws_tasks_source"] = planned.source
            st.session_state["ws_tasks_message"] = planned.message
            st.session_state["ws_editor_epoch"] += 1
            _invalidate_plans()
        st.rerun()

    if st.session_state["ws_error"]:
        st.html(f'<p class="qo-error" role="alert">{esc(st.session_state["ws_error"])}</p>')

    # 要望・カテゴリを変えたのに整理し直していないときは、その旨を出す（仕様 §8）。
    if tasks and (
        request_text != st.session_state["ws_request"]
        or selected_categories != st.session_state["ws_categories"]
    ):
        st.warning(
            "要望またはタスクの種類が変更されています。"
            "「タスクを分解する →」を押して作り直してください。",
            icon="⚠️",
        )


# --------------------------------------------------------------------------- #
# B. タスク整理（TASK BREAKDOWN）
# --------------------------------------------------------------------------- #
def _editor_frame(rows: list[Task], *, with_quantity: bool) -> pd.DataFrame:
    data = {
        "ID": [t.id for t in rows],
        "タスク": [t.title for t in rows],
        "重要度": [int(t.priority) for t in rows],
        "難易度": [difficulty_label(t.difficulty) for t in rows],
        "前提": ["、".join(t.dependencies) if t.dependencies else "—" for t in rows],
        "機密": [bool(t.confidential) for t in rows],
        "成果物": [t.deliverable or "成果物" for t in rows],
    }
    if with_quantity:
        data["枚数"] = [max(1, int(t.quantity)) for t in rows]
    return pd.DataFrame(data)


def _apply_edits(rows: list[Task], frame: pd.DataFrame, *, with_quantity: bool) -> bool:
    """編集結果をタスクへ書き戻す。変更があれば True。"""

    changed = False
    by_id = {t.id: t for t in rows}
    for record in frame.to_dict("records"):
        task = by_id.get(str(record["ID"]))
        if task is None:
            continue
        title = str(record["タスク"]).strip()[:MAX_TITLE_CHARS]
        if title and title != task.title:
            task.title, changed = title, True
        priority = max(1, min(5, int(record["重要度"] or task.priority)))
        if priority != task.priority:
            task.priority, changed = priority, True
        difficulty = DIFFICULTY_TO_VALUE.get(str(record["難易度"]), task.difficulty)
        if difficulty != task.difficulty:
            task.difficulty, changed = difficulty, True
        confidential = bool(record["機密"])
        if confidential != task.confidential:
            task.confidential, changed = confidential, True
        if with_quantity:
            quantity = max(1, int(record["枚数"] or 1))
            if quantity != task.quantity:
                task.quantity, changed = quantity, True
    return changed


if tasks:
    section_anchor("section-tasks")
    with st.container(key="qopanel-tasks"):
        section_head("TASK BREAKDOWN", "成果物ごとに、必要な作業を整理", f"{len(tasks)} tasks")

        if st.session_state["ws_tasks_source"] == "template":
            st.warning(st.session_state["ws_tasks_message"], icon="⚠️")
        else:
            st.success(st.session_state["ws_tasks_message"], icon="✅")

        st.markdown(
            '<span class="qo-muted">'
            "重要度・難易度・前提タスク・機密を確認し、必要に応じて変更できます。"
            "重要度は目的関数の重み（w_j = 値 / 5）、難易度は必要な能力の目安です。"
            "機密が付いたタスクは社外 API のモデルに割り当てません。"
            "</span>",
            unsafe_allow_html=True,
        )

        epoch = st.session_state["ws_editor_epoch"]
        for category in PLAN_CATEGORIES:
            rows = [t for t in tasks if plan_category_of(t.role) == category]
            if not rows:
                continue  # 選ばれていないカテゴリの空表は出さない
            st.markdown(f"##### {CATEGORY_LABELS[category]}")
            with_quantity = category == "image"
            column_config = {
                "ID": st.column_config.TextColumn("ID", width=70, disabled=True),
                "タスク": st.column_config.TextColumn(
                    "タスク", width="large", max_chars=MAX_TITLE_CHARS, required=True
                ),
                "重要度": st.column_config.NumberColumn(
                    "重要度",
                    min_value=1,
                    max_value=5,
                    step=1,
                    width=80,
                    required=True,
                    help="目的関数の重み w_j = この値 / 5。業務上の優先順位ではありません。",
                ),
                "難易度": st.column_config.SelectboxColumn(
                    "難易度", options=DIFFICULTY_CHOICES, width=110, required=True
                ),
                "前提": st.column_config.TextColumn("前提", width=130, disabled=True),
                "機密": st.column_config.CheckboxColumn(
                    "機密", width=70, help="社外 API のモデルへ割り当てません。"
                ),
                "成果物": st.column_config.TextColumn("成果物", width=150, disabled=True),
            }
            if with_quantity:
                column_config["枚数"] = st.column_config.NumberColumn(
                    "枚数",
                    min_value=1,
                    max_value=50,
                    step=1,
                    width=90,
                    help="生成する画像の枚数",
                )
            edited = st.data_editor(
                _editor_frame(rows, with_quantity=with_quantity),
                key=f"ws_editor_{category}_{epoch}",
                hide_index=True,
                width="stretch",
                num_rows="fixed",
                column_config=column_config,
            )
            _apply_edits(rows, edited, with_quantity=with_quantity)

        dependency_issues = dependency_errors(tasks)
        for problem in dependency_issues:
            st.warning(problem, icon="⚠️")

        # 依存関係のロジックツリー（前提 → タスク の有向グラフ）。
        if any(t.dependencies for t in tasks) and not dependency_issues:
            by_id = {t.id: t for t in tasks}
            ordered = [tid for level in levels(tasks) for tid in level if tid in by_id]
            tree_nodes = [
                (
                    tid,
                    by_id[tid].title,
                    [d for d in by_id[tid].dependencies if d in by_id],
                    plan_category_of(by_id[tid].role),
                )
                for tid in ordered
            ]
            st.markdown(
                '<span class="qo-muted">タスクの前提関係。上のタスクが終わってから'
                "下のタスクに進めます。</span>",
                unsafe_allow_html=True,
            )
            st.graphviz_chart(dependency_tree_dot(tree_nodes), use_container_width=True)


# --------------------------------------------------------------------------- #
# ④ 予算とモデル選定（BUDGET & MODELS）
# --------------------------------------------------------------------------- #
def _match_agent(agent, providers: list[str], kinds: list[str], query: str, local_only: bool):
    if providers and agent.provider not in providers:
        return False
    if kinds and agent.model_type not in kinds:
        return False
    if local_only and agent.external:
        return False
    if query and query.lower() not in agent.name.lower():
        return False
    return True


if tasks:
    section_anchor("section-scope")
    with st.container(key="qopanel-scope"):
        section_head("BUDGET & MODELS", "予算と、使う AI モデルを決める")

        budget_column, solver_column = st.columns([1, 1], vertical_alignment="bottom")
        budget = budget_column.number_input(
            "最大予算（USD）  ※必須",
            min_value=0.01,
            max_value=1000.0,
            value=float(st.session_state["ws_budget"]),
            step=0.5,
            help="3 つのプランは、この予算の 30% / 60% / 100% を上限に配分します。",
        )
        solver_label = solver_column.selectbox(
            "最適化ソルバ",
            [
                "Amplify AE（量子インスパイアード）",
                "D-Wave Advantage（量子アニーリング）",
                "Greedy（古典・貪欲法）",
            ],
            index={"amplify": 0, "dwave": 1, "greedy": 2}.get(
                st.session_state["ws_solver"], 0
            ),
            key="ws_solver_label",
        )
        solver = (
            "dwave"
            if solver_label.startswith("D-Wave")
            else "greedy"
            if solver_label.startswith("Greedy")
            else "amplify"
        )
        st.session_state["ws_budget"] = budget
        st.session_state["ws_solver"] = solver

        st.markdown(
            "**候補モデル** — 最適化が選べる範囲。"
            "旧バージョンやベンチ専用モデル（一般提供なし）は除外済みです。"
        )
        providers = sorted({a.provider for a in agents if a.provider})
        kinds = sorted({a.model_type for a in agents if a.model_type})
        filter_left, filter_mid, filter_right = st.columns([1.3, 1.1, 1.3])
        pick_provider = filter_left.multiselect("提供元", providers, key="ws_model_provider")
        pick_kind = filter_mid.multiselect("種別", kinds, key="ws_model_kind")
        name_query = filter_right.text_input("名前で絞り込み", key="ws_model_query")
        local_only = st.checkbox("ローカル実行できるモデルだけ", key="ws_model_local_only")

        selected_set = set(st.session_state["ws_candidate_models"])
        view_agents = [
            a for a in agents if _match_agent(a, pick_provider, pick_kind, name_query, local_only)
        ]
        pick_all, pick_none, count_slot = st.columns([1, 1, 2])
        if pick_all.button("表示中をすべて選択", width="stretch"):
            selected_set |= {a.id for a in view_agents}
        if pick_none.button("表示中を解除", width="stretch"):
            selected_set -= {a.id for a in view_agents}

        model_table = pd.DataFrame(
            {
                "id": [a.id for a in view_agents],
                "使う": [a.id in selected_set for a in view_agents],
                "モデル": [a.name for a in view_agents],
                "提供": [a.provider for a in view_agents],
                "種別": [a.model_type for a in view_agents],
                "ローカル": [not a.external for a in view_agents],
                "対応": [
                    " / ".join(
                        CATEGORY_LABELS[c]
                        for c in PLAN_CATEGORIES
                        if any(a.can_do(r) for r in PLAN_CATEGORY_ROLES[c])
                    )
                    for a in view_agents
                ],
                "コスト/タスク": [round(float(a.cost_per_task), 2) for a in view_agents],
            }
        )
        edited_models = st.data_editor(
            model_table,
            key="ws_model_editor",
            hide_index=True,
            width="stretch",
            column_config={
                "id": None,
                "使う": st.column_config.CheckboxColumn("使う", width="small"),
                "ローカル": st.column_config.CheckboxColumn(
                    "ローカル",
                    width="small",
                    help="社外 API を通さず自前で動かせる（機密タスク可）",
                ),
                "対応": st.column_config.TextColumn("対応", width="medium"),
                "コスト/タスク": st.column_config.NumberColumn("コスト/タスク", format="$%.2f"),
            },
            disabled=["モデル", "提供", "種別", "ローカル", "対応", "コスト/タスク"],
        )
        for record in edited_models.to_dict("records"):
            if record["使う"]:
                selected_set.add(str(record["id"]))
            else:
                selected_set.discard(str(record["id"]))

        candidate_ids = sorted(selected_set & agent_ids)
        st.session_state["ws_candidate_models"] = candidate_ids
        count_slot.markdown(
            f'<span class="qo-muted">選択中 {len(candidate_ids)} 種 ／ '
            f"表示中 {len(view_agents)} 種（候補プール {len(agents)} 種）</span>",
            unsafe_allow_html=True,
        )

        with st.expander("能力マトリクス（カテゴリ別スコア・価格・出典）", expanded=False):
            st.dataframe(
                ui_helpers.models_df(candidate_ids or None),
                hide_index=True,
                width="stretch",
                column_config={
                    "出典": st.column_config.LinkColumn("出典", display_text="開く"),
                    "入力(/1M)": st.column_config.NumberColumn("入力(/1M)", format="$%.2f"),
                    "出力(/1M)": st.column_config.NumberColumn("出力(/1M)", format="$%.2f"),
                    "実測(/タスク)": st.column_config.NumberColumn("実測(/タスク)", format="$%.2f"),
                },
            )
            st.caption(f"出典: {ui_helpers.source_links_md()}")

        enough_models = len(candidate_ids) >= 2
        if not enough_models:
            st.error("候補モデルを 2 件以上選んでください。", icon="🚫")
        calculate = st.button(
            "この条件で最適化する →",
            type="primary",
            width="stretch",
            disabled=not enough_models,
        )
        if calculate:
            with st.spinner("最適化しています…（3 プランを求解）"):
                revision = _revision(tasks, budget, candidate_ids, solver)
                payload = _plan_payload(tasks, budget, candidate_ids, solver)
                st.session_state["ws_plans"] = _solve_plans(payload)
                st.session_state["ws_plan_revision"] = revision
                st.session_state["ws_run"] = None
                st.session_state["ws_plan_chat"] = []
                # 目安上限にも収まる案を優先し、無ければ「上限超過だが予算内」の案を選ぶ。
                runnable = [p for p in st.session_state["ws_plans"] if p.runnable]
                pool = [p for p in runnable if p.feasible] or runnable
                balanced = next((p for p in pool if p.kind == "balanced"), None)
                chosen = balanced or (pool[0] if pool else None)
                st.session_state["ws_selected_plan"] = chosen.kind if chosen else ""
            st.rerun()


# --------------------------------------------------------------------------- #
# 入力が変わっていないかの確認（仕様 §8）
#
# タスク・予算・候補モデルのスナップショット（revision）が、プランを計算した
# ときと違えば、表示中のプランと実行結果は捨てる。どの経路で変わっても
# ここで必ず捕まるので、「入力を変えたのに古いプランを実行できてしまう」が起きない。
# --------------------------------------------------------------------------- #
if (
    plans
    and _revision(
        tasks,
        st.session_state["ws_budget"],
        st.session_state["ws_candidate_models"],
        st.session_state["ws_solver"],
    )
    != st.session_state["ws_plan_revision"]
):
    _invalidate_plans()
    st.rerun()


# --------------------------------------------------------------------------- #
# C. プラン比較（PLAN COMPARISON）
# --------------------------------------------------------------------------- #
def _money(value: float) -> str:
    return f"${value:,.4f}"


def _metric(label: str, value: str) -> str:
    return f'<div class="qo-metric"><span>{esc(label)}</span><span>{esc(value)}</span></div>'


def _solver_alert(plan: Plan, requested_solver: str) -> tuple[str, str, str] | None:
    """選択ソルバの失敗を、ワークスペース向けの日本語説明へ変換する。"""

    result = plan.result
    solver_error = str(result.get("solver_error", ""))
    if requested_solver != "dwave" or not solver_error:
        return None

    lower_error = solver_error.lower()
    if "embedding" in lower_error or "clique" in lower_error or "minor" in lower_error:
        detail = (
            "問題の規模がD-Waveの構造へ埋め込めませんでした。"
            "タスク数または候補モデル数を減らすと改善する可能性があります。"
        )
    elif "token" in lower_error or "authentication" in lower_error or "認証" in solver_error:
        detail = (
            "D-Wave APIトークンが未設定、または認証に失敗しました。"
            "DWAVE_API_TOKENを確認してください。"
        )
    elif "有効な割当" in solver_error or "one-hot" in lower_error:
        detail = "D-Waveから制約を満たす解が返りませんでした。問題規模や制約を見直してください。"
    else:
        detail = "D-Waveで解を取得できませんでした。接続状態と問題の規模を確認してください。"

    return "D-Waveでの最適化に失敗しました", detail, solver_error


def _deliverable_link(revision: str, task_id: str) -> str:
    """成果物の保存先（予定）を示すプレースホルダーリンク。

    模擬実行のため実ファイルは存在しない。生成 API・成果物ストア接続後に
    実リンクへ差し替える前提の、パスの形だけを先に決めておくためのもの。
    """

    return f"outputs/{(revision or 'draft')[:8]}/{task_id}"


def _rerun_flagged_tasks(
    tasks_to_rerun: list[Task], budget_cap: float, candidate_models: list[str]
) -> dict:
    """レビューが付いたタスクだけを、精度優先（γ=0固定）で再求解する。

    余った予算の中でやり直すのが目的なので、3プラン比較はせず「精度優先」の
    重み1本に固定する（コストやバランスへ振れて品質が落ちるのを避ける）。
    """

    weights = config.MODE_WEIGHTS["精度優先"]
    optimization_input: OptimizationInput = {
        "tasks": [
            {
                "task_id": t.id,
                "task_name": t.title,
                "task_type": t.role,
                "importance": t.priority,
                "difficulty": t.difficulty,
                "workload": t.est_time,
                "is_confidential": t.confidential,
                "dependencies": [],  # 再実行は対象タスクのみを独立に解く
                "quantity": max(1, int(t.quantity)),
            }
            for t in tasks_to_rerun
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
        "max_completion_time": 3.0,
        "masking_enabled": False,
        "optimization_mode": "精度優先",
    }
    return run_optimization(optimization_input)


if plans:
    section_anchor("section-plans")
    selected_kind = st.session_state["ws_selected_plan"]
    selected_plan = next((p for p in plans if p.kind == selected_kind and p.runnable), None)

    section_head("PLAN COMPARISON", "費用と期待品質を比較する")
    if selected_plan is not None:
        solver_alert = _solver_alert(selected_plan, str(st.session_state.get("ws_solver", "")))
        if solver_alert is not None:
            alert_title, alert_detail, solver_error = solver_alert
            st.html(
                '<div class="qo-solver-alert">'
                f'<div class="qo-solver-alert-title"><span class="qo-solver-alert-icon">×</span>'
                f"<strong>{esc(alert_title)}</strong></div>"
                f'<p class="qo-solver-alert-detail">{esc(alert_detail)}</p>'
                f'<p class="qo-solver-alert-error"><b>Error:</b> {esc(solver_error)}</p>'
                "</div>"
            )
    # 予算超過のカードから逃げ道を示すために、実行できる案のうち最も安いものを持っておく。
    _runnable = [p for p in plans if p.runnable]
    cheapest_runnable = min(_runnable, key=lambda p: p.total_cost) if _runnable else None
    plan_columns = st.columns(3, gap="medium")
    for column, plan in zip(plan_columns, plans, strict=True):
        with column, st.container(key=f"qoplan-{plan.kind}"):
            is_selected = plan.kind == selected_kind
            marker = '<span class="qo-on"></span>' if is_selected else ""
            if plan.status == "over_cap":
                # 目安上限は超えたが実行はできる。実行不可の赤い枠とは別扱いにする。
                marker += '<span class="qo-overcap"></span>'
            elif not plan.runnable:
                marker += '<span class="qo-infeasible"></span>'

            # 「予算上限」ではなく「目安上限」。30/60/100% は 3 案に幅を出すための
            # 内部的な刻みであって、利用者と約束した制約ではない。
            cap_note = "（超過）" if plan.status == "over_cap" else ""
            head = (
                f'<div class="qo-plan-name">{esc(plan.label)}</div>'
                f'<div class="qo-muted">この案の目安上限 {_money(plan.budget_cap)}'
                f"{cap_note}</div>"
            )
            if plan.runnable:
                over = plan.status == "over_cap"
                price_class = "qo-price over" if over else "qo-price"
                notice = (
                    '<p class="qo-note">'
                    f"目安上限を {_money(plan.overrun)} 超過"
                    f"（予算 {_money(plan.total_budget)} 内に収まります）</p>"
                    if over
                    else ""
                )
                body = (
                    f'<div class="{price_class}">{_money(plan.total_cost)}</div>'
                    '<div class="qo-muted">予想合計API費用</div>'
                    + notice
                    + _metric(
                        "期待品質（実測ベンチ由来）",
                        f"{plan.expected_quality:.2f} / 5.00"
                        if plan.expected_quality is not None
                        else "—",
                    )
                    + _metric("文書・コード費用", _money(plan.text_cost))
                    + _metric("画像タスク費用", _money(plan.image_cost))
                    + _metric("合計作業量", f"{plan.workload_hours:,.1f} h")
                    + _metric("生成画像枚数", f"{plan.image_count:,} 枚")
                    + _metric("使用モデル数", f"{plan.distinct_models} 種")
                )
                chips = "".join(
                    tag(c)
                    + f"<span class='qo-tag'>{plan.task_count_by_category.get(c, 0)} 件</span>"
                    for c in PLAN_CATEGORIES
                    if plan.task_count_by_category.get(c, 0)
                )
                body += f'<div class="qo-chips">{chips}</div>'
            elif plan.status == "over_budget":
                # 予算が原因なので金額で説明する。ただしこの費用は「この案の重みで選ばれた
                # 構成」の費用であって、全タスクの実行に必要な最低額ではない。他の案がもっと
                # 安く全タスクを実行できることは普通に起きるので、そちらへ逃がす。
                alternative = (
                    f"<br>{esc(cheapest_runnable.label)}なら "
                    f"{_money(cheapest_runnable.total_cost)} で全タスクを実行できます。"
                    if cheapest_runnable is not None
                    else ""
                )
                body = (
                    f'<div class="qo-price na">{_money(plan.total_cost)}</div>'
                    '<div class="qo-muted">この構成に必要な費用</div>'
                    f'<p class="qo-error">予算 {_money(plan.total_budget)} では'
                    f"この構成を実行できません（{_money(plan.shortfall)} 不足）。"
                    f"{alternative}</p>"
                )
            else:
                # 予算では解決しない理由。金額を出すと「増額すれば直る」と誤解させる。
                # 求解失敗（solver_error）は理由が Python の例外文なので画面には出さない。
                if plan.result.get("solver_error"):
                    body = '<div class="qo-price na">実行できません</div>'
                else:
                    reason = esc(plan.infeasible_reason).replace("\n", "<br>")
                    body = (
                        f'<div class="qo-price na">実行できません</div>'
                        f'<p class="qo-error">{reason}</p>'
                    )
            st.html(marker + head + body)

            if plan.runnable:
                if st.button(
                    "選択中" if is_selected else "このプランを選択",
                    key=f"ws_select_{plan.kind}",
                    type="primary" if is_selected else "secondary",
                    width="stretch",
                    disabled=is_selected,
                ):
                    st.session_state["ws_selected_plan"] = plan.kind
                    st.session_state["ws_run"] = None
                    st.rerun()
            else:
                st.button(
                    "選択できません",
                    key=f"ws_select_{plan.kind}",
                    width="stretch",
                    disabled=True,
                )

    for group in identical_plan_kinds(plans):
        names = "・".join(label for kind, label, _, _ in PLAN_SPECS if kind in group)
        st.markdown(
            '<span class="qo-muted">'
            f"この条件では {esc(names)} の最適なモデル構成が同じです。"
            "目安上限が異なっても配分が変わらない場合があります。"
            "</span>",
            unsafe_allow_html=True,
        )

    if selected_plan is None:
        solver_error = next(
            (
                str(plan.result.get("message", ""))
                for plan in plans
                if plan.result.get("solver_error")
            ),
            "",
        )
        # over_budget の案は全タスクに担当モデルが付いている（金額だけが問題）。その中の
        # 最安値が、いま提示できる「いくら足りないか」の目安になる。理論上の最小費用では
        # ないので、断定しない書き方にする。
        priced = [p.total_cost for p in plans if p.status == "over_budget"]
        budget_now = float(st.session_state["ws_budget"])
        if solver_error:
            st.error(solver_error, icon="🚫")
        elif priced:
            needed = min(priced)
            st.error(
                "すべてのプランが予算内に収まらず、実行できません。"
                f"最も安いプランでも {_money(needed)} かかります"
                f"（現在の予算 {_money(budget_now)} ／ 不足 {_money(needed - budget_now)}）。"
                "これは 3 プランの中での最安値で、理論上の最小費用ではありません。",
                icon="🚫",
            )
        else:
            st.error(
                "すべてのプランが実行できません。"
                "候補モデルを増やすか、タスクの種類を見直してください。",
                icon="🚫",
            )

    # ---------------------------------------------------------------- #
    # D. 実行フローと配分内訳（WORKFLOW）
    # ---------------------------------------------------------------- #
    if selected_plan is not None:
        section_anchor("section-workflow")
        by_id = {t.id: t for t in tasks}
        results_by_task = {r["task_id"]: r for r in selected_plan.result.get("task_results", [])}
        run_states: dict[str, str] = {}
        if run and run.get("plan_kind") == selected_plan.kind:
            run_states = run.get("states", {})

        with st.container(key="qopanel-flow"):
            section_head(
                "WORKFLOW",
                "選択した実行プラン",
                f"{selected_plan.label} / 上限 {_money(selected_plan.budget_cap)}",
            )
            st.markdown(
                '<span class="qo-muted">'
                "各段のタスクは前提完了後に開始可能。文書・コード・画像を横断した依存関係を示します。"
                "同じ段に並ぶことは、無制限に同時実行してよいという意味ではありません。"
                "</span>",
                unsafe_allow_html=True,
            )

            level_blocks: list[str] = []
            deps_by_task: dict[str, list[str]] = {}
            for level in selected_plan.workflow_levels:
                nodes = ""
                for task_id in level:
                    task = by_id.get(task_id)
                    result = results_by_task.get(task_id)
                    if task is None or result is None:
                        continue
                    category = plan_category_of(task.role)
                    shown_deps = [d for d in task.dependencies if d in by_id]
                    if shown_deps:
                        deps_by_task[task.id] = shown_deps
                    nodes += node_html(
                        display_id=task.id,
                        category=category,
                        title=task.title,
                        model=str(result.get("model_display_name", result["selected_model"])),
                        depends_on=("、".join(task.dependencies) if task.dependencies else "—"),
                        cost=_money(float(result["cost"])),
                        extra=(f"{task.quantity} 枚 / 1 回の生成" if category == "image" else ""),
                        state=run_states.get(task_id, ""),
                    )
                level_blocks.append(nodes)
            st.markdown(
                '<span class="qo-muted">タスクにカーソルを合わせると、その前提タスクが'
                "強調されます。</span>",
                unsafe_allow_html=True,
            )
            st.html(workflow_html(level_blocks, deps_by_task))

            with st.expander("モデル配分と費用の内訳", expanded=True):
                rows = []
                for task in tasks:
                    result = results_by_task.get(task.id)
                    if result is None:
                        continue
                    quality = float(result["accuracy_score"])
                    rows.append(
                        {
                            "タスク": f"{task.id} {task.title}",
                            "種類": CATEGORY_LABELS[plan_category_of(task.role)],
                            "担当モデル": result.get(
                                "model_display_name", result["selected_model"]
                            ),
                            "費用(USD)": round(float(result["cost"]), 4),
                            "配分の根拠": (
                                f"{ROLE_LABELS.get(task.role, task.role)}の実測ベンチ品質から "
                                f"精度 {quality:.2f}/5.00"
                                f"（難易度 {difficulty_label(task.difficulty)} 補正後）。"
                                f"予算上限 {_money(selected_plan.budget_cap)} の制約内で "
                                "合計スコアが最大になる組み合わせとして選択。"
                            ),
                        }
                    )
                st.dataframe(
                    pd.DataFrame(rows),
                    hide_index=True,
                    width="stretch",
                    column_config={
                        "費用(USD)": st.column_config.NumberColumn("費用(USD)", format="%.4f"),
                        "配分の根拠": st.column_config.TextColumn("配分の根拠", width="large"),
                    },
                )
                st.caption(
                    "根拠は models.json の実測ベンチマークと価格から機械的に作っています"
                    "（LLM に文章を作らせていません）。"
                )

            st.divider()
            st.subheader("AIアシスタント", anchor=False)
            st.caption(
                "このプランをレビューし、費用・品質・作業量の希望に合わせて3案から再提案します。"
                "タスク自体の変更が必要な場合は、修正箇所も案内します。"
            )

            chat_history: list[dict[str, object]] = st.session_state["ws_plan_chat"]
            if not chat_history:
                with st.chat_message("assistant", avatar=":material/smart_toy:"):
                    st.markdown(
                        f"現在は **{selected_plan.label}** を選択しています。"
                        "「もっと安くしたい」「品質を優先したい」「この配分の弱点は？」など、"
                        "希望や懸念を教えてください。"
                    )

            for index, item in enumerate(chat_history):
                role = str(item.get("role") or "assistant")
                with st.chat_message(role):
                    st.markdown(str(item.get("content") or ""))
                    recommendation = item.get("recommended_plan_kind")
                    target = next(
                        (plan for plan in plans if plan.kind == recommendation and plan.runnable),
                        None,
                    )
                    if target is not None and target.kind != selected_plan.kind:
                        if st.button(
                            f"「{target.label}」へ切り替える",
                            key=f"ws_apply_plan_review_{index}",
                            type="primary",
                        ):
                            st.session_state["ws_selected_plan"] = target.kind
                            st.session_state["ws_run"] = None
                            chat_history.append(
                                {
                                    "role": "assistant",
                                    "content": (
                                        f"{target.label}へ切り替えました。"
                                        "変更後の内容も続けて相談できます。"
                                    ),
                                }
                            )
                            st.rerun()

            prompt = st.chat_input(
                "例：品質を落としすぎず、もう少し安い案にできますか？",
                key="ws_plan_chat_input",
            )
            if prompt:
                previous_history = list(chat_history)
                chat_history.append({"role": "user", "content": prompt})
                with st.chat_message("user"):
                    st.markdown(prompt)
                with st.chat_message("assistant", avatar=":material/smart_toy:"):
                    with st.spinner("プランをレビューしています…"):
                        answer = review_plan(
                            prompt,
                            selected=selected_plan,
                            plans=plans,
                            tasks=tasks,
                            history=previous_history,
                        )
                    st.markdown(answer.content)
                    if not answer.used_llm:
                        st.caption("AI API未接続のため、計算済みデータによるローカルレビューです。")
                chat_history.append(
                    {
                        "role": "assistant",
                        "content": answer.content,
                        "recommended_plan_kind": answer.recommended_plan_kind,
                        "used_llm": answer.used_llm,
                    }
                )
                st.rerun()

            summary_column, run_column = st.columns([2.2, 1], vertical_alignment="center")
            solver_label = (
                "Amplify AE"
                if selected_plan.solver_method == "amplify"
                else (
                    "D-Wave Advantage（Amplify経由）"
                    if selected_plan.solver_method == "dwave"
                    else "Greedy（古典・貪欲法）"
                )
            )
            # st.markdown だと "$1.23" が LaTeX の数式区切りとして食われるため st.html で描く。
            summary_column.html(
                f"<b>{esc(len(results_by_task))} タスク / "
                f"合計 {esc(_money(selected_plan.total_cost))}</b>"
                f'<span class="qo-muted">　（上限 {esc(_money(selected_plan.budget_cap))}・'
                f"求解 {esc(solver_label)}）</span>"
            )
            already_running = bool(run and run.get("status") == "queued")
            if run_column.button(
                "このプランで模擬実行",
                type="primary",
                width="stretch",
                disabled=already_running,
            ):
                st.session_state["ws_run"] = {
                    "delivery_id": str(time.time_ns()),
                    "request": st.session_state["ws_request"],
                    "completed": {},
                    "artifacts": {},
                    "plan_kind": selected_plan.kind,
                    "revision": st.session_state["ws_plan_revision"],
                    "status": "queued",
                    "states": {},
                }
                st.session_state["ws_reviews"] = {}
                st.session_state["ws_rerun"] = None
                st.rerun()


# --------------------------------------------------------------------------- #
# E. 実行状況（SIMULATED EXECUTION）
# --------------------------------------------------------------------------- #
if run and plans:
    section_anchor("section-run")
    active_plan = next((p for p in plans if p.kind == run.get("plan_kind")), None)
    stale = run.get("revision") != st.session_state["ws_plan_revision"]

    with st.container(key="qopanel-run"):
        section_head("SIMULATED EXECUTION", "実行状況")
        if active_plan is None or stale:
            # 実行中のプランは固定スナップショット。入力が変わったら結果を上書きしない。
            st.warning(
                "入力が変更されたため、この実行結果は現在の条件と一致しません。"
                "計算し直してから、もう一度実行してください。",
                icon="⚠️",
            )
        else:
            st.info(
                "これは模擬実行です。文書・コード・画像の生成 API は呼び出しておらず、"
                "成果物は作成されません。表示されるのは、選択したプランで生成する予定の"
                "成果物一覧です。",
                icon="🧪",
            )
            by_id = {t.id: t for t in tasks}
            results_by_task = {r["task_id"]: r for r in active_plan.result.get("task_results", [])}

            if run["status"] == "queued":
                progress = st.progress(0.0, text="実行を開始しています…")
                status_line = st.empty()
                flow_slot = st.empty()
                states: dict[str, str] = {}
                level_list = active_plan.workflow_levels
                total = max(1, len(level_list))

                def _draw(levels_to_draw, current_states):
                    blocks = []
                    deps: dict[str, list[str]] = {}
                    for level in levels_to_draw:
                        nodes = ""
                        for task_id in level:
                            task = by_id.get(task_id)
                            result = results_by_task.get(task_id)
                            if task is None or result is None:
                                continue
                            shown = [d for d in task.dependencies if d in by_id]
                            if shown:
                                deps[task.id] = shown
                            nodes += node_html(
                                display_id=task.id,
                                category=plan_category_of(task.role),
                                title=task.title,
                                model=str(
                                    result.get("model_display_name", result["selected_model"])
                                ),
                                depends_on=(
                                    "、".join(task.dependencies) if task.dependencies else "—"
                                ),
                                cost=_money(float(result["cost"])),
                                state=current_states.get(task_id, ""),
                            )
                        blocks.append(nodes)
                    return workflow_html(blocks, deps)

                for index, level in enumerate(level_list, start=1):
                    for task_id in level:
                        states[task_id] = "running"
                    names = "、".join(by_id[t].title for t in level if t in by_id)
                    status_line.markdown(f"STEP {index} を実行中: {names}")
                    flow_slot.html(_draw(level_list, states))
                    time.sleep(SIMULATION_STEP_SEC)
                    for task_id in level:
                        states[task_id] = "done"
                    progress.progress(index / total, text=f"STEP {index} / {total} 完了")

                flow_slot.html(_draw(level_list, states))
                status_line.markdown("すべての段が完了しました。")
                run["states"] = states
                run["status"] = "succeeded"
                st.session_state["ws_run"] = run
                st.rerun()

            else:
                st.progress(1.0, text="完了")
                st.markdown("#### 生成する予定の成果物")
                run_revision = str(run.get("revision") or "")
                reviews: dict[str, str] = st.session_state["ws_reviews"]
                completed = run.setdefault("completed", {})
                artifacts = run.setdefault("artifacts", {})
                delivery_id = run.setdefault("delivery_id", str(time.time_ns()))
                review_epoch = run.setdefault("review_epoch", 0)
                st.caption("各行の「完了」にチェックすると、全件完了後にダウンロードできます。")
                for category in PLAN_CATEGORIES:
                    rows = [
                        (t, results_by_task[t.id])
                        for t in tasks
                        if plan_category_of(t.role) == category and t.id in results_by_task
                    ]
                    if not rows:
                        continue
                    st.markdown(f"**{CATEGORY_LABELS[category]}**")
                    task_ids = [t.id for t, _ in rows]
                    edited = st.data_editor(
                        pd.DataFrame(
                            {
                                "ID": task_ids,
                                "成果物（予定）": [
                                    f"{t.deliverable or '成果物'}"
                                    + (f" × {t.quantity} 枚" if category == "image" else "")
                                    for t, _ in rows
                                ],
                                "担当モデル": [
                                    r.get("model_display_name", r["selected_model"])
                                    for _, r in rows
                                ],
                                "費用(USD)": [round(float(r["cost"]), 4) for _, r in rows],
                                "状態": [
                                    "準備済み" if artifacts.get(tid) else "未生成（模擬実行）"
                                    for tid in task_ids
                                ],
                                "成果物リンク": [
                                    _deliverable_link(run_revision, tid) for tid in task_ids
                                ],
                                "レビュー": [reviews.get(tid, "") for tid in task_ids],
                                "完了": [completed.get(tid, False) for tid in task_ids],
                            }
                        ),
                        hide_index=True,
                        width="stretch",
                        disabled=[
                            "ID",
                            "成果物（予定）",
                            "担当モデル",
                            "費用(USD)",
                            "状態",
                            "成果物リンク",
                        ],
                        column_config={
                            "完了": st.column_config.CheckboxColumn(
                                "完了", help="レビューが完了したらチェック"
                            ),
                            "費用(USD)": st.column_config.NumberColumn("費用(USD)", format="%.4f"),
                            "成果物リンク": st.column_config.LinkColumn(
                                "成果物リンク", display_text="開く（プレースホルダー）"
                            ),
                            "レビュー": st.column_config.TextColumn(
                                "レビュー", help="人によるレビューコメントを入力してください。"
                            ),
                        },
                        key=f"qo-review-{category}-{delivery_id}-{review_epoch}",
                    )
                    for tid, comment in zip(task_ids, edited["レビュー"], strict=True):
                        if reviews.get(tid, "") != str(comment or ""):
                            completed[tid] = False
                        else:
                            row_index = task_ids.index(tid)
                            completed[tid] = bool(edited.iloc[row_index]["完了"])
                        reviews[tid] = str(comment or "")
                st.session_state["ws_reviews"] = reviews
                if st.button(
                    "すべてのレビューを完了",
                    key=f"complete-all-{delivery_id}",
                    disabled=not tasks,
                ):
                    completed.update({t.id: True for t in tasks})
                    run["review_epoch"] += 1
                    st.rerun()
                architecture = ""
                ready = bool(tasks) and all(
                    completed.get(t.id) for t in tasks
                )
                done_count = sum(bool(completed.get(t.id)) for t in tasks)
                st.caption(f"レビュー完了 {done_count} / {len(tasks)} 件")
                delivery_zip = build_delivery(
                    tasks, active_plan, run, reviews, completed, artifacts, architecture
                ) if ready else b""
                report_pdf = b""
                if ready:
                    with ZipFile(io.BytesIO(delivery_zip)) as archive:
                        report_pdf = archive.read("タスク実行報告.pdf")
                st.download_button(
                    "成果物ZIPをダウンロード",
                    data=delivery_zip,
                    file_name=f"task-delivery-{delivery_id}.zip",
                    mime="application/zip",
                    disabled=not ready,
                    width="stretch",
                    key=f"download-delivery-{delivery_id}",
                )
                st.download_button(
                    "実行報告PDFをダウンロード", data=report_pdf,
                    file_name=f"yakizakana-report-{delivery_id}.pdf",
                    mime="application/pdf", disabled=not ready, width="stretch",
                    key=f"download-report-{delivery_id}",
                )
                st.caption(
                    "模擬実行ではZIPに実行報告を収録します。"
                    "コード・画像・文章の実ファイルは、生成機能の接続後に収録されます。"
                )

                # -------------------------------------------------------------- #
                # レビューを踏まえた再実行（余った予算の中から抽出）
                # -------------------------------------------------------------- #
                leftover_budget = round(
                    max(0.0, active_plan.budget_cap - active_plan.total_cost), 4
                )
                flagged_ids = [
                    tid
                    for tid in results_by_task
                    if reviews.get(tid, "").strip() and not completed.get(tid, False)
                ]
                st.markdown("#### レビューを踏まえて再実行")
                st.caption(
                    "レビューが入力されたタスクだけを、このプランの余った予算 "
                    f"{_money(leftover_budget)}（目安上限 {_money(active_plan.budget_cap)} − "
                    f"実行費用 {_money(active_plan.total_cost)}）の範囲で再求解します。"
                    "3プラン比較はせず、精度優先（コストは目的関数から外す）に固定します。"
                )
                rerun_disabled = leftover_budget <= 0 or not flagged_ids
                if rerun_disabled:
                    st.caption(
                        "再実行するには、少なくとも1件にレビューを入力し、"
                        "かつ余った予算が残っている必要があります。"
                    )
                if st.button(
                    f"レビュー済み {len(flagged_ids)} 件を再実行",
                    disabled=rerun_disabled,
                    width="stretch",
                ):
                    by_id_all = {t.id: t for t in tasks}
                    rerun_tasks = [by_id_all[tid] for tid in flagged_ids if tid in by_id_all]
                    rerun_result = _rerun_flagged_tasks(
                        rerun_tasks, leftover_budget, [a.id for a in agents]
                    )
                    st.session_state["ws_rerun"] = {
                        "revision": run_revision,
                        "task_ids": flagged_ids,
                        "budget_used": leftover_budget,
                        "result": rerun_result,
                    }
                    run.setdefault("rerun_reports", []).append(
                        {
                            "task_ids": list(flagged_ids),
                            "reviews": {tid: reviews.get(tid, "") for tid in flagged_ids},
                            "status": rerun_result.get("status"),
                            "estimated_cost": rerun_result.get("total_cost", 0),
                        }
                    )
                    for tid in flagged_ids:
                        completed[tid] = False
                    run["review_epoch"] += 1
                    st.rerun()

                rerun = st.session_state["ws_rerun"]
                if rerun and rerun.get("revision") == run_revision:
                    rerun_result = rerun["result"]
                    if rerun_result.get("status") != "success":
                        st.error(
                            "再実行に失敗しました: "
                            + str(rerun_result.get("message") or "不明なエラー")
                        )
                    else:
                        rerun_task_results = {
                            r["task_id"]: r for r in rerun_result.get("task_results", [])
                        }
                        by_id_all = {t.id: t for t in tasks}
                        st.dataframe(
                            pd.DataFrame(
                                {
                                    "ID": list(rerun_task_results.keys()),
                                    "タイトル": [
                                        by_id_all[tid].title
                                        for tid in rerun_task_results
                                        if tid in by_id_all
                                    ],
                                    "レビュー": [
                                        reviews.get(tid, "") for tid in rerun_task_results
                                    ],
                                    "再実行後モデル": [
                                        r.get("model_display_name", r["selected_model"])
                                        for r in rerun_task_results.values()
                                    ],
                                    "費用(USD)": [
                                        round(float(r["cost"]), 4)
                                        for r in rerun_task_results.values()
                                    ],
                                }
                            ),
                            hide_index=True,
                            width="stretch",
                            column_config={
                                "費用(USD)": st.column_config.NumberColumn(
                                    "費用(USD)", format="%.4f"
                                )
                            },
                        )
                        st.caption(
                            f"再実行に使った予算: {_money(float(rerun_result['total_cost']))} / "
                            f"割当可能だった予算 {_money(rerun['budget_used'])}"
                        )


# --------------------------------------------------------------------------- #
# F. モデル一覧・料金の出典・計算条件
# --------------------------------------------------------------------------- #
section_anchor("section-catalog")
with st.container(key="qopanel-catalog"):
    with st.expander("モデル一覧・料金の出典・計算条件", expanded=False):
        selected_solver = str(st.session_state.get("ws_solver", "amplify"))
        actual_solver = selected_solver
        if plans:
            selected_plan_for_catalog = next(
                (plan for plan in plans if plan.kind == st.session_state.get("ws_selected_plan")),
                None,
            )
            if selected_plan_for_catalog is not None and selected_plan_for_catalog.solver_method:
                actual_solver = selected_plan_for_catalog.solver_method

        solver_labels = {
            "amplify": "Fixstars Amplify AE",
            "dwave": "D-Wave Advantage（Amplify経由）",
            "greedy": "Greedy（古典・貪欲法）",
        }
        solver_state = solver_labels.get(actual_solver, actual_solver)
        using_groq = bool(os.getenv("GROQ_API_KEY"))
        llm_provider = "Groq" if using_groq else "OpenAI"
        llm_default_model = "openai/gpt-oss-120b" if using_groq else "gpt-4o-mini"
        llm_model = os.getenv("GROQ_MODEL" if using_groq else "OPENAI_MODEL", llm_default_model)
        llm_service = f"LLM（{llm_provider} / {llm_model}）"
        llm_connection = "設定済み" if ui_helpers.llm_available() else "未設定"
        amplify_connection = "設定済み" if os.getenv("FIXSTARS_AMPLIFY_TOKEN") else "未設定"
        dwave_connection = "設定済み" if os.getenv("DWAVE_API_TOKEN") else "未設定"
        st.markdown(f"**使用サービス** — 求解: {solver_state}　/　タスク分解: {llm_service}")
        st.markdown(
            f"**接続状態** — Amplify AE: {amplify_connection}"
            f"　/　D-Wave: {dwave_connection}　/　タスク分解LLM: {llm_connection}"
        )
        st.caption(model_source_note())
        st.caption(
            "この表は全 "
            f"{len(ui_helpers.models_df())} モデル。最適化の候補は"
            "『予算とモデル選定』で選んだ範囲だけです（旧バージョン・ベンチ専用は除外済み）。"
        )
        st.dataframe(
            ui_helpers.models_df(),
            hide_index=True,
            width="stretch",
            column_config={"出典": st.column_config.LinkColumn("出典", display_text="開く")},
        )
        st.markdown(f"**出典** — {ui_helpers.source_links_md()}")
        st.markdown(f"""
**計算条件**

- 費用は「タスク 1 件あたりの実測コスト × 難易度補正（難易度3を基準に ±12%/段） × 個数」。
  実測コストが無いモデルは API 単価（USD / 100万 tokens）からの推計、それも無ければ既定値。
  トークン単価の積み上げではないため、比較カードに入力/出力 tokens は表示していません。
- 品質は公開ベンチマークの実測値を役割ブレンドで合成した 0-1 のスコアを 0-5 へ換算した値です
  （デモの仮定スコアではありません）。難易度が 1 段上がるごとに 0.12 低下する補正を掛けます。
- **代理指標の注意**: 「文書作成」タスクの品質は IDP Leaderboard の**文書理解・抽出**の実測値を
  代理指標として使っています。文章を書く能力そのものを測ったベンチマークではないため、
  文書タスクに OCR 特化モデルが選ばれることがあります。画像は「画像生成」の実測値
  （Image Arena）なので、画像理解しかできないモデルが画像生成へ割り当たることはありません。
- 3 プランの違いは、予算上限（最大予算の 30% / 60% / 100%）と編成モードの重み
  α・β・γ だけです。同じ配分になった場合は、そのまま同じと表示します。
- 制約は C1（各タスクにちょうど 1 モデル）・C2（能力なし / 機密タスク×社外モデルを除外）・
  C3（合計実コスト ≤ 予算上限）。締切 C4 と負荷分散 μ は未実装です。
- 求解は選択したソルバ（{solver_state}）で行います。選択したソルバが利用できない場合は
    Greedy（古典・貪欲法）へ切り替わります。実際にどのソルバで解いたかは、
    選択プランの下にも表示します。
- 費用は生成タスクの見積もりのみで、プラン作成・再試行・キャッシュ・外部検索・税金は含みません。
  実際の課金・文書作成・コード生成・画像生成は行いません。
""")

    with st.expander("従来の4画面（詳細モード）", expanded=False):
        st.caption(
            "候補モデルの絞り込み、手法比較グラフ、JSON / CSV エクスポートは"
            "従来の画面に残しています。こちらの画面はワークスペースとは別の状態を持ちます。"
        )
        for path, label, icon in (
            ("pages/1_タスク設定.py", "1. タスク設定", "1️⃣"),
            ("pages/2_エージェント設定.py", "2. エージェント設定", "2️⃣"),
            ("pages/3_最適化実行.py", "3. 最適化実行", "3️⃣"),
            ("pages/4_アウトプット.py", "4. アウトプット", "4️⃣"),
        ):
            st.page_link(path, label=label, icon=icon)
