import sys
import types

# ── Shim for legacy Ragas vertexai import crash ──────────────────────────────
if "langchain_community.chat_models.vertexai" not in sys.modules:
    dummy_vertex = types.ModuleType("langchain_community.chat_models.vertexai")
    dummy_vertex.ChatVertexAI = None
    sys.modules["langchain_community.chat_models.vertexai"] = dummy_vertex
# ──────────────────────────────────────────────────────────────────────────────

import asyncio
import os
import instructor
import logfire
import pandas as pd
from openai import AsyncOpenAI
from langchain_community.embeddings import HuggingFaceEmbeddings
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms.base import InstructorLLM
from ragas.metrics.collections import (
    AnswerCorrectness,
    AnswerRelevancy,
    ContextPrecision,
    ContextRecall,
    Faithfulness,
)
from app.gateway.key_manager import key_rotator

COOLDOWN_STANDARD = 2
COOLDOWN_MINI = 1
GENERAL_BATCH_SIZE = 1
CONTEXT_TRUNCATE = 500
CONTEXT_LIMIT = 2


def _build_judge():
    google_key = os.getenv("GOOGLE_API_KEY")
    if google_key:
        # Use Google AI Studio OpenAI-compatible endpoint with active model
        raw_client = AsyncOpenAI(
            api_key=google_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )
        judge_model = "gemini-3.6-flash"
    else:
        # Fallback to Groq if GOOGLE_API_KEY is not set
        raw_client = AsyncOpenAI(
            api_key=key_rotator.get_key(),
            base_url="https://api.groq.com/openai/v1",
        )
        judge_model = os.getenv("GROQ_MODEL", "qwen/qwen3.6-27b")

    patched_client = instructor.from_openai(raw_client, mode=instructor.Mode.MD_JSON)

    judge_llm = InstructorLLM(
        client=patched_client,
        model=judge_model,
        provider="openai",
    )

    hf_emb = HuggingFaceEmbeddings(
        model_name="sentence-transformers/all-MiniLM-L6-v2",
        model_kwargs={"device": "cpu"},
    )
    judge_embeddings = LangchainEmbeddingsWrapper(hf_emb)

    return judge_llm, judge_embeddings


async def _cooldown(seconds: int, label: str, status_cb=None):
    msg = f"⏳ {seconds}s cooldown after {label}..."
    if status_cb:
        status_cb(msg)
    await asyncio.sleep(seconds)
    if status_cb:
        status_cb("✅ Ready — starting next experiment.")


def _prep_samples(golden_dataset: dict) -> list:
    valid = []
    for s in golden_dataset.get("rag_samples", []):
        response = s.get("actual_response", "").strip()
        if not response:
            continue
        raw_contexts = s.get("actual_contexts") or s.get("relevant_contexts") or []
        contexts = [str(c)[:CONTEXT_TRUNCATE] for c in raw_contexts[:CONTEXT_LIMIT]]
        valid.append({**s, "actual_contexts": contexts})
    return valid[:3]


def _score_df(metric_key: str, samples: list, scores) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "question": s["question"][:65],
                metric_key: round(float(getattr(r, "value", r)), 3),
            }
            for s, r in zip(samples, scores)
        ]
    )


async def _batched_score(metric, inputs: list, samples: list, status_cb=None, label: str = "") -> list:
    all_scores = []
    batches = [inputs[i : i + GENERAL_BATCH_SIZE] for i in range(0, len(inputs), GENERAL_BATCH_SIZE)]
    for b_idx, batch in enumerate(batches):
        if b_idx > 0:
            await _cooldown(COOLDOWN_MINI, f"{label} batch {b_idx}", status_cb)
        scores = await metric.abatch_score(batch)
        all_scores.extend(scores)
    return all_scores


async def run_all_metrics(golden_dataset: dict, status_cb=None) -> dict:
    judge_llm, ragas_embeddings = _build_judge()
    samples = _prep_samples(golden_dataset)

    if not samples:
        raise ValueError("No samples with actual_response found. Run Step 2 first.")

    results = {}

    with logfire.span("🧪 Eval Phase 2 — All Metrics", total_samples=len(samples)):
        # ── Exp 1: Faithfulness ───────────────────────────────────────────────
        if status_cb:
            status_cb(f"🧪 Exp 1/6 — Faithfulness ({len(samples)} samples)...")
        with logfire.span("🧪 Exp 1 — Faithfulness"):
            inputs = [
                {
                    "user_input": s["question"],
                    "response": s["actual_response"],
                    "retrieved_contexts": s["actual_contexts"],
                }
                for s in samples
            ]
            metric = Faithfulness(llm=judge_llm)
            scores = await _batched_score(metric, inputs, samples, status_cb, "Faithfulness")
            df = _score_df("faithfulness", samples, scores)
            results["faithfulness"] = df
            logfire.info("🧪 Faithfulness done", avg=round(df["faithfulness"].mean(), 3))

        await _cooldown(COOLDOWN_STANDARD, "Faithfulness", status_cb)

        # ── Exp 2: Answer Relevancy ───────────────────────────────────────────
        if status_cb:
            status_cb(f"🧪 Exp 2/6 — Answer Relevancy ({len(samples)} samples)...")
        with logfire.span("🧪 Exp 2 — Answer Relevancy"):
            inputs = [{"user_input": s["question"], "response": s["actual_response"]} for s in samples]
            metric = AnswerRelevancy(llm=judge_llm, embeddings=ragas_embeddings)
            scores = await _batched_score(metric, inputs, samples, status_cb, "Answer Relevancy")
            df = _score_df("answer_relevancy", samples, scores)
            results["answer_relevancy"] = df
            logfire.info("🧪 Answer Relevancy done", avg=round(df["answer_relevancy"].mean(), 3))

        await _cooldown(COOLDOWN_STANDARD, "Answer Relevancy", status_cb)

        # ── Exp 3: Context Precision ──────────────────────────────────────────
        if status_cb:
            status_cb(f"🧪 Exp 3/6 — Context Precision ({len(samples)} samples)...")
        with logfire.span("🧪 Exp 3 — Context Precision"):
            inputs = [
                {
                    "user_input": s["question"],
                    "reference": s["reference"],
                    "retrieved_contexts": s["actual_contexts"],
                }
                for s in samples
            ]
            metric = ContextPrecision(llm=judge_llm)
            scores = await _batched_score(metric, inputs, samples, status_cb, "Context Precision")
            df = _score_df("context_precision", samples, scores)
            results["context_precision"] = df
            logfire.info("🧪 Context Precision done", avg=round(df["context_precision"].mean(), 3))

        await _cooldown(COOLDOWN_STANDARD, "Context Precision", status_cb)

        # ── Exp 4: Context Recall ─────────────────────────────────────────────
        if status_cb:
            status_cb(f"🧪 Exp 4/6 — Context Recall ({len(samples)} samples)...")
        with logfire.span("🧪 Exp 4 — Context Recall"):
            inputs = [
                {
                    "user_input": s["question"],
                    "reference": s["reference"],
                    "retrieved_contexts": s["actual_contexts"],
                }
                for s in samples
            ]
            metric = ContextRecall(llm=judge_llm)
            scores = await _batched_score(metric, inputs, samples, status_cb, "Context Recall")
            df = _score_df("context_recall", samples, scores)
            results["context_recall"] = df
            logfire.info("🧪 Context Recall done", avg=round(df["context_recall"].mean(), 3))

        await _cooldown(COOLDOWN_STANDARD, "Context Recall", status_cb)

        # ── Exp 5: Answer Correctness ─────────────────────────────────────────
        if status_cb:
            status_cb(f"🧪 Exp 5/6 — Answer Correctness ({len(samples)} samples)...")
        with logfire.span("🧪 Exp 5 — Answer Correctness"):
            inputs = [
                {
                    "user_input": s["question"],
                    "response": s["actual_response"],
                    "reference": s["reference"],
                }
                for s in samples
            ]
            metric = AnswerCorrectness(llm=judge_llm, embeddings=ragas_embeddings)
            all_scores = await _batched_score(metric, inputs, samples, status_cb, "Answer Correctness")
            df = _score_df("answer_correctness", samples, all_scores)
            results["answer_correctness"] = df
            logfire.info("🧪 Answer Correctness done", avg=round(df["answer_correctness"].mean(), 3))

        await _cooldown(COOLDOWN_STANDARD, "Answer Correctness", status_cb)

        # ── Exp 6: Tool Correctness ───────────────────────────────────────────
        if status_cb:
            status_cb("⚡ Exp 6/6 — Tool Correctness...")
        with logfire.span("🧪 Exp 6 — Tool Correctness"):
            tool_rows = []
            for s in samples:
                called = set(s.get("actual_tools_called") or [])
                expected = set(s.get("expected_tools") or [])
                union = len(called | expected)
                score = len(called & expected) / union if union > 0 else 0.0
                tool_rows.append({"question": s["question"][:65], "tool_correctness": round(score, 3)})
            df = pd.DataFrame(tool_rows)
            results["tool_correctness"] = df
            logfire.info("🧪 Tool Correctness done", avg=round(df["tool_correctness"].mean(), 3))

        if status_cb:
            status_cb("✅ All 6 experiments complete!")

    return results