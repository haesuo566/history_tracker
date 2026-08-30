from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.api.routes import conversation as conversation_route
from backend.db.base import Base
from backend.db.session import get_db
from backend.models.conversation import Conversation, Message, MessageRole
from backend.models.document import Document
from backend.services.conversation import (
    TITLE_MAX_CHARS,
    append_message,
    ensure_conversation,
)


@pytest.fixture
def api():
    """/conversations 만 띄운 앱. (client, db) 를 준다.

    인메모리 DB를 TestClient 스레드와 공유하려면 check_same_thread=False 와 StaticPool 이 필요하다.
    """
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(
        bind=engine, tables=[Conversation.__table__, Message.__table__, Document.__table__]
    )

    app = FastAPI()
    app.include_router(conversation_route.router)

    with Session(engine) as db:
        app.dependency_overrides[get_db] = lambda: db
        with TestClient(app) as client:
            yield client, db


def listed(client: TestClient, **params) -> list[dict]:
    response = client.get("/conversations", params=params)
    assert response.status_code == 200, response.text
    return response.json()["conversations"]


def turn(conversation_id: str, question: str, answer: str, db: Session, at: str | None = None) -> None:
    """질문·답변 한 턴을 넣는다.

    at("YYYY-MM-DD HH:MM:SS")을 주면 created_at 을 그 값으로 고정한다. server_default 로 들어오는
    시각은 초 단위라, 한 테스트 안에서 벌어진 일이 모두 같은 값을 갖기 때문이다.
    """
    for role, content in ((MessageRole.USER, question), (MessageRole.ASSISTANT, answer)):
        if at is None:
            append_message(conversation_id, role, content, db)
        else:
            # 컬럼이 naive DateTime 이므로 tz 를 붙이지 않는다.
            created_at = datetime.fromisoformat(at)
            db.add(
                Message(conversation_id=conversation_id, role=role, content=content, created_at=created_at)
            )
            db.commit()


def test_created_conversation_has_no_title_or_activity_until_it_is_used(api):
    """생성만 하고 쓰지 않은 대화. 파생 값이 없으므로 title/last_message_at 은 비어 있다."""
    client, db = api
    ensure_conversation(None, db)

    (row,) = listed(client)

    assert row["title"] is None
    assert row["message_count"] == 0
    assert row["last_message_at"] is None


def test_list_titles_a_conversation_with_its_first_question(api):
    """제목은 messages 에서 파생된다. 첫 user 메시지이고, 답변이나 뒤 질문이 아니다."""
    client, db = api
    conversation_id = ensure_conversation(None, db)
    turn(conversation_id, "요리 블로그 찾아줘", "이 글입니다", db)
    turn(conversation_id, "그거 다시", "같은 글입니다", db)

    (row,) = listed(client)

    assert row["title"] == "요리 블로그 찾아줘"
    assert row["message_count"] == 4
    assert row["last_message_at"] is not None


def test_list_folds_a_multiline_question_into_one_line(api):
    client, db = api
    conversation_id = ensure_conversation(None, db)
    turn(conversation_id, "  어제 본\n리액트   글 \n 찾아줘 ", "이 글입니다", db)

    (row,) = listed(client)

    assert row["title"] == "어제 본 리액트 글 찾아줘"


def test_list_truncates_a_long_question(api):
    """목록 응답에 본문 전체를 담지 않는다."""
    client, db = api
    conversation_id = ensure_conversation(None, db)
    turn(conversation_id, "가" * 500, "이 글입니다", db)

    (row,) = listed(client)

    assert row["title"] == "가" * TITLE_MAX_CHARS + "…"


def test_list_is_ordered_by_last_activity(api):
    client, db = api
    older = ensure_conversation(None, db)
    newer = ensure_conversation(None, db)
    turn(older, "먼저 물어본 것", "답변", db, at="2026-08-01 09:00:00")
    turn(newer, "나중에 물어본 것", "답변", db, at="2026-08-03 09:00:00")

    assert [row["conversation_id"] for row in listed(client)] == [newer, older]


def test_reviving_an_old_conversation_moves_it_to_the_top(api):
    """생성 순이 아니라 활동 순이다. 같은 초에 벌어져도 id 로 갈린다."""
    client, db = api
    revived = ensure_conversation(None, db)
    other = ensure_conversation(None, db)
    turn(revived, "예전 질문", "답변", db)
    turn(other, "다른 대화의 질문", "답변", db)

    turn(revived, "다시 이어서", "답변", db)

    assert [row["conversation_id"] for row in listed(client)] == [revived, other]


def test_empty_conversation_sorts_by_its_creation_time(api):
    """메시지가 없으면 정렬할 활동 시각이 없다. 오래된 대화 뒤로 밀리지 않아야 한다."""
    client, db = api
    used = ensure_conversation(None, db)
    turn(used, "오래된 질문", "답변", db, at="2026-08-01 09:00:00")
    empty = ensure_conversation(None, db)

    assert [row["conversation_id"] for row in listed(client)] == [empty, used]


def test_limit_keeps_the_most_recent_conversations(api):
    client, db = api
    for index in range(5):
        conversation_id = ensure_conversation(None, db)
        turn(conversation_id, f"질문 {index}", "답변", db)

    rows = listed(client, limit=2)

    assert [row["title"] for row in rows] == ["질문 4", "질문 3"]


def test_limit_out_of_range_is_rejected(api):
    client, _db = api

    assert client.get("/conversations", params={"limit": 0}).status_code == 422


def test_detail_returns_every_message_in_order(api):
    """목록을 눌러 대화를 되살리는 경로. load_recent_messages 처럼 잘라내지 않는다."""
    client, db = api
    conversation_id = ensure_conversation(None, db)
    turn(conversation_id, "요리 블로그 찾아줘", "이 글입니다", db)
    turn(conversation_id, "그거 다시", "같은 글입니다", db)

    body = client.get(f"/conversations/{conversation_id}").json()

    assert body["conversation_id"] == conversation_id
    assert [(message["role"], message["content"]) for message in body["messages"]] == [
        ("user", "요리 블로그 찾아줘"),
        ("assistant", "이 글입니다"),
        ("user", "그거 다시"),
        ("assistant", "같은 글입니다"),
    ]


def test_detail_restores_the_result_cards_of_each_turn(api):
    """content 에는 답변 문장만 남는다. 카드는 남은 document_id 로 문서를 되살려 만든다."""
    client, db = api
    db.add(
        Document(
            document_id="doc-kimchi",
            url="https://blog.example.com/kimchi",
            title="김치찌개 레시피",
            full_text="본문",
            hash="hash-kimchi",
        )
    )
    db.commit()
    conversation_id = ensure_conversation(None, db)
    append_message(conversation_id, MessageRole.USER, "요리 블로그 찾아줘", db)
    append_message(
        conversation_id, MessageRole.ASSISTANT, "이 글입니다", db, result_document_ids=["doc-kimchi"]
    )

    body = client.get(f"/conversations/{conversation_id}").json()

    assert body["messages"][0]["results"] == []
    assert body["messages"][1]["results"] == [
        {
            "document_id": "doc-kimchi",
            "title": "김치찌개 레시피",
            "url": "https://blog.example.com/kimchi",
        }
    ]


def test_detail_of_a_turn_without_results_has_no_cards(api):
    """결과 없이 답만 한 턴, 그리고 result_document_ids 가 생기기 전에 쌓인 메시지."""
    client, db = api
    conversation_id = ensure_conversation(None, db)
    turn(conversation_id, "고마워", "천만에요", db)

    body = client.get(f"/conversations/{conversation_id}").json()

    assert [message["results"] for message in body["messages"]] == [[], []]


def test_detail_of_an_empty_conversation_has_no_messages(api):
    client, db = api
    conversation_id = ensure_conversation(None, db)

    body = client.get(f"/conversations/{conversation_id}").json()

    assert body["messages"] == []


def test_detail_does_not_mix_in_other_conversations(api):
    client, db = api
    mine = ensure_conversation(None, db)
    other = ensure_conversation(None, db)
    turn(mine, "내 질문", "내 답변", db)
    turn(other, "남의 질문", "남의 답변", db)

    body = client.get(f"/conversations/{mine}").json()

    assert [message["content"] for message in body["messages"]] == ["내 질문", "내 답변"]


def test_detail_of_unknown_id_is_404(api):
    client, _db = api

    assert client.get("/conversations/does-not-exist").status_code == 404


def test_rename_changes_the_title(api):
    client, db = api
    conversation_id = ensure_conversation(None, db)
    turn(conversation_id, "요리 블로그 찾아줘", "이 글입니다", db)

    response = client.patch(f"/conversations/{conversation_id}", json={"title": "저녁 메뉴 검색"})

    assert response.status_code == 204
    (row,) = listed(client)
    assert row["title"] == "저녁 메뉴 검색"


def test_rename_strips_surrounding_whitespace(api):
    client, db = api
    conversation_id = ensure_conversation(None, db)

    client.patch(f"/conversations/{conversation_id}", json={"title": "  새 이름  "})

    (row,) = listed(client)
    assert row["title"] == "새 이름"


def test_rename_rejects_a_blank_title(api):
    client, db = api
    conversation_id = ensure_conversation(None, db)

    response = client.patch(f"/conversations/{conversation_id}", json={"title": "   "})

    assert response.status_code == 422


def test_rename_rejects_a_title_longer_than_the_limit(api):
    client, db = api
    conversation_id = ensure_conversation(None, db)

    response = client.patch(f"/conversations/{conversation_id}", json={"title": "가" * (TITLE_MAX_CHARS + 1)})

    assert response.status_code == 422


def test_rename_of_unknown_id_is_404(api):
    client, _db = api

    response = client.patch("/conversations/does-not-exist", json={"title": "새 이름"})

    assert response.status_code == 404


def test_delete_removes_the_conversation_from_the_list(api):
    client, db = api
    conversation_id = ensure_conversation(None, db)
    turn(conversation_id, "질문", "답변", db)

    response = client.delete(f"/conversations/{conversation_id}")

    assert response.status_code == 204
    assert response.content == b""
    assert listed(client) == []
    assert client.get(f"/conversations/{conversation_id}").status_code == 404


def test_delete_also_removes_its_messages(api):
    """FK가 강제되지 않으므로 고아 메시지가 남지 않는지 직접 확인한다."""
    client, db = api
    conversation_id = ensure_conversation(None, db)
    turn(conversation_id, "질문", "답변", db)

    client.delete(f"/conversations/{conversation_id}")

    remaining = db.scalars(select(Message).where(Message.conversation_id == conversation_id)).all()
    assert remaining == []


def test_delete_does_not_touch_other_conversations(api):
    client, db = api
    mine = ensure_conversation(None, db)
    other = ensure_conversation(None, db)
    turn(mine, "내 질문", "내 답변", db)
    turn(other, "남의 질문", "남의 답변", db)

    client.delete(f"/conversations/{mine}")

    assert [row["conversation_id"] for row in listed(client)] == [other]
    assert client.get(f"/conversations/{other}").status_code == 200


def test_delete_of_unknown_id_is_404(api):
    client, _db = api

    assert client.delete("/conversations/does-not-exist").status_code == 404


def test_delete_of_an_empty_conversation_works(api):
    client, db = api
    conversation_id = ensure_conversation(None, db)

    assert client.delete(f"/conversations/{conversation_id}").status_code == 204
