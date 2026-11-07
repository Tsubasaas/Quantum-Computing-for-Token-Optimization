# Quantum Computing for Token Optimization

開発要求をタスクに分解し、実在する AI コーディングエージェントへの割当を
**量子最適化（QUBO / Fixstars Amplify）** で決める Web アプリです。
一般化割当問題（NP 困難）として定式化し、古典手法（Random / Greedy）と比較検証します。

アプリ全体の役割、画面間のデータフロー、内部の最適化処理、各ファイルの責務、
実装済み／未実装の境界は **[`docs/APP_GUIDE.md`](docs/APP_GUIDE.md)** を参照してください。

## セットアップ

```bash
uv sync                 # 基本依存
cp .env.example .env     # 必要なトークンを記入（無くても Greedy / Random は動作）
```

LLM でタスク分解する場合は、`.env` に API キーを入れるだけ（openai SDK は基本依存に含まれる）:

```bash
# Groq を使う場合（既定モデルは GPT-OSS 120B）
# .env に GROQ_API_KEY（必要なら GROQ_BASE_URL / GROQ_MODEL）
# OpenAI を使う場合は OPENAI_API_KEY（必要なら OPENAI_BASE_URL / OPENAI_MODEL）
```

## 起動

```bash
uv run streamlit run app/app.py
```

起動すると **ワークスペース**（1 枚の縦スクロール画面）が開きます。操作が進むごとに
次のセクションが現れます。

1. **01 要望** — つくりたいものを書き、含めるタスクの種類（文書作成 / 開発・プログラミング /
   画像生成）を複数選択する
2. **02 タスク** — カテゴリ別のタスク・難易度・前提・成果物を確認して調整し、最大予算を決める
3. **03 プラン** — 予算の 30% / 60% / 100% を上限に解いた「コスト重視 / バランス / 精度重視」を
   比較し、1 つ選ぶ。選んだプランの実行フロー（STEP 段組み）とモデル配分の内訳が下に出る
4. **04 実行** — 依存段ごとに進行を表示する **模擬実行**。文書・コード・画像の生成 API は
   呼び出さず、成果物も作りません（「生成する予定の成果物」を一覧するだけ）

従来の 4 画面（候補モデルの絞り込み、手法比較グラフ、JSON / CSV エクスポート）は
そのまま残っており、ワークスペース最下部の「従来の4画面（詳細モード）」から開けます。
サイドバーのナビは出しません（`st.navigation(..., position="hidden")`）。

### 3 プランの作り方

3 案の違いは **予算上限の刻み**（最大予算の 30% / 60% / 100%）と、既存の編成モード重み
（`config.MODE_WEIGHTS` の α・β・γ）だけです。求解はどの案も既存の `run_optimization()` を
そのまま呼ぶので、QUBO の目的関数・制約（C1/C2/C3）は変えていません。**3 案に差をつけるために
モデル名や品質を後から書き換えることはしません。** 上限が違っても同じ配分になった場合は、
画面上でも「構成が同じ」と明示します。

デザイン（濃紺ヘッダー・青緑 CTA・白パネル・カテゴリ 3 色）は
`.streamlit/config.toml` と `app/workspace_theme.py` にまとめてあります。

## 最適化の処理の流れ（QUBO → Amplify → 結果整形）

「3. 最適化実行」を押してから結果が返るまでの内部処理です。

```
Agent（候補モデル）・Task（タスク） の一覧
        │
        ▼
build_coefficients()                    src/taqumi2026s_teame/qubo/coefficients.py
  タスク×モデルの (N, M) 行列を作る
  q (品質) / r (信頼性) / c, c_norm (コスト) / forbidden (割当禁止セル)
        │
        ▼
solve_amplify() が QUBO を組み立てる      src/taqumi2026s_teame/solvers/amplify_solver.py
  1) VariableGenerator で x[i,j] ∈ {0,1} を生成
  2) forbidden なセルは C2 として x[i,j] = 0 に固定
     （能力なし / 機密タスク×社外モデル）
  3) 目的関数を構築（最小化なので符号反転）
       objective = -Σ w_j(α q_ij + β r_ij) x_ij + γ Σ ĉ_ij x_ij
  4) 制約を構築
       C1: one_hot(x[:, j])                 各タスクに必ず1モデル
       C3: less_equal(Σ c_ij x_ij, 予算B)   予算上限（budget 指定時のみ）
  5) Model(objective, constraints) にまとめる
        │
        ▼
Fixstars Amplify AE に投げる（AmplifyAEClient.solve）
  トークン未設定 / SDK 未導入なら、ここに進む前に
  クリーンなメッセージで打ち切る（実際には通信しない）
        │
        ▼
結果を受け取り、割当としてデコード
  x.evaluate(result.best.values) で 0/1 の解を取得し、
  タスク列 j ごとに x[:, j] == 1 のモデル index を読む
  （どのモデルも選ばれない/複数選ばれる = 想定外 → 未割当扱い）
  制約を満たす解が無ければ len(result) == 0 → 「実行可能な編成なし」を返す
        │
        ▼
evaluate_assignment() で整形             src/taqumi2026s_teame/evaluation/metrics.py
  割当 index → タスクID/モデルID の対応表、目的関数値、総コスト、
  feasible / within_budget などをまとめた AssignmentResult を作る
        │
        ▼
(AssignmentResult, メッセージ) を画面へ返す → 「3. 最適化実行」「4. アウトプット」で表示
```

古典ソルバ（`solve_greedy` / `solve_random`）も同じ `build_coefficients()` の行列と同じ目的関数の式を使い、
最後は同じ `evaluate_assignment()` で整形するため、量子/古典の結果をそのまま比較できます。

締切（C4）と負荷分散の重み μ は現状スコープ外です（`SolveOptions.deadline` / `Weights.mu` はフィールドとして
残していますが、目的関数・制約には使っていません）。

## 開発

```bash
uv run pytest            # テスト（Amplify トークン不要）
uv run ruff check . && uv run ruff format --check .
uv run mypy src
uv run jupyter lab       # notebooks/
```

Groq の実 API 通信を確認する場合は、キーを表示せず次のテストだけを実行します。

```bash
RUN_GROQ_LIVE_TESTS=1 uv run pytest tests/test_llm_decompose.py -k groq_api_returns_task_response
```

## 環境変数（`.env`）

| 変数 | 用途 | 必須 |
|---|---|---|
| `FIXSTARS_AMPLIFY_TOKEN` | Amplify AE ソルバ | 量子求解時のみ |
| `GROQ_API_KEY` / `GROQ_BASE_URL` / `GROQ_MODEL` | Groq API（既定: `openai/gpt-oss-120b`）でタスク分解 | 任意 |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL` | OpenAI 互換 API でタスク分解 | 任意（無ければサンプル使用） |
| `GUROBI_SERVER` / `GUROBI_PASSWORD` | Gurobi 比較（未実装・予約） | — |

## 生成 AI 利用の開示

本リポジトリのコードは生成 AI（Claude）支援で作成しています。
AI が生成したコード片は `# ===== AI生成: <内容> ここから / ここまで =====` で囲み、
全体が AI 支援のモジュールは冒頭 docstring に明記しています。
詳細は [`IMPLEMENTATION_AUDIT.md`](IMPLEMENTATION_AUDIT.md) を参照。

## データについて

候補は **31 モデル**（`src/taqumi2026s_teame/data/models.json`）。能力は 8 カテゴリ
（コード / ターミナル / 文書 / OCR / 表 / KIE / 文書QA / 画像生成）に分かれ、
各値の算出方法は **[`data/README.md`](src/taqumi2026s_teame/data/README.md)** にまとめています。

**能力値はすべて公開ベンチマークの実測**（推定では埋めていない。値が無いカテゴリは `null`）:

- コード: [SWE-rebench](https://swe-rebench.com/)（2026-05-15〜07-01、111 問）
- ターミナル: [Terminal-Bench 2.1](https://llm-stats.com/benchmarks/terminal-bench-2.1)（2026-09-08）
- 文書 / OCR / 表 / KIE / 文書QA: [IDP Leaderboard](https://www.idp-leaderboard.org/) v1.5
- 画像生成: [Image Arena](https://artificialanalysis.ai/text-to-image/arena)（2026-09）

- QUBO へ渡すのは、役割ブレンドで合成した品質 `Q_ja` とコスト `C_ja` のみ（能力カラムを増やしても最適化モデルは不変）
- 価格は 2026-09-08 時点の各社公式ページ。ベンチにより世代が異なるため 1 モデルが全カテゴリを持つことは少ない

## 継承依存について

`qiskit*` / `docplex` は本プロジェクトでは未使用です（テンプレートからの継承）。
