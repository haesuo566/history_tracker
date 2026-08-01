import re
from enum import StrEnum

from google import genai
from google.genai import types
from loguru import logger

from backend.core.config import settings


class Intent(StrEnum):
    """chat 메시지를 분류하는 2가지 의도."""

    RECALL = "recall"
    ETC = "etc"


SYSTEM_INSTRUCTION = (
    "사용자의 메시지를 다음 두 가지 의도 중 하나로 분류하라. "
    "recall: 과거에 방문했거나 열람한 웹 페이지/사이트/글을 다시 찾거나 검색하려는 의도. "
    "etc: 그 외 잡담이나 무관한 질문. "
    "가장 적절한 값 하나만 출력하라."
)

_RECALL_KEYWORDS = re.compile(
    r"찾아|검색|서치|북마크|즐겨찾기|방문\s?기록|열람\s?기록|기록에|히스토리에|"
    r"url|링크\s?(줘|알려|보내)",
    re.IGNORECASE,
)
_RECALL_RECOLLECTION = re.compile(
    r"(봤|봤었|봤던|본\s?적|읽었|읽었던|들어갔|열었|방문했|접속했)"
    r".{0,15}?(사이트|페이지|글|블로그|기사|영상|뉴스|링크|주소|탭|자료|문서)"
)
_ETC_GREETING = re.compile(r"^(안녕|반가워|고마워|고마웠|감사|잘\s?가|수고)?[ㅋㅎ.!?\s]*$")


def classify_by_regex(message: str) -> Intent | None:
    """정규식/키워드로 의도를 분류한다. 확신할 수 없으면 None을 반환한다."""
    stripped = message.strip()
    if not stripped:
        return Intent.ETC
    if _RECALL_KEYWORDS.search(stripped) or _RECALL_RECOLLECTION.search(stripped):
        return Intent.RECALL
    if _ETC_GREETING.match(stripped):
        return Intent.ETC
    return None


_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


def classify_by_gemini(message: str) -> Intent:
    """정규식으로 판단할 수 없는 메시지를 Gemini로 분류한다."""
    logger.debug("classifying intent via {}: {!r}", settings.intent_classify_model, message)
    response = _get_client().models.generate_content(
        model=settings.intent_classify_model,
        contents=message,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=Intent,
        ),
    )
    if not isinstance(response.parsed, Intent):
        logger.warning("gemini intent classification unparsable, defaulting to etc: {!r}", response.text)
        return Intent.ETC
    return response.parsed


def classify_intent(message: str) -> Intent:
    """메시지의 의도를 분류한다: 정규식 우선, 판정 불가 시 Gemini로 폴백."""
    intent = classify_by_regex(message)
    if intent is not None:
        logger.debug("intent classified by regex: {!r} -> {}", message, intent)
        return intent
    intent = classify_by_gemini(message)
    logger.debug("intent classified by gemini: {!r} -> {}", message, intent)
    return intent
