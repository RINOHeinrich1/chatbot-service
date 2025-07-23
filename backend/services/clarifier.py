# services/clarifier.py

from typing import List
from services.mixtral import call_llm

def clarify_question(history: List[dict], question: str) -> str:
    formatted_history = ""
    for msg in history:
        role = "Utilisateur" if msg["role"] == "user" else "Assistant"
        formatted_history += f"{role} : {msg['content'].strip()}\n"

    messages = [
        {"role": "system", "content": "Tu es un assistant qui reformule une question en la rendant claire, complète et explicite."},
        {"role": "user", "content": (
            "Voici l'historique de la conversation :\n"
            f"{formatted_history.strip()}\n\n"
            f"Et voici la question actuelle :\n{question.strip()}\n\n"
            "Reformule cette question pour qu'elle soit claire et complète, sans ambiguïté. "
            "Si elle contient des pronoms ou références implicites, remplace-les par leur forme explicite."
        )}
    ]

    clarified = call_llm("mixtral", messages)
    return clarified.strip()
