"""タスク設定UI要件定義書に基づく単体テスト・検証テスト。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

# app フォルダをモジュール検索パスに追加
app_path = Path(__file__).parent.parent / "app"
if str(app_path) not in sys.path:
    sys.path.insert(0, str(app_path))

from ui_helpers import (  # noqa: E402
    REQUIRED_TASK_COLUMNS,
    TASK_ID_DIGITS,
    df_to_tasks_dict,
    generate_next_task_id,
    generate_optimization_input,
    merge_generated_tasks,
    model_tasks_to_tasks_dict,
    normalize_task_id,
    parse_dependencies,
    stale_dependencies,
    task_editor_df,
    tasks_dict_to_df,
    tasks_dict_to_model_tasks,
    validate_task_setting_inputs,
)

from taqumi2026s_teame.data import load_sample_tasks  # noqa: E402
from taqumi2026s_teame.models import Task  # noqa: E402


@pytest.fixture
def sample_tasks_dict() -> dict[str, dict[str, object]]:
    return {
        "T001": {
            "task_id": "T001",
            "task_name": "商品説明文の生成",
            "task_type": "backend",
            "importance": 3,
            "workload": 2000.0,
            "is_confidential": False,
            "reference_file_name": None,
        },
        "T002": {
            "task_id": "T002",
            "task_name": "画像解析API",
            "task_type": "frontend",
            "importance": 5,
            "workload": 1500.0,
            "is_confidential": True,
            "reference_file_name": "specs.pdf",
        },
    }


def test_at01_auto_id_generation(sample_tasks_dict):
    """AT-01: 一意のIDが自動採番される。"""
    next_id = generate_next_task_id(sample_tasks_dict)
    assert next_id == "T003"

    sample_tasks_dict[next_id] = {
        "task_id": next_id,
        "task_name": "新規タスク",
        "task_type": "test",
        "importance": 4,
        "workload": 500.0,
        "is_confidential": False,
        "reference_file_name": None,
    }
    next_id_2 = generate_next_task_id(sample_tasks_dict)
    assert next_id_2 == "T004"


def test_at02_edit_task(sample_tasks_dict):
    """AT-02: 登録済みタスクの重要度を変更してもIDが維持される。"""
    sample_tasks_dict["T001"]["importance"] = 4
    assert sample_tasks_dict["T001"]["task_id"] == "T001"
    assert sample_tasks_dict["T001"]["importance"] == 4


def test_at03_delete_task(sample_tasks_dict):
    """AT-03: タスク削除。"""
    del sample_tasks_dict["T001"]
    assert "T001" not in sample_tasks_dict
    assert len(sample_tasks_dict) == 1


def test_at04_empty_task_name_validation(sample_tasks_dict):
    """AT-04: タスク名が空の場合はエラー。"""
    sample_tasks_dict["T003"] = {
        "task_id": "T003",
        "task_name": "   ",
        "task_type": "backend",
        "importance": 3,
        "workload": 1000.0,
        "is_confidential": False,
        "reference_file_name": None,
    }
    errors = validate_task_setting_inputs(sample_tasks_dict, 1000.0, "バランス")
    assert any("タスク名が空です" in e for e in errors)


def test_at05_budget_validation(sample_tasks_dict):
    """AT-05: 予算上限が0以下ならエラー（単位は USD に統一）。"""
    errors_zero = validate_task_setting_inputs(sample_tasks_dict, 0.0, "バランス")
    assert any("予算上限は 0 より大きい値" in e for e in errors_zero)

    errors_neg = validate_task_setting_inputs(sample_tasks_dict, -100.0, "バランス")
    assert any("予算上限は 0 より大きい値" in e for e in errors_neg)


def test_at06_importance_validation(sample_tasks_dict):
    """AT-06: 重要度が1〜5の範囲外ならエラー。"""
    sample_tasks_dict["T001"]["importance"] = 6
    errors = validate_task_setting_inputs(sample_tasks_dict, 1000.0, "バランス")
    assert any("重要度は1〜5の範囲" in e for e in errors)


def test_at07_valid_without_file(sample_tasks_dict):
    """AT-07: 参照ファイルなしでも正常に通過する。"""
    errors = validate_task_setting_inputs(
        sample_tasks_dict,
        budget_limit=1000.0,
        optimization_mode="バランス",
        uploaded_file_name=None,
    )
    assert errors == []


def test_at08_unsupported_file_extension(sample_tasks_dict):
    """AT-08: 未対応形式のファイルならエラー。"""
    errors = validate_task_setting_inputs(
        sample_tasks_dict,
        budget_limit=1000.0,
        optimization_mode="バランス",
        uploaded_file_name="virus.exe",
    )
    assert any("対応していません" in e for e in errors)


def test_at11_tasks_dict_7_columns(sample_tasks_dict):
    """AT-11: tasks_dict が指定された7カラムを持つ。"""
    df = tasks_dict_to_df(sample_tasks_dict)
    for col in REQUIRED_TASK_COLUMNS:
        assert col in df.columns, f"{col} が見つかりません"


def test_at12_optimization_input_structure(sample_tasks_dict):
    """AT-12: optimization_input が tasks と config の所定構造を持つ。"""
    opt_input = generate_optimization_input(
        sample_tasks_dict,
        budget_limit=1500.0,
        optimization_mode="accuracy_first",
        time_limit_seconds=60,
    )
    assert "tasks" in opt_input
    assert "config" in opt_input
    assert isinstance(opt_input["tasks"], list)
    assert len(opt_input["tasks"]) == 2
    assert opt_input["config"]["budget_limit"] == 1500.0
    assert opt_input["config"]["optimization_mode"] == "accuracy_first"
    assert opt_input["config"]["time_limit_seconds"] == 60


def test_compatibility_with_model_tasks():
    """既存の Task モデルと相互変換できる。"""
    sample_tasks = load_sample_tasks()
    as_dict = model_tasks_to_tasks_dict(sample_tasks)
    assert len(as_dict) == len(sample_tasks)

    # 必須カラムチェック
    first_item = next(iter(as_dict.values()))
    for col in REQUIRED_TASK_COLUMNS:
        assert col in first_item

    # 逆変換
    converted_back = tasks_dict_to_model_tasks(as_dict)
    assert len(converted_back) == len(sample_tasks)
    assert converted_back[0].id == sample_tasks[0].id
    assert converted_back[0].title == sample_tasks[0].title


def test_difficulty_and_dependencies_survive_round_trip():
    """難易度・依存関係が tasks_dict を通しても失われない（QUBO の品質補正と編成図が使う）。"""
    sample_tasks = load_sample_tasks()
    restored = tasks_dict_to_model_tasks(model_tasks_to_tasks_dict(sample_tasks))
    for before, after in zip(sample_tasks, restored, strict=True):
        assert after.difficulty == before.difficulty
        assert after.dependencies == before.dependencies
    # サンプルには難易度 3 以外と依存ありのタスクが実際に含まれている
    assert any(t.difficulty != 3 for t in restored)
    assert any(t.dependencies for t in restored)


def test_data_editor_round_trip_is_lossless():
    """表示用 DataFrame への往復で tasks_dict が変化しない（往復のたびに差分が出ると
    「サンプル表示中」の状態が即座に「手編集済み」へ化ける）。"""
    original = model_tasks_to_tasks_dict(load_sample_tasks())
    assert df_to_tasks_dict(task_editor_df(original)) == original


def test_df_to_tasks_dict_assigns_id_to_new_rows():
    """data_editor で追加された ID 空の行に自動採番される。空行は捨てる。"""
    df = task_editor_df(model_tasks_to_tasks_dict(load_sample_tasks()[:2]))
    df.loc[len(df)] = {**dict.fromkeys(df.columns, None), "タスク名": "追加したタスク"}
    df.loc[len(df)] = dict.fromkeys(df.columns, None)  # 完全な空行

    result = df_to_tasks_dict(df)
    assert len(result) == 3
    added = [v for v in result.values() if v["task_name"] == "追加したタスク"]
    assert len(added) == 1
    assert added[0]["task_id"] not in {"", None}


def test_merge_generated_tasks_append_remaps_dependencies():
    """追記時に ID を振り直しても、依存関係が新しい ID を指し続ける。"""
    existing = model_tasks_to_tasks_dict(load_sample_tasks())
    merged = merge_generated_tasks(existing, load_sample_tasks(), replace=False)

    assert len(merged) == 2 * len(existing)
    known_ids = set(merged)
    for item in merged.values():
        for dep in item["dependencies"]:
            assert dep in known_ids, f"{item['task_id']} の依存 {dep} が迷子になっている"


def test_merge_generated_tasks_replace_discards_existing():
    existing = model_tasks_to_tasks_dict(load_sample_tasks())
    merged = merge_generated_tasks(existing, load_sample_tasks()[:3], replace=True)
    assert len(merged) == 3


# --------------------------------------------------------------------------- #
# タスクIDの桁数統一
# --------------------------------------------------------------------------- #
def test_normalize_task_id_pads_to_three_digits():
    assert normalize_task_id("T1") == "T001"
    assert normalize_task_id("T01") == "T001"
    assert normalize_task_id("T001") == "T001"
    assert normalize_task_id("t12") == "T012"
    assert normalize_task_id(" T7 ") == "T007"
    # T + 数字 以外はそのまま（勝手に壊さない）
    assert normalize_task_id("auth-api") == "auth-api"
    assert normalize_task_id(None) == ""


def test_sample_tasks_use_canonical_ids():
    """サンプルデータ自体が正準形（T001..）であること。"""
    for task in load_sample_tasks():
        assert re.fullmatch(rf"T\d{{{TASK_ID_DIGITS}}}", task.id), f"{task.id} が正準形でない"
        for dep in task.dependencies:
            assert re.fullmatch(rf"T\d{{{TASK_ID_DIGITS}}}", dep), f"{dep} が正準形でない"


def test_two_digit_ids_are_normalized_with_dependencies():
    """2桁 ID で入ってきても 3 桁へ揃え、依存関係も新 ID へ張り替える。"""
    legacy = [
        Task(id="T01", title="設計", role="plan"),
        Task(id="T02", title="実装", role="backend", dependencies=["T01"]),
    ]
    result = model_tasks_to_tasks_dict(legacy)
    assert list(result) == ["T001", "T002"]
    assert result["T002"]["dependencies"] == ["T001"]


def test_new_row_id_matches_existing_width():
    """表への追加行も 3 桁で揃い、既存の最大番号 + 1 になる。"""
    sample = load_sample_tasks()
    tasks_dict = model_tasks_to_tasks_dict(sample)
    df = task_editor_df(tasks_dict)
    df.loc[len(df)] = {**dict.fromkeys(df.columns, None), "タスク名": "追加したタスク"}

    ids = list(df_to_tasks_dict(df))
    assert ids[-1] == f"T{len(sample) + 1:0{TASK_ID_DIGITS}d}"
    assert all(re.fullmatch(rf"T\d{{{TASK_ID_DIGITS}}}", i) for i in ids)


def test_dependencies_column_holds_a_list_for_multiselect():
    """MultiselectColumn はリスト値を要求するので、表示用 DataFrame もリストで持つ。"""
    tasks_dict = model_tasks_to_tasks_dict(load_sample_tasks())
    df = task_editor_df(tasks_dict)
    values = df["依存タスク"].tolist()
    assert all(isinstance(v, list) for v in values)
    assert values[0] == []  # T001 は先行タスクなし
    assert values[1] == ["T001"]  # T002 は T001 に依存


def test_parse_dependencies_accepts_list_string_and_missing():
    assert parse_dependencies(["T001", "T002"]) == ["T001", "T002"]
    assert parse_dependencies("T001, T002") == ["T001", "T002"]
    assert parse_dependencies("T001、T002") == ["T001", "T002"]  # 全角カンマ
    assert parse_dependencies(None) == []
    assert parse_dependencies(float("nan")) == []
    assert parse_dependencies([]) == []


def test_self_reference_is_dropped():
    """MultiselectColumn の options は列単位で自分自身も選べるため、読み戻しで落とす。"""
    tasks_dict = model_tasks_to_tasks_dict(load_sample_tasks()[:3])
    df = task_editor_df(tasks_dict)
    df.at[1, "依存タスク"] = ["T001", "T002"]  # T002 の行に自分自身を混ぜる

    result = df_to_tasks_dict(df)
    assert result["T002"]["dependencies"] == ["T001"]


def test_stale_dependencies_reports_unknown_and_self():
    tasks_dict = model_tasks_to_tasks_dict(load_sample_tasks()[:3])
    tasks_dict["T002"]["dependencies"] = ["T001", "T099", "T002"]

    issues = stale_dependencies(tasks_dict)
    assert "T002 → T099" in issues  # 存在しない
    assert "T002 → T002" in issues  # 自分自身
    assert "T002 → T001" not in issues  # 正常なものは挙げない


def test_task_editor_df_hides_invalid_dependencies():
    """削除済みタスクを指す依存は表に出さない（選択肢に無い値を渡さない）。"""
    tasks_dict = model_tasks_to_tasks_dict(load_sample_tasks()[:3])
    tasks_dict["T003"]["dependencies"] = ["T002", "T099"]

    df = task_editor_df(tasks_dict)
    assert df.loc[df["タスクID"] == "T003", "依存タスク"].iloc[0] == ["T002"]


def test_duplicate_ids_do_not_silently_drop_tasks():
    """ID が重複しても採番し直して全件残す（辞書の後勝ちで消えないこと）。"""
    dup = [
        Task(id="T01", title="認証API", role="backend"),
        Task(id="T001", title="決済API", role="backend"),
        Task(id="T02", title="UI", role="frontend"),
    ]
    result = model_tasks_to_tasks_dict(dup)
    assert len(result) == 3
    assert {v["task_name"] for v in result.values()} == {"認証API", "決済API", "UI"}
