"""Writer Specialist Agent.

Synthesizes collected factual findings into a structured technical report
with validated citations and an executive summary.
"""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate

from src.core.llm import extract_token_usage, get_chat_model
from src.core.logger import logger
from src.core.telemetry import ExecutionTimer, TokenUsage
from src.schemas.finding import FindingRecord
from src.schemas.report import ResearchReport

WRITER_SYSTEM_PROMPT = """You are a technical report synthesis specialist.
Your sole responsibility is to synthesize a collection of verified factual findings into a cohesive, publication-ready research report.

STRICT OPERATIONAL RULES:
1. Every major factual claim or metric must include an inline citation marker, e.g., '[cite_1]', '[cite_2]'.
2. Only make claims that are explicitly supported by the provided Finding Records. Do not invent citations or facts.
3. Every citation referenced in the text must be listed in the `citations` array with its exact source URL and verified claim.
4. Structure the report logically with a concise executive summary and thematic technical sections.
5. Output must strictly conform to the ResearchReport schema.
"""

WRITER_HUMAN_PROMPT = """Synthesize a research report for the following query based strictly on the verified findings below:

Research Query: {query}

Verified Findings:
{findings_text}
"""


def format_findings_for_writer(findings: list[FindingRecord]) -> str:
    """Format finding records into structured prompt text with assigned citation IDs."""
    if not findings:
        return "No findings available. Provide a best-effort report stating insufficient data."

    lines = []
    for i, finding in enumerate(findings, start=1):
        lines.append(
            f"Citation ID: [cite_{i}]\n"
            f"- SubQuestion: {finding.sub_question_id}\n"
            f"- Source URL: {finding.source_url}\n"
            f"- Claim: {finding.claim}\n"
            f"- Source Snippet: {finding.snippet}\n"
        )
    return "\n".join(lines)


async def write_report(
    query: str,
    findings: list[FindingRecord],
    llm: BaseChatModel | None = None,
) -> tuple[ResearchReport, TokenUsage, float]:
    """Execute the writer specialist in isolation against gathered findings.

    Args:
        query: The overarching research query.
        findings: The list of accumulated FindingRecord objects.
        llm: Optional chat model instance.

    Returns:
        Tuple of (ResearchReport, TokenUsage, latency_ms).
    """
    model = llm or get_chat_model()
    structured_llm = model.with_structured_output(ResearchReport, include_raw=True)

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", WRITER_SYSTEM_PROMPT),
            ("human", WRITER_HUMAN_PROMPT),
        ]
    )

    findings_text = format_findings_for_writer(findings)
    formatted_messages = prompt.format_messages(
        query=query,
        findings_text=findings_text,
    )

    timer = ExecutionTimer()
    with timer:
        raw_result = await structured_llm.ainvoke(formatted_messages)

    if isinstance(raw_result, dict) and "parsed" in raw_result:
        report: ResearchReport = raw_result["parsed"]
        raw_response = raw_result.get("raw")
        token_usage = extract_token_usage(raw_response)
    elif isinstance(raw_result, ResearchReport):
        report = raw_result
        token_usage = TokenUsage()
    else:
        raise ValueError(f"Failed to produce valid ResearchReport: {raw_result}")

    # Compile the full markdown text representation
    report.compile_markdown()

    logger.info(
        "Writer completed research report synthesis",
        title=report.title,
        sections_count=len(report.sections),
        citations_count=len(report.citations),
        latency_ms=timer.elapsed_ms,
        tokens=token_usage.total_tokens,
    )

    return report, token_usage, timer.elapsed_ms
