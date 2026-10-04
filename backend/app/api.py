from __future__ import annotations

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app import __version__
from app.analysis import analyse
from app.models import AnalysisResult
from app.sample import generate

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB

app = FastAPI(
    title="loglens",
    version=__version__,
    description="Drop in a log file, get answers: patterns, anomalies, timeline.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyseRequest(BaseModel):
    text: str = Field(..., description="Raw log content")
    max_entries: int = Field(2000, ge=1, le=20_000)
    pattern_limit: int = Field(25, ge=1, le=200)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.post("/api/analyse", response_model=AnalysisResult)
def analyse_text(payload: AnalyseRequest) -> AnalysisResult:
    if not payload.text.strip():
        raise HTTPException(status_code=422, detail="No log content provided")
    return analyse(
        payload.text,
        max_entries=payload.max_entries,
        pattern_limit=payload.pattern_limit,
    )


@app.post("/api/upload", response_model=AnalysisResult)
async def analyse_upload(file: UploadFile = File(...)) -> AnalysisResult:
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (limit {MAX_UPLOAD_BYTES // 1024 // 1024} MB)",
        )
    if not content.strip():
        raise HTTPException(status_code=422, detail="Uploaded file is empty")
    return analyse(content.decode("utf-8", errors="replace"))


@app.get("/api/sample", response_model=AnalysisResult)
def analyse_sample(lines: int = 1200) -> AnalysisResult:
    lines = max(50, min(lines, 20_000))
    return analyse(generate(lines))


@app.get("/api/sample/raw")
def sample_raw(lines: int = 1200) -> dict:
    return {"text": generate(max(50, min(lines, 20_000)))}
