import re
from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Optional, Union
from services.retrieval import retrieve_documents
from services.mixtral import ask_mixtral_for_relevant_sources, generate_answer,is_question_or_request,extract_slots_with_llm, reformulate_answer_via_llm, call_llm
from services.clarifier import clarify_question
from utils.helpers import (
    get_connexions_for_chatbot,
    get_documents_for_chatbot,
    get_slots_for_chatbot,
    get_memoire_contextuelle,
    get_slot_events_for_chatbot,
    get_web_action_by_id,
    get_event_web_action_urls
)
from qdrant_client import QdrantClient
from config import *
import json

router = APIRouter()

client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)

class Reasoning(BaseModel):
    sources: List[str]
    sql: Optional[str] = None

class AnswerResponse(BaseModel):
    documents: List[str]
    answer: str
    logs: Optional[List[str]] = []  # Ajouté pour stocker les logs
    slot_state: Optional[dict] = {}  # <- AJOUT ICI


class MessageHistory(BaseModel):
    role: str
    content: str

class QuestionRequest(BaseModel):
    question: str
    chatbot_id: Optional[str] = None
    owner_id: Optional[str] = None
    history: Optional[List[MessageHistory]] = []
    slot_state: Optional[dict] = {}

@router.post("/ask", response_model=AnswerResponse)
def ask_question(req: QuestionRequest):
    logs = []
    original_question = req.question
    combined_docs = []
    context_messages = []
    slot_state = req.slot_state or {}
    
    # --- Historique et clarification ---
    if req.chatbot_id and req.history:
        max_ctx = get_memoire_contextuelle(req.chatbot_id)
        context_messages = req.history[-max_ctx:]
    logs.append(f"🔍 Question originale : {original_question}")
    
    clarified_question = original_question
    if is_question_or_request(original_question):
        clarified_question = clarify_question(
            history=[{"role": m.role, "content": m.content} for m in context_messages],
            question=original_question
        )
        logs.append(f"🔍 Question clarifiée : {clarified_question}")
    else:
        logs.append("Requête non considérée comme demande, pas besoin de clarification")
    
    # --- Récupération des sources pertinentes ---
    relevant_sources = ask_mixtral_for_relevant_sources(req.chatbot_id, clarified_question)
    if not relevant_sources:
        logs.append("Aucune source sélectionnée.")
    else:
        logs.append(f"Sources utilisées : {relevant_sources}")
    
    documents_to_use, connexions_to_use, slots_to_use = [], [], []
    if isinstance(relevant_sources, str):
        try:
            relevant_sources = json.loads(relevant_sources)
        except Exception:
            relevant_sources = []

    for src in relevant_sources:
        if isinstance(src, dict):
            typ = src.get("type")
            if typ == "document":
                documents_to_use.append(src.get("name"))
            elif typ in ["connexion", "connection"]:
                connexions_to_use.append(src.get("name"))
            elif typ == "slot":
                slots_to_use.append(src.get("name"))
    
    # --- Récupération documents ---
    if documents_to_use:
        text_docs = retrieve_documents(
            client, COLLECTION_NAME, clarified_question, k=10, document_filter=documents_to_use
        )
        combined_docs.extend(text_docs)
        logs.append(f"Documents textes : {text_docs}")
        
    if connexions_to_use:
        connexion_docs = retrieve_documents(
            client, POSTGRESS_COLLECTION_NAME, clarified_question, k=10, document_filter=connexions_to_use
        )
        combined_docs.extend(connexion_docs)
        logs.append("Documents PostgreSQL : " + json.dumps(connexion_docs, ensure_ascii=False, indent=2))
    
    # --- Récupération slots ---
    slot_values = slot_state or {}
    if slots_to_use:
        all_slots = get_slots_for_chatbot(req.chatbot_id)
        columns_to_extract = [s["columns"] for s in all_slots if s["slot_name"] in slots_to_use]
        if columns_to_extract:
            slot_values = extract_slots_with_llm(
                clarified_question, columns_to_extract, slot_state, req.chatbot_id
            )
            logs.append("Valeurs extraites des slots : " + json.dumps(slot_values, ensure_ascii=False))
    
    # --- Ajouter data_api_list de data_action_api dans combined_docs si existant ---
    if slot_values.get("data_action_api") and "data_api_list" in slot_values["data_action_api"]:
        combined_docs.append({
            "text": json.dumps(slot_values["data_action_api"]["data_api_list"], ensure_ascii=False, indent=2)
        })
        logs.append(f"✅ data_api_list ajoutés dans combined_docs : {len(slot_values['data_action_api']['data_api_list'])}")
    
    docs_text_only = [doc["text"] for doc in combined_docs]
    
    # --- Générer la réponse ---
    resp = generate_answer(clarified_question, combined_docs, req.chatbot_id)
    answer_llm = resp.get("answer", "")
    logs.extend(resp.get("logs", []))
    
    # --- Construction de la réponse finale ---
    answer_final = ""

    if slot_values.get("data_action_api") and "data_api_list" in slot_values["data_action_api"]:
        try:
            data_list = slot_values["data_action_api"]["data_api_list"]

            if data_list:
                # ✅ On garde le JSON brut pour reformulation par le LLM ensuite
                answer_final = json.dumps(data_list, ensure_ascii=False, indent=2)
            else:
                # ⚠️ Aucune donnée trouvée : on génère une réponse polie via LLM
                llm_prompt_empty = [
                    {
                        "role": "system",
                        "content": (
                            "Tu es un assistant bienveillant et pédagogue. "
                            "Si aucune information n'a été trouvée pour la requête de l'utilisateur, "
                            "réponds poliment en expliquant qu'aucun résultat n’a été trouvé pour cette question "
                            "et encourage l'utilisateur à reformuler ou à préciser sa demande."
                        )
                    },
                    {
                        "role": "user",
                        "content": f"Question utilisateur : {original_question}\nAucune donnée trouvée dans l'API."
                    }
                ]
                try:
                    answer_final = call_llm("mixtral", llm_prompt_empty).strip()
                except Exception as e:
                    logs.append(f"⚠️ Erreur LLM pour réponse vide : {e}")
                    answer_final = "Aucune réponse disponible pour cette question."

        except Exception as e:
            logs.append(f"⚠️ Erreur lors du traitement des données API : {e}")
            answer_final = answer_llm or "Aucune réponse disponible."
    else:
        answer_final = answer_llm or "Aucune réponse disponible."

    # --- Clarification avec LLM pour rendre la réponse fluide ---
    clair_answer_final = ""

    if answer_final:
        clarify_prompt = [
            {
                "role": "system",
                "content": (
                    "Tu es un assistant expert en reformulation claire et pédagogique. "
                    "Ta tâche est d'améliorer la compréhension du texte fourni en le réécrivant en français naturel et fluide.\n\n"
                    "Règles à suivre :\n"
                    "1. N'ajoute aucune information nouvelle et ne modifie pas le sens du texte.\n"
                    "2. Organise le texte avec des paragraphes clairs et des titres ou expressions importantes en **gras**.\n"
                    "3. Explique ou reformule les passages techniques si nécessaire, sans trahir le contenu.\n"
                    "4. Évite tout ton robotique ou académique excessif — le texte doit être lisible et humain.\n"
                    "5. Écris uniquement en français, sans anglais ni caractères techniques (JSON, crochets, guillemets inutiles, etc.).\n"
                    "6. Si le texte contient plusieurs articles, sépare-les proprement avec des sous-titres explicites.\n"
                    "7. Ne traduis pas les termes juridiques ou noms d’articles du Code civil."
                ),
            },
            {
                "role": "user",
                "content": f"{answer_final}"
            }
        ]
        try:
            # clair_answer_final = call_llm("mixtral", clarify_prompt).strip()
            clair_answer_final = call_llm("mixtral", clarify_prompt).strip()
            print("🪄 Réponse clarifiée :", clair_answer_final)
        except Exception as e:
            logs.append(f"⚠️ Erreur lors de la clarification via LLM : {e}")
            clair_answer_final = answer_final
    else:
        clair_answer_final = "Aucune réponse disponible pour cette question."

    # --- Réponse finale envoyée au frontend ---
    return AnswerResponse(
        documents=docs_text_only,
        answer=clair_answer_final,  # ✅ On renvoie la version clarifiée finale
        logs=logs,
        slot_state=slot_values
    )