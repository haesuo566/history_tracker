import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.db.base import Base
from backend.models.conversation import Conversation, Message, MessageRole
from backend.services import preprocess as preprocess_service
from backend.services.conversation import append_message, ensure_conversation
from backend.services.intent import Intent
from backend.services.preprocess import preprocess_message
from backend.services.query_parser import ParsedQuery


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(bind=engine, tables=[Conversation.__table__, Message.__table__])
    with Session(engine) as session:
        yield session


def stub_rewrite(monkeypatch, intent: Intent) -> list[list[tuple[str, str]]]:
    """재작성을 대체해 원하는 의도를 돌려주게 하고, 호출마다 받은 history를 담는 리스트를 준다."""
    calls: list[list[tuple[str, str]]] = []

    def fake_rewrite_query(message, history=()):
        calls.append([(past.role, past.content) for past in history])
        return ParsedQuery(intent=intent, query=f"{message}(재작성)")

    monkeypatch.setattr(preprocess_service, "rewrite_query", fake_rewrite_query)
    return calls


def seed_answered_turn(db: Session) -> str:
    """기록을 한 번 찾아준 대화를 만들어 그 conversation_id를 준다. 지목할 결과가 있는 상태다."""
    conversation_id = ensure_conversation(None, db)
    append_message(conversation_id, MessageRole.USER, "요리 블로그 찾아줘", db)
    append_message(conversation_id, MessageRole.ASSISTANT, "'김치찌개 레시피' 페이지를 찾았어요", db)
    return conversation_id


def test_detail_is_kept_when_a_previous_turn_exists(db, monkeypatch):
    stub_rewrite(monkeypatch, Intent.DETAIL)
    conversation_id = seed_answered_turn(db)

    prepared = preprocess_message("두 번째 것 자세히", conversation_id, db)

    assert prepared.intent is Intent.DETAIL


def test_detail_on_the_first_turn_falls_back_to_recall(db, monkeypatch):
    """지목할 결과가 아직 없는 턴은 상세 요청이 될 수 없다."""
    stub_rewrite(monkeypatch, Intent.DETAIL)

    prepared = preprocess_message("두 번째 것 자세히", None, db)

    assert prepared.intent is Intent.RECALL


def test_detail_survives_a_regex_recall_verdict(db, monkeypatch):
    """'찾아' 같은 키워드는 recall과 detail에 똑같이 붙으므로 정규식이 detail을 막지 않는다."""
    stub_rewrite(monkeypatch, Intent.DETAIL)
    conversation_id = seed_answered_turn(db)

    prepared = preprocess_message("그 페이지에서 가격 부분 찾아줘", conversation_id, db)

    assert prepared.intent is Intent.DETAIL


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
    calls = stub_rewrite(monkeypatch, Intent.DETAIL)
    conversation_id = seed_answered_turn(db)

    preprocess_message("두 번째 것 자세히", conversation_id, db)

    assert calls == [
        [("user", "요리 블로그 찾아줘"), ("assistant", "'김치찌개 레시피' 페이지를 찾았어요")]
    ]
