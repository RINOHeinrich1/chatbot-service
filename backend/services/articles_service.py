# services/articles_service.py
import psycopg2
from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
import re

def get_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )

def format_tsquery(keywords: str) -> str:
    words = [w.strip() for w in keywords.split() if w.strip()]
    return " & ".join(words)

def search_articles(query: str):
    """
    Recherche hybride : par numéro et par contenu full-text.
    """
    numero_match = re.findall(r"Article\s*(\d+[-\d]*)", query, re.IGNORECASE)
    results = []

    conn = get_connection()
    with conn.cursor() as cur:
        # Recherche par numéro
        for num in numero_match:
            cur.execute(
                "SELECT numero_article, contenu FROM articles WHERE numero_article = %s",
                (num,),
            )
            row = cur.fetchone()
            if row:
                results.append({"numero_article": row[0], "contenu": row[1]})

        # Recherche par mots-clés si aucun résultat
        if not results:
            ts_query = format_tsquery(query)
            cur.execute(
                """
                SELECT numero_article, contenu 
                FROM articles 
                WHERE tsv_content @@ to_tsquery('french', %s)
                ORDER BY numero_article
                """,
                (ts_query,),
            )
            for r in cur.fetchall():
                results.append({"numero_article": r[0], "contenu": r[1]})

    conn.close()
    return results
