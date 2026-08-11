import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.db.base import Base
from backend.models.conversation import Conversation, Message, MessageRole
from backend.models.document import Document
from backend.services import preprocess as preprocess_service
from backend.services.conversation import append_message, ensure_conversation
from backend.services.intent import Intent
from backend.services.preprocess import preprocess_message
from backend.services.query_parser import ParsedQuery

KIMCHI = ("doc-kimchi", "김치찌개 레시피", "https://blog.example.com/kimchi-jjigae")
DOENJANG = ("doc-doenjang", "된장찌개 끓이는 법", "https://recipe.example.com/doenjang")


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        bind=engine, tables=[Conversation.__table__, Message.__table__, Document.__table__]
    )
    with Session(engine) as session:
        yield session


def stub_rewrite(
    monkeypatch, intent: Intent, target_index: int | None = None, query: str | None = None
) -> list[dict]:
    """재작성을 대체해 원하는 판정을 돌려주게 하고, 호출마다 받은 입력을 담는 리스트를 준다."""
    calls: list[dict] = []

    def fake_rewrite_query(message, history=(), candidates=()):
        calls.append(
            {
                "history": [(past.role, past.content) for past in history],
                "candidates": [candidate.title for candidate in candidates],
            }
        )
        return ParsedQuery(
            intent=intent,
            target_index=target_index,
            query=query if query is not None else f"{message}(재작성)",
        )

    monkeypatch.setattr(preprocess_service, "rewrite_query", fake_rewrite_query)
    return calls


def add_document(db: Session, document_id: str, title: str, url: str) -> str:
    db.add(
        Document(
            document_id=document_id,
            url=url,
            title=title,
            full_text=f"{title} 본문",
            hash=f"hash-{document_id}",
        )
    )
    db.commit()
    return document_id


def seed_answered_turn(db: Session, *documents: tuple[str, str, str]) -> str:
    """기록을 한 번 찾아준 대화를 만들어 그 conversation_id를 준다. 지목할 결과가 있는 상태다."""
    documents = documents or (KIMCHI, DOENJANG)
    document_ids = [add_document(db, *document) for document in documents]

    conversation_id = ensure_conversation(None, db)
    append_message(conversation_id, MessageRole.USER, "요리 블로그 찾아줘", db)
    append_message(
        conversation_id,
        MessageRole.ASSISTANT,
        "'김치찌개 레시피' 페이지를 찾았어요",
        db,
        result_document_ids=document_ids,
    )
    return conversation_id


def test_detail_is_kept_when_a_result_list_exists(db, monkeypatch):
    stub_rewrite(monkeypatch, Intent.DETAIL, target_index=2)
    conversation_id = seed_answered_turn(db)

    prepared = preprocess_message("두 번째 것 자세히", conversation_id, db)

    assert prepared.intent is Intent.DETAIL
    assert prepared.target_document.title == "된장찌개 끓이는 법"


def test_detail_on_the_first_turn_falls_back_to_recall(db, monkeypatch):
    """지목할 결과가 아직 없는 턴은 상세 요청이 될 수 없다."""
    stub_rewrite(monkeypatch, Intent.DETAIL, target_index=1)

    prepared = preprocess_message("두 번째 것 자세히", None, db)

    assert prepared.intent is Intent.RECALL
    assert prepared.target_document is None


def test_detail_survives_a_regex_recall_verdict(db, monkeypatch):
    """'찾아' 같은 키워드는 recall과 detail에 똑같이 붙으므로 정규식이 detail을 막지 않는다."""
    stub_rewrite(monkeypatch, Intent.DETAIL, target_index=1)
    conversation_id = seed_answered_turn(db)

    prepared = preprocess_message("그 페이지에서 가격 부분 찾아줘", conversation_id, db)

    assert prepared.intent is Intent.DETAIL


def test_candidates_are_the_last_shown_result_list(db, monkeypatch):
    """후보는 결과가 있던 마지막 턴에서 온다. 그 뒤에 결과 없는 턴이 끼어도 목록은 유지된다."""
    calls = stub_rewrite(monkeypatch, Intent.DETAIL, target_index=1)
    conversation_id = seed_answered_turn(db)
    append_message(conversation_id, MessageRole.USER, "고마워", db)
    append_message(conversation_id, MessageRole.ASSISTANT, "천만에요", db)

    preprocess_message("첫 번째 거 자세히", conversation_id, db)

    assert calls[0]["candidates"] == ["김치찌개 레시피", "된장찌개 끓이는 법"]


def test_target_is_matched_by_title_when_no_index_is_given(db, monkeypatch):
    """재작성이 번호를 못 주더라도 재작성된 검색어로 후보를 짚을 수 있다."""
    stub_rewrite(monkeypatch, Intent.DETAIL, query="김치찌개 레시피")
    conversation_id = seed_answered_turn(db)

    prepared = preprocess_message("아까 그 김치찌개 글 내용 알려줘", conversation_id, db)

    assert prepared.intent is Intent.DETAIL
    assert prepared.target_document.document_id == "doc-kimchi"


def test_out_of_range_index_falls_back_to_title_matching(db, monkeypatch):
    stub_rewrite(monkeypatch, Intent.DETAIL, target_index=9, query="된장찌개 끓이는 법")
    conversation_id = seed_answered_turn(db)

    prepared = preprocess_message("아홉 번째 거 자세히", conversation_id, db)

    assert prepared.target_document.document_id == "doc-doenjang"


def test_unpointable_detail_falls_back_to_recall(db, monkeypatch):
    """후보 중 어느 것도 짚지 못하면 엉뚱한 문서를 근거로 삼는 대신 검색으로 내려보낸다."""
    stub_rewrite(monkeypatch, Intent.DETAIL, query="우주 로켓 발사")
    conversation_id = seed_answered_turn(db)

    prepared = preprocess_message("그거 자세히", conversation_id, db)

    assert prepared.intent is Intent.RECALL
    assert prepared.target_document is None


def test_tied_candidates_are_not_guessed(db, monkeypatch):
    """제목이 같아 하나로 좁혀지지 않으면 찍지 않는다."""
    stub_rewrite(monkeypatch, Intent.DETAIL, query="김치찌개 레시피")
    conversation_id = seed_answered_turn(
        db,
        ("doc-a", "김치찌개 레시피", "https://a.example.com/kimchi"),
        ("doc-b", "김치찌개 레시피", "https://b.example.com/kimchi"),
    )

    prepared = preprocess_message("그 김치찌개 글 자세히", conversation_id, db)

    assert prepared.intent is Intent.RECALL


def test_regex_recall_is_not_overturned_by_a_chitchat_verdict(db, monkeypatch):
    """정규식이 확신한 '기록 관련'은 재작성이 잡담이라 해도 유지된다."""
    stub_rewrite(monkeypatch, Intent.ETC)
    conversation_id = seed_answered_turn(db)

    prepared = preprocess_message("파이썬 비동기 글 찾아줘", conversation_id, db)

    assert prepared.intent is Intent.RECALL


def test_undecided_message_follows_the_rewrite(db, monkeypatch):
    """정규식이 판단하지 못한 턴은 재작성 판정을 그대로 따른다."""
    stub_rewrite(monkeypatch, Intent.ETC)
    conversation_id = seed_answered_turn(db)

    prepared = preprocess_message("오늘 날씨 어때", conversation_id, db)

    assert prepared.intent is Intent.ETC


def test_greeting_never_reaches_the_rewrite(db, monkeypatch):
    calls = stub_rewrite(monkeypatch, Intent.RECALL)

    prepared = preprocess_message("안녕", None, db)

    assert prepared.intent is Intent.ETC
    assert prepared.query == "안녕"  # 재작성을 건너뛰었으니 원문 그대로다
    assert calls == []


def test_rewrite_sees_the_conversation_up_to_the_previous_turn(db, monkeypatch):
    """의도를 가리려면 앞선 대화가 필요하다. 이번 입력은 아직 섞이지 않아야 한다."""
    calls = stub_rewrite(monkeypatch, Intent.DETAIL, target_index=1)
    conversation_id = seed_answered_turn(db)

    preprocess_message("두 번째 것 자세히", conversation_id, db)

    assert len(calls) == 1
    assert calls[0]["history"] == [
        ("user", "요리 블로그 찾아줘"),
        ("assistant", "'김치찌개 레시피' 페이지를 찾았어요"),
    ]
