from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
from fastapi import Request
from fastapi.responses import JSONResponse
import os
import shutil
import tempfile
import requests
import numpy as np
import zipfile
from core.retrieval import retrieve_documents
from core.agent import generate_answer
from qdrant_client import QdrantClient
from typing import Optional
from supabase import create_client
from qdrant_client.models import Filter, FieldCondition, MatchValue
from dotenv import load_dotenv
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
collection_name = os.getenv("COLLECTION_NAME")
# --- Initialisation de l'application ---
app = FastAPI(title="RAG API")

# Autoriser le frontend React (localhost:3000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class AnswerResponse(BaseModel):
    documents: List[str]
    answer: str

class MessageHistory(BaseModel):
    role: str  # "user" ou "assistant"
    content: str

class QuestionRequest(BaseModel):
    question: str
    chatbot_id: Optional[str] = None
    history: Optional[List[MessageHistory]] = []  # 👈 nouveau champ

client = QdrantClient(
    url=os.getenv("QDRANT_URL"),
    api_key=os.getenv("QDRANT_API_KEY"),
)

# --- Route principale ---
def get_document_names_from_chatbot(chatbot_id: str) -> List[str]:
    response = supabase.table("chatbot_document_association") \
        .select("document_name") \
        .eq("chatbot_id", chatbot_id) \
        .execute()

    if not response.data:
        return []

    return [item["document_name"] for item in response.data]

def get_pgsql_sources_from_chatbot(chatbot_id: str) -> List[str]:
    response = supabase.table("chatbot_pgsql_connexions") \
        .select("connexion_name") \
        .eq("chatbot_id", chatbot_id) \
        .execute()

    if not response.data:
        return []

    return [f"{item['connexion_name']}" for item in response.data]

def get_memoire_contextuelle(chatbot_id: str) -> int:
    response = supabase.table("chatbots") \
        .select("memoire_contextuelle") \
        .eq("id", chatbot_id) \
        .single() \
        .execute()

    if not response.data:
        return 0  # valeur par défaut si absent

    return int(response.data.get("memoire_contextuelle", 0))

@app.post("/ask", response_model=AnswerResponse)
def ask_question(req: QuestionRequest):
    question = req.question
    combined_docs = []

    if req.chatbot_id:
        document_names = get_document_names_from_chatbot(req.chatbot_id)
        print(document_names)
        if document_names:
            docs_classic = retrieve_documents(
                client=client,
                collection_name=os.getenv("COLLECTION_NAME"),
                query=question,
                k=5,
                threshold=0,
                document_filter=document_names
            )
            combined_docs.extend(docs_classic)
        print(combined_docs)
        pgsql_sources = get_pgsql_sources_from_chatbot(req.chatbot_id)
        if pgsql_sources:
            docs_pgsql = retrieve_documents(
                client=client,
                collection_name=os.getenv("POSTGRESS_COLLECTION_NAME"),
                query=question,
                k=5,
                threshold=0,
                document_filter=pgsql_sources
            )
            combined_docs.extend(docs_pgsql)

    if not req.chatbot_id:
        print("trueeeeeee")
        combined_docs = retrieve_documents(
            client=client,
            collection_name=os.getenv("COLLECTION_NAME"),
            query=question,
            k=5,
            threshold=0,
            document_filter=[]
        )

    docs_text_only = [doc["text"] for doc in combined_docs]

    # === Appliquer memoire_contextuelle ===
    context_messages = []
    if req.chatbot_id and req.history:
        max_ctx = get_memoire_contextuelle(req.chatbot_id)
        context_messages = req.history[-max_ctx:]  # garder les derniers messages uniquement

    # === Génération de la réponse ===
    answer = generate_answer(
        query=question,
        docs=combined_docs,
        chatbot_id=req.chatbot_id,
        history=context_messages
    )


    return AnswerResponse(documents=docs_text_only, answer=answer)

# --- Mode CLI (facultatif) ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8010, reload=True)
