import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.api.routes import chat as chat_route
from backend.db.base import Base
from backend.db.session import get_db
from backend.models.conversation import Conversation, Message
from backend.services.intent import Intent


@pytest.fixture
def chat(monkeypatch):
    """Gemini와 검색을 대체한 /chat. 대화 저장·전달 배선만 남겨서 확인한다.

    (client, db, seen) 을 준다. seen["history"] 에는 search_history 가 받은 history 가 담긴다.
    """
    # TestClient는 앱을 별도 스레드에서 돌린다. 인메모리 DB를 그 스레드와 공유하려면 운영 엔진과
    # 같은 check_same_thread=False 에 더해, 커넥션이 하나로 유지되는 StaticPool이 필요하다.
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine, tables=[Conversation.__table__, Message.__table__])
    seen: dict[str, list[tuple[str, str]]] = {}

    def fake_search_history(message, db, history=()):
        seen["history"] = [(past.role, past.content) for past in history]
        return []

    monkeypatch.setattr(chat_route, "classify_intent", lambda message: Intent.RECALL)
    monkeypatch.setattr(chat_route, "search_history", fake_search_history)
    monkeypatch.setattr(chat_route, "generate_recall_answer", lambda message, results: f"{message}에 대한 답변")

    app = FastAPI()
    app.include_router(chat_route.router)

    with Session(engine) as db:
        app.dependency_overrides[get_db] = lambda: db
        with TestClient(app) as client:
            yield client, db, seen


def post(client: TestClient, message: str, conversation_id: str | None = None) -> dict:
    response = client.post("/chat", json={"message": message, "conversation_id": conversation_id})
    assert response.status_code == 200, response.text
    return response.json()


def stored(db: Session, conversation_id: str) -> list[tuple[str, str]]:
    messages = db.scalars(
        select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id)
    )
    return [(message.role, message.content) for message in messages]


def test_first_request_issues_an_id_and_has_no_history(chat):
    client, _db, seen = chat

    body = post(client, "요리 블로그 찾아줘")

    assert body["conversation_id"]
    assert seen["history"] == []


def test_both_sides_of_the_turn_are_stored(chat):
    client, db, _seen = chat

    conversation_id = post(client, "요리 블로그 찾아줘")["conversation_id"]

    assert stored(db, conversation_id) == [
        ("user", "요리 블로그 찾아줘"),
        ("assistant", "요리 블로그 찾아줘에 대한 답변"),
    ]


def test_second_request_reuses_the_id_and_receives_the_previous_turn(chat):
    """history는 이번 입력을 저장하기 전 시점이어야 한다. 여기 '그거 다시'가 섞이면 중복 전달이다."""
    client, _db, seen = chat
    conversation_id = post(client, "요리 블로그 찾아줘")["conversation_id"]

    body = post(client, "그거 다시", conversation_id)

    assert body["conversation_id"] == conversation_id
    assert seen["history"] == [
        ("user", "요리 블로그 찾아줘"),
        ("assistant", "요리 블로그 찾아줘에 대한 답변"),
    ]


def test_omitting_the_id_starts_a_fresh_conversation(chat):
    """프론트의 '새 대화'는 저장한 id를 버리는 것이다. 이전 맥락이 딸려오면 안 된다."""
    client, _db, seen = chat
    first = post(client, "요리 블로그 찾아줘")["conversation_id"]

    body = post(client, "파이썬 비동기 글 찾아줘")

    assert body["conversation_id"] != first
    assert seen["history"] == []
