from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Optional, Union
from services.retrieval import retrieve_documents
from services.mixtral import ask_mixtral_for_relevant_sources, generate_answer,is_question_or_request,extract_slots_with_llm
from services.clarifier import clarify_question
from utils.helpers import (
    get_connexions_for_chatbot,
    get_documents_for_chatbot,
    get_slots_for_chatbot,
    get_memoire_contextuelle,
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
    history: Optional[List[MessageHistory]] = []
    slot_state: Optional[dict] = {} 

@router.post("/ask", response_model=AnswerResponse)
def ask_question(req: QuestionRequest):
    logs = []
    original_question = req.question
    combined_docs = []
    context_messages = []
    slot_state=req.slot_state
    if req.chatbot_id and req.history:
        max_ctx = get_memoire_contextuelle(req.chatbot_id)
        context_messages = req.history[-max_ctx:]
    logs.append(f"🔍 Question original : {original_question}")
    clarified_question=original_question
    # --- Reformuler la question ---
    if  is_question_or_request(original_question):
        logs.append("Requête considéré comme demande")
        clarified_question = clarify_question(
            history=[{"role": m.role, "content": m.content} for m in context_messages],
            question=original_question
        )
        logs.append(f"🔍 Question clarifiée : {clarified_question}")
    else:
        logs.append("Requête non considéré comme demande, pas besoin de clarification")

    relevant_sources = ask_mixtral_for_relevant_sources(req.chatbot_id, clarified_question)
    if len(relevant_sources)==0:
        logs.append(f"Aucune source sélectionnée, peut-être que la description de la connexion n'est pas assez précis")
    else:
        logs.append(f"Sources utilisées : {relevant_sources}")
        
    documents_to_use = []
    connexions_to_use = []

    if isinstance(relevant_sources, str):
        try:
            relevant_sources = json.loads(relevant_sources)
        except Exception:
            relevant_sources = []

    for src in relevant_sources:
        if isinstance(src, dict):
            if src.get("type") == "document":
                documents_to_use.append(src["name"])
            elif src.get("type") == "connexion" or src.get("type")=="connection":
                connexions_to_use.append(src["name"])
    slot_values = {}
    slots_to_use = []

    for src in relevant_sources:
        if isinstance(src, dict) and src.get("type") == "slot":
            slots_to_use.append(src["name"])
    # --- Récupération des documents ---
    if documents_to_use:
        text_docs = retrieve_documents(
            client, COLLECTION_NAME, clarified_question, k=10, threshold=0, document_filter=documents_to_use,apply_contextual_filter=False)
        combined_docs.extend(text_docs)
        logs.append(f"Documents textes : {text_docs}")
        

    if connexions_to_use:
        connexion_docs = retrieve_documents(
            client, POSTGRESS_COLLECTION_NAME, clarified_question, k=10, threshold=0, document_filter=connexions_to_use,apply_contextual_filter=True)
        combined_docs.extend(connexion_docs)
        logs.append("Documents postgreSQL : " + json.dumps(connexion_docs, ensure_ascii=False, indent=2))
    if slots_to_use:
        all_slots = get_slots_for_chatbot(req.chatbot_id)
        # Crée une liste des colonnes à extraire (en fonction des slots sélectionnés)
        columns_to_extract = []
        for slot in all_slots:
            if slot["slot_name"] in slots_to_use:
                columns_to_extract.append(slot["columns"])
        if columns_to_extract:
            print(f"Colonnes à extraire : {columns_to_extract}")
            logs.append(f"Colonnes à extraire : {columns_to_extract}")
            slot_values = extract_slots_with_llm(clarified_question, columns_to_extract,slot_state)
            logs.append("Valeurs extraites des slots : " + json.dumps(slot_values, ensure_ascii=False))
    # --- Fallback si aucun doc ---
    if not req.chatbot_id and not combined_docs:
        combined_docs = retrieve_documents(client, COLLECTION_NAME, clarified_question, k=5)

    docs_text_only = [doc["text"] for doc in combined_docs]

    # --- Générer la réponse ---
    if slot_values:  # Vérifie si non vide
        combined_docs.append({"text": json.dumps(slot_values, ensure_ascii=False)})
    resp = generate_answer(clarified_question, combined_docs, req.chatbot_id)
    answer = resp.get("answer", "")
    generated_logs = resp.get("logs", [])
    logs.extend(generated_logs)  # Concaténation des logs
    if slot_values=={}:
        slot_values=slot_state
    return AnswerResponse(
        documents=docs_text_only,
        answer=answer,
        logs=logs,
        slot_state=slot_values  
    )

