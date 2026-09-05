"""SQLAlchemy async ORM models and database helpers for TalimBot."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Optional

from dotenv import load_dotenv
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Uuid,
    insert,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set in .env")
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    interviews: Mapped[list["Interview"]] = relationship(back_populates="user")


class Interview(Base):
    __tablename__ = "interviews"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    cv_text: Mapped[str] = mapped_column(Text)
    jd_text: Mapped[str] = mapped_column(Text)
    domains: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    job_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    parent_interview_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("interviews.id", ondelete="SET NULL"), nullable=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    is_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    proctor_flags: Mapped[list] = mapped_column(JSON, default=list)

    user: Mapped["User"] = relationship(back_populates="interviews")
    qa_pairs: Mapped[list["QAPair"]] = relationship(back_populates="interview")
    score: Mapped[Optional["Score"]] = relationship(back_populates="interview", uselist=False)


class QAPair(Base):
    __tablename__ = "qa_pairs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    interview_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("interviews.id"))
    domain: Mapped[str] = mapped_column(String(255))
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    turn_number: Mapped[int] = mapped_column(Integer)
    asked_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    interview: Mapped["Interview"] = relationship(back_populates="qa_pairs")


class Score(Base):
    __tablename__ = "scores"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    interview_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("interviews.id"), unique=True)
    overall_score: Mapped[float] = mapped_column(Float)
    hire_recommendation: Mapped[str] = mapped_column(String(20))
    domain_scores: Mapped[dict] = mapped_column(JSON)
    summary_feedback: Mapped[str] = mapped_column(Text)
    detailed_feedback: Mapped[dict] = mapped_column(JSON)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    interview: Mapped["Interview"] = relationship(back_populates="score")


engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


def _as_uuid(value: Any) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


async def _get_interview(session: AsyncSession, session_id: str) -> Interview:
    interview = (
        await session.execute(select(Interview).where(Interview.session_id == session_id))
    ).scalar_one_or_none()
    if interview is None:
        raise ValueError(f"No interview found for session {session_id}")
    return interview


async def create_tables() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def save_session_to_db(
    session_id: str,
    user_id: Any,
    cv_text: str,
    jd_text: str,
    job_title: Optional[str] = None,
    parent_interview_id: Any = None,
) -> Interview:
    async with AsyncSessionLocal() as session:
        interview = Interview(
            session_id=session_id,
            user_id=_as_uuid(user_id),
            cv_text=cv_text,
            jd_text=jd_text,
            job_title=job_title,
            parent_interview_id=_as_uuid(parent_interview_id) if parent_interview_id else None,
        )
        session.add(interview)
        await session.commit()
        await session.refresh(interview)
        return interview


async def save_qa_pairs_to_db(session_id: str, qa_pairs: list[dict]) -> int:
    async with AsyncSessionLocal() as session:
        interview = await _get_interview(session, session_id)
        rows = [
            {
                "id": uuid.uuid4(),
                "interview_id": interview.id,
                "domain": pair.get("domain", ""),
                "question": pair.get("question", ""),
                "answer": pair.get("answer", ""),
                "turn_number": pair.get("turn_number", index + 1),
                "asked_at": _utcnow(),
            }
            for index, pair in enumerate(qa_pairs)
        ]
        if rows:
            await session.execute(insert(QAPair), rows)
            await session.commit()
        return len(rows)


async def save_scores_to_db(session_id: str, scores_dict: dict) -> Score:
    async with AsyncSessionLocal() as session:
        interview = await _get_interview(session, session_id)
        score = Score(
            interview_id=interview.id,
            overall_score=float(scores_dict.get("overall_score", 0.0)),
            hire_recommendation=str(scores_dict.get("hire_recommendation", ""))[:20],
            domain_scores=scores_dict.get("domain_scores") or {},
            summary_feedback=str(scores_dict.get("summary", "")),
            detailed_feedback=scores_dict,
        )
        interview.is_complete = True
        interview.ended_at = _utcnow()
        session.add(score)
        await session.commit()
        await session.refresh(score)
        return score


async def get_session_from_db(session_id: str) -> Optional[Interview]:
    async with AsyncSessionLocal() as session:
        return (
            await session.execute(select(Interview).where(Interview.session_id == session_id))
        ).scalar_one_or_none()
