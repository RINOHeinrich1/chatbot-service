import requests
import json
from utils.helpers import *
from config import *
from .cache import *
import os
from datetime import datetime
from .postgres import *
def reformulate_answer_via_llm(query, contexte_text):
    reformulation_prompt = (
        "Tu es un assistant qui reformule une réponse claire, naturelle et concise pour un utilisateur.\n"
        f"Voici la question posée :\n{query}\n\n"
        f"Voici le contexte complet :\n{contexte_text}\n\n"
        "Formule une réponse naturelle, sans mentionner SQL ni format brut.\n"
    )

    messages = [
        {"role": "system", "content": "Tu es un assistant intelligent, clair et naturel."},
        {"role": "user", "content": reformulation_prompt}
    ]

    payload = {
        "model": "mixtral",
        "messages": messages,
        "temperature": 0.5,
        "max_tokens": 300,
    }

    headers = {
        "Authorization": f"Bearer {AI_TOKEN}",
        "Content-Type": "application/json",
    }

    response = requests.post(AI_URL, headers=headers, data=json.dumps(payload))
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()


def ask_mixtral_for_relevant_sources(chatbot_id: str, question: str):
    connexions = get_connexions_for_chatbot(chatbot_id)
    documents = get_documents_for_chatbot(chatbot_id)

    sources = []

    for c in connexions:
        sources.append({
            "type": "connexion",
            "name": c["connexion_name"],
            "description": c["description"]
        })

    for d in documents:
        sources.append({
            "type": "document",
            "name": d["document_name"],
            "description": d["description"]
        })
    mixtral_prompt = (
        "Tu es un assistant intelligent va sélectionner les sources les plus pertinentes pour répondre à une question.\n"
        "Voici la question posée par l'utilisateur :\n"
        f"{question}\n\n"
        "Voici la liste des sources disponibles (documents et connexions) avec leurs descriptions :\n"
        f"{json.dumps(sources, ensure_ascii=False)}\n\n"
        f"Réponds uniquement avec une liste JSON au format suivant :\n"
        "[{\"type\": \"document\" | \"connexion\", \"name\": \"nom_de_la_source\"}, ...]\n"
        "Ne fais aucun commentaire, ne donne aucune explication. "
        "Tu dois obligatoirement choisir un parmis les sources"

    )
    messages = [
        {"role": "system", "content": "Tu es un assistant intelligent qui sélectionne les sources pertinentes."},
        {"role": "user", "content": mixtral_prompt}
    ]

    payload = {
        "model": "mixtral",
        "messages": messages,
        "temperature": 0.5,
        "max_tokens": 300,
    }

    headers = {
        "Authorization": f"Bearer {AI_TOKEN}",
        "Content-Type": "application/json",
    }

    response = requests.post(AI_URL, headers=headers, data=json.dumps(payload))
    response.raise_for_status()

    result = response.json()["choices"][0]["message"]["content"].strip()

    try:
        # On tente de parser comme JSON directement
        sources_selected = json.loads(result)
    except Exception:
        # Sinon on renvoie le texte brut
        sources_selected = result

    return sources_selected

def generate_answer(query, docs, chatbot_id=None, history=None):
    cached = get_cache(query, docs)
    if cached:
        return cached

    try:
        res = supabase.table("chatbots").select("description").eq("id", chatbot_id).single().execute()
        description = res.data.get("description", "").strip()
    except Exception:
        description = ""

    sql_reasoning_enabled = False
    schema_text = ""
    connexion_name = ""
    connexion_params = {}

    try:
        res = supabase.table("chatbot_pgsql_connexions") \
            .select("connexion_name, sql_reasoning") \
            .eq("chatbot_id", chatbot_id) \
            .single() \
            .execute()
        connexion_name = res.data["connexion_name"]
        sql_reasoning_enabled = res.data.get("sql_reasoning", False)
        if sql_reasoning_enabled:
            res_conn = supabase.table("postgresql_connexions") \
                .select("data_schema, host_name, port, user, password, database, ssl_mode") \
                .eq("connexion_name", connexion_name) \
                .single() \
                .execute()
            schema_text = res_conn.data.get("data_schema", "").strip()
            connexion_params = res_conn.data
    except Exception as e:
        print(f"[Erreur chargement SQL reasoning ou schéma] : {e}")

    history_formatted = ""
    if history:
        for msg in history:
            role = "Utilisateur" if msg.role == "user" else "Assistant"
            history_formatted += f"{role} : {msg.content.strip()}\n"

    system_prompt = (
        "Tu es un assistant intelligent, clair et naturel. "
        "Tu prends en compte la conversation précédente pour comprendre les questions vagues. "
        f"Tu suis la consigne suivante : {description or 'réponds poliment et avec clarté.'} "
    )

    if sql_reasoning_enabled and schema_text:
        system_prompt += (
            f"\n\nVoici les informations sur la table PostgreSQL et ses colonnes :\n{schema_text}\n\n"
            "\n\nIMPORTANT :\n"
            "1. Retourne uniquement une requête SQL PostgreSQL valide, exécutable.\n"
            "2. Ne retourne jamais de texte, d'explication ou de balises Markdown (` ```sql ` ou `sql:`).\n"
            "3. La requête doit contenir toutes les clauses nécessaires : SELECT, FROM, GROUP BY, etc.\n"
            "4. Les noms de colonnes et de tables doivent obligatoirement être mis entre guillemets (ex: \"HireDate\").\n"
            "5. Si un champ est agrégé (comme COUNT), utilise GROUP BY si besoin.\n"
            "6. N'oublie jamais de spécifier la table à utiliser pour les requêtes.\n"
            "7. Les requêtes doivent toujours être écrites en une seule ligne.\n"
            "8. Les requêtes doivent être cohérentes avec les types et formats des colonnes.\n"
            "9. Tu dois utiliser uniquement des syntaxes compatibles PostgreSQL.\n"
            "10. Parfois utiliser la fonction AGE() est utile pour la différence entre deux périodes"
        )
    else:
        system_prompt += "\n\nSi tu ne trouves pas la réponse dans les contextes fournis, indique que l'information n'est pas disponible."

    messages = [{"role": "system", "content": system_prompt}]
    contexte = "\n---\n".join(f"{doc['text']}\n(Source: {doc.get('source', 'inconnu')})" for doc in docs)

    messages.append({
        "role": "user",
        "content": (
            f"Voici la conversation précédente entre toi et l'user :\n{history_formatted.strip()}\n\n"
            f"Voici le contexte :\n{contexte.strip()}\n\n"
            f"Voici la question :\n{query.strip()}"
        )
    })

    headers = {
        "Authorization": f"Bearer {AI_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "mixtral",
        "messages": messages,
        "temperature": 0,
        "max_tokens": 300,
    }

    try:
        response = requests.post(AI_URL, headers=headers, data=json.dumps(payload))
        response.raise_for_status()
        raw_result = response.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        raw_result = f"Erreur lors de la génération de la réponse : {str(e)}"
        set_cache(query, docs, raw_result)
        return raw_result

    final_answer = raw_result

    # === SQL Reasoning et ajout dans docs ===
    if sql_reasoning_enabled:
        extracted_sql = extract_sql_from_text(raw_result)
        print(f"SQL à exécutée: {extracted_sql}")
        if extracted_sql:
            sql_result = execute_sql_via_api(connexion_params, extracted_sql)
            if sql_result is not None:
                if len(sql_result) == 0:
                    final_answer = "Aucune donnée trouvée dans la base."
                else:
                    # Ajouter le SQL + résultat comme document
                    docs.insert(0, {
                        "text": (
                            f"Résultat SQL pour la requête suivante :{query}\n"
                            f"{extracted_sql}\n\n"
                            f"Résultat brut :\n{json.dumps(sql_result, indent=2, ensure_ascii=False)}"
                        ),
                        "source": "résultat_sql"
                    })
                    contexte = "\n---\n".join(f"{doc['text']}\n(Source: {doc.get('source', 'inconnu')})" for doc in docs)
                    # Reformuler en langage naturel
                    final_answer = reformulate_answer_via_llm(query, contexte)
            else:
                final_answer = "Aucune donnée trouvée dans la base."
        else:
            final_answer = raw_result

    set_cache(query, docs, final_answer)
    return final_answer
