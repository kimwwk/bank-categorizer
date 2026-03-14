from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    firefly_url: str
    firefly_token: str

    plaid_env: str = "sandbox"
    plaid_client_id: str
    plaid_secret: str
    plaid_access_token: str

    openai_api_key: str

    # Plaid account_id → Firefly account ID mapping
    # Format: "plaid_id_1:firefly_id_1,plaid_id_2:firefly_id_2"
    account_map: str = ""

    # Firefly rule group ID for auto-categorization rules
    rule_group_id: int = 1


    state_dir: str = "./data"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @property
    def plaid_base_url(self) -> str:
        envs = {
            "sandbox": "https://sandbox.plaid.com",
            "development": "https://development.plaid.com",
            "production": "https://production.plaid.com",
        }
        return envs.get(self.plaid_env, envs["sandbox"])

    @property
    def account_mapping(self) -> dict[str, str]:
        """Parse ACCOUNT_MAP into {plaid_account_id: firefly_account_id}."""
        if not self.account_map:
            return {}
        mapping = {}
        for pair in self.account_map.split(","):
            pair = pair.strip()
            if ":" in pair:
                plaid_id, firefly_id = pair.split(":", 1)
                mapping[plaid_id.strip()] = firefly_id.strip()
        return mapping


settings = Settings()
