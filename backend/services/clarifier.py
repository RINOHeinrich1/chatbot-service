from typing import List
from services.mixtral import call_llm, is_question_or_request

def clarify_question(history: List[dict], question: str) -> str:
    formatted_history = ""
    for msg in history:
        role = "Utilisateur" if msg["role"] == "user" else "Assistant"
        formatted_history += f"{role} : {msg['content'].strip()}\n"

    messages = [
        {
            "role": "system",
            "content": (
                "Tu es un assistant intelligent qui travaille exclusivement en **français**.\n"
                "Ton seul rôle est de **résoudre les coréférences** dans les phrases de demandes.\n"
                "Tu dois **remplacer tous les pronoms et expressions référentielles** "
                "(comme « il », « elle », « cela », « ce dernier », « le même », etc.) "
                "par les noms ou entités correspondants présents dans l'historique de la conversation.\n\n"
                "⚠️ Ne remplace **jamais** les pronoms de première et deuxième personne "
                "comme **je**, **tu**, **nous**, **vous**, même s'ils semblent faire référence à l'utilisateur ou à l'assistant.\n\n"
                "Ne réponds jamais à la question. Ne donne pas d’explication. N’ajoute aucun commentaire.\n"
                "Réponds uniquement par la phrase reformulée avec les coréférences résolues.\n\n"
                "👉 Ta réponse doit être **en français uniquement**."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Historique de la conversation :\n{formatted_history.strip()}\n\n"
                f"Message reçu :\n{question.strip()}"
            ),
        },
    ]

    clarified = call_llm("mixtral", messages)
    return clarified.strip()