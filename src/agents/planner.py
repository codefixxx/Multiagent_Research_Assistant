"""Planner Specialist Agent.

Decomposes a broad research query into 2 to 4 atomic, factual, non-overlapping sub-questions.
Enforces Pydantic schema validation.
"""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate

from src.core.llm import extract_token_usage, get_chat_model
from src.core.logger import logger
from src.core.telemetry import ExecutionTimer, TokenUsage
from src.schemas.plan import ResearchPlan, SubQuestionStatus

PLANNER_SYSTEM_PROMPT = """You are a technical research decomposition engine.
Your sole job is to take a research question and break it down into 2 to 4 distinct, non-overlapping, and factual sub-questions.

STRICT OPERATIONAL RULES:
1. Every sub-question must be atomic, precise, and answerable through web searches.
2. Avoid generic questions like "What is X?" or "What are future trends?".
3. Focus on concrete technical aspects, historical data, architecture, benchmarks, or explicit tradeoffs.
4. For each sub-question, provide 1 to 3 targeted search query strings optimized for search engines.
5. Do not include fluff, conversational greetings, or subjective filler.
6. You must return your output strictly matching the provided ResearchPlan schema.
"""

PLANNER_HUMAN_PROMPT = """Decompose this research query into a structured research plan:
Research Query: {query}
"""


async def plan_research(
    query: str,
    llm: BaseChatModel | None = None,
) -> tuple[ResearchPlan, TokenUsage, float]:
    """Execute the planner specialist in isolation.

    Args:
        query: The user's research query.
        llm: Optional chat model instance. If None, default model is instantiated.

    Returns:
        Tuple of (ResearchPlan, TokenUsage, latency_ms).
    """
    model = llm or get_chat_model()
    structured_llm = model.with_structured_output(ResearchPlan, include_raw=True)

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", PLANNER_SYSTEM_PROMPT),
            ("human", PLANNER_HUMAN_PROMPT),
        ]
    )

    formatted_messages = prompt.format_messages(query=query)

    timer = ExecutionTimer()
    with timer:
        raw_result = await structured_llm.ainvoke(formatted_messages)

    # raw_result has keys: 'raw', 'parsed', 'parsing_error'
    if isinstance(raw_result, dict) and "parsed" in raw_result:
        parsed_plan: ResearchPlan = raw_result["parsed"]
        raw_response = raw_result.get("raw")
        token_usage = extract_token_usage(raw_response)
    elif isinstance(raw_result, ResearchPlan):
        parsed_plan = raw_result
        token_usage = TokenUsage()
    else:
        raise ValueError(f"Failed to produce valid ResearchPlan: {raw_result}")

    # Ensure all sub-questions are initialized with pending status
    for sq in parsed_plan.sub_questions:
        sq.status = SubQuestionStatus.PENDING

    logger.info(
        "Planner generated research plan",
        query=query,
        sub_questions_count=len(parsed_plan.sub_questions),
        latency_ms=timer.elapsed_ms,
        tokens=token_usage.total_tokens,
    )

    return parsed_plan, token_usage, timer.elapsed_ms
