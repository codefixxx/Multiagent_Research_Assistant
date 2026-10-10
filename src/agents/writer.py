"""Writer Specialist Agent.

Synthesizes collected factual findings into a structured technical report
with validated citations and an executive summary.
"""

import re
import urllib.parse

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate

from src.core.llm import extract_token_usage, get_chat_model
from src.core.logger import logger
from src.core.telemetry import ExecutionTimer, TokenUsage
from src.schemas.finding import FindingRecord
from src.schemas.report import Citation, ResearchReport

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


def create_text_fragment_url(url: str, text_quote: str) -> str:
    """Generate a W3C browser text-fragment anchor URL (#:~:text=...) jumping directly to the quote."""
    if not url or not text_quote:
        return url
    try:
        base_url = url.split("#")[0]
        # Clean quote: remove special markdown or formatting characters
        clean_text = re.sub(r"[^\w\s\-\.]", " ", text_quote).strip()
        words = clean_text.split()
        if not words:
            return url
        # Use first 5-7 meaningful words for precision
        target_phrase = " ".join(words[:6])
        encoded = urllib.parse.quote(target_phrase)
        return f"{base_url}#:~:text={encoded}"
    except Exception:
        return url


def format_findings_for_writer(findings: list[FindingRecord]) -> str:
    """Format finding records into structured prompt text with assigned citation IDs."""
    if not findings:
        return "No findings available. Provide a best-effort report stating insufficient data."

    lines = []
    for i, finding in enumerate(findings, start=1):
        snippet = finding.snippet.strip()
        if len(snippet) > 300:
            snippet = snippet[:297] + "..."
        lines.append(
            f"Citation ID: [cite_{i}]\n"
            f"- SubQuestion: {finding.sub_question_id}\n"
            f"- Source URL: {finding.source_url}\n"
            f"- Claim: {finding.claim}\n"
            f"- Source Snippet: {snippet}\n"
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

    # --- DETERMINISTIC CITATION RECONCILIATION & BINDING ---
    citation_id_map: dict[str, FindingRecord] = {}
    for i, finding in enumerate(findings, start=1):
        cid = f"cite_{i}"
        citation_id_map[cid] = finding

    # Scan report text for all referenced citation tokens
    cite_matches = re.findall(r"\[(cite_?\d+|\d+)\]", report.executive_summary or "", re.IGNORECASE)
    for sec in report.sections:
        cite_matches.extend(re.findall(r"\[(cite_?\d+|\d+)\]", sec.content or "", re.IGNORECASE))
        for cid in sec.citation_ids:
            cite_matches.append(cid)

    normalized_referenced: list[str] = []
    seen_cids: set[str] = set()
    for raw in cite_matches:
        cleaned = raw.strip("[]").strip()
        if cleaned.isdigit():
            norm = f"cite_{cleaned}"
        elif not cleaned.lower().startswith("cite_"):
            norm = f"cite_{cleaned.lower().replace('cite', '')}"
        else:
            norm = cleaned.lower()

        if norm not in seen_cids:
            seen_cids.add(norm)
            normalized_referenced.append(norm)

    compiled_citations: list[Citation] = []
    bound_cid_set: set[str] = set()

    # Pass 1: Keep citations already declared by LLM if they map to valid ground-truth findings
    for c in report.citations or []:
        cleaned_cid = c.citation_id.strip("[]").strip()
        norm_cid = f"cite_{cleaned_cid}" if cleaned_cid.isdigit() else cleaned_cid.lower()
        if norm_cid in citation_id_map and norm_cid not in bound_cid_set:
            matched_finding = citation_id_map[norm_cid]
            compiled_citations.append(
                Citation(
                    citation_id=f"[{norm_cid}]",
                    source_url=matched_finding.source_url,
                    verified_claim=c.verified_claim or matched_finding.claim,
                    verbatim_quote=matched_finding.snippet[:180],
                    anchor_url=create_text_fragment_url(
                        matched_finding.source_url, matched_finding.snippet
                    ),
                    is_deep_link=bool(matched_finding.is_deep_link),
                )
            )
            bound_cid_set.add(norm_cid)

    # Pass 2: Auto-bind ANY citation referenced in the text that the LLM forgot to declare
    for norm in normalized_referenced:
        if norm in citation_id_map and norm not in bound_cid_set:
            matched_finding = citation_id_map[norm]
            compiled_citations.append(
                Citation(
                    citation_id=f"[{norm}]",
                    source_url=matched_finding.source_url,
                    verified_claim=matched_finding.claim,
                    verbatim_quote=matched_finding.snippet[:180],
                    anchor_url=create_text_fragment_url(
                        matched_finding.source_url, matched_finding.snippet
                    ),
                    is_deep_link=bool(matched_finding.is_deep_link),
                )
            )
            bound_cid_set.add(norm)

    def _cite_sort_key(c: Citation) -> int:
        num_m = re.search(r"\d+", c.citation_id)
        return int(num_m.group()) if num_m else 999

    compiled_citations.sort(key=_cite_sort_key)
    report.citations = compiled_citations

    # Filter section.citation_ids to reflect real verified citations
    for sec in report.sections:
        sec_matches = re.findall(r"\[(cite_?\d+|\d+)\]", sec.content or "", re.IGNORECASE)
        valid_sec_cids = []
        for sm in sec_matches:
            cleaned = sm.strip("[]").strip()
            norm = f"cite_{cleaned}" if cleaned.isdigit() else cleaned.lower()
            if norm in bound_cid_set and f"[{norm}]" not in valid_sec_cids:
                valid_sec_cids.append(f"[{norm}]")
        sec.citation_ids = valid_sec_cids

    # Compile the full markdown text representation with active deep anchors
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
