"""要望文と選択カテゴリ（文書 / 開発 / 画像）から、割当対象のタスク一覧を組み立てる。

ワークスペース画面「01 要望 → 02 タスク」の裏側。既存の
:func:`taqumi2026s_teame.llm.decompose_request` をそのまま使い、その結果を
選択カテゴリで絞り込む。LLM が使えない場合はカテゴリ別テンプレートへ落とす。

テンプレートは特定の題材（売上管理・予約管理など）に固定せず、要望文のキーワードで
関連タスクだけを足す。生成物が LLM 由来かテンプレート由来かは
:attr:`PlanningResult.source` で必ず区別できるようにしている。

本モジュールは全体が生成 AI（Claude）支援で作成されています。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from .data.task_types import (
    PLAN_CATEGORIES,
    PLAN_CATEGORY_LABELS,
    plan_category_of,
)
from .llm import decompose_request
from .models import Task

__all__ = [
    "PlanningResult",
    "plan_tasks",
    "renumber",
    "prune_dependencies",
    "filter_by_categories",
]

PlanningSource = Literal["llm", "template"]

# 難易度は 1（軽量）/ 3（標準）/ 5（複雑）の 3 段階だけを使う（data.task_types と対応）。
_LIGHT, _NORMAL, _HEAVY = 1, 3, 5


@dataclass(slots=True)
class PlanningResult:
    """タスク分解の結果。

    Attributes:
        tasks (list[Task]): 生成したタスク一覧（ID は T001 から連番）。
        source (PlanningSource): "llm"（LLM が実際に分解した）| "template"（テンプレート）。
        message (str): 画面に出す説明文。LLM を使えなかった理由もここに入る。
    """

    tasks: list[Task]
    source: PlanningSource
    message: str

    @property
    def used_llm(self) -> bool:
        return self.source == "llm"


# --------------------------------------------------------------------------- #
# テンプレート
# --------------------------------------------------------------------------- #
# (key, タイトル, role, 難易度, 依存 key, 成果物, 個数)
_TemplateRow = tuple[str, str, str, int, tuple[str, ...], str, int]

_DOC_BASE: list[_TemplateRow] = [
    ("brief", "要件・構成を整理する", "doc_understand", _NORMAL, (), "要件メモ", 1),
    ("proposal", "提案書を作成する", "doc_understand", _NORMAL, ("brief",), "提案書", 1),
    (
        "guide",
        "利用手順・説明文を整える",
        "doc_understand",
        _LIGHT,
        ("proposal",),
        "利用ガイド",
        1,
    ),
]

_CODE_BASE: list[_TemplateRow] = [
    ("design", "データ構造と API を設計する", "code_gen", _HEAVY, ("brief",), "設計書", 1),
    ("backend", "主要な処理を実装する", "code_gen", _HEAVY, ("design",), "サーバ実装", 1),
    ("ui", "画面・表示を実装する", "code_gen", _NORMAL, ("design",), "画面実装", 1),
    ("test", "テスト・結合確認", "test_gen", _HEAVY, ("backend", "ui"), "テスト一式", 1),
]

_IMAGE_BASE: list[_TemplateRow] = [
    (
        "visual",
        "紹介用キービジュアルを生成",
        "image_gen",
        _NORMAL,
        ("brief",),
        "キービジュアル",
        1,
    ),
    ("banner", "告知用バナーを生成", "image_gen", _LIGHT, ("proposal",), "バナー", 2),
]

# 要望文のキーワードで足す追加タスク。カテゴリ -> [(正規表現, 行)]
_EXTRA: dict[str, list[tuple[str, _TemplateRow]]] = {
    "doc": [
        (
            r"OCR|PDF|帳票|スキャン|読み取り|請求書|領収書",
            (
                "extract",
                "帳票・PDF から情報を抽出する",
                "doc_extract",
                _HEAVY,
                ("brief",),
                "抽出結果",
                1,
            ),
        ),
        (
            r"マニュアル|運用|手順書|引き継ぎ",
            (
                "runbook",
                "運用手順書をまとめる",
                "doc_understand",
                _NORMAL,
                ("proposal",),
                "運用手順書",
                1,
            ),
        ),
    ],
    "code": [
        (
            r"CSV|エクスポート|出力|ダウンロード|レポート出力",
            ("csv", "CSV 出力を実装する", "code_gen", _LIGHT, ("backend",), "CSV 出力", 1),
        ),
        (
            r"認証|ログイン|ユーザー管理|権限|アカウント|個人情報|パスワード",
            ("auth", "認証・権限を実装する", "code_gen", _NORMAL, ("design",), "認証機能", 1),
        ),
        (
            r"デプロイ|インフラ|CI|CD|Docker|Kubernetes|自動化|運用基盤",
            ("devops", "デプロイ・CI を整える", "devops", _NORMAL, ("backend",), "CI/CD 設定", 1),
        ),
        (
            r"ダッシュボード|集計|グラフ|可視化|分析画面",
            (
                "dashboard",
                "集計・ダッシュボードを実装する",
                "code_gen",
                _NORMAL,
                ("backend",),
                "ダッシュボード",
                1,
            ),
        ),
    ],
    "image": [
        (
            r"ロゴ|アイコン|ブランド",
            ("logo", "ロゴ・アイコン案を生成", "image_gen", _NORMAL, (), "ロゴ案", 2),
        ),
        (
            r"SNS|告知|広告|キャンペーン|宣伝",
            ("promo", "SNS 用の告知画像を生成", "image_gen", _LIGHT, ("visual",), "告知画像", 3),
        ),
    ],
}

# 認証・個人情報まわりのタスクは機密扱い（= 社外 API へ割当不可）にする。
_CONFIDENTIAL_KEYS = frozenset({"auth"})


def _template_rows(request: str, categories: list[str]) -> list[_TemplateRow]:
    base = {"doc": _DOC_BASE, "code": _CODE_BASE, "image": _IMAGE_BASE}
    rows: list[_TemplateRow] = []
    for category in PLAN_CATEGORIES:
        if category not in categories:
            continue
        rows.extend(base[category])
        for pattern, row in _EXTRA.get(category, []):
            if re.search(pattern, request, re.IGNORECASE):
                rows.append(row)
    return rows


def _est_time(difficulty: int) -> float:
    return {1: 2.0, 3: 4.0, 5: 8.0}.get(difficulty, 4.0)


def _tasks_from_template(request: str, categories: list[str]) -> list[Task]:
    rows = _template_rows(request, categories)
    keys = {row[0] for row in rows}
    key_to_id = {row[0]: f"T{i:03d}" for i, row in enumerate(rows, start=1)}
    tasks: list[Task] = []
    for key, title, role, difficulty, deps, deliverable, quantity in rows:
        tasks.append(
            Task(
                id=key_to_id[key],
                title=title,
                role=role,
                difficulty=difficulty,
                # 重要度は QUBO の w_j。テンプレートでは中央値を置き、画面には
                # 「一律で高優先度」という列を作らない（利用者は難易度と前提だけを見る）。
                priority=3,
                est_time=_est_time(difficulty),
                # 選ばれなかったカテゴリの前提は、ここで最初から作らない。
                dependencies=[key_to_id[d] for d in deps if d in keys],
                confidential=key in _CONFIDENTIAL_KEYS,
                quantity=quantity,
                deliverable=deliverable,
            )
        )
    return tasks


# --------------------------------------------------------------------------- #
# 共通ユーティリティ
# --------------------------------------------------------------------------- #
def filter_by_categories(tasks: list[Task], categories: list[str]) -> list[Task]:
    """選択カテゴリに属するタスクだけを残す。"""

    allowed = set(categories)
    return [t for t in tasks if plan_category_of(t.role) in allowed]


def prune_dependencies(tasks: list[Task]) -> list[Task]:
    """存在しない ID・自己参照・循環を依存関係から取り除く。

    循環は「先に並んでいるタスクへの依存だけ残す」という規則で断ち切る。タスクを
    消さずに DAG 化できるので、カテゴリを外した結果として前提が宙に浮くケース
    （仕様 §5）をそのまま扱える。
    """

    order = {t.id: i for i, t in enumerate(tasks)}
    for task in tasks:
        task.dependencies = [
            dep
            for dep in dict.fromkeys(task.dependencies)
            if dep in order and dep != task.id and order[dep] < order[task.id]
        ]
    return tasks


def renumber(tasks: list[Task]) -> list[Task]:
    """ID を T001 から振り直し、依存関係の参照も付け替える。"""

    mapping = {t.id: f"T{i:03d}" for i, t in enumerate(tasks, start=1)}
    for task in tasks:
        task.dependencies = [mapping[d] for d in task.dependencies if d in mapping]
        task.id = mapping[task.id]
    return tasks


def _normalize(tasks: list[Task]) -> list[Task]:
    ordered = sorted(tasks, key=lambda t: PLAN_CATEGORIES.index(plan_category_of(t.role)))
    return renumber(prune_dependencies(ordered))


def _category_hint(categories: list[str]) -> str:
    labels = "・".join(PLAN_CATEGORY_LABELS[c] for c in PLAN_CATEGORIES if c in categories)
    return f"\n\n必要な成果物の種類: {labels}。この種類に含まれる作業だけをタスクにしてください。"


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def plan_tasks(
    request: str,
    categories: list[str],
    *,
    use_llm: bool = False,
    context: str | None = None,
) -> PlanningResult:
    """要望文と選択カテゴリからタスク一覧を作る。

    Args:
        request (str): 利用者が書いた要望文。
        categories (list[str]): "doc" / "code" / "image" のうち選択されたもの。
        use_llm (bool): LLM でタスク分解を試みるか。
        context (str | None): 参照ファイルの本文（任意）。

    Returns:
        PlanningResult: タスク一覧と、LLM を使えたかどうか。

    Raises:
        ValueError: 要望が空、またはカテゴリが 1 つも選ばれていない場合。
    """

    request = (request or "").strip()
    if not request:
        raise ValueError("要望を入力してください。")
    selected = [c for c in PLAN_CATEGORIES if c in set(categories)]
    if not selected:
        raise ValueError("タスクの種類を1つ以上選択してください。")

    if not use_llm:
        return PlanningResult(
            _normalize(_tasks_from_template(request, selected)),
            "template",
            "テンプレートと要望文のキーワードからタスクを構成しました（LLM 未使用）。",
        )

    decomposition = decompose_request(
        request + _category_hint(selected), use_llm=True, context=context
    )
    if not decomposition.used_llm:
        # LLM を使えなかったときは、サンプルタスクではなくテンプレートへ落とす。
        # サンプル（予約管理アプリ）は要望と無関係になり、成功と誤解されるため。
        return PlanningResult(
            _normalize(_tasks_from_template(request, selected)),
            "template",
            f"LLM は使われていません（{decomposition.message}）。"
            "テンプレートからタスクを構成しました。",
        )

    tasks = filter_by_categories(decomposition.tasks, selected)
    covered = {plan_category_of(t.role) for t in tasks}
    missing = [c for c in selected if c not in covered]
    if missing:
        # LLM が触れなかったカテゴリだけテンプレートで補う。補ったことは message に出す。
        tasks = tasks + _tasks_from_template(request, missing)
    for task in tasks:
        if not task.deliverable:
            task.deliverable = "成果物"
        task.quantity = max(1, int(task.quantity))

    note = ""
    if missing:
        labels = "・".join(PLAN_CATEGORY_LABELS[c] for c in missing)
        note = f" {labels} はテンプレートで補いました。"
    return PlanningResult(_normalize(tasks), "llm", decomposition.message + note)
