"""Pydantic schemas for the Writer Specialist and verified report output."""

import re

from pydantic import BaseModel, Field


def normalize_citation_token(token: str) -> str | None:
    """Normalize a single citation token like 'cite1', 'cite_1', '1', 'cite:1' to 'cite_1'.

    Returns normalized token without brackets (e.g. 'cite_1') if valid, else None.
    """
    cleaned = token.strip().strip("[]").strip()
    if not cleaned:
        return None
    if cleaned.isdigit():
        return f"cite_{cleaned}"
    m = re.match(r"^cite[_:]?(\d+)$", cleaned, re.IGNORECASE)
    if m:
        return f"cite_{m.group(1)}"
    if cleaned.lower().startswith("cite"):
        return cleaned.lower()
    return None


def normalize_inline_citations(text: str) -> str:
    """Normalize all inline citations in text into standard separate bracketed citations.

    Converts grouped or non-standard citations:
        '[cite1,cite2]' -> '[cite_1] [cite_2]'
        '[cite_1, cite_2]' -> '[cite_1] [cite_2]'
        '[1, 2]' -> '[cite_1] [cite_2]'
        '[cite1]' -> '[cite_1]'
    while leaving non-citation brackets like '[Note]' or markdown links intact.
    """
    if not text:
        return ""

    def _replace_group(match: re.Match) -> str:
        inner = match.group(1).strip()
        parts = [p.strip() for p in re.split(r"[,;]+", inner) if p.strip()]
        if not parts:
            return match.group(0)

        norm_tokens: list[str] = []
        for p in parts:
            norm = normalize_citation_token(p)
            if norm is None:
                return match.group(0)
            norm_tokens.append(f"[{norm}]")

        return " ".join(norm_tokens)

    # Match brackets not preceded by '!' and not followed by '('
    return re.sub(r"(?<!\!)\[([a-zA-Z0-9_:\s,;-]+)\](?!\()", _replace_group, text)


class Citation(BaseModel):
    """Citation metadata linking an inline reference to an underlying verified source URL."""

    citation_id: str = Field(description="Unique reference identifier, e.g., 'cite_1' or '[1]'")
    source_url: str = Field(description="URL of the referenced source")
    verified_claim: str = Field(
        description="Specific finding or claim substantiated by this source"
    )
    anchor_url: str = Field(
        default="",
        description="Deep-link URL with browser text-fragment anchor (#:~:text=...) jumping directly to the cited text.",
    )
    verbatim_quote: str = Field(
        default="",
        description="Direct verbatim excerpt from the source webpage substantiating the claim.",
    )
    http_status: int = Field(
        default=200,
        description="Verified HTTP status code for this link (e.g., 200).",
    )
    is_deep_link: bool = Field(
        default=True,
        description="Whether this link points to a specific article/doc subpage rather than a generic root domain.",
    )


class ReportSection(BaseModel):
    """A cohesive section of the final research report."""

    title: str = Field(description="Section heading")
    content: str = Field(
        description="Factual narrative synthesising findings with inline citation markers like [cite_1]."
    )
    citation_ids: list[str] = Field(
        default_factory=list,
        description="List of citation IDs referenced in this section.",
    )


class ResearchReport(BaseModel):
    """Fully synthesized research report with validated citations and executive summary."""

    title: str = Field(description="High-level title of the research report")
    executive_summary: str = Field(
        description="Concise, high-impact executive summary answering the root question."
    )
    sections: list[ReportSection] = Field(
        description="Structured thematic sections detailing the findings."
    )
    citations: list[Citation] = Field(
        default_factory=list,
        description="List of validated citations utilized across all report sections.",
    )
    markdown_output: str = Field(
        default="",
        description="Full compiled Markdown representation of the report.",
    )

    def compile_markdown(self) -> str:
        """Helper to generate clean Markdown text from structured report fields."""
        if self.executive_summary:
            self.executive_summary = normalize_inline_citations(self.executive_summary)
        for sec in self.sections:
            if sec.content:
                sec.content = normalize_inline_citations(sec.content)

        md_lines = [
            f"# {self.title}\n",
            "## Executive Summary",
            f"{self.executive_summary}\n",
        ]
        for sec in self.sections:
            md_lines.append(f"## {sec.title}")
            md_lines.append(f"{sec.content}\n")

        if self.citations:
            md_lines.append("## References & Citations")
            for cite in self.citations:
                target_url = cite.anchor_url or cite.source_url
                quote_suffix = f' — Quote: "_{cite.verbatim_quote}_"' if cite.verbatim_quote else ""
                md_lines.append(
                    f"- **{cite.citation_id}**: [{cite.source_url}]({target_url}) - _{cite.verified_claim}_{quote_suffix}"
                )

        self.markdown_output = "\n".join(md_lines)
        return self.markdown_output
