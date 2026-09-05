"""Interview router: orchestrates the full voice interview pipeline per turn."""

import asyncio
import base64
import logging
import os
import unicodedata
import uuid
from typing import Annotated, Optional

from deepgram import DeepgramClient, PrerecordedOptions
import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from backend.auth_router import get_current_user
from backend.db import (
    Interview,
    Score,
    User,
    get_db,
    save_qa_pairs_to_db,
    save_scores_to_db,
    save_session_to_db,
)
from langgraph_engine.interview_graph import INTRO_QUESTION, InterviewSession, extract_job_title

logger = logging.getLogger("talimbot.interview")

router = APIRouter(prefix="/interview", tags=["interview"])

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
TTS_MODEL = os.getenv("TTS_MODEL", "cosyvoice-v3-flash")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")


def sanitize_header(text: str) -> str:
    """Replace non-latin-1 characters so they can be safely sent in HTTP headers."""
    return unicodedata.normalize('NFKD', text).encode('latin-1', 'ignore').decode('latin-1')


class StartInterviewBody(BaseModel):
    candidate_name: str
    cv_text: str
    jd_text: str
    parent_interview_id: Optional[str] = None
    job_title: Optional[str] = None


class StartInterviewResponse(BaseModel):
    session_id: str
    question_text: str
    audio_base64: str


class TextAnswerBody(BaseModel):
    transcript: str


@router.post("/{session_id}/answer-text")
async def submit_answer_text(
    session_id: str,
    body: TextAnswerBody,
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Accept transcript text directly instead of audio. Fallback path for manual text entry."""
    transcript = body.transcript.strip()
    if not transcript:
        raise HTTPException(status_code=400, detail="Transcript cannot be empty")

    session = InterviewSession(session_id=session_id)
    result = await asyncio.to_thread(session.submit_answer, transcript)

    if result.get("interview_complete"):
        try:
            qa_pairs = session.graph.get_state(session.config).values.get("qa_pairs", [])
            await save_qa_pairs_to_db(session_id, qa_pairs)
            if result.get("scores"):
                await save_scores_to_db(session_id, result["scores"])
        except Exception as exc:
            logger.error("Failed to persist final results for session %s: %s", session_id, exc)
        return JSONResponse(
            content={"done": True, "scores": result.get("scores"), "session_id": session_id},
            headers={"X-Interview-Done": "true"},
        )

    question_text = result.get("question", "")
    audio_bytes = await text_to_speech(question_text)

    headers = {
        "X-Question-Text": sanitize_header(question_text),
        "X-Interview-Done": "false",
        "X-Current-Domain": sanitize_header(result.get("current_domain") or ""),
    }
    return Response(content=audio_bytes, media_type="audio/mpeg", headers=headers)


async def transcribe_audio(audio_bytes: bytes, mimetype: str = "audio/webm") -> str:
    """Transcribe audio via Deepgram Nova-3 and return transcript text."""
    if not DEEPGRAM_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Deepgram API key is not configured",
        )

    deepgram = DeepgramClient(DEEPGRAM_API_KEY)
    payload = {"buffer": audio_bytes, "mimetype": mimetype}
    options = PrerecordedOptions(
        model="nova-3",
        smart_format=True,
        punctuate=True,
        filler_words=False,
        utterances=False,
    )

    try:
        response = await deepgram.listen.asyncrest.v("1").transcribe_file(payload, options)
    except Exception as exc:
        logger.error("Deepgram ASR error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"ASR failed: {exc}",
        ) from exc

    transcript = response.results.channels[0].alternatives[0].transcript
    transcript = (transcript or "").strip()

    if not transcript:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No speech detected. Please try again.",
        )

    return transcript


# --- DASHSCOPE TTS CODE (commented out for quick revert) ---
# async def text_to_speech(text: str) -> bytes:
#     """Convert text to speech via DashScope TTS. Returns audio bytes."""
#     if not text:
#         return b""
#
#     if not DASHSCOPE_API_KEY or DASHSCOPE_API_KEY.startswith("your_"):
#         logger.warning("DashScope API key not configured; returning empty audio for dev mode")
#         return b""
#
#     dashscope.api_key = DASHSCOPE_API_KEY
#
#     try:
#         synthesizer = SpeechSynthesizer(model=TTS_MODEL, voice="longxiaochun")
#         audio = synthesizer.call(text)
#
#         if audio is None:
#             raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="TTS returned no audio")
#
#         return bytes(audio)
#     except Exception as exc:
#         err_str = str(exc).lower()
#         # Invalid/expired key or connection refused — silently fall back to dev mode
#         if any(kw in err_str for kw in ["invalid", "401", "unauthorized", "connection is already closed"]):
#             logger.warning("DashScope TTS auth/connection error; returning empty audio for dev mode")
#             return b""
#         logger.error("DashScope TTS error: %s", exc)
#         raise HTTPException(
#             status_code=status.HTTP_502_BAD_GATEWAY,
#             detail=f"TTS failed: {exc}",
#         ) from exc


async def text_to_speech(text: str) -> bytes:
    """Convert text to speech via ElevenLabs. Returns MP3 bytes."""
    if not ELEVENLABS_API_KEY or ELEVENLABS_API_KEY.startswith("your_"):
        logger.warning("ElevenLabs API key not configured; returning empty audio for dev mode")
        return b""

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            url,
            json={
                "text": text,
                "model_id": "eleven_flash_v2_5",
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.75,
                },
            },
            headers={
                "xi-api-key": ELEVENLABS_API_KEY,
                "Content-Type": "application/json",
            },
        )

    if response.status_code == 401:
        # Invalid/expired key — silently fall back to dev mode instead of crashing
        logger.warning("ElevenLabs returned 401 (invalid key); returning empty audio for dev mode")
        return b""

    if response.status_code != 200:
        logger.error("ElevenLabs API error: %s — %s", response.status_code, response.text[:300])
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"ElevenLabs TTS failed: {response.status_code}",
        )

    return response.content


async def _resolve_parent_interview(db: AsyncSession, value: str, user_id) -> uuid.UUID:
    """Resolve a parent attempt to an interviews.id.

    The frontend only has session_id in sessionStorage, so accept either that or a
    row id. Scoped to the caller so a session can't be linked to someone else's interview.
    """
    try:
        candidate_id: Optional[uuid.UUID] = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        candidate_id = None

    if candidate_id is not None:
        found = (
            await db.execute(
                select(Interview.id).where(Interview.id == candidate_id, Interview.user_id == user_id)
            )
        ).scalar_one_or_none()
        if found is not None:
            return found

    found = (
        await db.execute(
            select(Interview.id).where(Interview.session_id == value, Interview.user_id == user_id)
        )
    ).scalar_one_or_none()
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parent interview not found")
    return found


@router.post("/start", response_model=StartInterviewResponse)
async def start_interview(
    body: StartInterviewBody,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Start a new interview session. Creates UUID, runs domain extraction + first question,
    converts question to audio, saves to DB, returns everything in one response."""
    session_id = str(uuid.uuid4())
    session = InterviewSession(session_id=session_id)

    # Resolve the parent link first so a bad id fails before spending LLM + TTS calls
    parent_id = None
    if body.parent_interview_id:
        parent_id = await _resolve_parent_interview(db, body.parent_interview_id, current_user.id)

    # The intro question is hardcoded and the job title only needs the JD, so neither
    # depends on the graph — run all three concurrently. to_thread keeps the sync
    # LangGraph and LLM calls off the event loop.
    result, intro_audio, extracted_title = await asyncio.gather(
        asyncio.to_thread(
            session.start_interview,
            cv_text=body.cv_text,
            jd_text=body.jd_text,
            candidate_name=body.candidate_name,
        ),
        text_to_speech(INTRO_QUESTION),
        asyncio.to_thread(extract_job_title, body.jd_text),
    )

    question = result.get("question") or ""
    if not question:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate opening question",
        )

    # New sessions always get the hardcoded intro → reuse the parallel audio.
    # A resumed checkpoint may hold a domain question → synthesize that instead.
    audio_bytes = intro_audio if question == INTRO_QUESTION else await text_to_speech(question)
    audio_base64 = base64.b64encode(audio_bytes).decode("ascii") if audio_bytes else ""

    job_title = (body.job_title or "").strip() or extracted_title

    # Persist to database (after all gather results are ready)
    await save_session_to_db(
        session_id=session_id,
        user_id=current_user.id,
        cv_text=body.cv_text,
        jd_text=body.jd_text,
        job_title=job_title,
        parent_interview_id=parent_id,
    )

    logger.info(
        "Interview started: session=%s user=%s domain=%s",
        session_id, current_user.email, result.get("current_domain"),
    )

    return StartInterviewResponse(
        session_id=session_id,
        question_text=question,
        audio_base64=audio_base64,
    )


@router.post("/{session_id}/answer")
async def submit_answer(
    session_id: str,
    file: UploadFile = File(...),
    current_user: Annotated[User, Depends(get_current_user)] = None,
):
    """Receive candidate's spoken answer, transcribe it, run LangGraph turn,
    generate next question audio, and stream back."""
    # Validate file type
    if not file.filename or not file.filename.lower().endswith(".webm"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .webm audio files are accepted",
        )

    audio_bytes = await file.read()

    # Transcribe via Deepgram Nova-3
    transcript = await transcribe_audio(audio_bytes, file.content_type or "audio/webm")
    logger.info("Transcript for session %s: %s", session_id, transcript[:100])

    # Run LangGraph turn (blocking LLM calls → keep them off the event loop)
    session = InterviewSession(session_id=session_id)
    result = await asyncio.to_thread(session.submit_answer, transcript)

    # If interview is complete, persist scores and Q&A pairs, return final result
    if result.get("interview_complete"):
        try:
            qa_pairs = session.graph.get_state(session.config).values.get("qa_pairs", [])
            await save_qa_pairs_to_db(session_id, qa_pairs)
            if result.get("scores"):
                await save_scores_to_db(session_id, result["scores"])
            logger.info("Interview completed: session=%s score=%.1f",
                         session_id, result.get("scores", {}).get("overall_score"))
        except Exception as exc:
            logger.error("Failed to persist final results for session %s: %s",
                          session_id, exc)

        return JSONResponse(
            content={
                "done": True,
                "scores": result.get("scores"),
                "session_id": session_id,
            },
            headers={"X-Interview-Done": "true"},
        )

    # Not complete — convert next question to audio and stream back
    question_text = result.get("question", "")
    audio_bytes = await text_to_speech(question_text)

    headers = {
        "X-Question-Text": sanitize_header(question_text),
        "X-Interview-Done": "false",
        "X-Current-Domain": sanitize_header(result.get("current_domain") or ""),
    }

    return Response(
        content=audio_bytes,
        media_type="audio/mpeg",
        headers=headers,
    )


@router.get("/{session_id}/status")
async def get_interview_status(
    session_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Return current session state from the LangGraph checkpoint."""
    session = InterviewSession(session_id=session_id)
    return session.get_status()


@router.get("/history")
async def get_interview_history(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return list of past interviews for the current user."""
    result = await db.execute(
        select(Interview)
        .where(Interview.user_id == current_user.id)
        .order_by(Interview.started_at.desc())
    )
    interviews = result.scalars().all()

    return [
        {
            "id": str(iv.id),
            "session_id": iv.session_id,
            "started_at": iv.started_at.isoformat() if iv.started_at else None,
            "ended_at": iv.ended_at.isoformat() if iv.ended_at else None,
            "is_complete": iv.is_complete,
            "domains": iv.domains,
        }
        for iv in interviews
    ]


# --------------------------------------------------------------- history router
# Separate prefix: client.js calls /interviews/*, this file's router is /interview/*.
history_router = APIRouter(prefix="/interviews", tags=["interviews"])

# hire_recommendation is internal scoring language; the UI speaks readiness levels.
READINESS_LABELS = {
    "Strong hire": "Interview Ready",
    "Hire": "Almost Ready",
    "Lean hire": "Getting There",
    "No hire": "Needs Practice",
}


def _readiness(recommendation: Optional[str]) -> str:
    return READINESS_LABELS.get(recommendation or "", "Practice Complete")


@history_router.get("/history")
async def get_history(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Last 20 interviews for the caller, each with its score and its parent attempt's score."""
    parent = aliased(Interview)
    parent_score = aliased(Score)

    rows = (
        await db.execute(
            select(
                Interview.id,
                Interview.session_id,
                Interview.job_title,
                Interview.started_at,
                Interview.is_complete,
                Interview.parent_interview_id,
                Score.overall_score,
                Score.hire_recommendation,
                parent_score.overall_score.label("parent_score"),
            )
            .outerjoin(Score, Score.interview_id == Interview.id)
            .outerjoin(parent, parent.id == Interview.parent_interview_id)
            .outerjoin(parent_score, parent_score.interview_id == parent.id)
            .where(Interview.user_id == current_user.id)
            .order_by(Interview.started_at.desc())
            .limit(20)
        )
    ).all()

    return [
        {
            "id": str(row.id),
            "session_id": row.session_id,
            "job_title": row.job_title or "Practice Interview",
            "overall_score": row.overall_score,
            "hire_recommendation": row.hire_recommendation,
            "readiness": _readiness(row.hire_recommendation),
            "is_complete": row.is_complete,
            # interviews has no created_at column; started_at is the equivalent
            "created_at": row.started_at.isoformat() if row.started_at else None,
            "parent_interview_id": str(row.parent_interview_id) if row.parent_interview_id else None,
            "parent_score": row.parent_score,
        }
        for row in rows
    ]


@history_router.get("/{interview_id}/feedback")
async def get_feedback(
    interview_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Full scores JSON for one interview, in the shape FeedbackPage already renders."""
    try:
        row_id = uuid.UUID(interview_id)
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found")

    interview = (
        await db.execute(
            select(Interview).where(Interview.id == row_id, Interview.user_id == current_user.id)
        )
    ).scalar_one_or_none()
    if interview is None:
        # 404, not 403 — don't confirm that another user's interview exists
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found")

    score = (
        await db.execute(select(Score).where(Score.interview_id == interview.id))
    ).scalar_one_or_none()
    if score is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No feedback recorded for this interview yet",
        )

    detailed = score.detailed_feedback or {}
    return {
        "id": str(interview.id),
        "session_id": interview.session_id,
        "job_title": interview.job_title or "Practice Interview",
        "created_at": interview.started_at.isoformat() if interview.started_at else None,
        "overall_score": score.overall_score,
        "hire_recommendation": score.hire_recommendation,
        "readiness": _readiness(score.hire_recommendation),
        "domain_scores": score.domain_scores or {},
        "summary_feedback": score.summary_feedback,
        "summary": score.summary_feedback,
        "strengths": detailed.get("strengths") or [],
        "improvements": detailed.get("improvements") or [],
        "detailed_feedback": detailed,
    }
