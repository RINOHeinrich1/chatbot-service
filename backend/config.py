# app/config.py
import os
from dotenv import load_dotenv
from supabase import create_client


load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
COLLECTION_NAME = os.getenv("COLLECTION_NAME")
POSTGRESS_COLLECTION_NAME = os.getenv("POSTGRESS_COLLECTION_NAME")
AI_TOKEN = os.getenv("AI_API_TOKEN")
AI_PRODUCT_ID = os.getenv("AI_PRODUCT_ID")
AI_URL = f"https://api.infomaniak.com/1/ai/{AI_PRODUCT_ID}/openai/chat/completions"
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
POSTGRESS_SQL_EXECUTOR = os.getenv("POSTGRESS_SQL_EXECUTOR", "https://postgresvectorizer.onirtech.com/execute")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")