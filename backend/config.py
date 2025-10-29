# app/config.py
import os
from dotenv import load_dotenv
from supabase import create_client


load_dotenv()

# --- Supabase (Existant) ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")

# --- Qdrant & Postgres (Existant) ---
QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
COLLECTION_NAME = os.getenv("COLLECTION_NAME")
POSTGRESS_COLLECTION_NAME = os.getenv("POSTGRESS_COLLECTION_NAME")
POSTGRESS_SQL_EXECUTOR = os.getenv("POSTGRESS_SQL_EXECUTOR", "https://postgresvectorizer.onirtech.com/execute")

# --- AI Service (Existant - Mixtral via Infomaniak) ---
AI_TOKEN = os.getenv("AI_API_TOKEN")
AI_PRODUCT_ID = os.getenv("AI_PRODUCT_ID")
# Construction de l'URL réelle de l'API Infomaniak
AI_URL = f"https://api.infomaniak.com/1/ai/{AI_PRODUCT_ID}/openai/chat/completions"
AI_MODEL = "mixtral" # Modèle par défaut

# --- NOUVEAU : Constantes Judilibre ---
# (Chargées depuis votre fichier .env)
JUDILIBRE_CLIENT_ID = os.getenv("JUDILIBRE_CLIENT_ID")
JUDILIBRE_CLIENT_SECRET = os.getenv("JUDILIBRE_CLIENT_SECRET")
JUDILIBRE_AUTH_URL = "https://sandbox-oauth.piste.gouv.fr/api/oauth/token"
JUDILIBRE_API_BASE_URL = "https://sandbox-api.piste.gouv.fr/cassation/judilibre/v1.0"
JUDILIBRE_PAGE_SIZE = 5 # Nombre de résultats à analyser

# --- DB Locale (Existant) ---
DB_NAME = os.getenv("DB_NAME", "madachat")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")

WEB_ACTION_URL = "http://127.0.0.1:8000/articles/search/"

import os
import psycopg2

def get_connection(dbname: str = None):
    """
    Retourne une connexion PostgreSQL
    """
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=dbname or DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )