import os
from contextlib import asynccontextmanager

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

import lira_engine as engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        engine.load_model()
        engine.initialize_reference_data()
        app.state.engine_error = None
    except Exception as exc:
        app.state.engine_error = str(exc)
    yield


app = FastAPI(
    title="LIRA API",
    description="Learning Intrusion Reasoning Agent",
    version="1.0.0",
    lifespan=lifespan,
)


class DetectOptions(BaseModel):
    row_index: int = 0


class ReportPDFRequest(BaseModel):
    report_markdown: str


def _markdown_to_pdf(markdown_text: str) -> bytes:
    """Render an investigation Markdown report as a downloadable PDF."""
    from io import BytesIO
    import re
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem,
        Preformatted, HRFlowable,
    )

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=18*mm, leftMargin=18*mm,
        topMargin=18*mm, bottomMargin=18*mm,
        title="LIRA - Network Security Investigation Report",
        author="LIRA - Learning Intrusion Reasoning Agent",
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="LiraTitle", parent=styles["Title"], fontName="Helvetica-Bold",
        fontSize=19, leading=23, textColor=colors.HexColor("#17365D"),
        alignment=TA_CENTER, spaceAfter=14,
    ))
    styles.add(ParagraphStyle(
        name="LiraH2", parent=styles["Heading2"], textColor=colors.HexColor("#174A73"),
        spaceBefore=10, spaceAfter=6, keepWithNext=True,
    ))
    styles.add(ParagraphStyle(
        name="LiraH3", parent=styles["Heading3"], textColor=colors.HexColor("#28627D"),
        spaceBefore=8, spaceAfter=4, keepWithNext=True,
    ))
    styles.add(ParagraphStyle(
        name="LiraBody", parent=styles["BodyText"], fontSize=9, leading=13,
        spaceAfter=5,
    ))
    styles.add(ParagraphStyle(
        name="LiraCode", parent=styles["Code"], fontSize=7.5, leading=10,
        backColor=colors.HexColor("#F1F4F7"), borderPadding=6,
    ))

    def inline_markup(value: str) -> str:
        value = escape(value)
        value = re.sub(r"`([^`]+)`", r'<font name="Courier">\1</font>', value)
        value = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", value)
        value = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", value)
        return value

    story = []
    lines = markdown_text.replace("\r\n", "\n").split("\n")
    paragraph = []
    bullets = []
    numbered = []
    in_code = False
    code_lines = []

    def flush_paragraph():
        if paragraph:
            story.append(Paragraph(inline_markup(" ".join(paragraph)), styles["LiraBody"]))
            paragraph.clear()

    def flush_list():
        if bullets:
            story.append(ListFlowable(
                [ListItem(Paragraph(inline_markup(x), styles["LiraBody"])) for x in bullets],
                bulletType="bullet", leftIndent=14, bulletFontSize=7,
            ))
            bullets.clear()
        if numbered:
            story.append(ListFlowable(
                [ListItem(Paragraph(inline_markup(x), styles["LiraBody"])) for x in numbered],
                bulletType="1", leftIndent=18,
            ))
            numbered.clear()

    for raw in lines:
        line = raw.strip()
        if line.startswith("```"):
            flush_paragraph(); flush_list()
            if in_code:
                story.append(Preformatted("\n".join(code_lines), styles["LiraCode"]))
                story.append(Spacer(1, 5))
                code_lines.clear()
            in_code = not in_code
            continue
        if in_code:
            code_lines.append(raw.rstrip())
            continue
        if not line:
            flush_paragraph(); flush_list()
            continue
        if line in {"---", "***", "___"}:
            flush_paragraph(); flush_list()
            story.append(HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#B8C4CE")))
            story.append(Spacer(1, 6))
            continue
        if line.startswith("# "):
            flush_paragraph(); flush_list()
            story.append(Paragraph(inline_markup(line[2:]), styles["LiraTitle"]))
        elif line.startswith("## "):
            flush_paragraph(); flush_list()
            story.append(Paragraph(inline_markup(line[3:]), styles["LiraH2"]))
        elif line.startswith("### "):
            flush_paragraph(); flush_list()
            story.append(Paragraph(inline_markup(line[4:]), styles["LiraH3"]))
        elif re.match(r"^[-*]\s+", line):
            flush_paragraph(); numbered.clear()
            bullets.append(re.sub(r"^[-*]\s+", "", line))
        elif re.match(r"^\d+[.)]\s+", line):
            flush_paragraph(); bullets.clear()
            numbered.append(re.sub(r"^\d+[.)]\s+", "", line))
        else:
            flush_list()
            paragraph.append(line)

    if in_code and code_lines:
        story.append(Preformatted("\n".join(code_lines), styles["LiraCode"]))
    flush_paragraph(); flush_list()
    doc.build(story)
    return buffer.getvalue()


@app.get("/health")
def health():
    return {"status": "ok", "service": "LIRA API"}


@app.get("/engine")
def engine_status():
    error = getattr(app.state, "engine_error", None)
    if error:
        return {"status": "error", "message": error}
    if engine.model is None:
        return {"status": "not_loaded"}
    return {"status": "available", "features_count": len(engine.feature_cols)}


@app.post("/detect")
async def detect(
    file: UploadFile = File(...),
    row_index: int = 0,
):
    if getattr(app.state, "engine_error", None):
        raise HTTPException(
            status_code=503,
            detail="The detection engine is not ready. Check LIRA_MODEL_PATH.",
        )

    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a CSV file.")

    try:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="The CSV file is empty.")
        if len(content) > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="CSV exceeds the 10 MB limit.")

        from io import BytesIO
        df = pd.read_csv(BytesIO(content), low_memory=False)

        if df.empty:
            raise HTTPException(status_code=400, detail="The CSV contains no rows.")
        if row_index < 0 or row_index >= len(df):
            raise HTTPException(status_code=400, detail="row_index is outside the CSV.")

        excluded = {
            "Label", "label", "class", "source_file", "Flow ID", "Timestamp"
        }
        row = df.iloc[row_index].drop(
            labels=[c for c in excluded if c in df.columns],
            errors="ignore",
        )

        detection = engine.lira_detect(row)
        return {
            "row_index": row_index,
            "rows_in_file": len(df),
            "columns_in_file": len(df.columns),
            "detection": detection,
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Detection failed: {type(exc).__name__}: {exc}",
        ) from exc
    finally:
        await file.close()


@app.post("/investigate")
async def investigate(
    file: UploadFile = File(...),
    row_index: int = 0,
):
    import uuid

    if getattr(app.state, "engine_error", None):
        raise HTTPException(
            status_code=503,
            detail="The detection engine is not ready.",
        )

    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a CSV file.")

    try:
        from io import BytesIO

        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="The CSV file is empty.")
        if len(content) > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="CSV exceeds the 10 MB limit.")

        df = pd.read_csv(BytesIO(content), low_memory=False)
        if df.empty:
            raise HTTPException(status_code=400, detail="The CSV contains no rows.")
        if row_index < 0 or row_index >= len(df):
            raise HTTPException(status_code=400, detail="Invalid row_index.")

        excluded = {
            "Label", "label", "class", "source_file", "Flow ID", "Timestamp"
        }
        row = df.iloc[row_index].drop(
            labels=[c for c in excluded if c in df.columns],
            errors="ignore",
        )

        detection = engine.lira_detect(row)
        investigation = engine.LIRAInvestigation(
            investigation_id=str(uuid.uuid4()),
            initial_detection=detection,
        )
        investigation.flow_features = row

        result = engine.lira_run_llm_investigation(
            investigation,
            verbose=False,
        )
        report = engine.lira_render_markdown_report(
            investigation,
            result,
            detection,
        )
        return {
            "investigation_id": investigation.investigation_id,
            "row_index": row_index,
            "detection": detection,
            "investigation": result,
            "report_markdown": report,
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Investigation failed: {type(exc).__name__}: {exc}",
        ) from exc
    finally:
        await file.close()


@app.post("/reports/pdf")
def download_report_pdf(payload: ReportPDFRequest):
    """Generate a PDF in memory and return it directly; no server-side file is stored."""
    if not payload.report_markdown.strip():
        raise HTTPException(status_code=400, detail="The report is empty.")

    try:
        pdf_bytes = _markdown_to_pdf(payload.report_markdown)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"PDF generation failed: {type(exc).__name__}: {exc}",
        ) from exc

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="LIRA_investigation_report.pdf"',
            "Cache-Control": "no-store",
        },
    )


from fastapi.staticfiles import StaticFiles

_frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
if os.path.isdir(_frontend_dir) and not any(
    getattr(route, "path", None) == "/frontend"
    for route in app.routes
):
    app.mount("/frontend", StaticFiles(directory=_frontend_dir), name="frontend")


@app.get("/", include_in_schema=False)
def frontend_home():
    return FileResponse(
        os.path.join(os.path.dirname(__file__), "frontend", "index.html")
    )
