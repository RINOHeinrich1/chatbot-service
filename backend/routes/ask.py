from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Optional, Union
from services.retrieval import retrieve_documents
from services.mixtral import ask_mixtral_for_relevant_sources, generate_answer
from services.clarifier import clarify_question
from utils.helpers import (
    get_connexions_for_chatbot,
    get_documents_for_chatbot,
    get_memoire_contextuelle,
)
from qdrant_client import QdrantClient
from config import *

router = APIRouter()

client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)

class Reasoning(BaseModel):
    sources: List[str]
    sql: Optional[str] = None

class AnswerResponse(BaseModel):
    documents: List[str]
    answer: str
    reasoning: Optional[Reasoning] = None  # maintenant un objet

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

    # --- Préparer l'historique contextuel ---
    context_messages = []
    if req.chatbot_id and req.history:
        max_ctx = get_memoire_contextuelle(req.chatbot_id)
        context_messages = req.history[-max_ctx:]

    # --- Reformuler la question ---
    clarified_question = clarify_question(
        history=[{"role": m.role, "content": m.content} for m in context_messages],
        question=original_question
    )
    print(f"🔍 Question clarifiée : {clarified_question}")

    # --- Sélection des sources ---
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

    # --- Récupération des documents ---
    if documents_to_use:
        combined_docs.extend(retrieve_documents(
            client, COLLECTION_NAME, clarified_question, k=10, threshold=0, document_filter=documents_to_use
        ))

    if connexions_to_use:
        combined_docs.extend(retrieve_documents(
            client, POSTGRESS_COLLECTION_NAME, clarified_question, k=10, threshold=0, document_filter=connexions_to_use
        ))

    # --- Fallback si aucun doc ---
    if not req.chatbot_id and not combined_docs:
        combined_docs = retrieve_documents(client, COLLECTION_NAME, clarified_question, k=5)

    docs_text_only = [doc["text"] for doc in combined_docs]

    # --- Générer la réponse ---
    resp = generate_answer(clarified_question, combined_docs, req.chatbot_id)
    answer = resp.get("answer", "")

    # Construire reasoning sous forme d'objet
    sources_list = [src['name'] for src in relevant_sources if isinstance(src, dict)]
    sql_doc = next((doc for doc in combined_docs if doc.get("source") == "résultat_sql"), None)

    sql_line = None
    if sql_doc:
        lines = sql_doc["text"].splitlines()
        try:
            # Trouver l'indice de la ligne qui contient "Code SQL :"
            start_idx = next(i for i, l in enumerate(lines) if l.startswith("Code SQL :"))
        except StopIteration:
            start_idx = None

        if start_idx is not None:
            # Extraire tout ce qui suit sur les lignes suivantes
            # On enlève la partie "Code SQL : " sur la première ligne, puis on concatène le reste
            sql_lines = [lines[start_idx][len("Code SQL : "):].strip()]  # ligne de départ sans le préfixe
            sql_lines += lines[start_idx + 1 :]  # les lignes suivantes

            # Optionnel : supprimer les lignes vides au début et à la fin
            while sql_lines and sql_lines[0].strip() == "":
                sql_lines.pop(0)
            while sql_lines and sql_lines[-1].strip() == "":
                sql_lines.pop()

            sql_query = "\n".join(sql_lines)
            sql_line = sql_query


    reasoning_obj = Reasoning(
        sources=sources_list,
        sql=sql_line
    )

    return AnswerResponse(
        documents=docs_text_only,
        answer=answer,
        reasoning=reasoning_obj
    )
