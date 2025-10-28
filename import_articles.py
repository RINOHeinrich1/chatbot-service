import os
import re
import psycopg2
from psycopg2 import sql
from backend.config import *

# Regex
ARTICLE_PATTERN = re.compile(r'^Article\s+[A-Z]?\d+(?:-\d+)*', re.IGNORECASE)
AMENDE_PATTERN = re.compile(r'(\d+(?:\s?\d{3})*)\s*€\s*d\'amende', re.IGNORECASE)


# ---------------------------------------------------------
#  🔗 Connexion
# ---------------------------------------------------------
def get_connection(dbname: str = None):
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=dbname or DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )


# ---------------------------------------------------------
#  🧹 Nettoyage du contenu
# ---------------------------------------------------------
def nettoyer_contenu(contenu: str) -> str:
    return AMENDE_PATTERN.sub("", contenu).strip()


# ---------------------------------------------------------
#  🗄️ Création de la base et des tables
# ---------------------------------------------------------
def create_database():
    """Crée la base de données si elle n'existe pas"""
    conn = get_connection("madachat")
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,))
        if not cur.fetchone():
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DB_NAME)))
            print(f"✅ Base de données '{DB_NAME}' créée")
        else:
            print(f"✅ Base de données '{DB_NAME}' existe déjà")
    conn.close()


def create_tables(conn):
    """Crée les tables conformes au schéma Go"""
    with conn.cursor() as cur:
        # --- Table categories ---
        cur.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id SERIAL PRIMARY KEY,
                nom TEXT UNIQUE NOT NULL
            );
        """)

        # --- Table articles ---
        cur.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id BIGSERIAL PRIMARY KEY,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                deleted_at TIMESTAMPTZ,
                code TEXT,
                livre TEXT,
                titre TEXT,
                chapitre TEXT,
                section TEXT,
                numero TEXT NOT NULL,
                contenu TEXT NOT NULL,
                mots_cles TEXT,
                categories TEXT,
                categorie_id INTEGER REFERENCES categories(id),
                UNIQUE (code, numero)
            );
        """)

        # Index pour recherche
        cur.execute("CREATE INDEX IF NOT EXISTS idx_article_numero ON articles (numero);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_article_fts ON articles USING GIN (to_tsvector('french', contenu));")

        conn.commit()
        print("✅ Tables 'articles' et 'categories' créées / mises à jour.")


# ---------------------------------------------------------
#  🧠 Détection automatique de la catégorie
# ---------------------------------------------------------
def detecter_categorie(contenu, conn):
    contenu_lower = contenu.lower()
    mapping = {
        "Crimes": ["meurtre", "assassinat", "viol", "homicide"],
        "Délits": ["vol", "escroquerie", "abus", "agression"],
        "Contraventions": ["stationnement", "tapage", "contravention"],
        "Droit de la famille": ["mariage", "divorce", "pacs", "époux"],
        "Droit des biens": ["propriété", "possession", "usufruit", "immobilier"],
        "Droit des obligations": ["contrat", "convention", "engagement", "obligation"],
        "Responsabilité civile": ["dommage", "réparation", "responsabilité"],
        "Droit des successions et donations": ["héritage", "succession", "donation"]
    }

    for categorie, mots in mapping.items():
        if any(mot in contenu_lower for mot in mots):
            with conn.cursor() as cur:
                # Crée la catégorie si elle n'existe pas
                cur.execute("""
                    INSERT INTO categories (nom)
                    VALUES (%s)
                    ON CONFLICT (nom) DO NOTHING;
                """, (categorie,))
                conn.commit()

                cur.execute("SELECT id FROM categories WHERE nom = %s", (categorie,))
                row = cur.fetchone()
                if row:
                    return row[0]

    # Défaut : Délits
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO categories (nom)
            VALUES ('Délits')
            ON CONFLICT (nom) DO NOTHING;
        """)
        conn.commit()
        cur.execute("SELECT id FROM categories WHERE nom = 'Délits'")
        row = cur.fetchone()
        return row[0] if row else None


# ---------------------------------------------------------
#  📂 Importation des articles
# ---------------------------------------------------------
def insert_articles_from_folder(root_folder):
    create_database()
    conn = get_connection()
    create_tables(conn)

    with conn.cursor() as cur:
        for root, _, files in os.walk(root_folder):
            for filename in files:
                if not filename.endswith(".md"):
                    continue

                file_path = os.path.join(root, filename)
                with open(file_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()

                if not lines:
                    continue

                first_line = lines[0].strip()
                if not ARTICLE_PATTERN.match(first_line):
                    print(f"⚠️ Format ignoré : {first_line} dans {filename}")
                    continue

                numero_article = first_line
                contenu = nettoyer_contenu("".join(lines[1:]).strip())
                categorie_id = detecter_categorie(contenu, conn)

                cur.execute("""
                    INSERT INTO articles (
                        code, livre, titre, chapitre, section, numero, contenu, mots_cles, categories, categorie_id, created_at, updated_at
                    )
                    VALUES (NULL, NULL, NULL, NULL, NULL, %s, %s, NULL, NULL, %s, NOW(), NOW())
                    ON CONFLICT (code, numero)
                    DO UPDATE SET
                        contenu = EXCLUDED.contenu,
                        categorie_id = EXCLUDED.categorie_id,
                        updated_at = NOW();
                """, (numero_article, contenu, categorie_id))

                print(f"✅ Article importé / mis à jour : {numero_article}")

        conn.commit()
    conn.close()


# ---------------------------------------------------------
#  🚀 Exécution principale
# ---------------------------------------------------------
if __name__ == "__main__":
    insert_articles_from_folder("./france.code-penal-master/")
    print("✅ Import terminé !")
