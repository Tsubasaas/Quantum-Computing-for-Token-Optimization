---
description: "Use when selecting files/logs for AI context, preparing patches, or sharing snippets. Enforces content exclusion for secrets, generated artifacts, caches, and irrelevant files."
name: "Content Exclusion Rules"
---

# Content Exclusion Rules

この指示は、AI へ渡すコンテキストと編集対象を最小化するためのルールです。

## 1) 絶対に含めない内容

- 秘密情報: `.env`, API キー, トークン, パスワード, 認証ヘッダ, 秘密鍵。
- バイナリ/キャッシュ: `**/__pycache__/**`, `*.pyc`, `.mypy_cache/**`, `.pytest_cache/**`, `.ruff_cache/**`, `.ipynb_checkpoints/**`。
- 実行生成物: `outputs/**`, `artifacts/**`, `logs/**`, `htmlcov/**`, `.coverage*`。
- ローカル環境依存: `.venv/**`, `venv/**`, `.vscode/**`, `.DS_Store`。

## 2) 通常は編集しない内容

- 依存ロック: `uv.lock`（依存更新タスクで明示要求がある場合のみ）。
- 生成データ: `src/taqumi2026s_teame/data/models.json`（更新は `scripts/build_models.py` 経由のみ）。
- 監査台帳: `IMPLEMENTATION_AUDIT.md`（監査更新が依頼された場合のみ）。

## 3) コンテキスト選定の優先順

- 優先: `src/**`, `app/**`, `tests/**`, `pyproject.toml`, `README.md`。
- 低優先: 長大ログ、スクリーンショット、ノートブック出力。
- ログを共有する場合は、必要な前後数行に切り詰め、機密値は `***` でマスクする。

## 4) このリポジトリ固有の注意

- Streamlit のページ名（例: `app/pages/1_タスク設定.py`）は動線に直結するため、除外ではなく保全対象として扱う。
- LLM/Amplify の未設定は正常系として扱えるため、`.env` の中身を見せる代わりに「未設定」である事実だけを共有する。

## 参考ドキュメント

- [README.md](README.md)
- [IMPLEMENTATION_AUDIT.md](IMPLEMENTATION_AUDIT.md)
- [src/taqumi2026s_teame/data/README.md](src/taqumi2026s_teame/data/README.md)
