from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Import des routes existantes
from routes.ask import router as ask_router
from routes.articles import router as articles_router 

# --- NOUVEAUTÉ : Import de la route Judilibre ---
from routes.judilibre_route import router as judilibre_router 
# ------------------------------------------------

from config import *
import psycopg2

app = FastAPI(title="RAG API")

# CORS (à adapter pour la prod)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ask_router)
app.include_router(articles_router)
app.include_router(judilibre_router)

# Pour lancement direct
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8010, reload=True)