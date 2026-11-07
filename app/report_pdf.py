"""日本語フォントを埋め込んだ実行報告PDF。"""

import io
from importlib.resources import files
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer


def render_report_pdf(sections):
    font = "YakizakanaJapanese"
    if font not in pdfmetrics.getRegisteredFontNames():
        source = files("matplotlib_fontja").joinpath("fonts/ipaexg.ttf")
        pdfmetrics.registerFont(TTFont(font, str(source)))
    body = ParagraphStyle(
        "body", fontName=font, fontSize=10, leading=17, wordWrap="CJK",
        textColor=colors.HexColor("#132b40"), spaceAfter=8,
    )
    styles = {
        1: ParagraphStyle("title", parent=body, fontSize=23, leading=32, spaceAfter=20),
        2: ParagraphStyle(
            "section", parent=body, fontSize=14, leading=22, spaceBefore=16,
            spaceAfter=10, textColor=colors.HexColor("#087e8b"), keepWithNext=True,
        ),
        3: ParagraphStyle(
            "task", parent=body, fontSize=11, leading=19, spaceBefore=10,
            keepWithNext=True, borderPadding=6, backColor=colors.HexColor("#edf5f6"),
        ),
    }
    story = []
    task_block = []
    for text in sections:
        if not text:
            continue
        level = next((n for n in (3, 2, 1) if text.startswith("#" * n + " ")), 0)
        if level and task_block:
            story.append(KeepTogether(task_block))
            task_block = []
        content = text[level + 1:] if level else text
        paragraph = Paragraph(escape(content).replace("\n", "<br/>"), styles.get(level, body))
        if level == 3 or task_block:
            task_block.append(paragraph)
        else:
            story.append(paragraph)
    if task_block:
        story.append(KeepTogether(task_block))
    story.append(Spacer(1, 8))

    def page_frame(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#087e8b"))
        canvas.rect(0, A4[1] - 8, A4[0], 8, fill=1, stroke=0)
        canvas.setFont(font, 9)
        canvas.drawString(42, A4[1] - 33, "Yakizakanaヤキザカナ | 量子×AI、最適な実行プランへ")
        canvas.setFillColor(colors.HexColor("#596e7f"))
        canvas.drawString(42, 28, "タスク実行報告 / 模擬実行")
        canvas.drawRightString(A4[0] - 42, 28, f"{doc.page}")
        canvas.restoreState()

    output = io.BytesIO()
    document = SimpleDocTemplate(
        output, pagesize=A4, rightMargin=42, leftMargin=42,
        topMargin=60, bottomMargin=50, title="タスク実行報告 - Yakizakanaヤキザカナ",
        author="Yakizakanaヤキザカナ",
    )
    document.build(story, onFirstPage=page_frame, onLaterPages=page_frame)
    return output.getvalue()
