from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "backend"
    database_url: str = "sqlite:///./app.db"
    embedding_dim: int = 3072
    gemini_api_key: str = "AIzaSyA71NJ_jH8PzZKy3rkIUvyoaOtiYbQa5y4"
    embedding_model: str = "gemini-embedding-001"
    query_rewrite_model: str = "gemini-3.5-flash"


settings = Settings()
