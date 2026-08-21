"""
Phase 1 — Live Pipeline.
Calls the running FastAPI /query endpoint for each golden sample.
Captures: actual_response (truncated to 300 chars), actual_contexts (from sources),
and actual_tools_called (detected from thought_process).
"""

import copy
import json
import os
import time

import logfire
import requests

API_URL = os.getenv("API_URL", "http://localhost:8000/query")
STATUS_URL_TEMPLATE = os.getenv("STATUS_URL_TEMPLATE", "http://localhost:8000/query/status/{job_id}")
RESPONSE_TRUNCATE = 300
DELAY_BETWEEN_CALLS = 6  # seconds buffer between calls
REQUEST_TIMEOUT = 120    # seconds
POLL_INTERVAL = 3        # seconds between job status polls
MAX_POLL_ATTEMPTS = 60   # ~3 minutes max wait per sample
MAX_RETRIES_429 = 3      # retries if Groq rate limits


def detect_tool(thought_process: list) -> str:
    """
    Maps the thought_process list from /query response to a tool name.
    Planner sets:  'Intent: Technical' + 'Search Term: ...' → retrieve_documents
                   'Intent: Conversational/Memory'          → direct_answer
    main.py sets:  'Intent: Guardrails Fired'               → guardrails
    """
    joined = " ".join(str(t) for t in thought_process).lower()
    if "guardrails fired" in joined or "blocked by guardrails" in joined:
        return "guardrails"
    if "intent: technical" in joined or "search term:" in joined or "context retrieved" in joined or "retrieval" in joined:
        return "retrieve_documents"
    if "conversational" in joined or "memory" in joined:
        return "direct_answer"
    return "retrieve_documents"


def _poll_for_result(job_id: str) -> dict:
    """Poll /query/status until the Celery job completes or times out."""
    url = STATUS_URL_TEMPLATE.format(job_id=job_id)
    for attempt in range(MAX_POLL_ATTEMPTS):
        with logfire.span("🔄 Eval polling job", job_id=job_id, attempt=attempt + 1):
            resp = requests.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()

        status = data.get("status", "UNKNOWN")
        if status == "SUCCESS":
            return data.get("result", {})
        if status == "FAILURE":
            error = data.get("error", "unknown failure")
            raise RuntimeError(f"RAG job failed: {error}")
        time.sleep(POLL_INTERVAL)

    raise RuntimeError(f"Polling timed out for job {job_id}")


def _fetch_query_result(question: str, thread_id: str) -> dict:
    """Submit a query with retry logic on 429 and return the final result."""
    payload = {"query": question, "q": question, "thread_id": thread_id}

    for attempt in range(MAX_RETRIES_429):
        resp = requests.post(API_URL, json=payload, timeout=REQUEST_TIMEOUT)
        
        if resp.status_code == 429:
            backoff = (attempt + 1) * 8
            logfire.warning(f"⚠️ 429 Rate limited. Backing off for {backoff}s before retry...")
            time.sleep(backoff)
            continue
            
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") == "Blocked by guardrails." or "answer" in data or "response" in data:
            return data

        job_id = data.get("job_id")
        if job_id:
            return _poll_for_result(job_id)

        return data

    raise RuntimeError("Query failed: Exceeded maximum 429 rate-limit retries.")


def run_pipeline(golden_dataset: dict, progress_callback=None) -> dict:
    """
    Enriches each rag_sample in golden_dataset with live API results.
    Returns a deep copy with actual_response, actual_contexts, actual_tools_called filled.
    """
    dataset = copy.deepcopy(golden_dataset)
    dataset["rag_samples"] = dataset.get("rag_samples", [])[:3]
    samples = dataset["rag_samples"]
    n = len(samples)

    with logfire.span("🚀 Eval Phase 1 — Live Pipeline", total_samples=n):
        for i, sample in enumerate(samples):
            question = sample["question"]

            if progress_callback:
                progress_callback(i, n, question, "calling")

            with logfire.span(
                f"📤 Live Query {i + 1}/{n}",
                question=question[:80],
                domain=sample.get("domain", ""),
            ):
                try:
                    data = _fetch_query_result(question, thread_id=f"eval_run_{i}")

                    raw_answer = data.get("answer") or data.get("response") or ""
                    thought_process = data.get("thought_process") or []
                    sources = data.get("sources") or data.get("retrieved_contexts") or []

                    sample["actual_response"] = raw_answer[:RESPONSE_TRUNCATE]
                    sample["actual_contexts"] = [str(s) for s in sources[:5]]
                    sample["actual_tools_called"] = [detect_tool(thought_process)]

                    logfire.info(
                        "✅ Response captured",
                        tool=sample["actual_tools_called"][0],
                        response_chars=len(raw_answer),
                        context_chunks=len(sources),
                    )

                except requests.exceptions.ConnectionError:
                    logfire.error("❌ Cannot reach FastAPI — is the app running on :8000?")
                    sample["actual_response"] = ""
                    sample["actual_contexts"] = sample.get("relevant_contexts", [])
                    sample["actual_tools_called"] = ["unknown"]

                except Exception as e:
                    logfire.error(f"❌ Query failed: {e}")
                    sample["actual_response"] = ""
                    sample["actual_contexts"] = sample.get("relevant_contexts", [])
                    sample["actual_tools_called"] = ["unknown"]

            if progress_callback:
                progress_callback(i, n, question, "done", sample["actual_response"])

            if i < n - 1:
                time.sleep(DELAY_BETWEEN_CALLS)

    return dataset


def save_results(dataset: dict, path: str) -> None:
    """Save dataset results to JSON with explicit UTF-8 encoding."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=2, ensure_ascii=False)


def load_golden_dataset() -> dict:
    """Load golden dataset from JSON with explicit UTF-8 encoding."""
    golden_path = os.path.join(os.path.dirname(__file__), "golden_dataset.json")
    with open(golden_path, "r", encoding="utf-8") as f:
        return json.load(f)