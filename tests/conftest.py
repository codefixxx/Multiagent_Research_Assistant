"""Pytest configuration and test fixtures with deterministic mock models."""

from typing import Any

import pytest
from langchain_core.callbacks.manager import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda

from src.schemas.finding import ExtractionStatus, FindingRecord, ResearcherOutput
from src.schemas.plan import ResearchPlan, SubQuestion, SubQuestionStatus
from src.schemas.report import Citation, ReportSection, ResearchReport
from src.schemas.review import ReviewEvaluation


class MockChatModel(BaseChatModel):
    """Deterministic Mock Chat Model for isolated specialist testing."""

    model_name: str = "mock-model"
    fixed_plan: ResearchPlan | None = None
    fixed_researcher_output: ResearcherOutput | None = None
    fixed_report: ResearchReport | None = None
    fixed_review: ReviewEvaluation | None = None

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        msg = AIMessage(
            content="Mock response",
            response_metadata={"token_usage": {"prompt_tokens": 15, "completion_tokens": 25}},
        )
        return ChatResult(generations=[ChatGeneration(message=msg)])

    @property
    def _llm_type(self) -> str:
        return "mock"

    def with_structured_output(self, schema: Any, *, include_raw: bool = False, **kwargs: Any):
        """Mock implementation of with_structured_output returning schema instances."""

        def _mock_structured_invoke(messages: Any) -> Any:
            ai_msg = AIMessage(
                content="{}",
                response_metadata={"token_usage": {"prompt_tokens": 10, "completion_tokens": 30}},
            )

            parsed: Any = None
            if schema == ResearchPlan:
                parsed = self.fixed_plan or ResearchPlan(
                    query="What are the latest developments in quantum computing?",
                    objective="Analyze key breakthroughs, physical qubit scalings, and error mitigation strategies in 2024.",
                    sub_questions=[
                        SubQuestion(
                            id="sq_1",
                            question="What recent logical qubit fidelity benchmarks were demonstrated in 2024?",
                            rationale="Quantifies fault-tolerant stability progress.",
                            search_queries=[
                                "logical qubit fidelity benchmarks 2024",
                                "fault tolerant quantum error correction",
                            ],
                            status=SubQuestionStatus.PENDING,
                        ),
                        SubQuestion(
                            id="sq_2",
                            question="How are major hardware architectures (superconducting vs neutral atom) comparing on coherence times?",
                            rationale="Evaluates competitive hardware approaches.",
                            search_queries=[
                                "neutral atom vs superconducting quantum coherence time"
                            ],
                            status=SubQuestionStatus.PENDING,
                        ),
                    ],
                )
            elif schema == ResearcherOutput:
                parsed = self.fixed_researcher_output or ResearcherOutput(
                    sub_question_id="sq_1",
                    is_answered=True,
                    findings=[
                        FindingRecord(
                            id="find_1",
                            sub_question_id="sq_1",
                            claim="Demonstrated 48 logical qubits with error rates below physical threshold using neutral atoms.",
                            source_url="https://nature.com/articles/quantum-qubits-2024",
                            snippet="We demonstrate fault-tolerant operation on 48 logical qubits...",
                        ),
                        FindingRecord(
                            id="find_2",
                            sub_question_id="sq_1",
                            claim="Two-qubit gate fidelities reached 99.9% in trapped-ion systems.",
                            source_url="https://arxiv.org/abs/2401.00123",
                            snippet="Achieving 99.9% fidelity in two-qubit entangling gates without post-selection.",
                        ),
                    ],
                    summary="Neutral atom and trapped-ion systems showed major fidelity milestones exceeding 99.9%.",
                    status=ExtractionStatus.SUCCESS,
                )
            elif schema == ResearchReport:
                parsed = self.fixed_report or ResearchReport(
                    title="State of Fault-Tolerant Quantum Computing 2024",
                    executive_summary="Quantum computing reached key inflection points with neutral atoms scaling to 48 logical qubits [cite_1] and gate fidelities touching 99.9% [cite_2].",
                    sections=[
                        ReportSection(
                            title="Logical Qubit Scaling",
                            content="Recent experiments achieved 48 logical qubits with suppressed physical error rates [cite_1].",
                            citation_ids=["[cite_1]"],
                        ),
                        ReportSection(
                            title="Gate Fidelity Milestones",
                            content="Trapped-ion systems demonstrated entangling fidelities reaching 99.9% [cite_2].",
                            citation_ids=["[cite_2]"],
                        ),
                    ],
                    citations=[
                        Citation(
                            citation_id="[cite_1]",
                            source_url="https://nature.com/articles/quantum-qubits-2024",
                            verified_claim="Demonstrated 48 logical qubits with error rates below physical threshold.",
                        ),
                        Citation(
                            citation_id="[cite_2]",
                            source_url="https://arxiv.org/abs/2401.00123",
                            verified_claim="Two-qubit gate fidelities reached 99.9% in trapped-ion systems.",
                        ),
                    ],
                )
            elif schema == ReviewEvaluation:
                parsed = self.fixed_review or ReviewEvaluation(
                    is_approved=True,
                    quality_score=0.9,
                    feedback="Sufficient factual evidence gathered with provenance.",
                    missing_aspects=[],
                )
            else:
                parsed = schema()

            if include_raw:
                return {"raw": ai_msg, "parsed": parsed, "parsing_error": None}
            return parsed

        return RunnableLambda(_mock_structured_invoke)


@pytest.fixture
def mock_llm() -> MockChatModel:
    return MockChatModel()
