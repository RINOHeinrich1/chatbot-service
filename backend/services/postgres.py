import os
import requests
from utils.helpers import generate_jwt

def execute_sql_via_api(connexion_params, extracted_sql):
    try:
        url = os.getenv("POSTGRESS_SQL_EXECUTOR")
        payload = {
            "host": connexion_params["host_name"],
            "port": str(connexion_params["port"]),
            "user": connexion_params["user"],
            "password": connexion_params["password"],
            "dbname": connexion_params["database"],
            "ssl_mode": connexion_params.get("ssl_mode", "disable"),
            "sql": extracted_sql,
        }

        headers = {
            "Authorization": f"Bearer {generate_jwt()}",
            "Content-Type": "application/json"
        }

        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        result = response.json()
        print(f"response:{result}")
        # Assure que le résultat est bien un tableau, même vide
        if result is None:
            return []
        return result

    except Exception as e:
        print(f"[Erreur exécution SQL via API] : {e}")
        return None
