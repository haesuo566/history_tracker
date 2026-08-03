from google import genai
from google.genai import types
from loguru import logger

from backend.core.config import settings
from backend.schemas.chat import ChatResult

_client: genai.Client | None = None

SYSTEM_INSTRUCTION = (
    "너는 사용자의 웹 브라우징 기록을 검색해주는 어시스턴트의 대화 응답을 담당한다. "
    "친절하고 간결한 한국어로 답하라. 확실하지 않은 사실은 지어내지 말고 모른다고 답하라."
)

RECALL_SYSTEM_INSTRUCTION = (
    "너는 사용자의 웹 브라우징 기록을 검색해주는 어시스턴트의 대화 응답을 담당한다. "
    "아래에는 사용자 질문과 그에 대해 검색된 기록 목록(제목, URL, 본문 발췌)이 주어진다. "
    "이 목록만 근거로 친절하고 간결한 한국어로 답하라. 목록에 없는 내용은 지어내지 말고, "
    "목록이 비어 있으면 관련 기록을 찾지 못했다고 답하라."
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


def generate_recall_answer(message: str, results: list[ChatResult]) -> str:
    """recall 의도의 메시지에 대해 검색된 기록(title, url)을 근거로 Gemini 응답을 생성한다."""
    logger.debug(
        "generating recall answer via {}: {!r} ({} result(s))", settings.answer_model, message, len(results)
    )
    found = (
        "\n".join(f"- {result.title} ({result.url})\n  본문 발췌: {result.snippet}" for result in results)
        or "(검색 결과 없음)"
    )
    contents = f"사용자 질문: {message}\n\n검색된 기록:\n{found}"
    response = _get_client().models.generate_content(
        model=settings.answer_model,
        contents=contents,
        config=types.GenerateContentConfig(system_instruction=RECALL_SYSTEM_INSTRUCTION),
    )
    return response.text.strip()
