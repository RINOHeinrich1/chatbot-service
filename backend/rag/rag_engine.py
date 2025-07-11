from rag.embedding import get_embedding
from rag.cache import get_cache, set_cache
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, SearchParams,MatchAny,FieldCondition,Filter
from dotenv import load_dotenv
from supabase import create_client, Client
import re
import requests
import time
import json
import jwt
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



def retrieve_from_all_collections(client, collection_names, query, k=5, threshold=0.5, document_filter=None):
    all_docs = []
    for collection_name in collection_names:
        docs = retrieve_documents(client, collection_name, query, k, threshold, document_filter)
        all_docs.extend(docs)
    return all_docs[:k]  # limiter à k documents au total
POSTGRESS_SQL_EXECUTOR = os.getenv("POSTGRESS_SQL_EXECUTOR", "https://postgresvectorizer.onirtech.com/execute")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")

def extract_sql_from_text(text):
    match = re.search(r"```sql\s+(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip().replace("\\*", "*")  # ✅ Fix anti-slash

    # Fallback : chercher la 1ère ligne qui commence par SELECT
    lines = text.splitlines()
    for line in lines:
        if line.strip().upper().startswith("SELECT"):
            return line.strip().replace("\\*", "*")  # ✅ ici aussi

    return None

def generate_jwt():
    payload = {
        "sub": "service-role",  # ou un ID spécifique
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,  # valide 5 minutes
        "role": "authenticated"  # facultatif selon ton handler Go
    }

    token = jwt.encode(payload, SUPABASE_JWT_SECRET, algorithm="HS256")
    return token

def execute_sql_via_api(connexion_params, extracted_sql):
    try:
        url = os.getenv("POSTGRESS_SQL_EXECUTOR")
        payload = {
            "host": connexion_params["host_name"],
            "port": str(connexion_params["port"]),
            "user": connexion_params["user"],
            "password": connexion_params["password"],
            "dbname": connexion_params["database"],
            "ssl_mode": connexion_params.get("ssl_mode", "disable"),
            "sql": extracted_sql,
        }

        headers = {
            "Authorization": f"Bearer {generate_jwt()}",
            "Content-Type": "application/json"
        }

        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        result = response.json()

        # Assure que le résultat est bien un tableau, même vide
        if result is None:
            return []
        return result

    except Exception as e:
        print(f"[Erreur exécution SQL via API] : {e}")
        return None

def reformulate_answer_via_llm(query, sql_result):
    reformulation_prompt = (
        "Tu es un assistant qui reformule une réponse claire, naturelle et concise pour un utilisateur.\n"
        f"Voici la question posée :\n{query}\n\n"
        f"Voici les résultats SQL obtenus :\n{json.dumps(sql_result, indent=2, ensure_ascii=False)}\n\n"
        "Formule une réponse naturelle, sans mentionner SQL ni format brut."
    )

    messages = [
        {"role": "system", "content": "Tu es un assistant intelligent, clair et naturel."},
        {"role": "user", "content": reformulation_prompt}
    ]

    payload = {
        "model": "mixtral",
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 256,
    }

    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    }

    response = requests.post(URL, headers=headers, data=json.dumps(payload))
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()


def generate_answer(query, docs, chatbot_id):
    cached = get_cache(query, docs)
    if cached:
        return cached

    # 1. Récupérer description chatbot
    try:
        res = supabase.table("chatbots").select("description").eq("id", chatbot_id).single().execute()
        description = res.data.get("description", "").strip()
    except Exception:
        description = ""

    # 2. Récupérer infos connexion SQL
    sql_reasoning_enabled = False
    schema_text = ""
    connexion_name = ""
    connexion_params = {}

    try:
        res = supabase.table("chatbot_pgsql_connexions").select("connexion_name, sql_reasoning").eq("chatbot_id", chatbot_id).single().execute()
        connexion_name = res.data["connexion_name"]
        sql_reasoning_enabled = res.data.get("sql_reasoning", False)

        if sql_reasoning_enabled:
            res_conn = supabase.table("postgresql_connexions").select("data_schema, host_name, port, user, password, database, ssl_mode").eq("connexion_name", connexion_name).single().execute()
            schema_text = res_conn.data.get("data_schema", "").strip()
            connexion_params = res_conn.data
    except Exception as e:
        print(f"[Erreur chargement SQL reasoning ou schéma] : {e}")

    # 3. Construire prompt système
    system_prompt = (
        "Tu es un assistant intelligent, clair et naturel. "
        f"Tu suis la consigne suivante : {description or 'réponds poliment et avec clarté.'} "
    )
    print(schema_text)
    if sql_reasoning_enabled and schema_text:
        system_prompt += (
            f"\n\nVoici le schéma de la base de données PostgreSQL à ta disposition :\n{schema_text}\n\n"
            "Règles de réponse :\n"
            "1. Si tu trouves la réponse dans le contexte fourni, réponds directement et naturellement sans aucun SQL.\n"
            "2. Si la réponse n’est pas présente dans le contexte, retourne uniquement une requête SQL PostgreSQL valide (sans commentaire ni explication).\n"
            "3. Le SQL doit commencer directement par SELECT.\n"
            "4. Ne confond pas Staff et Manager.\n"
            "5. N'oublies pas qu'avec POSTGRESQL, il faut que le nom des tables et des colonnes  soient mis entre guillemets même dans les comparaisons WHERE sauf pour *, postgreSQL est sensible à la casse donc fait attention.\n"
            "6. Exemple: SELECT * FROM \"Employee\" WHERE Title = 'IT Director'; çà c'est incorecte, mais çà c'est correcte SELECT * FROM \"Employee\" WHERE \"Title\" = 'IT Director';"
            "7. Ne retourne jamais du base64, tu les converties en chaine lisible.\n"
            "8. N’utilise pas de balise Markdown ni d'explication, retourne juste la requête."
        )
    else:
        system_prompt += "\n\nSi tu ne trouves pas la réponse dans les contextes fournis, indique que l'information n'est pas disponible."

    # 4. Formater contexte
    contexte = "\n---\n".join(f"{doc['text']}\n(Source: {doc.get('source', 'inconnu')})" for doc in docs)

    # 5. Appel LLM pour générer SQL ou réponse
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Voici le contexte :\n{contexte}\n\nVoici la question :\n{query}"}
    ]

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

    # 6. Si SQL reasoning activé, extraire et exécuter SQL puis reformuler
    if sql_reasoning_enabled:
        extracted_sql = extract_sql_from_text(raw_result)
        print(f"extracted sql: {extracted_sql}")

        if extracted_sql:
            sql_result = execute_sql_via_api(connexion_params, extracted_sql)
            if sql_result:
                if len(sql_result) == 0:
                    final_answer = "Aucune donnée trouvée dans la base."
                else:
                    # Reformuler proprement la réponse via 2e appel LLM
                    final_answer = reformulate_answer_via_llm(query, sql_result)
            else:
                final_answer = "Erreur lors de l'obtention de la réponse"
        else:
            final_answer = raw_result
    else:
        final_answer = raw_result

    # 7. Mettre en cache et retourner
    set_cache(query, docs, final_answer)
    return final_answer