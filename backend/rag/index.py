import faiss
import numpy as np
import os
from rag.embedding import get_embedding

EMB_FILE = "embeddings/embeddings.npy"
INDEX_FILE = "embeddings/faiss.index"

def build_or_load_index(dataset):
    if os.path.exists(EMB_FILE) and os.path.exists(INDEX_FILE):
        print("🔄 Chargement des embeddings et de l'index FAISS depuis disque...")
        embeddings = np.load(EMB_FILE)
        index = faiss.read_index(INDEX_FILE)
    else:
        print("⚙️ Génération des embeddings et de l'index FAISS...")
        texts = dataset["texte"]
        embeddings = get_embedding(texts)
        os.makedirs("embeddings", exist_ok=True)
        np.save(EMB_FILE, embeddings)

        dimension = embeddings.shape[1]
        index = faiss.IndexFlatL2(dimension)
        index.add(embeddings)
        faiss.write_index(index, INDEX_FILE)
    return index

def build_faiss_index(embeddings: np.ndarray):
    """
    Construit un index FAISS à partir des embeddings fournis.

    Args:
        embeddings (np.ndarray): Matrice (N x D) des embeddings normalisés (float32).

    Returns:
        faiss.IndexFlatIP: Index FAISS basé sur le produit scalaire (inner product).
    """
    d = embeddings.shape[1]  # dimension des embeddings
    index = faiss.IndexFlatIP(d)  # produit scalaire (inner product) = cosine similarity si embeddings normalisés
    index.add(embeddings)
    return index