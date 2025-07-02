from rag.index import build_or_load_index
from rag.embedding import get_embedding
from rag.generation import generate
from rag.cache import get_cache, set_cache
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, SearchParams,MatchAny,FieldCondition,Filter
from dotenv import load_dotenv
import requests
import json
import os
load_dotenv()
TOKEN = os.getenv("AI_API_TOKEN")
PRODUCT_ID = os.getenv("AI_PRODUCT_ID")
URL = f"https://api.infomaniak.com/1/ai/{PRODUCT_ID}/openai/chat/completions"

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

    # Préparation du contexte concaténé
    contexte = "\n---\n".join(docs)

    # Préparation du prompt final (query + contexte)
    messages = [
    {
        "role": "system",
        "content": "Tu es un assistant intelligent. Réponds à la question en te basant uniquement sur le contexte fourni."
    },
    {
        "role": "user",
        "content": f"Voici le contexte :\n{contexte}\n\nVoici la question :\n{query}"
    }
]


    headers = {
        'Authorization': f'Bearer {TOKEN}',
        'Content-Type': 'application/json',
    }

    payload = {
        "model": "mixtral",  # ou autre modèle compatible
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 512
    }

    try:
        response = requests.post(URL, headers=headers, data=json.dumps(payload))
        response.raise_for_status()
        result = response.json()['choices'][0]['message']['content'].strip()
    except Exception as e:
        result = f"Erreur lors de la génération de la réponse : {str(e)}"

    set_cache(query, docs, result)
    return result

