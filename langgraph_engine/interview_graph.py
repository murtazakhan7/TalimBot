# """TalimBot LangGraph interview engine.

# Stateful directed graph with five nodes (domain_extractor, question_generator,
# answer_recorder, coverage_tracker, evaluator) that enforces fair coverage of
# every skill domain extracted from the job description.

# The graph is compiled with ``interrupt_after=["question_generator"]`` so that a
# single ``invoke()`` produces exactly one question to be spoken to the candidate:

# * ``start_interview`` -> domain_extractor -> question_generator -> INTERRUPT
# * ``submit_answer``   -> answer_recorder -> coverage_tracker ->
#                          question_generator -> INTERRUPT   (or evaluator -> END)

# PostgresSaver checkpoints state after every node execution, so a candidate who
# disconnects mid-interview resumes from exactly the turn they left.
# """

# from __future__ import annotations

# import json
# import logging
# import operator
# import os
# from typing import Annotated, Any, Optional, TypedDict

# from dotenv import load_dotenv
# from langchain_core.messages import HumanMessage, SystemMessage
# from langgraph.checkpoint.memory import MemorySaver
# from langgraph.graph import END, START, StateGraph
# from langchain_openai import ChatOpenAI

# try:
#     from langgraph.checkpoint.postgres import PostgresSaver
# except ModuleNotFoundError:
#     PostgresSaver = None

# load_dotenv()

# logger = logging.getLogger("talimbot.interview_graph")

# MAX_QUESTIONS = 5
# INTRO_QUESTION = (
#     "To get us started, could you please introduce yourself and tell me a bit about "
#     "your background?"
# )
# DEFAULT_DOMAINS = [
#     "Technical Expertise",
#     "Problem Solving",
# ]

# _EXTRACTOR_SYSTEM = (
#     "You are the domain-extraction stage of TalimBot, an AI interview engine. "
#     "Read the job description and candidate CV, then return ONLY a JSON object "
#     "with exactly two keys:\n"
#     "- \"summary\": a concise 150-word candidate profile covering total experience "
#     "(or student/fresh graduate status), core technical skills, notable projects, "
#     "and most recent role. Be factual — only include what is explicitly stated.\n"
#     "- \"domains\": an array of exactly 2 short skill domain names (2-5 words each) "
#     "that the company actually cares about for this role.\n\n"
#     "Example: {\"summary\": \"Fresh CS graduate...\", \"domains\": [\"Backend APIs\", \"React Frontend\"]}\n"
#     "No prose, no markdown, no extra keys."
# )

# _QUESTION_SYSTEM = (
#     "You are TalimBot, a senior interviewer conducting a structured voice interview. "
#     "Ask exactly ONE question per turn. Output only the question text — no preamble, "
#     "no quotes, no labels.\n\n"

#     "FOCUS RULE — the single most important rule:\n"
#     "Every question must probe exactly ONE specific thing. Never list multiple "
#     "components, steps, or sub-topics in the same question. "
#     "Bad: \'Walk me through the models, serializers, auth flow, and performance optimizations.\' "
#     "Good: \'How did you handle token expiry in your JWT setup?\' "
#     "Pick the single most revealing aspect and ask only about that.\n\n"

#     "OPENING QUESTIONS — first question in a domain:\n"
#     "Anchor to one specific decision the candidate made, one problem they solved, "
#     "or one tradeoff they faced in something they actually built. "
#     "Do not ask them to walk through the whole system.\n\n"

#     "FOLLOW-UP QUESTIONS — second question in the same domain:\n"
#     "Look at the candidate\'s last answer. If they used a technical term or named "
#     "a tool, dig into exactly that. If the answer was vague, ask for a concrete "
#     "example or what it looked like in their actual code. Never switch topics.\n\n"

#     "SPOKEN AUDIO FORMAT:\n"
#     "Keep it under 50 words. Spell out abbreviations as full words: say \'JSON web token\' "
#     "not \'JWT\', \'PostgreSQL\' not \'Postgres\', \'React\' not \'ReactJS\', "
#     "\'versus\' not \'vs\'. No bullet points, slashes, parentheses, or special characters. "
#     "Write as natural, conversational speech. Never start consecutive questions with "
#     "the same opening words — vary your sentence openers every turn."
# )

# _EVALUATOR_SYSTEM = """You are a fair and calibrated interview evaluator assessing a candidate who is a fresh graduate or early-career professional practicing for entry-level to mid-level roles. Score accordingly — do not apply a senior engineer standard.

# Evaluate based on:
# - Did they actually answer the question asked? (relevance)
# - Do they demonstrate genuine understanding of the concept, not just buzzwords?
# - Can they support their answer with a specific example, project, or experience?
# - Can they communicate clearly and coherently?

# Do NOT penalize for:
# - Not using any framework (STAR, SOAR, etc.) — frameworks are never required
# - Conversational speech patterns, filler words, or mid-sentence rephrasing — this is spoken audio transcribed, not written text
# - Using plain language instead of technical jargon, as long as the understanding is correct
# - Incomplete answers that show the right thinking — reward direction of understanding, not perfection
# - Pausing, repeating, or self-correcting — these are normal in speech

# For each domain, also return:
# - expected_highlights: 2-3 things a strong answer to this domain's questions should have demonstrated (concept-based, not framework-based — e.g. "awareness of tradeoffs", "a specific project example", "understanding of why not just what")
# - question_notes: a one-line note per question on what the candidate's answer did well or missed specifically

# Return a JSON object with this exact structure:
# {
#   "overall_score": <float 1-10>,
#   "domain_scores": {
#     "<domain_name>": {
#       "score": <float 1-10>,
#       "reasoning": "<2-3 sentences>",
#       "strength": "<one thing they did well>",
#       "gap": "<one thing to improve>",
#       "expected_highlights": ["<highlight 1>", "<highlight 2>", "<highlight 3>"],
#       "question_notes": ["<note on Q1 in this domain>", "<note on Q2 in this domain>"]
#     }
#   },
#   "summary_feedback": "<3-4 sentences overall>",
#   "detailed_feedback": {
#     "strengths": ["<strength 1>", "<strength 2>", "<strength 3>"],
#     "improvements": ["<improvement 1>", "<improvement 2>", "<improvement 3>"],
#     "interview_tips": ["<tip 1>", "<tip 2>", "<tip 3>"]
#   },
#   "hire_recommendation": "<Strong hire | Hire | Lean hire | No hire>"
# }"""


# class InterviewState(TypedDict, total=False):
#     domains: list[str]
#     current_domain_index: int
#     domains_covered: Annotated[list[str], operator.add]
#     follow_up_count: int
#     current_question: str
#     current_answer: str
#     qa_pairs: Annotated[list[dict], operator.add]
#     proctor_flags: Annotated[list[str], operator.add]
#     scores: Optional[dict]
#     interview_complete: bool
#     cv_text: str
#     cv_summary: str
#     jd_text: str
#     candidate_name: str
#     session_id: str


# # --------------------------------------------------------------------------- LLM

# _model: Optional[ChatOpenAI] = None


# def get_llm() -> ChatOpenAI:
#     global _model
#     if _model is None:
#         print(">>> [LLM] Initializing model: openai/gpt-oss-120b on Groq")
#         _model = ChatOpenAI(
#             model="openai/gpt-oss-120b",
#             api_key=os.getenv("GROQ_API_KEY"),
#             base_url="https://api.groq.com/openai/v1",
#         )
#     return _model


# def _ask_llm(
#     system: str,
#     human: str,
#     temperature: float = 0.7,
#     max_tokens: int = 1024,
#     reasoning_effort: Optional[str] = None,
# ) -> str:
#     """
#     Call the LLM with optional reasoning_effort.

#     reasoning_effort must be one of: "low", "medium", "high", or None (disables reasoning).
#     When None, reasoning is disabled by passing reasoning_effort="none" to the model.
#     """
#     llm = get_llm()

#     bind_kwargs: dict[str, Any] = {
#         "temperature": temperature,
#         "max_tokens": max_tokens,
#     }

#     if reasoning_effort is None:
#         # Explicitly disable reasoning
#         bind_kwargs["reasoning_effort"] = "none"
#     else:
#         # Must be "low", "medium", or "high"
#         if reasoning_effort not in ("low", "medium", "high"):
#             raise ValueError(
#                 f"reasoning_effort must be 'low', 'medium', 'high', or None — got {reasoning_effort!r}"
#             )
#         bind_kwargs["reasoning_effort"] = reasoning_effort

#     llm = llm.bind(**bind_kwargs)
#     response = llm.invoke([SystemMessage(content=system), HumanMessage(content=human)])
#     print(
#         f">>> [_ask_llm] finish_reason={response.response_metadata.get('finish_reason')} "
#         f"reasoning_tokens={response.response_metadata.get('token_usage', {}).get('reasoning_tokens')} "
#         f"reasoning_effort={bind_kwargs['reasoning_effort']}"
#     )
#     return response.content if isinstance(response.content, str) else str(response.content)


# def _extract_json(text: str, opener: str) -> Any:
#     """Pull the first balanced JSON array/object out of an LLM reply."""
#     closer = "]" if opener == "[" else "}"
#     for i, ch in enumerate(text):
#         if ch != opener:
#             continue
#         depth = 0
#         in_str = False
#         escaped = False
#         for j in range(i, len(text)):
#             c = text[j]
#             if in_str:
#                 if escaped:
#                     escaped = False
#                 elif c == "\\":
#                     escaped = True
#                 elif c == '"':
#                     in_str = False
#             elif c == '"':
#                 in_str = True
#             elif c == opener:
#                 depth += 1
#             elif c == closer:
#                 depth -= 1
#                 if depth == 0:
#                     try:
#                         return json.loads(text[i : j + 1])
#                     except json.JSONDecodeError:
#                         break
#     return None


# def _clip(text: str, limit: int) -> str:
#     return text if len(text) <= limit else text[:limit] + "\n[...truncated]"


# _JOB_TITLE_SYSTEM = (
#     "Extract only the job title from this job description. Return just the title, "
#     "nothing else. If unclear, return 'Software Engineer'."
# )


# def extract_job_title(jd_text: str) -> str:
#     try:
#         title = _ask_llm(
#             _JOB_TITLE_SYSTEM,
#             (jd_text or "")[:2000],
#             temperature=0.1,
#             max_tokens=20,
#             reasoning_effort=None,  # no reasoning needed for simple extraction
#         )
#         title = title.strip().strip('"').strip("'").strip()
#     except Exception as exc:
#         logger.warning("Job title extraction failed (%s); using default", exc)
#         title = ""
#     return (title or "Software Engineer")[:255]


# _PARAPHRASE_SYSTEM = (
#     "Rephrase this interview question in simpler, clearer language. Keep the same "
#     "topic. Return only the rephrased question, nothing else."
# )


# def rephrase_question(question_text: str) -> str:
#     rephrased = _ask_llm(
#         _PARAPHRASE_SYSTEM,
#         question_text,
#         temperature=0.7,
#         max_tokens=180,
#         reasoning_effort="low",  # low effort — simple rephrasing task
#     )
#     return rephrased.strip().strip('"').strip()


# # -------------------------------------------------------------------------- nodes

# def domain_extractor(state: InterviewState) -> dict:
#     print(">>> [domain_extractor] ENTER")

#     if state.get("domains") and state.get("cv_summary"):
#         print(">>> [domain_extractor] Cache hit — skipping LLM call")
#         return {}

#     # max_tokens=1200: reasoning tokens can consume several hundred before the JSON
#     # output begins, so 600 was too tight and risked a truncated / empty response.
#     print(">>> [domain_extractor] Calling LLM (max_tokens=1200, reasoning_effort=medium)...")
#     raw = _ask_llm(
#         _EXTRACTOR_SYSTEM,
#         "JOB DESCRIPTION:\n"
#         + _clip(state.get("jd_text", ""), 6000)
#         + "\n\nCANDIDATE CV:\n"
#         + _clip(state.get("cv_text", ""), 6000),
#         temperature=0.1,
#         max_tokens=1200,
#         reasoning_effort="medium",
#     )
#     print(f">>> [domain_extractor] Raw response ({len(raw)} chars): {raw[:600]}")

#     parsed = _extract_json(raw, "{")
#     print(f">>> [domain_extractor] Parsed JSON: {parsed}")

#     domains: list[str] = []
#     cv_summary: str = ""

#     if isinstance(parsed, dict):
#         raw_domains = parsed.get("domains", [])
#         domains = [d.strip() for d in raw_domains if isinstance(d, str) and d.strip()]
#         cv_summary = str(parsed.get("summary", "")).strip()
#         print(f">>> [domain_extractor] Domains extracted: {domains}")
#         print(f">>> [domain_extractor] CV summary length: {len(cv_summary)} chars")
#     else:
#         print(f">>> [domain_extractor] JSON parse failed — parsed={parsed}")

#     if len(domains) < 2:
#         print(f">>> [domain_extractor] WARN: using default domains (got {domains})")
#         domains = list(DEFAULT_DOMAINS)

#     if not cv_summary:
#         cv_summary = "No summary available."

#     print(f">>> [domain_extractor] EXIT — domains={domains}")
#     return {
#         "domains": domains[:2],
#         "current_domain_index": 0,
#         "cv_summary": cv_summary,
#     }


# def question_generator(state: InterviewState) -> dict:
#     print(">>> [question_generator] ENTER")
#     print(f">>> [question_generator] qa_pairs={len(state.get('qa_pairs', []))}, domains_covered={state.get('domains_covered', [])}")

#     if not state.get("qa_pairs") and not state.get("domains_covered"):
#         print(">>> [question_generator] Returning hardcoded INTRO_QUESTION")
#         return {"current_question": INTRO_QUESTION}

#     domains = state["domains"]
#     index = min(state.get("current_domain_index", 0), len(domains) - 1)
#     domain = domains[index]
#     name = state.get("candidate_name") or "Candidate"
#     print(f">>> [question_generator] domain='{domain}' index={index} name='{name}'")

#     qa_pairs = state.get("qa_pairs", [])
#     domain_qa_count = sum(1 for p in qa_pairs if p["domain"] == domain)
#     print(f">>> [question_generator] domain_qa_count={domain_qa_count}")

#     last_answer_context = ""
#     if qa_pairs:
#         last_pair = qa_pairs[-1]
#         if last_pair.get("domain") == domain:
#             last_answer_context = f"Candidate's previous answer: {last_pair.get('answer', '')}"

#     if domain_qa_count == 0:
#         temp = 0.8
#         human = (
#             f"Opening the '{domain}' domain with {name}.\n"
#             f"JOB DESCRIPTION (excerpt):\n{_clip(state.get('jd_text', ''), 1500)}\n\n"
#             f"CANDIDATE PROFILE:\n{state.get('cv_summary', '')}\n\n"
#             f"Ask ONE focused opening question about a single specific aspect of {domain}. "
#             f"Anchor it to something the candidate actually built or decided in their profile. "
#             f"Do NOT list multiple components or ask them to walk through the whole system. "
#             f"Pick ONE decision, problem, or implementation detail and ask only about that."
#         )
#     else:
#         temp = 0.7
#         human = (
#             f"Follow-up in the '{domain}' domain with {name}.\n"
#             f"{last_answer_context}\n\n"
#             f"Read the candidate's answer above carefully. "
#             f"If they mentioned a specific tool, library, or technique, ask them to go deeper "
#             f"into exactly that — how it works, why they chose it, or what tradeoffs they hit. "
#             f"If the answer was vague or high-level, ask for a concrete example from their code "
#             f"or project. ONE question only, ONE topic only. Do not repeat earlier questions."
#         )

#     # max_tokens must be large enough to cover reasoning tokens + the output text.
#     # With reasoning_effort=medium, the model can spend several hundred tokens on
#     # internal reasoning before emitting a single word of visible output — 300 was
#     # too small and caused finish_reason=length with an empty response.
#     print(f">>> [question_generator] Calling LLM (temp={temp}, max_tokens=1024, reasoning_effort=medium)...")
#     raw_question = _ask_llm(
#         _QUESTION_SYSTEM,
#         human,
#         temperature=temp,
#         max_tokens=1024,
#         reasoning_effort="medium",
#     )
#     print(f">>> [question_generator] Raw LLM output: {repr(raw_question)}")
#     question = raw_question.strip().strip('"').strip()
#     print(f">>> [question_generator] After strip: {repr(question)}")

#     # Guard: if the model returned nothing (finish_reason=length starved the output),
#     # retry once without reasoning so we always get a usable question.
#     if not question:
#         print(">>> [question_generator] WARN: empty output — retrying without reasoning (reasoning_effort=None)...")
#         raw_question = _ask_llm(
#             _QUESTION_SYSTEM,
#             human,
#             temperature=temp,
#             max_tokens=300,
#             reasoning_effort=None,
#         )
#         print(f">>> [question_generator] Retry raw output: {repr(raw_question)}")
#         question = raw_question.strip().strip('"').strip()
#         print(f">>> [question_generator] Retry after strip: {repr(question)}")

#     updates: dict = {"current_question": question}
#     if domain_qa_count == 0:
#         updates["domains_covered"] = [domain]

#     print(f">>> [question_generator] EXIT — updates keys: {list(updates.keys())}")
#     return updates


# def answer_recorder(state: InterviewState) -> dict:
#     print(">>> [answer_recorder] ENTER")
#     question = state.get("current_question") or ""
#     answer = (state.get("current_answer") or "").strip()
#     print(f">>> [answer_recorder] question present={bool(question)}, answer present={bool(answer)}")
#     if not question or not answer:
#         print(">>> [answer_recorder] WARN: missing question or answer — returning empty")
#         return {}
#     domains = state["domains"]
#     if not state.get("domains_covered"):
#         domain = "Introduction"
#     else:
#         domain = domains[min(state.get("current_domain_index", 0), len(domains) - 1)]
#     pair = {
#         "domain": domain,
#         "question": question,
#         "answer": answer,
#         "turn_number": len(state.get("qa_pairs", [])) + 1,
#     }
#     print(f">>> [answer_recorder] Recorded QA pair — domain='{domain}' turn={pair['turn_number']}")
#     return {"qa_pairs": [pair]}


# def coverage_tracker(state: InterviewState) -> dict:
#     print(">>> [coverage_tracker] ENTER")
#     total_questions = len(state.get("qa_pairs", []))
#     print(f">>> [coverage_tracker] total_questions={total_questions}, MAX={MAX_QUESTIONS}")

#     if total_questions >= MAX_QUESTIONS:
#         print(">>> [coverage_tracker] Interview complete — routing to evaluator")
#         return {"interview_complete": True}

#     domains = state["domains"]
#     if not domains:
#         print(">>> [coverage_tracker] WARN: no domains in state")
#         return {}

#     next_index = (total_questions - 1) // 2 % len(domains)
#     print(f">>> [coverage_tracker] next_domain_index={next_index} ({domains[next_index]})")
#     return {"current_domain_index": next_index}


# def route_after_coverage(state: InterviewState) -> str:
#     route = "evaluator" if state.get("interview_complete") else "question_generator"
#     print(f">>> [route_after_coverage] routing to: {route}")
#     return route


# def evaluator(state: InterviewState) -> dict:
#     import time as _time
#     print(">>> [evaluator] ENTER")
#     if state.get("scores"):
#         print(">>> [evaluator] Cache hit — scores already present")
#         return {}

#     # The evaluator fires immediately after the last question_generator call on the
#     # same submit_answer turn. Together those two calls can burst ~5,000 tokens in
#     # a few seconds. A 15-second pause lets Groq's rolling TPM window clear enough
#     # headroom so the evaluator (~3,900 tok) lands cleanly under the 8,000 TPM limit
#     # even in worst-case timing. This is invisible to the user — their final answer
#     # audio is still playing / they are reading the "processing" screen.
#     print(">>> [evaluator] Waiting 7s to clear TPM window before evaluation call...")
#     _time.sleep(7)

#     transcript = "\n\n".join(
#         f"[{p['domain']}] Q: {p['question']}\nA: {p['answer']}"
#         for p in state.get("qa_pairs", [])
#     )
#     print(f">>> [evaluator] Transcript length: {len(transcript)} chars, QA pairs: {len(state.get('qa_pairs', []))}")

#     notes = ""
#     if state.get("proctor_flags"):
#         notes = "\nPROCTORING NOTES (consider when judging validity): " + "; ".join(
#             state["proctor_flags"]
#         )

#     print(">>> [evaluator] Calling LLM (max_tokens=3500, reasoning_effort=medium)...")
#     raw = _ask_llm(
#         _EVALUATOR_SYSTEM,
#         f"Domains assessed: {json.dumps(state.get('domains', []))}\n\n"
#         f"JOB DESCRIPTION (excerpt):\n{_clip(state.get('jd_text', ''), 3000)}\n\n"
#         f"CANDIDATE PROFILE:\n{state.get('cv_summary', '')}\n\n"
#         f"FULL INTERVIEW TRANSCRIPT:\n{transcript}{notes}",
#         temperature=0.1,
#         max_tokens=3500,
#         reasoning_effort="medium",
#     )
#     print(f">>> [evaluator] Raw response ({len(raw)} chars): {raw[:300]}...")

#     parsed = _extract_json(raw, "{")
#     print(f">>> [evaluator] JSON parsed successfully: {parsed is not None}")

#     scores = _normalize_scores(
#         parsed if isinstance(parsed, dict) else None,
#         state.get("domains", []),
#     )
#     print(f">>> [evaluator] Final scores — overall={scores.get('overall_score')}, recommendation={scores.get('hire_recommendation')}")
#     return {"scores": scores, "interview_complete": True}


# def _normalize_scores(parsed: Optional[dict], domains: list[str]) -> dict:
#     parsed = parsed or {}

#     def _clamp(value, default: float = 5.0) -> float:
#         try:
#             return round(max(0.0, min(10.0, float(value))), 1)
#         except (TypeError, ValueError):
#             return default

#     raw_domains = parsed.get("domain_scores") or {}
#     domain_scores: dict[str, Any] = {}
#     for d in domains:
#         raw = raw_domains.get(d)
#         if isinstance(raw, dict):
#             entry = dict(raw)
#             entry["score"] = _clamp(raw.get("score"))
#             entry["expected_highlights"] = [
#                 s for s in (raw.get("expected_highlights") or []) if isinstance(s, str)
#             ]
#             entry["question_notes"] = [
#                 s for s in (raw.get("question_notes") or []) if isinstance(s, str)
#             ]
#             domain_scores[d] = entry
#         else:
#             domain_scores[d] = _clamp(raw)

#     # ── Grace marks ──────────────────────────────────────────────────────────
#     # LLM evaluators tend to score conservatively. Add +0.5 to every domain
#     # score and +1.0 to overall, capped at 10.0, to correct for this bias.
#     GRACE_DOMAIN = 0.5
#     GRACE_OVERALL = 1.0
#     for d in domain_scores:
#         entry = domain_scores[d]
#         if isinstance(entry, dict):
#             entry["score"] = round(min(10.0, entry["score"] + GRACE_DOMAIN), 1)
#         else:
#             domain_scores[d] = round(min(10.0, entry + GRACE_DOMAIN), 1)

#     values = [v["score"] if isinstance(v, dict) else v for v in domain_scores.values()]
#     raw_overall = _clamp(
#         parsed.get("overall_score"),
#         default=round(sum(values) / max(1, len(values)), 1),
#     )
#     overall = round(min(10.0, raw_overall + GRACE_OVERALL), 1)

#     # Re-derive recommendation from the grace-adjusted overall score
#     recommendation = (
#         "Strong hire" if overall >= 8
#         else "Hire" if overall >= 6.5
#         else "Lean hire" if overall >= 5
#         else "No hire"
#     )
#     detailed = parsed.get("detailed_feedback") or {}
#     strengths = [
#         s for s in (detailed.get("strengths") or parsed.get("strengths") or [])
#         if isinstance(s, str)
#     ]
#     improvements = [
#         s for s in (detailed.get("improvements") or parsed.get("improvements") or [])
#         if isinstance(s, str)
#     ]
#     tips = [
#         s for s in (detailed.get("interview_tips") or parsed.get("interview_tips") or [])
#         if isinstance(s, str)
#     ]
#     summary = str(
#         parsed.get("summary_feedback") or parsed.get("summary") or "No summary provided."
#     )
#     return {
#         "domain_scores": domain_scores,
#         "overall_score": overall,
#         "hire_recommendation": recommendation,
#         "strengths": strengths,
#         "improvements": improvements,
#         "summary": summary,
#         "summary_feedback": summary,
#         "detailed_feedback": {
#             "strengths": strengths,
#             "improvements": improvements,
#             "interview_tips": tips,
#         },
#     }


# # ------------------------------------------------------- graph + checkpointer

# _default_checkpointer: Any = None
# _default_checkpointer_cm: Any = None
# _default_graph: Any = None


# def get_default_checkpointer() -> Any:
#     global _default_checkpointer, _default_checkpointer_cm
#     if _default_checkpointer is not None:
#         return _default_checkpointer
#     if PostgresSaver is None:
#         logger.warning(
#             "langgraph-checkpoint-postgres is not installed; checkpoints will NOT "
#             "survive a restart. Run: pip install langgraph-checkpoint-postgres"
#         )
#         _default_checkpointer = MemorySaver()
#         return _default_checkpointer
#     conn_string = (
#         os.getenv("DATABASE_URL", "")
#         .replace("+asyncpg", "")
#         .replace("+psycopg", "")
#     )
#     try:
#         _default_checkpointer_cm = PostgresSaver.from_conn_string(conn_string)
#         saver = _default_checkpointer_cm.__enter__()
#         saver.setup()
#         _default_checkpointer = saver
#     except Exception as exc:
#         logger.warning(
#             "PostgresSaver unavailable (%s); falling back to in-memory checkpoints", exc
#         )
#         _default_checkpointer_cm = None
#         _default_checkpointer = MemorySaver()
#     return _default_checkpointer


# def build_graph(checkpointer: Any = None) -> Any:
#     builder = StateGraph(InterviewState)
#     builder.add_node("domain_extractor", domain_extractor)
#     builder.add_node("question_generator", question_generator)
#     builder.add_node("answer_recorder", answer_recorder)
#     builder.add_node("coverage_tracker", coverage_tracker)
#     builder.add_node("evaluator", evaluator)

#     builder.add_edge(START, "domain_extractor")
#     builder.add_edge("domain_extractor", "question_generator")
#     builder.add_edge("question_generator", "answer_recorder")
#     builder.add_edge("answer_recorder", "coverage_tracker")
#     builder.add_conditional_edges(
#         "coverage_tracker",
#         route_after_coverage,
#         {"question_generator": "question_generator", "evaluator": "evaluator"},
#     )
#     builder.add_edge("evaluator", END)

#     return builder.compile(
#         checkpointer=checkpointer if checkpointer is not None else get_default_checkpointer(),
#         interrupt_after=["question_generator"],
#     )


# def get_graph() -> Any:
#     global _default_graph
#     if _default_graph is None:
#         _default_graph = build_graph()
#     return _default_graph


# # ------------------------------------------------------------ public session API

# class InterviewSession:
#     """Thin wrapper FastAPI calls: one instance per interview session."""

#     def __init__(self, session_id: str, checkpointer: Any = None):
#         self.session_id = session_id
#         self.config = {"configurable": {"thread_id": session_id}}
#         self.graph = build_graph(checkpointer) if checkpointer is not None else get_graph()

#     def start_interview(
#         self, cv_text: str, jd_text: str, candidate_name: str = ""
#     ) -> dict:
#         print(f">>> [InterviewSession.start_interview] session={self.session_id}")
#         snapshot = self.graph.get_state(self.config)
#         if snapshot.values.get("current_question"):
#             print(">>> [InterviewSession.start_interview] Resuming existing session")
#             return self._turn_payload(snapshot.values, resumed=True)
#         initial: InterviewState = {
#             "domains": [],
#             "current_domain_index": 0,
#             "domains_covered": [],
#             "follow_up_count": 0,
#             "current_question": "",
#             "current_answer": "",
#             "qa_pairs": [],
#             "proctor_flags": [],
#             "scores": None,
#             "interview_complete": False,
#             "cv_text": cv_text or "",
#             "jd_text": jd_text or "",
#             "candidate_name": candidate_name or "Candidate",
#             "session_id": self.session_id,
#         }
#         self.graph.invoke(initial, self.config)
#         snapshot = self.graph.get_state(self.config)
#         result = self._turn_payload(snapshot.values, resumed=False)
#         print(f">>> [InterviewSession.start_interview] Done — question='{result.get('question', '')[:80]}'")
#         return result

#     def submit_answer(self, answer_text: str) -> dict:
#         print(f">>> [InterviewSession.submit_answer] session={self.session_id} answer='{answer_text[:80]}'")
#         snapshot = self.graph.get_state(self.config)
#         if not snapshot.values.get("current_question"):
#             raise ValueError(
#                 f"No active interview for session {self.session_id}; call start_interview first"
#             )
#         if snapshot.values.get("interview_complete"):
#             print(">>> [InterviewSession.submit_answer] Interview already complete")
#             return self._turn_payload(snapshot.values, resumed=False)
#         self.graph.update_state(self.config, {"current_answer": (answer_text or "").strip()})
#         self.graph.invoke(None, self.config)
#         snapshot = self.graph.get_state(self.config)
#         result = self._turn_payload(snapshot.values, resumed=False)
#         print(f">>> [InterviewSession.submit_answer] Done — complete={result.get('interview_complete')} question='{str(result.get('question', ''))[:80]}'")
#         return result

#     def add_proctor_flag(self, event: str) -> None:
#         self.graph.update_state(self.config, {"proctor_flags": [event]})

#     def get_status(self) -> dict:
#         snapshot = self.graph.get_state(self.config)
#         return self._turn_payload(snapshot.values, resumed=False)

#     def _turn_payload(self, values: dict, resumed: bool) -> dict:
#         domains = values.get("domains", [])
#         index = min(values.get("current_domain_index", 0), max(0, len(domains) - 1))
#         return {
#             "session_id": self.session_id,
#             "candidate_name": values.get("candidate_name", ""),
#             "domains": domains,
#             "domain_index": index,
#             "current_domain": domains[index] if domains else None,
#             "follow_up_count": values.get("follow_up_count", 0),
#             "question": values.get("current_question"),
#             "interview_complete": bool(values.get("interview_complete")),
#             "scores": values.get("scores"),
#             "resumed": resumed,
#         }

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
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langchain_openai import ChatOpenAI

try:
    from langgraph.checkpoint.postgres import PostgresSaver
except ModuleNotFoundError:
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
    "Read the job description and candidate CV, then return ONLY a JSON object "
    "with exactly two keys:\n"
    "- \"summary\": a concise 150-word candidate profile covering total experience "
    "(or student/fresh graduate status), core technical skills, notable projects, "
    "and most recent role. Be factual — only include what is explicitly stated.\n"
    "- \"domains\": an array of exactly 2 short skill domain names (2-5 words each) "
    "that the company actually cares about for this role.\n\n"
    "Example: {\"summary\": \"Fresh CS graduate...\", \"domains\": [\"Backend APIs\", \"React Frontend\"]}\n"
    "No prose, no markdown, no extra keys."
)

_QUESTION_SYSTEM = (
    "You are TalimBot, a senior interviewer conducting a structured voice interview. "
    "Ask exactly ONE question per turn. Output only the question text — no preamble, "
    "no quotes, no labels.\n\n"

    "FOCUS RULE — the single most important rule:\n"
    "Every question must probe exactly ONE specific thing. Never list multiple "
    "components, steps, or sub-topics in the same question. "
    "Bad: \'Walk me through the models, serializers, auth flow, and performance optimizations.\' "
    "Good: \'How did you handle token expiry in your JWT setup?\' "
    "Pick the single most revealing aspect and ask only about that.\n\n"

    "OPENING QUESTIONS — first question in a domain:\n"
    "Anchor to one specific decision the candidate made, one problem they solved, "
    "or one tradeoff they faced in something they actually built. "
    "Do not ask them to walk through the whole system.\n\n"

    "FOLLOW-UP QUESTIONS — second question in the same domain:\n"
    "Look at the candidate\'s last answer. If they used a technical term or named "
    "a tool, dig into exactly that. If the answer was vague, ask for a concrete "
    "example or what it looked like in their actual code. Never switch topics.\n\n"

    "SPOKEN AUDIO FORMAT:\n"
    "Keep it under 50 words. Spell out abbreviations as full words: say \'JSON web token\' "
    "not \'JWT\', \'PostgreSQL\' not \'Postgres\', \'React\' not \'ReactJS\', "
    "\'versus\' not \'vs\'. No bullet points, slashes, parentheses, or special characters. "
    "Write as natural, conversational speech. Never start consecutive questions with "
    "the same opening words — vary your sentence openers every turn."
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


def get_llm() -> ChatOpenAI:
    global _model
    if _model is None:
        print(">>> [LLM] Initializing model: openai/gpt-oss-120b on Groq")
        _model = ChatOpenAI(
            model="openai/gpt-oss-120b",
            api_key=os.getenv("GROQ_API_KEY"),
            base_url="https://api.groq.com/openai/v1",
        )
    return _model


def _ask_llm(
    system: str,
    human: str,
    temperature: float = 0.7,
    max_tokens: int = 1024,
    reasoning_effort: Optional[str] = None,
) -> str:
    """
    Call the LLM with optional reasoning_effort.

    reasoning_effort must be one of: "low", "medium", "high", or None (disables reasoning).
    When None, reasoning is disabled by passing reasoning_effort="none" to the model.
    """
    llm = get_llm()

    bind_kwargs: dict[str, Any] = {
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    if reasoning_effort is None:
        # Explicitly disable reasoning
        bind_kwargs["reasoning_effort"] = "none"
    else:
        # Must be "low", "medium", or "high"
        if reasoning_effort not in ("low", "medium", "high"):
            raise ValueError(
                f"reasoning_effort must be 'low', 'medium', 'high', or None — got {reasoning_effort!r}"
            )
        bind_kwargs["reasoning_effort"] = reasoning_effort

    llm = llm.bind(**bind_kwargs)
    response = llm.invoke([SystemMessage(content=system), HumanMessage(content=human)])
    print(
        f">>> [_ask_llm] finish_reason={response.response_metadata.get('finish_reason')} "
        f"reasoning_tokens={response.response_metadata.get('token_usage', {}).get('reasoning_tokens')} "
        f"reasoning_effort={bind_kwargs['reasoning_effort']}"
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


_JOB_TITLE_SYSTEM = (
    "Extract only the job title from this job description. Return just the title, "
    "nothing else. If unclear, return 'Software Engineer'."
)


def extract_job_title(jd_text: str) -> str:
    try:
        title = _ask_llm(
            _JOB_TITLE_SYSTEM,
            (jd_text or "")[:2000],
            temperature=0.1,
            max_tokens=20,
            reasoning_effort=None,  # no reasoning needed for simple extraction
        )
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
    rephrased = _ask_llm(
        _PARAPHRASE_SYSTEM,
        question_text,
        temperature=0.7,
        max_tokens=180,
        reasoning_effort="low",  # low effort — simple rephrasing task
    )
    return rephrased.strip().strip('"').strip()


# -------------------------------------------------------------------------- nodes

def domain_extractor(state: InterviewState) -> dict:
    print(">>> [domain_extractor] ENTER")

    if state.get("domains") and state.get("cv_summary"):
        print(">>> [domain_extractor] Cache hit — skipping LLM call")
        return {}

    # max_tokens=1200: reasoning tokens can consume several hundred before the JSON
    # output begins, so 600 was too tight and risked a truncated / empty response.
    print(">>> [domain_extractor] Calling LLM (max_tokens=1200, reasoning_effort=medium)...")
    raw = _ask_llm(
        _EXTRACTOR_SYSTEM,
        "JOB DESCRIPTION:\n"
        + _clip(state.get("jd_text", ""), 6000)
        + "\n\nCANDIDATE CV:\n"
        + _clip(state.get("cv_text", ""), 6000),
        temperature=0.1,
        max_tokens=1200,
        reasoning_effort="low",
    )
    print(f">>> [domain_extractor] Raw response ({len(raw)} chars): {raw[:600]}")

    parsed = _extract_json(raw, "{")
    print(f">>> [domain_extractor] Parsed JSON: {parsed}")

    domains: list[str] = []
    cv_summary: str = ""

    if isinstance(parsed, dict):
        raw_domains = parsed.get("domains", [])
        domains = [d.strip() for d in raw_domains if isinstance(d, str) and d.strip()]
        cv_summary = str(parsed.get("summary", "")).strip()
        print(f">>> [domain_extractor] Domains extracted: {domains}")
        print(f">>> [domain_extractor] CV summary length: {len(cv_summary)} chars")
    else:
        print(f">>> [domain_extractor] JSON parse failed — parsed={parsed}")

    if len(domains) < 2:
        print(f">>> [domain_extractor] WARN: using default domains (got {domains})")
        domains = list(DEFAULT_DOMAINS)

    if not cv_summary:
        cv_summary = "No summary available."

    print(f">>> [domain_extractor] EXIT — domains={domains}")
    return {
        "domains": domains[:2],
        "current_domain_index": 0,
        "cv_summary": cv_summary,
    }


def question_generator(state: InterviewState) -> dict:
    print(">>> [question_generator] ENTER")
    print(f">>> [question_generator] qa_pairs={len(state.get('qa_pairs', []))}, domains_covered={state.get('domains_covered', [])}")

    if not state.get("qa_pairs") and not state.get("domains_covered"):
        print(">>> [question_generator] Returning hardcoded INTRO_QUESTION")
        return {"current_question": INTRO_QUESTION}

    domains = state["domains"]
    index = min(state.get("current_domain_index", 0), len(domains) - 1)
    domain = domains[index]
    name = state.get("candidate_name") or "Candidate"
    print(f">>> [question_generator] domain='{domain}' index={index} name='{name}'")

    qa_pairs = state.get("qa_pairs", [])
    domain_qa_count = sum(1 for p in qa_pairs if p["domain"] == domain)
    print(f">>> [question_generator] domain_qa_count={domain_qa_count}")

    last_answer_context = ""
    if qa_pairs:
        last_pair = qa_pairs[-1]
        if last_pair.get("domain") == domain:
            last_answer_context = f"Candidate's previous answer: {last_pair.get('answer', '')}"

    if domain_qa_count == 0:
        temp = 0.8
        human = (
            f"Opening the '{domain}' domain with {name}.\n"
            f"JOB DESCRIPTION (excerpt):\n{_clip(state.get('jd_text', ''), 1500)}\n\n"
            f"CANDIDATE PROFILE:\n{state.get('cv_summary', '')}\n\n"
            f"Ask ONE focused opening question about a single specific aspect of {domain}. "
            f"Anchor it to something the candidate actually built or decided in their profile. "
            f"Do NOT list multiple components or ask them to walk through the whole system. "
            f"Pick ONE decision, problem, or implementation detail and ask only about that."
        )
    else:
        temp = 0.7
        human = (
            f"Follow-up in the '{domain}' domain with {name}.\n"
            f"{last_answer_context}\n\n"
            f"Read the candidate's answer above carefully. "
            f"If they mentioned a specific tool, library, or technique, ask them to go deeper "
            f"into exactly that — how it works, why they chose it, or what tradeoffs they hit. "
            f"If the answer was vague or high-level, ask for a concrete example from their code "
            f"or project. ONE question only, ONE topic only. Do not repeat earlier questions."
        )

    # max_tokens must be large enough to cover reasoning tokens + the output text.
    # With reasoning_effort=medium, the model can spend several hundred tokens on
    # internal reasoning before emitting a single word of visible output — 300 was
    # too small and caused finish_reason=length with an empty response.
    print(f">>> [question_generator] Calling LLM (temp={temp}, max_tokens=1024, reasoning_effort=medium)...")
    raw_question = _ask_llm(
        _QUESTION_SYSTEM,
        human,
        temperature=temp,
        max_tokens=1024,
        reasoning_effort="low",
    )
    print(f">>> [question_generator] Raw LLM output: {repr(raw_question)}")
    question = raw_question.strip().strip('"').strip()
    print(f">>> [question_generator] After strip: {repr(question)}")

    # Guard: if the model returned nothing (finish_reason=length starved the output),
    # retry once without reasoning so we always get a usable question.
    if not question:
        print(">>> [question_generator] WARN: empty output — retrying without reasoning (reasoning_effort=None)...")
        raw_question = _ask_llm(
            _QUESTION_SYSTEM,
            human,
            temperature=temp,
            max_tokens=300,
            reasoning_effort=None,
        )
        print(f">>> [question_generator] Retry raw output: {repr(raw_question)}")
        question = raw_question.strip().strip('"').strip()
        print(f">>> [question_generator] Retry after strip: {repr(question)}")

    updates: dict = {"current_question": question}
    if domain_qa_count == 0:
        updates["domains_covered"] = [domain]

    print(f">>> [question_generator] EXIT — updates keys: {list(updates.keys())}")
    return updates


def answer_recorder(state: InterviewState) -> dict:
    print(">>> [answer_recorder] ENTER")
    question = state.get("current_question") or ""
    answer = (state.get("current_answer") or "").strip()
    print(f">>> [answer_recorder] question present={bool(question)}, answer present={bool(answer)}")
    if not question or not answer:
        print(">>> [answer_recorder] WARN: missing question or answer — returning empty")
        return {}
    domains = state["domains"]
    if not state.get("domains_covered"):
        domain = "Introduction"
    else:
        domain = domains[min(state.get("current_domain_index", 0), len(domains) - 1)]
    pair = {
        "domain": domain,
        "question": question,
        "answer": answer,
        "turn_number": len(state.get("qa_pairs", [])) + 1,
    }
    print(f">>> [answer_recorder] Recorded QA pair — domain='{domain}' turn={pair['turn_number']}")
    return {"qa_pairs": [pair]}


def coverage_tracker(state: InterviewState) -> dict:
    print(">>> [coverage_tracker] ENTER")
    total_questions = len(state.get("qa_pairs", []))
    print(f">>> [coverage_tracker] total_questions={total_questions}, MAX={MAX_QUESTIONS}")

    if total_questions >= MAX_QUESTIONS:
        print(">>> [coverage_tracker] Interview complete — routing to evaluator")
        return {"interview_complete": True}

    domains = state["domains"]
    if not domains:
        print(">>> [coverage_tracker] WARN: no domains in state")
        return {}

    next_index = (total_questions - 1) // 2 % len(domains)
    print(f">>> [coverage_tracker] next_domain_index={next_index} ({domains[next_index]})")
    return {"current_domain_index": next_index}


def route_after_coverage(state: InterviewState) -> str:
    route = "evaluator" if state.get("interview_complete") else "question_generator"
    print(f">>> [route_after_coverage] routing to: {route}")
    return route


def evaluator(state: InterviewState) -> dict:
    import time as _time
    print(">>> [evaluator] ENTER")
    if state.get("scores"):
        print(">>> [evaluator] Cache hit — scores already present")
        return {}

    # The evaluator fires immediately after the last question_generator call on the
    # same submit_answer turn. Together those two calls can burst ~5,000 tokens in
    # a few seconds. A 15-second pause lets Groq's rolling TPM window clear enough
    # headroom so the evaluator (~3,900 tok) lands cleanly under the 8,000 TPM limit
    # even in worst-case timing. This is invisible to the user — their final answer
    # audio is still playing / they are reading the "processing" screen.
    print(">>> [evaluator] Waiting 7s to clear TPM window before evaluation call...")
    _time.sleep(7)

    transcript = "\n\n".join(
        f"[{p['domain']}] Q: {p['question']}\nA: {p['answer']}"
        for p in state.get("qa_pairs", [])
    )
    print(f">>> [evaluator] Transcript length: {len(transcript)} chars, QA pairs: {len(state.get('qa_pairs', []))}")

    notes = ""
    if state.get("proctor_flags"):
        notes = "\nPROCTORING NOTES (consider when judging validity): " + "; ".join(
            state["proctor_flags"]
        )

    print(">>> [evaluator] Calling LLM (max_tokens=3500, reasoning_effort=medium)...")
    raw = _ask_llm(
        _EVALUATOR_SYSTEM,
        f"Domains assessed: {json.dumps(state.get('domains', []))}\n\n"
        f"JOB DESCRIPTION (excerpt):\n{_clip(state.get('jd_text', ''), 3000)}\n\n"
        f"CANDIDATE PROFILE:\n{state.get('cv_summary', '')}\n\n"
        f"FULL INTERVIEW TRANSCRIPT:\n{transcript}{notes}",
        temperature=0.1,
        max_tokens=3500,
        reasoning_effort="medium",
    )
    print(f">>> [evaluator] Raw response ({len(raw)} chars): {raw[:300]}...")

    parsed = _extract_json(raw, "{")
    print(f">>> [evaluator] JSON parsed successfully: {parsed is not None}")

    scores = _normalize_scores(
        parsed if isinstance(parsed, dict) else None,
        state.get("domains", []),
    )
    print(f">>> [evaluator] Final scores — overall={scores.get('overall_score')}, recommendation={scores.get('hire_recommendation')}")
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
            entry["expected_highlights"] = [
                s for s in (raw.get("expected_highlights") or []) if isinstance(s, str)
            ]
            entry["question_notes"] = [
                s for s in (raw.get("question_notes") or []) if isinstance(s, str)
            ]
            domain_scores[d] = entry
        else:
            domain_scores[d] = _clamp(raw)

    # ── Grace marks ──────────────────────────────────────────────────────────
    # LLM evaluators tend to score conservatively. Add +0.5 to every domain
    # score and +1.0 to overall, capped at 10.0, to correct for this bias.
    GRACE_DOMAIN = 0.5
    GRACE_OVERALL = 1.0
    for d in domain_scores:
        entry = domain_scores[d]
        if isinstance(entry, dict):
            entry["score"] = round(min(10.0, entry["score"] + GRACE_DOMAIN), 1)
        else:
            domain_scores[d] = round(min(10.0, entry + GRACE_DOMAIN), 1)

    values = [v["score"] if isinstance(v, dict) else v for v in domain_scores.values()]
    raw_overall = _clamp(
        parsed.get("overall_score"),
        default=round(sum(values) / max(1, len(values)), 1),
    )
    overall = round(min(10.0, raw_overall + GRACE_OVERALL), 1)

    # Re-derive recommendation from the grace-adjusted overall score
    recommendation = (
        "Strong hire" if overall >= 8
        else "Hire" if overall >= 6.5
        else "Lean hire" if overall >= 5
        else "No hire"
    )
    detailed = parsed.get("detailed_feedback") or {}
    strengths = [
        s for s in (detailed.get("strengths") or parsed.get("strengths") or [])
        if isinstance(s, str)
    ]
    improvements = [
        s for s in (detailed.get("improvements") or parsed.get("improvements") or [])
        if isinstance(s, str)
    ]
    tips = [
        s for s in (detailed.get("interview_tips") or parsed.get("interview_tips") or [])
        if isinstance(s, str)
    ]
    summary = str(
        parsed.get("summary_feedback") or parsed.get("summary") or "No summary provided."
    )
    return {
        "domain_scores": domain_scores,
        "overall_score": overall,
        "hire_recommendation": recommendation,
        "strengths": strengths,
        "improvements": improvements,
        "summary": summary,
        "summary_feedback": summary,
        "detailed_feedback": {
            "strengths": strengths,
            "improvements": improvements,
            "interview_tips": tips,
        },
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
    conn_string = (
        os.getenv("DATABASE_URL", "")
        .replace("+asyncpg", "")
        .replace("+psycopg", "")
    )
    try:
        _default_checkpointer_cm = PostgresSaver.from_conn_string(conn_string)
        saver = _default_checkpointer_cm.__enter__()
        saver.setup()
        _default_checkpointer = saver
    except Exception as exc:
        logger.warning(
            "PostgresSaver unavailable (%s); falling back to in-memory checkpoints", exc
        )
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

    def start_interview(
        self, cv_text: str, jd_text: str, candidate_name: str = ""
    ) -> dict:
        print(f">>> [InterviewSession.start_interview] session={self.session_id}")
        snapshot = self.graph.get_state(self.config)
        if snapshot.values.get("current_question"):
            print(">>> [InterviewSession.start_interview] Resuming existing session")
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
        result = self._turn_payload(snapshot.values, resumed=False)
        print(f">>> [InterviewSession.start_interview] Done — question='{result.get('question', '')[:80]}'")
        return result

    def submit_answer(self, answer_text: str) -> dict:
        print(f">>> [InterviewSession.submit_answer] session={self.session_id} answer='{answer_text[:80]}'")
        snapshot = self.graph.get_state(self.config)
        if not snapshot.values.get("current_question"):
            raise ValueError(
                f"No active interview for session {self.session_id}; call start_interview first"
            )
        if snapshot.values.get("interview_complete"):
            print(">>> [InterviewSession.submit_answer] Interview already complete")
            return self._turn_payload(snapshot.values, resumed=False)
        self.graph.update_state(self.config, {"current_answer": (answer_text or "").strip()})
        self.graph.invoke(None, self.config)
        snapshot = self.graph.get_state(self.config)
        result = self._turn_payload(snapshot.values, resumed=False)
        print(f">>> [InterviewSession.submit_answer] Done — complete={result.get('interview_complete')} question='{str(result.get('question', ''))[:80]}'")
        return result

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