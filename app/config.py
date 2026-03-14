from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    firefly_url: str
    firefly_token: str

    plaid_env: str = "sandbox"
    plaid_client_id: str
    plaid_secret: str
    plaid_access_token: str

    openai_api_key: str

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


settings = Settings()
