from typing import List
from services.mixtral import call_llm,is_question_or_request

def clarify_question(history: List[dict], question: str) -> str:
    formatted_history = ""
    for msg in history:
        role = "Utilisateur" if msg["role"] == "user" else "Assistant"
        formatted_history += f"{role} : {msg['content'].strip()}\n"

    messages = [
        {
            "role": "system",
            "content": (
                "Tu es un assistant dont le seul rôle est de resoudre les coréférences dans les phrases de demandes  en français.\n"
                "Dans la reformulation, remplace tous les pronoms et référence (comme « il », « elle », « cela », « le dernier » etc.) par les noms ou entités correspondants présents dans l'historique de la conversation, Sauf pour le pronom **tu**\n"
                "Ne réponds jamais à la question. Ne donne pas d’explication. N’ajoute aucun commentaire ou information supplémentaire."
            )
        },
        {
            "role": "user",
            "content": (
                "Historique de la conversation :\n"
                f"{formatted_history.strip()}\n\n"
                "Message à reformuler :\n"
                f"{question.strip()}"
            )
        }
    ]

    clarified = call_llm("mixtral", messages)
    return clarified.strip()
