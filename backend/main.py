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
from rag.embedding import get_embedding  # <-- modèle SentenceTransformer à jour
from rag.rag_engine import retrieve_documents, generate_answer
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
# --- Schémas Pydantic ---
class QuestionRequest(BaseModel):
    question: str
    chatbot_id: Optional[str] = None  # si tu veux garder ce champ
    document_filter: Optional[List[str]]   # <-- nouveau champ

class AnswerResponse(BaseModel):
    documents: List[str]
    answer: str
    
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

@app.post("/ask", response_model=AnswerResponse)
def ask_question(req: QuestionRequest):
    question = req.question
    document_filter = get_document_names_from_chatbot(req.chatbot_id) or []
    docs = retrieve_documents(
        client=client,
        collection_name=collection_name,
        query=question,
        k=5,
        threshold=0,
        document_filter=document_filter  # <-- passe les documents à filtrer
    )
    answer = generate_answer(question, docs,req.chatbot_id)
    return AnswerResponse(documents=docs, answer=answer)

# --- Mode CLI (facultatif) ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8010, reload=True)
