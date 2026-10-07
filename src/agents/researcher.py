"""Researcher Specialist Agent.

Investigates an individual sub-question using search context and extracts factual findings
with complete source URL, snippet, and timestamp provenance.
"""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate

from src.core.llm import extract_token_usage, get_chat_model
from src.core.logger import logger
from src.core.telemetry import ExecutionTimer, TokenUsage
from src.schemas.finding import ResearcherOutput
from src.schemas.plan import SubQuestion

RESEARCHER_SYSTEM_PROMPT = """You are a rigorous technical research specialist.
Your sole job is to investigate one specific sub-question and extract factual findings with strict provenance.

STRICT OPERATIONAL RULES:
1. Every finding must state a concrete factual claim or statistic directly substantiated by the provided source text.
2. Every finding must retain the exact source URL and a verifiable snippet from that source.
3. Skip generic summaries. We need atomic claims that can be cited in a technical report.
4. Assess whether the sub-question has been adequately answered (`is_answered=True/False`).
5. Output must strictly conform to the ResearcherOutput schema.
"""

RESEARCHER_HUMAN_PROMPT = """Investigate the following sub-question based on the evidence provided:

Sub-Question ID: {sub_question_id}
Sub-Question: {question}
Rationale: {rationale}

Search & Source Evidence Context:
{evidence_context}
"""


async def research_subquestion(
    sub_question: SubQuestion,
    evidence_context: str,
    llm: BaseChatModel | None = None,
) -> tuple[ResearcherOutput, TokenUsage, float]:
    """Execute the researcher specialist in isolation against provided evidence context.

    Args:
        sub_question: The SubQuestion model to research.
        evidence_context: String containing raw scraped documents, snippets, and source URLs.
        llm: Optional chat model instance.

    Returns:
        Tuple of (ResearcherOutput, TokenUsage, latency_ms).
    """
    model = llm or get_chat_model()
    structured_llm = model.with_structured_output(ResearcherOutput, include_raw=True)

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", RESEARCHER_SYSTEM_PROMPT),
            ("human", RESEARCHER_HUMAN_PROMPT),
        ]
    )

    formatted_messages = prompt.format_messages(
        sub_question_id=sub_question.id,
        question=sub_question.question,
        rationale=sub_question.rationale,
        evidence_context=evidence_context or "No search results returned for this query.",
    )

    timer = ExecutionTimer()
    with timer:
        raw_result = await structured_llm.ainvoke(formatted_messages)

    if isinstance(raw_result, dict) and "parsed" in raw_result:
        output: ResearcherOutput = raw_result["parsed"]
        raw_response = raw_result.get("raw")
        token_usage = extract_token_usage(raw_response)
    elif isinstance(raw_result, ResearcherOutput):
        output = raw_result
        token_usage = TokenUsage()
    else:
        raise ValueError(f"Failed to produce valid ResearcherOutput: {raw_result}")

    # Ensure findings are tied to the sub-question id
    for finding in output.findings:
        finding.sub_question_id = sub_question.id

    logger.info(
        "Researcher completed sub-question investigation",
        sub_question_id=sub_question.id,
        findings_count=len(output.findings),
        is_answered=output.is_answered,
        latency_ms=timer.elapsed_ms,
        tokens=token_usage.total_tokens,
    )

    return output, token_usage, timer.elapsed_ms
