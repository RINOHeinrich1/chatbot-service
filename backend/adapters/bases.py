

class DatabaseAdapter:
    def get_schema(self, connexion_params):
        raise NotImplementedError

    def execute_query(self, connexion_params, query):
        raise NotImplementedError

    def format_system_prompt(self, schema_text, description):
        raise NotImplementedError

    def extract_query(self, llm_response):
        raise NotImplementedError

    def format_result_for_user(self, query, result):
        raise NotImplementedError
