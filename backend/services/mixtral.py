import requests
import json
import os
from datetime import datetime
from config import *
from utils.helpers import *
from .cache import *
from .postgres import *

# === Fonctions utilitaires ===

def call_llm(model, messages, temperature=0.5, max_tokens=300):
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {AI_TOKEN}",
        "Content-Type": "application/json",
    }
    response = requests.post(AI_URL, headers=headers, data=json.dumps(payload))
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()

def build_contexte(docs):
    return "\n---\n".join(
        f"{doc['text']}\n(Source: {doc.get('source', 'inconnu')})" for doc in docs
    )

def get_chatbot_description(chatbot_id):
    try:
        res = supabase.table("chatbots").select("description").eq("id", chatbot_id).single().execute()
        return res.data.get("description", "").strip()
    except Exception:
        return ""

def get_connexion_info(chatbot_id):
    try:
        res = supabase.table("chatbot_pgsql_connexions") \
            .select("connexion_name, sql_reasoning") \
            .eq("chatbot_id", chatbot_id) \
            .single().execute()
        name = res.data["connexion_name"]
        enabled = res.data.get("sql_reasoning", False)

        schema, params = "", {}
        if enabled:
            res_conn = supabase.table("postgresql_connexions") \
                .select("data_schema, host_name, port, user, password, database, ssl_mode") \
                .eq("connexion_name", name) \
                .single().execute()
            schema = res_conn.data.get("data_schema", "").strip()
            params = res_conn.data
        return name, enabled, schema, params
    except Exception as e:
        print(f"[Erreur chargement SQL reasoning ou schéma] : {e}")
        return "", False, "", {}

def build_system_prompt(description, sql_reasoning_enabled, schema_text):
    prompt = (
        "Tu es un assistant intelligent, clair et naturel. "
        "Tu prends en compte la conversation précédente pour comprendre les questions vagues. "
        f"Tu suis la consigne suivante : {description or 'réponds poliment et avec clarté.'} "
    )
    if sql_reasoning_enabled and schema_text:
        prompt += (
            f"\n\nVoici les informations sur la table PostgreSQL et ses colonnes :\n{schema_text}\n\n"
            "\n\nIMPORTANT :\n"
            "1. Retourne uniquement une requête SQL PostgreSQL valide, exécutable.\n"
            "2. Ne retourne jamais de texte, d'explication ou de balises Markdown (` ```sql ` ou `sql:`).\n"
            "3. La requête doit contenir toutes les clauses nécessaires : SELECT, FROM, GROUP BY, etc.\n"
            "4. Les noms de colonnes et de tables doivent obligatoirement être mis entre guillemets.\n"
            "5. Utilise GROUP BY pour les agrégations si besoin.\n"
            "6. Indique toujours la table utilisée.\n"
            "7. La requête doit être sur une seule ligne.\n"
            "8. Respecte les types et formats.\n"
            "9. Syntaxe PostgreSQL uniquement.\n"
            "10. La fonction AGE() est parfois utile pour les dates."
        )
    else:
        prompt += "\n\nSi tu ne trouves pas la réponse dans les contextes fournis, indique que l'information n'est pas disponible."
    return prompt

# === Fonctions principales ===

def reformulate_answer_via_llm(query, contexte_text):
    messages = [
        {"role": "system", "content": "Tu es un assistant intelligent, clair et naturel."},
        {"role": "user", "content": (
            "Tu es un assistant qui reformule une réponse claire, naturelle et concise pour un utilisateur.\n"
            f"Voici la question posée :\n{query}\n\n"
            f"Voici le contexte complet :\n{contexte_text}\n\n"
            "Formule une réponse naturelle, sans mentionner SQL ni format brut.\n"
        )}
    ]
    return call_llm("mixtral", messages)

def ask_mixtral_for_relevant_sources(chatbot_id: str, question: str):
    sources = []

    for c in get_connexions_for_chatbot(chatbot_id):
        sources.append({
            "type": "connexion",
            "name": c["connexion_name"],
            "description": c["description"]
        })

    for d in get_documents_for_chatbot(chatbot_id):
        sources.append({
            "type": "document",
            "name": d["document_name"],
            "description": d["description"]
        })

    prompt = (
        "Tu es un assistant intelligent chargé de sélectionner les sources les plus pertinentes pour répondre à une question.\n"
        f"Question :\n{question}\n\n"
        "Sources disponibles :\n"
        f"{json.dumps(sources, ensure_ascii=False)}\n\n"
        "Réponds uniquement avec une liste JSON au format :\n"
        "[{\"type\": \"document\" | \"connexion\", \"name\": \"nom_de_la_source\"}, ...]\n"
        "Ne fais aucun commentaire, ne donne aucune explication. Tu dois obligatoirement choisir une ou plusieurs sources."
    )

    messages = [
        {"role": "system", "content": "Tu es un assistant intelligent qui sélectionne les sources pertinentes."},
        {"role": "user", "content": prompt}
    ]

    result = call_llm("mixtral", messages)

    try:
        return json.loads(result)
    except Exception:
        return result

def extract_sources(docs):
    return list({doc.get("source", "inconnu") for doc in docs})

def generate_answer(query, docs, chatbot_id=None, history=None):
    cached = get_cache(query, docs)
    if cached:
        return cached

    description = get_chatbot_description(chatbot_id)
    connexion_name, sql_reasoning_enabled, schema_text, connexion_params = get_connexion_info(chatbot_id)

    history_formatted = ""
    if history:
        for msg in history:
            role = "Utilisateur" if msg.role == "user" else "Assistant"
            history_formatted += f"{role} : {msg.content.strip()}\n"

    system_prompt = build_system_prompt(description, sql_reasoning_enabled, schema_text)
    contexte = build_contexte(docs)

    # 🔍 Log des sources utilisées
    sources_used = extract_sources(docs)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": (
            f"Voici la conversation précédente entre toi et l'user :\n{history_formatted.strip()}\n\n"
            f"Voici le contexte :\n{contexte.strip()}\n\n"
            f"Voici la question :\n{query.strip()}"
        )}
    ]

    try:
        raw_result = call_llm("mixtral", messages, temperature=0, max_tokens=300)
    except Exception as e:
        raw_result = f"Erreur lors de la génération de la réponse : {str(e)}"
        set_cache(query, docs, raw_result)
        return raw_result

    final_answer = raw_result

    if sql_reasoning_enabled:
        extracted_sql = extract_sql_from_text(raw_result)
        if os.environ.get("DEBUG_SQL"):
            print(f"SQL à exécutée: {extracted_sql}")

        if extracted_sql:
            sql_result = execute_sql_via_api(connexion_params, extracted_sql)
            if sql_result:
                docs.insert(0, {
                    "text": (
                        f"Résultat SQL pour la requête suivante : {query}\n"
                        f"Code SQL : {extracted_sql}\n\n"
                        f"Résultat :\n{json.dumps(sql_result, indent=2, ensure_ascii=False)}"
                    ),
                    "source": "résultat_sql"
                })

            final_answer = reformulate_answer_via_llm(query, build_contexte(docs))
        else:
            final_answer = reformulate_answer_via_llm(query, contexte)

    set_cache(query, docs, final_answer)
    return final_answer
