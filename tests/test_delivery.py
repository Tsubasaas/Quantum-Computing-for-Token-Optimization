"""ZIPの完了条件と実ファイル・報告内容を確認する。"""

import io
import sys
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from delivery import build_delivery  # noqa: E402

from taqumi2026s_teame.models import Task  # noqa: E402


def test_delivery_requires_all_reviews_and_successful_run():
    tasks = [Task(id="T1", title="コード", role="code_gen")]
    with pytest.raises(ValueError):
        build_delivery(tasks, None, {}, {}, {}, {}, "")
    with pytest.raises(ValueError):
        build_delivery(tasks, None, {}, {}, {"T1": True}, {}, "")


def test_delivery_without_attachments_contains_report():
    tasks = [Task(id="T1", title="コード", role="code_gen")]
    plan = SimpleNamespace(label="バランス", total_budget=10, total_cost=2,
                           assignment={"T1": "model"})
    data = build_delivery(
        tasks, plan, {"status": "succeeded"}, {}, {"T1": True}, {}, "",
    )
    with ZipFile(io.BytesIO(data)) as archive:
        assert set(archive.namelist()) == {"タスク実行報告.md", "タスク実行報告.pdf"}
        assert archive.read("タスク実行報告.pdf").startswith(b"%PDF-")
        assert "未添付" in archive.read("タスク実行報告.md").decode("utf-8")


def test_delivery_contains_actual_bytes_and_report():
    tasks = [Task(id="T1", title="コード", role="code_gen")]
    plan = SimpleNamespace(label="バランス", total_budget=10, total_cost=2,
                           assignment={"T1": "model"})
    data = build_delivery(
        tasks, plan, {"status": "succeeded", "request": "売上管理アプリ"},
        {"T1": "入力検証を修正"}, {"T1": True},
        {"T1": [("../../app.py", b"print('hello')")]}, "画面 → API → DB",
    )
    with ZipFile(io.BytesIO(data)) as archive:
        report = archive.read("タスク実行報告.md").decode("utf-8")
        assert "入力検証を修正" in report and "画面 → API → DB" in report
        assert "2.0000 USD" in report and "売上管理アプリ" in report
        files = [name for name in archive.namelist() if name.startswith("code/")]
        assert len(files) == 1
        assert ".." not in files[0].split("/")
        assert archive.read(files[0]) == b"print('hello')"
