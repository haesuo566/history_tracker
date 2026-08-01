from google import genai
from google.genai import types
from loguru import logger

from backend.core.config import settings

_client: genai.Client | None = None

SYSTEM_INSTRUCTION = (
    "너는 사용자의 웹 브라우징 기록을 검색해주는 어시스턴트의 대화 응답을 담당한다. "
    "친절하고 간결한 한국어로 답하라. 확실하지 않은 사실은 지어내지 말고 모른다고 답하라."
)


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


def generate_answer(message: str) -> str:
    """etc 의도의 메시지에 대해 Gemini로 일반 대화 응답을 생성한다."""
    logger.debug("generating chat answer via {}: {!r}", settings.answer_model, message)
    response = _get_client().models.generate_content(
        model=settings.answer_model,
        contents=message,
        config=types.GenerateContentConfig(system_instruction=SYSTEM_INSTRUCTION),
    )
    return response.text.strip()
