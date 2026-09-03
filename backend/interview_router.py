"""Interview router: orchestrates the full voice interview pipeline per turn."""

import base64
import logging
import os
import uuid
from typing import Annotated, Optional

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth_router import get_current_user
from backend.db import (
    Interview,
    User,
    get_db,
    save_qa_pairs_to_db,
    save_scores_to_db,
    save_session_to_db,
)
from langgraph_engine.interview_graph import InterviewSession

logger = logging.getLogger("taleembot.interview")

router = APIRouter(prefix="/interview", tags=["interview"])

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")


class StartInterviewBody(BaseModel):
    candidate_name: str
    cv_text: str
    jd_text: str


class StartInterviewResponse(BaseModel):
    session_id: str
    question_text: str
    audio_base64: str


async def transcribe_audio(audio_bytes: bytes, filename: str) -> str:
    """Send audio to OpenAI Whisper API and return transcript text."""
    if not OPENAI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="OpenAI API key is not configured",
        )

    async with httpx.AsyncClient(timeout=30.0) as client:
        files = {
            "file": (filename, audio_bytes, "audio/webm"),
        }
        data = {
            "model": "whisper-1",
            "language": "en",
            "response_format": "text",
        }
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
        }
        response = await client.post(
            "https://api.openai.com/v1/audio/transcriptions",
            files=files,
            data=data,
            headers=headers,
        )

    if response.status_code != 200:
        logger.error("Whisper API error: %s — %s", response.status_code, response.text[:300])
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Whisper transcription failed: {response.status_code}",
        )

    return response.text.strip()


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
                "model_id": "eleven_monolingual_v1",
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

    result = session.start_interview(
        cv_text=body.cv_text,
        jd_text=body.jd_text,
        candidate_name=body.candidate_name,
    )

    if not result.get("question"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate opening question",
        )

    # Convert question to speech
    audio_bytes = await text_to_speech(result["question"])
    audio_base64 = base64.b64encode(audio_bytes).decode("ascii") if audio_bytes else ""

    # Persist to database
    await save_session_to_db(
        session_id=session_id,
        user_id=current_user.id,
        cv_text=body.cv_text,
        jd_text=body.jd_text,
    )

    logger.info(
        "Interview started: session=%s user=%s domain=%s",
        session_id, current_user.email, result.get("current_domain"),
    )

    return StartInterviewResponse(
        session_id=session_id,
        question_text=result["question"],
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

    # Transcribe via Whisper
    transcript = await transcribe_audio(audio_bytes, file.filename)
    logger.info("Transcript for session %s: %s", session_id, transcript[:100])

    # Run LangGraph turn
    session = InterviewSession(session_id=session_id)
    result = session.submit_answer(transcript)

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

        return {
            "done": True,
            "scores": result.get("scores"),
            "session_id": session_id,
        }

    # Not complete — convert next question to audio and stream back
    question_text = result.get("question", "")
    audio_bytes = await text_to_speech(question_text)

    headers = {
        "X-Question-Text": question_text,
        "X-Interview-Done": "false",
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
