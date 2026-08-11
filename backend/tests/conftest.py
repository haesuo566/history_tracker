import os

# Settings 는 모든 값을 .env 에서 읽는다. .env 가 없는 환경(CI, 새 클론)에서도
# 테스트가 돌도록 필수값을 채운다. 이미 설정된 값은 건드리지 않는다.
_TEST_ENV = {
    "APP_NAME": "backend",
    "LOG_LEVEL": "INFO",
    "DATABASE_URL": "sqlite:///./app.db",
    "EMBEDDING_DIM": "3072",
    "GEMINI_API_KEY": "test-key-for-unit-tests",
    "EMBEDDING_MODEL": "gemini-embedding-001",
    "QUERY_REWRITE_MODEL": "gemini-3.1-flash-lite",
    "ANSWER_MODEL": "gemini-3.1-flash-lite",
    "MIN_COSINE_SIMILARITY": "0.5",
    "MIN_FTS_MATCHED_TERMS": "1",
    "CHAT_HISTORY_MESSAGES": "30",
    "CHAT_HISTORY_MAX_CHARS": "8000",
    "DETAIL_MAX_CHARS": "20000",
}

for _key, _value in _TEST_ENV.items():
    os.environ.setdefault(_key, _value)
