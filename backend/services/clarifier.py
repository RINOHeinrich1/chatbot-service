# services/clarifier.py

from typing import List
from services.mixtral import call_llm

def clarify_question(history: List[dict], question: str) -> str:
    formatted_history = ""
    for msg in history:
        role = "Utilisateur" if msg["role"] == "user" else "Assistant"
        formatted_history += f"{role} : {msg['content'].strip()}\n"
    messages = [
    {"role": "system", "content": "Tu es un assistant spécialisé uniquement dans la reformulation des questions."},
    {"role": "user", "content": (
        "Voici l'historique de la conversation :\n"
        f"{formatted_history.strip()}\n\n"
        f"Et voici la question actuelle :\n{question.strip()}\n\n"
        "Reformule cette question en remplaçant uniquement les pronoms par les noms correspondants dans l'historique. "
        "Ne modifie aucun autre mot, surtout ne rajoute pas, ne supprime rien."
        "Ne traduit surtout pas des noms en d'autres langues"
        "Ne réponds pas à la question, ne donne pas d'explication, ne rajoute rien d'autre, "
        "retourne uniquement la question reformulée telle qu'elle doit être."
    )}
]

    clarified = call_llm("mixtral", messages)
    return clarified.strip()
