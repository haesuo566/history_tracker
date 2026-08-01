from google import genai
from google.genai import types
from loguru import logger
from pydantic import BaseModel

from backend.core.config import settings

_client: genai.Client | None = None


class ParsedQuery(BaseModel):
    """rewrite_query의 구조화 출력 스키마."""

    query: str
    desired_count: int | None = None


SYSTEM_INSTRUCTION = (
    "사용자의 입력을 다음 JSON 형식으로 변환하라. "
    "query 필드에는 검색 엔진에 넣기 좋은 간결한 한국어 검색어 문장을 담아라. "
    "대화체, 잡담, 존댓말 표현은 제거하고 핵심 주제와 키워드만 남겨라. "
    "desired_count 필드에는 사용자가 '3개만', '다섯 개 찾아줘'처럼 결과 개수를 명시적으로 요청한 경우 "
    "그 숫자를 정수로, 그렇지 않으면 null을 담아라."
)


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


def rewrite_query(message: str) -> ParsedQuery:
    """사용자 입력을 검색어와 메타데이터(원하는 결과 개수 등)로 재작성한다."""
    logger.debug("rewriting query via {}: {!r}", settings.query_rewrite_model, message)
    response = _get_client().models.generate_content(
        model=settings.query_rewrite_model,
        contents=message,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=ParsedQuery,
        ),
    )
    if not isinstance(response.parsed, ParsedQuery):
        logger.warning("query rewrite unparsable, falling back to raw message: {!r}", response.text)
        return ParsedQuery(query=message)
    return response.parsed
