# Production-Grade Multi-Agent Research Assistant
## Comprehensive Architecture Specification & Phased Engineering Roadmap

---

### Executive Overview & Core Philosophy

Most AI agent demos fail in real-world production environments because they:
1. **Crash permanently on restarts** rather than resuming from checkpointed state.
2. **Burn through budgets silently** with endless self-reflection and re-prompting loops.
3. **Black-box their failures**, making post-mortem debugging impossible without structured step traces.
4. **Rely on vague "personality" prompts** instead of strictly validated Pydantic input/output schemas.

This project implements a **Production-Grade Multi-Agent Research Assistant** using a **Supervisor-Worker topology** built with **LangGraph**, **FastAPI**, **Redis**, and a provider-agnostic LLM interface supporting free/open-source models.

```
                                  +-----------------------+
                                  |   Client / Caller     |
                                  +-----------+-----------+
                                              |
                   POST /research (job init)  |  GET /research/{id}/trace (audit)
                   GET /research/{id} (poll)  |  GET /research/{id}/stream (SSE)
                                              v
                              +-------------------------------+
                              |    FastAPI Production API     |
                              +---------------+---------------+
                                              |
                                              v
                              +-------------------------------+
                              |     LangGraph Orchestrator    |
                              |   (Supervisor State Machine)  |
                              +---------------+---------------+
                                       |      ^
            +--------------------------+      +--------------------------+
            | Checkpoint / State                     Budget & Telemetry  |
            v                                                            v
+-----------------------+                                    +-----------------------+
|  Redis Checkpointer   |                                    | Trace Logger & Cost   |
|  (Durable Run State)  |                                    | Budget Enforcer       |
+-----------------------+                                    +-----------------------+
            |
            | Routes & Governs
            v
  +-------------------+        +---------------------+        +--------------------+
  |   Planner Agent   | -----> |   Researcher Agent  | -----> |    Writer Agent    |
  |  (Sub-questions)  |        |  (Search+Provenance)|        | (Citations+Report) |
  +-------------------+        +---------------------+        +--------------------+
                                          |
                                          v
                               +---------------------+
                               | Search & Scraping   |
                               | (Tavily / DuckDuck) |
                               | Page Extractor &    |
                               | Provenance Builder  |
                               +---------------------+
```

---

## 1. LLM Strategy: Free & Open-Source Models with High Token Limits

To ensure you can test, develop, and deploy without paying API fees while maintaining the precision required for structured JSON and tool calling, we establish a **Provider-Agnostic LLM Layer** (`langchain.chat_models.init_chat_model` or custom factory).

### Recommended Free & Open-Source Options

| Provider / Model | Context Window | Structured Outputs / Tool Calling | Free Tier Limits | Best Use Case |
| :--- | :--- | :--- | :--- | :--- |
| **Groq Cloud API**<br>`llama-3.3-70b-versatile` | 128k tokens | **Exceptional** (native tool use & JSON mode) | Free Tier:<br>30 req/min, 1k-6k req/day, ultra-fast (~250 tokens/sec) | **Primary Recommendation** for development, fast agent iterations, structured outputs. |
| **Google Gemini API**<br>`gemini-2.0-flash` / `gemini-1.5-flash` | 1M tokens | **Exceptional** (Pydantic schema enforcement) | Free Tier (Google AI Studio):<br>15 RPM, 1M TPM, 1,500 requests/day | **Top Choice for Heavy Context** (reading long scraped web pages) and complex syntheses. |
| **OpenRouter Free Tier**<br>`meta-llama/llama-3.3-70b-instruct:free`<br>`deepseek/deepseek-r1:free` | Up to 128k tokens | Good (OpenAI-compatible format) | Free model endpoints with per-day rate caps | Backup fallback provider. |
| **Local Ollama / vLLM**<br>`qwen2.5:14b-instruct`<br>`llama3.1:8b-instruct` | 32k - 128k tokens | Good (requires 8GB - 16GB VRAM) | 100% Free, offline, zero rate limits | Offline local development and deployment on private hardware. |

### Architectural Decision: LLM Adapter Pattern
We will implement an adapter interface `get_llm(model_role: str)`:
- **Fast / High-throughput Role (Supervisor, Router, Validator):** `llama-3.3-70b` on Groq or `gemini-2.0-flash`.
- **Long-context Role (Researcher Extractor, Writer):** `gemini-2.0-flash` (1M token window handles large scraped documents without truncation).
- Switchable via `.env` parameter `LLM_PROVIDER=groq | gemini | ollama`.

---

## 2. Master Phased Implementation Breakdown

```
+----------------------------------------------------------------------------------------+
| Phase 0: Project Foundation, Configuration, and Provider Agnostic LLM Setup            |
+----------------------------------------------------------------------------------------+
                                           |
                                           v
+----------------------------------------------------------------------------------------+
| Phase 1: The Three Specialists (Isolated Prompts + Pydantic Hand-offs + Unit Tests)    |
|   1.1 Pydantic Domain Schemas (Plan, Finding, Report)                                  |
|   1.2 Planner Specialist Agent                                                         |
|   1.3 Researcher Specialist Agent (Mocked Tools)                                       |
|   1.4 Writer Specialist Agent (Strict Citation Schema)                                 |
|   1.5 Isolation Unit Testing Suite                                                     |
+----------------------------------------------------------------------------------------+
                                           |
                                           v
+----------------------------------------------------------------------------------------+
| Phase 2: LangGraph Supervisor, State Machine, and Deterministic Budget Engine          |
|   2.1 Graph State Definition (Single Source of Truth)                                  |
|   2.2 Supervisor Routing Node & State Machine Transitions                              |
|   2.3 Single-pass Revision Gate (Max 1 Review Loop)                                    |
|   2.4 Hard Budget Enforcer (Max Sub-questions, Max Searches, Max Tokens, Wall Clock)   |
|   2.5 Orchestration Integration Testing                                                |
+----------------------------------------------------------------------------------------+
                                           |
                                           v
+----------------------------------------------------------------------------------------+
| Phase 3: Production Web Search, Deep Page Extraction, and Provenance Engine            |
|   3.1 Search Client Integration (Tavily API with DuckDuckGo fallback)                  |
|   3.2 Deep Page Extractor (Raw HTML Fetching, Boilerplate Removal, Markdown Conversion)|
|   3.3 URL Deduplication & Domain Rate / Bias Limiting                                  |
|   3.4 Structured Search Failure Enums (no_results, rate_limited, paywalled, timed_out) |
|   3.5 Provenance Record Validation                                                     |
+----------------------------------------------------------------------------------------+
                                           |
                                           v
+----------------------------------------------------------------------------------------+
| Phase 4: Durable State Persistence & Resumption with Redis                             |
|   4.1 Redis Infrastructure Setup (Local Docker / Managed Redis)                        |
|   4.2 LangGraph Redis Checkpointer Integration                                         |
|   4.3 Node-by-Node State Serialization & Idempotency Cache                             |
|   4.4 Crash Recovery & Resume-from-Step Engine                                         |
|   4.5 Resilience & Chaos Verification Testing                                          |
+----------------------------------------------------------------------------------------+
                                           |
                                           v
+----------------------------------------------------------------------------------------+
| Phase 5: FastAPI Production Service, SSE Progress Streaming, and Audit Trace API       |
|   5.1 Background Job Execution Architecture (Asyncio / Worker Tasks)                   |
|   5.2 Endpoints: POST /research, GET /research/{id}, GET /research/{id}/stream         |
|   5.3 Deterministic Citation Validator (Pre-flight Claim-to-Finding Integrity Check)   |
|   5.4 GET /research/{id}/trace Audit Logging (Inputs, Outputs, Tools, Latency, Tokens) |
|   5.5 End-to-End SLA Benchmark (Sub-5-minute SLA Guarantee)                            |
+----------------------------------------------------------------------------------------+
                                           |
                                           v
+----------------------------------------------------------------------------------------+
| Phase 6: Production Hardening, Packaging, and Stretch Features                         |
|   6.1 Parallel Researcher Fan-out / Fan-in (Send / Map-Reduce Nodes)                  |
|   6.2 Source Contradiction & Bias Detection                                            |
|   6.3 Human-in-the-Loop (HITL) Approval Interrupt Gate                                 |
|   6.4 Docker Compose Multi-Container Stack & CI/CD Pipeline                            |
+----------------------------------------------------------------------------------------+
```

---

## 3. Deep-Dive Subphase Specifications

### Phase 0: Project Foundation & Configuration Architecture
- **Goal:** Set up a clean, scalable Python production repo with strict typing, linting, configuration management, and LLM abstraction.
- **Subphases:**
  - **0.1 Environment & Dependency Layout:**
    - Python 3.11+, Poetry or uv/pip with `pyproject.toml` and lockfile.
    - Core dependencies: `langgraph`, `langchain-core`, `langchain-groq`, `langchain-google-genai`, `fastapi`, `uvicorn`, `redis`, `pydantic>=2.0`, `httpx`, `trafilatura` (or `beautifulsoup4`), `pytest`, `pytest-asyncio`.
  - **0.2 Typed Settings Management:**
    - `pydantic-settings` configuration loading environment variables (`REDIS_URL`, `GROQ_API_KEY`, `GEMINI_API_KEY`, `TAVILY_API_KEY`, `MAX_BUDGET_TOKENS`, `MAX_WALL_CLOCK_SECONDS`).
  - **0.3 Provider-Agnostic LLM Factory:**
    - `src/core/llm.py`: Configurable model factory that transparently returns Groq (`llama-3.3-70b-versatile`), Gemini (`gemini-2.0-flash`), or Ollama with standardized retry and timeout policies.
  - **0.4 Structured Logging & Metric Telemetry Foundation:**
    - Python `structlog` or `loguru` configured with JSON formatting for machine-readable production logs.

---

### Phase 1: The Three Specialists (No Orchestration, Strict Schemas)
- **Goal:** Build the three core worker specialists as isolated, deterministic units. Each specialist is defined strictly by **Prompt + Tools + Pydantic Schema**, with zero conversational "fluff".
- **Subphases:**
  - **1.1 Schema Definitions (`src/schemas/`):**
    - `ResearchPlan`: `query: str`, `sub_questions: list[SubQuestion]`, `objective: str`.
    - `SubQuestion`: `id: str`, `question: str`, `rationale: str`, `status: SubQuestionStatus`.
    - `FindingRecord`: `id: str`, `sub_question_id: str`, `claim: str`, `source_url: HttpUrl`, `snippet: str`, `retrieval_timestamp: datetime`.
    - `ResearchReport`: `title: str`, `executive_summary: str`, `sections: list[ReportSection]`, `citations: list[Citation]`.
    - `Citation`: `citation_id: str`, `source_url: HttpUrl`, `verified_claim: str`.
  - **1.2 Specialist 1: The Planner (`src/agents/planner.py`):**
    - Takes user research query.
    - Produces a deterministic `ResearchPlan` broken into 2 to 4 precise, non-overlapping sub-questions.
    - Rejects ambiguous or broad questions by generating targeted clarifying scopes.
  - **1.3 Specialist 2: The Researcher (`src/agents/researcher.py`):**
    - Takes one specific `SubQuestion`.
    - Executes research via tool call and parses findings into structured `FindingRecord` objects.
    - Evaluates whether the question was answered or if additional search queries are required.
  - **1.4 Specialist 3: The Writer (`src/agents/writer.py`):**
    - Takes user query + all accumulated `list[FindingRecord]`.
    - Synthesizes findings into a professional Markdown report.
    - Enforces citation inline markers `[citation_id]` linked directly to verified findings.
  - **1.5 Isolated Unit Testing (`tests/test_specialists/`):**
    - Mocked LLM responses asserting schema compliance for Planner, Researcher, and Writer.
    - Test failure cases: malformed JSON parsing, schema validation errors, and empty findings.

---

### Phase 2: LangGraph Supervisor, State Machine, & Budget Enforcer
- **Goal:** Bind specialists into a cohesive LangGraph state machine directed by a Supervisor node that enforces hard budgets and limits review loops.
- **Subphases:**
  - **2.1 Shared State Object (`src/graph/state.py`):**
    - Typed `AgentState` TypedDict:
      ```python
      class ResearchState(TypedDict):
          run_id: str
          research_query: str
          plan: Optional[ResearchPlan]
          current_sub_question_index: int
          findings: list[FindingRecord]
          review_notes: Optional[str]
          revision_count: int  # STRICT CAP: max 1
          report: Optional[ResearchReport]
          token_budget: TokenBudgetTracker
          wall_clock_start: float
          status: Literal["planning", "researching", "reviewing", "writing", "completed", "failed", "budget_exceeded"]
          error_message: Optional[str]
      ```
  - **2.2 Supervisor Routing Node (`src/graph/supervisor.py`):**
    - Decides next node:
      - If no plan -> route to `planner`.
      - If plan exists and sub-questions remain -> route to `researcher`.
      - If sub-question finished -> route to `reviewer`.
      - If reviewer approves or revision cap reached -> route to next sub-question or `writer`.
      - If all sub-questions answered -> route to `writer`.
      - If writer finished -> route to `END`.
  - **2.3 Single-Pass Revision Gate:**
    - Reviewer inspects output against sub-question requirements.
    - Hard limit: If `revision_count >= 1`, force approval and proceed; do not loop again.
  - **2.4 Hard Budget Enforcement (`src/graph/budgets.py`):**
    - Programmatic check inside supervisor edge decisions (not LLM prompt requests):
      - `max_sub_questions`: Default 4
      - `max_searches_per_sub_question`: Default 3
      - `max_total_tokens`: Default 150,000 tokens
      - `max_wall_clock_seconds`: Default 240 seconds (4 minutes)
    - If any limit exceeded: Graph routes directly to `emergency_writer` to assemble best-effort report from existing findings, tagging output with budget warning.
  - **2.5 Graph Integration Tests (`tests/test_graph/`):**
    - Verification of state transitions, loop termination, and budget cut-offs using mock LLM tools.

---

### Phase 3: Live Web Search, Page Extraction, & Provenance Tracking
- **Goal:** Replace search stubs with live, production-grade search and web extraction capable of handling real-world web failures gracefully.
- **Subphases:**
  - **3.1 Production Search Tool (`src/tools/search.py`):**
    - Primary: Tavily Search API.
    - Fallback: DuckDuckGo Search API (for zero-cost development without API keys).
    - Returns structured metadata: title, URL, search engine snippet, score.
  - **3.2 Deep Page Extractor (`src/tools/scraper.py`):**
    - Do not rely solely on search engine snippets.
    - Asynchronous HTTP client (`httpx` with 5s timeout, browser user-agent headers).
    - Boilerplate extraction via `trafilatura` or `readability-lxml` to strip scripts, ads, and navbars.
    - Content chunking with max token cap per page (e.g. 3,000 words).
  - **3.3 URL Deduplication & Domain Diversity Guard (`src/tools/domain_guard.py`):**
    - Canonical URL deduplication (remove tracking query params like `utm_*`).
    - Domain cap: Maximum 2 citations per domain per report to avoid single-source bias.
  - **3.4 Structured Failure Handling Enums (`src/tools/errors.py`):**
    - Model web fetch outcomes as a structured enum rather than unhandled exceptions:
      ```python
      class ExtractionStatus(str, Enum):
          SUCCESS = "success"
          NO_RESULTS = "no_results"
          RATE_LIMITED = "rate_limited"
          PAYWALLED = "paywalled"
          TIMED_OUT = "timed_out"
          BLOCKED = "blocked"
      ```
    - The Researcher receives this status and selects an alternative source instead of crashing the run.
  - **3.5 Provenance Verifier:**
    - Every claim recorded in `FindingRecord` must have: raw snippet, target URL, and millisecond timestamp.

---

### Phase 4: Durable State Persistence in Redis (Fault-Tolerant Resumption)
- **Goal:** Ensure agent runs survive worker restarts, crashes, and deployments. A restarted worker resumes from the exact last completed node instead of restarting from scratch.
- **Subphases:**
  - **4.1 Redis Checkpointer Integration (`src/persistence/redis_saver.py`):**
    - LangGraph Redis Checkpointer (`langgraph-checkpoint-redis` or custom Redis state store).
    - Key structure: `research:run:{run_id}:checkpoint:{step_id}` and `research:run:{run_id}:metadata`.
  - **4.2 Node-by-Node State Commitment:**
    - State flushed atomically after every agent transition:
      - Node completed -> Write checkpoint -> Update status -> Advance pointer.
  - **4.3 Node Idempotency & Caching:**
    - If a node is re-entered with identical input state, return cached outputs to prevent duplicate token spend and duplicate external web requests.
  - **4.4 Crash Recovery Simulation & Verification:**
    - Chaos test (`tests/test_persistence/test_recovery.py`):
      1. Trigger research run.
      2. Kill process midway through Researcher Step 2.
      3. Instantiate new runner with same `run_id`.
      4. Assert graph resumes at Researcher Step 2 without re-running Planner or Step 1.

---

### Phase 5: FastAPI Production Service, Streaming, & Audit Trace
- **Goal:** Expose the research engine as an enterprise-ready async HTTP microservice with real-time SSE progress streaming, claim-level citation validation, and step-level audit trails.
- **Subphases:**
  - **5.1 Async Job Architecture (`src/api/`):**
    - FastAPI app with background job runner (asyncio task pool or Celery/RQ).
    - Request validation with Pydantic v2.
  - **5.2 Core API Endpoints:**
    - `POST /research`:
      - Payload: `{"query": str, "max_depth": Optional[int], "budget_tokens": Optional[int]}`
      - Immediate response (HTTP 202): `{"run_id": str, "status": "queued", "created_at": datetime}`
    - `GET /research/{id}`:
      - Returns current status: `{"run_id": str, "status": "researching", "progress_pct": 45, "report": null}`
      - When done: Returns finished report with citations and executive summary.
    - `GET /research/{id}/stream`:
      - Server-Sent Events (SSE) streaming real-time node lifecycle events:
        `data: {"event": "planner_completed", "sub_questions": 3}`
        `data: {"event": "researching_subquestion", "index": 1, "query": "..."}`
  - **5.3 Pre-Flight Citation Validator (`src/validators/citation_checker.py`):**
    - Before returning `ResearchReport`, an automated deterministic check runs:
      - Validates every `[citation_id]` in the report text against the persisted `findings` list.
      - If a hallucinated citation ID or orphaned URL is found, strip or flag the claim before delivery.
  - **5.4 Audit Trace Endpoint (`GET /research/{id}/trace`):**
    - Returns granular step log:
      - `step_number`: int
      - `agent_name`: "planner" | "researcher" | "supervisor" | "writer"
      - `input_payload`: sanitized state snippet
      - `output_payload`: generated schema
      - `tool_calls`: tools invoked, latency (ms), and status
      - `token_usage`: prompt tokens, completion tokens, estimated cost ($0.00 if free tier)
      - `latency_ms`: step execution duration
  - **5.5 Performance SLA Verification:**
    - Benchmark test confirming standard research queries complete in under 5 minutes with complete provenance.

---

### Phase 6: Production Hardening & Advanced Stretch Goals
- **Goal:** Expand system throughput and enterprise capabilities.
- **Subphases:**
  - **6.1 Parallel Researcher Fan-Out / Fan-In:**
    - Utilize LangGraph's `Send` API to dispatch researchers for all sub-questions in parallel.
    - Fan-in aggregator node merges findings and performs global deduplication.
  - **6.2 Contradiction & Source Discrepancy Detection:**
    - Add an analytical review node that compares findings across sources and flags contradictory statistics or claims in the final report.
  - **6.3 Human-in-the-Loop (HITL) Gate:**
    - LangGraph `interrupt()` breakpoint after the Planner generates sub-questions.
    - Allow human to inspect, add, modify, or approve sub-questions via `POST /research/{id}/approve` before search operations trigger.
  - **6.4 Containerization & Production Packaging:**
    - Multi-stage `Dockerfile` (optimized Python runtime, non-root user).
    - `docker-compose.yml` bundling FastAPI app, Redis instance, and optional local Ollama.
    - Automated GitHub Actions workflow running linting (`ruff`), typing (`mypy`), and test suite (`pytest`).

---

## 4. Proposed Repository Directory Structure

```
Multiagent_research_assistant/
|-- PROJECT_BREAKDOWN.md            # This master architecture specification
|-- pyproject.toml                  # Project metadata, dependencies, and tool configs
|-- .env.example                    # Template environment variables (GROQ_API_KEY, REDIS_URL, etc.)
|-- README.md                       # Overview, setup instructions, and architecture diagrams
|-- docker-compose.yml              # Multi-container orchestration (App + Redis)
|-- Dockerfile                      # Production container image
|-- src/
|   |-- __init__.py
|   |-- config.py                   # Pydantic Settings & environment validation
|   |-- core/
|   |   |-- __init__.py
|   |   |-- llm.py                  # Provider-agnostic LLM factory (Groq, Gemini, Ollama)
|   |   |-- logger.py               # Structured JSON logging
|   |   `-- telemetry.py            # Token counter and budget manager
|   |-- schemas/
|   |   |-- __init__.py
|   |   |-- plan.py                 # ResearchPlan and SubQuestion models
|   |   |-- finding.py              # FindingRecord and ExtractionStatus models
|   |   |-- report.py               # ResearchReport and Citation models
|   |   `-- trace.py                # StepTrace, ToolTrace, and AuditLog models
|   |-- agents/
|   |   |-- __init__.py
|   |   |-- planner.py              # Planner specialist node & prompt
|   |   |-- researcher.py           # Researcher specialist node & prompt
|   |   `-- writer.py               # Writer specialist node & prompt
|   |-- tools/
|   |   |-- __init__.py
|   |   |-- search.py               # Tavily & DuckDuckGo search wrappers
|   |   |-- scraper.py              # Async HTTP page fetcher & trafilatura extractor
|   |   `-- domain_guard.py         # URL deduplication & domain diversity limiter
|   |-- graph/
|   |   |-- __init__.py
|   |   |-- state.py                # LangGraph AgentState TypedDict
|   |   |-- supervisor.py           # Routing logic & review gate
|   |   |-- budgets.py              # Hard deterministic budget enforcer
|   |   `-- builder.py              # Graph construction & compilation
|   |-- persistence/
|   |   |-- __init__.py
|   |   `-- redis_checkpointer.py   # Redis connection & state checkpointing
|   |-- validators/
|   |   |-- __init__.py
|   |   `-- citation_validator.py   # Claim-to-source integrity verifier
|   `-- api/
|       |-- __init__.py
|       |-- main.py                 # FastAPI application entrypoint
|       |-- routes.py               # /research, /research/{id}, /trace, /stream
|       `-- sse.py                  # Server-Sent Events streaming helper
|-- tests/
|   |-- conftest.py                 # Pytest fixtures and mock LLM providers
|   |-- test_specialists/           # Unit tests for Planner, Researcher, Writer
|   |-- test_tools/                 # Search, Scraper, and Failure enum tests
|   |-- test_graph/                 # Supervisor routing, budgets, and single-pass review
|   |-- test_persistence/           # Redis checkpointing and crash recovery
|   `-- test_api/                   # FastAPI endpoints, SSE streaming, and trace verification
`-- scripts/
    |-- run_dev.ps1                 # Local development starter script
    `-- simulate_crash.py           # Chaos testing script for restart recovery
```

---

## 5. Definition of Done & Interview-Proof Checklist

| Feature | Verification Method | Pass Criteria |
| :--- | :--- | :--- |
| **No "Personality" Prompts** | Code Review & Unit Tests | Agents rely 100% on typed Pydantic models for inputs and outputs. |
| **Hard Budget Caps** | Test `test_budget_cap()` | Run aborts/synthesizes when hitting max tokens or 240s wall-clock ceiling. |
| **Single Revision Loop** | Test `test_single_revision()` | Supervisor sends work back at most once; never loops indefinitely. |
| **Full Provenance Records** | Test `test_finding_provenance()` | Every finding has verified claim, exact source URL, snippet, and timestamp. |
| **Durable Redis Recovery** | Test `test_crash_resumption()` | Killed process resumes from exact last node; no replay of completed nodes. |
| **Citation Integrity** | Test `test_citation_validator()` | Zero orphan or hallucinated citations in the published report. |
| **Live Trace Inspection** | API `GET /research/{id}/trace` | Full JSON log detailing agent, input, output, tools, tokens, latency per step. |
| **Time-to-Report SLA** | End-to-End Run Benchmark | Standard research query produces verified report in under 5 minutes. |
