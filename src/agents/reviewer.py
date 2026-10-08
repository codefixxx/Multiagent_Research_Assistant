"""Reviewer Specialist Agent.

Evaluates researcher findings against sub-question requirements to determine
whether a single revision pass is justified or if work is approved.
"""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate

from src.core.llm import extract_token_usage, get_chat_model
from src.core.logger import logger
from src.core.telemetry import ExecutionTimer, TokenUsage
from src.schemas.finding import FindingRecord
from src.schemas.plan import SubQuestion
from src.schemas.review import ReviewEvaluation

REVIEWER_SYSTEM_PROMPT = """You are a research quality verification engine.
Your sole job is to review gathered findings against a specific sub-question and determine if the findings are sufficient or need one revision.

STRICT OPERATIONAL RULES:
1. Approve (is_approved=true) if findings contain factual claims, concrete data, or metrics addressing the question.
2. Reject (is_approved=false) ONLY if findings are completely missing, completely off-topic, or lack any factual claims.
3. If rejecting, list exactly 1 to 2 missing aspects in `missing_aspects` to guide a single revision pass.
4. If findings are empty because no data exists, approve with a low quality score so the pipeline does not waste budget.
5. You must return your output strictly matching the provided ReviewEvaluation schema.
"""

REVIEWER_HUMAN_PROMPT = """Evaluate whether these findings adequately answer the sub-question:

Sub-Question ID: {sub_question_id}
Sub-Question: {question}
Rationale: {rationale}

Gathered Findings:
{findings_text}
"""


def format_findings_for_review(findings: list[FindingRecord]) -> str:
    """Format finding records into concise review prompt text."""
    if not findings:
        return "No findings recorded in this pass."
    lines = []
    for f in findings:
        lines.append(f"- Claim: {f.claim} (Source: {f.source_url})")
    return "\n".join(lines)


async def evaluate_research(
    sub_question: SubQuestion,
    findings: list[FindingRecord],
    llm: BaseChatModel | None = None,
) -> tuple[ReviewEvaluation, TokenUsage, float]:
    """Execute the reviewer specialist in isolation against gathered findings.

    Args:
        sub_question: The SubQuestion being investigated.
        findings: The findings gathered by the researcher for this sub-question.
        llm: Optional chat model instance.

    Returns:
        Tuple of (ReviewEvaluation, TokenUsage, latency_ms).
    """
    model = llm or get_chat_model()
    structured_llm = model.with_structured_output(ReviewEvaluation, include_raw=True)

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", REVIEWER_SYSTEM_PROMPT),
            ("human", REVIEWER_HUMAN_PROMPT),
        ]
    )

    findings_text = format_findings_for_review(findings)
    formatted_messages = prompt.format_messages(
        sub_question_id=sub_question.id,
        question=sub_question.question,
        rationale=sub_question.rationale,
        findings_text=findings_text,
    )

    timer = ExecutionTimer()
    with timer:
        raw_result = await structured_llm.ainvoke(formatted_messages)

    if isinstance(raw_result, dict) and "parsed" in raw_result:
        evaluation: ReviewEvaluation = raw_result["parsed"]
        raw_response = raw_result.get("raw")
        token_usage = extract_token_usage(raw_response)
    elif isinstance(raw_result, ReviewEvaluation):
        evaluation = raw_result
        token_usage = TokenUsage()
    else:
        raise ValueError(f"Failed to produce valid ReviewEvaluation: {raw_result}")

    logger.info(
        "Reviewer completed evaluation",
        sub_question_id=sub_question.id,
        is_approved=evaluation.is_approved,
        quality_score=evaluation.quality_score,
        latency_ms=timer.elapsed_ms,
        tokens=token_usage.total_tokens,
    )

    return evaluation, token_usage, timer.elapsed_ms
