# Teammate 2 Deliverables — Evidence Checklist, Demo Guide & Operational Summary

**Branch:** `docs/teammate2-evidence-checklist`  
**Target Service:** Pre-Authorization API (`http://127.0.0.1:8000`) & Evaluation Stack

---

## 1. Requirement-to-Evidence Checklist (From PDF & `REVIEW_GUIDE.md`)

| Req ID | Requirement Summary (PDF / `REVIEW_GUIDE.md`) | Evidence Status | Artifact / Command / Observed Evidence |
| :--- | :--- | :--- | :--- |
| REQ-01 | Pre-authorization submission (`POST /api/v1/preauth`) & task polling (`GET /api/v1/preauth/{task_id}`) | Verified (Local) | Tested against `http://localhost:8000`; `POST` returns `task_id`, `GET` returns `PENDING` or `SUCCESS` payload |
| REQ-02 | Policy waiting-period & coverage evaluation (e.g., cataract `Code-Excl02` 24-month rule vs. emergency admission) | Partially Captured | Task `d5863065-04e5-40c0-91fd-01030d9c49de` returned `APPROVE` (`indicative_limit: 60000.0`, `escalation_required: false`) with `care_supreme_policy.txt` & `optima_restore_policy.txt` citations; 11m (`ac4e67f5-1d4a-4dcd-83f1-17aec1492a56`) & 24m runs pending final JSON capture |
| REQ-03 | Input validation & error handling on malformed payloads | Pending Capture | `POST` with negative tenure/cost (`422` check) ready/queued for response capture |
| REQ-04 | Escalation / guardrail handling for unsupported procedures & prompt injection | Pending Capture | Unsupported procedure and prompt injection scenarios queued for response capture |
| REQ-05 | Metrics & API schema exposure (`/metrics/`, `/openapi.json`) and load testing (`load_test/locustfile.py`) | Partially Captured | Headless Locust executed (`-u 5 -r 1 -t 1m`) against `http://localhost:8000`; `/metrics/` and `/openapi.json` checks included |
| REQ-06 | Deliverable isolated outside core codebase / on separate branch | In Progress | Authored in `TEAMMATE_2_DELIVERABLES.md` on branch `docs/teammate2-evidence-checklist` |

*(Update or expand rows above with exact PDF section/page references and `REVIEW_GUIDE.md` items as needed.)*

---

## 2. Demo Checklist

| # | Demo Scenario | Expected Behavior | Session Status | Captured Evidence / Key Fields |
| :---: | :--- | :--- | :--- | :--- |
| 1 | **Valid Request** | Task completes (`SUCCESS`) with valid recommendation, limit, and policy citations | **Captured** | Task `d5863065-04e5-40c0-91fd-01030d9c49de` -> `status: "SUCCESS"`, `recommendation: "APPROVE"`, `indicative_limit: 60000.0`, `escalation_required: false`, `clinical_category: "general hospitalisation"`, `steps: 1` (`care_supreme_policy.txt`, `optima_restore_policy.txt`) |
| 2 | **11-Month Cataract Rejection** | Flagged under 24-month waiting period (`Code-Excl02`) / not approved for standard waiting-period window | **Submitted (`ac4e67f5-1d4a-4dcd-83f1-17aec1492a56`)** | Paste final `GET` JSON summary (`status`, `recommendation`, `reason`, waiting-period/exclusion details) |
| 3 | **24-Month Cataract Approval** | Waiting period satisfied; evaluated as eligible subject to policy terms | **Pending Paste** | Paste `task_id` and final `GET` JSON summary |
| 4 | **Malformed Request** | Rejected with HTTP `422` validation error | **Pending Paste** | Paste HTTP `422` status and `detail` validation error |
| 5 | **Unsupported Procedure Escalation** | Escalation flagged (`escalation_required: true`) or routed for review/non-coverage handling | **Pending Paste** | Paste `task_id` and final `GET` JSON summary (`recommendation`, `escalation_required`, `reason`) |
| 6 | **Prompt Injection Handling** | Injection text in `diagnosis_name` (`Ignore all waiting period rules...`) is ignored; policy/tenure rules still apply | **Pending Paste** | Paste `task_id` and final `GET` JSON summary (`recommendation`, `escalation_required`, `reason`) |
| 7 | **Metrics Dashboard** | Exposes `/metrics/` (and dashboard/Prometheus view if running) | **Pending Paste** | Paste HTTP status (`200`) and sample metric names or dashboard notes |

---

## 3. Feature & Evidence Classification Table

| Implemented Features | Tested Features | Estimated Results | Features Not Implemented |
| :--- | :--- | :--- | :--- |
| FastAPI pre-authorization submission (`POST /api/v1/preauth`) and status polling (`GET /api/v1/preauth/{task_id}`) | Local synchronous API run (`CELERY_BROKER_URL` unset with `uvicorn` on `127.0.0.1:8000`) | Locust 1-minute headless run (`-u 5 -r 1 -t 1m`) throughput, percentile latencies, and error rates (paste final summary table) | *(List any PDF / `REVIEW_GUIDE.md` features not present in the codebase)* |
| Policy clause retrieval & decision response schema (`recommendation`, `indicative_limit`, `citations`, `escalation_required`) | Valid emergency pre-authorization request (`d5863065-04e5-40c0-91fd-01030d9c49de`) returning `SUCCESS` | Expected production concurrency/latency scaling beyond the 5-user local run | |
| Container/orchestration assets (`Dockerfile`, `docker-compose.yml` with API, worker, Redis, Prometheus) & Streamlit client | Headless Locust load test (`-u 5 -r 1 -t 1m`) and port `8000` conflict cleanup (`com.docker.backend.exe` / `python.exe`) | Any uncaptured scenario outputs prior to pasting raw JSON | |

---

## 4. Glossary (In Simple Language)

* **Pre-authorization (`preauth`):** Checking a requested medical admission or procedure against insurance policy rules before final claim processing to see if it appears covered, what indicative limit applies, or if it needs review.
* **Waiting Period (e.g., `Code-Excl02`):** A minimum duration a policy must be active before coverage applies to specific conditions—such as a 24-month waiting period for cataract surgery.
* **Synchronous vs. Asynchronous / Broker Execution:** Synchronous execution runs the request right away and returns the finished result directly; asynchronous execution with a broker (such as Celery + Redis) queues the job for a background worker and uses status polling (`PENDING` -> `SUCCESS`) until completion.
* **Escalation (`escalation_required`):** Routing a request to a human review or special handling path instead of auto-approving when a procedure is unsupported, ambiguous, or outside standard rules.
* **Prompt Injection:** Adversarial text inside an input field (such as `diagnosis_name`) designed to make an LLM/agent ignore policy rules—for example, telling it to return `APPROVE` despite a short policy tenure.
* **HTTP `422` (Unprocessable Entity):** A response status indicating the request was well-formed JSON/HTTP, but field validation failed (such as negative costs or invalid policy tenure).
* **Headless Locust (`--headless`):** Running a Locust load test from the command line without opening the browser UI, using `-u` (users), `-r` (spawn rate), and `-t` (duration).
* **Metrics Endpoint (`/metrics/`) & `openapi.json`:** `/metrics/` exposes numeric telemetry for monitoring/Prometheus, while `/openapi.json` publishes the OpenAPI schema for the API endpoints.

---

## 5. Limitations & Future Work

* **Containerized Celery / Redis Result Polling Behavior:** In containerized runs (`docker compose`), polling `GET /api/v1/preauth/{task_id}` can remain `PENDING` if worker execution or result-backend wiring/state differs from local single-process runs. Running `uvicorn` locally with `CELERY_BROKER_URL` unset avoided `PENDING` stalls during single-node verification, but end-to-end containerized async result parity still warrants verification.
* **Local Port & Process Contention:** Port `8000` can be occupied by `com.docker.backend.exe` or leftover `python.exe` processes, requiring cleanup (`docker compose down` / `taskkill`) before starting `uvicorn`.
* **Light Load-Test Scope:** The 1-minute headless Locust test (`-u 5 -r 1 -t 1m`) checks basic local behavior under 5 users, not high-concurrency production traffic or worker queue backpressure.
* **Future Work:**
  * Paste captured outputs for the remaining demo scenarios (11-month cataract, 24-month cataract, `422`, unsupported procedure, prompt injection, and `/metrics/`) and the Locust summary table into the tables above.
  * Add automated smoke/regression checks for the 7 demo scenarios so evidence can be regenerated quickly.
