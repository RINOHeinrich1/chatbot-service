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
import faiss
import zipfile
from rag.embedding import get_embedding  # <-- modèle SentenceTransformer à jour
from rag.index import build_or_load_index,get_embedding,EMB_FILE,INDEX_FILE
from rag.rag_engine import retrieve_documents, generate_answer
from qdrant_client import QdrantClient
from typing import Optional
from qdrant_client.models import Filter, FieldCondition, MatchValue
from dotenv import load_dotenv
load_dotenv()

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
collection_name=os.getenv("COLLECTION_NAME")
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

@app.post("/ask", response_model=AnswerResponse)
def ask_question(req: QuestionRequest):
    question = req.question
    document_filter = req.document_filter or []
    print(f"DOCUMENT FILTER: {document_filter}")
    docs = retrieve_documents(
        client=client,
        collection_name=collection_name,
        query=question,
        k=5,
        threshold=0,
        document_filter=document_filter  # <-- passe les documents à filtrer
    )
    answer = generate_answer(question, docs)
    return AnswerResponse(documents=docs, answer=answer)

# --- Mode CLI (facultatif) ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8010, reload=True)
