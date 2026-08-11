from google import genai
from google.genai import types
from loguru import logger

from backend.core.config import settings
from backend.models.document import Document
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

# recall과 달리 근거가 문서 하나의 본문이다. 그래서 '목록에서 못 찾았다'가 아니라 '그 문서에는
# 그 내용이 없다'가 옳은 실패 답변이 되어, 목록을 전제한 위 프롬프트를 재활용할 수 없다.
DETAIL_SYSTEM_INSTRUCTION = (
    "너는 사용자의 웹 브라우징 기록을 검색해주는 어시스턴트의 대화 응답을 담당한다. "
    "아래에는 사용자 질문과, 사용자가 지목한 기록 한 건의 제목·URL·본문이 주어진다. "
    "이 본문만 근거로 친절하고 간결한 한국어로 답하라. 요약을 원하면 핵심을 추려 요약하고, "
    "특정 정보를 물으면 본문에서 그 대목을 찾아 답하라. 본문에 없는 내용은 지어내지 말고 "
    "그 기록에는 해당 내용이 없다고 답하라."
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


def generate_detail_answer(message: str, document: Document) -> str:
    """detail 의도의 메시지에 대해 지목된 문서 한 건의 본문을 근거로 Gemini 응답을 생성한다.

    근거가 검색 결과의 발췌가 아니라 본문이라는 점이 generate_recall_answer와의 차이다. '자세히
    알려줘'에 답하려면 발췌로는 부족하다. 근거로 쓸 본문이 없으면 Gemini를 부르지 않는다 —
    제목만 주면 그럴듯한 내용을 지어내기 때문이다.
    """
    contents = _build_detail_prompt(message, document, settings.detail_max_chars)
    if contents is None:
        logger.info("detail document has no usable body: document_id={}", document.document_id)
        return f"'{document.title}' 기록은 제목과 주소만 남아 있어 본문 내용을 알려드릴 수 없습니다."

    logger.debug(
        "generating detail answer via {}: {!r} (document_id={} body={} chars)",
        settings.answer_model,
        message,
        document.document_id,
        len(document.full_text),
    )
    response = _get_client().models.generate_content(
        model=settings.answer_model,
        contents=contents,
        config=types.GenerateContentConfig(system_instruction=DETAIL_SYSTEM_INSTRUCTION),
    )
    return response.text.strip()


def _build_detail_prompt(message: str, document: Document, max_chars: int) -> str | None:
    """지목된 문서를 근거로 붙인 프롬프트를 만든다. 근거로 쓸 본문이 없으면 None.

    본문이 max_chars를 넘으면 앞부분만 싣고 잘렸다는 사실을 함께 알린다. 뒤가 더 있다는 것을
    모르면 실린 앞부분이 문서의 전부인 줄 알고 '그런 내용은 없다'고 단정한다. 질문과 맞물리는
    구간을 골라 싣는 것은 청크 검색이 필요한 별개 과제라, 지금은 앞에서부터 자른다.
    """
    body = document.full_text[:max_chars]
    if not body.strip():
        return None

    prompt = (
        f"사용자 질문: {message}\n\n"
        f"지목된 기록\n"
        f"제목: {document.title}\n"
        f"URL: {document.url}\n"
        f"본문:\n{body}"
    )
    if len(document.full_text) > max_chars:
        prompt += f"\n\n(본문이 길어 앞 {max_chars}자만 실었다. 이 뒤의 내용은 알 수 없다.)"
    return prompt
