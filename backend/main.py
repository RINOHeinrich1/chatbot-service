from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
from fastapi import Request
from fastapi.responses import JSONResponse
import os
import shutil
import tempfile
import json
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


def get_connexions_for_chatbot(chatbot_id: str):
    response = supabase.table("chatbot_pgsql_connexions") \
                       .select("connexion_name, description") \
                       .eq("chatbot_id", chatbot_id) \
                       .execute()
    return response.data or []

def get_documents_for_chatbot(chatbot_id: str):
    response = supabase.table("chatbot_document_association") \
                       .select("document_name, description") \
                       .eq("chatbot_id", chatbot_id) \
                       .execute()
    return response.data or []
TOKEN = os.getenv("AI_API_TOKEN")
PRODUCT_ID = os.getenv("AI_PRODUCT_ID")
URL = f"https://api.infomaniak.com/1/ai/{PRODUCT_ID}/openai/chat/completions"
def ask_mixtral_for_relevant_sources(chatbot_id: str, question: str):
    connexions = get_connexions_for_chatbot(chatbot_id)
    documents = get_documents_for_chatbot(chatbot_id)

    sources = []

    for c in connexions:
        sources.append({
            "type": "connexion",
            "name": c["connexion_name"],
            "description": c["description"]
        })

    for d in documents:
        sources.append({
            "type": "document",
            "name": d["document_name"],
            "description": d["description"]
        })
    print(sources)
    mixtral_prompt = (
        "Tu es un assistant intelligent va sélectionner les sources les plus pertinentes pour répondre à une question.\n"
        "Voici la question posée par l'utilisateur :\n"
        f"{question}\n\n"
        "Voici la liste des sources disponibles (documents et connexions) avec leurs descriptions :\n"
        f"{json.dumps(sources, ensure_ascii=False)}\n\n"
        f"Réponds uniquement avec une liste JSON au format suivant :\n"
        "[{\"type\": \"document\" | \"connexion\", \"name\": \"nom_de_la_source\"}, ...]\n"
        "Ne fais aucun commentaire, ne donne aucune explication. "
        "Tu dois obligatoirement choisir un parmis les sources"

    )



    messages = [
        {"role": "system", "content": "Tu es un assistant intelligent qui sélectionne les sources pertinentes."},
        {"role": "user", "content": mixtral_prompt}
    ]

    payload = {
        "model": "mixtral",
        "messages": messages,
        "temperature": 0.5,
        "max_tokens": 300,
    }

    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    }

    response = requests.post(URL, headers=headers, data=json.dumps(payload))
    response.raise_for_status()

    result = response.json()["choices"][0]["message"]["content"].strip()

    try:
        # On tente de parser comme JSON directement
        sources_selected = json.loads(result)
    except Exception:
        # Sinon on renvoie le texte brut
        sources_selected = result

    return sources_selected


@app.post("/ask", response_model=AnswerResponse)
def ask_question(req: QuestionRequest):
    question = req.question
    combined_docs = []

    relevant_sources = ask_mixtral_for_relevant_sources(req.chatbot_id, req.question)
    print("🔎 Sources sélectionnées :", relevant_sources)

    # --- Séparation des sources documents / connexions ---
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
            elif src.get("type") == "connexion":
                connexions_to_use.append(src["name"])

    # --- Recherche documentaire vectorielle via Qdrant ---
    if documents_to_use:
        docs_classic = retrieve_documents(
            client=client,
            collection_name=os.getenv("COLLECTION_NAME"),
            query=question,
            k=100,
            threshold=0,
            document_filter=documents_to_use
        )
        combined_docs.extend(docs_classic)

    if connexions_to_use:
        docs_pgsql = retrieve_documents(
            client=client,
            collection_name=os.getenv("POSTGRESS_COLLECTION_NAME"),
            query=question,
            k=100,
            threshold=0,
            document_filter=connexions_to_use
        )
        combined_docs.extend(docs_pgsql)

    # --- Mode fallback sans chatbot_id ---
    if not req.chatbot_id and not combined_docs:
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
        context_messages = req.history[-max_ctx:]

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
