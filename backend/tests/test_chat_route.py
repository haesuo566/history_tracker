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
from backend.services import preprocess as preprocess_service
from backend.services.intent import Intent
from backend.services.query_parser import ParsedQuery


@pytest.fixture
def chat(monkeypatch):
    """Gemini와 검색을 대체한 /chat. 대화 저장·전달 배선만 남겨서 확인한다.

    (client, db, seen) 을 준다. seen 에는 재작성이 받은 history 와, 전처리를 거쳐 검색으로
    넘어간 query·count 가 담긴다. 재작성이 아예 불리지 않았으면 "history" 키가 없다.
    """
    # TestClient는 앱을 별도 스레드에서 돌린다. 인메모리 DB를 그 스레드와 공유하려면 운영 엔진과
    # 같은 check_same_thread=False 에 더해, 커넥션이 하나로 유지되는 StaticPool이 필요하다.
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine, tables=[Conversation.__table__, Message.__table__])
    seen: dict = {}

    def fake_rewrite_query(message, history=()):
        seen["history"] = [(past.role, past.content) for past in history]
        # 실제 재작성도 의도·검색어·개수를 한 번에 돌려준다. 여기서는 입력에 섞인 '잡담'/'상세'로
        # 의도를 정한다 — 의도 판정 규칙 자체는 test_preprocess.py가 본다.
        intent = Intent.ETC if "잡담" in message else Intent.DETAIL if "상세" in message else Intent.RECALL
        return ParsedQuery(
            intent=intent,
            query=f"{message}(재작성)",
            desired_count=3 if "3개" in message else None,
        )

    def fake_search_history(query, db, count=None):
        seen["query"] = query
        seen["count"] = count
        return []

    monkeypatch.setattr(preprocess_service, "rewrite_query", fake_rewrite_query)
    monkeypatch.setattr(chat_route, "search_history", fake_search_history)
    monkeypatch.setattr(chat_route, "generate_recall_answer", lambda message, results: f"{message}에 대한 답변")
    monkeypatch.setattr(chat_route, "generate_answer", lambda message: f"{message}에 대한 잡담 답변")

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


def test_search_receives_the_rewritten_query(chat):
    """검색은 원문이 아니라 전처리를 거친 검색어를 받아야 한다."""
    client, _db, seen = chat

    post(client, "요리 블로그 찾아줘")

    assert seen["query"] == "요리 블로그 찾아줘(재작성)"


def test_requested_result_count_reaches_search(chat):
    """재작성이 뽑아낸 결과 개수도 전처리 결과로 검색까지 전달돼야 한다."""
    client, _db, seen = chat

    post(client, "요리 블로그 3개만 찾아줘")

    assert seen["count"] == 3


def test_answer_is_generated_from_the_original_message(chat):
    """검색어는 재작성해도 사용자에게 답할 때 근거로 삼는 질문은 원문이다."""
    client, db, _seen = chat

    conversation_id = post(client, "요리 블로그 찾아줘")["conversation_id"]

    assert stored(db, conversation_id)[1] == ("assistant", "요리 블로그 찾아줘에 대한 답변")


def test_greeting_skips_the_rewrite_entirely(chat):
    """정규식이 잡담으로 확신한 턴은 검색을 타지 않으니 재작성 호출도 낭비다."""
    client, db, seen = chat

    conversation_id = post(client, "안녕")["conversation_id"]

    assert "history" not in seen  # 재작성이 불리지 않았다
    assert "query" not in seen  # 검색도 불리지 않았다
    assert stored(db, conversation_id)[1] == ("assistant", "안녕에 대한 잡담 답변")


def test_rewrite_can_route_an_undecided_message_to_chitchat(chat):
    """정규식이 판단하지 못한 턴은 재작성이 돌려준 의도를 따른다."""
    client, db, seen = chat

    conversation_id = post(client, "잡담이나 하자")["conversation_id"]

    assert seen["history"] == []  # 의도를 받으려면 재작성은 돌아야 한다
    assert "query" not in seen  # etc로 판정됐으니 검색은 안 탄다
    assert stored(db, conversation_id)[1] == ("assistant", "잡담이나 하자에 대한 잡담 답변")


def test_regex_verdict_wins_over_the_rewrite(chat):
    """정규식이 recall로 확신하면 재작성이 etc라고 해도 검색을 탄다."""
    client, _db, seen = chat

    post(client, "잡담 블로그 찾아줘")

    assert seen["query"] == "잡담 블로그 찾아줘(재작성)"


def test_detail_still_takes_the_recall_path_for_now(chat):
    """상세 검색 경로는 아직 없다. 분류만 갈라 두고 지금은 recall과 같은 검색을 탄다."""
    client, db, seen = chat
    conversation_id = post(client, "요리 블로그 찾아줘")["conversation_id"]

    post(client, "그거 상세 내용 알려줘", conversation_id)

    assert seen["query"] == "그거 상세 내용 알려줘(재작성)"
    assert stored(db, conversation_id)[3] == ("assistant", "그거 상세 내용 알려줘에 대한 답변")
