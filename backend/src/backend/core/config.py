from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "backend"
    log_level: str = "INFO"
    database_url: str = "sqlite:///./app.db"
    embedding_dim: int = 3072
    gemini_api_key: str
    embedding_model: str = "gemini-embedding-001"
    query_rewrite_model: str = "gemini-3.1-flash-lite"
    intent_classify_model: str = "gemini-3.1-flash-lite"
    answer_model: str = "gemini-3.1-flash-lite"
    min_cosine_similarity: float = 0.5
    min_fts_matched_terms: int = 1
    chat_history_messages: int = 10


settings = Settings()
