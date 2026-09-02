import asyncio
import os
import sys
import tempfile
import uuid

sys.path.insert(0, r"C:\Users\Dell Pc\talimbot")

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import configure_mappers

from backend import db

configure_mappers()
print("mappers configured OK")

tmp = os.path.join(tempfile.gettempdir(), f"tb_{uuid.uuid4().hex}.sqlite3")
db.engine = create_async_engine(f"sqlite+aiosqlite:///{tmp}")
db.AsyncSessionLocal = async_sessionmaker(db.engine, expire_on_commit=False)


async def main() -> None:
    await db.create_tables()
    async with db.AsyncSessionLocal() as session:
        user = db.User(email=f"t{uuid.uuid4().hex[:8]}@test.io", hashed_password="x", full_name="Test User")
        session.add(user)
        await session.commit()
        await session.refresh(user)
    assert user.created_at and user.is_active is True

    sid = f"sess-{uuid.uuid4().hex[:8]}"
    interview = await db.save_session_to_db(sid, user.id, "CV text", "JD text")
    assert interview.id and interview.started_at and interview.proctor_flags == [] and interview.is_complete is False

    n = await db.save_qa_pairs_to_db(
        sid,
        [
            {"domain": "Backend APIs", "question": "Q1", "answer": "A1", "turn_number": 1},
            {"domain": "Backend APIs", "question": "Q2", "answer": "A2", "turn_number": 2},
        ],
    )
    assert n == 2

    loaded = await db.get_session_from_db(sid)
    assert loaded is not None and loaded.session_id == sid and loaded.user_id == user.id

    async with db.AsyncSessionLocal() as session:
        rows = (await session.execute(db.select(db.QAPair).where(db.QAPair.interview_id == interview.id))).scalars().all()
        assert len(rows) == 2 and rows[0].turn_number == 1 and rows[1].question == "Q2"

    scores = {
        "domain_scores": {"Backend APIs": 8.0},
        "overall_score": 8.0,
        "hire_recommendation": "Strong hire",
        "strengths": ["s"],
        "improvements": ["i"],
        "summary": "Good.",
    }
    score = await db.save_scores_to_db(sid, scores)
    assert score.overall_score == 8.0 and score.hire_recommendation == "Strong hire"
    assert score.domain_scores == {"Backend APIs": 8.0}
    assert score.detailed_feedback["strengths"] == ["s"] and score.summary_feedback == "Good."
    assert score.evaluated_at is not None

    loaded = await db.get_session_from_db(sid)
    assert loaded.is_complete is True and loaded.ended_at is not None
    assert await db.get_session_from_db("missing-session") is None

    try:
        await db.save_qa_pairs_to_db("missing-session", [])
        raise AssertionError("expected ValueError")
    except ValueError:
        pass

    async for s in db.get_db():
        assert isinstance(s, db.AsyncSession)
    print("SQLITE LOGIC ROUNDTRIP PASSED")


asyncio.run(main())
os.remove(tmp)
