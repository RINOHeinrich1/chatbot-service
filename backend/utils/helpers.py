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
