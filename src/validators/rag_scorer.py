"""Automated RAG Quality Scoring Engine.

Calculates deterministic Groundedness, Citation Precision, and Topic Coverage
metrics for generated research reports without requiring extra LLM calls.
"""


from pydantic import BaseModel, Field

from src.schemas.finding import FindingRecord
from src.schemas.plan import ResearchPlan
from src.schemas.report import ResearchReport
from src.validators.citation_validator import CitationValidationResult, _normalize_url


class RAGQualityScore(BaseModel):
    """Structured evaluation of research report grounding and citation precision."""

    groundedness_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Ratio of cited claims verified against empirical finding records (0.0 to 1.0).",
    )
    citation_precision: float = Field(
        ge=0.0,
        le=1.0,
        description="Ratio of valid, accessible, and non-hallucinated citations (0.0 to 1.0).",
    )
    coverage_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Fraction of planned research sub-questions addressed by findings (0.0 to 1.0).",
    )
    overall_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Weighted composite quality score: 50% Groundedness + 35% Precision + 15% Coverage.",
    )
    grade: str = Field(
        default="A",
        description="Human-readable letter grade (A+, A, B, C, D).",
    )
    total_citations: int = Field(default=0, ge=0)
    verified_citations_count: int = Field(default=0, ge=0)
    hallucinated_count: int = Field(default=0, ge=0)
    dead_urls_count: int = Field(default=0, ge=0)
    findings_count: int = Field(default=0, ge=0)
    sub_questions_addressed: int = Field(default=0, ge=0)
    sub_questions_total: int = Field(default=0, ge=0)
    summary: str = Field(default="", description="Executive diagnostic summary of report quality.")


def calculate_rag_quality_score(
    report: ResearchReport | None,
    findings: list[FindingRecord] | None = None,
    validation_result: CitationValidationResult | None = None,
    plan: ResearchPlan | None = None,
) -> RAGQualityScore:
    """Compute empirical RAG groundedness, citation precision, and coverage scores."""
    if not report:
        return RAGQualityScore(
            groundedness_score=0.0,
            citation_precision=0.0,
            coverage_score=0.0,
            overall_score=0.0,
            grade="D",
            summary="No report artifact available to evaluate.",
        )

    findings_list = findings or []
    raw_citations = getattr(report, "citations", None) or (
        report.get("citations") if isinstance(report, dict) else []
    )
    citations = raw_citations or []
    total_citations = len(citations)

    # 1. Groundedness Score: match citation URLs & claims against findings
    finding_urls: set[str] = set()
    finding_claims: set[str] = set()
    for f in findings_list:
        url = getattr(f, "source_url", None) or (f.get("source_url") if isinstance(f, dict) else "")
        if url:
            finding_urls.add(_normalize_url(url))
        claim = getattr(f, "claim", None) or (f.get("claim") if isinstance(f, dict) else "")
        if claim:
            finding_claims.add(str(claim).lower().strip())

    grounded_cites = 0
    for c in citations:
        c_url = getattr(c, "source_url", None) or (c.get("source_url") if isinstance(c, dict) else "")
        c_claim = getattr(c, "verified_claim", None) or (
            c.get("verified_claim") if isinstance(c, dict) else ""
        )
        norm_url = _normalize_url(c_url) if c_url else ""
        url_match = bool(norm_url and norm_url in finding_urls)
        claim_match = (
            any(
                str(c_claim).lower() in fc or fc in str(c_claim).lower()
                for fc in finding_claims
            )
            if c_claim
            else False
        )
        if url_match or claim_match:
            grounded_cites += 1

    groundedness = (
        round(grounded_cites / float(total_citations), 3)
        if total_citations > 0
        else (1.0 if findings_list else 0.5)
    )

    # 2. Citation Precision Score: based on citation validation result
    if validation_result:
        val_total = getattr(validation_result, "total_citations", total_citations) or total_citations
        val_verified = len(getattr(validation_result, "verified_citations", []))
        val_hallucinated = len(getattr(validation_result, "hallucinated_citations", []))
        val_dead = len(getattr(validation_result, "dead_urls", []))

        effective_valid = max(0, val_verified - val_dead)
        precision = round(effective_valid / float(val_total), 3) if val_total > 0 else 1.0
        hallucinated_count = val_hallucinated
        dead_count = val_dead
        verified_count = val_verified
    else:
        precision = groundedness
        hallucinated_count = total_citations - grounded_cites
        dead_count = 0
        verified_count = grounded_cites

    # 3. Sub-question Coverage Score
    plan_subqs = (
        getattr(plan, "sub_questions", None)
        or (plan.get("sub_questions") if isinstance(plan, dict) else None)
        if plan
        else None
    )
    total_subqs = len(plan_subqs) if plan_subqs else 0
    if total_subqs > 0:
        covered_ids: set[str] = set()
        for f in findings_list:
            sq_id = getattr(f, "sub_question_id", None) or (
                f.get("sub_question_id") if isinstance(f, dict) else None
            )
            if sq_id:
                covered_ids.add(str(sq_id))
        addressed_count = len(covered_ids)
        coverage = min(1.0, round(addressed_count / float(total_subqs), 3))
    else:
        addressed_count = 1 if findings_list else 0
        total_subqs = 1
        coverage = 1.0 if findings_list else 0.5

    # 4. Weighted Composite Score
    # 50% Groundedness, 35% Precision, 15% Subquestion Coverage
    overall = round(
        (0.50 * groundedness) + (0.35 * precision) + (0.15 * coverage),
        3,
    )
    overall = max(0.0, min(1.0, overall))

    # 5. Letter Grade Assignment
    if overall >= 0.92:
        grade = "A+"
    elif overall >= 0.82:
        grade = "A"
    elif overall >= 0.70:
        grade = "B"
    elif overall >= 0.55:
        grade = "C"
    else:
        grade = "D"

    summary = (
        f"RAG Quality Grade {grade} ({int(overall * 100)}%): "
        f"{int(groundedness * 100)}% groundedness, {int(precision * 100)}% citation precision, "
        f"{addressed_count}/{total_subqs} sub-questions covered with {len(findings_list)} empirical findings."
    )

    return RAGQualityScore(
        groundedness_score=groundedness,
        citation_precision=precision,
        coverage_score=coverage,
        overall_score=overall,
        grade=grade,
        total_citations=total_citations,
        verified_citations_count=verified_count,
        hallucinated_count=hallucinated_count,
        dead_urls_count=dead_count,
        findings_count=len(findings_list),
        sub_questions_addressed=addressed_count,
        sub_questions_total=total_subqs,
        summary=summary,
    )
