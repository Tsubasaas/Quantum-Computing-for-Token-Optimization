"""タスクの役割と、それが参照するモデル能力カテゴリの対応。

能力カテゴリ（models.json の capability キー）と出典:
  repo_bug_fix     : SWE-bench Verified（未掲載は SWE-rebench）
  terminal         : Terminal-Bench 2.1
  document         : IDP Leaderboard（Overall）
  ocr              : IDP Leaderboard（OlmOCR）
  image_generation : Image Arena
"""

from __future__ import annotations

CATEGORIES: list[str] = [
    "repo_bug_fix",
    "terminal",
    "document",
    "ocr",
    "image_generation",
]

# 役割 -> (日本語ラベル, 能力カテゴリ, 役割係数)
_ROLES: dict[str, tuple[str, str, float]] = {
    "code_gen": ("コード生成", "repo_bug_fix", 1.00),
    "code_fix": ("リポジトリのバグ修正", "repo_bug_fix", 1.00),
    "code_review": ("コードレビュー", "repo_bug_fix", 0.93),
    "test_gen": ("テスト生成", "repo_bug_fix", 0.95),
    "terminal_ops": ("ターミナル操作・自動化", "terminal", 1.00),
    "devops": ("DevOps・CI/CD", "terminal", 0.95),
    "doc_understand": ("文書・PDF の理解", "document", 1.00),
    "doc_extract": ("文書からの情報抽出（表・項目）", "document", 0.95),
    "ocr": ("OCR・文字起こし", "ocr", 1.00),
    "image_gen": ("画像生成", "image_generation", 1.00),
}

ROLES: list[str] = list(_ROLES)
ROLE_LABELS: dict[str, str] = {k: v[0] for k, v in _ROLES.items()}
ROLE_CATEGORY: dict[str, str] = {k: v[1] for k, v in _ROLES.items()}
ROLE_FACTOR: dict[str, float] = {k: v[2] for k, v in _ROLES.items()}

CATEGORY_LABELS: dict[str, str] = {
    "repo_bug_fix": "コード / バグ修正",
    "terminal": "ターミナル / DevOps",
    "document": "文書理解・抽出",
    "ocr": "OCR",
    "image_generation": "画像生成",
}

# 役割ごとに Q_ja を合成する能力ブレンド {capability: weight}。
# QUBO へは合成後の Q_ja / C_ja だけを渡す（能力カラムを増やしても QUBO の式は不変）。
# 主能力（重み最大）が null のモデルはそのタスク担当不可。
ROLE_BLEND: dict[str, dict[str, float]] = {
    "code_gen": {"repo_bug_fix": 1.0},
    "code_fix": {"repo_bug_fix": 0.8, "terminal": 0.2},
    "code_review": {"repo_bug_fix": 1.0},
    "test_gen": {"repo_bug_fix": 0.85, "terminal": 0.15},
    "terminal_ops": {"terminal": 1.0},
    "devops": {"terminal": 0.85, "repo_bug_fix": 0.15},
    "doc_understand": {"document": 1.0},
    "doc_extract": {"document": 0.6, "ocr": 0.4},
    "ocr": {"ocr": 0.7, "document": 0.3},
    "image_gen": {"image_generation": 1.0},
}

ROLE_MIN_QUALITY: dict[str, float] = dict.fromkeys(_ROLES, 0.35)

ROLES_BY_CATEGORY: dict[str, list[str]] = {
    cat: [r for r in ROLES if ROLE_CATEGORY[r] == cat] for cat in CATEGORIES
}


def label(role: str) -> str:
    return ROLE_LABELS.get(role, role)


def category_of(role: str) -> str:
    return ROLE_CATEGORY.get(role, "repo_bug_fix")


def blend_of(role: str) -> dict[str, float]:
    return ROLE_BLEND.get(role, {ROLE_CATEGORY.get(role, "repo_bug_fix"): 1.0})


def primary_capability(role: str) -> str:
    return max(blend_of(role).items(), key=lambda kv: kv[1])[0]


# --------------------------------------------------------------------------- #
# 画面カテゴリ（doc / code / image）
#
# ワークスペース画面（app/app_pages/workspace.py）がユーザーへ見せる粒度。
# ROLES はモデル能力ベンチのカテゴリ由来で 10 種類あるが、利用者が選ぶのは
# 「文書作成 / 開発・プログラミング / 画像生成」の 3 つだけにする。
# QUBO へ渡るのは従来どおり ROLES なので、最適化の式はこの写像に影響されない。
# --------------------------------------------------------------------------- #

PLAN_CATEGORIES: list[str] = ["doc", "code", "image"]

PLAN_CATEGORY_LABELS: dict[str, str] = {
    "doc": "文書作成",
    "code": "開発・プログラミング",
    "image": "画像生成",
}

PLAN_CATEGORY_HINTS: dict[str, str] = {
    "doc": "要件定義・提案書・ガイド",
    "code": "設計・コード・テスト",
    "image": "キービジュアル・バナー",
}

# 役割 -> 画面カテゴリ。ROLES を過不足なく覆う（ROLE_PLAN_CATEGORY のテストで検証）。
ROLE_PLAN_CATEGORY: dict[str, str] = {
    "code_gen": "code",
    "code_fix": "code",
    "code_review": "code",
    "test_gen": "code",
    "terminal_ops": "code",
    "devops": "code",
    "doc_understand": "doc",
    "doc_extract": "doc",
    "ocr": "doc",
    "image_gen": "image",
}

PLAN_CATEGORY_ROLES: dict[str, list[str]] = {
    cat: [r for r in ROLES if ROLE_PLAN_CATEGORY.get(r) == cat] for cat in PLAN_CATEGORIES
}

# 難易度（1..5）と画面表示の 3 段階の対応。画面から書き戻すときはこの値を使う。
DIFFICULTY_LABELS: dict[int, str] = {1: "軽量", 3: "標準", 5: "複雑"}
DIFFICULTY_VALUES: dict[str, int] = {v: k for k, v in DIFFICULTY_LABELS.items()}


def plan_category_of(role: str) -> str:
    """役割を画面カテゴリ（doc/code/image）へ写す。未知の役割は code 扱い。"""

    return ROLE_PLAN_CATEGORY.get(role, "code")


def difficulty_label(difficulty: int) -> str:
    """1..5 の難易度を「軽量 / 標準 / 複雑」へ丸める（2→軽量, 4→複雑）。"""

    if difficulty <= 2:
        return "軽量"
    if difficulty >= 5:
        return "複雑"
    return "標準"
