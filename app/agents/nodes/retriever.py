import logfire

from app.agents.state import AgentState
from app.services.retrieval.qdrant_service import search_enterprise_knowledge
from app.services.retrieval.ranking_service import rerank_documents


def retrieve_node(state: AgentState):
    """
    Performs vector search and semantic reranking for technical queries.
    """
    query = state["current_query"]
    user_id = state.get("user_id")
    thread_id = state.get("thread_id")

    # Standard Retrieval Logic
    with logfire.span("🔍 Knowledge Retrieval"):
        logfire.info(f"Searching Qdrant for: {query} (thread_id={thread_id})")
        raw_results = search_enterprise_knowledge(query, limit=15, user_id=user_id, thread_id=thread_id)

        logfire.info(f"Retrieved {len(raw_results)} candidates from Vector DB")

        if not raw_results:
            return {
                "documents": [],
                "status": "No specific documents matched.",
                "plan": state["plan"] + ["No Documents Found"],
            }

        doc_contents = [doc["content"] for doc in raw_results]

        with logfire.span("⚖️ Semantic Reranking"):
            reranked_contents = rerank_documents(query, doc_contents, top_n=5)
            logfire.info("Reranking complete. Kept top 5 most relevant chunks.")

        # Re-attach metadata for the top reranked chunks
        final_docs = []
        for text in reranked_contents:
            matched_raw = next((r for r in raw_results if r["content"] == text), None)
            if matched_raw:
                final_docs.append(matched_raw)
            else:
                final_docs.append({"content": text, "is_master_kb": True, "source": "Master Knowledge"})

    return {
        "documents": final_docs,
        "status": "Found technical context.",
        "plan": state["plan"] + ["Context Retrieved"],
    }

