import requests
import numpy as np

API_URL = "https://madachat-embedder.hf.space/embed"

def get_embedding(texts):
    payload = {
        "texts": texts,
        "model":"",
    }

    try:
        response = requests.post(API_URL, json=payload)
        response.raise_for_status()  # lève une exception si erreur HTTP
        embeddings = response.json()["embeddings"]
        return np.array(embeddings)
    except Exception as e:
        print(f"❌ Erreur lors de l'appel à l'API d'embedding : {e}")
        return None
