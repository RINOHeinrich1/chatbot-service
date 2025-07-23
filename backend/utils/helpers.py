# app/utils/helpers.py
from config import *
import re
import requests
import time
import json
import jwt


def get_connexions_for_chatbot(chatbot_id: str):
    return supabase.table("chatbot_pgsql_connexions") \
                   .select("connexion_name, description") \
                   .eq("chatbot_id", chatbot_id) \
                   .execute().data or []

def get_documents_for_chatbot(chatbot_id: str):
    return supabase.table("chatbot_document_association") \
                   .select("document_name, description") \
                   .eq("chatbot_id", chatbot_id) \
                   .execute().data or []

def get_memoire_contextuelle(chatbot_id: str) -> int:
    data = supabase.table("chatbots") \
                   .select("memoire_contextuelle") \
                   .eq("id", chatbot_id) \
                   .single() \
                   .execute().data
    return int(data.get("memoire_contextuelle", 0)) if data else 0

def extract_sql_from_text(text):
    # 1. Si c’est une chaîne JSON (ex: "\"SELECT ...\""), essaye de la parser
    try:
        parsed = json.loads(text)
        text = parsed
    except json.JSONDecodeError:
        pass

    # 2. Bloc Markdown SQL : ```sql ... ```
    match = re.search(r"```sql\s+(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if match:
        return _clean_sql(match.group(1))

    # 3. Bloc commençant par SELECT jusqu’à un point-virgule ou fin
    lines = text.splitlines()
    collecting = False
    sql_lines = []
    for line in lines:
        if not collecting and line.strip().upper().startswith("SELECT"):
            collecting = True
        if collecting:
            sql_lines.append(line)
            if ";" in line:
                break
    if sql_lines:
        return _clean_sql("\n".join(sql_lines))

    return None

def _clean_sql(sql):
    return sql.replace("\\*", "*").replace("\\_", "_")


def generate_jwt():
    payload = {
        "sub": "service-role",  # ou un ID spécifique
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,  # valide 5 minutes
        "role": "authenticated"  # facultatif selon ton handler Go
    }

    token = jwt.encode(payload, SUPABASE_JWT_SECRET, algorithm="HS256")
    return token
