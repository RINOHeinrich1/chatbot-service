
from .embedding import get_embedding
from qdrant_client.models import Filter, FieldCondition, MatchAny,MatchValue
import requests
from utils.helpers import generate_jwt
from config import *

def get_postgres_service_url(source_name: str) -> str:
    try:
        response = supabase.table("postgresql_connexions") \
            .select("postgres_service_url") \
            .eq("connexion_name", source_name) \
            .single() \
            .execute()

        return response.data.get("postgres_service_url", "")
    except Exception as e:
        print(f"[Erreur Supabase] Impossible de récupérer l'URL du service PostgreSQL pour '{source_name}': {e}")
        return ""

def render_template_from_service(service_url: str, template: str, conn_data: dict) -> str:
    try:
        jwt_token = generate_jwt()

        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Content-Type": "application/json",
        }

        payload = {
            "host": str(conn_data.get("host_name", "")),
            "port": str(conn_data.get("port", "")),
            "user": str(conn_data.get("user", "")),
            "password": str(conn_data.get("password", "")),
            "dbname": str(conn_data.get("database", "")),
            "ssl_mode": str(conn_data.get("ssl_mode", "")),
            "template": str(template),
        }

        resp = requests.post(
            f"{service_url}/render",
            json=payload,
            headers=headers,
            timeout=5
        )

        if resp.status_code == 200:
            return resp.text
        else:
            print(f"Erreur rendu template : {resp.status_code} - {resp.text}")
    except Exception as e:
        print(f"Exception lors du rendu template : {e}")
    return "[Erreur de rendu]"

def retrieve_documents(client, collection_name, query, k=5, threshold=0, document_filter=None, apply_contextual_filter=False):
    query_vector = get_embedding([query])[0]
    filter_conditions = []

    if document_filter:
        # Filtrer par source
        filter_conditions.append(
            FieldCondition(
                key="source",
                match=MatchAny(any=document_filter)
            )
        )

        # Si c'est une connexion, on applique le filtre "contextual = true"
        if apply_contextual_filter:
            filter_conditions.append(
                FieldCondition(
                    key="contextual",
                    match=MatchValue(value="true")
                )
            )

        filter_condition = Filter(must=filter_conditions)
    else:
        print("[Info] Aucun document_filter spécifié, pas de récupération possible.")
        return []

    search_result = client.search(
        collection_name=collection_name,
        query_vector=query_vector,
        limit=k,
        with_payload=True,
        query_filter=filter_condition,
        with_vectors=False
    )

    documents = []
    for hit in search_result:
        if hit.score <= threshold:
            continue

        payload = hit.payload
        text = payload.get("text", "")
        source = payload.get("source", "")
        is_template = str(payload.get("template", "")).lower() == "true"

        if is_template:
            service_url = get_postgres_service_url(source)
            if service_url:
                res_conn = supabase.table("postgresql_connexions") \
                    .select("data_schema, host_name, port, user, password, database, ssl_mode") \
                    .eq("connexion_name", source) \
                    .single().execute()

                if res_conn.data:
                    text = render_template_from_service(
                        service_url=service_url,
                        template=text,
                        conn_data=res_conn.data
                    )
                else:
                    print("Connexion non trouvée dans Supabase")

        documents.append({
            "text": text,
            "source": source
        })
    return documents
