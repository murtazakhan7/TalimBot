"""Document parser router: extract clean text from CV and JD uploads."""

import re
from io import BytesIO

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

router = APIRouter(prefix="/docs", tags=["docs"])

MAX_CV_SIZE = 5 * 1024 * 1024   # 5 MB
MAX_JD_SIZE = 5 * 1024 * 1024   # 5 MB


def _clean_text(raw: str) -> str:
    """Collapse excessive whitespace and strip leading/trailing blank lines."""
    raw = re.sub(r"\r\n?", "\n", raw)
    raw = re.sub(r"\n{3,}", "\n\n", raw)
    return raw.strip()


class ParseResult(BaseModel):
    text: str
    page_count: int
    char_count: int


class TextBody(BaseModel):
    text: str


@router.post("/parse-cv", response_model=ParseResult)
async def parse_cv(file: UploadFile = File(...)):
    """Extract clean text from an uploaded CV PDF."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    contents = await file.read()
    if len(contents) > MAX_CV_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"CV file too large (max {MAX_CV_SIZE // (1024*1024)} MB)",
        )

    try:
        import pdfplumber
    except ImportError:
        raise HTTPException(status_code=500, detail="pdfplumber is not installed")

    with pdfplumber.open(BytesIO(contents)) as pdf:
        pages = pdf.pages
        text_parts = [page.extract_text() or "" for page in pages]

    raw_text = "\n".join(text_parts)
    cleaned = _clean_text(raw_text)

    if len(cleaned) < 100:
        raise HTTPException(
            status_code=422,
            detail="Extracted text is too short (< 100 chars). "
                   "The PDF may be a scanned image without selectable text.",
        )

    return ParseResult(
        text=cleaned,
        page_count=len(pages),
        char_count=len(cleaned),
    )


@router.post("/parse-jd", response_model=ParseResult)
async def parse_jd(file: UploadFile = File(...)):
    """Extract clean text from an uploaded job description PDF."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    contents = await file.read()
    if len(contents) > MAX_JD_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"JD file too large (max {MAX_JD_SIZE // (1024*1024)} MB)",
        )

    try:
        import pdfplumber
    except ImportError:
        raise HTTPException(status_code=500, detail="pdfplumber is not installed")

    with pdfplumber.open(BytesIO(contents)) as pdf:
        pages = pdf.pages
        text_parts = [page.extract_text() or "" for page in pages]

    raw_text = "\n".join(text_parts)
    cleaned = _clean_text(raw_text)

    if len(cleaned) < 50:
        raise HTTPException(
            status_code=422,
            detail="Extracted text is too short (< 50 chars). "
                   "The PDF may be a scanned image without selectable text.",
        )

    return ParseResult(
        text=cleaned,
        page_count=len(pages),
        char_count=len(cleaned),
    )


@router.post("/parse-jd-text", response_model=ParseResult)
async def parse_jd_text(body: TextBody):
    """Accept plain-text JD pasted directly by the candidate."""
    cleaned = _clean_text(body.text)

    if len(cleaned) < 50:
        raise HTTPException(
            status_code=400,
            detail="JD text is too short (< 50 characters)",
        )

    return ParseResult(
        text=cleaned,
        page_count=1,
        char_count=len(cleaned),
    )
