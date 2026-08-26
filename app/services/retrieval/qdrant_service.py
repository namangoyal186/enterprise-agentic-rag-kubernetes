import uuid
import logfire
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from tenacity import before_sleep_log, retry, stop_after_attempt, wait_exponential

from app.config import settings
from app.services.retrieval.embedding import embed_query, embed_texts

# Initialize Qdrant Client
client = QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY)


def ensure_payload_indexes():
    """Ensures Qdrant payload indexes exist for multi-tenant and thread filtering."""
    try:
        client.create_payload_index(
            collection_name=settings.QDRANT_COLLECTION,
            field_name="is_master_kb",
            field_schema=qmodels.PayloadSchemaType.BOOL,
        )
    except Exception:
        pass

    try:
        client.create_payload_index(
            collection_name=settings.QDRANT_COLLECTION,
            field_name="user_id",
            field_schema=qmodels.PayloadSchemaType.KEYWORD,
        )
    except Exception:
        pass

    try:
        client.create_payload_index(
            collection_name=settings.QDRANT_COLLECTION,
            field_name="thread_id",
            field_schema=qmodels.PayloadSchemaType.KEYWORD,
        )
    except Exception:
        pass


# Ensure indexes on module import
ensure_payload_indexes()


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=5),
    reraise=True,
    before_sleep=before_sleep_log(logfire, "warning"),
)
def _search_enterprise_knowledge(
    query: str,
    limit: int = 8,
    user_id: str | None = None,
    thread_id: str | None = None,
):
    """Internal search with retry logic and thread/tenant-scoped filtering."""
    query_vector = embed_query(query)

    query_filter = None
    if thread_id:
        query_filter = qmodels.Filter(
            should=[
                qmodels.FieldCondition(key="is_master_kb", match=qmodels.MatchValue(value=True)),
                qmodels.FieldCondition(key="thread_id", match=qmodels.MatchValue(value=thread_id)),
            ]
        )
    elif user_id:
        query_filter = qmodels.Filter(
            should=[
                qmodels.FieldCondition(key="is_master_kb", match=qmodels.MatchValue(value=True)),
                qmodels.FieldCondition(key="user_id", match=qmodels.MatchValue(value=user_id)),
            ]
        )

    # Using query_points with automatic fallback if filter index is building
    try:
        response = client.query_points(
            collection_name=settings.QDRANT_COLLECTION,
            query=query_vector,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )
    except Exception as e:
        logfire.warning(f"Filtered vector query raised: {e}; falling back to general search.")
        response = client.query_points(
            collection_name=settings.QDRANT_COLLECTION,
            query=query_vector,
            limit=limit,
            with_payload=True,
        )

    results = []
    for res in response.points:
        payload = res.payload or {}
        results.append({
            "content": payload.get("text", ""),
            "source": payload.get("source", payload.get("filename", "Unknown")),
            "filename": payload.get("filename", payload.get("source", "Unknown")),
            "is_master_kb": payload.get("is_master_kb", True),
            "user_id": payload.get("user_id"),
            "thread_id": payload.get("thread_id"),
            "score": float(res.score) if res.score is not None else 0.0,
        })

    return results


def search_enterprise_knowledge(
    query: str,
    limit: int = 8,
    user_id: str | None = None,
    thread_id: str | None = None,
):
    """
    Performs a high-precision search in the enterprise knowledge base.
    If thread_id is provided, searches Master Knowledge AND documents uploaded in this specific thread.
    """
    try:
        return _search_enterprise_knowledge(query, limit=limit, user_id=user_id, thread_id=thread_id)
    except Exception as e:
        logfire.error(f"❌ Qdrant Search Failed after retries: {e}")
        return []



def upsert_document_chunks(
    chunks: list[str],
    filename: str,
    is_master_kb: bool = False,
    user_id: str | None = None,
    thread_id: str | None = None,
    doc_id: str | None = None,
) -> int:
    """
    Embeds chunks and upserts them into Qdrant Cloud.
    Returns number of chunks indexed.
    """
    if not chunks:
        return 0

    if not doc_id:
        doc_id = str(uuid.uuid4())

    with logfire.span("Upsert Document to Qdrant", filename=filename, is_master=is_master_kb, count=len(chunks)):
        embeddings = embed_texts(chunks)

        points = []
        for i, (chunk, vector) in enumerate(zip(chunks, embeddings)):
            point_id = str(uuid.uuid4())
            payload = {
                "text": chunk,
                "source": filename,
                "filename": filename,
                "chunk_index": i,
                "doc_id": doc_id,
                "is_master_kb": is_master_kb,
            }
            if user_id:
                payload["user_id"] = user_id
            if thread_id:
                payload["thread_id"] = thread_id

            points.append(
                qmodels.PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=payload,
                )
            )

        # Batch upsert in chunks of 64
        for start in range(0, len(points), 64):
            batch = points[start : start + 64]
            client.upsert(
                collection_name=settings.QDRANT_COLLECTION,
                points=batch,
            )

        logfire.info(f"Successfully upserted {len(points)} chunks into Qdrant for {filename}")
        return len(points)
