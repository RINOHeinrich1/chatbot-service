import requests
import json
import re
from typing import Optional, Dict, Any
from fastapi import HTTPException
from config import (
    JUDILIBRE_CLIENT_ID,
    JUDILIBRE_CLIENT_SECRET,
    JUDILIBRE_AUTH_URL,
    JUDILIBRE_API_BASE_URL,
    JUDILIBRE_PAGE_SIZE,
    AI_MODEL
)

try:
    from services.mixtral import call_llm
except ImportError:
    from .mixtral import call_llm


# --- PROMPT BIEN STRUCTURÉ ---
def build_prompt(role: str, objectif: str, instructions: str, exemple: Optional[str], question: str, format_attendu: str) -> str:
    exemple_section = f"### EXEMPLE ###\n{exemple}\n\n" if exemple else ""
    return f"""
        ### RÔLE ###
        {role}

        ### OBJECTIF ###
        {objectif}

        ### INSTRUCTIONS ###
        {instructions}

        {exemple_section}### QUESTION UTILISATEUR ###
        {question}

        ### FORMAT ATTENDU ###
        {format_attendu}
        """.strip()


# --- AUTHENTIFICATION JUDILIBRE ---
def get_judilibre_token() -> str:
    data = {"grant_type": "client_credentials"}
    try:
        resp = requests.post(
            JUDILIBRE_AUTH_URL,
            data=data,
            auth=(JUDILIBRE_CLIENT_ID, JUDILIBRE_CLIENT_SECRET),
            timeout=10
        )
        resp.raise_for_status()
        token = resp.json().get("access_token")
        if not token:
            raise ValueError("Token manquant dans la réponse de l’API.")
        return token
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Erreur Judilibre (auth) : {e}")


# --- RECHERCHE ---
def search_judilibre(token: str, query: str) -> Optional[Dict[str, Any]]:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    params = {
        "query": query,
        "page_size": JUDILIBRE_PAGE_SIZE,
        "page": 0,
        "field": ["motivations"],  # <-- ajouter le champ motivations
        "resolve_references": "false"  # tu peux mettre true si tu veux les intitulés complets
    }
    url = f"{JUDILIBRE_API_BASE_URL}/search"
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        print("Résultats obtenus avec highlights de motivations.")
        return resp.json()
    except requests.exceptions.RequestException as e:
        print(f"Erreur API : {e}")
        return None


# --- DÉTAILS D'UNE DÉCISION ---
def get_decision_details(token: str, decision_id: str, resolve_references: bool = True) -> Optional[Dict[str, Any]]:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    params = {"id": decision_id, "resolve_references": str(resolve_references).lower()}
    url = f"{JUDILIBRE_API_BASE_URL}/decision"
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        print(" Détails récupérés avec succès.")
        return resp.json()
    except requests.exceptions.RequestException as e:
        print(f" Erreur lors de la récupération : {e}")
        return None


# --- EXTRACTION DE MOTS-CLÉS ---
def extract_keywords_via_llm(question: str) -> list[str]:
    prompt = build_prompt(
        role="Tu es un expert en droit français et en recherche jurisprudentielle.",
        objectif="Extraire tous les mots-clés pertinents pour interroger Judilibre, sans limite de nombre.",
        instructions=(
            "- Donne uniquement les mots-clés finaux, séparés par des espaces.\n"
            "- Pas de phrases ou de ponctuation.\n"
            "- Évite les termes vagues ('loi', 'procès', 'tribunal').\n"
            "- Fournis autant de mots-clés pertinents que possible."
        ),
        exemple="Question : Quelles sont les règles pour la garde alternée ?\nRéponse : garde alternée résidence enfant intérêt supérieur",
        question=question,
        format_attendu="mot1 mot2 mot3 ..."
    )

    messages = [
        {"role": "system", "content": "Tu es un extracteur de mots-clés juridiques concis."},
        {"role": "user", "content": prompt}
    ]

    try:
        keywords = call_llm(AI_MODEL, messages, temperature=0.0, max_tokens=150)
        keywords = re.sub(r"[\"',()\n]", " ", keywords).strip()
        keywords = re.sub(r"\s+", " ", keywords)
        keywords_list = [kw.lower() for kw in keywords.split() if kw.lower() not in {"loi", "procès", "tribunal"}]
        print(f"Mots-clés extraits : {keywords_list}")
        return keywords_list
    except Exception as e:
        print(f"Erreur d’extraction : {e}")
        raise HTTPException(status_code=503, detail=f"Erreur Mixtral (Extraction) : {e}")


# --- REFORMULATION VIA LLM ---
def reformulate_answer_via_llm(question: str, contexte_judilibre: str) -> str:
    instructions = (
        "- Rédige une réponse claire, fluide et professionnelle en français.\n"
        "- Ne parle pas de toi-même.\n"
        "- Si aucune décision n’est trouvée, précise-le poliment.\n"
        "- Si des décisions existent :\n"
        "   1 Donne le principe juridique général.\n"
        "   2 Résume la décision principale (chambre, date, solution).\n"
        "   3 Cite la source."
    )

    prompt = build_prompt(
        role="Tu es un juriste-assistant IA spécialisé en droit français.",
        objectif="Fournir une réponse claire à partir des décisions Judilibre.",
        instructions=instructions,
        exemple=None,
        question=f"### CONTEXTE JURIDIQUE ###\n{contexte_judilibre}\n\n### QUESTION ###\n{question}",
        format_attendu="Réponse claire et structurée, en français professionnel."
    )

    messages = [
        {"role": "system", "content": "Tu es un assistant juridique expert qui rédige comme un humain."},
        {"role": "user", "content": prompt}
    ]

    try:
        answer = call_llm(AI_MODEL, messages, temperature=0.4, max_tokens=2048)
        print(" Réponse reformulée avec succès.")
        return answer
    except Exception as e:
        print(f" Erreur lors de la reformulation : {e}")
        raise HTTPException(status_code=503, detail=f"Erreur Mixtral (Reformulation) : {e}")

# --- DÉTECTION D'INTENTION ---
def detect_intention(question: str) -> str:
    q = question.lower().strip()

    # --- Politesse ---
    if re.search(r"\b(merci|thanks|thx|très bien|ok|bon)\b", q, re.IGNORECASE):
        return "remerciement"
    if re.search(r"\b(hey|bonjour|salut|coucou|bonsoir)\b", q, re.IGNORECASE):
        return "salutation"
    if re.search(r"\b(au revoir|bonne journée|bonne soirée)\b", q, re.IGNORECASE):
        return "au_revoir"

    # --- Impolitesse ---
    if re.search(r"\b(con|idiot|nul|stupide|ferme ta|va te)\b", q, re.IGNORECASE):
        return "insulte"

    # --- Demande floue ---
    if len(q.split()) < 3:
        return "floue"

    return "juridique"

# --- FONCTION PRINCIPALE ---
async def judilibre_flow(question: str) -> Dict[str, Any]:
    intention = detect_intention(question)
    if intention == "remerciement":
        return {"answer": "Je vous en prie 😊, heureux d’avoir pu vous aider.", "decision": [], "summary": "", "motivations": "", "themes": ""}

    if intention == "salutation":
        return {"answer": "Bonjour 👋 ! En quoi puis-je vous aider concernant le droit français ?", "decision": [], "summary": "", "motivations": "", "themes": ""}

    if intention == "au_revoir":
        return {"answer": "Au revoir ! N’hésitez pas à revenir si vous avez d’autres questions juridiques ⚖️.", "decision": [], "summary": "", "motivations": "", "themes": ""}

    if intention == "insulte":
        return {"answer": "Je préfère rester professionnel et respectueux. Posons plutôt une question juridique 😊.", "decision": [], "summary": "", "motivations": "", "themes": ""}

    if intention == "floue":
        return {"answer": "Pouvez-vous préciser un peu votre question ? Par exemple : ‘Quelles sont les conditions de la garde alternée ?’", "decision": [], "summary": "", "motivations": "", "themes": ""}


    token = get_judilibre_token()
    keywords_list = extract_keywords_via_llm(question)
    if not keywords_list:
        raise HTTPException(status_code=400, detail="Impossible d'extraire des mots-clés pertinents.")

    query = " ".join(keywords_list)
    results = search_judilibre(token, query)
    if not results or not results.get("results"):
        contexte = {"status": "no_results", "query": query}
        answer = reformulate_answer_via_llm(question, json.dumps(contexte))
        return {"answer": answer, "decision": [], "summary": "", "motivations": "", "themes": ""}

    # --- FILTRAGE DES DÉCISIONS PERTINENTES ---
    relevant_results = []
    for r in results.get("results", []):
        text = (r.get("summary", "") + " " + " ".join(r.get("themes", []))).lower()
        if any(kw in text for kw in keywords_list):
            relevant_results.append(r)

    if not relevant_results:
        contexte = {"status": "no_relevant_results", "query": query}
        answer = reformulate_answer_via_llm(question, json.dumps(contexte))
        return {"answer": answer, "decision": [], "summary": "", "motivations": "", "themes": ""}

    # --- DÉCISION PRINCIPALE ---
    main_decision = relevant_results[0]
    decision_id = main_decision.get("id")
    decision_details = get_decision_details(token, decision_id)

    summary = main_decision.get("summary", "")
    motivations = ""
    if decision_details:
        motivations = decision_details.get("motivations") or ""
        if not motivations and "highlights" in main_decision:
            motivations = " ".join(main_decision["highlights"].get("motivations", []))
    themes = ", ".join(main_decision.get("themes", []))

    contexte = {
        "status": "success",
        "principal_id": decision_id,
        "principal_summary": summary,
        "principal_details": decision_details,
        "other_summaries": [r.get("summary") for r in relevant_results[1:5]]
    }
    contexte_json = json.dumps(contexte, indent=2, ensure_ascii=False)
    answer = reformulate_answer_via_llm(question, contexte_json)

    return {
        "answer": answer,
        "decision": [{"text": decision_details or "", "id": decision_id}],
        "summary": summary,
        "motivations": motivations,
        "themes": themes
    }
