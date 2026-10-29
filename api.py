import os
from contextlib import asynccontextmanager

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
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

from fastapi.staticfiles import StaticFiles

_frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
if os.path.isdir(_frontend_dir) and not any(
    getattr(route, "path", None) == "/frontend"
    for route in app.routes
):
    app.mount("/frontend", StaticFiles(directory=_frontend_dir), name="frontend")


from fastapi.responses import FileResponse

@app.get("/", include_in_schema=False)
def frontend_home():
    return FileResponse(
        os.path.join(os.path.dirname(__file__), "frontend", "index.html")
    )
