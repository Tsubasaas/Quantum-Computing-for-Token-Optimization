"""Streamlit ページ共通のヘルパー（DataFrame 変換・グラフ・説明文）。"""

from __future__ import annotations

import os
import re
from collections.abc import Collection
from typing import Any

import _boot  # noqa: F401  (sys.path 調整)
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

try:  # 日本語フォント（任意）
    import matplotlib_fontja  # noqa: F401
except Exception:  # noqa: BLE001
    pass

import streamlit as st

from taqumi2026s_teame.data import (
    category_source,
    cost_for,
    load_models,
    source_index,
)
from taqumi2026s_teame.data.task_types import (
    CATEGORIES,
    ROLE_CATEGORY,
    ROLE_LABELS,
    ROLES,
    label,
)
from taqumi2026s_teame.models import Agent, AssignmentResult, Task
from taqumi2026s_teame.qubo.coefficients import Coefficients

ROLE_OPTIONS = list(ROLES)
_FALLBACK_ROLE = "code_gen"

# 最適化方針の内部値マッピング（要件定義書 7.3）
OPTIMIZATION_MODE_MAP: dict[str, str] = {
    "コスト優先": "cost_first",
    "バランス": "balanced",
    "精度優先": "accuracy_first",
}

# 逆引きマップ
OPTIMIZATION_MODE_REVERSE_MAP: dict[str, str] = {v: k for k, v in OPTIMIZATION_MODE_MAP.items()}

# 内部値 -> config.MODE_WEIGHTS のキー（＝画面2の「編成モード」）
INTERNAL_MODE_TO_LEGACY_MODE: dict[str, str] = {
    "cost_first": "コスト優先",
    "balanced": "バランス",
    "accuracy_first": "精度優先",
}

ALLOWED_FILE_EXTENSIONS = {
    ".txt",
    ".md",
    ".json",
    ".csv",
    ".pdf",
    ".py",
    ".yaml",
    ".yml",
}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10MB

# このうち本文をテキストとして取り出せる形式。.pdf は抽出ライブラリを入れていないため対象外。
TEXT_FILE_EXTENSIONS = {".txt", ".md", ".json", ".csv", ".py", ".yaml", ".yml"}

# 能力カテゴリごとの淡い塗り色（ライト/ダーク両テーマで黒文字が読める）
_CATEGORY_FILL: dict[str, str] = {
    "repo_bug_fix": "#8FD4A8",
    "terminal": "#8EC5F0",
    "document": "#B4A0E8",
    "ocr": "#F5B860",
    "image_generation": "#EF95AC",
}


def role_fill(role: str) -> str:
    return _CATEGORY_FILL.get(ROLE_CATEGORY.get(role, "repo_bug_fix"), "#EEF1F4")


# エージェントごとの識別色
AGENT_COLORS: list[str] = [
    "#2E45D9",
    "#1E7A5B",
    "#B5761A",
    "#8E44AD",
    "#0E7C86",
    "#C0392B",
    "#5D6D7E",
    "#7D6608",
]


def nav_link(path: str, text: str, icon: str) -> None:
    """次ページへのリンク。マルチページ未登録の環境（AppTest など）では文字にフォールバック。"""

    try:
        st.page_link(path, label=text, icon=icon)
    except Exception:  # noqa: BLE001
        st.caption(f"{icon} {text}")


def role_option_label(role: str) -> str:
    """種類の表示名。表の横幅を食わないよう日本語ラベルのみ（値は重複しない）。"""

    return ROLE_LABELS.get(role, role)


ROLE_OPTION_LABELS = [role_option_label(r) for r in ROLE_OPTIONS]
_ROLE_BY_OPTION_LABEL = {role_option_label(r): r for r in ROLE_OPTIONS}


def role_from_option(value: object) -> str:
    """:data:`ROLE_OPTION_LABELS` の表示名を役割 ID へ戻す。未知の値は既定役割。"""

    text = str(value or "").strip()
    if text in _ROLE_BY_OPTION_LABEL:
        return _ROLE_BY_OPTION_LABEL[text]
    return text if text in ROLES else _FALLBACK_ROLE


# --------------------------------------------------------------------------- #
# フラッシュメッセージ
#
# st.success(...) の直後に st.rerun() を呼ぶと、その再実行で描画済みの要素は破棄され
# メッセージが一度も表示されない。session_state に積んで再実行後の先頭で描画する。
# --------------------------------------------------------------------------- #
_FLASH_KEY = "_flash_messages"


def push_flash(level: str, text: str) -> None:
    """``level`` は success / warning / error / info。"""

    st.session_state.setdefault(_FLASH_KEY, []).append((level, text))


def render_flash() -> None:
    for level, text in st.session_state.pop(_FLASH_KEY, []):
        getattr(st, level, st.info)(text)


# --------------------------------------------------------------------------- #
# LLM / 参照ファイル
# --------------------------------------------------------------------------- #
def llm_available() -> bool:
    """LLM API を利用できる設定かどうかを返す。"""

    return bool(os.getenv("GROQ_API_KEY") or os.getenv("OPENAI_API_KEY"))


def read_reference_text(uploaded_file: Any, limit: int = 8000) -> tuple[str | None, str | None]:
    """参照ファイルの本文を返す。``(本文, 注意メッセージ)``。

    本文を取り出せない形式・サイズでは ``(None, 理由)`` を返す。help に書いた
    「タスク生成時に参照する」を実際に果たすための読み取り口。
    """

    if uploaded_file is None:
        return None, None
    name = getattr(uploaded_file, "name", "")
    size = getattr(uploaded_file, "size", 0) or 0
    if size > MAX_FILE_SIZE_BYTES:
        return None, f"「{name}」は 10MB を超えているため読み込みません。"
    ext = os.path.splitext(name)[1].lower()
    if ext not in TEXT_FILE_EXTENSIONS:
        return (
            None,
            f"{ext or 'この形式'} は本文抽出に未対応です。ファイル名のみ記録します。",
        )
    try:
        raw = uploaded_file.getvalue()
    except Exception:  # noqa: BLE001
        return None, f"「{name}」を読み込めませんでした。ファイル名のみ記録します。"
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return None, f"「{name}」の中身が空でした。"
    if len(text) > limit:
        return text[:limit], f"「{name}」が長いため先頭 {limit:,} 文字だけを渡します。"
    return text, None


# --------------------------------------------------------------------------- #
# タスク  <->  DataFrame & tasks_dict（要件定義書 7. Output 仕様）
# --------------------------------------------------------------------------- #
# 要件定義書 7.1 が定める必須 7 カラム。外部仕様なので増やさない。
REQUIRED_TASK_COLUMNS = [
    "task_id",
    "task_name",
    "task_type",
    "importance",
    "workload",
    "is_confidential",
    "reference_file_name",
]

# 拡張カラム。LLM 分解が返す難易度と依存関係を捨てないために保持する。
# difficulty は QUBO の品質補正、dependencies は編成図の矢印で実際に使われる。
OPTIONAL_TASK_COLUMNS = ["difficulty", "dependencies"]

TASK_COLUMN_LABELS: dict[str, str] = {
    "task_id": "タスクID",
    "task_name": "タスク名",
    "task_type": "種類",
    "importance": "重要度",
    "difficulty": "難易度",
    "workload": "作業量",
    "is_confidential": "機密性",
    "dependencies": "依存タスク",
    "reference_file_name": "参照ファイル",
}
TASK_COLUMN_ORDER = list(TASK_COLUMN_LABELS)


# タスクIDの正準形は 3 桁ゼロ詰め（T001, T002...）。サンプルや LLM が
# 2 桁（T01）で返しても、tasks_dict へ入る時点でこの形へ揃える。
TASK_ID_DIGITS = 3
_TASK_ID_RE = re.compile(r"^[Tt](\d+)$")


def normalize_task_id(raw: object) -> str:
    """``T01`` / ``T1`` などを正準形 ``T001`` へ揃える。``T`` + 数字以外はそのまま返す。"""

    text = str(raw or "").strip()
    matched = _TASK_ID_RE.match(text)
    if matched:
        return f"T{int(matched.group(1)):0{TASK_ID_DIGITS}d}"
    return text


def generate_next_task_id(tasks_dict: dict[str, dict[str, object]]) -> str:
    """未使用のタスクID（T001, T002...）を採番する。"""
    max_num = 0
    for k in tasks_dict:
        # T01, T001, etc.
        digits = "".join(c for c in k if c.isdigit())
        if digits:
            try:
                num = int(digits)
                if num > max_num:
                    max_num = num
            except ValueError:
                pass
    return f"T{max_num + 1:0{TASK_ID_DIGITS}d}"


def model_tasks_to_tasks_dict(tasks: list[Task]) -> dict[str, dict[str, object]]:
    """既存の Task リストから要件定義書の tasks_dict 形式へ変換する。

    ID は正準形へ揃え、衝突・空の場合は採番し直す。ID が変わったぶんは
    ``dependencies`` も新 ID へ張り替える（放置すると依存の矢印が迷子になる）。
    """
    result: dict[str, dict[str, object]] = {}
    id_map: dict[str, str] = {}
    for idx, t in enumerate(tasks, start=1):
        raw_id = str(t.id or f"T{idx:0{TASK_ID_DIGITS}d}")
        task_id = normalize_task_id(raw_id)
        if not task_id or task_id in result:
            task_id = generate_next_task_id(result)
        id_map.setdefault(raw_id, task_id)
        result[task_id] = {
            "task_id": task_id,
            "task_name": t.title,
            "task_type": t.role,
            "importance": int(t.priority),
            "difficulty": int(t.difficulty),
            "workload": float(t.est_time),
            "is_confidential": bool(t.confidential),
            "dependencies": list(t.dependencies),
            "reference_file_name": None,
        }
    for item in result.values():
        deps = item["dependencies"]
        item["dependencies"] = [
            id_map.get(str(d), normalize_task_id(d))
            for d in deps  # type: ignore[union-attr]
        ]
    return result


def tasks_dict_to_model_tasks(tasks_dict: dict[str, dict[str, object]]) -> list[Task]:
    """tasks_dict から既存の Task リストへ変換する（最適化ソルバとの互換性レイヤー）。"""
    tasks: list[Task] = []
    for tid, item in tasks_dict.items():
        role = str(item.get("task_type", _FALLBACK_ROLE))
        if role not in ROLES:
            role = _FALLBACK_ROLE
        tasks.append(
            Task(
                id=str(item.get("task_id", tid)),
                title=str(item.get("task_name", "")),
                role=role,
                difficulty=_clamp(item.get("difficulty", 3)),
                priority=_clamp(item.get("importance", 3)),
                est_time=max(0.1, _to_float(item.get("workload"), 2.0) or 2.0),
                dependencies=[str(d) for d in (item.get("dependencies") or [])],  # type: ignore[union-attr]
                confidential=bool(item.get("is_confidential", False)),
            )
        )
    return tasks


def tasks_dict_to_df(tasks_dict: dict[str, dict[str, object]]) -> pd.DataFrame:
    """tasks_dict を正本として DataFrame に変換する（要件 7.1）。

    必須 7 カラムは値が無くても必ず列として存在させ、拡張カラムは持っていれば残す。
    """
    if not tasks_dict:
        return pd.DataFrame(columns=REQUIRED_TASK_COLUMNS)
    df = pd.DataFrame(list(tasks_dict.values()))
    for col in REQUIRED_TASK_COLUMNS:
        if col not in df.columns:
            df[col] = None
    ordered = [c for c in TASK_COLUMN_ORDER if c in df.columns]
    return df[ordered + [c for c in df.columns if c not in ordered]]


def parse_dependencies(value: object) -> list[str]:
    """依存タスクのセル値を ID のリストにする。

    MultiselectColumn はリストを返すが、旧形式のカンマ区切り文字列や、
    新規行の None / NaN も受け取れるようにしておく。
    """
    if value is None or isinstance(value, float):
        return []
    if isinstance(value, str):
        return [d.strip() for d in value.replace("、", ",").split(",") if d.strip()]
    try:
        items = list(value)  # type: ignore[call-overload]
    except TypeError:
        return []
    return [str(d).strip() for d in items if str(d).strip()]


def task_editor_df(tasks_dict: dict[str, dict[str, object]]) -> pd.DataFrame:
    """st.data_editor に渡す表示用 DataFrame（日本語列名）。

    依存タスクは MultiselectColumn 用に ID のリストで持つ。選択肢に無いもの
    （削除済みタスク・自分自身）は表に出さない。
    """
    rows = []
    for tid, item in tasks_dict.items():
        task_id = str(item.get("task_id", tid))
        deps = [
            d
            for d in parse_dependencies(item.get("dependencies"))
            if d in tasks_dict and d != task_id
        ]
        rows.append(
            {
                "タスクID": task_id,
                "タスク名": str(item.get("task_name", "")),
                "種類": role_option_label(str(item.get("task_type", _FALLBACK_ROLE))),
                "重要度": _clamp(item.get("importance", 3)),
                "難易度": _clamp(item.get("difficulty", 3)),
                "作業量": _to_float(item.get("workload"), 2.0),
                "機密性": bool(item.get("is_confidential", False)),
                "依存タスク": deps,
                "参照ファイル": str(item.get("reference_file_name") or ""),
            }
        )
    return pd.DataFrame(rows, columns=list(TASK_COLUMN_LABELS.values()))


def df_to_tasks_dict(df: pd.DataFrame) -> dict[str, dict[str, object]]:
    """:func:`task_editor_df` の逆変換。ID が空の新規行には自動採番する。

    名前も ID も空の行は「まだ書きかけの行」として捨てる。名前だけ空の行は残し、
    4 章の検証でエラーとして報告させる（黙って消さない）。
    """
    result: dict[str, dict[str, object]] = {}
    for row in df.to_dict("records"):
        name = str(row.get("タスク名") or "").strip()
        task_id = normalize_task_id(row.get("タスクID"))
        if task_id.lower() in {"", "nan", "none"}:
            if not name:
                continue
            task_id = generate_next_task_id(result)
        role = role_from_option(row.get("種類"))
        reference = str(row.get("参照ファイル") or "").strip()
        # MultiselectColumn の options は列単位なので自分自身も選べてしまう。ここで落とす。
        deps = [d for d in parse_dependencies(row.get("依存タスク")) if d != task_id]
        result[task_id] = {
            "task_id": task_id,
            "task_name": name,
            "task_type": role,
            "importance": _clamp(row.get("重要度", 3)),
            "difficulty": _clamp(row.get("難易度", 3)),
            "workload": _to_float(row.get("作業量")),
            "is_confidential": bool(row.get("機密性", False)),
            "dependencies": deps,
            "reference_file_name": reference or None,
        }
    return result


def task_option_label(tasks_dict: dict[str, dict[str, object]], task_id: str) -> str:
    """依存タスクの選択肢に出す表示名（``T003　予約枠管理 API``）。"""

    name = str(tasks_dict.get(task_id, {}).get("task_name") or "").strip()
    return f"{task_id}　{name}" if name else task_id


def stale_dependencies(tasks_dict: dict[str, dict[str, object]]) -> list[str]:
    """存在しないタスク・自分自身を指している依存を ``"T005 → T004"`` 形式で列挙する。"""

    issues: list[str] = []
    for task_id, item in tasks_dict.items():
        for dep in item.get("dependencies") or []:  # type: ignore[union-attr]
            if str(dep) == task_id or str(dep) not in tasks_dict:
                issues.append(f"{task_id} → {dep}")
    return issues


def merge_generated_tasks(
    existing: dict[str, dict[str, object]],
    generated: list[Task],
    *,
    replace: bool,
    reference_file_name: str | None = None,
) -> dict[str, dict[str, object]]:
    """生成タスクを tasks_dict へ反映する。

    ``replace=False`` のときは ID を振り直して追記し、依存関係も新 ID へ張り替える
    （振り直しだけして依存を放置すると、編成図の矢印が消える）。
    """
    incoming = model_tasks_to_tasks_dict(generated)
    if reference_file_name:
        for item in incoming.values():
            item["reference_file_name"] = reference_file_name
    if replace:
        return incoming

    merged = dict(existing)
    id_map: dict[str, str] = {}
    for old_id, item in incoming.items():
        new_id = generate_next_task_id(merged)
        id_map[old_id] = new_id
        merged[new_id] = {**item, "task_id": new_id}
    for new_id in id_map.values():
        deps = merged[new_id].get("dependencies") or []
        merged[new_id]["dependencies"] = [id_map.get(str(d), str(d)) for d in deps]  # type: ignore[union-attr]
    return merged


def generate_optimization_input(
    tasks_dict: dict[str, dict[str, object]],
    budget_limit: float = 1000.0,
    optimization_mode: str = "balanced",
    time_limit_seconds: int = 60,
) -> dict[str, object]:
    """要件定義書 7.2 に準拠した optimization_input 辞書を生成する。"""
    return {
        "tasks": list(tasks_dict.values()),
        "config": {
            "budget_limit": float(budget_limit),
            "optimization_mode": str(optimization_mode),
            "time_limit_seconds": int(time_limit_seconds),
        },
    }


def validate_task_setting_inputs(
    tasks_dict: dict[str, dict[str, object]],
    budget_limit: float,
    optimization_mode: str,
    uploaded_file_name: str | None = None,
    uploaded_file_size: int | None = None,
) -> list[str]:
    """要件定義書 FR-07 に基づく入力検証。問題がある場合は修正方法を含むエラー文のリストを返す。"""
    errors: list[str] = []

    # 1. 予算上限が0より大きいこと
    if budget_limit <= 0:
        errors.append(
            "予算上限は 0 より大きい値を入力してください。"
            "（「3. 全体条件設定」の「予算上限（USD）」を修正してください）"
        )

    # 2. 最適化方針が選択されていること
    if not optimization_mode or (
        optimization_mode not in OPTIMIZATION_MODE_MAP
        and optimization_mode not in OPTIMIZATION_MODE_REVERSE_MAP
    ):
        errors.append(
            "最適化方針を選択してください。（「コスト優先」「バランス」「精度優先」から選んでください）"
        )

    # 3. 参照ファイルの検証
    if uploaded_file_name:
        ext = os.path.splitext(uploaded_file_name)[1].lower()
        if ext not in ALLOWED_FILE_EXTENSIONS:
            allowed = ", ".join(sorted(ALLOWED_FILE_EXTENSIONS))
            errors.append(
                f"参照ファイル「{uploaded_file_name}」の形式（{ext}）は対応していません。対応形式（{allowed}）のファイルを指定してください。"
            )
        if uploaded_file_size is not None and uploaded_file_size > MAX_FILE_SIZE_BYTES:
            errors.append(
                f"参照ファイル「{uploaded_file_name}」のサイズが上限（10MB）を超えています。10MB以下のファイルを指定してください。"
            )

    # 4. タスクが1件以上登録されていること
    if not tasks_dict:
        errors.append("タスクが登録されていません。少なくとも1件以上のタスクを追加してください。")
        return errors

    # 5. 各タスクの検証
    seen_ids = set()
    for tid, item in tasks_dict.items():
        task_id = str(item.get("task_id", "")).strip()
        task_name = str(item.get("task_name", "")).strip()
        importance = item.get("importance")
        workload = item.get("workload")

        label_ = task_name or task_id or str(tid)

        if not task_id:
            errors.append(
                f"タスクキー「{tid}」のタスクIDが空です。一意なタスクIDを設定してください。"
            )
        elif task_id in seen_ids:
            errors.append(
                f"タスクID「{task_id}」が重複しています。一意なタスクIDに修正してください。"
            )
        else:
            seen_ids.add(task_id)

        if not task_name:
            errors.append(
                f"タスク（ID: {task_id or tid}）のタスク名が空です。タスク名を入力してください。"
            )

        try:
            imp_val = int(importance)  # type: ignore[arg-type]
            if imp_val < 1 or imp_val > 5:
                errors.append(
                    f"タスク「{label_}」の重要度は1〜5の範囲で設定してください。"
                    f"（現在値: {importance}）"
                )
        except (TypeError, ValueError):
            errors.append(f"タスク「{label_}」の重要度が不正です。1〜5の整数値を指定してください。")

        wl_val = _to_float(workload)
        if wl_val is None:
            errors.append(
                f"タスク「{label_}」の作業量が未入力または不正な数値です。"
                "0より大きい数値を入力してください。"
            )
        elif wl_val <= 0:
            errors.append(
                f"タスク「{label_}」の作業量は0より大きい値を入力してください。"
                f"（現在値: {workload}）"
            )

    return errors


def tasks_to_df(tasks: list[Task]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "id": t.id,
                "title": t.title,
                "role": t.role,
                "difficulty": t.difficulty,
                "priority": t.priority,
                "est_time": t.est_time,
                "confidential": t.confidential,
                "dependencies": ", ".join(t.dependencies),
            }
            for t in tasks
        ]
    )


def df_to_tasks(df: pd.DataFrame) -> list[Task]:
    tasks: list[Task] = []
    for idx, row in enumerate(df.itertuples(index=False), start=1):
        title = str(getattr(row, "title", "") or "").strip()
        if not title:
            continue
        role = str(getattr(row, "role", _FALLBACK_ROLE))
        if role not in ROLES:
            role = _FALLBACK_ROLE
        deps_raw = str(getattr(row, "dependencies", "") or "")
        tasks.append(
            Task(
                id=str(getattr(row, "id", "") or f"T{idx:02d}").strip(),
                title=title,
                role=role,
                difficulty=_clamp(getattr(row, "difficulty", 3)),
                priority=_clamp(getattr(row, "priority", 3)),
                est_time=max(0.5, float(getattr(row, "est_time", 2.0) or 2.0)),
                dependencies=[
                    d.strip() for d in deps_raw.replace("、", ",").split(",") if d.strip()
                ],
                confidential=bool(getattr(row, "confidential", False)),
            )
        )
    return tasks


def _clamp(value: object) -> int:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 3
    if number != number:  # NaN
        return 3
    return max(1, min(5, int(round(number))))


def _to_float(value: object, default: float | None = None) -> float | None:
    """数値化できない値・NaN は ``default`` にする。既定は None（未入力として検証に回す）。"""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return default if number != number else number


def validate_tasks(tasks: list[Task]) -> list[str]:
    warnings: list[str] = []
    ids = [t.id for t in tasks]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        warnings.append(f"重複したタスク ID: {', '.join(sorted(dup))}")
    known = set(ids)
    for t in tasks:
        missing = [d for d in t.dependencies if d not in known]
        if missing:
            warnings.append(f"{t.id}: 未知の依存 {', '.join(missing)}")
    return warnings


# --------------------------------------------------------------------------- #
# モデル表示
# --------------------------------------------------------------------------- #
_CAT_LABEL = {
    "repo_bug_fix": "コード",
    "terminal": "ターミナル",
    "document": "文書",
    "ocr": "OCR",
    "image_generation": "画像生成",
}


def agents_overview_df(agents: list[Agent]) -> pd.DataFrame:
    rows = []
    for a in agents:
        quals = list(a.quality.values())
        rows.append(
            {
                "モデル": a.name,
                "提供": a.provider,
                "種別": a.model_type,
                "社外": "○" if a.external else "—",
                "対応": " / ".join(
                    _CAT_LABEL[c] for c in CATEGORIES if a.capability.get(c) is not None
                ),
                "平均品質": round(float(np.mean(quals)), 2) if quals else 0.0,
                "コスト/タスク": a.cost_per_task,
                "処理時間": a.latency_sec,
                "最大担当": a.max_tasks,
            }
        )
    return pd.DataFrame(rows)


def selectable_models_df(agents: list[Agent], selected_ids: set[str]) -> pd.DataFrame:
    """表内チェックボックスでモデルを選ぶための DataFrame（`id` 列は表示側で隠す）。"""

    rows = []
    for a in agents:
        quals = list(a.quality.values())
        rows.append(
            {
                "id": a.id,
                "使う": a.id in selected_ids,
                "モデル": a.name,
                "提供": a.provider,
                "種別": a.model_type,
                "社内": not a.external,
                "対応": " / ".join(
                    _CAT_LABEL[c] for c in CATEGORIES if a.capability.get(c) is not None
                ),
                "平均品質": round(float(np.mean(quals)), 2) if quals else 0.0,
                "コスト/タスク": a.cost_per_task,
                "処理時間": a.latency_sec,
            }
        )
    return pd.DataFrame(rows)


def model_categories(agent: Agent) -> set[str]:
    return {c for c in CATEGORIES if agent.capability.get(c) is not None}


def _model_source_url(model: dict[str, object]) -> str:
    """そのモデルの主カテゴリの出典 URL。"""

    cats = category_source()
    idx = source_index()
    cap = model.get("capability", {})
    for c in CATEGORIES:
        if isinstance(cap, dict) and cap.get(c) is not None:
            return idx.get(cats.get(c, ""), "")
    return ""


def models_df(ids: Collection[str] | None = None) -> pd.DataFrame:
    """生のベンチマーク値・価格・出典リンク（能力マトリクスの表表示）。

    ``ids`` を渡すと、その model_id の行だけに絞る（順序は models.json のまま）。
    """

    rows = []
    for m in load_models():
        if ids is not None and m["model_id"] not in ids:
            continue
        cap = m.get("capability", {})
        pr = m.get("pricing", {})
        row: dict[str, object] = {
            "モデル": m["model_name"],
            "提供": m["provider"],
            "種別": m["model_type"],
            "社外": "○" if m.get("external_api", True) else "—",
        }
        for c in CATEGORIES:
            v = cap.get(c)
            row[_CAT_LABEL[c]] = round(v, 2) if v is not None else None
        row["入力(/1M)"] = pr.get("input_per_1m")
        row["出力(/1M)"] = pr.get("output_per_1m")
        row["実測(/タスク)"] = pr.get("benchmark_cost_per_task")
        row["出典"] = _model_source_url(m)
        rows.append(row)
    return pd.DataFrame(rows)


def source_links_md() -> str:
    """出典の一覧を Markdown リンクで。"""

    return " ／ ".join(f"[{name}]({url})" for name, url in source_index().items())


def capability_matrix(agents: list[Agent]) -> dict[str, dict[str, object]]:
    """仕様どおりの model_capability_matrix（Task 別スコアはこの後 QUBO 前処理で合成）。"""

    by_id = {m["model_id"]: m for m in load_models()}
    matrix: dict[str, dict[str, object]] = {}
    for a in agents:
        m = by_id.get(a.id, {})
        cap = m.get("capability", {})
        pr = m.get("pricing", {})
        matrix[a.name] = {
            "model_id": a.id,
            "provider": a.provider,
            "repo_bug_fix_score": cap.get("repo_bug_fix"),
            "terminal_score": cap.get("terminal"),
            "document_score": cap.get("document"),
            "ocr_score": cap.get("ocr"),
            "table_score": cap.get("table"),
            "kie_score": cap.get("kie"),
            "vqa_score": cap.get("vqa"),
            "image_generation_score": cap.get("image_generation"),
            "input_price_per_1m": pr.get("input_per_1m"),
            "output_price_per_1m": pr.get("output_per_1m"),
            "benchmark_cost_per_task": pr.get("benchmark_cost_per_task"),
            "benchmark_scores": m.get("benchmark_scores", {}),
            "sources": m.get("sources", {}),
        }
    return matrix


def model_can_take(agent: Agent, task: Task) -> bool:
    """そのモデルがそのタスクを担当できるか（能力対応 かつ 機密→社外でない）。"""

    return agent.can_do(task.role) and not (task.confidential and agent.external)


def coverage_gaps(tasks: list[Task], selected: list[Agent]) -> list[str]:
    """選択モデルでは担当できないタスクの一覧（人間向けメッセージ）。"""

    gaps: list[str] = []
    for t in tasks:
        if not any(model_can_take(a, t) for a in selected):
            why = "社内モデル未選択" if t.confidential else f"「{label(t.role)}」対応モデルなし"
            gaps.append(f"{t.id} {t.title}（{why}）")
    return gaps


def min_cost_estimate(tasks: list[Task], selected: list[Agent]) -> float | None:
    """各タスクを最も安い割当可能モデルに振ったときの総コスト（予算の下限見積り）。"""

    by_id = {m["model_id"]: m for m in load_models()}
    total = 0.0
    for t in tasks:
        candidates = [a for a in selected if model_can_take(a, t)]
        if not candidates:
            return None
        total += min(cost_for(by_id[a.id], t.difficulty) for a in candidates)
    return round(total, 2)


# --------------------------------------------------------------------------- #
# 割当結果
# --------------------------------------------------------------------------- #
def assignment_df(result: AssignmentResult, agents: list[Agent], tasks: list[Task]) -> pd.DataFrame:
    by_id = {a.id: a for a in agents}
    rows = []
    for t in tasks:
        agent_id = result.assignments.get(t.id)
        agent = by_id.get(agent_id) if agent_id else None
        rows.append(
            {
                "タスク": f"{t.id} {t.title}",
                "役割": label(t.role),
                "重要度": t.priority,
                "機密": "🔒" if t.confidential else "",
                "担当エージェント": agent.name if agent else "（未割当）",
                "品質": round(agent.q(t.role), 2) if agent else None,
                "信頼性": round(agent.r(t.role), 2) if agent else None,
            }
        )
    return pd.DataFrame(rows)


def explain_assignment(
    result: AssignmentResult,
    agents: list[Agent],
    tasks: list[Task],
    coeffs: Coefficients,
) -> pd.DataFrame:
    idx_of = {a.id: i for i, a in enumerate(agents)}
    rows = []
    for j, t in enumerate(tasks):
        agent_id = result.assignments.get(t.id)
        if agent_id is None:
            rows.append({"タスク": t.id, "理由": "未割当（制約により配置できず）"})
            continue
        i = idx_of[agent_id]
        col = coeffs.q[:, j].copy()
        col[coeffs.forbidden[:, j]] = -1.0
        best_i = int(np.argmax(col))
        if t.confidential:
            reason = "機密タスクのため社内エージェントに限定"
        elif i == best_i:
            reason = "この役割で最も品質が高い"
        elif coeffs.c[i, j] <= np.median(coeffs.c[:, j]):
            reason = "予算内で品質とコストのバランスが最善"
        else:
            reason = "負荷分散のため次善のエージェントへ配分"
        rows.append({"タスク": f"{t.id} {t.title}", "担当": agents[i].name, "理由": reason})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# 編成図（Graphviz DOT）
# --------------------------------------------------------------------------- #
def _esc(text: str, limit: int = 16) -> str:
    text = text.replace('"', "'").replace("\n", " ").strip()
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text


def assignment_graph_dot(result: AssignmentResult, agents: list[Agent], tasks: list[Task]) -> str:
    """タスク→担当エージェントの編成を、依存関係の矢印つきで DOT 図にする。"""

    task_by_id = {t.id: t for t in tasks}
    color_of = {a.id: AGENT_COLORS[i % len(AGENT_COLORS)] for i, a in enumerate(agents)}

    def node_line(t: Task) -> str:
        border = "#C0392B" if t.confidential else "#5B6472"
        pen = "2.4" if t.confidential else "1.0"
        lock = "🔒 " if t.confidential else ""
        fill = role_fill(t.role)
        lbl = f"{t.id}  {lock}{_esc(t.title)}\\n[{label(t.role)}]"
        attrs = f'label="{lbl}", fillcolor="{fill}", color="{border}", penwidth={pen}'
        return f'    "{t.id}" [{attrs}];'

    lines = [
        "digraph assignment {",
        '  bgcolor="transparent";',
        "  rankdir=LR;",
        "  compound=true;",
        '  node [shape=box, style="filled,rounded", fontname="Helvetica", '
        'fontsize=10, fontcolor="#15181F", margin="0.12,0.07"];',
        '  edge [color="#9AA3B2", arrowsize=0.7, penwidth=1.1];',
    ]

    for i, agent in enumerate(agents):
        assigned = [tid for tid, aid in result.assignments.items() if aid == agent.id]
        if not assigned:
            continue
        col = color_of[agent.id]
        head = f"{_esc(agent.name, 24)}\\n${agent.cost_per_task:.2f}/タスク  ·  {len(assigned)}件"
        lines.append(f"  subgraph cluster_{i} {{")
        lines.append(f'    label="{head}";')
        lines.append(f'    style="rounded"; color="{col}"; fontcolor="{col}"; penwidth=2;')
        lines.append('    fontname="Helvetica-Bold"; fontsize=11;')
        for tid in assigned:
            lines.append(node_line(task_by_id[tid]))
        lines.append("  }")

    unassigned = [t for t in tasks if t.id not in result.assignments]
    if unassigned:
        lines.append("  subgraph cluster_unassigned {")
        lines.append(
            '    label="未割当"; style="rounded,dashed"; color="#C0392B"; fontcolor="#C0392B";'
        )
        for t in unassigned:
            lines.append(node_line(t))
        lines.append("  }")

    for t in tasks:
        for dep in t.dependencies:
            if dep in task_by_id:
                lines.append(f'  "{dep}" -> "{t.id}";')

    lines.append("}")
    return "\n".join(lines)


def role_legend_html() -> str:
    chips = []
    for cat in CATEGORIES:
        chips.append(
            f'<span style="display:inline-block;margin:2px 8px 2px 0;padding:1px 8px;'
            f"border-radius:4px;background:{_CATEGORY_FILL.get(cat, '#EEF1F4')};"
            f'color:#15181F;font-size:12px;">{_CAT_LABEL[cat]}</span>'
        )
    chips.append(
        '<span style="display:inline-block;margin:2px 0;padding:1px 8px;border-radius:4px;'
        'border:2px solid #C0392B;font-size:12px;">🔒 機密タスク</span>'
    )
    return "".join(chips)


# --------------------------------------------------------------------------- #
# グラフ
# --------------------------------------------------------------------------- #
def load_bar_fig(result: AssignmentResult, agents: list[Agent]):
    names = [a.name for a in agents]
    counts = [len(result.per_agent.get(a.id, [])) for a in agents]
    fig, ax = plt.subplots(figsize=(6, 2.6 + 0.25 * len(agents)))
    ax.barh(names, counts, color="#2E45D9")
    ax.set_xlabel("担当タスク数")
    ax.invert_yaxis()
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    return fig


def cost_bar_fig(
    result: AssignmentResult,
    agents: list[Agent],
    tasks: list[Task],
    coeffs: Coefficients,
):
    idx_of = {a.id: i for i, a in enumerate(agents)}
    id_of_task = {t.id: j for j, t in enumerate(tasks)}
    per_cost = {a.name: 0.0 for a in agents}
    for task_id, agent_id in result.assignments.items():
        i, j = idx_of[agent_id], id_of_task[task_id]
        per_cost[agents[i].name] += float(coeffs.c[i, j])
    fig, ax = plt.subplots(figsize=(6, 2.6 + 0.25 * len(agents)))
    ax.barh(list(per_cost), list(per_cost.values()), color="#1E7A5B")
    ax.set_xlabel("コスト合計（USD）")
    ax.invert_yaxis()
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    return fig


def comparison_df(results: dict[str, AssignmentResult]) -> pd.DataFrame:
    rows = []
    for name, res in results.items():
        m = res.metric
        rows.append(
            {
                "手法": name,
                "目的関数値": round(m.objective, 3),
                "期待品質": round(m.exp_quality, 3),
                "信頼性": round(m.reliability, 3),
                "コスト($)": round(m.cost_total, 2),
                "makespan(秒)": round(m.makespan, 0),
                "負荷σ": round(m.load_std, 2),
                "実行可能": "✓" if m.feasible else "✗",
                "違反数": m.violations,
                "solve(ms)": round(m.solve_ms, 1),
            }
        )
    return pd.DataFrame(rows)


def comparison_bar_fig(results: dict[str, AssignmentResult]):
    names = list(results)
    quality = np.array([results[n].metric.exp_quality for n in names])
    cost = np.array([results[n].metric.cost_total for n in names])
    time_ = np.array([results[n].metric.makespan for n in names])

    def norm(v: np.ndarray) -> np.ndarray:
        span = v.max() - v.min()
        return (v - v.min()) / span if span > 1e-9 else np.zeros_like(v)

    data = {
        "品質(高いほど良)": norm(quality),
        "コスト(低いほど良)": norm(cost),
        "時間(低いほど良)": norm(time_),
    }
    x = np.arange(len(names))
    width = 0.26
    fig, ax = plt.subplots(figsize=(7, 3.4))
    for k, (label_, vals) in enumerate(data.items()):
        ax.bar(x + (k - 1) * width, vals, width, label=label_)
    ax.set_xticks(x)
    ax.set_xticklabels(names, rotation=15, ha="right")
    ax.set_ylabel("正規化スコア（0-1）")
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    return fig


def scatter_fig(results: dict[str, AssignmentResult]):
    fig, ax = plt.subplots(figsize=(6, 3.6))
    for name, res in results.items():
        ax.scatter(max(res.metric.solve_ms, 0.1), res.metric.objective, s=70)
        ax.annotate(
            name,
            (max(res.metric.solve_ms, 0.1), res.metric.objective),
            textcoords="offset points",
            xytext=(6, 4),
            fontsize=8,
        )
    ax.set_xscale("log")
    ax.set_xlabel("solve 時間（ms・対数）")
    ax.set_ylabel("目的関数値（高いほど良）")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    return fig
