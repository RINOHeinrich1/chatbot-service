import requests
import json
import os
from datetime import datetime
from config import *
from utils.helpers import *
from .cache import *
from .postgres import *
# === Fonctions utilitaires ===
import joblib

# Chargement du modèle et du vectorizer
model = joblib.load("request_classifier_model.pkl")
vectorizer = joblib.load("request_vectorizer.pkl")

def is_question_or_request(text: str) -> bool:
    X = vectorizer.transform([text])
    prediction = model.predict(X)[0]
    return bool(prediction)

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

def build_system_prompt(query,description, sql_reasoning_enabled, schema_text,discu):
    prompt = (
        "Tu es un assistant intelligent, clair et naturel. "
        f"Tu suis la consigne suivante : {description or 'réponds poliment et avec clarté.'} "
    )
    if sql_reasoning_enabled and schema_text:
        prompt += (
            f"\n\nVoici les tables de la base de donnée postgres avec leurs colonnes respectif :\n{schema_text}\n\n"
            f"\nEn te basant sur ces informations sur la base de donnée, donne  un requête SQL pour répondre au question :\"{query}\", en respectant les règles:\n"
            "1. Retourne uniquement une requête SQL PostgreSQL valide, exécutable.\n"
            "2. Ne retourne jamais  d'explication ou de commentaire, de balises Markdown ou des échappements via \. Juste la requête\n"
            "3. La requête doit toujours êtres complètes"
            "4. Les noms de colonnes et de tables dans la requête doivent obligatoirement être mis entre guillemets anglais.\n"
            "5. Indique toujours la table utilisée.\n"
            "6. La requête doit être sur une seule ligne.\n"
        )
      #  print(f"Prompt: {prompt}")

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
            "Répond uniquement au question posée en français, ne donne pas de détails technique ni de la façon dont tu as obtenue la réponse\n"
        )}
    ]
    return call_llm("mixtral", messages)

def ask_mixtral_for_relevant_sources(chatbot_id: str, question: str):
    if not is_question_or_request(question):
        return [{"type": "aucun", "name": "aucun"}]

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

    if not sources:
        return [{"type": "aucun", "name": "aucun"}]

    print(f"Liste des sources:{sources}")

    prompt = (
        "Tu es un assistant intelligent chargé de sélectionner les sources les plus pertinentes pour répondre à une question.\n"
        f"Question :\n{question}\n\n"
        "Sources disponibles :\n"
        f"{json.dumps(sources, ensure_ascii=False)}\n\n"
        "Réponds uniquement par la liste JSON EXACTE au format :\n"
        "[{\"type\": \"document\" ou \"connexion\", \"name\": \"nom_de_la_source\"}, ...]\n"
        "Si la question n'est pas une demande (exemple: salutation, remerciement ou autres), tu ne renvoies :\n"
        "[{\"type\": \"aucun\", \"name\": \"aucun\"}]\n"
        "La liste doit contenir uniquement les sources sélectionnées, sans aucune explication, commentaire, texte supplémentaire ou guillemets inversés.\n"
        "Si aucune source n'est pertinente, retourne une liste vide : []\n"
        "Ne réponds jamais autre chose que cette liste JSON."
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
import re

def corriger_sql_heuristique(sql):
    # Mots-clés SQL à ne jamais mettre entre guillemets
    mots_cles = {
        "SELECT", "FROM", "JOIN", "INNER", "LEFT", "RIGHT", "FULL", "OUTER", "ON",
        "WHERE", "AS", "AND", "OR", "GROUP", "BY", "ORDER", "HAVING", "DESC", "ASC",
        "LIMIT", "OFFSET", "IN", "IS", "NULL", "NOT", "UNION"
    }

    # Fonction pour mettre des guillemets sur identifiants si pas déjà faits
    def quote_identifier(ident):
        ident = ident.strip()
        if ident.upper() in mots_cles or re.match(r'^["\'].*["\']$', ident) or ident.isdigit():
            return ident
        return f'"{ident}"'

    # Corriger les a.b → "a"."b"
    def corriger_dot_expr(match):
        left, right = match.group(1), match.group(2)
        return f'{quote_identifier(left)}.{quote_identifier(right)}'

    # Corriger AS alias
    def corriger_alias(match):
        base, alias = match.group(1), match.group(2)
        return f'{base} AS {quote_identifier(alias)}'

    # Étape 1 : corriger a.b
    sql = re.sub(r'(\w+)\.(\w+)', corriger_dot_expr, sql)

    # Étape 2 : corriger alias sans guillemets
    sql = re.sub(r'AS\s+(\w+)', lambda m: f'AS {quote_identifier(m.group(1))}', sql, flags=re.IGNORECASE)

    # Étape 3 : corriger noms de table/colonne simples dans SELECT ou FROM/JOIN
    def corriger_mots_simples(match):
        mot = match.group(0)
        return quote_identifier(mot)

    # Séparer les blocs SELECT ... FROM ...
    pattern_select_from = re.search(r'SELECT\s+(.*?)\s+FROM\s+', sql, flags=re.IGNORECASE | re.DOTALL)
    if pattern_select_from:
        select_block = pattern_select_from.group(1)
        corrected = []

        for part in select_block.split(','):
            part = part.strip()
            if "AS" not in part.upper() and "." not in part:
                part = quote_identifier(part)
            corrected.append(part)
        sql = sql.replace(select_block, ', '.join(corrected))

    # Corriger noms simples après FROM ou JOIN
    sql = re.sub(r'\b(FROM|JOIN)\s+(\w+)', lambda m: f'{m.group(1)} {quote_identifier(m.group(2))}', sql, flags=re.IGNORECASE)

    return sql

def extract_sources(docs):
    return list({doc.get("source", "inconnu") for doc in docs})

def generate_answer(query, docs, chatbot_id=None, max_retries=3):
    cached = get_cache(query, docs)
    if cached:
        return {
            "answer": cached,
            "sql": None,
            "sources": extract_sources(docs),
        }

    description = get_chatbot_description(chatbot_id)
    connexion_name, sql_reasoning_enabled, schema_text, connexion_params = get_connexion_info(chatbot_id)

    system_prompt = build_system_prompt(query, description, (sql_reasoning_enabled and len(docs)>0), schema_text, "")
    contexte = build_contexte(docs)

    sources_used = extract_sources(docs)
    extracted_sql = None

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": (
            f"Voici le contexte :\n{contexte.strip()}\n\n"
            f"Voici la question :\n{query.strip()}"
        )}
    ]

    try:
        raw_result = call_llm("mixtral", messages, temperature=0, max_tokens=300)
        print("🔧 Contenu brut du LLM:\n", raw_result)
    except Exception as e:
        raw_result = f"Erreur lors de la génération de la réponse : {str(e)}"
        set_cache(query, docs, raw_result)
        return {
            "answer": raw_result,
            "sql": None,
            "sources": sources_used,
        }

    final_answer = raw_result
    if sql_reasoning_enabled and len(docs)>0:
        retry_count = 0
        tried_heuristic = False  # Pour ne corriger heuristiquement qu'une fois

        while retry_count <= max_retries:
            extracted_sql = extract_sql_from_text(raw_result)
            if extracted_sql is None:
                print("Aucune requête SQL extraite.")
                break

            if os.environ.get("DEBUG_SQL"):
                print(f"SQL à exécuter (essai #{retry_count + 1}): {extracted_sql}")

            try:
                # 1ère tentative ou tentative après LLM/heuristique
                sql_result = execute_sql_via_api(connexion_params, extracted_sql)
                if sql_result is not None:
                    print(f"Résultat SQL: {sql_result}")
                    docs.insert(0, {
                        "text": (
                            f"Résultat SQL pour la requête suivante : {query}\n"
                            f"Code SQL : {extracted_sql}\n\n"
                            f"Résultat :\n{json.dumps(sql_result, indent=2, ensure_ascii=False)}"
                        ),
                        "source": "résultat_sql"
                    })
                    final_answer = reformulate_answer_via_llm(query, build_contexte(docs))
                    break  # Succès
                else:
                    raise Exception("Résultat SQL vide ou invalide")

            except Exception as e:
                print(f"Erreur exécution SQL: {e}")

                # Tentative avec correcteur heuristique
                if not tried_heuristic:
                    print("⛑️ Tentative de correction heuristique...")
                    extracted_sql = corriger_sql_heuristique(extracted_sql)
                    tried_heuristic = True
                    continue  # Réessayer avec la requête corrigée
                 
                if retry_count == max_retries:
                    final_answer = f"Erreur lors de l'exécution de la requête SQL : {e}\nRequête SQL : {extracted_sql}"
                    break

                # Appel LLM comme dernier recours
                correction_prompt = [
                    {"role": "system", "content": "Tu es un assistant SQL expert qui corrige les requêtes SQL erronées."},
                    {"role": "user", "content": (
                        f"La requête SQL suivante a provoqué une erreur lors de son exécution :\n{extracted_sql}\n"
                        f"Erreur : {e}\n"
                        "Merci de corriger cette requête SQL pour qu'elle soit valide et exécutable en PostgreSQL.\n"
                        "Retourne uniquement la requête SQL corrigée, sans explications."
                    )}
                ]
                raw_result = call_llm("mixtral", correction_prompt, temperature=0, max_tokens=200)
                retry_count += 1
        else:
            # Si on sort de la boucle sans break (pas de requête SQL correcte)
            final_answer = reformulate_answer_via_llm(query, contexte)

    set_cache(query, docs, final_answer)

    return {
        "answer": final_answer,
        "sql": extracted_sql,
        "sources": sources_used,
    }
