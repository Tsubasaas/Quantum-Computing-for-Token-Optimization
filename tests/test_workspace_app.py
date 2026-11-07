"""ワークスペース画面を `AppTest` で通し確認する（ブラウザなし・ヘッドレス）。

UI 実装プロンプト §8「状態管理・変更時の挙動」と §11 の受け入れ条件のうち、
画面を動かさないと確かめられないものだけをここで見る。

本モジュールは全体が生成 AI（Claude）支援で作成されています。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app" / "app.py"
LEGACY_PAGES = [
    "pages/1_タスク設定.py",
    "pages/2_エージェント設定.py",
    "pages/3_最適化実行.py",
    "pages/4_アウトプット.py",
]


def _button(app: AppTest, needle: str):
    return next(b for b in app.button if needle in b.label)


def _select_greedy(app: AppTest) -> None:
    """API 未設定のテストでは Greedy を明示選択する（amplify は自動フォールバックしない）。"""

    next(s for s in app.selectbox if s.label == "最適化ソルバ").set_value(
        "Greedy（古典・貪欲法）"
    ).run()


def _html_bodies(app: AppTest) -> str:
    return " ".join(str(getattr(element, "body", "")) for element in app.get("html"))


@pytest.fixture
def app() -> AppTest:
    instance = AppTest.from_file(str(APP), default_timeout=300).run()
    assert not instance.exception, [e.value for e in instance.exception]
    return instance


@pytest.fixture
def planned(app: AppTest) -> AppTest:
    """3 プランまで計算した状態。"""

    _button(app, "タスクを分解する").click().run()
    _select_greedy(app)
    _button(app, "この条件で最適化する").click().run()
    assert not app.exception, [e.value for e in app.exception]
    return app


def test_initial_render_shows_only_the_brief_step(app: AppTest):
    assert app.session_state["ws_tasks"] == []
    assert app.session_state["ws_plans"] == []
    # 最初に見えるのは要望入力と種類の選択だけ
    assert len(app.text_area) == 1
    assert {c.label for c in app.checkbox} >= {"文書作成", "開発・プログラミング", "画像生成"}


def test_section_shortcuts_disable_future_sections(app: AppTest):
    """初期表示では未生成の後続セクションをリンクにしない。"""
    initial_html = _html_bodies(app)
    assert "qo-section-nav" in initial_html
    assert 'href="#section-brief"' in initial_html
    assert 'href="#section-catalog"' in initial_html
    assert 'href="#section-tasks"' not in initial_html
    assert 'aria-disabled="true"' in initial_html


def test_section_shortcuts_link_to_rendered_sections(planned: AppTest):
    """プラン作成後は表示済みセクションのアンカーへ移動できる。"""
    planned_html = _html_bodies(planned)
    for anchor in ("section-tasks", "section-scope", "section-plans", "section-workflow"):
        assert f'href="#{anchor}"' in planned_html
        assert f'id="{anchor}"' in planned_html
    assert 'href="#section-run"' not in planned_html


def test_section_nav_tracks_the_section_in_view(app: AppTest):
    """今見ているセクションを強調する仕掛け（追従スクリプトと .active）があること。"""

    html = _html_bodies(app)
    # スクロール追従スクリプト（前回リスナーを捨てる stop() つき）
    assert "__qoSectionSpy" in html
    assert 'window.addEventListener("scroll"' in html
    # ホバーとは別に、現在地用のスタイルが定義されている
    assert ".qo-section-nav a.active" in html


def test_full_flow_reaches_simulated_execution(planned: AppTest):
    assert len(planned.session_state["ws_plans"]) == 3
    assert planned.session_state["ws_selected_plan"] == "balanced"

    _button(planned, "模擬実行").click().run()
    run = planned.session_state["ws_run"]

    assert not planned.exception, [e.value for e in planned.exception]
    assert run["status"] == "succeeded"
    # 全タスクが done まで進む。成果物は作らないので「未生成」表示のまま
    assert set(run["states"].values()) == {"done"}
    assert len(run["states"]) == len(planned.session_state["ws_tasks"])
    run_html = _html_bodies(planned)
    assert 'href="#section-run"' in run_html
    assert 'id="section-run"' in run_html


def test_selected_plan_has_a_conversational_assistant(planned: AppTest):
    assert len(planned.chat_input) == 1
    assert "品質を落としすぎず" in planned.chat_input[0].placeholder
    assert any("AIアシスタント" in subheader.value for subheader in planned.subheader)


def test_delivery_unlocks_without_upload_ui(planned):
    _button(planned, "模擬実行").click().run()
    assert planned.get("download_button")[0].proto.disabled
    assert not any("成果物を添付" in e.label for e in planned.expander)
    _button(planned, "すべてのレビューを完了").click().run()
    assert not planned.exception
    downloads = planned.get("download_button")
    assert {d.proto.label for d in downloads} == {
        "成果物ZIPをダウンロード", "実行報告PDFをダウンロード"
    }
    assert all(not d.proto.disabled for d in downloads)
    planned.run()
    assert not planned.exception
    assert all(not d.proto.disabled for d in planned.get("download_button"))


def test_assistant_keeps_history_and_offers_plan_switch(planned: AppTest, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    planned.chat_input[0].set_value("もっと安くしたい").run()

    history = planned.session_state["ws_plan_chat"]
    assert [message["role"] for message in history] == ["user", "assistant"]
    assert history[-1]["recommended_plan_kind"] == "cost"
    assert any("コスト重視" in button.label for button in planned.button)
    assert not planned.exception


def test_switching_plan_discards_the_previous_run(planned: AppTest):
    _button(planned, "模擬実行").click().run()
    assert planned.session_state["ws_run"] is not None

    # 未選択のカードを選ぶ（"選択中" は disabled なのでクリック対象にならない）
    next(b for b in planned.button if b.label == "このプランを選択").click().run()

    assert planned.session_state["ws_selected_plan"] != "balanced"
    assert planned.session_state["ws_run"] is None


def test_editing_tasks_invalidates_plans_and_run(planned: AppTest):
    """入力を変えたら、古いプランを実行できないこと（§11）。"""

    _button(planned, "模擬実行").click().run()
    assert planned.session_state["ws_plans"]

    planned.session_state["ws_tasks"][0].difficulty = 1
    planned.run()

    assert planned.session_state["ws_plans"] == []
    assert planned.session_state["ws_run"] is None
    assert planned.session_state["ws_plan_revision"] == ""
    assert not planned.exception


def test_changing_budget_invalidates_plans_but_keeps_tasks(planned: AppTest):
    tasks_before = list(planned.session_state["ws_tasks"])
    planned.number_input[0].set_value(30.0).run()

    assert planned.session_state["ws_plans"] == []
    assert planned.session_state["ws_tasks"] == tasks_before


def test_unchanged_input_keeps_plans_across_reruns(planned: AppTest):
    """revision 照合が毎回プランを捨てて再実行ループになっていないこと。"""

    planned.run()
    planned.run()

    assert len(planned.session_state["ws_plans"]) == 3
    assert not planned.exception


def test_tiny_budget_shows_every_plan_as_infeasible(app: AppTest):
    _button(app, "タスクを分解する").click().run()
    _select_greedy(app)
    app.number_input[0].set_value(0.02).run()
    _button(app, "この条件で最適化する").click().run()

    assert all(not p.feasible for p in app.session_state["ws_plans"])
    assert app.session_state["ws_selected_plan"] == ""
    # 実行ボタンは出さない（課金の起点はプラン選択後の実行だけ）
    assert not [b for b in app.button if "模擬実行" in b.label]
    assert any("実行できません" in e.value for e in app.error)


def test_empty_request_reports_an_error_without_building_tasks(app: AppTest):
    app.text_area[0].set_value("   ").run()
    _button(app, "タスクを分解する").click().run()

    assert app.session_state["ws_tasks"] == []
    assert app.session_state["ws_error"] == "要望を入力してください。"


def test_no_category_selected_reports_an_error(app: AppTest):
    for category in ("doc", "code", "image"):
        app.session_state[f"ws_cat_{category}"] = False
    app.run()
    _button(app, "タスクを分解する").click().run()

    assert app.session_state["ws_tasks"] == []
    assert app.session_state["ws_error"] == "タスクの種類を1つ以上選択してください。"


def test_breakdown_drops_workload_estimate_editor(app: AppTest):
    """作業量の編集欄（見積もりの前提を調整）は廃止されていること。"""

    _button(app, "タスクを分解する").click().run()
    assert not app.exception
    assert not [e for e in app.expander if "見積もり" in e.label]
    assert "作業量" not in " ".join(m.value for m in app.markdown)


def test_candidate_models_default_excludes_stale_and_enforces_floor(app: AppTest):
    _button(app, "タスクを分解する").click().run()

    selected = app.session_state["ws_candidate_models"]
    assert len(selected) >= 2
    # 旧バージョン・ベンチ専用モデルは候補に出ない
    assert "claude_opus_47" not in selected
    assert "claude_mythos_5" not in selected

    app.session_state["ws_candidate_models"] = selected[:1]
    app.run()
    assert any("2 件以上" in e.value for e in app.error)


def test_workflow_graph_has_dependency_hover_rules(planned: AppTest):
    """実行フロー図のノードにも、前提を強調する :has() ルールが載ること。"""

    bodies = " ".join(str(getattr(el, "body", "")) for el in planned.get("html"))
    assert 'data-task="T001"' in bodies
    assert ".qo-workflow:has(.qo-node[data-task=" in bodies


def test_changing_models_invalidates_plans(planned: AppTest):
    planned.session_state["ws_candidate_models"] = planned.session_state["ws_candidate_models"][:3]
    planned.run()
    assert planned.session_state["ws_plans"] == []


@pytest.mark.parametrize("page", LEGACY_PAGES)
def test_legacy_pages_still_open(app: AppTest, page: str):
    """従来の4画面は st.navigation 配下でそのまま開ける。"""

    app.switch_page(page).run()
    assert not app.exception, [e.value for e in app.exception]
