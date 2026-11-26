import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from backend.main import llm_unavailable
from backend.services.llm import openai_compat
from backend.services.llm.generation import ChatMessage, LlmError, Tool, ToolCall
from backend.services.llm.openai_compat import (
    OpenAICompatGenerator,
    _endpoint,
    list_models,
)

BASE_URL = "http://ollama.internal:11434"


class Plan(BaseModel):
    title: str = Field(description="대시보드 제목.")


def completion(content: str | None) -> dict:
    return {"choices": [{"index": 0, "message": {"role": "assistant", "content": content}}]}


class FakeServer:
    """가짜 OpenAI 호환 서버. 받은 본문을 기록하고, 테스트가 정한 응답을 돌려준다."""

    def __init__(self) -> None:
        self.bodies: list[dict] = []
        self.headers: list[httpx.Headers] = []
        self.urls: list[str] = []
        self.handler = lambda request: httpx.Response(200, json=completion("안녕하세요"))

    def answer(self, content: str | None) -> None:
        self.handler = lambda request: httpx.Response(200, json=completion(content))

    def dispatch(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(request.content) if request.content else {})
        self.headers.append(request.headers)
        self.urls.append(str(request.url))
        return self.handler(request)


@pytest.fixture
def server(monkeypatch):
    """httpx.Client를 MockTransport를 물린 것으로 바꿔치운다(test_tei.py와 같은 방식)."""
    real_client = httpx.Client
    fake = FakeServer()
    monkeypatch.setattr(
        openai_compat.httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(fake.dispatch), **kwargs),
    )
    return fake


CONVERSATION = [
    ChatMessage(role="user", text="첫 질문"),
    ChatMessage(role="assistant", text="첫 답변"),
    ChatMessage(role="user", text="그거 다시"),
]

TOOLS = [
    Tool(
        "search_history",
        "기록을 찾는다.",
        {"type": "object", "properties": {"query": {"type": "string", "description": "검색어만 남긴다."}}},
    ),
    Tool("chat", "잡담."),
]


@pytest.mark.parametrize(
    "base_url",
    [BASE_URL, f"{BASE_URL}/", f"{BASE_URL}/v1", f"{BASE_URL}/v1/chat/completions"],
)
def test_any_spelling_of_the_server_reaches_the_same_endpoint(base_url):
    assert _endpoint(base_url) == f"{BASE_URL}/v1/chat/completions"


def test_a_missing_server_address_is_reported_up_front():
    with pytest.raises(LlmError, match="주소"):
        OpenAICompatGenerator("", "qwen3.5:4b")


def test_text_generation_sends_the_instruction_first_and_the_roles_as_they_are(server):
    reply = OpenAICompatGenerator(BASE_URL, "qwen3.5:4b").generate_text("지시", CONVERSATION)

    body = server.bodies[0]
    assert reply == "안녕하세요"
    assert body["model"] == "qwen3.5:4b"
    assert body["stream"] is False
    assert body["messages"] == [
        {"role": "system", "content": "지시"},
        {"role": "user", "content": "첫 질문"},
        {"role": "assistant", "content": "첫 답변"},
        {"role": "user", "content": "그거 다시"},
    ]
    assert "response_format" not in body


def test_thinking_mixed_into_the_answer_is_dropped(server):
    server.answer("<think>사용자가 인사했다.\n뭐라고 할까</think>\n\n안녕하세요")

    assert OpenAICompatGenerator(BASE_URL, "m").generate_text("지시", CONVERSATION) == "안녕하세요"


def test_the_api_key_and_reasoning_effort_go_out_only_when_set(server):
    OpenAICompatGenerator(BASE_URL, "m").generate_text("지시", CONVERSATION)
    OpenAICompatGenerator(BASE_URL, "m", api_key="sk-test", reasoning_effort="none").generate_text(
        "지시", CONVERSATION
    )

    bare, configured = server.bodies
    assert "authorization" not in server.headers[0]
    assert "reasoning_effort" not in bare
    assert server.headers[1]["authorization"] == "Bearer sk-test"
    assert configured["reasoning_effort"] == "none"


def test_choosing_a_tool_constrains_the_answer_and_spells_out_the_tools(server):
    server.answer('{"tool": "search_history", "arguments": {"query": "김치찌개"}}')

    calls = OpenAICompatGenerator(BASE_URL, "m").choose_tool("지시", CONVERSATION, TOOLS)

    body = server.bodies[0]
    branches = body["response_format"]["json_schema"]["schema"]["anyOf"]
    assert [branch["properties"]["tool"]["enum"] for branch in branches] == [["search_history"], ["chat"]]
    # 서버는 schema를 모델에게 보여주지 않으므로 도구 설명과 필드 규칙이 지시에 실려야 한다.
    system = body["messages"][0]["content"]
    assert system.startswith("지시")
    assert "search_history: 기록을 찾는다." in system
    assert "검색어만 남긴다." in system
    assert calls == [ToolCall(name="search_history", args={"query": "김치찌개"})]


@pytest.mark.parametrize(
    "content",
    ["무엇을 도와드릴까요?", '{"arguments": {}}', '["chat"]'],
    ids=["prose", "no tool name", "not an object"],
)
def test_an_answer_that_is_not_a_tool_call_gives_no_calls(server, content):
    server.answer(content)

    assert OpenAICompatGenerator(BASE_URL, "m").choose_tool("지시", CONVERSATION, TOOLS) == []


def test_a_tool_without_arguments_comes_back_with_empty_args(server):
    server.answer('{"tool": "chat", "arguments": null}')

    assert OpenAICompatGenerator(BASE_URL, "m").choose_tool("지시", CONVERSATION, TOOLS) == [ToolCall("chat")]


def test_a_structured_answer_comes_back_as_the_schema(server):
    server.answer('{"title": "이번 달"}')

    plan = OpenAICompatGenerator(BASE_URL, "m").generate_structured("지시", CONVERSATION, Plan)

    body = server.bodies[0]
    assert plan == Plan(title="이번 달")
    assert body["response_format"]["json_schema"]["name"] == "Plan"
    assert "대시보드 제목." in body["messages"][0]["content"]


def test_an_unreadable_structured_answer_gives_none(server):
    server.answer('{"heading": "이번 달"}')

    assert OpenAICompatGenerator(BASE_URL, "m").generate_structured("지시", CONVERSATION, Plan) is None


@pytest.mark.parametrize(
    ("handler", "reason"),
    [
        (lambda request: httpx.Response(404, text='{"error":"model \\"nope\\" not found"}'), "404"),
        (lambda request: httpx.Response(200, text="<html>"), "JSON"),
        (lambda request: httpx.Response(200, json={"choices": []}), "choices"),
        (lambda request: httpx.Response(200, json=completion(None)), "빈 답변"),
    ],
    ids=["http error", "not json", "no choices", "null content"],
)
def test_a_failing_server_raises_an_llm_error(server, handler, reason):
    server.handler = handler

    with pytest.raises(LlmError, match=reason):
        OpenAICompatGenerator(BASE_URL, "m").generate_text("지시", CONVERSATION)


def test_an_unreachable_server_raises_an_llm_error(server):
    def refuse(request):
        raise httpx.ConnectError("connection refused", request=request)

    server.handler = refuse

    with pytest.raises(LlmError, match="연결할 수 없습니다"):
        OpenAICompatGenerator(BASE_URL, "m").generate_text("지시", CONVERSATION)


def test_an_llm_error_reaches_the_client_as_502_with_its_reason():
    app = FastAPI()
    app.add_exception_handler(LlmError, llm_unavailable)

    @app.get("/boom")
    def boom():
        raise LlmError("생성 모델 서버에 연결할 수 없습니다")

    response = TestClient(app).get("/boom")

    assert response.status_code == 502
    assert response.json() == {"detail": "생성 모델 서버에 연결할 수 없습니다"}


def test_the_model_list_is_read_from_v1_models(server):
    server.handler = lambda request: httpx.Response(
        200, json={"object": "list", "data": [{"id": "qwen3.5:4b"}, {"id": "llama3.2:3b"}, {"object": "model"}]}
    )

    assert list_models(f"{BASE_URL}/v1", api_key="sk-test") == ["llama3.2:3b", "qwen3.5:4b"]
    assert server.urls == [f"{BASE_URL}/v1/models"]
    assert server.headers[0]["authorization"] == "Bearer sk-test"


def test_a_model_list_without_data_raises_an_llm_error(server):
    server.handler = lambda request: httpx.Response(200, json={"models": []})

    with pytest.raises(LlmError, match="data"):
        list_models(BASE_URL)
