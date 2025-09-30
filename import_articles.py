import os
import re
import psycopg2
from psycopg2 import sql

# --- Paramètres de connexion PostgreSQL ---
DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = os.getenv("POSTGRES_PORT", "5432")
DB_NAME = os.getenv("POSTGRES_DB", "madachat")
DB_USER = os.getenv("POSTGRES_USER", "postgres")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")

# Regex
ARTICLE_PATTERN = re.compile(r'^Article\s+[A-Z]?\d+(?:-\d+)*', re.IGNORECASE)
AMENDE_PATTERN = re.compile(r'(\d+(?:\s?\d{3})*)\s*€\s*d\'amende', re.IGNORECASE)

def get_connection(dbname: str = None):
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=dbname or DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )

def nettoyer_contenu(contenu: str) -> str:
    return AMENDE_PATTERN.sub("", contenu).strip()

def create_database():
    """Crée la base de données si elle n'existe pas"""
    conn = get_connection("postgres")
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
    """Crée ou met à jour les tables existantes avec recherche full-text"""
    with conn.cursor() as cur:
        # Table catégories
        cur.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id SERIAL PRIMARY KEY,
                nom VARCHAR(100) NOT NULL UNIQUE,
                code_type VARCHAR(50) NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Table articles avec colonne tsvector pour recherche full-text
        cur.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id SERIAL PRIMARY KEY,
                numero_article VARCHAR(100) NOT NULL UNIQUE,
                contenu TEXT,
                categorie_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
                search_vector tsvector,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Créer un index GIN sur la colonne search_vector pour recherche rapide
        cur.execute("CREATE INDEX IF NOT EXISTS idx_articles_search ON articles USING GIN(search_vector)")

        # Mise à jour des catégories
        categories_base = [
            ("Crimes", "pénal"), ("Délits", "pénal"), ("Contraventions", "pénal"),
            ("Droit pénal général", "pénal"), ("Droit pénal spécial", "pénal"),
            ("Droit pénal des affaires", "pénal"), ("Droit pénal de l'environnement", "pénal"),
            ("Droit pénal social", "pénal"), ("Procédure pénale", "pénal"),
            ("Droit des personnes", "civil"), ("Droit de la famille", "civil"),
            ("Droit des biens", "civil"), ("Droit des obligations", "civil"),
            ("Droit des contrats", "civil"), ("Responsabilité civile", "civil"),
            ("Droit des successions et donations", "civil"), ("Droit des sûretés", "civil"),
            ("Droit de la consommation", "civil"), ("Droit des assurances", "civil"),
            ("Droit de la propriété intellectuelle", "civil"), ("Droit immobilier", "civil"),
            ("Procédure civile", "civil")
        ]
        for nom, code_type in categories_base:
            cur.execute("""
                INSERT INTO categories (nom, code_type)
                VALUES (%s, %s)
                ON CONFLICT (nom)
                DO UPDATE SET code_type = EXCLUDED.code_type
            """, (nom, code_type))
        conn.commit()

def detecter_categorie(contenu, conn):
    """Détecte la catégorie via mots-clés"""
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
                cur.execute("SELECT id FROM categories WHERE nom = %s", (categorie,))
                row = cur.fetchone()
                if row:
                    return row[0]
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM categories WHERE nom = %s", ("Délits",))
        row = cur.fetchone()
        return row[0] if row else None

def insert_articles_from_folder(root_folder):
    """Insère ou met à jour tous les articles .md avec search_vector"""
    create_database()
    conn = get_connection()
    create_tables(conn)

    with conn.cursor() as cur:
        for root, dirs, files in os.walk(root_folder):
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
                contenu = "".join(lines[1:]).strip()
                contenu = nettoyer_contenu(contenu)
                categorie_id = detecter_categorie(contenu, conn)

                # Création du search_vector pour full-text search
                cur.execute("""
                    INSERT INTO articles (numero_article, contenu, categorie_id, search_vector)
                    VALUES (%s, %s, %s, to_tsvector('french', %s))
                    ON CONFLICT (numero_article)
                    DO UPDATE SET
                        contenu = EXCLUDED.contenu,
                        categorie_id = EXCLUDED.categorie_id,
                        search_vector = to_tsvector('french', EXCLUDED.contenu),
                        updated_at = CURRENT_TIMESTAMP
                """, (numero_article, contenu, categorie_id, contenu))
                print(f"✅ Article importé / mis à jour : {numero_article} (catégorie: {categorie_id})")
        conn.commit()
    conn.close()

if __name__ == "__main__":
    insert_articles_from_folder("./france.code-penal-master/")
    print("✅ Import terminé !")