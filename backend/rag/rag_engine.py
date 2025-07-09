from rag.embedding import get_embedding
from rag.generation import generate
from rag.cache import get_cache, set_cache
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, SearchParams,MatchAny,FieldCondition,Filter
from dotenv import load_dotenv
from supabase import create_client, Client
import requests
import json
import os
load_dotenv()
TOKEN = os.getenv("AI_API_TOKEN")
PRODUCT_ID = os.getenv("AI_PRODUCT_ID")
URL = f"https://api.infomaniak.com/1/ai/{PRODUCT_ID}/openai/chat/completions"
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

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
            query_filter=filter_condition  # <-- ici on filtre
        )
    else:
        search_result=["Aucun contexte disponible"]
        return search_result

    return [hit.payload["text"] for hit in search_result if hit.score > threshold]

def retrieve_from_all_collections(client, collection_names, query, k=5, threshold=0.5, document_filter=None):
    all_docs = []
    for collection_name in collection_names:
        docs = retrieve_documents(client, collection_name, query, k, threshold, document_filter)
        all_docs.extend(docs)
    return all_docs[:k]  # limiter à k documents au total

def generate_answer(query, docs):
    cached = get_cache(query, docs)
    if cached:
        return cached

    # 1. Récupérer la description du chatbot
    try:
        res = supabase.table("chatbots").select("description").eq("id", chatbot_id).single().execute()
        description = res.data.get("description", "").strip()
    except Exception as e:
        description = ""
        print(f"Erreur récupération description chatbot : {e}")

    # 2. Prompt system combiné
    system_prompt = (
        f"Tu dois toujours répondre  à partir des **contextes fournis** en  suivant la description suivante :{description if description else 'sois poli et clair.'}"
        "Si le contexte est vide, contente-toi de répondre aux salutations de l'utilisateur."
    )
    print("Description: ",description)
    # 3. Construire le message utilisateur avec contexte
    contexte = "\n---\n".join(docs)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Voici le contexte :\n{contexte}\n\nVoici la question :\n{query}"}
    ]
    print(f"CONTEXT: {contexte}")

    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "mixtral",
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 512,
    }

    try:
        response = requests.post(URL, headers=headers, data=json.dumps(payload))
        response.raise_for_status()
        result = response.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        result = f"Erreur lors de la génération de la réponse : {str(e)}"

    set_cache(query, docs, result)
    return result
