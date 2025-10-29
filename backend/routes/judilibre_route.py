from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel
from typing import Any, Dict

# Import du service d'orchestration
# Import compatible quand l'app est lancée depuis le dossier `backend`
from services.judilibre_service import judilibre_flow

router = APIRouter()

# Modèle Pydantic pour valider le corps de la requête
class JudilibreRequest(BaseModel):
    question: str

@router.post("/judilibre/ask", 
             tags=["Judilibre"], 
             summary="Poser une question de jurisprudence à Judilibre/Mixtral")
async def ask_judilibre(request_body: JudilibreRequest) -> Dict[str, Any]:
    if not request_body.question:
        raise HTTPException(status_code=400, detail="La question ne peut pas être vide.")
    
    try:
        answer = await judilibre_flow(request_body.question)
        # Retourner la réponse brute (dict) sans validation stricte
        return answer
        
    except HTTPException as http_err:
        raise http_err
    except Exception as e:
        print(f"Erreur inattendue dans le flux Judilibre: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur interne du serveur: {e}")
