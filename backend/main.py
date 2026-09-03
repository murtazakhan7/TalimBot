"""TaleemBot FastAPI application entry point."""

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.auth_router import router as auth_router
from backend.db import create_tables
from backend.doc_parser_router import router as doc_parser_router
from backend.interview_router import router as interview_router
from backend.proctor_router import router as proctor_router

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create database tables on startup."""
    await create_tables()
    yield


app = FastAPI(
    title="TaleemBot API",
    description="AI-powered structured voice interview platform",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware for React frontend development servers
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Question-Text", "X-Interview-Done"],
)

# Register routers
app.include_router(auth_router)
app.include_router(interview_router)
app.include_router(doc_parser_router)
app.include_router(proctor_router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "TaleemBot API"}
