import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.db.base import Base
from backend.models.conversation import Conversation, Message, MessageRole
from backend.models.document import Document
from backend.services.conversation import (
    append_message,
    ensure_conversation,
    load_all_messages,
)
from backend.services.results import latest_shown, load_shown_documents, past_shown

KIMCHI = ("doc-kimchi", "김치찌개 레시피", "https://blog.example.com/kimchi")
DOENJANG = ("doc-doenjang", "된장찌개 끓이는 법", "https://recipe.example.com/doenjang")
BUDAE = ("doc-budae", "부대찌개 맛집", "https://map.example.com/budae")


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        bind=engine, tables=[Conversation.__table__, Message.__table__, Document.__table__]
    )
    with Session(engine) as session:
        yield session


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


def answered_turn(db: Session, conversation_id: str, *document_ids: str) -> None:
    """결과를 보여준 턴 한 쌍(질문+답변)을 덧붙인다."""
    append_message(conversation_id, MessageRole.USER, "요리 블로그 찾아줘", db)
    append_message(
        conversation_id,
        MessageRole.ASSISTANT,
        "찾았어요",
        db,
        result_document_ids=list(document_ids),
    )


def titles(shown: dict[int, list[Document]]) -> list[list[str]]:
    """메시지 순서대로 각 턴이 보여준 제목 목록."""
    return [[document.title for document in shown[key]] for key in sorted(shown)]


def test_shown_documents_keep_the_order_they_were_listed_in(db):
    for document in (KIMCHI, DOENJANG):
        add_document(db, *document)
    conversation_id = ensure_conversation(None, db)
    answered_turn(db, conversation_id, "doc-doenjang", "doc-kimchi")

    shown = load_shown_documents(load_all_messages(conversation_id, db), db)

    assert titles(shown) == [["된장찌개 끓이는 법", "김치찌개 레시피"]]


def test_turns_without_results_get_no_entry(db):
    """결과가 없던 턴은 키 자체가 없어야 '결과가 있던 턴'을 키 존재만으로 가릴 수 있다."""
    add_document(db, *KIMCHI)
    conversation_id = ensure_conversation(None, db)
    answered_turn(db, conversation_id, "doc-kimchi")
    append_message(conversation_id, MessageRole.USER, "고마워", db)
    append_message(conversation_id, MessageRole.ASSISTANT, "천만에요", db)

    shown = load_shown_documents(load_all_messages(conversation_id, db), db)

    assert titles(shown) == [["김치찌개 레시피"]]


def test_documents_that_no_longer_exist_are_skipped(db):
    """해시 방식 마이그레이션에서 지워진 문서를 가리키는 id가 옛 메시지에 남아 있을 수 있다."""
    add_document(db, *KIMCHI)
    conversation_id = ensure_conversation(None, db)
    answered_turn(db, conversation_id, "doc-kimchi", "doc-사라짐")

    shown = load_shown_documents(load_all_messages(conversation_id, db), db)

    assert titles(shown) == [["김치찌개 레시피"]]


def test_a_turn_whose_documents_all_vanished_gets_no_entry(db):
    conversation_id = ensure_conversation(None, db)
    answered_turn(db, conversation_id, "doc-사라짐")

    assert load_shown_documents(load_all_messages(conversation_id, db), db) == {}


def test_latest_shown_is_the_last_turn_that_had_results(db):
    """뒤에 결과 없는 턴이 끼어도 마지막 '결과가 있던' 턴을 고른다."""
    for document in (KIMCHI, DOENJANG):
        add_document(db, *document)
    conversation_id = ensure_conversation(None, db)
    answered_turn(db, conversation_id, "doc-kimchi")
    answered_turn(db, conversation_id, "doc-doenjang")
    append_message(conversation_id, MessageRole.USER, "고마워", db)
    append_message(conversation_id, MessageRole.ASSISTANT, "천만에요", db)

    shown = load_shown_documents(load_all_messages(conversation_id, db), db)

    assert [document.title for document in latest_shown(shown)] == ["된장찌개 끓이는 법"]


def test_latest_shown_of_an_empty_map_is_empty():
    assert latest_shown({}) == []


def test_past_shown_drops_the_latest_turn(db):
    """직전 턴의 목록은 후보 목록으로 따로 실리므로 여기서 빼야 두 번 실리지 않는다."""
    for document in (KIMCHI, DOENJANG):
        add_document(db, *document)
    conversation_id = ensure_conversation(None, db)
    answered_turn(db, conversation_id, "doc-kimchi")
    answered_turn(db, conversation_id, "doc-doenjang")

    shown = load_shown_documents(load_all_messages(conversation_id, db), db)

    assert titles(past_shown(shown)) == [["김치찌개 레시피"]]


def test_past_shown_keeps_only_the_most_recent_turns(db):
    for document in (KIMCHI, DOENJANG, BUDAE):
        add_document(db, *document)
    conversation_id = ensure_conversation(None, db)
    for document_id in ("doc-kimchi", "doc-doenjang", "doc-budae", "doc-kimchi"):
        answered_turn(db, conversation_id, document_id)

    shown = load_shown_documents(load_all_messages(conversation_id, db), db)

    # 마지막 턴을 뺀 셋 중 최근 둘.
    assert titles(past_shown(shown, limit=2)) == [["된장찌개 끓이는 법"], ["부대찌개 맛집"]]


def test_past_shown_with_no_room_lists_nothing(db):
    add_document(db, *KIMCHI)
    conversation_id = ensure_conversation(None, db)
    answered_turn(db, conversation_id, "doc-kimchi")
    answered_turn(db, conversation_id, "doc-kimchi")

    shown = load_shown_documents(load_all_messages(conversation_id, db), db)

    assert past_shown(shown, limit=0) == {}
