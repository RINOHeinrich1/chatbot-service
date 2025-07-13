from adapters.postgresql import PostgreSQLAdapter
def get_adapter_and_connexion(chatbot_id, supabase,type):
    tables = [
        # Format : (table_liaison, table_connexions, adapter)
        ("chatbot_pgsql_connexions", "postgresql_connexions", PostgreSQLAdapter()),
        # Tu pourras en ajouter d’autres ici avec le nom exact :
        # ("chatbot_mariadb_connexions", "mariadb_connexions", MariaDBAdapter()),
    ]
    if type == "postgres":
        res = supabase.table(table_liaison).select("connexion_name, sql_reasoning") \
            .eq("chatbot_id", chatbot_id).single().execute()
        return {
                "adapter": adapter,
                "connexion_name": res.data["connexion_name"],
                "sql_reasoning": res.data.get("sql_reasoning", False),
                "table_connexions": table_connexions
            }

