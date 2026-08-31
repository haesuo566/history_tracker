from collections.abc import Mapping, Sequence
from datetime import datetime

from google.genai import types
from loguru import logger

from backend.core.config import settings
from backend.models.conversation import Message
from backend.models.document import Document
from backend.schemas.chat import ChatResult
from backend.services.gemini import get_client
from backend.services.prompt import render_history
from backend.services.runtime_settings import get_settings
from backend.services.timerange import TimeWindow, to_local

# 세 프롬프트가 공유하는 규칙. 앞선 대화는 맥락으로만 쓰고 답변의 근거는 이번 턴에 주어진 것으로
# 한정한다 — 이 문장이 없으면 지난 턴에 실린 목록을 이번 답변의 근거로 끌어다 쓴다.
_HISTORY_RULE = (
    "앞선 대화가 함께 주어지면 무엇을 가리키는 말인지 알아듣는 데에만 쓰고, 답변의 근거는 "
    "마지막에 주어진 것으로 한정하라. "
)

SYSTEM_INSTRUCTION = (
    "너는 사용자의 웹 브라우징 기록을 검색해주는 어시스턴트의 대화 응답을 담당한다. "
    f"{_HISTORY_RULE}"
    "친절하고 간결한 한국어로 답하라. 확실하지 않은 사실은 지어내지 말고 모른다고 답하라."
)

RECALL_SYSTEM_INSTRUCTION = (
    "너는 사용자의 웹 브라우징 기록을 검색해주는 어시스턴트의 대화 응답을 담당한다. "
    f"{_HISTORY_RULE}"
    "마지막에는 사용자 질문과 그에 대해 검색된 기록 목록(제목, URL, 본 날짜, 본문 발췌)이 주어진다. "
    "이 목록만 근거로 친절하고 간결한 한국어로 답하라. 목록에 없는 내용은 지어내지 말고, "
    "목록이 비어 있으면 관련 기록을 찾지 못했다고 답하라. "
    "기간이 함께 주어졌다면 그 기간에 본 기록만 찾은 것이다. 그때 목록이 비어 있으면 반드시 그 "
    "기간을 밝혀 '그 기간에는 관련 기록이 없다'고 답하라 — 기간을 빼고 '기록이 없다'고만 하면 "
    "사용자는 아예 없는 줄로 안다. 날짜를 물었거나 여러 날에 걸친 목록이면 각 기록을 언제 봤는지도 "
    "함께 알려라."
)

# recall과 달리 근거가 문서 하나의 본문이다. 그래서 '목록에서 못 찾았다'가 아니라 '그 문서에는
# 그 내용이 없다'가 옳은 실패 답변이 되어, 목록을 전제한 위 프롬프트를 재활용할 수 없다.
DETAIL_SYSTEM_INSTRUCTION = (
    "너는 사용자의 웹 브라우징 기록을 검색해주는 어시스턴트의 대화 응답을 담당한다. "
    f"{_HISTORY_RULE}"
    "마지막에는 사용자 질문과, 사용자가 지목한 기록 한 건의 제목·URL·본 날짜·본문이 주어진다. "
    "이 본문만 근거로 친절하고 간결한 한국어로 답하라. 요약을 원하면 핵심을 추려 요약하고, "
    "특정 정보를 물으면 본문에서 그 대목을 찾아 답하라. 본문에 없는 내용은 지어내지 말고 "
    "그 기록에는 해당 내용이 없다고 답하라."
)


def _contents(
    history: Sequence[Message],
    shown: Mapping[int, Sequence[Document]],
    prompt: str,
) -> list[types.Content]:
    """앞선 대화 뒤에 이번 턴의 프롬프트(질문 + 근거)를 붙인다.

    history를 함께 싣는 것은 '아까 그거'가 무엇인지 답변 단계도 알아야 하기 때문이다. 재작성이
    풀어낸 검색어는 검색에만 쓰이고, 답변은 사용자가 실제로 쓴 문장을 받는다.
    """
    return [*render_history(history, shown), types.Content(role="user", parts=[types.Part(text=prompt)])]


def generate_answer(
    message: str,
    history: Sequence[Message] = (),
    shown: Mapping[int, Sequence[Document]] = {},
) -> str:
    """etc 의도의 메시지에 대해 Gemini로 일반 대화 응답을 생성한다."""
    model = get_settings().answer_model
    logger.debug("generating chat answer via {}: {!r} (history={})", model, message, len(history))
    response = get_client().models.generate_content(
        model=model,
        contents=_contents(history, shown, message),
        config=types.GenerateContentConfig(system_instruction=SYSTEM_INSTRUCTION),
    )
    return response.text.strip()


def _visited_on(moment: datetime | None, client_now: datetime | None) -> str:
    """그 기록을 본 날짜. 값이 없으면 빈 문자열이라 부르는 쪽에서 그 줄이 통째로 빠진다.

    사용자의 지역 날짜로 적는다. UTC 그대로 적으면 한국에서는 아침 아홉 시 이전에 본 것이 전날로
    표기되어, 정작 "어제 본 것"을 물어 찾아준 결과에 그저께 날짜가 찍힌다.
    """
    if moment is None:
        return ""
    local = to_local(moment, client_now)
    return f"{local.year}년 {local.month}월 {local.day}일"


def _result_line(result: ChatResult, client_now: datetime | None) -> str:
    """검색 결과 한 건을 프롬프트 한 덩이로. 날짜를 모르는 기록은 그 줄 없이 나간다."""
    visited = _visited_on(result.visited_at, client_now)
    seen = f"\n  본 날짜: {visited}" if visited else ""
    return f"- {result.title} ({result.url}){seen}\n  본문 발췌: {result.snippet}"


def generate_recall_answer(
    message: str,
    results: list[ChatResult],
    history: Sequence[Message] = (),
    shown: Mapping[int, Sequence[Document]] = {},
    window: TimeWindow | None = None,
    client_now: datetime | None = None,
) -> str:
    """recall 의도의 메시지에 대해 검색된 기록(title, url, 본 날짜)을 근거로 Gemini 응답을 생성한다.

    window가 있으면 그 기간만 뒤졌다는 사실을 프롬프트에 함께 싣는다. 0건일 때 "기록이 없다"로
    끝나면 사용자는 아예 없는 줄로 알기 때문에, 어느 기간을 뒤졌는지 답변이 밝힐 수 있어야 한다.
    """
    model = get_settings().answer_model
    logger.debug(
        "generating recall answer via {}: {!r} ({} result(s), period={}, history={})",
        model,
        message,
        len(results),
        window.label if window else None,
        len(history),
    )
    found = "\n".join(_result_line(result, client_now) for result in results) or "(검색 결과 없음)"
    period = f"\n\n찾은 기간: {window.label}" if window else ""
    response = get_client().models.generate_content(
        model=model,
        contents=_contents(history, shown, f"사용자 질문: {message}{period}\n\n검색된 기록:\n{found}"),
        config=types.GenerateContentConfig(system_instruction=RECALL_SYSTEM_INSTRUCTION),
    )
    return response.text.strip()


def generate_detail_answer(
    message: str,
    document: Document,
    history: Sequence[Message] = (),
    shown: Mapping[int, Sequence[Document]] = {},
    client_now: datetime | None = None,
) -> str:
    """detail 의도의 메시지에 대해 지목된 문서 한 건의 본문을 근거로 Gemini 응답을 생성한다.

    근거가 검색 결과의 발췌가 아니라 본문이라는 점이 generate_recall_answer와의 차이다. '자세히
    알려줘'에 답하려면 발췌로는 부족하다. 근거로 쓸 본문이 없으면 Gemini를 부르지 않는다 —
    제목만 주면 그럴듯한 내용을 지어내기 때문이다.
    """
    prompt = _build_detail_prompt(message, document, settings.detail_max_chars, client_now)
    if prompt is None:
        logger.info("detail document has no usable body: document_id={}", document.document_id)
        return f"'{document.title}' 기록은 제목과 주소만 남아 있어 본문 내용을 알려드릴 수 없습니다."

    model = get_settings().answer_model
    logger.debug(
        "generating detail answer via {}: {!r} (document_id={} body={} chars, history={})",
        model,
        message,
        document.document_id,
        len(document.full_text),
        len(history),
    )
    response = get_client().models.generate_content(
        model=model,
        contents=_contents(history, shown, prompt),
        config=types.GenerateContentConfig(system_instruction=DETAIL_SYSTEM_INSTRUCTION),
    )
    return response.text.strip()


def _build_detail_prompt(
    message: str, document: Document, max_chars: int, client_now: datetime | None = None
) -> str | None:
    """지목된 문서를 근거로 붙인 프롬프트를 만든다. 근거로 쓸 본문이 없으면 None.

    본문이 max_chars를 넘으면 앞부분만 싣고 잘렸다는 사실을 함께 알린다. 뒤가 더 있다는 것을
    모르면 실린 앞부분이 문서의 전부인 줄 알고 '그런 내용은 없다'고 단정한다. 질문과 맞물리는
    구간을 골라 싣는 것은 청크 검색이 필요한 별개 과제라, 지금은 앞에서부터 자른다.

    본 날짜도 함께 싣는다. '그거 언제 봤더라'는 지목한 기록에 대한 상세 질문이라 이 경로로 오는데,
    본문만 주면 답할 근거가 없다.
    """
    body = document.full_text[:max_chars]
    if not body.strip():
        return None

    visited = _visited_on(document.timestamp, client_now)
    seen = f"\n본 날짜: {visited}" if visited else ""
    prompt = (
        f"사용자 질문: {message}\n\n"
        f"지목된 기록\n"
        f"제목: {document.title}\n"
        f"URL: {document.url}{seen}\n"
        f"본문:\n{body}"
    )
    if len(document.full_text) > max_chars:
        prompt += f"\n\n(본문이 길어 앞 {max_chars}자만 실었다. 이 뒤의 내용은 알 수 없다.)"
    return prompt
