from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Optional, Union
from services.retrieval import retrieve_documents
from services.mixtral import ask_mixtral_for_relevant_sources, generate_answer,is_question_or_request
from services.clarifier import clarify_question
from utils.helpers import (
    get_connexions_for_chatbot,
    get_documents_for_chatbot,
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


class MessageHistory(BaseModel):
    role: str
    content: str

class QuestionRequest(BaseModel):
    question: str
    chatbot_id: Optional[str] = None
    history: Optional[List[MessageHistory]] = []

@router.post("/ask", response_model=AnswerResponse)
def ask_question(req: QuestionRequest):
    logs = []
    original_question = req.question
    combined_docs = []

    # --- Préparer l'historique contextuel ---
    context_messages = []
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

    # --- Récupération des documents ---
    if documents_to_use:
        text_docs = retrieve_documents(
            client, COLLECTION_NAME, clarified_question, k=10, threshold=0, document_filter=documents_to_use
        )
        combined_docs.extend(documents_docs)
        logs.append(f"Documents textes : {text_docs}")
        

    if connexions_to_use:
        connexion_docs = retrieve_documents(
            client, POSTGRESS_COLLECTION_NAME, clarified_question, k=10, threshold=0, document_filter=connexions_to_use
        )
        combined_docs.extend(connexion_docs)
        logs.append("Documents postgreSQL : " + json.dumps(connexion_docs, ensure_ascii=False, indent=2))

    # --- Fallback si aucun doc ---
    if not req.chatbot_id and not combined_docs:
        combined_docs = retrieve_documents(client, COLLECTION_NAME, clarified_question, k=5)

    docs_text_only = [doc["text"] for doc in combined_docs]

    # --- Générer la réponse ---
    resp = generate_answer(clarified_question, combined_docs, req.chatbot_id)
    answer = resp.get("answer", "")
    generated_logs = resp.get("logs", [])
    logs.extend(generated_logs)  # Concaténation des logs

    return AnswerResponse(
        documents=docs_text_only,
        answer=answer,
        logs=logs
    )
