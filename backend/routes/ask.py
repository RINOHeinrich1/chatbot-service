# app/routes/ask.py

from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Optional
from services.retrieval import retrieve_documents
from services.mixtral import ask_mixtral_for_relevant_sources, generate_answer
from services.clarifier import clarify_question  # <-- Import ajouté ici
from utils.helpers import (
    get_connexions_for_chatbot,
    get_documents_for_chatbot,
    get_memoire_contextuelle,
)
from qdrant_client import QdrantClient
from config import *

router = APIRouter()

client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)

# === Models ===

class AnswerResponse(BaseModel):
    documents: List[str]
    answer: str

class MessageHistory(BaseModel):
    role: str
    content: str

class QuestionRequest(BaseModel):
    question: str
    chatbot_id: Optional[str] = None
    history: Optional[List[MessageHistory]] = []


@router.post("/ask", response_model=AnswerResponse)
def ask_question(req: QuestionRequest):
    original_question = req.question
    combined_docs = []

    # === Préparer l'historique contextuel ===
    context_messages = []
    if req.chatbot_id and req.history:
        max_ctx = get_memoire_contextuelle(req.chatbot_id)
        context_messages = req.history[-max_ctx:]

    # === Reformuler la question ===
    clarified_question = clarify_question(
        history=[{"role": m.role, "content": m.content} for m in context_messages],
        question=original_question
    )
    print(f"🔍 Question clarifiée : {clarified_question}")

    # === Sélection des sources ===
    relevant_sources = ask_mixtral_for_relevant_sources(req.chatbot_id, clarified_question)
    print(f"Sources utilisées pour '{clarified_question}' : {relevant_sources}")

    documents_to_use = []
    connexions_to_use = []

    if isinstance(relevant_sources, str):
        try:
            import json
            relevant_sources = json.loads(relevant_sources)
        except Exception:
            relevant_sources = []

    for src in relevant_sources:
        if isinstance(src, dict):
            if src.get("type") == "document":
                documents_to_use.append(src["name"])
            elif src.get("type") == "connexion":
                connexions_to_use.append(src["name"])

    # === Récupération des documents ===
    if documents_to_use:
        combined_docs.extend(retrieve_documents(
            client, COLLECTION_NAME, clarified_question, k=10, threshold=0, document_filter=documents_to_use
        ))

    if connexions_to_use:
        combined_docs.extend(retrieve_documents(
            client, POSTGRESS_COLLECTION_NAME, clarified_question, k=10, threshold=0, document_filter=connexions_to_use
        ))

    # === Fallback si aucun doc
    if not req.chatbot_id and not combined_docs:
        combined_docs = retrieve_documents(client, COLLECTION_NAME, clarified_question, k=5)

    docs_text_only = [doc["text"] for doc in combined_docs]

    # === Générer la réponse ===
    answer = generate_answer(clarified_question, combined_docs, req.chatbot_id, context_messages)

    return AnswerResponse(documents=docs_text_only, answer=answer)
