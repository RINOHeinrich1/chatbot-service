from core.utils import extract_sql_from_text, execute_sql_via_api, reformulate_answer_via_llm
from .bases import DatabaseAdapter

class PostgreSQLAdapter(DatabaseAdapter):
    def get_schema(self, connexion_params):
        return connexion_params.get("data_schema", "")

    def execute_query(self, connexion_params, query):
        return execute_sql_via_api(connexion_params, query)

    def format_system_prompt(self, schema_text, description):
        return (
            f"Tu es un assistant intelligent [...]"
            # Même contenu que dans ton code
        )

    def extract_query(self, llm_response):
        return extract_sql_from_text(llm_response)

    def format_result_for_user(self, query, result):
        if not result:
            return "Aucune donnée trouvée dans la base."
        return reformulate_answer_via_llm(query, result)
