"""TaleemBot LangGraph interview engine.

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
from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

try:
    from langgraph.checkpoint.postgres import PostgresSaver
except ModuleNotFoundError:  # langgraph-checkpoint-postgres not installed yet
    PostgresSaver = None

load_dotenv()

logger = logging.getLogger("taleembot.interview_graph")

MAX_FOLLOW_UPS = 3
DEFAULT_DOMAINS = [
    "Technical Expertise",
    "Problem Solving",
    "System Design & Architecture",
    "Communication & Collaboration",
]

_EXTRACTOR_SYSTEM = (
    "You are the domain-extraction stage of TaleemBot, an AI interview engine. "
    "Read the job description and the candidate's CV, then identify the 3-4 core "
    "skill domains the company actually cares about for this role. Return ONLY a "
    "JSON array of 3-4 short domain names (2-5 words each), e.g. "
    '["Backend APIs", "Relational Databases", "React Frontend", "DevOps & CI/CD"]. '
    "No prose, no markdown."
)

_QUESTION_SYSTEM = (
    "You are TaleemBot, a senior interviewer conducting a structured voice interview. "
    "Ask exactly ONE question per turn. The question is spoken aloud by a TTS voice, "
    "so keep it conversational, natural and under 60 words. Never reveal scoring, "
    "domains covered, or that you are an AI state machine. Output only the question "
    "text, no preamble, no quotes."
)

_EVALUATOR_SYSTEM = (
    "You are a strict but fair hiring manager evaluating a completed voice interview. "
    "Score every domain 0-10 (0 = no competence, 10 = expert). overall_score is the "
    "average of domain scores weighted by how central each domain is to the job "
    "description. hire_recommendation must be one of: \"Strong hire\", \"Hire\", "
    "\"Lean hire\", \"No hire\". Be honest: reward concrete examples and depth, "
    "penalise vagueness. Return ONLY a JSON object with keys: domain_scores (object "
    "mapping each domain name to a number), overall_score (number), "
    "hire_recommendation (string), strengths (array of strings), improvements "
    "(array of strings), summary (string, 2-4 sentences). No prose, no markdown."
)


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
    jd_text: str
    candidate_name: str
    session_id: str


# --------------------------------------------------------------------------- LLM

_model: Optional[ChatTongyi] = None


def get_llm() -> ChatTongyi:
    global _model
    if _model is None:
        _model = ChatTongyi(model=os.getenv("QWEN_MODEL", "qwen-max"))
    return _model


def _ask_llm(system: str, human: str) -> str:
    response = get_llm().invoke([SystemMessage(content=system), HumanMessage(content=human)])
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


# -------------------------------------------------------------------------- nodes

def domain_extractor(state: InterviewState) -> dict:
    if state.get("domains"):
        return {}  # cached in state; never re-extracted, even on reconnect
    raw = _ask_llm(
        _EXTRACTOR_SYSTEM,
        "JOB DESCRIPTION:\n"
        + _clip(state.get("jd_text", ""), 6000)
        + "\n\nCANDIDATE CV:\n"
        + _clip(state.get("cv_text", ""), 6000),
    )
    parsed = _extract_json(raw, "[")
    domains = [d.strip() for d in parsed if isinstance(d, str) and d.strip()] if isinstance(parsed, list) else []
    if len(domains) < 2:
        logger.warning("Domain extraction returned %r; using default domains", raw[:200])
        domains = list(DEFAULT_DOMAINS)
    return {"domains": domains[:4], "current_domain_index": 0}


def question_generator(state: InterviewState) -> dict:
    domains = state["domains"]
    index = min(state.get("current_domain_index", 0), len(domains) - 1)
    domain = domains[index]
    opened = domain in state.get("domains_covered", [])
    name = state.get("candidate_name") or "Candidate"

    if not opened:
        human = (
            f"This opens the '{domain}' domain of the interview with {name}.\n"
            f"JOB DESCRIPTION (excerpt):\n{_clip(state.get('jd_text', ''), 3000)}\n\n"
            f"CANDIDATE CV (excerpt):\n{_clip(state.get('cv_text', ''), 3000)}\n\n"
            f"Ask ONE opening question that assesses {domain} for this role. Where the "
            f"CV shows relevant experience, anchor the question to it so the candidate "
            f"can demonstrate real depth."
        )
    else:
        history = [p for p in state.get("qa_pairs", []) if p["domain"] == domain][-6:]
        transcript = "\n".join(f"Q: {p['question']}\nA: {p['answer']}" for p in history)
        human = (
            f"You are in the '{domain}' domain, follow-up "
            f"#{state.get('follow_up_count', 0) + 1} of {MAX_FOLLOW_UPS}, with {name}.\n"
            f"Conversation so far in this domain:\n{transcript}\n\n"
            f"Ask ONE targeted follow-up to the candidate's last answer: probe for "
            f"concrete detail, challenge vague claims, or explore trade-offs. Do not "
            f"repeat an earlier question and do not switch topics."
        )

    question = _ask_llm(_QUESTION_SYSTEM, human).strip().strip('"').strip()
    updates: dict = {"current_question": question}
    if not opened:
        updates["domains_covered"] = [domain]
    return updates


def answer_recorder(state: InterviewState) -> dict:
    question = state.get("current_question") or ""
    answer = (state.get("current_answer") or "").strip()
    if not question or not answer:
        return {}
    domains = state["domains"]
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
    domains = state["domains"]
    index = min(state.get("current_domain_index", 0), len(domains) - 1)
    domain = domains[index]
    answered = sum(1 for p in state.get("qa_pairs", []) if p["domain"] == domain)
    # The first Q&A in a domain is the opener; everything after is a follow-up.
    follow_ups = max(0, answered - 1)
    if follow_ups >= MAX_FOLLOW_UPS:
        next_index = index + 1
        updates: dict = {"follow_up_count": 0, "current_domain_index": next_index}
        if next_index >= len(domains):
            updates["interview_complete"] = True
        return updates
    return {"follow_up_count": follow_ups}


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
        f"FULL INTERVIEW TRANSCRIPT:\n{transcript}{notes}",
    )
    parsed = _extract_json(raw, "{")
    scores = _normalize_scores(parsed if isinstance(parsed, dict) else None, state.get("domains", []))
    return {"scores": scores, "interview_complete": True}


def _normalize_scores(parsed: Optional[dict], domains: list[str]) -> dict:
    domain_scores: dict[str, float] = {}
    for d in domains:
        value = (parsed or {}).get("domain_scores", {}).get(d, 5.0) if parsed else 5.0
        try:
            domain_scores[d] = round(max(0.0, min(10.0, float(value))), 1)
        except (TypeError, ValueError):
            domain_scores[d] = 5.0
    overall = (parsed or {}).get("overall_score") if parsed else None
    try:
        overall = round(max(0.0, min(10.0, float(overall))), 1)
    except (TypeError, ValueError):
        overall = round(sum(domain_scores.values()) / max(1, len(domain_scores)), 1)
    recommendation = (parsed or {}).get("hire_recommendation") if parsed else None
    if recommendation not in ("Strong hire", "Hire", "Lean hire", "No hire"):
        recommendation = (
            "Strong hire" if overall >= 8
            else "Hire" if overall >= 6.5
            else "Lean hire" if overall >= 5
            else "No hire"
        )
    return {
        "domain_scores": domain_scores,
        "overall_score": overall,
        "hire_recommendation": recommendation,
        "strengths": [s for s in ((parsed or {}).get("strengths") or []) if isinstance(s, str)],
        "improvements": [s for s in ((parsed or {}).get("improvements") or []) if isinstance(s, str)],
        "summary": str((parsed or {}).get("summary") or "No summary provided."),
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
