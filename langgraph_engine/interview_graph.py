"""TalimBot LangGraph interview engine.

Stateful directed graph with five nodes (domain_extractor, question_generator,
answer_recorder, coverage_tracker, evaluator) that enforces fair coverage of
every skill domain extracted from the job description.

The graph is compiled with ``interrupt_after=["question_generator"]`` so that a
single ``invoke()`` produces exactly one question to be spoken to the candidate:

* ``start_interview`` -> domain_extractor -> question_generator -> INTERRUPT
* ``submit_answer``   -> answer_recorder -> coverage_tracker ->
                         question_generator -> INTERRUPT   (or evaluator -> END)

PostgresSaver checkpoints state after every node execution, so a candidate who
disconnects mid-interview resumes from exactly the turn they left.
"""

from __future__ import annotations

import json
import logging
import operator
import os
from typing import Annotated, Any, Optional, TypedDict

from dotenv import load_dotenv
# from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langchain_openai import ChatOpenAI
import dashscope

try:
    from langgraph.checkpoint.postgres import PostgresSaver
except ModuleNotFoundError:  # langgraph-checkpoint-postgres not installed yet
    PostgresSaver = None

load_dotenv()

logger = logging.getLogger("talimbot.interview_graph")

MAX_QUESTIONS = 5
INTRO_QUESTION = (
    "To get us started, could you please introduce yourself and tell me a bit about "
    "your background?"
)
DEFAULT_DOMAINS = [
    "Technical Expertise",
    "Problem Solving",
]

_EXTRACTOR_SYSTEM = (
    "You are the domain-extraction stage of TalimBot, an AI interview engine. "
    "Read the job description and the candidate's CV, then identify exactly 2 core "
    "skill domains the company actually cares about for this role. Return ONLY a "
    "JSON array of 2 short domain names (2-5 words each), e.g. "
    '["Backend APIs", "React Frontend"]. '
    "No prose, no markdown."
)

_CV_SUMMARY_SYSTEM = """You are a recruitment assistant. Compress the provided CV into a concise 150-word candidate profile covering:
- Total years of experience (or student/fresh graduate status)
- Core technical skills and stacks
- Notable projects or achievements (with specifics if present)
- Most recent role or current status

Be factual. Only include what is explicitly stated. Do not infer or embellish."""

_QUESTION_SYSTEM = (
    "You are TalimBot, a senior interviewer conducting a structured voice interview. "
    "Ask exactly ONE question per turn. The question is spoken aloud by a TTS voice, "
    "so keep it conversational, natural and under 60 words. Never reveal scoring, "
    "domains covered, or that you are an AI state machine. Output only the question "
    "text, no preamble, no quotes. "
    "Format questions for spoken audio: spell out all abbreviations and symbols as "
    "words (say \"and\" not \"&\", \"Kubernetes\" not \"k8s\", \"React\" not \"ReactJS\", "
    "\"versus\" not \"vs\", \"for example\" not \"e.g.\"). Never use bullet points, "
    "slashes, parentheses, or special characters. Write as natural speech."
)

_EVALUATOR_SYSTEM = """You are a fair and calibrated interview evaluator assessing a candidate who is a fresh graduate or early-career professional practicing for entry-level to mid-level roles. Score accordingly — do not apply a senior engineer standard.

Evaluate based on:
- Did they actually answer the question asked? (relevance)
- Do they demonstrate genuine understanding of the concept, not just buzzwords?
- Can they support their answer with a specific example, project, or experience?
- Can they communicate clearly and coherently?

Do NOT penalize for:
- Not using any framework (STAR, SOAR, etc.) — frameworks are never required
- Conversational speech patterns, filler words, or mid-sentence rephrasing — this is spoken audio transcribed, not written text
- Using plain language instead of technical jargon, as long as the understanding is correct
- Incomplete answers that show the right thinking — reward direction of understanding, not perfection
- Pausing, repeating, or self-correcting — these are normal in speech

For each domain, also return:
- expected_highlights: 2-3 things a strong answer to this domain's questions should have demonstrated (concept-based, not framework-based — e.g. "awareness of tradeoffs", "a specific project example", "understanding of why not just what")
- question_notes: a one-line note per question on what the candidate's answer did well or missed specifically

Return a JSON object with this exact structure:
{
  "overall_score": <float 1-10>,
  "domain_scores": {
    "<domain_name>": {
      "score": <float 1-10>,
      "reasoning": "<2-3 sentences>",
      "strength": "<one thing they did well>",
      "gap": "<one thing to improve>",
      "expected_highlights": ["<highlight 1>", "<highlight 2>", "<highlight 3>"],
      "question_notes": ["<note on Q1 in this domain>", "<note on Q2 in this domain>"]
    }
  },
  "summary_feedback": "<3-4 sentences overall>",
  "detailed_feedback": {
    "strengths": ["<strength 1>", "<strength 2>", "<strength 3>"],
    "improvements": ["<improvement 1>", "<improvement 2>", "<improvement 3>"],
    "interview_tips": ["<tip 1>", "<tip 2>", "<tip 3>"]
  },
  "hire_recommendation": "<Strong hire | Hire | Lean hire | No hire>"
}"""


class InterviewState(TypedDict, total=False):
    domains: list[str]
    current_domain_index: int
    domains_covered: Annotated[list[str], operator.add]
    follow_up_count: int
    current_question: str
    current_answer: str
    qa_pairs: Annotated[list[dict], operator.add]
    proctor_flags: Annotated[list[str], operator.add]
    scores: Optional[dict]
    interview_complete: bool
    cv_text: str
    cv_summary: str
    jd_text: str
    candidate_name: str
    session_id: str


# --------------------------------------------------------------------------- LLM

_model: Optional[ChatOpenAI] = None

dashscope.base_http_api_url = os.getenv("DASHSCOPE_API_URL", "")
dashscope.base_websocket_api_url = os.getenv("DASHSCOPE_WS_URL", "")


from langchain_openai import ChatOpenAI

def get_llm():
    global _model
    if _model is None:
        _model = ChatOpenAI(
            model=os.getenv("QWEN_MODEL", "qwen3.7-plus"),
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            base_url=os.getenv("DASHSCOPE_BASE_URL"),
        )
    return _model


def _ask_llm(system: str, human: str, temperature: float = 0.7) -> str:
    response = get_llm().bind(temperature=temperature).invoke(
        [SystemMessage(content=system), HumanMessage(content=human)]
    )
    return response.content if isinstance(response.content, str) else str(response.content)


def _extract_json(text: str, opener: str) -> Any:
    """Pull the first balanced JSON array/object out of an LLM reply."""
    closer = "]" if opener == "[" else "}"
    for i, ch in enumerate(text):
        if ch != opener:
            continue
        depth = 0
        in_str = False
        escaped = False
        for j in range(i, len(text)):
            c = text[j]
            if in_str:
                if escaped:
                    escaped = False
                elif c == "\\":
                    escaped = True
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == opener:
                depth += 1
            elif c == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[i : j + 1])
                    except json.JSONDecodeError:
                        break
    return None


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "\n[...truncated]"


def _summarize_cv(cv_text: str) -> str:
    # Spec showed async, but all graph nodes run via sync graph.invoke()
    return _ask_llm(_CV_SUMMARY_SYSTEM, cv_text[:8000], temperature=0.1).strip()


_JOB_TITLE_SYSTEM = (
    "Extract only the job title from this job description. Return just the title, "
    "nothing else. If unclear, return 'Software Engineer'."
)


def extract_job_title(jd_text: str) -> str:
    """Sync like every other graph-side LLM call; never blocks interview start."""
    try:
        title = _ask_llm(_JOB_TITLE_SYSTEM, (jd_text or "")[:2000], temperature=0.1)
        title = title.strip().strip('"').strip("'").strip()
    except Exception as exc:
        logger.warning("Job title extraction failed (%s); using default", exc)
        title = ""
    return (title or "Software Engineer")[:255]


_PARAPHRASE_SYSTEM = (
    "Rephrase this interview question in simpler, clearer language. Keep the same "
    "topic. Return only the rephrased question, nothing else."
)


def rephrase_question(question_text: str) -> str:
    """Simpler wording for the question already asked; does not consume a graph turn."""
    rephrased = _ask_llm(_PARAPHRASE_SYSTEM, question_text, temperature=0.7)
    return rephrased.strip().strip('"').strip()


# -------------------------------------------------------------------------- nodes

def domain_extractor(state: InterviewState) -> dict:
    if state.get("domains") and state.get("cv_summary"):
        return {}  # cached in state; never re-run, even on reconnect
    cv_summary = state.get("cv_summary") or _summarize_cv(state.get("cv_text", ""))
    if state.get("domains"):
        return {"cv_summary": cv_summary}
    raw = _ask_llm(
        _EXTRACTOR_SYSTEM,
        "JOB DESCRIPTION:\n"
        + _clip(state.get("jd_text", ""), 6000)
        + "\n\nCANDIDATE PROFILE:\n"
        + cv_summary,
        temperature=0.1,
    )
    parsed = _extract_json(raw, "[")
    domains = [d.strip() for d in parsed if isinstance(d, str) and d.strip()] if isinstance(parsed, list) else []
    if len(domains) < 2:
        logger.warning("Domain extraction returned %r; using default domains", raw[:200])
        domains = list(DEFAULT_DOMAINS)
    return {"domains": domains[:2], "current_domain_index": 0, "cv_summary": cv_summary}


def question_generator(state: InterviewState) -> dict:
    # First question is always an introduction
    if not state.get("qa_pairs") and not state.get("domains_covered"):
        return {"current_question": INTRO_QUESTION}

    domains = state["domains"]
    index = min(state.get("current_domain_index", 0), len(domains) - 1)
    domain = domains[index]
    name = state.get("candidate_name") or "Candidate"

    # Determine if this is an opener or follow-up based on qa_pairs count for this domain
    qa_pairs = state.get("qa_pairs", [])
    domain_qa_count = sum(1 for p in qa_pairs if p["domain"] == domain)

    # On domain change or first question in domain: no history needed
    # On follow-up within same domain: only the last answer
    last_answer_context = ""
    if qa_pairs:
        last_pair = qa_pairs[-1]
        if last_pair.get("domain") == domain:
            # Same domain — include only the candidate's last answer
            last_answer_context = f"Candidate's previous answer: {last_pair.get('answer', '')}"
        # Different domain — pass nothing from history

    if domain_qa_count == 0:
        # Opener question for this domain
        temp = 0.8
        human = (
            f"This opens the '{domain}' domain of the interview with {name}.\n"
            f"JOB DESCRIPTION (excerpt):\n{_clip(state.get('jd_text', ''), 3000)}\n\n"
            f"CANDIDATE PROFILE:\n{state.get('cv_summary', '')}\n\n"
            f"Ask ONE opening question that assesses {domain} for this role. Where the "
            f"profile shows relevant experience, anchor the question to it so the candidate "
            f"can demonstrate real depth."
        )
    else:
        # Follow-up question based on the candidate's last answer
        temp = 0.7
        human = (
            f"You are in the '{domain}' domain with {name}.\n"
            f"{last_answer_context}\n\n"
            f"Ask ONE targeted follow-up to the candidate's last answer: probe for "
            f"concrete detail, challenge vague claims, or explore trade-offs. Do not "
            f"repeat an earlier question and do not switch topics."
        )

    question = _ask_llm(_QUESTION_SYSTEM, human, temperature=temp).strip().strip('"').strip()
    updates: dict = {"current_question": question}
    if domain_qa_count == 0:
        updates["domains_covered"] = [domain]
    return updates


def answer_recorder(state: InterviewState) -> dict:
    question = state.get("current_question") or ""
    answer = (state.get("current_answer") or "").strip()
    if not question or not answer:
        return {}
    domains = state["domains"]
    if not state.get("domains_covered"):
        # Intro answer: keep it out of domain tallies so Domain 1 still gets a real opener
        domain = "Introduction"
    else:
        domain = domains[min(state.get("current_domain_index", 0), len(domains) - 1)]
    pair = {
        "domain": domain,
        "question": question,
        "answer": answer,
        "turn_number": len(state.get("qa_pairs", [])) + 1,
    }
    return {"qa_pairs": [pair]}


def coverage_tracker(state: InterviewState) -> dict:
    """Pure logic routing brain: no LLM call."""
    total_questions = len(state.get("qa_pairs", []))
    
    # Check if we've reached 5 questions total (1 intro + 2 domains × 2 questions each)
    if total_questions >= MAX_QUESTIONS:
        return {"interview_complete": True}
    
    # Cycle through domains: after intro (question 0), alternate between domain 0 and domain 1
    # Question 1 → domain 0 opener, Question 2 → domain 0 follow-up
    # Question 3 → domain 1 opener, Question 4 → domain 1 follow-up
    domains = state["domains"]
    if not domains:
        return {}
    
    # Calculate which domain we should be in based on question number
    # After intro question, questions 1-2 are domain 0, questions 3-4 are domain 1
    next_index = (total_questions - 1) // 2 % len(domains)
    
    return {"current_domain_index": next_index}


def route_after_coverage(state: InterviewState) -> str:
    return "evaluator" if state.get("interview_complete") else "question_generator"


def evaluator(state: InterviewState) -> dict:
    if state.get("scores"):
        return {}
    transcript = "\n\n".join(
        f"[{p['domain']}] Q: {p['question']}\nA: {p['answer']}" for p in state.get("qa_pairs", [])
    )
    notes = ""
    if state.get("proctor_flags"):
        notes = "\nPROCTORING NOTES (consider when judging validity): " + "; ".join(state["proctor_flags"])
    raw = _ask_llm(
        _EVALUATOR_SYSTEM,
        f"Domains assessed: {json.dumps(state.get('domains', []))}\n\n"
        f"JOB DESCRIPTION (excerpt):\n{_clip(state.get('jd_text', ''), 3000)}\n\n"
        f"CANDIDATE CV:\n{_clip(state.get('cv_text', ''), 6000)}\n\n"
        f"FULL INTERVIEW TRANSCRIPT:\n{transcript}{notes}",
        temperature=0.1,
    )
    parsed = _extract_json(raw, "{")
    scores = _normalize_scores(parsed if isinstance(parsed, dict) else None, state.get("domains", []))
    return {"scores": scores, "interview_complete": True}


def _normalize_scores(parsed: Optional[dict], domains: list[str]) -> dict:
    parsed = parsed or {}

    def _clamp(value, default: float = 5.0) -> float:
        try:
            return round(max(0.0, min(10.0, float(value))), 1)
        except (TypeError, ValueError):
            return default

    raw_domains = parsed.get("domain_scores") or {}
    domain_scores: dict[str, Any] = {}
    for d in domains:
        raw = raw_domains.get(d)
        if isinstance(raw, dict):
            entry = dict(raw)
            entry["score"] = _clamp(raw.get("score"))
            entry["expected_highlights"] = [s for s in (raw.get("expected_highlights") or []) if isinstance(s, str)]
            entry["question_notes"] = [s for s in (raw.get("question_notes") or []) if isinstance(s, str)]
            domain_scores[d] = entry
        else:
            domain_scores[d] = _clamp(raw)

    values = [v["score"] if isinstance(v, dict) else v for v in domain_scores.values()]
    overall = _clamp(parsed.get("overall_score"), default=round(sum(values) / max(1, len(values)), 1))
    recommendation = parsed.get("hire_recommendation")
    if recommendation not in ("Strong hire", "Hire", "Lean hire", "No hire"):
        recommendation = (
            "Strong hire" if overall >= 8
            else "Hire" if overall >= 6.5
            else "Lean hire" if overall >= 5
            else "No hire"
        )
    detailed = parsed.get("detailed_feedback") or {}
    strengths = [s for s in (detailed.get("strengths") or parsed.get("strengths") or []) if isinstance(s, str)]
    improvements = [s for s in (detailed.get("improvements") or parsed.get("improvements") or []) if isinstance(s, str)]
    tips = [s for s in (detailed.get("interview_tips") or parsed.get("interview_tips") or []) if isinstance(s, str)]
    summary = str(parsed.get("summary_feedback") or parsed.get("summary") or "No summary provided.")
    return {
        "domain_scores": domain_scores,
        "overall_score": overall,
        "hire_recommendation": recommendation,
        "strengths": strengths,
        "improvements": improvements,
        "summary": summary,
        "summary_feedback": summary,
        "detailed_feedback": {"strengths": strengths, "improvements": improvements, "interview_tips": tips},
    }


# ------------------------------------------------------- graph + checkpointer

_default_checkpointer: Any = None
_default_checkpointer_cm: Any = None
_default_graph: Any = None


def get_default_checkpointer() -> Any:
    global _default_checkpointer, _default_checkpointer_cm
    if _default_checkpointer is not None:
        return _default_checkpointer
    if PostgresSaver is None:
        logger.warning(
            "langgraph-checkpoint-postgres is not installed; checkpoints will NOT "
            "survive a restart. Run: pip install langgraph-checkpoint-postgres"
        )
        _default_checkpointer = MemorySaver()
        return _default_checkpointer
    conn_string = os.getenv("DATABASE_URL", "").replace("+asyncpg", "").replace("+psycopg", "")
    try:
        _default_checkpointer_cm = PostgresSaver.from_conn_string(conn_string)
        saver = _default_checkpointer_cm.__enter__()
        saver.setup()
        _default_checkpointer = saver
    except Exception as exc:
        logger.warning("PostgresSaver unavailable (%s); falling back to in-memory checkpoints", exc)
        _default_checkpointer_cm = None
        _default_checkpointer = MemorySaver()
    return _default_checkpointer


def build_graph(checkpointer: Any = None) -> Any:
    builder = StateGraph(InterviewState)
    builder.add_node("domain_extractor", domain_extractor)
    builder.add_node("question_generator", question_generator)
    builder.add_node("answer_recorder", answer_recorder)
    builder.add_node("coverage_tracker", coverage_tracker)
    builder.add_node("evaluator", evaluator)

    builder.add_edge(START, "domain_extractor")
    builder.add_edge("domain_extractor", "question_generator")
    builder.add_edge("question_generator", "answer_recorder")
    builder.add_edge("answer_recorder", "coverage_tracker")
    builder.add_conditional_edges(
        "coverage_tracker",
        route_after_coverage,
        {"question_generator": "question_generator", "evaluator": "evaluator"},
    )
    builder.add_edge("evaluator", END)

    return builder.compile(
        checkpointer=checkpointer if checkpointer is not None else get_default_checkpointer(),
        interrupt_after=["question_generator"],
    )


def get_graph() -> Any:
    global _default_graph
    if _default_graph is None:
        _default_graph = build_graph()
    return _default_graph


# ------------------------------------------------------------ public session API

class InterviewSession:
    """Thin wrapper FastAPI calls: one instance per interview session."""

    def __init__(self, session_id: str, checkpointer: Any = None):
        self.session_id = session_id
        self.config = {"configurable": {"thread_id": session_id}}
        self.graph = build_graph(checkpointer) if checkpointer is not None else get_graph()

    def start_interview(self, cv_text: str, jd_text: str, candidate_name: str = "") -> dict:
        snapshot = self.graph.get_state(self.config)
        if snapshot.values.get("current_question"):
            return self._turn_payload(snapshot.values, resumed=True)
        initial: InterviewState = {
            "domains": [],
            "current_domain_index": 0,
            "domains_covered": [],
            "follow_up_count": 0,
            "current_question": "",
            "current_answer": "",
            "qa_pairs": [],
            "proctor_flags": [],
            "scores": None,
            "interview_complete": False,
            "cv_text": cv_text or "",
            "jd_text": jd_text or "",
            "candidate_name": candidate_name or "Candidate",
            "session_id": self.session_id,
        }
        self.graph.invoke(initial, self.config)
        snapshot = self.graph.get_state(self.config)
        return self._turn_payload(snapshot.values, resumed=False)

    def submit_answer(self, answer_text: str) -> dict:
        snapshot = self.graph.get_state(self.config)
        if not snapshot.values.get("current_question"):
            raise ValueError(f"No active interview for session {self.session_id}; call start_interview first")
        if snapshot.values.get("interview_complete"):
            return self._turn_payload(snapshot.values, resumed=False)
        self.graph.update_state(self.config, {"current_answer": (answer_text or "").strip()})
        self.graph.invoke(None, self.config)
        snapshot = self.graph.get_state(self.config)
        return self._turn_payload(snapshot.values, resumed=False)

    def add_proctor_flag(self, event: str) -> None:
        self.graph.update_state(self.config, {"proctor_flags": [event]})

    def get_status(self) -> dict:
        snapshot = self.graph.get_state(self.config)
        return self._turn_payload(snapshot.values, resumed=False)

    def _turn_payload(self, values: dict, resumed: bool) -> dict:
        domains = values.get("domains", [])
        index = min(values.get("current_domain_index", 0), max(0, len(domains) - 1))
        return {
            "session_id": self.session_id,
            "candidate_name": values.get("candidate_name", ""),
            "domains": domains,
            "domain_index": index,
            "current_domain": domains[index] if domains else None,
            "follow_up_count": values.get("follow_up_count", 0),
            "question": values.get("current_question"),
            "interview_complete": bool(values.get("interview_complete")),
            "scores": values.get("scores"),
            "resumed": resumed,
        }
