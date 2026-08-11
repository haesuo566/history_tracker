from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """모든 값은 `.env` 에서 읽는다. 누락되면 기동 시점에 검증 오류로 알린다."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str
    log_level: str
    database_url: str
    embedding_dim: int
    gemini_api_key: str
    embedding_model: str
    query_rewrite_model: str
    answer_model: str
    min_cosine_similarity: float
    min_fts_matched_terms: int
    chat_history_messages: int
    chat_history_max_chars: int
    detail_max_chars: int


settings = Settings()
