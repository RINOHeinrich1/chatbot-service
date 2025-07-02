
---

## 🧠 1. Notions de base en NLP (Traitement du langage naturel)

### ✅ **Tokenization**

* Transformer une phrase en **tokens** (morceaux de mots ou mots).
* Ex: `"Paris est belle"` → `["Paris", "est", "belle"]` → puis en IDs numériques via le tokenizer.

### ✅ **Embeddings**

* Représentation numérique dense d’un texte, permettant de **comparer sémantiquement** deux textes.
* Exemple : `"Paris est en France"` ≈ `"La capitale de la France est Paris"` grâce à des embeddings proches.

### ✅ **Modèles pré-entraînés**

* `sentence-transformers/all-MiniLM-L6-v2` : génère des embeddings.
* `moussaKam/barthez` : génère du texte en français.

---

## 🔎 2. Recherche sémantique avec FAISS

### ✅ **FAISS (Facebook AI Similarity Search)**

* Librairie rapide pour faire de la recherche dans de grands ensembles vectoriels.
* Utile pour retrouver les documents **les plus proches** d’une requête.

### ✅ **Index FAISS**

* Structure de données optimisée pour retrouver rapidement les `k` documents les plus similaires.

### ✅ **Distance L2 / Cosine**

* Le code utilise `IndexFlatL2` = **distance euclidienne**.
* Plus la distance est petite, plus les phrases sont proches sémantiquement.

---

## ⚙️ 3. Génération de réponse (RAG)

### ✅ **RAG (Retrieval-Augmented Generation)**

* Pipeline **classique** :
  → Requête utilisateur → Recherche de documents → Génération de réponse à partir des documents.
* Tu guides le modèle de génération **uniquement avec le contexte extrait**.

### ✅ **Prompt engineering**

* Structure du prompt pour forcer le modèle à :

  * Ne **répondre qu’avec** le contexte.
  * Dire **"Je ne sais pas"** si ce n’est pas dans le contexte.

---

## 🧪 4. Optimisation et industrialisation

### ✅ **GPU / CPU**

* `torch.cuda.is_available()` permet d'utiliser un GPU si dispo, ce qui accélère l'inférence.

### ✅ **Cache d'embeddings**

* Pour éviter de recalculer les embeddings et l’index à chaque lancement → ils sont **sauvegardés sur disque**.

### ✅ **Cache de réponses**

* Tu utilises un `dict` Python (`cache`) pour éviter de générer deux fois la même réponse.

---

## 📚 5. Python & Bibliothèques

### 📦 `transformers` (Hugging Face)

* Pour le **tokenizer**, les **modèles de génération**, et les **pipelines** NLP.

### 📦 `datasets`

* Permet de manipuler des bases de données textuelles (ici, `knowledge_base`) facilement.

### 📦 `faiss`

* Pour indexer les embeddings et effectuer la recherche la plus rapide possible.

### 📦 `torch` (PyTorch)

* Pour manipuler les tensors, faire de l’inférence sur les modèles.

---

## 🧩 En résumé (connaissances clés)

| Domaine                  | Notions à savoir                                        |
| ------------------------ | ------------------------------------------------------- |
| **NLP**                  | Tokenizer, embeddings, modèles pré-entraînés            |
| **Vectorisation**        | Embeddings, distances, batch processing                 |
| **Recherche sémantique** | FAISS, Index, top-k, seuil de similarité                |
| **Génération**           | Prompt engineering, modèles seq2seq, pipeline text2text |
| **Optimisation**         | Cache, GPU vs CPU, sauvegarde de l’index                |
| **Python/Librairies**    | `transformers`, `datasets`, `faiss`, `torch`            |

---
