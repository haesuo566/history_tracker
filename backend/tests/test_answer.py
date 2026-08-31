from datetime import datetime, timedelta, timezone

import pytest

from backend.models.document import Document
from backend.schemas.chat import ChatResult
from backend.services import answer as answer_service
from backend.services.answer import _build_detail_prompt, _result_line, generate_detail_answer

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 8, 31, 12, 0, tzinfo=KST)
# 저장된 값에는 시간대가 없다. UTC 로 8/29 20:00 은 한국에서 8/30 아침 5시다.
VISITED = datetime(2026, 8, 29, 20, 0)


def document(full_text: str, timestamp: datetime | None = None) -> Document:
    return Document(
        document_id="doc-kimchi",
        url="https://blog.example.com/kimchi-jjigae",
        title="김치찌개 레시피",
        full_text=full_text,
        hash="hash-kimchi",
        timestamp=timestamp,
    )


def result(visited_at: datetime | None) -> ChatResult:
    return ChatResult(
        document_id="doc-kimchi",
        url="https://blog.example.com/kimchi-jjigae",
        title="김치찌개 레시피",
        score=0.5,
        snippet="돼지고기와 신김치를",
        visited_at=visited_at,
    )


def test_detail_prompt_carries_the_question_and_the_whole_body():
    prompt = _build_detail_prompt("자세히 알려줘", document("돼지고기와 신김치를 볶는다"), 20000)

    assert "자세히 알려줘" in prompt
    assert "김치찌개 레시피" in prompt
    assert "돼지고기와 신김치를 볶는다" in prompt
    assert "이 뒤의 내용은 알 수 없다" not in prompt


def test_detail_prompt_marks_a_truncated_body():
    """뒤가 더 있다는 것을 모르면 실린 앞부분을 전부로 알고 '그런 내용은 없다'고 단정한다."""
    prompt = _build_detail_prompt("가격 얼마였어", document("가" * 100), 50)

    assert "가" * 50 in prompt
    assert "가" * 51 not in prompt
    assert "앞 50자만 실었다" in prompt


def test_detail_prompt_is_none_when_the_body_is_blank():
    """본문이 저장되지 않은 기록도 실제로 있다. 근거가 없으면 프롬프트를 만들지 않는다."""
    assert _build_detail_prompt("자세히 알려줘", document("  \n  "), 20000) is None


def test_the_result_line_dates_in_the_users_timezone(monkeypatch):
    """UTC 그대로 적으면 한국에서 아침 아홉 시 이전에 본 것이 전날로 찍힌다."""
    assert "본 날짜: 2026년 8월 30일" in _result_line(result(VISITED), NOW)


def test_a_result_without_a_date_has_no_date_line():
    assert "본 날짜" not in _result_line(result(None), NOW)


def test_detail_prompt_carries_the_visit_date():
    """'그거 언제 봤더라'는 지목한 기록에 대한 질문이라 이 경로로 온다. 본문만으로는 답할 수 없다."""
    prompt = _build_detail_prompt("이거 언제 봤지", document("본문", VISITED), 20000, NOW)

    assert "본 날짜: 2026년 8월 30일" in prompt


def test_a_blank_body_answers_without_calling_gemini(monkeypatch):
    """근거 없이 제목만 주면 내용을 지어낸다. 부르지 않는 것이 옳다."""
    monkeypatch.setattr(
        answer_service, "get_client", lambda: pytest.fail("본문이 없는데 Gemini를 불렀다")
    )

    reply = generate_detail_answer("자세히 알려줘", document(""))

    assert "김치찌개 레시피" in reply
