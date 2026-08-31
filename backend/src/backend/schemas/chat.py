from datetime import UTC, datetime

from pydantic import BaseModel, field_validator


class ChatRequest(BaseModel):
    """conversation_id를 넘기면 그 대화를 이어간다. 없으면 새 대화가 시작된다.

    client_now는 클라이언트의 현재 시각으로, 오프셋이 붙은 ISO 문자열을 기대한다("어제"의 경계는
    브라우저 앞에 앉은 사람의 자정이라 서버 시각으로는 알 수 없다). 없으면 UTC로 간주하고 경고를
    남긴다 — 옛 클라이언트도 기간 없는 질의는 그대로 동작해야 한다.
    """

    message: str
    conversation_id: str | None = None
    client_now: datetime | None = None


class ChatResult(BaseModel):
    """검색 결과 한 줄. visited_at은 이 페이지를 수집한 시각(documents.timestamp)이다.

    같은 URL을 다시 방문해도 갱신되지 않으므로(services/document.py) 정확히는 '처음 본 때'다.
    """

    document_id: str
    url: str
    title: str
    score: float
    snippet: str
    visited_at: datetime | None = None

    @field_validator("visited_at")
    @classmethod
    def _mark_as_utc(cls, value: datetime | None) -> datetime | None:
        """저장된 값은 tzinfo가 없는 UTC다. 나갈 때 그 사실을 붙인다.

        붙이지 않으면 "2026-08-30T05:00:00"으로 직렬화되고, 브라우저의 Date는 오프셋 없는 값을
        로컬 시각으로 읽어 한국에서는 아홉 시간이 어긋난 날짜가 카드에 찍힌다.
        """
        if value is None or value.tzinfo is not None:
            return value
        return value.replace(tzinfo=UTC)


class ChatResponse(BaseModel):
    """conversation_id는 항상 이번 요청이 실제로 사용한 대화의 id다.

    요청이 모르는 id를 보냈으면 새로 시작된 대화의 id가 들어오므로, 클라이언트는 매 응답의
    이 값으로 저장해 둔 id를 갱신하면 된다.
    """

    conversation_id: str
    results: list[ChatResult] = []
    answer: str | None = None
