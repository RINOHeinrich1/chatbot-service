import requests
import json
import os
from datetime import datetime
from config import *
from utils.helpers import *
from .cache import *
from .postgres import *
import re
from typing import List, Dict, Any
import psycopg2

# === Fonctions utilitaires ===
import joblib

# Chargement du modèle et du vectorizer
model = joblib.load("request_classifier_model.pkl")
vectorizer = joblib.load("request_vectorizer.pkl")


# --- execution sql ---
def execute_sql(query_sql):
    """Exécute une requête SQL brute sur PostgreSQL et renvoie le résultat."""
    try:
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT,
        )
        cur = conn.cursor()
        cur.execute(query_sql)
        rows = cur.fetchall()
        colnames = [desc[0] for desc in cur.description]
        cur.close()
        conn.close()
        return [dict(zip(colnames, row)) for row in rows]
    except Exception as e:
        return {"error": str(e), "sql": query_sql}


def get_existing_categories(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT nom FROM categories")
        rows = cur.fetchall()
        return [r[0] for r in rows]


def detect_category_from_existing(query, conn):
    categories = get_existing_categories(conn)
    categories_text = ", ".join(categories)

    system_prompt = (
        "Tu es un expert en droit français et en classification juridique. "
        f"Analyse la question et indique la catégorie la plus pertinente parmi celles existantes dans la base de données : {categories_text}\n"
        "Retourne uniquement le nom de la catégorie, exactement comme dans la liste."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": query},
    ]

    category = call_llm("mixtral", messages, temperature=0, max_tokens=20)
    category = category.strip()

    # Vérification : si Mixtral a répondu une catégorie qui n’existe pas, on prend "Délits" par défaut
    if category not in categories:
        category = "Délits"
    return category


def strip_html_tags(text):
    return re.sub(r"<[^>]*>", "", text)


def extract_keywords(query):
    words = re.findall(r"\w+", query.lower())
    stopwords = {
        "quelle",
        "est",
        "la",
        "le",
        "les",
        "pour",
        "à",
        "de",
        "des",
        "du",
        "en",
        "un",
        "une",
    }
    keywords = [w for w in words if w not in stopwords]
    return keywords


# --- recherche hybride articles (numéro + contenu) ---
def search_articles_hybride(query_keywords, conn):
    query_text = (
        query_keywords if isinstance(query_keywords, str) else " ".join(query_keywords)
    )
    with conn.cursor() as cur:
        # d'abord par numéro si la question contient "Article XXX"
        numero_match = re.findall(r"Article\s*(\d+[-\d]*)", query_text, re.IGNORECASE)
        results = []
        if numero_match:
            for num in numero_match:
                cur.execute(
                    "SELECT numero_article, contenu FROM articles WHERE numero_article = %s",
                    (num,),
                )
                row = cur.fetchone()
                if row:
                    results.append({"numero_article": row[0], "contenu": row[1]})

        # recherche par contenu si aucun résultat
        if not results:
            keywords = re.findall(r"\w+", query_text.lower())
            ts_query = " & ".join(keywords)
            cur.execute(
                "SELECT numero_article, contenu FROM articles WHERE to_tsvector('french', contenu) @@ to_tsquery('french', %s)",
                (ts_query,),
            )
            for r in cur.fetchall():
                results.append({"numero_article": r[0], "contenu": r[1]})
    return results


# --- génération réponse finale avec surlignage ---
# def generate_answer_with_slots(query: str, conn):
#     # 1️⃣ Extraction du slot générique
#     expected_slots = [{"sujet_principal": "text"}]
#     slots = extract_slots_with_llm(query, expected_slots, {})
#     sujet = slots.get("sujet_principal") or query

#     # 2️⃣ Recherche hybride d'articles (numéro ou contenu)
#     articles = search_articles_hybride(sujet, conn)
#     if not articles:
#         return "Aucun article trouvé pour cette demande."

#     # 3️⃣ Préparer le texte à envoyer au LLM pour filtrage précis
#     articles_text = [
#         {"numero": art["numero_article"], "contenu": art["contenu"]} for art in articles
#     ]

#     system_prompt = {
#         "role": "system",
#         "content": (
#             "Tu es un assistant intelligent."
#             f"La demande: {query}."
#             f"Évalue la pertinence des articles suivants par rapport à la demande"
#             "Ne conserve que ceux qui correspondent très précisément (+95%) au demande. "
#             "Enlever les parties ou les phrases qui ne corresponds pas au demande."
#             "Garde seulement les parties tres important."
#             "Retourne uniquement un JSON sous la forme : [{'numero': ..., 'contenu': ...}, ...]."
#         ),
#     }

#     user_prompt = {
#         "role": "user",
#         "content": f"Question : {sujet}\nArticles : {articles_text}",
#     }

#     filtered_response = call_llm("mixtral", [system_prompt, user_prompt])

#     try:
#         filtered_articles = json.loads(filtered_response)
#     except Exception:
#         # fallback : si le LLM échoue, on garde tous les articles
#         filtered_articles = articles_text

#     # 4️⃣ Génération de la réponse finale avec surlignage
#     response_parts = []
#     for art in filtered_articles:
#         contenu_highlight = re.sub(
#             rf"({re.escape(sujet)})",
#             r'<mark style="background: #FFB8EBA6;">\1</mark>',
#             art["contenu"],
#             flags=re.IGNORECASE,
#         )
#         response_parts.append(f"**Article {art['numero']}** : {contenu_highlight}")

#     return "\n\n".join(response_parts)
# services/mixtral.py
from .articles_service import search_articles
import re
import json

def generate_answer_with_slots(query: str, conn=None):
    """
    Utilise la recherche d'articles pour générer la réponse finale.
    """
    articles = search_articles(query)  # ← ici on appelle le service articles

    if not articles:
        return "Aucun article trouvé pour cette demande."

    articles_text = [{"numero": art["numero_article"], "contenu": art["contenu"]} for art in articles]

    system_prompt = {
        "role": "system",
        "content": (
            "Tu es un assistant intelligent."
            f"La demande: {query}."
            "Évalue la pertinence des articles suivants et retourne uniquement ceux qui sont pertinents."
            "Ne conserve que les parties importantes et retourne un JSON [{'numero':..., 'contenu':...}, ...]."
        )
    }
    user_prompt = {"role": "user", "content": f"Articles : {articles_text}"}

    filtered_response = call_llm("mixtral", [system_prompt, user_prompt])

    try:
        filtered_articles = json.loads(filtered_response)
    except Exception:
        filtered_articles = articles_text

    response_parts = []
    for art in filtered_articles:
        contenu_highlight = re.sub(
            rf"({re.escape(query)})",
            r'<mark style="background: #FFB8EBA6;">\1</mark>',
            art["contenu"],
            flags=re.IGNORECASE
        )
        response_parts.append(f"**Article {art['numero']}** : {contenu_highlight}")

    return "\n\n".join(response_parts)


def ask_mixtral_categorize(user_message: str):
    """
    Retourne (categorie_id, categorie_nom)
    1️⃣ Cherche un mot clé dans la DB
    2️⃣ Sinon fallback sur LLM Mixtral
    """
    default_id = 6
    default_name = "Délit"

    conn = None
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
        )
        with conn.cursor() as cur:
            cur.execute("SELECT id, nom FROM categories")
            categories = cur.fetchall()  # [(id, nom), ...]

            message_lower = user_message.lower()
            for cat_id, cat_nom in categories:
                mots = cat_nom.lower().split()
                if any(mot in message_lower for mot in mots):
                    return cat_id, cat_nom  # trouvé dans DB

            # Fallback Mixtral
            categories_dict = {cat_id: cat_nom for cat_id, cat_nom in categories}
            json_example = json.dumps({"categorie": 1}, ensure_ascii=False, indent=2)

            system_prompt = {
                "role": "system",
                "content": (
                    "Tu es un classificateur juridique intelligent.\n"
                    "Analyse le message et retourne UNIQUEMENT un JSON valide contenant le numéro de catégorie.\n\n"
                    "Catégories disponibles :\n"
                    + "\n".join([f"{k}: {v}" for k, v in categories_dict.items()])
                    + f"\n\nFormat attendu :\n{json_example}"
                ),
            }
            user_prompt = {"role": "user", "content": f'Message: "{user_message}"'}

            response = call_llm(
                "mixtral", [system_prompt, user_prompt], temperature=0.1, max_tokens=20
            )

            try:
                extracted = json.loads(response)
                llm_category = extracted.get("categorie")
                if isinstance(llm_category, int) and llm_category in categories_dict:
                    return llm_category, categories_dict[llm_category]
            except Exception:
                pass

    except Exception as e:
        print(f"⚠️ Erreur connexion ou LLM : {e}")
    finally:
        if conn:
            conn.close()

    return default_id, default_name


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
        res = (
            supabase.table("chatbots")
            .select("description")
            .eq("id", chatbot_id)
            .single()
            .execute()
        )
        return res.data.get("description", "").strip()
    except Exception:
        return ""


def get_connexion_info(chatbot_id):
    try:
        res = (
            supabase.table("chatbot_pgsql_connexions")
            .select("connexion_name, sql_reasoning")
            .eq("chatbot_id", chatbot_id)
            .single()
            .execute()
        )
        name = res.data["connexion_name"]
        enabled = res.data.get("sql_reasoning", False)

        schema, params = "", {}
        if enabled:
            res_conn = (
                supabase.table("postgresql_connexions")
                .select(
                    "data_schema, host_name, port, user, password, database, ssl_mode"
                )
                .eq("connexion_name", name)
                .single()
                .execute()
            )
            schema = res_conn.data.get("data_schema", "").strip()
            params = res_conn.data
        return name, enabled, schema, params
    except Exception as e:
        print(f"[Erreur chargement SQL reasoning ou schéma] : {e}")
        return "", False, "", {}

from difflib import SequenceMatcher
import unicodedata
import re
import json

# Charger ou créer la liste de mots-clés juridiques
KEYWORDS_FILE = "juridical_keywords.json"

if os.path.exists(KEYWORDS_FILE):
    with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
        juridical_keywords = json.load(f)
else:
    juridical_keywords = [
        "article", "loi", "code", "juridique", "legal", "avocat", "procedure",
        "tribunal", "justice", "droit",
        "code civil", "code penal", "code du travail", "code de commerce",
        "code de procedure", "code de la consommation",
        "mariage", "divorce", "succession", "heritage", "contrat", "famille",
        "vol", "vol a main arme", "crime", "delit", "infraction", "agression", "braquage"
    ]

def save_keywords():
    with open(KEYWORDS_FILE, "w", encoding="utf-8") as f:
        json.dump(juridical_keywords, f, ensure_ascii=False, indent=2)

def normalize_text(text: str) -> str:
    """Met en minuscules, supprime accents et ponctuation."""
    text = text.lower()
    text = "".join(
        c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn"
    )
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def fuzzy_match(text, keywords, cutoff=0.8):
    """Retourne True si au moins un mot-clé correspond de façon floue."""
    for kw in keywords:
        ratio = SequenceMatcher(None, text, kw).ratio()
        if ratio >= cutoff:
            return True
    return False

def extract_keywords_from_llm(query):
    """Demander au LLM de fournir les mots-clés juridiques de la question."""
    messages = [
        {
            "role": "system",
            "content": "Tu es un assistant qui extrait les mots ou expressions principales liées au droit dans une question.",
        },
        {
            "role": "user",
            "content": f"Question: {query}\nListe uniquement les mots-clés juridiques séparés par une virgule, sans autre texte.",
        },
    ]
    result = call_llm("mixtral", messages, temperature=0, max_tokens=50)
    keywords = [normalize_text(k.strip()) for k in result.split(",") if k.strip()]
    return keywords


def classify_juridical(query: str) -> str:
    """
    Retourne 'oui' si la question est juridique, 'non' sinon.
    Utilise d'abord mots-clés locaux puis LLM strict si nécessaire.
    """
    q_norm = normalize_text(query)

    # 1️⃣ Vérification mots-clés locaux (y compris multi-mots)
    for kw in juridical_keywords:
        kw_norm = normalize_text(kw)
        if kw_norm in q_norm:
            return "oui"

    # 2️⃣ Vérification via LLM strict
    messages = [
        {
            "role": "system",
            "content": (
                "Tu es un classificateur juridique très strict. "
                "Analyse la question et décide si elle est juridique ou non. "
                "⚠️ Répond uniquement par 'oui' ou 'non'. "
                "Ne jamais ajouter d'explications, de contexte ou de mots supplémentaires. "
                "Réponds 'oui' seulement si la question relève du droit (articles de loi, infractions, notions juridiques, procédure, tribunal, avocat…). "
                "Sinon répond 'non'."
            ),
        },
        {"role": "user", "content": query},
    ]

    result = call_llm("mixtral", messages, temperature=0, max_tokens=1).strip().lower()

    # 3️⃣ Enrichir la liste de mots-clés automatiquement si LLM confirme
    if result == "oui":
        new_keywords = extract_keywords_from_llm(query)
        for kw in new_keywords:
            if kw not in juridical_keywords:
                juridical_keywords.append(kw)
        save_keywords()

    return result

def classify_domain(query, chatbot_description=""):
    """
    Vérifie si la question est pertinente pour le domaine du chatbot.
    Renvoie 'oui' si elle est dans le domaine, 'non' sinon.
    """
    q_normalized = normalize_text(query)
    description_normalized = normalize_text(chatbot_description)

    # 🔹 Vérification rapide par mots-clés du domaine
    if fuzzy_match(q_normalized, description_normalized.split()):
        return "oui"

    # 🔹 Sinon, vérification via LLM
    messages = [
        {
            "role": "system",
            "content": (
                "Tu es un classificateur spécialisé. "
                f"Analyse la question de l'utilisateur et décide si elle est pertinente pour le domaine : {chatbot_description}. "
                "Réponds uniquement par 'oui' si c'est pertinent, ou 'non' sinon."
            ),
        },
        {"role": "user", "content": query},
    ]
    result = call_llm("mixtral", messages, temperature=0, max_tokens=1).strip().lower()
    return result

def build_system_prompt(query, description, sql_reasoning_enabled, schema_text, discu):
    """
    Génère un prompt clair et strict pour l'assistant.

    - Répond aux questions dans le domaine décrit par `description`.
    - Pour les salutations, répond simplement et poliment.
    - Pour les questions hors domaine, répond uniquement qu'il n'est pas possible de répondre.
    - Si SQL activé, génère uniquement la requête SQL.
    """

    if description:
        prompt = (
            "Tu es un assistant intelligent, clair et très poli.\n"
            "Faire en text gras les informations et les mots necessaires a bien connaitre"
            f"Ton domaine est : {description}.\n\n"
            f"La demande ou le question est : {query}.\n\n"
            "Instructions strictes :\n"
            "1. Si la question est dans ton domaine, répond normalement.\n"
            "2. Si c'est une salutation (ex: 'Bonjour', 'Salut'), répond simplement et poliment.\n"
            f"3. Si la question est hors domaine, répond uniquement comme je suis un assistant spécialisé dans {description}"
            "4. Ne fournis jamais d'informations hors domaine.\n"
            "5. Pas de conseils ni d'explications supplémentaires. c'est un ordre même repeter"
        )
    else:
        prompt = "Réponds seulement 'Désolé, je ne peux pas répondre à cette question.'"

    if sql_reasoning_enabled and schema_text:
        prompt += (
            f"\n\nVoici les tables de la base de données Postgres avec leurs colonnes :\n{schema_text}\n\n"
            f'En te basant uniquement sur ces informations, génère une requête SQL pour répondre à la demande : "{query}".\n'
            "Règles strictes pour la requête SQL :\n"
            "1. Retourne uniquement une requête SQL PostgreSQL valide et exécutable.\n"
            "2. Pas d'explications, pas de commentaires, pas de balises Markdown.\n"
            "3. La requête doit être complète et sur une seule ligne.\n"
            "4. Tous les noms de colonnes et tables doivent être entre guillemets.\n"
            "5. Indique toujours la table utilisée."
        )
    else:
        prompt += "\n\nSi tu ne peux pas répondre car la question est hors contexte, indique uniquement poliment que l'information n'est pas disponible."

    return prompt


# === Fonctions principales ===
def reformulate_answer_via_llm(query, contexte_text):
    messages = [
        {
            "role": "system",
            "content": (
                "Tu es un assistant intelligent, clair et naturel. "
                "Tu t'exprimes uniquement en français."
            ),
        },
        {
            "role": "user",
            "content": (
                "Ta mission est de reformuler une réponse claire, naturelle et concise pour l'utilisateur.\n\n"
                f"Demande reçue :\n{query}\n\n"
                f"Contexte disponible :\n{contexte_text}\n\n"
                "Règles importantes :\n"
                "1. Si le contexte est une liste de slots et que certaines valeurs sont nulles, pose des questions pour demander ces valeurs manquantes.\n"
                "2. Si le contexte contient des références légales (articles, codes, etc.), ajoute-les et rends-les visibles en **gras**.\n"
                "3. Mets aussi en **gras** les mots, informations ou données essentielles de la réponse.\n"
                "Autre cas: Si le contexte est un refus de réponse, réponds uniquement par une phrase claire, polie et courte, sans explication. Ne donne jamais de détails techniques ni sur la façon dont la réponse a été produite.\n"
            ),
        },
    ]
    return call_llm("mixtral", messages, temperature=0.3, max_tokens=300)

# === Fonctions principales ===
def reformulate_juridical_answer(query, contexte_text):
    """
    Reformule une réponse juridique claire, naturelle et concise,
    en respectant le format suivant pour tout article légal :

    ✅ Article [numéro] : [titre ou sujet]

    [Description claire et concise de l'article, expliquant ce qu'il prévoit et à qui il s'applique.]

    Les peines sont les suivantes :
    - [Peine 1]
    - [Peine 2, si applicable]
    - [Autres peines, si applicable]

    Toutes les informations importantes ou références légales doivent être en **gras**.
    """
    messages = [
        {
            "role": "system",
            "content": (
                "Tu es un assistant juridique expert, clair et concis. "
                "Tu t'exprimes uniquement en français."
            ),
        },
        {
            "role": "user",
            "content": (
                "Ta mission : reformuler une réponse juridique claire, naturelle et concise pour l'utilisateur.\n\n"
                f"Demande reçue :\n{query}\n\n"
                f"Contexte disponible :\n{contexte_text}\n\n"
                "Règles importantes :\n"
                "1. Utilise strictement le format suivant pour tout article légal :\n"
                "   ✅ Article [numéro] : [titre ou sujet]\n"
                "   [Description claire et concise]\n"
                "   Les peines sont les suivantes :\n"
                "   - [Peine 1]\n"
                "   - [Peine 2, si applicable]\n"
                "2. Mets en **gras** toutes les informations importantes et références légales.\n"
                "3. Ne rajoute aucun texte inutile et ne mentionne jamais de détails techniques sur la génération de la réponse."
            ),
        },
    ]

    return call_llm(
        model="mixtral",
        messages=messages,
        temperature=0.3,
        max_tokens=500
    )


def ask_mixtral_for_relevant_sources(chatbot_id: str, question: str):
    sources = []
    if is_question_or_request(question):
        for c in get_connexions_for_chatbot(chatbot_id):
            sources.append(
                {
                    "type": "connexion",
                    "name": c["connexion_name"],
                    "description": c["description"],
                }
            )

        for d in get_documents_for_chatbot(chatbot_id):
            sources.append(
                {
                    "type": "document",
                    "name": d["document_name"],
                    "description": d["description"],
                }
            )

    for s in get_slots_for_chatbot(chatbot_id):
        sources.append(
            {"type": "slot", "name": s["slot_name"], "description": s["description"]}
        )

    if not sources:
        return []

    prompt = (
        "Tu es un assistant intelligent chargé de sélectionner les sources les plus pertinentes pour répondre à une demande.\n"
        f"Demande :\n{question}\n\n"
        "Voici la liste des sources disponibles :\n"
        f"{json.dumps(sources, ensure_ascii=False, indent=2)}\n\n"
        'Réponds uniquement par la liste JSON EXACTE des noms des sources sélectionnées (exemple : ["Rendez-vous-vole", "Doc A"]).\n'
        "Ne réponds jamais autre chose que cette liste JSON."
    )

    result = call_llm(
        "mixtral",
        [
            {
                "role": "system",
                "content": "Tu es un assistant intelligent qui sélectionne les sources pertinentes.",
            },
            {"role": "user", "content": prompt},
        ],
    )

    print(f"Réponse brute du LLM : {result}")

    try:
        cleaned_result = re.sub(r'\\([^\\"/bfnrtu])', r"\1", result)
        selected_names = json.loads(cleaned_result)
        if isinstance(selected_names, list) and all(
            isinstance(n, str) for n in selected_names
        ):
            # Filtrer les sources en fonction des noms renvoyés par le LLM
            selected_sources = [s for s in sources if s["name"] in selected_names]
            return selected_sources
        else:
            print("⚠️ Format inattendu : attendu liste de noms (strings).")
            return []
    except Exception as e:
        print(f"Erreur parsing JSON LLM: {e}")
        return []


# --- slot extraction existant ---
def extract_slots_with_llm(
    user_input: str, expected_slots: List[Dict[str, str]], slot_state: Dict[str, Any]
):
    slot_state = slot_state or {}

    if not expected_slots or not isinstance(expected_slots[0], dict):
        print("⚠️ Structure inattendue pour expected_slots :", expected_slots)
        return {}

    full_slot_schema = expected_slots[0]  # ex: {'Nom': 'text', 'Date': 'date', ...}

    missing_slots = {
        slot: full_slot_schema[slot]
        for slot in full_slot_schema
        if not slot_state.get(slot)
    }
    if not missing_slots:
        return slot_state

    slots_template = {k: None for k in missing_slots}
    json_example = json.dumps(slots_template, ensure_ascii=False, indent=2)

    system_prompt = {
        "role": "system",
        "content": (
            f"Tu es un assistant intelligent. Extrait les informations suivantes si elles sont présentes dans la phrase : {', '.join(missing_slots.keys())}.\n"
            f"Retourne uniquement un JSON valide au format suivant :\n{json_example}\n"
            "Si une valeur n’est pas présente, utilise null."
        ),
    }
    user_prompt = {"role": "user", "content": user_input}
    response = call_llm("mixtral", [system_prompt, user_prompt])

    try:
        extracted = json.loads(response)
    except Exception:
        cleaned = response.replace("\\_", "_").replace("\\n", "").strip("`")
        try:
            extracted = json.loads(cleaned)
        except Exception:
            print("⚠️ LLM n'a pas retourné un JSON valide :", response)
            return slot_state

    final_slots = {}
    for slot in full_slot_schema:
        if slot_state.get(slot) is not None:
            final_slots[slot] = slot_state[slot]
        elif extracted.get(slot) is not None:
            final_slots[slot] = extracted[slot]
        else:
            final_slots[slot] = None

    return final_slots


def corriger_sql_heuristique(sql):
    # Mots-clés SQL à ne jamais mettre entre guillemets
    mots_cles = {
        "SELECT",
        "FROM",
        "JOIN",
        "INNER",
        "LEFT",
        "RIGHT",
        "FULL",
        "OUTER",
        "ON",
        "WHERE",
        "AS",
        "AND",
        "OR",
        "GROUP",
        "BY",
        "ORDER",
        "HAVING",
        "DESC",
        "ASC",
        "LIMIT",
        "OFFSET",
        "IN",
        "IS",
        "NULL",
        "NOT",
        "UNION",
        "*",
    }

    # Fonction pour mettre des guillemets sur identifiants si pas déjà faits
    def quote_identifier(ident):
        ident = ident.strip()
        if (
            ident.upper() in mots_cles
            or re.match(r'^["\'].*["\']$', ident)
            or ident.isdigit()
        ):
            return ident
        return f'"{ident}"'

    # Corriger les a.b → "a"."b"
    def corriger_dot_expr(match):
        left, right = match.group(1), match.group(2)
        return f"{quote_identifier(left)}.{quote_identifier(right)}"

    # Corriger AS alias
    def corriger_alias(match):
        base, alias = match.group(1), match.group(2)
        return f"{base} AS {quote_identifier(alias)}"

    # Étape 1 : corriger a.b
    sql = re.sub(r"(\w+)\.(\w+)", corriger_dot_expr, sql)

    # Étape 2 : corriger alias sans guillemets
    sql = re.sub(
        r"AS\s+(\w+)",
        lambda m: f"AS {quote_identifier(m.group(1))}",
        sql,
        flags=re.IGNORECASE,
    )

    # Étape 3 : corriger noms de table/colonne simples dans SELECT ou FROM/JOIN
    def corriger_mots_simples(match):
        mot = match.group(0)
        return quote_identifier(mot)

    # Séparer les blocs SELECT ... FROM ...
    pattern_select_from = re.search(
        r"SELECT\s+(.*?)\s+FROM\s+", sql, flags=re.IGNORECASE | re.DOTALL
    )
    if pattern_select_from:
        select_block = pattern_select_from.group(1)
        corrected = []

        for part in select_block.split(","):
            part = part.strip()
            if "AS" not in part.upper() and "." not in part:
                part = quote_identifier(part)
            corrected.append(part)
        sql = sql.replace(select_block, ", ".join(corrected))

    # Corriger noms simples après FROM ou JOIN
    sql = re.sub(
        r"\b(FROM|JOIN)\s+(\w+)",
        lambda m: f"{m.group(1)} {quote_identifier(m.group(2))}",
        sql,
        flags=re.IGNORECASE,
    )

    return sql


def extract_sources(docs):
    return list({doc.get("source", "inconnu") for doc in docs})


def extract_keywords_with_llm(query: str) -> str:
    """
    Utilise ton LLM pour transformer une question en mots-clés utiles pour la recherche.
    Exemple:
        "Quels sont les articles concernant le vol à main armée ?"
        -> "vol main armée"
    """
    expected_slots = [{"mots_cles": "text"}]

    slots = extract_slots_with_llm(query, expected_slots, {})
    mots_cles = slots.get("mots_cles")

    if not mots_cles:
        mots_cles = query  # fallback si extraction vide
    return mots_cles

def generate_answer(query, docs, chatbot_id=None, max_retries=3):
    logs = []
    cached = get_cache(query, docs)
    if cached:
        logs.append("Utilisation du cache")
        return {
            "answer": cached,
            "logs": logs,
        }

    # Étape 2 : Vérification domaine chatbot
    description = get_chatbot_description(chatbot_id)
    domain_flag = classify_domain(query, description)
    logs.append(f"Classification Mixtral (domaine): {domain_flag}")

    is_query_is_description_message = [
        {
            "role": "system",
            "content": (
                f"Tu es un classificateur spécialisé dans l'analyse des textes. "
                "Reponds toujours en francais"
                f"Ton rôle est de déterminer si une question appartient dans le monde {description} ou non"
                f"Analyse le sens profond de la demande, même si les mots exacts ne sont pas utilisés. "
                f"La demande est: {query}"
                f"Réponds uniquement en miniscule par : 'oui' si la question est dans le monde de {description}, ou 'non' si la question n'est pas dans le monde de {description}, ou 'greet' si la question est dans le monde de conversation generale greeting comme bonjour, ca va, comme ca, non pas une conversation avec un autre sujet ou autre domaine"
                "⚠️ N’écris même point même virgule, rien d’autre que 'oui' ou 'non'"
            ),
        },
        {"role": "user", "content": query},
    ]

    is_query_is_description = call_llm(
        "mixtral", is_query_is_description_message, temperature=0, max_tokens=1
    )
    is_query_is_description_stripe = is_query_is_description

    print(f"======= DOMAINE DESCRIPTION: {is_query_is_description_stripe}")

    # 🚫 Cas hors sujet
    if is_query_is_description_stripe.lower() == "non":
        answer_default = (
            "Cette question ne correspond pas au domaine de ce chatbot. "
            f"Je ne peux pas y répondre car je suis dans le domaine de {description}."
        )

        final_answer = reformulate_answer_via_llm("Pas besoin", answer_default)
        logs.append("Question hors sujet → pas de réponse.")

        return {
            "answer": final_answer,
            "logs": logs,
        }

    elif is_query_is_description_stripe.lower() == "greet":
        answer_default = (
            "Cette question est dans la conversation generale. "
            f"Je peux vous répondre dans le domaine de {description}."
        )

        final_answer = reformulate_answer_via_llm("Pas besoin", answer_default)
        logs.append("Question greeting")

        return {
            "answer": final_answer,
            "logs": logs,
        }

    else:
        # ✅ Cas juridique

        # Étape 1 : Vérification juridique
        juridical_flag = classify_juridical(query)
        logs.append(f"Classification Mixtral (juridique): {juridical_flag}")

        if juridical_flag.lower() == "oui":
            print("⚖️ Question juridique détectée → demande des articles à Mixtral")
            # --- 1️⃣ Demande à Mixtral les articles pertinents ---
            system_prompt = (
                "Tu es un assistant juridique expert en droit français. "
                "Réponds uniquement en français. "
                "Pour toute question juridique, retourne UNIQUEMENT la liste des NUMÉROS D'ARTICLE exacts du Code pénal français, "
                "sans commentaire, sans explication, sans texte supplémentaire. "
                "Si plusieurs articles s'appliquent, liste-les tous, séparés par une virgule. "
                "Si aucun article ne correspond, retourne exactement : None. "
                "Ne fais aucune interprétation, ne reformule pas la question, ne donne pas d'exemple. "
                "Exemple de réponse : Article 311-8, Article 311-9. "
            )

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query},
            ]
            raw_article_numbers = call_llm(
                "mixtral", messages, temperature=0, max_tokens=100
            ).strip()
            print(f"📝 Mixtral a retourné: {raw_article_numbers}")

            # --- 2️⃣ Parsing ---
            article_numbers = [
                a.strip()
                for a in re.split(r",|\n", raw_article_numbers)
                if a.strip() and a.strip().lower() != "none"
            ]

            articles_found = []
            if article_numbers:
                conn = psycopg2.connect(
                    host=DB_HOST,
                    port=DB_PORT,
                    dbname=DB_NAME,
                    user=DB_USER,
                    password=DB_PASSWORD,
                )
                with conn.cursor() as cur:
                    for num_article in article_numbers:
                        cur.execute(
                            """
                            SELECT numero_article, contenu
                            FROM articles
                            WHERE numero_article = %s
                            """,
                            (num_article,),
                        )
                        row = cur.fetchone()
                        if row:
                            articles_found.append(
                                {"numero_article": row[0], "contenu": row[1]}
                            )
                conn.close()

            ## --- 3️⃣ Formulation finale ---
            # if articles_found:
            #     final_answer = reformulate_answer_via_llm(query, articles_found)

            # else:
            #     system_prompt = (
            #         "Tu es un assistant juridique expert. "
            #         "Mixtral a suggéré des articles mais aucun n'a été trouvé dans la base. "
            #         "Formule une réponse polie et claire en français pour expliquer à l'utilisateur "
            #     )
            #     messages = [
            #         {"role": "system", "content": system_prompt},
            #         {"role": "user", "content": query},
            #     ]
            #     final_answer = call_llm(
            #         "mixtral", messages, temperature=0.3, max_tokens=100
            #     )
            # --- Dans ton flux principal ---
            if articles_found:
                final_answer = reformulate_juridical_answer(query, articles_found)

            else:
                # 1️⃣ Extraction LLM des mots-clés
                keywords = extract_keywords_with_llm(query)
                print(f"🔎 Mots-clés extraits: {keywords}")

                # 2️⃣ Recherche dans ton web action
                try:
                    resp = requests.get(WEB_ACTION_URL, params={"q": keywords})
                    resp.raise_for_status()
                    api_results = resp.json()
                except Exception as e:
                    print(f"⚠️ Erreur appel web action: {e}")
                    api_results = []

                if api_results:
                    print("📚 Résultats récupérés depuis le web action :", api_results)
                    final_answer = reformulate_juridical_answer(query, api_results)
                else:
                    # 3️⃣ Sinon réponse polie via LLM
                    system_prompt = (
                        "Tu es un assistant juridique expert. "
                        "Mixtral a suggéré des articles mais aucun n'a été trouvé dans la base. "
                        "Formule une réponse polie et claire en français pour expliquer à l'utilisateur."
                    )
                    messages = [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": query},
                    ]
                    final_answer = call_llm(
                        "mixtral", messages, temperature=0.3, max_tokens=100
                    )

            print(f"✅ Réponse finale : {final_answer}")

        else:
            print("⚖️ Question non juridique détectée")
            connexion_name, sql_reasoning_enabled, schema_text, connexion_params = (
                get_connexion_info(chatbot_id)
            )
            system_prompt = build_system_prompt(
                query,
                description,
                (sql_reasoning_enabled and len(docs) > 0),
                schema_text,
                "",
            )
            contexte = build_contexte(docs)
            sources_used = extract_sources(docs)

            messages = [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"Voici le contexte :\n{contexte.strip()}\n\n"
                        f"Voici la demande :\n{query.strip()}"
                    ),
                },
            ]

            try:
                logs.append(f"Requête envoyés:{messages}")
                raw_result = call_llm(
                    "mixtral", messages, temperature=0, max_tokens=300
                )
                logs.append(f"🔧 Résulat brut du LLM:{raw_result}")
            except Exception as e:
                raw_result = f"Erreur lors de la génération de la réponse : {str(e)}"
                set_cache(query, docs, raw_result)
                return {"answer": raw_result, "logs": logs}

            final_answer = raw_result
            if sql_reasoning_enabled and len(docs) > 0:
                retry_count, tried_heuristic = 0, False
                while retry_count <= max_retries:
                    extracted_sql = extract_sql_from_text(raw_result)
                    if extracted_sql is None:
                        logs.append("Aucune requête SQL extraite.")
                        break
                    try:
                        sql_result = execute_sql_via_api(
                            connexion_params, extracted_sql
                        )
                        if sql_result is not None:
                            logs.append(f"Résultat SQL: {sql_result}")
                            docs.insert(
                                0,
                                {
                                    "text": (
                                        f"Résultat SQL pour la requête suivante : {query}\n"
                                        f"Code SQL : {extracted_sql}\n\n"
                                        f"Résultat :\n{json.dumps(sql_result, indent=2, ensure_ascii=False)}"
                                    ),
                                    "source": "résultat_sql",
                                },
                            )
                            final_answer = reformulate_answer_via_llm(
                                query, build_contexte(docs)
                            )
                            break
                        else:
                            raise Exception("Résultat SQL vide ou invalide")
                    except Exception as e:
                        logs.append(f"Erreur exécution SQL: {e}")
                        if not tried_heuristic:
                            extracted_sql = corriger_sql_heuristique(extracted_sql)
                            tried_heuristic = True
                            continue
                        if retry_count == max_retries:
                            final_answer = f"Erreur lors de l'exécution de la requête SQL : {e}\nRequête SQL : {extracted_sql}"
                            break
                        correction_prompt = [
                            {
                                "role": "system",
                                "content": "Tu es un assistant SQL expert qui corrige les requêtes SQL erronées.",
                            },
                            {
                                "role": "user",
                                "content": (
                                    f"La requête SQL suivante a provoqué une erreur lors de son exécution :\n{extracted_sql}\n"
                                    f"Erreur : {e}\n"
                                    "Merci de corriger cette requête SQL pour qu'elle soit valide et exécutable en PostgreSQL.\n"
                                    "Retourne uniquement la requête SQL corrigée, sans explications."
                                ),
                            },
                        ]
                        raw_result = call_llm(
                            "mixtral", correction_prompt, temperature=0, max_tokens=200
                        )
                        retry_count += 1

    set_cache(query, docs, final_answer)
    return {"answer": final_answer, "logs": logs}