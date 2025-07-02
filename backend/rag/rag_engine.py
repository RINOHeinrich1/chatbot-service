from rag.index import build_or_load_index
from rag.embedding import get_embedding
from rag.generation import generate
from rag.cache import get_cache, set_cache
from qdrant_client import QdrantClient

from qdrant_client.models import Filter, SearchParams,MatchAny,FieldCondition,Filter
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
    print(f"FILTER CONDITION:{filter_condition}")
    search_result = client.search(
        collection_name=collection_name,
        query_vector=query_vector,
        limit=k,
        with_payload=True,
        query_filter=filter_condition  # <-- ici on filtre
    )

    return [hit.payload["text"] for hit in search_result if hit.score > threshold]

def generate_answer(query, docs):
    cached = get_cache(query, docs)
    if cached:
        return cached

    if not docs:
        return "Je ne dispose pas d'informations pertinentes pour répondre à cette question."

    contexte = "\n---\n".join(docs)

    result= contexte
    set_cache(query, docs, result)
    return result
