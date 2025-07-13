from rag.embedding import get_embedding
from rag.cache import get_cache, set_cache
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, SearchParams,MatchAny,FieldCondition,Filter
from dotenv import load_dotenv
from supabase import create_client, Client
from adapters.postgresql import PostgreSQLAdapter
import re
import requests
import time
import json
import jwt
import os
load_dotenv()
TOKEN = os.getenv("AI_API_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
POSTGRESS_SQL_EXECUTOR = os.getenv("POSTGRESS_SQL_EXECUTOR", "https://postgresvectorizer.onirtech.com/execute")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")
PRODUCT_ID = os.getenv("AI_PRODUCT_ID")
URL = f"https://api.infomaniak.com/1/ai/{PRODUCT_ID}/openai/chat/completions"

def generate_answer(query, docs, chatbot_id=None, history=None):
    cached = get_cache(query, docs)
    if cached:
        return cached

    try:
        res = supabase.table("chatbots").select("description").eq("id", chatbot_id).single().execute()
        description = res.data.get("description", "").strip()
    except Exception:
        description = ""

    try:
        conn_info = get_adapter_and_connexion(chatbot_id, supabase,"postgres")
        adapter = conn_info["adapter"]
        connexion_name = conn_info["connexion_name"]
        sql_reasoning_enabled = conn_info["sql_reasoning"]
        table_connexions = conn_info["table_connexions"]

        if sql_reasoning_enabled:
            res_conn = supabase.table(table_connexions).select("*") \
                .eq("connexion_name", connexion_name).single().execute()
            connexion_params = res_conn.data
            schema_text = adapter.get_schema(connexion_params)
        else:
            connexion_params = {}
            schema_text = ""
    except Exception as e:
        print(f"[Erreur chargement SQL reasoning ou schéma] : {e}")
        sql_reasoning_enabled = False
        connexion_params = {}
        schema_text = ""
        adapter = PostgreSQLAdapter()  # fallback

    system_prompt = adapter.format_system_prompt(schema_text, description)

    contexte = "\n---\n".join(f"{doc['text']}\n(Source: {doc.get('source', 'inconnu')})" for doc in docs)

    messages = [{"role": "system", "content": system_prompt}]

    history_formatted = ""
    if history:
        for i, msg in enumerate(history):
            role = "Utilisateur" if msg.role == "user" else "Assistant"
            history_formatted += f"{role} : {msg.content.strip()}\n"

    messages.append({
        "role": "user",
        "content": (
            f"Voici la conversation précédente :\n{history_formatted.strip()}\n\n"
            f"Voici le contexte :\n{contexte.strip()}\n\n"
            f"Voici la question :\n{query.strip()}"
        )
    })

    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "mixtral",
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 512,
    }

    try:
        response = requests.post(URL, headers=headers, data=json.dumps(payload))
        response.raise_for_status()
        raw_result = response.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        raw_result = f"Erreur lors de la génération de la réponse : {str(e)}"
        set_cache(query, docs, raw_result)
        return raw_result

    if sql_reasoning_enabled:
        extracted_query = adapter.extract_query(raw_result)
        print(f"extracted sql: {extracted_query}")

        if extracted_query:
            sql_result = adapter.execute_query(connexion_params, extracted_query)
            final_answer = adapter.format_result_for_user(query, sql_result)
        else:
            final_answer = raw_result
    else:
        final_answer = raw_result

    set_cache(query, docs, final_answer)
    return final_answer
