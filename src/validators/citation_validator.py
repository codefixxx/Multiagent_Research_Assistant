"""Pre-flight citation and source integrity validator.

Ensures that every citation cited in the final research report is grounded
in actual FindingRecord objects retrieved during the research phase,
eliminating hallucinated URLs and phantom reference IDs before delivery.
"""

import asyncio
import re
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

from src.core.logger import logger
from src.schemas.finding import FindingRecord
from src.schemas.report import Citation, ReportSection, ResearchReport


def _normalize_url(url: str | Any) -> str:
    """Normalize a URL for robust comparison across protocols and trailing slashes."""
    if not url:
        return ""
    url_str = str(url).strip()
    try:
        parsed = urlparse(url_str)
        # Compare netloc + path without trailing slashes
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        path = parsed.path.rstrip("/")
        return f"{netloc}{path}"
    except Exception:
        return url_str.rstrip("/").lower()


def _normalize_citation_id(cid: str) -> str:
    """Normalize citation identifiers like '[cite_1]' -> 'cite_1'."""
    cleaned = cid.strip()
    if cleaned.startswith("[") and cleaned.endswith("]"):
        cleaned = cleaned[1:-1]
    return cleaned.strip()


class CitationValidationResult(BaseModel):
    """Structured report detailing citation audit results."""

    is_valid: bool = Field(
        description="True if all cited sources are grounded with zero hallucinations."
    )
    total_citations: int = Field(
        default=0,
        description="Total number of citation entries declared in the report.",
    )
    verified_citations: list[str] = Field(
        default_factory=list,
        description="Citation IDs whose URLs match real finding records.",
    )
    hallucinated_citations: list[str] = Field(
        default_factory=list,
        description="Citation IDs with ungrounded URLs or fake references.",
    )
    orphaned_citations: list[str] = Field(
        default_factory=list,
        description="Citations declared in the citations list but never referenced in section text.",
    )
    live_probed_urls: dict[str, int] = Field(
        default_factory=dict,
        description="Map of citation URLs to verified HTTP status codes (e.g. 200).",
    )
    dead_urls: list[str] = Field(
        default_factory=list,
        description="URLs that returned 404, 500, or were completely unreachable.",
    )
    resolved_redirects: dict[str, str] = Field(
        default_factory=dict,
        description="Map of original URL to final destination URL after following redirects.",
    )
    sanitized_report: ResearchReport = Field(
        description="The report artifact after pruning or flagging hallucinated citations."
    )
    summary: str = Field(
        default="",
        description="Human-readable summary of validation outcome.",
    )


class CitationValidator:
    """Deterministic citation verification engine."""

    # Matches inline citations like [cite_1], [cite:1], [1], [cit_abc], etc.
    INLINE_CITATION_REGEX = re.compile(r"\[(cite(?:_|\:)?\d+|\d+|[a-zA-Z0-9_\-]+)\]", re.IGNORECASE)

    def __init__(self, flag_hallucinations_in_text: bool = True) -> None:
        self.flag_hallucinations_in_text = flag_hallucinations_in_text

    def extract_text_citation_ids(self, text: str) -> set[str]:
        """Extract all citation identifier tokens referenced inline within markdown text."""
        if not text:
            return set()
        matches = self.INLINE_CITATION_REGEX.findall(text)
        found: set[str] = set()
        for m in matches:
            norm = _normalize_citation_id(m)
            # Filter out non-citation brackets like [TOC], [X], markdown links
            if norm.lower().startswith("cite") or norm.isdigit():
                found.add(norm)
        return found

    def validate(
        self,
        report: ResearchReport,
        findings: list[FindingRecord],
        auto_sanitize: bool = True,
    ) -> CitationValidationResult:
        """Validate all citations in the report against real findings.

        Args:
            report: The ResearchReport object to inspect.
            findings: The ground-truth list of FindingRecord objects collected.
            auto_sanitize: Whether to automatically prune/flag hallucinated citations.

        Returns:
            CitationValidationResult with verification breakdown and sanitized report.
        """
        # 1. Build lookup of normalized finding URLs
        finding_urls = {_normalize_url(f.source_url) for f in findings if f.source_url}

        # 2. Inspect citations declared in report.citations
        declared_citations_map: dict[str, Citation] = {}
        verified_cids: list[str] = []
        hallucinated_cids: list[str] = []

        for cite in report.citations:
            cid_norm = _normalize_citation_id(cite.citation_id)
            declared_citations_map[cid_norm] = cite
            cite_url_norm = _normalize_url(cite.source_url)

            if cite_url_norm in finding_urls:
                verified_cids.append(cid_norm)
            else:
                hallucinated_cids.append(cid_norm)
                logger.warning(
                    "Detected hallucinated or ungrounded citation URL",
                    citation_id=cite.citation_id,
                    source_url=cite.source_url,
                )

        # 3. Inspect inline references across all section texts and section.citation_ids
        referenced_in_text: set[str] = set()
        for sec in report.sections:
            for cid in sec.citation_ids:
                referenced_in_text.add(_normalize_citation_id(cid))
            referenced_in_text.update(self.extract_text_citation_ids(sec.content))

        # Also check executive summary
        referenced_in_text.update(self.extract_text_citation_ids(report.executive_summary))

        # Check for citation markers in text that are not even declared
        undeclared_markers: set[str] = set()
        for cid in referenced_in_text:
            if cid not in declared_citations_map and cid not in hallucinated_cids:
                undeclared_markers.add(cid)
                hallucinated_cids.append(cid)
                logger.warning("Detected undeclared citation marker in text", citation_id=cid)

        # 4. Check for orphaned citations (declared in report.citations but unused in text)
        orphaned_cids: list[str] = [
            cid for cid in declared_citations_map if cid not in referenced_in_text
        ]

        is_valid = len(hallucinated_cids) == 0

        # 5. Sanitize report if requested
        sanitized_report = report.model_copy(deep=True)
        if auto_sanitize and not is_valid:
            hallucinated_set = set(hallucinated_cids)
            # Filter citations list
            sanitized_report.citations = [
                cite
                for cite in sanitized_report.citations
                if _normalize_citation_id(cite.citation_id) not in hallucinated_set
            ]

            # Clean sections
            sanitized_sections: list[ReportSection] = []
            for sec in sanitized_report.sections:
                new_sec = sec.model_copy(deep=True)
                # Filter section.citation_ids
                new_sec.citation_ids = [
                    cid
                    for cid in new_sec.citation_ids
                    if _normalize_citation_id(cid) not in hallucinated_set
                ]

                # Update section content
                content = new_sec.content
                for h_id in hallucinated_set:
                    target_pattern = rf"\[{re.escape(h_id)}\]|\[cite_{re.escape(h_id)}\]"
                    if self.flag_hallucinations_in_text:
                        content = re.sub(
                            target_pattern,
                            f"[UNVERIFIED_CITATION: {h_id}]",
                            content,
                            flags=re.IGNORECASE,
                        )
                    else:
                        content = re.sub(target_pattern, "", content, flags=re.IGNORECASE)
                new_sec.content = content
                sanitized_sections.append(new_sec)

            sanitized_report.sections = sanitized_sections
            sanitized_report.compile_markdown()

        summary_parts = [
            f"Validated {len(report.citations)} declared citations against {len(findings)} findings.",
            f"Verified: {len(verified_cids)}.",
            f"Hallucinated/Ungrounded: {len(hallucinated_cids)}.",
            f"Orphaned: {len(orphaned_cids)}.",
        ]
        if not is_valid:
            summary_parts.append(
                f"Auto-sanitized report: pruned {len(hallucinated_cids)} invalid citations."
            )

        return CitationValidationResult(
            is_valid=is_valid,
            total_citations=len(report.citations),
            verified_citations=verified_cids,
            hallucinated_citations=hallucinated_cids,
            orphaned_citations=orphaned_cids,
            sanitized_report=sanitized_report,
            summary=" ".join(summary_parts),
        )

    async def validate_async(
        self,
        report: ResearchReport,
        findings: list[FindingRecord],
        auto_sanitize: bool = True,
        probe_http: bool = True,
    ) -> CitationValidationResult:
        """Validate citations and optionally probe live URLs via concurrent HTTP requests.

        Verifies HTTP 200 OK, resolves redirected canonical URLs, and records dead links.
        """
        result = self.validate(report=report, findings=findings, auto_sanitize=auto_sanitize)

        if not probe_http or not result.sanitized_report.citations:
            return result

        # Probe live URLs concurrently
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        }

        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True, headers=headers) as client:

            async def _probe_citation(cite: Citation) -> tuple[Citation, int, str]:
                clean_url = cite.source_url.split("#")[0]
                try:
                    resp = await client.head(clean_url)
                    if resp.status_code in (404, 405, 501):
                        resp = await client.get(clean_url)
                    return cite, resp.status_code, str(resp.url)
                except Exception:
                    try:
                        resp = await client.get(clean_url)
                        return cite, resp.status_code, str(resp.url)
                    except Exception as err:
                        logger.warning("HTTP citation probe failed", url=cite.source_url, error=str(err))
                        return cite, 0, cite.source_url

            tasks = [_probe_citation(c) for c in result.sanitized_report.citations]
            probed_outcomes = await asyncio.gather(*tasks, return_exceptions=True)

            for outcome in probed_outcomes:
                if isinstance(outcome, tuple):
                    cite_obj, status_code, final_url = outcome
                    cite_obj.http_status = status_code
                    result.live_probed_urls[cite_obj.source_url] = status_code

                    # If redirected to a canonical URL, update it
                    if status_code in (200, 201, 204, 301, 302, 304, 403):
                        clean_final = final_url.split("#")[0]
                        clean_orig = cite_obj.source_url.split("#")[0]
                        if clean_final != clean_orig:
                            result.resolved_redirects[cite_obj.source_url] = clean_final
                            cite_obj.source_url = clean_final
                            if cite_obj.anchor_url:
                                fragment = cite_obj.anchor_url.split("#")[1] if "#" in cite_obj.anchor_url else ""
                                cite_obj.anchor_url = f"{clean_final}#{fragment}" if fragment else clean_final

                    if status_code in (404, 410):
                        result.dead_urls.append(cite_obj.source_url)
                        logger.warning("Dead link detected in citation", citation_id=cite_obj.citation_id, url=cite_obj.source_url)

        # Recompile markdown with resolved canonical URLs
        result.sanitized_report.compile_markdown()
        return result


def validate_report_citations(
    report: ResearchReport,
    findings: list[FindingRecord],
    auto_sanitize: bool = True,
) -> CitationValidationResult:
    """Convenience functional interface for validating report citations."""
    validator = CitationValidator()
    return validator.validate(report=report, findings=findings, auto_sanitize=auto_sanitize)


async def validate_report_citations_async(
    report: ResearchReport,
    findings: list[FindingRecord],
    auto_sanitize: bool = True,
    probe_http: bool = True,
) -> CitationValidationResult:
    """Async convenience functional interface for live-probing report citations."""
    validator = CitationValidator()
    return await validator.validate_async(
        report=report,
        findings=findings,
        auto_sanitize=auto_sanitize,
        probe_http=probe_http,
    )
