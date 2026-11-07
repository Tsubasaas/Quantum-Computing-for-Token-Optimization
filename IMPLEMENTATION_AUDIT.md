# 実装監査 — 生成 AI 利用の記録

ハッカソン規約に基づき、生成 AI（Claude）が関与した箇所を記録します。

## 表記ルール

- AI が生成したコード片は `# ===== AI生成: <内容> ここから =====` … `ここまで` で囲む。
- 全体が AI 支援で作成されたモジュールは冒頭 docstring に一行明記する。
- 毎日のコードフリーズ時にこの台帳を更新する（後追いでまとめない）。

## モジュール一覧（2026-09-08 時点）

| 区分 | パス | 目的 | 生成 AI 関与 | 検証 |
|---|---|---|---|---|
| モデル | `src/taqumi2026s_teame/models.py` | ドメイン dataclass | 雛形を AI 生成、内容はチームで確認 | mypy strict / import テスト |
| 設定 | `src/taqumi2026s_teame/config.py` | 編成モードのプリセット | AI 生成 | — |
| データ | `src/taqumi2026s_teame/data/benchmarks.csv` | SWE-rebench 実測値（解決率 / Pass@5 / Cost・Tokens per Problem、2026-05-15〜07-01、111 問） | 出典 [swe-rebench.com](https://swe-rebench.com/) を人手で転記。ローダは AI 生成 | `test_benchmarks_are_verified_and_sane` / `test_agents_join_benchmarks` |
| データ | `src/taqumi2026s_teame/data/agents.json`, `sample_tasks.json` | エージェントのメタ情報・役割バイアス（推定）・サンプルタスク | AI 生成。`role_bias` は推定補正（±0.10）で未検証 | `test_coefficient_shapes` |
| QUBO | `src/taqumi2026s_teame/qubo/coefficients.py` | q/r/c/t/w 係数行列 | AI 生成 | 係数 shape・値域テスト |
| ソルバ | `src/taqumi2026s_teame/solvers/classical.py` | Random / Greedy | AI 生成 | 割当一意・機密尊重・決定性・Greedy≥Random |
| ソルバ | `src/taqumi2026s_teame/solvers/amplify_solver.py` | Amplify AE 求解 | AI 生成（教材の Amplify パターンを踏襲） | トークン無しガードパス / モデル構築を手動確認（66 変数・予算制約） |
| 評価 | `src/taqumi2026s_teame/evaluation/metrics.py` | 割当 → メトリクス | AI 生成 | コスト合計 == 手計算 |
| LLM | `src/taqumi2026s_teame/llm/decompose.py` | 自然言語 → タスク JSON。参照ファイルを追加コンテキストに使う。失敗時サンプル | AI 生成 | `test_decompose_fallback_without_llm` / `test_decompose_request_reports_that_llm_was_not_used` |
| UI | `app/app.py`, `app/pages/1-4`, `app/ui_helpers.py` | Streamlit 4 画面 | AI 生成 | `streamlit.testing.v1.AppTest` で全 5 ページ例外なし + 実行フロー |
| テスト | `tests/test_optimization.py`, `tests/test_task_setting_ui.py` | 34 ケース | AI 生成 | 全通過 |

## 画面 1 の改修（2026-09-08）

タスク設定画面が「サンプルが最初から入っている編集画面」になっており、
アプリの主動線（開発要求 → 分解 → 割当）と入口がずれていた。以下を修正。

| # | 内容 | 影響 |
|---|---|---|
| 1 | `st.success()` の直後に `st.rerun()` を呼び、メッセージが一度も表示されていなかった（4 箇所）。`session_state` 経由のフラッシュに変更 | バグ修正 |
| 2 | LLM 未使用のフォールバックを「成功」と表示していた。`Decomposition.used_llm` を追加し success / warning を出し分け | バグ修正 |
| 3 | 「開発要求からの一括生成」を折りたたみの「（任意）」から 1 章へ昇格。`OPENAI_API_KEY` がある時のみチェック可・既定オン | 動線 |
| 4 | `tasks_dict` に `difficulty` / `dependencies` を追加（要件定義書の必須 7 カラムは維持）。LLM が返す難易度・依存を捨てなくなった | 最適化結果 |
| 5 | 予算の単位を USD に統一し、画面 1 を正本に。画面 2 の予算スライダーを表示のみへ（従来は 1000 が 60 に切り詰められていた） | 最適化結果 |
| 6 | 参照ファイルを 1 章へ移し、本文を実際に LLM へ渡すようにした（PDF は本文抽出未対応・ファイル名のみ記録） | 説明と実装の一致 |
| 7 | サンプルデータ表示中であることをバナーで明示 | 誤解防止 |
| 8 | 生成結果の「置換 / 追記」を選択可に。手編集済みの置換は確認チェックを要求。追記時は依存関係の ID を張り替え | 事故防止 |
| 9 | 一覧・編集・削除の 3 タブを `st.data_editor` に統合 | 操作性 |

## タスクIDと依存タスクの改修（2026-09-08）

レビュー指摘を受けた追加修正。

| # | 内容 | 影響 |
|---|---|---|
| 10 | タスクIDの桁数を 3 桁ゼロ詰め（`T001`）に統一。`normalize_task_id()` を追加し、`sample_tasks.json` を `T001..T012` へ、LLM プロンプトも 3 桁指定へ変更。従来は `T12` の次が `T013` になり桁が混在していた | 表示の一貫性 |
| 11 | ID 正規化で衝突した場合は採番し直すようにした。従来は LLM が同じ ID を 2 回返すと辞書の後勝ちでタスクが黙って消えていた（3 件 → 2 件） | データ欠落の防止 |
| 12 | 依存タスクを自由入力から **タスクIDの選択式**（`st.multiselect`）へ変更。表の依存列は読み取り専用にし、自分自身は選択肢から除外。依存先が削除された場合は宙に浮いた依存を外して警告表示 | 入力ミスの防止 |

## 検証結果（2026-09-08 更新）

- `uv run pytest -q` — 34 passed。
- `uv run ruff check .` / `ruff format --check .` — クリーン。
- `uv run mypy src` — Success（`app/` は strict 対象外）。
- `AppTest` — `app.py` / 4 ページすべて例外なし。画面 1 → 2 → 3 → 4 を通し確認。
  - 画面 1 の予算 $15.00 が画面 2 の `SolveOptions.budget` にそのまま届くことを確認。
  - サンプル 12 タスクの難易度・依存関係が `tasks_dict` 往復後も保持されることを確認。
  - LLM キー無しで生成すると warning（success ではない）が再実行後に表示されることを確認。
  - 画面 3 で Greedy 実行 → 総コスト $13.88 / 実行可能。
  - 依存タスクの multiselect で `T005` の依存を変更 → `tasks_dict` とソルバへ渡る
    `Task.dependencies` に反映されることを確認。依存先タスクを削除しても例外にならず、
    宙に浮いた依存を外して警告表示することを確認。
- ヘッドレス Edge（CDP）で画面 1 を実描画し、タスクIDが `T001..T012` で揃うこと、
  依存タスクがタグ表示の選択式になっていることを目視確認。
- Amplify モデル構築を手動確認: 二値変数 66 個（機密 × 社外 18 ペアを 0 固定）、one-hot 制約 12、予算 `less_equal` 制約 1。

## 既知の未対応

- `st.graphviz_chart(..., use_container_width=True)` が画面 3・4 に残っており、Streamlit の
  非推奨警告が出る（`width="stretch"` へ置き換えが必要）。
- タスクの依存関係は編成図に描画するのみで、スケジューリング制約としては最適化に入っていない。
- 削除したタスクIDが再利用される（`T014` を消して追加すると再び `T014`）。他タスクの依存が
  黙って別タスクを指すおそれがある。採番を単調増加にする必要がある。
- 画面 1 の表で右端の「依存」列が見切れる（横スクロールで参照可能。下のエディタでも確認できる）。
- 参照ファイルの上限はアプリ側で 10MB だが、アップローダの表示は Streamlit 既定の 200MB のまま
  （`server.maxUploadSize` の設定が必要）。
- `app/ui_helpers.py` の `tasks_to_df` / `df_to_tasks`（旧 data_editor 用）が未使用のまま残っている。

## 実行環境が必要な項目

- `FIXSTARS_AMPLIFY_TOKEN` — Amplify AE ソルバの実求解（未設定でも UI と古典ソルバは動作）。
- `OPENAI_API_KEY` — LLM タスク分解（未設定時はサンプルにフォールバック）。
- `GUROBI_SERVER` / `GUROBI_PASSWORD` — Gurobi 比較（未実装・将来用）。


## ワークスペース UI への移植（2026-09-10）

外部デザイン仕様「AI Task Planner — UIデザイン・操作フロー実装プロンプト」
（参照デモ: https://ai-task-planner-sylvia.yyi201342.chatgpt.site ）を、既存の QUBO
パイプラインへ接続した。**QUBO の目的関数・制約（C1/C2/C3）・評価設計は変更していない。**

| 区分 | パス | 目的 | 生成 AI 関与 | 検証 |
|---|---|---|---|---|
| ドメイン | `src/taqumi2026s_teame/planner.py` | 要望＋カテゴリ → タスク一覧 | AI 生成 | `test_workspace_flow.py`（全7カテゴリ組合せ・依存の健全性・キーワード追加） |
| ドメイン | `src/taqumi2026s_teame/plans.py` | 3プラン（予算 30/60/100%）の求解と集計 | AI 生成 | 予算遵守・内訳一致・画像モデル制限・全案不可 |
| ドメイン | `src/taqumi2026s_teame/workflow.py` | 依存関係 → STEP 段組み、循環検出 | AI 生成 | 段分け・循環・欠落の各テスト |
| UI | `app/app_pages/workspace.py` | 縦1枚のワークスペース画面 | AI 生成 | `AppTest` で 要望→タスク→プラン→模擬実行 を通し確認 |
| UI | `app/workspace_theme.py`, `.streamlit/config.toml` | デザイン基準（§3 / 付録B） | AI 生成 | Playwright で 1440px / 390px の実描画を目視確認 |
| テスト | `tests/test_workspace_flow.py` | ドメイン側の受け入れ条件 24 ケース | AI 生成 | 全通過 |
| テスト | `tests/test_workspace_app.py` | 画面の状態遷移・無効化 13 ケース（`AppTest`） | AI 生成 | 全通過 |

### 既存モジュールへの変更

| # | 変更 | 理由 | 影響 |
|---|---|---|---|
| 13 | `Task` に `quantity` / `deliverable` を追加。`quantity` はコスト行列 `c` を線形倍する | 画像枚数を変えたら費用が再計算される必要があるため（仕様 §11） | 変数・制約・目的関数の形は不変。`c` のスケールのみ |
| 14 | `OptimizationResult` に `feasible` / `within_budget` / `violations` / `solver_method` を NotRequired で追加 | 「この予算では実行できない」を UI が丸めた表示値でなく求解器の判定で出し分けるため | 既存の読み手には影響なし |
| 15 | `TaskResult` に `model_display_name` / `plan_category` / `quantity` を NotRequired で追加 | 画面表示用。最適化には使わない | なし |
| 16 | `total_cost` / タスク別 `cost` の丸めを 2 桁 → 4 桁へ | 表示の丸めで予算超過を見逃さないため（仕様 §4.D） | 表示桁数 |
| 17 | `data/task_types.py` に doc/code/image のカテゴリ写像と難易度ラベルを追加 | 利用者に見せる粒度を 3 種類に絞るため。QUBO へ渡るのは従来どおり ROLES | 最適化モデルは不変 |
| 18 | `app/app.py` を `st.navigation(position="hidden")` の入口に変更。従来 4 画面はページとして登録したまま残し、各画面にワークスペースへの戻りリンクを追加 | 「単一の縦スクロール画面」「サイドバーを追加しない」（仕様 最優先の条件 #2 / #10） | 既存 4 画面の内容は不変 |

### 未実装のまま残した箇所（成功と報告しない）

- **成果物の生成**: 04 実行は模擬実行のみ。文書・コード・画像の生成 API も成果物ストアも
  接続していない。画面上は「シミュレーション」バッジと「未生成（模擬実行）」で明示する。
- **文書作成タスクの品質指標**: IDP Leaderboard の「文書理解・抽出」を代理指標として
  使用している。文章生成能力そのものを測ったベンチマークではないため、文書タスクに
  OCR 特化モデルが選ばれることがある。カタログ欄に注記済み。
- **トークン見積もり**: このアプリの費用はタスク単位の実測コストで、トークン単価の
  積み上げではない。そのため比較カードに入力/出力 tokens は表示していない（仕様の
  項目をそのまま出すと、持っていない数値を作ることになるため）。
- **依存関係の順序制約**: STEP 段組みは表示と模擬実行の進行順のみ。QUBO の制約には未反映。

### 検証結果（2026-09-10）

- `uv run pytest -q` — 121 passed, 1 skipped。
- `uv run ruff check .` — クリーン。`ruff format` は今回追加・変更したファイルへ適用済み
  （既存の未整形ファイル 9 件はこの変更の対象外として据え置き）。
- `uv run mypy src` — Success（22 files）。
- `AppTest` — ワークスペースと従来 4 画面すべて例外なし。要望 → タスク → 3プラン →
  プラン切替 → 模擬実行 を通し確認。予算 $0.02 での全案実行不可、カテゴリ全 7 通りも確認。
- Playwright — 1440px と 390px で実描画を確認。モバイルで横スクロールが出ないこと
  （`scrollWidth == clientWidth == 390`）、3枚のカードが同じ高さに揃うことを確認。
