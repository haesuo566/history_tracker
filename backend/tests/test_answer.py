import pytest

from backend.models.document import Document
from backend.services import answer as answer_service
from backend.services.answer import _build_detail_prompt, generate_detail_answer


def document(full_text: str) -> Document:
    return Document(
        document_id="doc-kimchi",
        url="https://blog.example.com/kimchi-jjigae",
        title="김치찌개 레시피",
        full_text=full_text,
        hash="hash-kimchi",
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


def test_a_blank_body_answers_without_calling_gemini(monkeypatch):
    """근거 없이 제목만 주면 내용을 지어낸다. 부르지 않는 것이 옳다."""
    monkeypatch.setattr(
        answer_service, "_get_client", lambda: pytest.fail("본문이 없는데 Gemini를 불렀다")
    )

    reply = generate_detail_answer("자세히 알려줘", document(""))

    assert "김치찌개 레시피" in reply
