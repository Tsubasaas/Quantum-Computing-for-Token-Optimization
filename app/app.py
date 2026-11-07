"""Q-Orchestrator / AI Task Planner — アプリの入口。

ワークスペース（1 枚の縦スクロール画面）を既定にする。従来の 4 画面は
`st.navigation` に登録したまま残し、ワークスペース最下部のリンクから開ける。
`position="hidden"` にしているのはサイドバーのナビを出さないため
（UI 実装プロンプト 最優先の条件 #2 / #10）。
"""

from __future__ import annotations

import _boot  # noqa: F401
import streamlit as st
from workspace_theme import inject_css

st.set_page_config(
    page_title="Yakizakanaヤキザカナ",
    page_icon="🐟",
    layout="wide",
    initial_sidebar_state="collapsed",
)

inject_css()

page = st.navigation(
    [
        st.Page(
            "app_pages/workspace.py",
            title="Yakizakanaヤキザカナ",
            url_path="workspace",
            default=True,
        ),
        st.Page("pages/1_タスク設定.py", title="1. タスク設定", url_path="task-setting"),
        st.Page("pages/2_エージェント設定.py", title="2. エージェント設定", url_path="agents"),
        st.Page("pages/3_最適化実行.py", title="3. 最適化実行", url_path="optimize"),
        st.Page("pages/4_アウトプット.py", title="4. アウトプット", url_path="output"),
    ],
    position="hidden",
)
page.run()
