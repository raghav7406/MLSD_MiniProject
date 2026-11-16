# Pre-Auth Desk — Presentation Content, Script & Viva Prep

Nov 16, 2026 · @Rahul

Use these 11 slides (title + the 10 topics your brief listed). Everything below comes from your README, REPORT and REVIEW\_GUIDE, so every number matches the repo. Keep slides to 3–5 short bullets; the talking goes in the script.

## Part 1 — Slide content

### Slide 1 — Title

- Health Insurance Pre-Authorisation Desk
- A multi-agent, citation-grounded recommendation service
- ML System Design & AgentOps (UE24AM342AA5), Mini Project 03
- Team names + SRNs; your own line: PES1UG24AM217

### Slide 2 — The problem

- Before a planned admission, the hospital asks the insurer: covered? how much?
- The answer is spread across the policy: cover section, waiting periods, exclusions, sub-limits, day-care list
- A single search finds the cover clause and misses the rule that modifies it
- Decision needed in minutes, not days

### Slide 3 — Business impact

- Wrong approval becomes a direct loss for the insurer
- Wrong denial becomes a grievance and possibly an IRDAI complaint
- Manual first-level review is slow and inconsistent
- Goal: fast first-level triage that is auditable and knows when not to answer

### Slide 4 — Proposed solution

- Validate → classify → retrieve (multiple passes) → apply rules → verify → route
- Three outcomes: approve-recommended, query-to-hospital, medical-review
- Every answer carries clause-level citations
- If evidence is missing or unverified, it escalates instead of guessing
- Recommendation only. A medical officer decides.

### Slide 5 — Architecture

- Draw this: Client (Streamlit) → FastAPI (rate limit, cache, validation → quarantine) → Celery/Redis queue → Worker → Agent graph → results.json; Prometheus → Grafana beside it
- Mark the deployment boundaries: app, worker, redis, prometheus, grafana (5 containers)
- Why async: runs are multi-step, so the API returns a task\_id immediately and the caller polls

### Slide 6 — Agent / workflow

- Node 1: input guardrails (injection check)
- Node 2: clinical agent classifies into 10 categories, flags pre-existing and exclusions
- Node 3: coverage agent runs 5 retrieval passes with 3 tools (corpus\_search, clause\_lookup, field\_lookup) and applies rules
- Node 4: verification agent checks every citation against retrieved text, retries once with an alternate query, otherwise downgrades to escalation
- Bounds: 10 steps, 20 tool calls, 30 s wall clock; any breach escalates, never approves

### Slide 7 — The hard case: cataract, 11 months

- Input: planned cataract surgery, policy tenure 11 months
- Pass 1 finds the cover clause: cataract is covered
- Pass 2 finds Code-Excl02: 24-month waiting period
- 11 < 24, so not approved. Result: REJECT, route medical-review, both clauses cited
- Contrast: at 24 months the same request returns approve-recommended with the sub-limit
- Show a screenshot of the actual API/Streamlit output

### Slide 8 — Evaluation results

- 78 unit/API/agent tests pass; 25-case evaluation set, 25/25 correct
- Groundedness 1.0, faithfulness 1.0, hallucination rate 0.0
- Deliberate change: 2 large chunks → 27 clause-aware chunks (5 → 25 cases)
- Context relevance fell 0.60 → 0.26: retrieval now pulls exclusion, sub-limit and day-care sections that do not repeat the procedure word. Accuracy unchanged.

### Slide 9 — Deployment and observability

- docker compose up: app, worker, redis, prometheus, grafana with health checks
- docker compose up --scale worker=3 for scaling
- Prometheus metrics, Grafana dashboard, run\_id and correlation\_id in every result and log
- Cache (5-min TTL), rate limit (20 req/min), circuit breaker, quarantine file
- SLO declared up front: p95 < 2 s. Final measured request p95: 54 ms (1 worker), 55 ms (3 workers)

### Slide 10 — Limitations (say them before they are asked)

- Token-overlap retrieval, not semantic embeddings (no FAISS/Chroma)
- Hand-written state graph, not LangGraph/CrewAI
- Deterministic rules, no live LLM, so no free-text reasoning
- 2 illustrative policy documents; JSON persistence; no authentication
- No OpenTelemetry/Jaeger tracing; run\_id log correlation instead

### Slide 11 — Future work

- Embeddings + FAISS/Chroma, with re-embedding without a full rebuild
- LangGraph with an LLM that chooses its next search, behind a provider interface
- OpenTelemetry traces to Jaeger or Tempo
- Real policy wording and day-care list, PostgreSQL results store, JWT auth
- Live quality scoring of sampled runs (TruLens)

## Part 2 — 5-minute speaking script

About 680 words at a steady pace. Time marks are cumulative. Practise it once with a timer; if you run long, cut the slide 9 and 11 lines first.

**Slide 1 (0:00)** Good afternoon. Our project is a Health Insurance Pre-Authorisation Desk: a service that gives an insurer a fast, cited, first-level recommendation on a hospital's pre-authorisation request.

**Slide 2 (0:15)** Here is the problem. Before a planned admission, the hospital asks the insurer: is this covered, and up to how much? The difficulty is that a policy does not keep the answer in one place. The cover section says what is covered, but waiting periods, exclusions and sub-limits sit in other sections. So a simple search finds the cover clause and misses the rule that changes the answer.

**Slide 3 (0:50)** Getting this wrong costs money both ways. A wrong approval is a loss to the insurer. A wrong denial becomes a customer grievance and possibly an IRDAI complaint. And all of it has to happen in minutes. So we need a system that is fast, but also knows when not to answer.

**Slide 4 (1:20)** Our solution works like a careful first-level desk assistant. It validates the request, classifies the treatment, searches the policy several times, applies the rules, checks its own evidence, and routes the case to one of three outcomes: approve-recommended, query-to-hospital, or medical-review. Every answer carries clause-level citations. And it only recommends. A medical officer always makes the final decision.

**Slide 5 (2:00)** Architecture: a Streamlit client calls a FastAPI service, which does rate limiting, caching and validation. Invalid requests are quarantined. Valid ones go onto a Celery and Redis queue, and a worker runs the agent graph. We made it asynchronous because a run has several steps, so the API returns a task ID immediately and the client polls. Five containers, with Prometheus and Grafana for monitoring.

**Slide 6 (2:30)** Inside the worker is a five-node workflow. Guardrails check for prompt injection. The clinical agent classifies the case. The coverage agent runs five retrieval passes using three tools, then applies the rules. The verification agent checks that every citation exists in the retrieved text, retries with a different query if not, and escalates if it still cannot support the answer. The loop is bounded: ten steps, twenty tool calls, thirty seconds.

**Slide 7 (3:10)** Now the demonstration case: planned cataract surgery, policy eleven months old. The first search finds that cataract is covered. The second finds Code-Excl02, a 24-month waiting period. Eleven is less than twenty-four, so the system does not approve. It returns a reject recommendation routed to medical review, citing both clauses. At twenty-four months, the same request is approved with the sub-limit.

**Slide 8 (3:50)** Evaluation: 78 tests pass, and our 25-case evaluation set passes 25 out of 25, with groundedness and faithfulness of 1.0 and zero hallucination. As our deliberate change we split two large chunks into 27 clause-aware chunks. Accuracy stayed the same, but context relevance dropped from 0.60 to 0.26, because we now retrieve exclusions and sub-limits too, which do not repeat the procedure name. We consider that a correct trade-off.

**Slide 9 (4:20)** Operationally, everything starts with docker compose up, and workers can be scaled. Prometheus and Grafana show metrics, every result carries a run ID, and we have caching, rate limiting, a circuit breaker and a quarantine file. Our declared target was p95 under two seconds; the final five-user runs measured 54 milliseconds with one worker and 55 milliseconds with three workers, with zero failures.

**Slide 10 (4:40)** Limitations, honestly: retrieval is token overlap rather than embeddings, the graph is hand-written rather than LangGraph, decisions are deterministic with no live LLM, and the corpus is two illustrative policies.

**Slide 11 (4:55)** Future work is embeddings with FAISS, an LLM-driven agent on LangGraph, OpenTelemetry tracing and a real policy corpus. Thank you. We are happy to take questions.

## Part 3 — Simple explanations (use these when a question is basic)

**Waiting period.** A stretch of time after buying a policy during which certain treatments are not payable, even though the policy covers them in general. In our policy, cataract has a 24-month waiting period (Code-Excl02). A customer at month 11 has not served it, so the claim is not payable yet. The cover section never mentions this, which is the whole difficulty.

**Retrieval.** Looking up the right passages from the policy before deciding, instead of relying on memory. We do not search once. We search for coverage, then for waiting periods and exclusions, then for the specific clause Code-Excl02, then sub-limits, then the day-care list. Each pass catches something a different query would miss.

**Citation grounding.** Every clause the system cites must actually exist in the text it retrieved. The verification step checks this by matching each citation against the retrieved passages. A citation that cannot be found means the answer is not trusted and the case is retried or escalated. This is why our hallucination rate is zero by construction: the system cannot cite a clause it did not retrieve.

**Escalation.** Handing the case to a human instead of answering. It happens when the condition may be pre-existing, the treatment is excluded or outside the corpus, evidence is missing, verification fails, the input looks like prompt injection, or the loop limits are hit. The design rule is: when unsure, route to query or medical review, never approve.

**Why the system does not authorise treatment.** Authorising an admission is a medical and contractual decision with legal consequences. A rule-based system built on two illustrative policies cannot carry that responsibility, and the project brief states it must not. The system produces a recommendation with evidence; the medical officer decides. The output filter and the response wording also prevent it from presenting a recommendation as a final authorisation.

## Part 4 — Likely viva questions and answers

The brief asks for LangGraph/CrewAI, FAISS/Chroma, an LLM with a stub, TruLens and OpenTelemetry. Your repo deliberately does not use these. Examiners will probe that gap, so answers in groups B and C matter most. Never claim something your repo does not do.

### A. Problem and design

**Q1. What problem does your system solve, in one minute?** It gives an insurer a fast first-level recommendation on a pre-authorisation request. The hard part is that waiting periods and exclusions are listed away from the cover clause, so we retrieve those separately, apply rules, verify citations, and escalate when unsure. (Then the cataract example.)

**Q2. Why is the cataract 11-month case hard?** The cover section confirms cataract is covered, and one search returns only that. The 24-month waiting period is in a different section, and the request never mentions it, so a query resembling the request will not retrieve it. We search for waiting periods explicitly and look up Code-Excl02 by identifier.

**Q3. Why did you choose asynchronous execution with a queue?** A run has several steps and, in a production version with an LLM, would take tens of seconds. Returning a task\_id immediately and polling keeps the API responsive, lets us scale workers independently, and puts a queue between submission and execution as the brief requires. A local synchronous fallback exists for development.

**Q4. Why these deployment boundaries (app, worker, redis, prometheus, grafana)?** The API and worker scale differently and fail independently: workers do the heavy work and can be scaled with --scale worker=3 without touching the API. Redis isolates the queue. Prometheus and Grafana are separate so monitoring survives an app crash.

**Q5. What happens if the worker fails mid-run?** The task does not return a result, so the caller sees a non-success status rather than a confident answer. Execution bounds (10 steps, 20 tool calls, 30 s) end runaway runs by escalating. Check RUNBOOK.md and INCIDENT\_LOG.md and quote what they actually say.

### B. Agents and the brief's requirements

**Q6. Is this really an agent, or a fixed pipeline?** Be honest: the coverage agent runs five retrieval passes that are defined in code, so the search sequence is largely fixed. What makes it more than a straight pipeline is verification: it checks the evidence, retries with an alternate query, and escalates. The brief wanted the agent to choose its own tool calls; with an LLM-driven agent on LangGraph that is the natural next step, and we list it as future work.

**Q7. Why not LangGraph or CrewAI, as the brief says?** We wrote a bounded state graph by hand. It has the same graph semantics (nodes, shared state, conditional retry) without heavy dependencies and without package conflicts on Python 3.13, and it keeps behaviour deterministic and auditable. We acknowledge this departs from requirement A1 and name it as an upgrade, not a hidden claim.

**Q8. Are your agents genuinely separate?** There are three roles with distinct responsibilities and a defined hand-off through a shared AgentState: clinical (classification), coverage (retrieval and decision), verification (grounding and consistency). They run in one worker process, so be precise: these are separate modules and roles, not separate services.

**Q9. Where is the LLM?** There is no live LLM in the decision path. Decisions are deterministic rules over retrieved clauses. The benefit is reproducibility, zero API cost and auditability; the cost is that it cannot reason about free text or novel conditions. A provider interface and circuit breaker exist for adding one.

**Q10. Then what do your two prompt versions do?** Prepare this answer before the viva. If the prompts are not used by a live model, say plainly that they are versioned artifacts ready for the LLM path and that the v1 vs v2 comparison you report is about what you actually ran. Open prompts/ and the eval output to confirm what was compared.

**Q11. Why token-overlap retrieval instead of FAISS and embeddings?** Embeddings needed a \~500 MB model. For 27 short, clause-structured chunks, token overlap is dependency-free, deterministic and fast (under 1 ms). Its weakness is paraphrase: it can miss semantically equivalent text. We cover that with multiple targeted passes and a direct clause lookup by identifier, and we list embeddings as future work.

**Q12. How did you chunk the corpus and why?** We split two whole-file chunks into 27 chunks along section boundaries, with clause\_id metadata (for example Code-Excl02). Clause-level chunks let the system cite a specific provision and let clause\_lookup fetch it directly.

### C. Verification, guardrails, safety

**Q13. How does citation grounding work?** Every citation is checked as a substring of the passages retrieved in that run. APPROVE without citations, or for an unsupported category or early pre-existing condition, is blocked. If checking fails, it searches again with an alternate query; if still unresolved it downgrades to QUERY plus MEDICAL\_REVIEW.

**Q14. Does groundedness 1.0 mean the answer is correct?** No. Groundedness means citations exist in retrieved text. Correctness is the separate accuracy metric, 25/25 on our set. Also be ready to say the 25 cases are our own and small, so the scores show consistency on designed cases, not real-world accuracy.

**Q15. How do you stop prompt injection?** prompt\_guard.py scans free-text fields (diagnosis, procedure) for injection patterns before any agent runs. A hit routes the case to medical-review and the injected instruction is not followed. Because decisions are rule-based, injected text cannot change policy rules. Do not claim toxicity detection unless you can show it in the code.

**Q16. What stops the system issuing an authorisation?** The response contract only allows recommendation and route values, the output filter blocks determination language, and the final decision is always for a medical officer. The README and report say it is a recommendation only.

**Q17. What does the circuit breaker do?** It opens after repeated provider failures so the system stops calling a failing dependency and degrades to escalation instead of hanging. With no live LLM it is implemented but only exercised through tests or simulation, so say that if asked to demo it.

### D. Evaluation and performance

**Q18. Your context relevance dropped from 0.60 to 0.26. Why is that acceptable?** The metric rewards chunks that mention the procedure word. After chunking we deliberately retrieve exclusion, sub-limit and day-care sections that do not repeat it, because they bind the decision. Accuracy, groundedness and faithfulness stayed at 100%, 1.0 and 1.0. We report the drop openly as a trade-off.

**Q19. How are the four metrics computed?** Describe exactly what eval/evaluate\_rag.py does, since it is your own implementation rather than TruLens. Read the functions before the viva and be able to state each metric's formula in one sentence.

**Q20. What was your declared SLO and did you meet it?** The declared target was p95 under 2 seconds. The final five-user Docker runs measured 54 ms with one worker and 55 ms with three workers, with zero failures. Be precise that these are aggregate HTTP request percentiles from the Locust submit-and-poll scenario, not one combined transaction timer.

**Q21. What is the bottleneck and what happens with --scale worker=3?** In the current deterministic system, retrieval is sub-millisecond, so the Redis queue and API overhead dominate, and a real LLM call would become the bottleneck. Quote the scaling result you measure, not the report's estimate of roughly 3x.

**Q22. What does caching and rate limiting do?** Cache keys on a SHA-256 of the request with a 5-minute TTL, so repeat requests skip the workflow. Rate limiting is 20 requests a minute per client, mainly cost control against one client looping on a multi-step agent.

### E. Limits and judgement

**Q23. What would you change first with more time?** Add embeddings with FAISS, move to LangGraph with an LLM that chooses its own searches, add OpenTelemetry tracing, and use a real insurer policy and day-care list.

**Q24. Is it safe to use in production?** No. It is an academic prototype: two illustrative policies, no authentication, JSON persistence, no tracing. It is first-level decision support only.

**Q25. What was the biggest failure during development?** Prepare a real one from INCIDENT\_LOG.md (the brief requires at least one genuine entry) and the lesson. The chunking change (2 chunks to 27) is also a good story of finding that retrieval was returning only two results.

## Part 5 — What to do before the presentation

The assignment says that if the system does not start and serve a valid request at the demo, the project gets zero marks. Do the first block first.

### Must do (system works)

- [ ] Clone the repo fresh into a new folder, copy .env.example to .env, run docker compose up --build, and confirm GET /health returns OK
- [ ] Submit the cataract request (11 months) and confirm REJECT, route medical-review, with both clauses cited
- [ ] Submit the same request at 24 months and confirm approve-recommended
- [ ] Run python -m pytest -q (expect 78 passed) and python -m eval.evaluate\_rag --report results/evaluation.json
- [ ] Take screenshots of both results as a backup in case the live demo fails

### Run the 10 demo items from the brief

- [ ] 1 Clean docker compose up
- [ ] 2 Valid request with citations
- [ ] 3 One run traced end to end using run\_id and step\_timings
- [ ] 4 Malformed request returns 422, lands in data/quarantine\_records.json, no run started
- [ ] 5 Unsupported procedure escalates to `QUERY` plus `medical-review` instead of inventing an answer
- [ ] 6 Verification catching an unsupported answer, then re-search or escalation
- [ ] 7 Prompt-injection text in the diagnosis field routes to medical-review
- [ ] 8 Circuit breaker opening (decide how you will show this with no live LLM)
- [ ] 9 Locust run and --scale worker=3 comparison
- [ ] 10 The cataract case

### Honesty checks

- [ ] Quote the final measured results: 1 worker = 245 requests, 4.18 RPS, p95 54 ms; 3 workers = 295 requests, 5.04 RPS, p95 55 ms; both had zero failures
- [ ] Check wording consistency: the README example shows REJECT with route medical-review but escalation\_required false. Decide how you will explain that a rejection is routed to medical-review
- [ ] Read prompts/v1\_conservative.txt, v2\_detailed.txt and the eval comparison so you can say exactly what was compared (Q10)
- [ ] Read eval/evaluate\_rag.py so you can say how each of the 4 metrics is computed (Q19)
- [ ] Open INCIDENT\_LOG.md and RUNBOOK.md and pick one real failure to narrate (Q25)
- [ ] Be ready to say there is no toxicity detection, OpenTelemetry, TruLens, FAISS or LangGraph unless you can point to the code
- [ ] Describe the workflow by responsibilities rather than node count: guardrails, clinical agent, coverage agent, verification, alternate-search retry, and final response

### Prepare the presentation

- [ ] Build the 11 slides from Part 1 (or ask me to turn them into a deck later)
- [ ] Draw the architecture diagram for slide 5 with the 5 containers marked
- [ ] Rehearse the script in Part 2 out loud with a timer; aim for 4:45 to 5:00
- [ ] Split speaking parts between teammates and decide who answers which viva group (A–E)
- [ ] Re-read Part 4 questions Q6, Q7, Q9, Q10, Q14 and Q20 twice; these are the most likely hard ones
