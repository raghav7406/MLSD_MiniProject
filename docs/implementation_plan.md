# Implementation Plan: Health Insurance Pre-Authorisation Desk

This document serves as the step-by-step implementation blueprint for the MLSD Mini Project. AI coding agents should process these phases sequentially, verifying the functionality of each phase before proceeding to the next.

## Phase 1: Foundation & Data Contracts
**Goal:** Establish the project skeleton, environment, and robust data validation schemas.

1.  **Initialize Repository:** Create the directory structure as defined in the project specifications.
2.  **Define Environment (`.env.example`):** Define keys for `OPENAI_API_KEY` (or equivalent), `REDIS_URL`, and vector store paths.
3.  **Data Contracts (`data_contracts/preauth_schema.py`):**
    *   Implement Pydantic models for the input payload (`PreAuthRequest`).
    *   Enforce constraints: `policy_tenure_months` (0-120), `estimated_cost` (>0), and valid `AdmissionType` enums.
    *   Implement Pydantic models for the output payload (`PreAuthResponse`), including recommendation (APPROVE, REJECT, QUERY), indicative limit, and citations.

## Phase 2: Ingestion & Retrieval Pipeline (RAG)
**Goal:** Process health insurance policy PDFs and create a searchable vector database.

1.  **Chunking (`src/ingestion/chunker.py`):**
    *   Implement PDF parsing (e.g., using PyPDF2 or Unstructured).
    *   Implement semantic or recursive character text splitting. Ensure clauses and exclusion codes (e.g., `Code-Excl02`) remain intact within chunks.
2.  **Vector Store (`src/ingestion/vector_store.py`):**
    *   Set up ChromaDB or FAISS.
    *   Create functions to embed chunks and perform similarity search (`retrieve_corpus_clause`).
3.  **Ingestion Script (`src/ingestion/ingest_pipeline.py`):**
    *   Create a CLI script to ingest `corpus/care_supreme_policy.pdf` and `corpus/optima_restore_policy.pdf` into the vector store.

## Phase 3: Dual-Agent Architecture (LangGraph)
**Goal:** Build the reasoning engine that classifies the request and verifies policy coverage.

1.  **State Definition (`src/agents/state.py`):** Define the `AgentState` TypedDict to track request data, retrieved clauses, verification status, and step counts.
2.  **Agent Tools (`src/agents/tools.py`):** Expose the vector store retrieval functions as tools for the LLM.
3.  **Clinical Agent (`src/agents/clinical_agent.py`):**
    *   Build a node to parse the `diagnosis_name` and `procedure_name`.
    *   Map the procedure to standard medical categories (e.g., categorizing "phacoemulsification" as "cataract surgery").
4.  **Coverage Agent (`src/agents/coverage_agent.py`):**
    *   **Crucial Business Logic:** Implement a two-pass retrieval. 
        *   Pass 1: Base coverage.
        *   Pass 2: Waiting periods/exclusions.
    *   **Hardcoded Scenario Handling:** Ensure the agent evaluates policy tenure against specific waiting periods (e.g., Cataract surgery requires 24 months tenure under `Code-Excl02`. If tenure is 11 months, output must be REJECT/QUERY).
5.  **Graph Orchestration (`src/agents/graph.py`):**
    *   Wire the nodes using LangGraph.
    *   Implement a routing mechanism to prevent infinite loops (max 5 steps) and handle escalations.

## Phase 4: Async API & Services
**Goal:** Expose the agent workflow via a non-blocking REST API.

1.  **Quarantine Service (`src/services/quarantine.py`):**
    *   Implement logic to catch Pydantic validation errors and save the rejected raw payloads to `quarantine_records.json`.
2.  **Worker Queue (`src/services/worker.py`):**
    *   Set up Celery with a Redis broker.
    *   Create a task that takes a validated `PreAuthRequest`, runs the LangGraph workflow, and stores the result.
3.  **FastAPI Server (`src/services/api.py`):**
    *   POST `/api/v1/preauth`: Accept request, validate via Pydantic (quarantine if fail), dispatch to Celery, return a `task_id`.
    *   GET `/api/v1/preauth/{task_id}`: Return the processing status and final recommendation.

## Phase 5: Guardrails
**Goal:** Ensure LLM outputs are grounded and safe.

1.  **Output Filtering (`src/guardrails/prompt_guard.py`):**
    *   Implement a check to ensure all `citations` provided by the Coverage Agent actually exist in the `retrieved_clauses`. If ungrounded, trigger an escalation flag.

## Phase 6: Client UI
**Goal:** Build a simple interface to interact with the API.

1.  **Streamlit App (`src/client/app.py`):**
    *   Create a form mapping to the `PreAuthRequest` schema.
    *   Handle async polling (submit request -> get task ID -> poll until complete -> display result).
    *   Display the final recommendation, approved limits, and cited policy clauses.

## Phase 7: Evaluation & Observability
**Goal:** Test for accuracy, performance, and operational health.

1.  **Evaluation (`eval/evaluate_rag.py` & `eval_dataset.json`):**
    *   Populate JSON with at least 5 test cases (including the 11-month cataract scenario).
    *   Write a script using TruLens or Ragas to evaluate context relevance and groundedness.
2.  **Metrics (`observability/prometheus.yml` & Docker):**
    *   Configure the FastAPI app to expose `/metrics` (request counts, latency).
    *   Set up `docker-compose.yml` to spin up the App, Redis, Prometheus, and Grafana.
3.  **Load Testing (`load_test/locustfile.py`):**
    *   Write a Locust script to simulate concurrent API requests against the async endpoint.