# Incident Log

## INC-001 – Vector Store Empty on First Run (2026-11-11)

**Date:** 2026-11-11  
**Severity:** High – all requests returned QUERY/escalation  
**Reporter:** Development team during integration testing  

### Symptom
All pre-auth requests were returning `QUERY` with reason "No supporting policy clause was retrieved; manual review is required." even for well-known cases like cataract after 24 months.

### Diagnosis
The `VectorStore` was loading from `data/vector_store.json` but the file was either missing or contained only 2 original chunks (from the stub `F.txt` placeholder). The `corpus_search()` function returned empty results for all queries, causing the coverage agent to escalate every request.

Additionally, `src/agents/tools.py` caches the `VectorStore` instance globally (`_store`). Tests were sharing the same instance and the cached store from a previous run with an old path was being reused.

### Impact
100% of requests incorrectly escalated during the development session. No production impact (prototype environment only).

### Fix
1. Expanded `data/corpus/` with comprehensive policy documents (`care_supreme_policy.txt` ~200 lines, `optima_restore_policy.txt`, `daycare_procedures.txt`).
2. Re-ran `python -m src.ingestion.ingest_pipeline --force` to rebuild the vector store with 27 chunks.
3. Added `reset_store()` function to `tools.py` and called it in the `conftest.py` fixture so tests get a clean store.
4. Updated `Dockerfile` to run ingestion with `--force` at build time.

### Prevention
- The `Dockerfile` now always rebuilds the index during `docker compose build`.
- `conftest.py` fixture isolates test environments.
- Added `test_ingest_creates_store` test to catch empty corpus issues.

---

## INC-002 – Citation Grounding Failure on Valid Approvals (2026-11-11)

**Date:** 2026-11-11  
**Severity:** Medium – correct decisions downgraded to QUERY  
**Reporter:** Test suite (6 failures)

### Symptom
Workflow tests for cataract approval, emergency admission, and hernia rejection were failing. All returning `QUERY` instead of `APPROVE`/`REJECT`. The verify_decision node was marking citations as "ungrounded."

### Diagnosis
The `_build_citations()` function in `coverage_agent.py` was truncating citation clause text to 500 characters before storing in `Citation.clause`. The `validate_grounding()` function was doing an exact set-membership check: `citation.clause in retrieved_set`. Since `retrieved_clauses` stored the full text (up to ~600 chars per chunk), truncated citations at 500 chars did not match the full stored text strings exactly.

### Impact
6/14 workflow tests failing. Correct business decisions (REJECT for cataract before waiting period, APPROVE for emergency) were being overridden to QUERY by the verification step.

### Fix
1. Changed `_build_citations()` to store the full text without truncation.
2. Changed `validate_grounding()` to use substring matching (`clause in retrieved_text or retrieved_text in clause`) instead of exact set membership.
3. Updated `verify_decision()` to use the same substring matching logic.

### Prevention
- Added grounding-specific tests in `test_guardrails.py` that verify the substring matching behaviour.
- The `verify_decision` function now explicitly documents that it uses substring matching.

