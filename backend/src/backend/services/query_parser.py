from google import genai
from google.genai import types
from loguru import logger

from backend.core.config import settings

_client: genai.Client | None = None

SYSTEM_INSTRUCTION = (
    "사용자의 입력을 검색 엔진에 넣기 좋은 간결한 한국어 검색어 문장으로 재작성하라. "
    "대화체, 잡담, 존댓말 표현은 제거하고 핵심 주제와 키워드만 남겨라. "
    "재작성된 검색어 문장만 출력하라."
)


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


def rewrite_query(message: str) -> str:
    """사용자 입력을 검색에 적합한 문장으로 재작성한다."""
    logger.debug("rewriting query via {}: {!r}", settings.query_rewrite_model, message)
    response = _get_client().models.generate_content(
        model=settings.query_rewrite_model,
        contents=message,
        config=types.GenerateContentConfig(system_instruction=SYSTEM_INSTRUCTION),
    )
    return response.text.strip()
