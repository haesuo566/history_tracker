import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from backend.db.base import Base
from backend.models.conversation import Conversation, Message, MessageRole
from backend.services.conversation import (
    append_message,
    ensure_conversation,
    load_conversation,
    load_recent_messages,
    rename_conversation,
)
from backend.services.query_parser import _build_contents


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(bind=engine, tables=[Conversation.__table__, Message.__table__])
    with Session(engine) as session:
        yield session


def conversation_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Conversation))


def turns(db: Session, conversation_id: str) -> list[tuple[str, str]]:
    return [(message.role, message.content) for message in load_recent_messages(conversation_id, db)]


def test_no_conversation_id_starts_a_new_conversation(db):
    conversation_id = ensure_conversation(None, db)

    assert conversation_id
    assert conversation_count(db) == 1


def test_known_conversation_id_is_reused(db):
    first = ensure_conversation(None, db)

    assert ensure_conversation(first, db) == first
    assert conversation_count(db) == 1


def test_unknown_conversation_id_starts_a_new_conversation(db):
    """클라이언트가 보낸 id를 그대로 만들지 않는다. 새 id를 발급해 응답으로 알려준다."""
    conversation_id = ensure_conversation("does-not-exist", db)

    assert conversation_id != "does-not-exist"
    assert conversation_count(db) == 1


def test_messages_load_oldest_first(db):
    conversation_id = ensure_conversation(None, db)
    append_message(conversation_id, MessageRole.USER, "첫 질문", db)
    append_message(conversation_id, MessageRole.ASSISTANT, "첫 답변", db)
    append_message(conversation_id, MessageRole.USER, "두 번째 질문", db)

    assert turns(db, conversation_id) == [
        ("user", "첫 질문"),
        ("assistant", "첫 답변"),
        ("user", "두 번째 질문"),
    ]


def test_limit_keeps_the_most_recent_messages_in_order(db):
    conversation_id = ensure_conversation(None, db)
    for index in range(5):
        append_message(conversation_id, MessageRole.USER, f"메시지 {index}", db)

    recent = load_recent_messages(conversation_id, db, limit=2)

    assert [message.content for message in recent] == ["메시지 3", "메시지 4"]


def test_limit_zero_loads_nothing(db):
    conversation_id = ensure_conversation(None, db)
    append_message(conversation_id, MessageRole.USER, "질문", db)

    assert load_recent_messages(conversation_id, db, limit=0) == []


def test_messages_of_other_conversations_are_not_mixed_in(db):
    mine = ensure_conversation(None, db)
    other = ensure_conversation(None, db)
    append_message(mine, MessageRole.USER, "내 질문", db)
    append_message(other, MessageRole.USER, "남의 질문", db)

    assert turns(db, mine) == [("user", "내 질문")]


def test_rename_overwrites_the_auto_derived_title(db):
    conversation_id = ensure_conversation(None, db)
    append_message(conversation_id, MessageRole.USER, "요리 블로그 찾아줘", db)

    assert rename_conversation(conversation_id, "저녁 메뉴 검색", db) is True
    assert load_conversation(conversation_id, db).title == "저녁 메뉴 검색"


def test_unknown_conversation_id_is_not_renamed(db):
    assert rename_conversation("does-not-exist", "새 이름", db) is False


def test_build_contents_maps_roles_and_appends_current_message_last():
    history = [
        Message(role=MessageRole.USER, content="첫 질문"),
        Message(role=MessageRole.ASSISTANT, content="첫 답변"),
    ]

    contents = _build_contents("그거 다시 찾아줘", history)

    assert [(content.role, content.parts[0].text) for content in contents] == [
        ("user", "첫 질문"),
        ("model", "첫 답변"),
        ("user", "그거 다시 찾아줘"),
    ]


def test_build_contents_drops_a_leading_assistant_turn():
    """답변만 남은 턴이 앞에 걸리면 contents가 model로 시작해 Gemini 호출이 깨진다."""
    history = [
        Message(role=MessageRole.ASSISTANT, content="잘려나간 앞턴의 답변"),
        Message(role=MessageRole.USER, content="다음 질문"),
    ]

    contents = _build_contents("그거 다시 보여줘", history)

    assert [(content.role, content.parts[0].text) for content in contents] == [
        ("user", "다음 질문"),
        ("user", "그거 다시 보여줘"),
    ]


def test_build_contents_skips_empty_messages():
    history = [
        Message(role=MessageRole.USER, content="첫 질문"),
        Message(role=MessageRole.ASSISTANT, content=""),
    ]

    contents = _build_contents("그거 다시 보여줘", history)

    assert [(content.role, content.parts[0].text) for content in contents] == [
        ("user", "첫 질문"),
        ("user", "그거 다시 보여줘"),
    ]


def test_build_contents_without_history_sends_only_the_current_message():
    contents = _build_contents("파이썬 비동기 글 찾아줘", [])

    assert [(content.role, content.parts[0].text) for content in contents] == [
        ("user", "파이썬 비동기 글 찾아줘")
    ]
