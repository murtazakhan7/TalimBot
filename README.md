# 🎙️ TalimBot: AI-Powered Interview Coach & Hiring Assistant for Pakistan

> **Alibaba Cloud AI Hackathon Submission**
> Practice for real interviews with a voice-based AI interviewer, tailored to your CV and target role.

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Environment Variables](#environment-variables)
  - [Backend Setup](#backend-setup)
  - [Frontend Setup](#frontend-setup)
- [API Reference](#api-reference)
- [Database Schema](#database-schema)
- [How It Works](#how-it-works)
- [Screenshots](#screenshots)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)

---

## Overview

TalimBot is a full-stack AI interview coaching platform built specifically for job seekers in Pakistan. Candidates upload their CV and a job description, and TalimBot conducts a structured, voice-based mock interview powered by large language models — asking relevant questions domain by domain, listening to spoken answers, and delivering detailed scoring and coaching feedback at the end.

The goal is to democratise interview preparation: anyone with a browser and a microphone can practice as many times as they need, get real-time feedback, and track their improvement over time.

---

## Features

- **Voice-based interview flow** — the AI speaks each question aloud (ElevenLabs TTS) and listens to the candidate's spoken response (Deepgram STT).
- **CV & JD-aware questions** — questions are dynamically generated from the candidate's own CV and the target job description, covering relevant skill domains.
- **Structured 5-question sessions** — each session covers multiple domains (e.g. technical skills, behavioural, communication) with one question per domain.
- **Real-time typewriter effect** — questions are rendered word-by-word as audio plays, giving a natural interviewer feel.
- **Rephrase & skip** — candidates can ask for a rephrased version of a question, or skip to the next one.
- **Anti-cheat proctoring** — tab-switch events are silently logged per session without interrupting the interview.
- **Detailed feedback report** — overall score (out of 10), domain-by-domain breakdown with reasoning, strengths, improvement areas, and interview tips.
- **Practice Again** — restart a new session on the same role with one click; improvement delta vs. previous attempt is shown.
- **Interview history** — browse all past sessions, scores, and timestamps from the dashboard.
- **JWT authentication** — secure registration, login, and protected routes throughout.

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Frontend** | React (Vite), React Router, inline styles |
| **Backend** | FastAPI (Python), async SQLAlchemy, Pydantic |
| **LLM** | `gpt-oss-120b` via [Groq](https://groq.com) |
| **Text-to-Speech** | [ElevenLabs](https://elevenlabs.io) |
| **Speech-to-Text** | [Deepgram](https://deepgram.com) |
| **Orchestration** | LangGraph (stateful interview graph) |
| **Database** | PostgreSQL (async via `asyncpg`) |
| **Auth** | JWT (HS256) via `python-jose`, bcrypt via `passlib` |
| **PDF Parsing** | `pdfplumber` |
| **Hosting** | Alibaba Cloud |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        React Frontend                           │
│  LoginPage → DashboardPage → UploadPage → InterviewPage        │
│                          → FeedbackPage → HistoryPage          │
└──────────────────────────┬──────────────────────────────────────┘
                           │ REST / HTTP (JSON + binary audio)
┌──────────────────────────▼──────────────────────────────────────┐
│                      FastAPI Backend                            │
│                                                                 │
│  /auth      AuthRouter      (register, login, JWT, /me)        │
│  /docs      DocParserRouter (parse CV/JD PDFs or plain text)   │
│  /interview InterviewRouter (start, answer, skip, paraphrase)  │
│  /proctor   ProctorRouter   (anti-cheat event logging)         │
└────────────┬─────────────────────┬───────────────┬─────────────┘
             │                     │               │
    ┌────────▼──────┐   ┌──────────▼─────┐  ┌─────▼──────┐
    │ LangGraph     │   │  ElevenLabs    │  │ Deepgram   │
    │ Interview     │   │  TTS API       │  │ STT API    │
    │ Graph (LLM)   │   └────────────────┘  └────────────┘
    │ (Groq/GPT)    │
    └────────┬──────┘
             │
    ┌────────▼──────┐
    │  PostgreSQL   │
    │  (users,      │
    │  interviews,  │
    │  qa_pairs,    │
    │  scores)      │
    └───────────────┘
```

The interview is orchestrated as a **LangGraph stateful graph** (`interview_graph.py`). Each node in the graph handles a discrete step, question generation, answer evaluation, domain routing, and final scoring, making the flow easy to extend and test.

---

## Project Structure

```
talimbot/
├── backend/
│   ├── main.py                  # FastAPI app entry point, CORS, lifespan
│   ├── auth_router.py           # /auth — register, login, JWT, /me
│   ├── interview_router.py      # /interview — start, answer, skip, paraphrase, history
│   ├── doc_parser_router.py     # /docs — parse CV/JD from PDF or plain text
│   ├── proctor_router.py        # /proctor — anti-cheat event logging
│   └── db.py                    # SQLAlchemy ORM models & async DB helpers
│
├── langgraph_engine/
│   └── interview_graph.py       # LangGraph interview state machine
│
├── frontend/
│   └── src/
│       ├── api/
│       │   └── client.js        # Axios API client (all backend calls)
│       ├── components/
│       │   └── Logo.jsx
│       ├── hooks/
│       │   └── useVoiceRecorder.js  # MediaRecorder + Deepgram STT + answer submission
│       └── pages/
│           ├── LoginPage.jsx
│           ├── DashboardPage.jsx
│           ├── UploadPage.jsx
│           ├── InterviewPage.jsx
│           ├── FeedbackPage.jsx
│           └── HistoryPage.jsx
│
├── .env                         # Environment variables (not committed)
├── requirements.txt
└── README.md
```

---

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+
- PostgreSQL 14+
- API keys for: Groq, ElevenLabs, Deepgram

### Environment Variables

Create a `.env` file in the project root:

```env
# Database
DATABASE_URL=postgresql://user:password@localhost:5432/talimbot

# Auth
SECRET_KEY=your-very-secret-key-change-in-production

# LLM (Groq)
GROQ_API_KEY=your_groq_api_key

# Text-to-Speech
ELEVENLABS_API_KEY=your_elevenlabs_api_key
ELEVENLABS_VOICE_ID=your_chosen_voice_id

# Speech-to-Text
DEEPGRAM_API_KEY=your_deepgram_api_key
```

### Backend Setup

```bash
# 1. Clone the repo
git clone https://github.com/your-username/talimbot.git
cd talimbot

# 2. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up your .env file (see above)

# 5. Start the server (tables are created automatically on first run)
uvicorn backend.main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`. Interactive docs are at `http://localhost:8000/docs`.

### Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Start the dev server
npm run dev
```

The frontend will be available at `http://localhost:5173`.

---

## API Reference

### Auth — `/auth`

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/auth/register` | Register a new user (`email`, `password`, `full_name`) |
| `POST` | `/auth/login` | Login and receive a JWT (`username` = email, `password`) |
| `GET` | `/auth/me` | Get current user's name and email (requires JWT) |

### Documents — `/docs`

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/docs/parse-cv` | Upload a CV PDF → returns extracted text |
| `POST` | `/docs/parse-jd` | Upload a JD PDF → returns extracted text |
| `POST` | `/docs/parse-jd-text` | Submit raw JD text → returns cleaned text |

### Interview — `/interview`

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/interview/start` | Start a session; returns first question text + audio (base64) |
| `POST` | `/interview/{session_id}/answer` | Submit recorded audio answer; returns next question audio or final scores |
| `POST` | `/interview/{session_id}/skip` | Skip current question and get the next one |
| `POST` | `/interview/{session_id}/paraphrase` | Get a rephrased version of the current question |
| `POST` | `/interview/{session_id}/restart` | Create a linked follow-up session on the same role |
| `GET` | `/interview/history` | List all past sessions for the current user |
| `GET` | `/interview/{session_id}/result` | Fetch full results for a completed session |

### Proctor — `/proctor`

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/proctor/{session_id}/event` | Log an anti-cheat event (`tab_switch`, `tab_returned`, etc.) |

All protected endpoints require the header: `Authorization: Bearer <token>`

Response audio is returned as binary `audio/mpeg`. The question text and domain are passed back via custom response headers (`X-Question-Text`, `X-Current-Domain`, `X-Interview-Done`).

---

## Database Schema

```
users
  id (UUID PK) | email | hashed_password | full_name | created_at | is_active

interviews
  id (UUID PK) | session_id | user_id (FK) | cv_text | jd_text
  domains (JSON) | job_title | parent_interview_id (FK, self-referential)
  started_at | ended_at | is_complete | proctor_flags (JSON)

qa_pairs
  id (UUID PK) | interview_id (FK) | domain | question | answer
  turn_number | asked_at

scores
  id (UUID PK) | interview_id (FK, unique) | overall_score | hire_recommendation
  domain_scores (JSON) | summary_feedback | detailed_feedback (JSON) | evaluated_at
```

The self-referential `parent_interview_id` on `interviews` lets the system track improvement across multiple "Practice Again" sessions on the same role.

---

## How It Works

**1. Setup**
The candidate uploads their CV (PDF) and a job description (PDF or pasted text). Both are parsed into clean text on the backend.

**2. Session Start**
`POST /interview/start` passes the CV and JD text to the LangGraph interview graph. The graph uses the LLM (GPT-oss-120b via Groq) to identify relevant skill domains and generate the opening question. ElevenLabs converts the question to speech; the audio and question text are returned to the client.

**3. Interview Loop**
For each turn:
- The question audio plays in the browser; the typewriter effect renders the text in sync.
- The candidate clicks the mic, records their answer (up to 2 minutes), and clicks Stop.
- The audio blob is sent to `POST /interview/{session_id}/answer`.
- The backend transcribes the audio with Deepgram, feeds the transcript + context to the LangGraph node, which generates the next question (or triggers final scoring on turn 5).
- The next question audio + text are returned; the loop repeats.

**4. Scoring**
After the fifth answer, the LangGraph scoring node prompts the LLM to evaluate all five Q&A pairs against the job description and CV. It returns a structured JSON report with an overall score, per-domain scores with reasoning, strengths, improvement areas, and interview tips.

**5. Feedback**
The FeedbackPage renders the full report. The candidate can copy a summary to the clipboard or click "Practice Again" to kick off a new linked session — which will display the score delta on completion.

---

## Roadmap

- [ ] Recruiter-side portal: post roles, receive scored candidate reports
- [ ] Urdu language support (STT + TTS)
- [ ] Video proctoring with webcam (face detection, eye tracking)
- [ ] Premium tier: unlimited sessions, advanced analytics, personalised coaching plans
- [ ] Mobile app (React Native)
- [ ] Leaderboard / community benchmarking by role and industry

---

## Contributing

Pull requests are welcome. For major changes please open an issue first to discuss what you'd like to change.

```bash
# Run backend tests
pytest

# Lint & format
ruff check backend/
black backend/
```

---

## License

MIT © 2026 TalimBot — Built for the Alibaba Cloud AI Hackathon 🇵🇰
