# app/utils/helpers.py
from config import *
import re
import requests
import time
import json
import jwt

def get_slots_for_chatbot(chatbot_id: str):
    response = supabase.from_("chatbot_slot_associations")\
        .select("*, slots(*)")\
        .eq("chatbot_id", chatbot_id)\
        .execute()

    # Vérifie simplement si des données sont retournées
    if not response or not getattr(response, "data", None):
        return []

    slots = []
    for assoc in response.data:
        if "slots" in assoc and assoc["slots"] is not None:
            slot_data = {
                "slot_name": assoc["slots"]["slot_name"],
                "columns": assoc["slots"]["columns"],
                "description": assoc["description"],
                "slot_id": assoc["slot_id"],
            }
            slots.append(slot_data)

    return slots

def get_web_actions_for_chatbot(chatbot_id: str):
    response = supabase.from_("chatbot_slot_associations")\
        .select("*, slots(*)")\
        .eq("chatbot_id", chatbot_id)\
        .execute()

    # Vérifie simplement si des données sont retournées
    if not response or not getattr(response, "data", None):
        return []

    slots = []
    for assoc in response.data:
        if "slots" in assoc and assoc["slots"] is not None:
            slot_data = {
                "slot_id": assoc["slot_id"],
            }
            slots.append(slot_data)

    return slots

def get_possible_values_for_chatbot(chatbot_id: str):
    """
    Retourne une liste plate de toutes les valeurs possibles
    pour les slots associés à un chatbot.
    """
    response = supabase.from_("chatbot_slot_associations")\
        .select("*, slots(*)")\
        .eq("chatbot_id", chatbot_id)\
        .execute()

    if not response or not getattr(response, "data", None):
        return []

    values = []
    for assoc in response.data:
        slot = assoc.get("slots")
        if slot and slot.get("valeurs_possibles"):
            # Récupère uniquement le label si c'est un dict
            for v in slot["valeurs_possibles"]:
                if isinstance(v, dict) and "label" in v:
                    values.append(v["label"])
                else:
                    values.append(str(v))

    return values

def get_slot_events_for_chatbot(chatbot_id: str):
    # 1️⃣ Récupère d'abord les slots associés à ce chatbot
    slots = get_slots_for_chatbot(chatbot_id)
    slot_ids = [s["slot_id"] for s in slots]

    # Si aucun slot n’est trouvé, on retourne une liste vide
    if not slot_ids:
        return []

    # 2️⃣ Récupère les événements correspondant à ces slot_ids
    response = supabase.from_("slot_events")\
        .select("*")\
        .in_("slot_id", slot_ids)\
        .execute()

    # 3️⃣ Vérifie si des données sont retournées
    if not response or not getattr(response, "data", None):
        return []

    events = []
    for event in response.data:
        event_data = {
            "event_id": event.get("id"),
            "slot_id": event.get("slot_id"),
            "event_name": event.get("event"),
            "action_id": event.get("action_id"),
            "created_at": event.get("created_at"),
        }
        events.append(event_data)

    return events

def get_web_action_by_id(action_id: int):
    """
    Récupère une web action depuis la table 'web_actions' de Supabase
    à partir de son action_id.

    Retourne :
      - Un dictionnaire contenant les colonnes de la web_action si elle existe
      - None si aucune action n'est trouvée
    """
    response = supabase.from_("web_actions")\
        .select("*")\
        .eq("id", action_id)\
        .execute()

    if not response or not getattr(response, "data", None):
        return None

    # Retourne le premier résultat trouvé
    return response.data[0] if len(response.data) > 0 else None

def get_event_web_action_urls(chatbot_id: str):
    """
    Pour un chatbot donné, récupère les URLs des web actions
    associées à ses events.
    """
    urls = []

    # 1️⃣ Récupère les événements du chatbot
    events = get_slot_events_for_chatbot(chatbot_id)

    # 2️⃣ Pour chaque événement, récupère la web action et son URL
    for event in events:
        action_id = event.get("action_id")
        if not action_id:
            continue

        action = get_web_action_by_id(action_id)
        if action and action.get("url"):
            urls.append({
                "event_name": event.get("event_name"),
                "url": action.get("url")
            })

    return urls

def process_chatbot_web_actions(chatbot_id):
    """
    Récupère et affiche les web actions associées aux événements d'un chatbot,
    puis retourne directement le lien (URL) s'il existe.
    """
    # 1️⃣ Récupérer les événements liés au chatbot
    events = get_slot_events_for_chatbot(chatbot_id)
    if not events:
        print(f"⚠️ Aucun événement trouvé pour le chatbot {chatbot_id}.")
        return None

    # 3️⃣ Récupérer et afficher les URLs correspondantes
    urls = get_event_web_action_urls(chatbot_id)
    if not urls:
        print("⚠️ Aucune URL trouvée pour ce chatbot.")
        return None

    print("\n🌐 Liste des URLs trouvées :")
    for u in urls:
        print(f"  - Événement : {u['event_name']}, URL : {u['url']}")

    # 🔁 Retourner le premier lien (ou tous si tu veux)
    first_url = urls[0]["url"]
    return first_url

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

    # 3. Extraction depuis le mot SELECT, peu importe où il se trouve dans la ligne
    lines = text.splitlines()
    collecting = False
    sql_lines = []

    for line in lines:
        if not collecting:
            # Cherche la position du mot SELECT (sans tenir compte de la casse)
            idx = line.upper().find("SELECT")
            if idx != -1:
                collecting = True
                # Commence la collecte à partir de "SELECT" dans cette ligne
                sql_lines.append(line[idx:])
        else:
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
