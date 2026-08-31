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
from backend.models.document import Document
from backend.schemas.chat import ChatResult
from backend.services import preprocess as preprocess_service
from backend.services.intent import Intent
from backend.services.query_parser import ParsedQuery
from backend.services.timerange import TimeRange, TimeRangeKind

DOCUMENT_ID = "doc-kimchi"
OTHER_DOCUMENT_ID = "doc-doenjang"

# 오프셋이 붙은 시각이라야 하루 경계를 사용자의 자정으로 잡을 수 있다(lib/clock.ts 가 만드는 값).
CLIENT_NOW = "2026-08-31T12:00:00+09:00"

# detail 답변이 카드용 발췌(as_chat_result 의 앞 300자)가 아니라 본문을 근거로 받는지 가리려면
# 본문이 그보다 길어야 한다.
FULL_TEXT = "돼지고기와 신김치를 볶다가 물을 붓는다. " * 20


@pytest.fixture
def chat(monkeypatch):
    """Gemini와 검색을 대체한 /chat. 대화 저장·전달 배선만 남겨서 확인한다.

    (client, db, seen) 을 준다. seen 에는 재작성이 받은 history 와, 전처리를 거쳐 검색으로
    넘어간 query·count 가 담긴다. 재작성이 아예 불리지 않았으면 "history" 키가 없다.
    """
    # TestClient는 앱을 별도 스레드에서 돌린다. 인메모리 DB를 그 스레드와 공유하려면 운영 엔진과
    # 같은 check_same_thread=False 에 더해, 커넥션이 하나로 유지되는 StaticPool이 필요하다.
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(
        bind=engine, tables=[Conversation.__table__, Message.__table__, Document.__table__]
    )
    seen: dict = {}

    def fake_rewrite_query(message, history=(), candidates=(), shown=None, client_now=None):
        seen["client_now"] = client_now
        seen["history"] = [(past.role, past.content) for past in history]
        seen["candidates"] = [candidate.document_id for candidate in candidates]
        seen["listed_turns"] = [
            [document.document_id for document in documents]
            for _, documents in sorted((shown or {}).items())
        ]
        # 실제 재작성도 의도·검색어·기간·개수를 한 번에 돌려준다. 여기서는 입력에 섞인 '잡담'/'상세'로
        # 의도를 정한다 — 의도 판정 규칙 자체는 test_preprocess.py가 본다.
        intent = Intent.ETC if "잡담" in message else Intent.DETAIL if "상세" in message else Intent.RECALL
        return ParsedQuery(
            intent=intent,
            target_index=1 if intent is Intent.DETAIL else None,
            time_range=TimeRange(kind=TimeRangeKind.YESTERDAY) if "어제" in message else TimeRange(),
            # 시간 표현을 빼면 검색어가 비는 질의는 재작성이 빈 문자열을 돌려준다.
            query="" if "다 보여줘" in message else f"{message}(재작성)",
            desired_count=3 if "3개" in message else None,
        )

    def fake_search_history(query, db, count=None, window=None):
        seen["query"] = query
        seen["count"] = count
        seen["window"] = window.label if window else None
        return [
            ChatResult(
                document_id=DOCUMENT_ID,
                url="https://blog.example.com/kimchi-jjigae",
                title="김치찌개 레시피",
                score=0.9,
                snippet="돼지고기와 신김치를",
            ),
            ChatResult(
                document_id=OTHER_DOCUMENT_ID,
                url="https://blog.example.com/doenjang-jjigae",
                title="된장찌개 끓이는 법",
                score=0.7,
                snippet="된장을 풀고",
            ),
        ]

    def fake_list_recent(window, db, count=None):
        seen["listed_period"] = window.label
        seen["count"] = count
        return [
            ChatResult(
                document_id=DOCUMENT_ID,
                url="https://blog.example.com/kimchi-jjigae",
                title="김치찌개 레시피",
                score=0.0,
                snippet="돼지고기와 신김치를",
            )
        ]

    def record_answer_context(history, shown) -> None:
        """답변 생성이 받은 맥락. 재작성이 받은 것과 같아야 한다."""
        seen["answer_history"] = [(past.role, past.content) for past in history]
        seen["answer_listed_turns"] = [
            [document.document_id for document in documents]
            for _, documents in sorted((shown or {}).items())
        ]

    def fake_generate_detail_answer(message, document, history=(), shown=None):
        seen["detail_body"] = document.full_text
        record_answer_context(history, shown)
        return f"{message}에 대한 상세 답변"

    def fake_generate_recall_answer(message, results, history=(), shown=None):
        record_answer_context(history, shown)
        return f"{message}에 대한 답변"

    def fake_generate_answer(message, history=(), shown=None):
        record_answer_context(history, shown)
        return f"{message}에 대한 잡담 답변"

    monkeypatch.setattr(preprocess_service, "rewrite_query", fake_rewrite_query)
    monkeypatch.setattr(chat_route, "search_history", fake_search_history)
    monkeypatch.setattr(chat_route, "list_recent", fake_list_recent)
    monkeypatch.setattr(chat_route, "generate_recall_answer", fake_generate_recall_answer)
    monkeypatch.setattr(chat_route, "generate_answer", fake_generate_answer)
    monkeypatch.setattr(chat_route, "generate_detail_answer", fake_generate_detail_answer)

    app = FastAPI()
    app.include_router(chat_route.router)

    with Session(engine) as db:
        db.add_all(
            [
                Document(
                    document_id=DOCUMENT_ID,
                    url="https://blog.example.com/kimchi-jjigae",
                    title="김치찌개 레시피",
                    full_text=FULL_TEXT,
                    hash="hash-kimchi",
                ),
                Document(
                    document_id=OTHER_DOCUMENT_ID,
                    url="https://blog.example.com/doenjang-jjigae",
                    title="된장찌개 끓이는 법",
                    full_text="된장을 풀고 두부를 넣는다",
                    hash="hash-doenjang",
                ),
            ]
        )
        db.commit()
        app.dependency_overrides[get_db] = lambda: db
        with TestClient(app) as client:
            yield client, db, seen


def post(
    client: TestClient,
    message: str,
    conversation_id: str | None = None,
    client_now: str | None = CLIENT_NOW,
) -> dict:
    response = client.post(
        "/chat",
        json={"message": message, "conversation_id": conversation_id, "client_now": client_now},
    )
    assert response.status_code == 200, response.text
    return response.json()


def messages_of(db: Session, conversation_id: str) -> list[Message]:
    return list(
        db.scalars(select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id))
    )


def stored(db: Session, conversation_id: str) -> list[tuple[str, str]]:
    return [(message.role, message.content) for message in messages_of(db, conversation_id)]


def results_of(db: Session, conversation_id: str) -> list[list[str] | None]:
    return [message.result_document_ids for message in messages_of(db, conversation_id)]


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


def test_answer_receives_the_same_context_as_the_rewrite(chat):
    """재작성만 맥락을 보면 '아까 그거'를 검색어로는 풀어도 답변 문장에서는 못 알아듣는다."""
    client, _db, seen = chat
    conversation_id = post(client, "요리 블로그 찾아줘")["conversation_id"]

    post(client, "그거 다시", conversation_id)

    assert seen["answer_history"] == seen["history"]
    # 답변은 직전 턴의 목록까지 받는다. 재작성은 같은 목록을 후보 목록으로 따로 받으므로 여기서 빠진다.
    assert seen["answer_listed_turns"] == [[DOCUMENT_ID, OTHER_DOCUMENT_ID]]
    assert seen["listed_turns"] == []
    assert seen["candidates"] == [DOCUMENT_ID, OTHER_DOCUMENT_ID]


def test_chitchat_answer_still_sees_the_conversation(chat):
    """잡담은 검색을 타지 않을 뿐, 앞선 대화까지 잊어야 할 이유는 없다."""
    client, _db, seen = chat
    conversation_id = post(client, "요리 블로그 찾아줘")["conversation_id"]

    post(client, "고마워 잡담", conversation_id)

    assert seen["answer_history"] == [
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


def test_a_stated_period_reaches_the_search(chat):
    """기간이 검색까지 닿지 않으면 재작성이 알아낸 것이 그 자리에서 버려진다."""
    client, _db, seen = chat

    post(client, "어제 본 요리 블로그 찾아줘")

    assert seen["window"] == "어제(8월 30일)"


def test_a_period_only_query_is_listed_instead_of_searched(chat):
    """'어제 본 거 다 보여줘'에는 찾을 낱말이 없다. 검색을 태우면 아무 문서나 끌어온다."""
    client, _db, seen = chat

    body = post(client, "어제 본 거 다 보여줘")

    assert "query" not in seen  # 검색은 타지 않았다
    assert seen["listed_period"] == "어제(8월 30일)"
    assert [result["document_id"] for result in body["results"]] == [DOCUMENT_ID]


def test_a_bare_query_without_a_period_still_searches(chat):
    """검색어가 비어도 기간이 없으면 늘어놓을 근거가 없다. 검색 쪽으로 간다."""
    client, _db, seen = chat

    post(client, "다 보여줘")

    assert "listed_period" not in seen
    assert seen["query"] == ""


def test_the_clients_clock_reaches_the_rewrite(chat):
    """서버는 브라우저의 시간대를 모른다. 요청에 실려 온 시각이 그대로 닿아야 한다."""
    client, _db, seen = chat

    post(client, "어제 본 요리 블로그 찾아줘")

    assert seen["client_now"].isoformat() == "2026-08-31T12:00:00+09:00"


def test_a_request_without_a_clock_still_works(chat):
    """옛 클라이언트가 보낸 요청도 기간 없는 질의는 그대로 동작해야 한다."""
    client, _db, seen = chat

    post(client, "요리 블로그 찾아줘", client_now=None)

    assert seen["client_now"] is None
    assert seen["query"] == "요리 블로그 찾아줘(재작성)"


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


def test_shown_results_are_stored_with_the_answer(chat):
    """다음 턴이 '두 번째 것'을 짚으려면 이번 턴이 무엇을 보여줬는지 남아 있어야 한다."""
    client, db, _seen = chat

    conversation_id = post(client, "요리 블로그 찾아줘")["conversation_id"]

    assert results_of(db, conversation_id) == [None, [DOCUMENT_ID, OTHER_DOCUMENT_ID]]


def test_chitchat_turn_stores_no_result_list(chat):
    """결과가 없던 턴이 후보로 걸리면 화면에 없는 것을 지목하게 된다."""
    client, db, _seen = chat

    conversation_id = post(client, "안녕")["conversation_id"]

    assert results_of(db, conversation_id) == [None, None]


def test_detail_uses_the_pointed_document_without_searching_again(chat):
    """지목이 끝난 문서를 다시 검색하면 그 문서가 아닌 것이 올라올 수 있다."""
    client, _db, seen = chat
    conversation_id = post(client, "요리 블로그 찾아줘")["conversation_id"]
    seen.pop("query")

    body = post(client, "그거 상세 내용 알려줘", conversation_id)

    # 직전 턴이 보여준 목록이 재작성으로 넘어갔다
    assert seen["candidates"] == [DOCUMENT_ID, OTHER_DOCUMENT_ID]
    assert "query" not in seen  # 검색은 다시 타지 않았다
    assert [result["document_id"] for result in body["results"]] == [DOCUMENT_ID]


def test_detail_answer_is_grounded_in_the_whole_body(chat):
    """'자세히 알려줘'에 답하려면 카드에 보이는 발췌로는 부족하다. 본문 전체가 근거여야 한다."""
    client, _db, seen = chat
    conversation_id = post(client, "요리 블로그 찾아줘")["conversation_id"]

    body = post(client, "그거 상세 내용 알려줘", conversation_id)

    assert seen["detail_body"] == FULL_TEXT
    assert len(body["results"][0]["snippet"]) < len(FULL_TEXT)  # 카드용 발췌는 그대로 잘려 나간다


def test_detail_turn_does_not_shrink_the_candidate_list(chat):
    """detail 턴이 목록을 지목된 한 건으로 갈아치우면 '아니 두 번째 것'이 막힌다."""
    client, db, seen = chat
    conversation_id = post(client, "요리 블로그 찾아줘")["conversation_id"]

    post(client, "그거 상세 내용 알려줘", conversation_id)
    post(client, "그거 상세 내용 알려줘", conversation_id)

    # 두 번째 상세 요청도 recall 턴이 보여준 목록 전체를 후보로 받는다
    assert seen["candidates"] == [DOCUMENT_ID, OTHER_DOCUMENT_ID]
    assert results_of(db, conversation_id) == [
        None,
        [DOCUMENT_ID, OTHER_DOCUMENT_ID],
        None,
        None,
        None,
        None,
    ]


def test_detail_without_a_previous_result_list_falls_back_to_search(chat):
    """지목할 목록이 없으면 상세 요청으로 볼 수 없다. 기록을 새로 뒤진다."""
    client, _db, seen = chat

    post(client, "그거 상세 내용 알려줘")

    assert seen["candidates"] == []
    assert seen["query"] == "그거 상세 내용 알려줘(재작성)"
