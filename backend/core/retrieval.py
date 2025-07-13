from rag.embedding import get_embedding
from qdrant_client.models import Filter, MatchAny, FieldCondition
import os


def retrieve_documents(client, collection_name, query, k=5, threshold=0, document_filter=None):
    query_vector = get_embedding([query])[0]

    # Appliquer le filtre "in" si document_filter est fourni
    if document_filter:
        filter_condition = Filter(
            must=[
                FieldCondition(
                    key="source",
                    match=MatchAny(any=document_filter)
                )
            ]
        )
    else:
        filter_condition = None

    if filter_condition:
        search_result = client.search(
            collection_name=collection_name,
            query_vector=query_vector,
            limit=k,
            with_payload=True,
            query_filter=filter_condition
        )
    else:
        return [{"text": "Aucun contexte disponible", "source": None}]

    return [
        {
            "text": hit.payload.get("text", ""),
            "source": hit.payload.get("source", "")
        }
        for hit in search_result if hit.score > threshold
    ]
