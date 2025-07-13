import time, re, os, jwt, requests, json

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
