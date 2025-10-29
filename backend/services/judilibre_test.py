import requests
import json
from typing import Optional, Dict, Any, List

# --- Constantes Globales (Basées sur vos fichiers .env et config.py) ---

# 1. JUDILIBRE (Piste Gouv)
AUTH_URL = "https://sandbox-oauth.piste.gouv.fr/api/oauth/token"
CLIENT_ID = "d22a7eec-525e-4c7c-9dc5-b9df90313503" 
CLIENT_SECRET = "d310b9af-1a56-455e-8580-5f7a0e2c9140" 
API_BASE_URL = "https://sandbox-api.piste.gouv.fr/cassation/judilibre/v1.0"
JUDILIBRE_PAGE_SIZE = 5 # Gardé à 5 pour des tests rapides

# 2. AI Service (Mixtral via Infomaniak)
# (Valeurs déduites de vos fichiers .env et config.py)
AI_PRODUCT_ID = "105104"
AI_TOKEN = "oPtkaPwDrHvl_DKeRFtMCAYHyEoMixyLlouB4DUH97_KWLxnGt4xJ_znEUDt13ZE90MaAxvXQgDjZr6s"

# L'URL RÉELLE de votre API, construite comme dans votre config.py
AI_URL = f"https://api.infomaniak.com/1/ai/{AI_PRODUCT_ID}/openai/chat/completions"
AI_MODEL = "mixtral" # Le nom du modèle tel qu'utilisé dans votre code d'exemple

# --- Fonctions Auxiliaires (API Judilibre) ---

def get_judilibre_token(client_id: str, client_secret: str) -> Optional[str]:
    """
    1. AUTHENTIFICATION : Obtient un token d'accès OAuth2 auprès de Piste Gouv.
    """
    print("Tentative d'obtention du token OAuth2...")
    auth_data = {"grant_type": "client_credentials"}
    
    try:
        auth_response = requests.post(
            AUTH_URL,
            data=auth_data,
            auth=(client_id, client_secret),
            timeout=10
        )
        auth_response.raise_for_status() 
        
        token_data = auth_response.json()
        token = token_data.get("access_token")
        
        if not token:
            print(f"Erreur: 'access_token' non trouvé dans la réponse : {token_data}")
            return None
            
        print("Token OAuth2 obtenu avec succès.")
        return token
        
    except requests.exceptions.RequestException as e:
        print(f"Erreur de connexion/HTTP lors de l'authentification: {e}")
    
    return None

def search_judilibre(token: str, query: str) -> Optional[Dict[str, Any]]:
    """
    3. RECHERCHE (Judilibre) : Appelle l'endpoint /search pour obtenir des résumés.
    """
    search_url = f"{API_BASE_URL}/search"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    params = {
        "query": query,
        "page_size": JUDILIBRE_PAGE_SIZE,
        "page": 0
    }
    
    print(f"Recherche Judilibre avec query='{query}' (Taille: {JUDILIBRE_PAGE_SIZE})...")
    try:
        response = requests.get(search_url, headers=headers, params=params, timeout=15)
        response.raise_for_status()
        print("Recherche effectuée avec succès.")
        return response.json()
    except requests.exceptions.HTTPError as http_err:
        print(f"Erreur HTTP lors de la recherche (/search): {http_err}")
        if http_err.response:
             print(f"Réponse API (erreur): {http_err.response.text}")
    except requests.exceptions.RequestException as e:
        print(f"Erreur de connexion lors de la recherche (/search): {e}")
    
    return None

# def get_judilibre_decision_detail(token: str, decision_id: str) -> Optional[Dict[str, Any]]:
#     """
#     [COMMENTÉ - ERREUR 403] 
#     Cette fonction permettrait de récupérer le JSON complet de la décision 
#     (endpoint /decision/{id}). Elle est commentée car l'accès n'est 
#     actuellement pas autorisé (403 Forbidden).
#     """
#     pass


# --- Fonctions LLM (Mixtral - Appel Réel) ---

def call_llm(model: str, messages: List[Dict], temperature: float = 0.2, max_tokens: int = 1024) -> str:
    """
    Fonction principale pour appeler l'API Mixtral (Infomaniak)
    Basée sur votre code d'exemple.
    """
    print(f"[LLM] Appel de l'API (Modèle: {model})...")
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
    
    try:
        response = requests.post(AI_URL, headers=headers, data=json.dumps(payload), timeout=45)
        response.raise_for_status()
        
        # Format de réponse compatible OpenAI
        json_response = response.json()
        content = json_response["choices"][0]["message"]["content"].strip()
        print("[LLM] Réponse reçue.")
        return content
        
    except requests.exceptions.RequestException as e:
        print(f"⚠️ Erreur de connexion/HTTP lors de l'appel LLM : {e}")
        if e.response:
            print(f"Réponse API (erreur): {e.response.text}")
        return f"**Erreur de service AI** : Échec de la communication avec le LLM."
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        print(f"⚠️ Erreur de parsing de la réponse LLM : {e}")
        return f"**Erreur de service AI** : Réponse inattendue du LLM."

def extract_keywords_via_llm(question: str) -> str:
    """
    2. EXTRACTION (Mixtral) : Demande à Mixtral d'extraire des mots-clés optimisés.
    """
    # Prompt amélioré pour éviter le "hors sujet"
    prompt = (
        "Tu es un expert en recherche juridique pour la base de données Judilibre (Cour de cassation française). "
        "Analyse la question utilisateur suivante et extrais les mots-clés (termes juridiques ou concepts clés) "
        "strictement pertinents pour trouver des décisions de jurisprudence. "
        "Ne réponds que par les mots-clés, séparés par des espaces. Ne fais pas de phrase. "
        "Par exemple, si la question est 'Quelles sont les règles pour la garde alternée ?', réponds 'garde alternée résidence enfant intérêt supérieur'.\n\n"
        f"Question: '{question}'"
    )
    
    messages = [
        {"role": "system", "content": "Tu es un extracteur de mots-clés expert en droit français, optimisé pour la recherche jurisprudentielle."},
        {"role": "user", "content": prompt}
    ]
    
    # Appel réel à Mixtral (via Infomaniak)
    keywords = call_llm(AI_MODEL, messages, temperature=0.0, max_tokens=100)
    
    # Nettoyage pour s'assurer qu'il n'y a que des mots-clés
    keywords = keywords.replace('"', '').replace("'", "").replace(",", "").strip()
    return keywords

def reformulate_answer_via_llm(question: str, contexte_judilibre: str) -> str:
    """
    6. REFORMULATION (Mixtral) : Demande à Mixtral de synthétiser les résultats.
    """
    # Prompt amélioré pour une synthèse structurée
    prompt = (
        "Tu es un assistant juridique expert (basé sur Mixtral). Tu dois analyser un contexte JSON contenant des résumés de jurisprudence de la Cour de cassation (Judilibre) pour répondre à une question utilisateur.\n\n"
        "**TÂCHE :** Rédige une réponse claire, structurée et en langage naturel (Markdown).\n\n"
        "**Contexte Fourni (JSON) :**\n"
        f"{contexte_judilibre}\n\n"
        "**Question Utilisateur :**\n"
        f"{question}\n\n"
        "---"
        "**Instructions de formatage :**\n"
        "1.  **Si 'status' est 'no_results'** : Informe poliment l'utilisateur qu'aucune décision n'a été trouvée pour les mots-clés (mentionne les 'query').\n"
        "2.  **Si 'status' est 'success'** : Rédige ta réponse en utilisant impérativement la structure Markdown suivante :\n"
        "### ⚖️ Cadre Légal et Principes Clés\n"
        "(Ici, déduis les grands principes juridiques ou les articles de code pertinents (ex: Code Civil, Convention de New York) mentionnés ou implicites dans les résumés.)\n\n"
        "### 🧠 Synthèse de la Jurisprudence\n"
        "(Ici, réponds à la question de l'utilisateur en synthétisant le résumé principal (principal_summary) et les résumés connexes (other_summaries). Explique ce que la Cour de cassation a décidé.)\n\n"
        "---\n"
        "**Source principale (Judilibre) :** (Indique l'ID de la décision principale, ex: ID: {principal_id})"
    )

    messages = [
        {"role": "system", "content": "Tu es un juriste synthétiseur expert (Mixtral) qui répond en français en se basant *uniquement* sur le contexte Judilibre fourni."},
        {"role": "user", "content": prompt}
    ]
    
    # Appel réel à Mixtral
    return call_llm(AI_MODEL, messages, temperature=0.3, max_tokens=2048)

# --- Fonction Principale (Orchestration) ---

def chatbot_flow(question: str) -> str:
    """
    Orchestre le flux complet du chatbot : Auth -> Extraction Mixtral -> Recherche Judilibre -> Synthèse Mixtral.
    """
    print("\n--- DÉMARRAGE DU FLUX CHATBOT ---")
    
    # 1. Authentification
    token = get_judilibre_token(CLIENT_ID, CLIENT_SECRET)
    if not token:
        return "**Erreur critique** : Impossible d'obtenir le token d'authentification Piste."

    # 2. Extraction (Mixtral)
    query_keywords = extract_keywords_via_llm(question)
    print(f"Mots-clés extraits par Mixtral: {query_keywords}")
    
    # Sécurité: Si l'appel LLM a échoué, on arrête
    if query_keywords.startswith("**Erreur de service AI**"):
        return query_keywords # Retourne l'erreur LLM directement

    # 3. Recherche (Judilibre)
    search_results = search_judilibre(token, query_keywords)
    if not search_results:
        return "**Erreur API** : L'appel à l'API de recherche Judilibre a échoué."

    # 4. Gestion des Résultats
    results_list: List[Dict[str, Any]] = search_results.get("results", [])
    
    if not results_list:
        print("Aucun résultat trouvé sur Judilibre.")
        # 4a. Appel à la reformulation (cas "pas de données")
        contexte_vide = json.dumps({"status": "no_results", "query": query_keywords})
        return reformulate_answer_via_llm(question, contexte_vide)

    print(f"Succès : {len(results_list)} résumés trouvés.")

    # 5. Préparation du Contexte pour Mixtral
    
    # Collecte des données pour le LLM, uniquement à partir de /search
    principal_decision = results_list[0]
    principal_id = principal_decision.get("id", "N/A")
    principal_summary = principal_decision.get("summary", "Résumé non disponible.")
    
    other_summaries = [
        res.get("summary", "Résumé non disponible.") 
        for res in results_list[1:] # On prend à partir du 2ème élément
    ]
    
    # Création du contexte JSON pour le LLM
    contexte_pour_llm_json = json.dumps({
        "status": "success",
        "principal_id": principal_id,
        "principal_summary": principal_summary,
        "other_summaries": other_summaries
    }, indent=2, ensure_ascii=False)
    
    # 6. Reformulation (Mixtral)
    final_answer = reformulate_answer_via_llm(question, contexte_pour_llm_json)
    
    print("--- FIN DU FLUX CHATBOT ---")
    return final_answer

# --- Point d'entrée du script ---

if __name__ == "__main__":
    
    # Test avec la question qui était "hors sujet"
    question_utilisateur_test = "Quels sont les critères de l'intérêt supérieur de l'enfant pour fixer la résidence (garde) ?"
    
    # Lancer le flux
    reponse_finale = chatbot_flow(question_utilisateur_test)
    
    print("\n============================================")
    print(" ✅ Réponse Finale du Chatbot (Synthèse Mixtral)")
    print("============================================")
    print(reponse_finale)