"""Proctor router: log anti-cheat events against active interview sessions."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from backend.auth_router import get_current_user
from backend.db import User
from langgraph_engine.interview_graph import InterviewSession

logger = logging.getLogger("talimbot.proctor")

router = APIRouter(prefix="/proctor", tags=["proctor"])


class ProctorEvent(BaseModel):
    event_type: str
    timestamp_seconds: float


@router.post("/{session_id}/event", status_code=status.HTTP_204_NO_CONTENT)
async def log_proctor_event(
    session_id: str,
    event: ProctorEvent,
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Log an anti-cheat event against the given interview session.

    Silently fails on storage errors so proctoring never interrupts the interview.
    """
    try:
        flag = f"{event.event_type}_at_{event.timestamp_seconds}s"
        session = InterviewSession(session_id=session_id)
        session.add_proctor_flag(flag)
        logger.info("Proctor event logged: session=%s user=%s flag=%s",
                     session_id, current_user.email, flag)
    except Exception as exc:
        # Silent fail — proctoring must never interrupt the interview flow
        logger.warning("Failed to log proctor event for session %s: %s",
                       session_id, exc)
