"""Unit tests for automated RAG Quality Scoring Engine."""

from src.schemas.finding import FindingRecord
from src.schemas.plan import ResearchPlan, SubQuestion
from src.schemas.report import Citation, ReportSection, ResearchReport
from src.validators.citation_validator import CitationValidationResult
from src.validators.rag_scorer import RAGQualityScore, calculate_rag_quality_score


def test_rag_scorer_no_report():
    score = calculate_rag_quality_score(None)
    assert isinstance(score, RAGQualityScore)
    assert score.overall_score == 0.0
    assert score.grade == "D"
    assert "No report" in score.summary


def test_rag_scorer_perfect_groundedness_and_precision():
    findings = [
        FindingRecord(
            id="f1",
            sub_question_id="sq1",
            claim="Raft provides consensus with a leader.",
            source_url="https://raft.github.io",
            snippet="Raft is designed to be easy to understand.",
        ),
        FindingRecord(
            id="f2",
            sub_question_id="sq2",
            claim="Paxos uses two-phase commit protocol.",
            source_url="https://paxos.lamport.org",
            snippet="The Part-Time Parliament.",
        ),
    ]

    report = ResearchReport(
        title="Consensus Algorithms",
        executive_summary="Review of Raft [cite_1] and Paxos [cite_2].",
        sections=[
            ReportSection(
                title="Analysis",
                content="Raft is leader-based [cite_1]. Paxos is consensus-based [cite_2].",
                citation_ids=["cite_1", "cite_2"],
            )
        ],
        citations=[
            Citation(
                citation_id="cite_1",
                source_url="https://raft.github.io",
                verified_claim="Raft provides consensus with a leader.",
            ),
            Citation(
                citation_id="cite_2",
                source_url="https://paxos.lamport.org",
                verified_claim="Paxos uses two-phase commit protocol.",
            ),
        ],
    )

    plan = ResearchPlan(
        query="Analyze consensus",
        objective="Analyze consensus",
        sub_questions=[
            SubQuestion(id="sq1", question="How does Raft work?", rationale="Leader rationale"),
            SubQuestion(id="sq2", question="How does Paxos work?", rationale="Consensus rationale"),
        ],
    )

    validation = CitationValidationResult(
        is_valid=True,
        total_citations=2,
        verified_citations=["cite_1", "cite_2"],
        hallucinated_citations=[],
        dead_urls=[],
        sanitized_report=report,
    )

    score = calculate_rag_quality_score(
        report=report,
        findings=findings,
        validation_result=validation,
        plan=plan,
    )

    assert score.groundedness_score == 1.0
    assert score.citation_precision == 1.0
    assert score.coverage_score == 1.0
    assert score.overall_score >= 0.95
    assert score.grade == "A+"
    assert score.verified_citations_count == 2
    assert score.hallucinated_count == 0


def test_rag_scorer_hallucinated_penalty():
    findings = [
        FindingRecord(
            id="f1",
            sub_question_id="sq1",
            claim="Raft provides consensus.",
            source_url="https://raft.github.io",
            snippet="Raft consensus.",
        ),
    ]

    report = ResearchReport(
        title="Faulty Citations Report",
        executive_summary="Fake claims [cite_fake_1].",
        sections=[
            ReportSection(
                title="Section",
                content="Unverified text [cite_fake_1].",
                citation_ids=["cite_fake_1"],
            )
        ],
        citations=[
            Citation(
                citation_id="cite_fake_1",
                source_url="https://completely-made-up-domain-xyz.com",
                verified_claim="Invented algorithm claim never observed in research.",
            ),
        ],
    )

    validation = CitationValidationResult(
        is_valid=False,
        total_citations=1,
        verified_citations=[],
        hallucinated_citations=["cite_fake_1"],
        dead_urls=["https://completely-made-up-domain-xyz.com"],
        sanitized_report=report,
    )

    score = calculate_rag_quality_score(
        report=report,
        findings=findings,
        validation_result=validation,
    )

    assert score.groundedness_score == 0.0
    assert score.citation_precision == 0.0
    assert score.hallucinated_count == 1
    assert score.grade == "D"
