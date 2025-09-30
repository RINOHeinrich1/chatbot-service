# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes.ask import router as ask_router
from routes.articles import router as articles_router  # ✅ importer le nouveau router

from config import *
import psycopg2
from services.mixtral import generate_answer_with_slots

app = FastAPI(title="RAG API")

# CORS (à adapter pour la prod)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inclusions de routes
app.include_router(ask_router)
app.include_router(articles_router)   # ✅  les routes d'articles

# Pour lancement direct
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8010, reload=True)