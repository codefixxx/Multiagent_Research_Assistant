"""Pydantic schemas for the Writer Specialist and verified report output."""

from pydantic import BaseModel, Field


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
                quote_suffix = f" — Quote: \"_{cite.verbatim_quote}_\"" if cite.verbatim_quote else ""
                md_lines.append(
                    f"- **{cite.citation_id}**: [{cite.source_url}]({target_url}) - _{cite.verified_claim}_{quote_suffix}"
                )

        self.markdown_output = "\n".join(md_lines)
        return self.markdown_output
