"""レビュー完了後の実ファイルと実行報告を ZIP にまとめる。"""

import io
import re
from zipfile import ZIP_DEFLATED, ZipFile

from report_pdf import render_report_pdf

from taqumi2026s_teame.data.task_types import plan_category_of


def build_delivery(tasks, plan, run, reviews, completed, artifacts, architecture):
    if not tasks or any(not completed.get(t.id) for t in tasks):
        raise ValueError("全タスクのレビュー完了が必要です。")
    if run.get("status") != "succeeded":
        raise ValueError("実行が完了していません。")
    report = [
        "# タスク実行報告", "", "## アプリの紹介", run.get("request", ""), "",
        "## 予算", f"選択プラン: {plan.label}",
        f"最大予算: {plan.total_budget:.4f} USD",
        f"初回実行の見積額: {plan.total_cost:.4f} USD",
        "成果物生成APIの実支出: 0 USD（模擬実行。添付成果物の外部制作費は未集計）", "",
        "## アプリのアーキテクチャー",
        architecture.strip() or "実装構成は未記入。以下は計画上のタスク構成・依存関係です。", "",
        "## タスク構成・レビュー箇所・成果物",
    ]
    output = io.BytesIO()
    for attempt in run.get("rerun_reports", []):
        report.extend([
            "### 再求解の記録（模擬実行）",
            f"対象: {', '.join(attempt['task_ids'])}",
            f"状態: {attempt['status']}",
            f"追加見積額: {attempt['estimated_cost']} USD（実支出ではありません）",
            f"レビュー内容: {attempt['reviews']}",
        ])
    folders = {"code": "code", "image": "images", "doc": "documents"}
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for index, task in enumerate(tasks, 1):
            report.extend([
                f"### {task.id}: {task.title}",
                f"前提: {', '.join(task.dependencies) or 'なし'}",
                f"担当モデル: {plan.assignment.get(task.id, '未割当')}",
                f"レビュー: {reviews.get(task.id) or '指摘なし'}", "レビュー状態: 完了",
            ])
            if not artifacts.get(task.id):
                report.append("成果物: 未添付（ZIPへの収録なし）")
            for number, (name, data) in enumerate(artifacts.get(task.id, []), 1):
                safe = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', name).strip('. ') or 'file'
                path = f"{folders[plan_category_of(task.role)]}/{index:03d}/{number:03d}_{safe}"
                archive.writestr(path, data)
                report.append(f"成果物: {path}")
            report.append("")
        archive.writestr("タスク実行報告.md", "\n\n".join(report).encode("utf-8"))
        archive.writestr("タスク実行報告.pdf", render_report_pdf(report))
    return output.getvalue()
