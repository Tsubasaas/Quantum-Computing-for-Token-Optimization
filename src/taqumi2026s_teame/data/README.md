# モデル能力データ（`models.json`）の算出方法

`models.json` は **`scripts/build_models.py` から生成**（再現可能なデータビルド）。
出典テーブルはすべてスクリプト内にコメントつきで記載。

## 方針（推測を入れない）

- 能力カテゴリごとに**出典ベンチマークを 1 つに固定**し、生値をそのまま使う（画像のみ Elo を正規化）
- モデルは各ベンチの表記名で識別。複数ベンチに**同名で載る場合のみ 1 候補に統合**
  （例: SWE-rebench=「Claude Sonnet 5」／ IDP=「Claude Sonnet 4.6」→ 別モデルとして扱う）
- 値が取れないカテゴリは `null`（= そのタスク担当不可）。推測で埋めない
- 価格は各社公式ページの実測。無ければ `null`

## 1. 能力スコア `capability`（0–1）

| カテゴリ | 出典 | 正規化 | 収録 |
|---|---|---|---|
| `repo_bug_fix` | [SWE-bench Verified](https://www.swebench.com/) % resolved | そのまま | benchlm.ai 集計 2026-09-04（約 40 モデル） |
| ↑ 未掲載分 | [SWE-rebench](https://swe-rebench.com/) Resolved Rate | そのまま | 2026-05-15〜07-01 window（14 モデル） |
| `terminal` | [Terminal-Bench 2.1](https://llm-stats.com/benchmarks/terminal-bench-2.1) Accuracy | そのまま | llm-stats 2026-09-08（35 モデル） |
| `document` | [IDP Leaderboard](https://www.idp-leaderboard.org/) v1.5 Overall | `/ 100` | 26 モデル |
| `ocr` | IDP Leaderboard v1.5 OlmOCR | `/ 100` | 26 モデル |
| `image_generation` | [Image Arena](https://artificialanalysis.ai/text-to-image/arena) Elo | `clip((elo − 850) / 330, 0, 1)` | 2026-09（22 モデル） |

- `benchmark_scores` に生値（`swe_bench_verified` / `idp_overall` / `image_arena_elo` …）を保持。
- `benchmark_metadata.<category>` に `source` / `date` / `verified` を保持。

## 2. 品質合成 `Q_ja`（`synthesize_quality`）

役割ブレンド（`task_types.ROLE_BLEND`）で 1 値にまとめる:

```
Q_ja = ( Σ_k blend[k] · capability_a[k] ) · role_factor[j]
```

- 例: `code_fix` = `0.8·repo_bug_fix + 0.2·terminal`、`doc_extract` = `0.6·document + 0.4·ocr`
- `role_factor`: 生成 1.00 / レビュー・抽出 0.93–0.95
- **主能力（重み最大）が `null` のモデルはそのタスク担当不可**。副能力が `null` なら 0 として合成。
- 難易度補正 `× (1 − 0.12·(difficulty − 1))` は QUBO 前処理側で適用。

## 3. コスト `C_ja`（`cost_for`）

1. `pricing.benchmark_cost_per_task`（SWE-rebench Cost per Problem・**実測**）— 最優先
2. 画像モデルは `pricing.per_image`
3. 公式 API 単価から見積り: `(input_per_1m · 60k + output_per_1m · 8k) / 1e6`
4. どれも無い（open-weight で公式単価なし等）→ `$0.20` フォールバック

いずれも難易度補正 `× (1 + 0.12·(difficulty − 3))`。

## 4. 信頼性 `reliability`

`benchmark_scores.swe_rebench_pass_at_5`（Pass@5）があればそれ、無ければ `Q + 0.10`。

## 5. 処理時間

`SWE-rebench Tokens per Problem / 30000 × (0.6 + 0.13·difficulty)`（相対値）。
SWE-rebench 未掲載のモデルは実測がないため既定 60 秒（`latency.note` に明記）。wall-clock 実測ではない。

## 6. 社外 / 社内

`external = external_api AND NOT local_available`。機密タスクは社内モデル（open-weight や自社ホスト）のみ割当可。

## 7. 価格の出典（2026-09-08 時点、各社公式ページ）

| 提供 | ソース |
|---|---|
| Anthropic | platform.claude.com/docs/en/about-claude/pricing |
| OpenAI | developers.openai.com/api/docs/pricing |
| Google | ai.google.dev/gemini-api/docs/pricing |
| xAI | docs.x.ai/docs/models |

open-weight モデル（DeepSeek / Qwen / GLM / Llama / Mistral 系）は公式 API 単価が無いため
`pricing = null`（コストは SWE-rebench 実測があればそれ、無ければフォールバック）。

## 8. データの更新

`scripts/build_models.py` の出典テーブルを新しいリーダーボードの値に差し替えて
`uv run python scripts/build_models.py` を実行するだけ。QUBO 側は変更不要。

## 9. 使えるモデルの選別（model_pool.py）

`models.json` はベンチ照合のため旧バージョンや一般提供のないモデルも載せている。
「最適でも呼べないモデルが編成に入ったら意味がない」ため、`model_pool.py` で
**除外理由つき**に絞る（`SUPERSEDED` = 旧バージョン、`BENCHMARK_ONLY` = ベンチ掲載のみ）。

- `load_agents(only_usable=True)` で選別後（現状 115 → 76）。既定 `only_usable=False` は全件。
- ワークスペースの「予算とモデル選定」は選別後プールから候補を選ぶ。旧 4 画面は全件のまま。
- 新しいモデル版が出たら `SUPERSEDED` に 1 行足す（`"旧id": "新id"`）。判断は
  `model_family` / `model_version` を見て、規模帯（mini/flash/27B 等）の違いは版落ち扱いにしない。
