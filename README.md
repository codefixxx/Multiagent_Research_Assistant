# Production-Grade Multi-Agent Research Assistant

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![LangGraph](https://img.shields.io/badge/orchestration-LangGraph-orange.svg)](https://github.com/langchain-ai/langgraph)
[![FastAPI](https://img.shields.io/badge/api-FastAPI-green.svg)](https://fastapi.tiangolo.com/)
[![Redis](https://img.shields.io/badge/persistence-Redis%208-red.svg)](https://redis.io/)
[![Tests](https://img.shields.io/badge/tests-74%20passed-brightgreen.svg)]()
[![Docker](https://img.shields.io/badge/docker-ready-blue.svg)](https://www.docker.com/)

A resilient, production-grade autonomous research service powered by **LangGraph**, **FastAPI**, **Redis**, and a provider-agnostic LLM interface (Google Gemini, Groq, Ollama).

Built specifically to solve the common failure modes of typical AI agent prototypes:
1. **Zero Data Loss on Restarts:** Checkpointed state machine via LangGraph and Redis ensures runs survive crashes and resume seamlessly.
2. **Deterministic Budget Guardrails:** Programmatic token and wall-clock ceilings trigger automatic emergency synthesis rather than burning budgets in endless loops.
3. **Claim-Level Citation Integrity:** Pre-flight citation validation guarantees zero hallucinated or orphaned sources before delivering reports.
4. **Strict Schema Contracts:** 100% Pydantic v2 typed inputs and outputs across all specialist agents with zero conversational "fluff".
5. **Full Observability & Auditing:** Granular step traces recording latency, token counts, inputs, outputs, and real-time Server-Sent Events (SSE).

---

## Architecture Overview

```mermaid
flowchart TD
    Client([Client / Caller]) -->|POST /research| API[FastAPI Microservice]
    Client -.->|GET /stream| SSE[Server-Sent Events Stream]
    Client -.->|GET /trace| Audit[Audit Trace Logger]

    API -->|Dispatch Background Task| Engine[ResearchJobService]
    Engine -->|Compile & Bind| Graph[LangGraph Supervisor Machine]

    subgraph StatePersistence ["Durable Persistence Layer"]
        Redis[(Redis 8 State Store)]
        Saver[AsyncShallowRedisSaver]
        RunMgr[RedisRunManager]
        Cache[NodeIdempotencyCache]
        Redis <--> Saver
        Redis <--> RunMgr
        Redis <--> Cache
    end

    Graph <--> StatePersistence

    subgraph MultiAgentStateMachine ["Governed Multi-Agent State Machine"]
        Start([START]) --> Planner[Planner Specialist]
        Planner -->|Decompose to Sub-Questions| Researcher[Researcher Specialist]
        Researcher --> Reviewer{Reviewer Evaluation}
        Reviewer -->|Needs Refinement max 1| Researcher
        Reviewer -->|Approved / Revision Cap| Writer[Writer Specialist]
        Reviewer -->|Budget Ceiling Breached| Emergency[Emergency Writer]
        Writer --> Validator[Pre-Flight Citation Validator]
        Emergency --> Validator
        Validator --> EndNode([END / Redis Persist])
    end

    subgraph EvidenceEngine ["Live Evidence Gathering"]
        Search[Tavily Search API / DDG Fallback]
        Scraper[Deep Webpage Scraper]
        Jina[Jina Reader Anti-Bot Fallback]
        HN[Hacker News Discussions]
    end

    Researcher <--> EvidenceEngine
```

---

## Agent Specialists

| Specialist Agent | Responsibility | Guarantee & Constraints |
| :--- | :--- | :--- |
| **Planner** | Decomposes broad queries into 2–4 factual sub-questions. | Strict `ResearchPlan` Pydantic model with optimized search queries. |
| **Researcher** | Investigates sub-questions using search and deep webpage extraction. | Retains raw snippet, exact target URL, and UTC timestamps for each finding. |
| **Reviewer** | Evaluates findings against questions and scores evidence quality. | **Strict Single-Pass Revision Cap:** Sends work back at most once; never loops indefinitely. |
| **Writer** | Synthesizes verified findings into a structured, publication-ready report. | Enforces inline citation markers (`[cite_1]`) strictly linked to gathered evidence. |
| **Emergency Writer** | Fallback synthesizer triggered when token or wall-clock budget caps trigger. | Assembles a best-effort report from verified evidence before graceful termination. |
| **Citation Validator** | Pre-flight programmatic validation of all report citations. | Reconciles claims against findings; strips or sanitizes invalid or hallucinated sources. |

---

## Quickstart Guide

### Option 1: Docker Compose (Recommended)

1. **Clone and Configure Environment:**
   ```bash
   git clone https://github.com/your-username/Multiagent_research_assistant.git
   cd Multiagent_research_assistant
   cp .env.example .env
   ```
   Add your API keys in `.env`:
   ```bash
   GEMINI_API_KEY="your-gemini-key"      # or GROQ_API_KEY="your-groq-key"
   TAVILY_API_KEY="your-tavily-key"      # optional (DuckDuckGo fallback enabled)
   ```

2. **Boot the Complete Stack:**
   ```bash
   docker compose up -d
   ```
   This launches:
   - **`research_api`**: FastAPI service listening on `http://localhost:8000`
   - **`research_redis`**: Official Linux Redis 8 container with persistent volume

3. **Verify System Health:**
   ```bash
   curl http://localhost:8000/health
   ```
   ```json
   {
     "status": "healthy",
     "service": "multiagent-research-assistant",
     "version": "0.1.0",
     "redis_connected": true,
     "llm_provider": "gemini",
     "search_engine": "auto"
   }
   ```

---

### Option 2: Local Development Setup

1. **Prerequisites:** Python 3.11+ and Docker Desktop (for Redis).

2. **Start Redis Container:**
   ```bash
   docker compose up -d redis
   ```

3. **Install Dependencies in Virtualenv:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Or .venv\Scripts\Activate.ps1 on Windows
   pip install -e ".[dev]"
   ```

4. **Launch Development API Server:**
   ```bash
   uvicorn src.api.main:app --reload --port 8000
   ```

5. **Run the Test Suite:**
   ```bash
   pytest -v
   # 74 passed
   ```

---

## API Reference

Interactive Swagger documentation is available at: **`http://localhost:8000/docs`**

### 1. Submit Research Job
```bash
POST /research
Content-Type: application/json

{
  "query": "Compare Redis vs Memcached latency and threading models",
  "max_sub_questions": 3,
  "deep_scrape": true
}
```
**Response (`HTTP 202 Accepted`):**
```json
{
  "run_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "status": "queued",
  "created_at": "2026-10-09T12:00:00Z",
  "message": "Research job accepted and queued for execution."
}
```

---

### 2. Stream Real-Time Progress via SSE
Stream progress updates and agent step transitions directly to frontend clients:
```bash
curl -N http://localhost:8000/research/{run_id}/stream
```
**Server-Sent Events Payload Stream:**
```text
event: job_started
data: {"status":"planning","message":"Orchestrator started: generating research plan."}

event: planner_completed
data: {"node":"planner","status":"researching","sub_questions_count":3}

event: researching_subquestion
data: {"node":"researcher","new_findings_count":4,"total_findings_count":4}

event: subquestion_reviewed
data: {"node":"reviewer","is_revision":false,"next_sub_question_index":1}

event: writing_completed
data: {"node":"writer","status":"completed","title":"Comprehensive Technical Comparison..."}

event: job_completed
data: {"status":"completed","citations_verified":9,"citations_hallucinated":0}
```

---

### 3. Retrieve Status & Final Report
```bash
GET /research/{run_id}
```
**Response:**
```json
{
  "run_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "status": "completed",
  "progress_pct": 100,
  "step_count": 10,
  "total_tokens": 17875,
  "report": {
    "title": "Comprehensive Technical Comparison: Redis vs. Memcached",
    "executive_summary": "This research report delivers a detailed comparison...",
    "sections": [
      {
        "title": "Threading Models and Architecture",
        "content": "Redis employs an event-driven architecture...",
        "citation_ids": ["cite_1", "cite_2"]
      }
    ],
    "citations": [
      {
        "citation_id": "cite_1",
        "source_url": "https://oneuptime.com/blog/post/redis-single-threaded-io",
        "verified_claim": "Redis uses a single main thread running an event loop with non-blocking I/O multiplexing..."
      }
    ]
  }
}
```

---

### 4. Inspect Granular Audit Trail
```bash
GET /research/{run_id}/trace
```
Returns a complete, step-by-step audit log tracking agent names, latency in milliseconds, token spend, and input/output payloads for telemetry and compliance analysis.

---

## Production Deployment with Upstash Redis

When deploying to cloud providers (Render, Railway, Fly.io, AWS, Google Cloud Run):

1. Create a serverless Redis database on [Upstash](https://upstash.com/).
2. Copy the secure TLS connection string (`rediss://...`).
3. Set your deployment environment variables:
   ```bash
   REDIS_URL="rediss://default:YOUR_PASSWORD@your-cluster.upstash.io:6379"
   LLM_PROVIDER="gemini"
   GEMINI_API_KEY="your-gemini-key"
   ```
4. **Zero Code Changes:** The built-in persistence layer detects the secure `rediss://` schema, enables SSL encryption, automatically probes for RedisJSON support, and manages checkpoints transparently.

---

## Verification & Testing Suite

Execute the automated test suite across all modules:
```bash
# Run all unit and integration tests
pytest

# Run tests with verbose output
pytest -v

# Run only persistence & recovery tests
pytest tests/test_persistence/

# Run static typing verification
mypy src/

# Run code style & formatting checks
ruff check src/
```

---

## License
MIT License. Free for open-source and commercial use.
