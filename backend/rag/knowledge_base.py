from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue
from datasets import Dataset
import pandas as pd
import os
from dotenv import load_dotenv

load_dotenv()

# Connexion au client Qdrant
client = QdrantClient(
    url=os.getenv("QDRANT_URL"),
    api_key=os.getenv("QDRANT_API_KEY"),
)

COLLECTION = os.getenv("COLLECTION_NAME")

def load_knowledge_base():
    # Récupérer tous les points avec pagination (si besoin)
    all_points = []
    offset = None

    while True:
        result = client.scroll(
            collection_name=COLLECTION,
            limit=100,
            offset=offset,
            with_payload=True,
        )
        points, next_offset = result
        all_points.extend(points)
        if not next_offset:
            break
        offset = next_offset

    # Extraire les champs de texte
    texts = [pt.payload.get("text") for pt in all_points if "text" in pt.payload]

    # Créer un dataset Hugging Face
    return Dataset.from_pandas(pd.DataFrame({"texte": texts}))
