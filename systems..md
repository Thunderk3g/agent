Nice — I’ll fold everything you’ve provided into a single, **developer/coding-agent prompt** that the coding agent can run with.
This prompt is focused on **Phase 1**: make the agent reliably *answer insurance-related questions about Bajaj Allianz eTouch II* using RAG over your `etouch.json` + `etouch-plan-sl.pdf` (both available at base path). It also includes the mapping schema you’ll use later, and clearly calls out the next phase (data-collection & API triggers).

Use this as the canonical instruction for the coding agent.

# Coding-Agent Prompt — Phase 1: Agentic RAG Chat Backend (etouch.json + Qwen 2.5B)

You are a **coding agent**. Build the **Phase 1** backend of an Agentic RAG Chat system for *Bajaj Allianz Life eTouch II*.

**Primary goal (Phase 1):**
Produce a FastAPI-based backend that provides a ChatGPT-style conversational API. The assistant must answer insurance-related queries about the eTouch II product by using retrieval-augmented generation over the structured `etouch.json` (stored at repo root) and the `etouch-plan-sl.pdf` (already provided). The LLM engine is **Qwen 2.5B** accessed via a local Ollama instance at `http://localhost:11434`.

> **Important:** Phase 1 does **not** implement the full onboarding-to-payment flow. It must only support conversational Q\&A and RAG explanation capability using the provided document(s). Later phases will add mapping updates and payment triggers.

---

# What you must implement (Phase 1 — deliverable list)

1. FastAPI service with these minimal endpoints:

   * `POST /session/start`

     * Request: `{ "userId": "optional" }`
     * Response: `{ "sessionId": "<uuid>", "mapping": <initial_mapping_schema> }`
     * Behavior: create a session and return an initialized mapping JSON (using the mapping schema you provided, empty fields).
   * `POST /chat`

     * Request: `{ "sessionId": "<uuid>", "message": "user text" }`
     * Response:

       ```json
       {
         "reply": "assistant text",
         "sources": [{"id":"etouch.json","loc":"variants.Life Shield","score":0.98}],
         "sessionSummary": {... optional short snapshot ...},
         "fallback": false
       }
       ```
     * Behavior: run RAG (retriever -> LLM) and return conversational answer + citations. Save the message in session history.
   * `GET /mapping?sessionId=...`

     * Response: current session mapping JSON (initial empty mapping until Phase 2).
   * `GET /health` — basic health check.

2. Retriever using `etouch.json` (primary) and `etouch-plan-sl.pdf` (secondary)

   * Load and index `etouch.json` file at repo root as canonical structured source for RAG. Break it into retrievable passages (keys/sections), store metadata (`path`, `section`, `confidence`).
   * Optionally, index `etouch-plan-sl.pdf` passages too and include page/section metadata (script `scripts/index_sources.py`).
   * Vector store: use Chroma (preferred) or FAISS. Provide a simple local persistence directory.

3. OllamaService client

   * Async httpx client that calls `OLLAMA_URL` (`http://localhost:11434`) and `OLLAMA_MODEL` (`qwen-2.5b` by default).
   * Implement timeout (20s), retries (3 attempts, exponential backoff), and a circuit-breaker fallback that returns a canned answer and sets `fallback:true` in `/chat` responses if Ollama is unreachable.

4. Agent orchestration (RAG pipeline)

   * For each `/chat`:

     1. Retrieve top-K passages from vector DB by query similarity (K=3).
     2. Build a concise system prompt for Qwen containing:

        * System instructions: persona = friendly, accurate, cite sources when using doc content, never fabricate numeric premium values.
        * The `retrieved_snippets` with metadata and short citations.
        * The `session_summary` (age, variant if present — from mapping; mapping initially empty).
        * The `user_message`.
        * A strict instruction: **return only a natural-language reply** (no required JSON schema for Phase 1). However include a short `SOURCES:` block at the end of the reply listing citation ids you used.
     3. Call Ollama (Qwen) to produce the assistant reply.
   * Post-process: attach `sources` array in API response with `source_id`, `path/section`, and `score`.

5. Session & storage

   * Keep per-session conversation history in memory (for dev) and persist sessions to a simple SQLite/Postgres DB or file for later expansion. Include session `mapping` with the mapping schema you provided (fields empty). Save messages (user/assistant) and timestamp.

6. Mapping skeleton

   * Provide Pydantic models for the mapping JSON you provided (the `personalDetails`, `quoteDetails`, `addOns`, `meta`) and return an initial mapping on `POST /session/start`. (Mapping remains passive in Phase 1.)

7. Logging & observability

   * Log each chat request: sessionId, user query, top retrieved IDs, Ollama latency, and whether fallback used.
   * Return `fallback` boolean in `/chat` response if Ollama was unavailable.

8. Indexing script

   * `scripts/index_sources.py` that:

     * Reads `etouch.json` and splits it into passages keyed by JSON path (e.g., `variants.Life Shield.notes`).
     * Reads `etouch-plan-sl.pdf` and splits into page/paragraph passages.
     * Computes embeddings (use an embedding model available locally or a small embedding method — if not available, stub embeddings by hashing text and use simple BM25 fallback).
     * Writes to Chroma/FAISS for retrieval.

9. README with run instructions

   * How to start Chroma/FAISS (or use in-memory), how to run indexer, how to start FastAPI, and how to seed Ollama (note: Ollama should be running separately at `http://localhost:11434`).

---

# Agent behavior rules (explicit)

* **Truth-first**: always prefer a sourced answer from `etouch.json` or the PDF. If the retrieved content answers the user, cite it.
* **No hallucination of policy numbers**: if the user asks for premium amounts, return a clear statement like: “I can explain the rules, but for numeric premiums I need your inputs (age, sum assured, variant).” (In Phase 1 we do not calculate premiums.)
* **Cite sources**: When you use the brochure or json content, list `SOURCES:` with `source_id` and `path` (e.g., `etouch.json → variants["Life Shield"].notes` or `pdf:page 12`).
* **Fallback**: If Ollama is unreachable, return a helpful fallback (e.g., “I can’t access the reasoning engine right now — here’s a summary from our brochure...”), still use local `etouch.json` to produce a best-effort textual summary.
* **Safety**: If user asks for disallowed tasks (fraud, illegal), refuse politely.

---

# Prompt templates (agent\_orchestrator must implement)

**System prompt (inject at every call):**

```
You are a friendly, precise insurance assistant specialized in the Bajaj Allianz Life eTouch II product.
Use only information from the provided product documents (etouch.json and etouch-plan-sl.pdf).
When answering, briefly summarize the rule and include a SOURCES block with the exact path used from etouch.json or the pdf page.
If numeric calculations are requested, ask for the required inputs (age, sum assured, variant). Do not fabricate numbers.
```

**User + retrieved snippets payload** — include top 3 passages with tags, then user message.

---

# Example /chat request & expected response

Request:

```json
{ "sessionId": "abc-123", "message": "What's the difference between Life Shield and Life Shield ROP?" }
```

Response:

```json
{
  "reply": "Life Shield provides death + terminal illness cover but does not return premiums at maturity. Life Shield ROP provides the same covers and returns total premiums paid on survival to maturity (subject to terms). For example, ROP maturity benefit: Total Premiums Paid (see variant rules).",
  "sources": [
    {"id":"etouch.json","path":"variants.Life Shield","score":0.99},
    {"id":"etouch.json","path":"variants.Life Shield ROP","score":0.98},
    {"id":"etouch-plan-sl.pdf","page":12,"loc":"Variant summaries","score":0.8}
  ],
  "sessionSummary": {},
  "fallback": false
}
```

---

# Phase 1 Acceptance criteria (tests the agent must pass)

1. `POST /session/start` returns a session with initial mapping JSON matching your schema.
2. `POST /chat` with queries like:

   * “What is premium holiday?”
   * “How does Life Shield Plus ADB work?”
   * “What's the entry age limit?”
     For each, the API must return a coherent answer that includes at least one source entry from `etouch.json` or PDF.
3. If Ollama is down, `POST /chat` returns a fallback answer sourced from `etouch.json` and `fallback:true`.
4. The retriever returns passages that map to keys in `etouch.json` (e.g., `variants.Life Shield`, `premium_holiday`).
5. Logging shows retrieval IDs and whether Ollama was used.

---

# Files to create (minimum for Phase 1)

* `app/main.py` — FastAPI app & endpoints
* `app/services/ollama_service.py` — httpx client wrapper with retries
* `app/services/retriever.py` — index loader & query function (etouch.json + pdf)
* `app/services/agent_orchestrator.py` — orchestrates retrieval + Ollama call
* `app/models/pydantic_models.py` — mapping schema + session models
* `scripts/index_sources.py` — indexer for etouch.json & pdf
* `README.md` — run instructions and dev notes
* `requirements.txt` — dependencies (fastapi, httpx, chorma-client or faiss, pydantic, python-multipart, uvicorn)

---
s
# Next steps after Phase 1 (brief)

* Phase 2 will add: conversational slot-filling that updates the `mapping` JSON, deterministic `quote_calculator` module, `POST /documents/upload` with OCR & extraction worker, and `POST /payment`. Keep your code modular so these can be added without major refactor.

---

If you want, I can now:

* scaffold the Phase 1 repo (create files above with working stubs), or
* generate the exact `agent_orchestrator.py` and `ollama_service.py` implementations you can drop into the repo.

Which would you like me to produce right now?
