# routes/articles.py
from fastapi import APIRouter, HTTPException
import psycopg2
from psycopg2 import sql
from config import DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT

router = APIRouter(prefix="/articles", tags=["Articles"])

def get_connection():
    return psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT
    )

def format_tsquery(keywords: str) -> str:
    """
    Transforme une chaîne de mots-clés en requête PostgreSQL full-text.
    Exemple: "mariage divorce" -> "mariage & divorce"
    """
    words = [w.strip() for w in keywords.split() if w.strip()]
    return " & ".join(words)

# --- Route pour tous les articles ---
@router.get("/")
def get_articles():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT numero_article, contenu FROM articles ORDER BY numero_article;")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"numero_article": r[0], "contenu": r[1]} for r in rows]

# --- Route pour un article par numéro ---
@router.get("/{numero}")
def get_article(numero: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT numero_article, contenu FROM articles WHERE numero_article = %s;", (numero,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Article non trouvé")
    return {"numero_article": row[0], "contenu": row[1]}

# --- Route recherche dynamique par mots-clés ---
@router.get("/search/")
def search_articles(q: str):
    """
    Recherche des articles par mots-clés dynamiques
    Exemple: /articles/search/?q=mariage divorce
    """
    ts_query = format_tsquery(q)
    conn = get_connection()
    cur = conn.cursor()
    # Assure-toi que la colonne tsv_content existe et indexée
    cur.execute("""
        SELECT numero_article, contenu
        FROM articles
        WHERE tsv_content @@ to_tsquery('french', %s)
        ORDER BY numero_article
    """, (ts_query,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"numero_article": r[0], "contenu": r[1]} for r in rows]


def extract_slots(query: str):
    mots = query.split()
    sujet = mots[0] if mots else "inconnu"
    return {"sujet_principal": sujet}