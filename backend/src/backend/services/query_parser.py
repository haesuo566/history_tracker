from collections.abc import Sequence
from itertools import dropwhile

from google import genai
from google.genai import types
from loguru import logger
from pydantic import BaseModel

from backend.core.config import settings
from backend.models.conversation import Message, MessageRole
from backend.services.intent import Intent

_client: genai.Client | None = None


class ParsedQuery(BaseModel):
    """rewrite_query의 구조화 출력 스키마."""

    # 이 docstring과 필드 순서는 그대로 Gemini에 스키마로 전달된다(description, propertyOrdering).
    # 설명은 모델에게 도움이 될 만큼만 적고, 설계 근거는 주석으로 남긴다. intent를 앞에 두는 것은
    # 의도를 먼저 정하고 그에 맞는 검색어를 쓰게 하려는 의도다 — 지시 표현이 무엇을 가리키는지
    # 찾는 일과 이 턴이 recall인지 판단하는 일이 같은 추론이라 한 호출로 함께 받는다.
    intent: Intent
    query: str
    desired_count: int | None = None


SYSTEM_INSTRUCTION = (
    "사용자의 입력을 다음 JSON 형식으로 변환하라. "
    "앞선 대화가 함께 주어지면 맥락 파악에만 쓰고, 판단과 재작성의 대상은 항상 마지막 사용자 메시지다. "
    "intent 필드에는 마지막 사용자 메시지의 의도를 담아라. "
    "recall: 과거에 방문했거나 열람한 웹 페이지/사이트/글을 기록에서 새로 찾으려는 의도. "
    "detail: 앞선 대화에서 이미 찾아준 결과 중 하나를 지목해 그 페이지의 내용을 더 알려달라는 의도. "
    "'두 번째 것 자세히', '첫 번째 링크 내용이 뭐였지', '거기 가격 얼마였어'처럼 지목한 대상이 앞선 "
    "대화의 결과 목록 안에 있어야 detail이다. 앞선 대화에 결과가 없거나 기록을 새로 뒤져야 하면 "
    "detail이 아니라 recall이다. "
    "etc: 그 외 잡담이나 무관한 질문. "
    "query 필드에는 검색 엔진에 넣기 좋은 간결한 한국어 검색어 문장을 담아라. "
    "대화체, 잡담, 존댓말 표현은 제거하고 핵심 주제와 키워드만 남겨라. "
    "'그거', '아까 그 사이트', '두 번째 것'처럼 앞선 대화를 가리키는 표현은 대화에서 그 대상을 찾아 "
    "구체적인 명사나 제목으로 바꿔라. 가리키는 대상을 찾을 수 없으면 그 표현은 버려라. "
    "intent가 detail이면 query에는 지목된 그 결과 하나를 특정할 수 있는 제목이나 키워드만 담아라. "
    "intent가 etc이면 query는 쓰이지 않으므로 마지막 사용자 메시지를 그대로 담아도 된다. "
    "desired_count 필드에는 사용자가 '3개만', '다섯 개 찾아줘'처럼 결과 개수를 명시적으로 요청한 경우 "
    "그 숫자를 정수로, 그렇지 않으면 null을 담아라."
)

# Gemini의 contents는 assistant 발화를 "model" 역할로 받는다.
_GEMINI_ROLE = {MessageRole.USER: "user", MessageRole.ASSISTANT: "model"}


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


def _build_contents(message: str, history: Sequence[Message]) -> list[types.Content]:
    """이전 메시지를 Gemini 멀티턴 contents로 옮기고 마지막에 이번 입력을 붙인다.

    Gemini는 contents가 user 발화로 시작하길 기대한다. 정상 경로에서는 user/assistant가 짝을
    이루지만 답변 생성이 실패해 user 메시지만 저장된 턴이 있으면 최근 N건을 자른 결과가
    assistant부터 시작할 수 있어, 앞쪽 assistant 발화는 버린다.
    """
    spoken = (past for past in history if past.content)
    turns = dropwhile(lambda past: past.role != MessageRole.USER, spoken)
    contents = [
        types.Content(role=_GEMINI_ROLE.get(past.role, "user"), parts=[types.Part(text=past.content)])
        for past in turns
    ]
    contents.append(types.Content(role="user", parts=[types.Part(text=message)]))
    return contents


def rewrite_query(message: str, history: Sequence[Message] = ()) -> ParsedQuery:
    """사용자 입력을 의도와 검색어, 메타데이터(원하는 결과 개수 등)로 한 번에 해석한다.

    history를 넘기면 그 대화를 맥락으로 삼아 '그거', '아까 그 사이트' 같은 지시 표현을 풀어낸다.
    """
    logger.debug(
        "rewriting query via {}: {!r} (history={} message(s))",
        settings.query_rewrite_model,
        message,
        len(history),
    )
    response = _get_client().models.generate_content(
        model=settings.query_rewrite_model,
        contents=_build_contents(message, history),
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=ParsedQuery,
        ),
    )
    if not isinstance(response.parsed, ParsedQuery):
        # 의도까지 못 받은 상황이라 검색으로 밀어봐야 원문 그대로 찾는 헛질의가 된다. etc로 두어
        # 일반 대화로 답하게 한다(분류 실패 시의 기존 동작과 같다).
        logger.warning("query rewrite unparsable, falling back to raw message: {!r}", response.text)
        return ParsedQuery(intent=Intent.ETC, query=message)
    return response.parsed
