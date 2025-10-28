# routes/articles.py
from fastapi import APIRouter, HTTPException
import psycopg2
from config import DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT

router = APIRouter(prefix="/articles", tags=["Articles"])


# --- Connexion à la base ---
def get_connection():
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


# --- Route pour tous les articles ---
@router.get("/")
def get_articles():
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT numero, contenu FROM articles ORDER BY numero;")
        rows = cur.fetchall()
        return [{"numero": r[0], "contenu": r[1]} for r in rows]
    finally:
        cur.close()
        conn.close()


# --- Route pour un article spécifique ---
@router.get("/{numero}")
def get_article(numero: str):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT numero, contenu FROM articles WHERE numero = %s;", (numero,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Article non trouvé")
        return {"numero": row[0], "contenu": row[1]}
    finally:
        cur.close()
        conn.close()


# --- Route recherche dynamique (avec stemming et tolérance) ---
@router.get("/search/")
def search_articles(q: str):
    """
    Recherche un article par mot-clé (avec formes similaires).
    Exemples :
      - "enfants" trouve aussi "enfant"
      - "mariages" trouve aussi "mariage"
    """
    if not q or not q.strip():
        return {"mot_cle": None, "articles": []}

    try:
        conn = get_connection()
        cur = conn.cursor()

        mots = [w.strip() for w in q.split() if w.strip()]
        query_text = " & ".join(mots)

        # 1️⃣ Recherche full-text PostgreSQL avec dictionnaire français
        cur.execute("""
            SELECT numero, contenu
            FROM articles
            WHERE to_tsvector('french', contenu) @@ to_tsquery('french', %s)
            ORDER BY numero
            LIMIT 5;
        """, (query_text,))
        rows = cur.fetchall()

        # 2️⃣ Si aucun résultat, recherche souple avec ILIKE
        if not rows:
            conditions = []
            params = []
            for mot in mots:
                conditions.append("contenu ILIKE %s")
                params.append(f"%{mot}%")
            sql_query = f"""
                SELECT numero, contenu
                FROM articles
                WHERE {" OR ".join(conditions)}
                ORDER BY numero
                LIMIT 5;
            """
            cur.execute(sql_query, params)
            rows = cur.fetchall()

        results = [{"numero": r[0], "contenu": r[1]} for r in rows]
        mot_cle = mots[0] if mots else None

        return {"mot_cle": mot_cle, "articles": results}

    finally:
        cur.close()
        conn.close()
