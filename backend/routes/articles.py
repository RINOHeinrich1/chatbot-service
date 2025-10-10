# routes/articles.py
from fastapi import APIRouter, HTTPException
import psycopg2
from psycopg2 import sql
from config import DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT

router = APIRouter(prefix="/articles", tags=["Articles"])

def get_connection():
    """
    Retourne une connexion PostgreSQL.
    """
    try:
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        return conn
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur de connexion à la base : {str(e)}")

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
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT numero_article, contenu FROM articles ORDER BY numero_article;")
        rows = cur.fetchall()
        return [{"numero_article": r[0], "contenu": r[1]} for r in rows]
    finally:
        cur.close()
        conn.close()

# --- Route pour un article par numéro ---
@router.get("/{numero}")
def get_article(numero: str):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT numero_article, contenu FROM articles WHERE numero_article = %s;", (numero,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Article non trouvé")
        return {"numero_article": row[0], "contenu": row[1]}
    finally:
        cur.close()
        conn.close()

# --- Route recherche dynamique par mots-clés ---
@router.get("/search/")
def search_articles(q: str):
    """
    Recherche articles par mots-clés.
    1️⃣ Recherche stricte : tous les mots doivent être présents.
    2️⃣ Si aucun résultat, recherche tolérante : un mot au moins.
    Retourne maximum 5 articles.
    Le premier mot trouvé est considéré comme mot-clé principal.
    """
    mots = [w.strip() for w in q.split() if w.strip()]
    if not mots:
        return {"mot_cle": None, "articles": []}

    try:
        conn = get_connection()
        cur = conn.cursor()

        # --- Recherche stricte : tous les mots présents (AND) ---
        tsquery_strict = " & ".join(mots)  # mariage & code & civil
        cur.execute("""
            SELECT numero_article, contenu
            FROM articles
            WHERE tsv_content @@ to_tsquery('french', %s)
            ORDER BY numero_article
            LIMIT 5
        """, (tsquery_strict,))
        rows = cur.fetchall()

        # --- Si aucun résultat strict, recherche tolérante mot par mot (OR) ---
        if not rows:
            conditions = []
            params = []
            for mot in mots:
                conditions.append("contenu ILIKE %s OR tsv_content @@ plainto_tsquery('french', %s)")
                params.extend([f"%{mot}%", mot])
            sql_query = f"""
                SELECT numero_article, contenu
                FROM articles
                WHERE {" OR ".join(conditions)}
                ORDER BY numero_article
                LIMIT 5
            """
            cur.execute(sql_query, params)
            rows = cur.fetchall()

        results = [{"numero_article": r[0], "contenu": r[1]} for r in rows]

        # --- Détecter le premier mot-clé trouvé ---
        mot_cle = None
        for mot in mots:
            for r in results:
                if mot.lower() in r["contenu"].lower():
                    mot_cle = mot
                    break
            if mot_cle:
                break

        return {"mot_cle": mot_cle, "articles": results}

    finally:
        cur.close()
        conn.close()

# --- Slot extraction simple (optionnel) ---
def extract_slots(query: str):
    mots = query.split()
    sujet = mots[0] if mots else "inconnu"
    return {"sujet_principal": sujet}
