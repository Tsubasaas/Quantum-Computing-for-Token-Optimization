"""タスク分解。LLM が使えない場合は必ずサンプルにフォールバックする。"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from importlib import resources

from ..data import load_sample_tasks
from ..data.task_types import ROLES
from ..models import Task

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(levelname)s:%(name)s:%(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

# プロンプト本体は prompt/*.md 側に置く（散文の編集にコード変更を要らなくするため）。
PROMPT_DIR = "prompt"
PROMPT_FILE = "prompt-task-decomposition.md"

# 参照ファイルをプロンプトへ載せるときの上限（トークン浪費と切り詰め事故を防ぐ）
MAX_CONTEXT_CHARS = 8000
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"

NO_REFERENCE = "（参考資料はありません）"

# プロンプトの「種類」（業務分類）→ ROLES（モデル能力の役割）。
# 能力ベンチは 5 カテゴリしか無いので写像は非全単射。QUBO 側はここで決まった役割で
# 担当可能なモデルを絞る（data.task_model_scores）ため、割当結果に直接効く。
TYPE_TO_ROLE: dict[str, str] = {
    "要件": "doc_understand",
    "設計": "doc_understand",
    "フロントエンド": "code_gen",
    "バックエンド": "code_gen",
    "API": "code_gen",
    "データ": "doc_extract",
    "AI": "code_gen",
    "インフラ": "devops",
    "セキュリティ": "code_review",
    "テスト": "test_gen",
    "ドキュメント": "doc_understand",
    "デザイン": "image_gen",
    "その他": "code_gen",
}
DEFAULT_ROLE = "code_gen"

# high/medium/low → 1..5。importance は w_j = priority/5、difficulty は品質補正に効く。
LEVEL_TO_SCORE: dict[str, int] = {"high": 5, "medium": 3, "low": 1}

# large/medium/small → 見積り時間（時間）。相対値なので絶対時間としての精度は求めない。
EFFORT_TO_HOURS: dict[str, float] = {"large": 8.0, "medium": 4.0, "small": 2.0}

# confidentiality=high のみ機密扱い（= 社外 API へ割当不可）。medium は「扱う可能性がある」
# 止まりで、これを機密にすると社内モデルへ寄りすぎて最適化の選択肢が潰れる。
CONFIDENTIAL_LEVELS = frozenset({"high"})


@dataclass(slots=True)
class Decomposition:
    """分解の結果。``used_llm`` が False ならサンプルへのフォールバック。"""

    tasks: list[Task]
    message: str
    used_llm: bool


def load_prompt_template() -> str:
    """タスク分解プロンプトの原文を返す。"""

    # prompt/ は __init__.py を持たない素のデータディレクトリなので、
    # パッケージ名ではなく llm パッケージからの相対で辿る。
    source = resources.files(__package__).joinpath(PROMPT_DIR).joinpath(PROMPT_FILE)
    return source.read_text(encoding="utf-8")


def render_prompt(request: str, context: str | None = None) -> str:
    """テンプレートのプレースホルダを埋めた、そのまま送れるプロンプトを返す。"""

    reference = (context or "").strip()
    reference = reference[:MAX_CONTEXT_CHARS] if reference else NO_REFERENCE
    return (
        load_prompt_template()
        .replace("{{ user_request }}", request)
        .replace("{{ reference }}", reference)
    )


def _role_of(value: object) -> str:
    """``type``（業務分類）を ROLES へ写す。ROLES の値が直接来た場合はそのまま使う。"""

    raw = str(value or "").strip()
    if raw in ROLES:
        return raw
    return TYPE_TO_ROLE.get(raw, DEFAULT_ROLE)


def _score_of(value: object, default: int = 3) -> int:
    """high/medium/low を 1..5 へ。数値が来た場合は 1..5 へ丸める。"""

    raw = str(value or "").strip().lower()
    if raw in LEVEL_TO_SCORE:
        return LEVEL_TO_SCORE[raw]
    try:
        return max(1, min(5, int(round(float(raw)))))
    except ValueError:
        return default


def _hours_of(value: object) -> float:
    """large/medium/small を時間へ。数値が来た場合は時間そのものとして扱う。"""

    raw = str(value or "").strip().lower()
    if raw in EFFORT_TO_HOURS:
        return EFFORT_TO_HOURS[raw]
    try:
        return max(0.5, float(raw))
    except ValueError:
        return 2.0


def _confidential_of(value: object) -> bool:
    raw = str(value or "").strip().lower()
    if raw in {"true", "false"}:
        return raw == "true"
    return raw in CONFIDENTIAL_LEVELS


def _coerce_tasks(raw: object) -> list[Task]:
    if isinstance(raw, dict):
        raw = raw.get("tasks", [])
    if not isinstance(raw, list) or not raw:
        raise ValueError("tasks 配列がありません")
    tasks: list[Task] = []
    seen_ids: set[str] = set()
    for idx, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            continue
        # id は依存関係の参照先であり QUBO 前処理の辞書キーでもある。重複すると
        # タスクが黙って消えるので、採番し直して一意にしておく。
        task_id = str(item.get("id") or "").strip() or f"T{idx:03d}"
        while task_id in seen_ids:
            task_id = f"{task_id}_{idx:03d}"
        seen_ids.add(task_id)
        title = item.get("task_name") or item.get("title") or f"タスク {idx}"
        tasks.append(
            Task(
                id=task_id,
                title=str(title),
                role=_role_of(item.get("type") or item.get("role")),
                difficulty=_score_of(item.get("difficulty")),
                priority=_score_of(item.get("importance") or item.get("priority")),
                est_time=_hours_of(item.get("effort") or item.get("est_time")),
                dependencies=[str(x) for x in item.get("dependencies", []) if x],
                confidential=_confidential_of(
                    item.get("confidentiality") or item.get("confidential")
                ),
            )
        )
    if not tasks:
        raise ValueError("有効なタスクがありません")
    return tasks


def _llm_decompose(request: str, model: str, context: str | None = None) -> list[Task]:
    from openai import OpenAI  # 遅延 import（未インストールでも他機能は動く）

    # Groq は OpenAI 互換エンドポイントなので、クライアントは openai SDK のまま
    # base_url だけ差し替える。GROQ_API_KEY があれば Groq を優先する。
    groq_key = os.getenv("GROQ_API_KEY")
    api_key = groq_key or os.getenv("OPENAI_API_KEY")
    base_url = (
        os.getenv("GROQ_BASE_URL") or GROQ_BASE_URL
        if groq_key
        else os.getenv("OPENAI_BASE_URL") or None
    )
    client = OpenAI(api_key=api_key, base_url=base_url)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": render_prompt(request, context)}],
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    response_content = resp.choices[0].message.content or "{}"
    logger.info("LLM response: %s", response_content)
    return _coerce_tasks(json.loads(response_content))


def decompose_request(
    request: str, *, use_llm: bool = False, context: str | None = None
) -> Decomposition:
    """開発要求をタスクへ分解する。``context`` は参照ファイルの本文（任意）。

    LLM を使えなかった理由は ``message`` に入れ、``used_llm`` で成否を区別できるようにする。
    呼び出し側が「サンプルへのフォールバック」を成功として表示しないための情報。
    """

    request = (request or "").strip()
    fallback = "サンプルタスクを読み込みました。"
    if not use_llm:
        return Decomposition(load_sample_tasks(), f"LLM 未使用: {fallback}", False)
    if not (os.getenv("GROQ_API_KEY") or os.getenv("OPENAI_API_KEY")):
        return Decomposition(
            load_sample_tasks(),
            f"GROQ_API_KEY または OPENAI_API_KEY が未設定です: {fallback}",
            False,
        )
    if not request:
        return Decomposition(
            load_sample_tasks(), f"開発要求が空です: {fallback}", False
        )

    using_groq = bool(os.getenv("GROQ_API_KEY"))
    default_model = DEFAULT_GROQ_MODEL if using_groq else "gpt-4o-mini"
    model = os.getenv("GROQ_MODEL" if using_groq else "OPENAI_MODEL", default_model)
    try:
        tasks = _llm_decompose(request, model, context)
    except (
        Exception
    ) as exc:  # noqa: BLE001 - API/ネットワーク/JSON いずれの失敗も UI へ返す
        return Decomposition(
            load_sample_tasks(),
            f"LLM 分解に失敗（{exc}）: サンプルタスクを使用します。",
            False,
        )
    suffix = "（参照ファイルつき）" if context else ""
    return Decomposition(
        tasks, f"LLM（{model}）で {len(tasks)} 件に分解しました{suffix}。", True
    )


def decompose(request: str, *, use_llm: bool = False) -> tuple[list[Task], str]:
    """``(tasks, message)`` を返す後方互換ラッパー。成否が要る場合は
    :func:`decompose_request` を使う。"""

    result = decompose_request(request, use_llm=use_llm)
    return result.tasks, result.message
