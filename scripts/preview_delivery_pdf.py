"""開発用: 長文・日本語を含むPDFの表示確認。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from report_pdf import render_report_pdf  # noqa: E402

if __name__ == "__main__":
    import pymupdf

    target = Path("tmp/pdfs")
    target.mkdir(parents=True, exist_ok=True)
    sections = [
        "# タスク実行報告", "## アプリの紹介",
        "売上管理アプリ。売上登録・月別集計・CSV出力を備え、社内の情報共有を支援します。",
        "## 予算", "最大予算: 15.0000 USD", "初回実行の見積額: 4.2500 USD",
        "成果物生成APIの実支出: 0 USD（模擬実行。添付成果物の外部制作費は未集計）",
        "## アプリのアーキテクチャー", "画面 → API → データベース\n認証処理と権限管理を設ける。",
        "## タスク構成・レビュー箇所・成果物",
    ]
    for index in range(1, 9):
        sections.extend([
            f"### T{index:02d}: 入力画面・検証・成果物の確認",
            "担当モデル: example-model", "レビュー: " + "入力検証とエラー表示を改善しました。" * 12,
            "レビュー状態: 完了", "成果物: 未添付（ZIPへの収録なし）",
        ])
    data = render_report_pdf(sections)
    (target / "preview.pdf").write_bytes(data)
    doc = pymupdf.open(stream=data, filetype="pdf")
    for index, page in enumerate(doc):
        page.get_pixmap(matrix=pymupdf.Matrix(1, 1)).save(target / f"page-{index + 1}.png")
    print(f"Rendered {len(doc)} pages")
