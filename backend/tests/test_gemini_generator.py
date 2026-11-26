from types import SimpleNamespace

import pytest
from google.genai import types
from pydantic import BaseModel

from backend.services.llm import gemini as gemini_service
from backend.services.llm.gemini import GeminiGenerator
from backend.services.llm.generation import ChatMessage, Tool, ToolCall


class Plan(BaseModel):
    title: str


def response_with(*parts: types.Part) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=list(parts)))]
    )


@pytest.fixture
def gemini(monkeypatch):
    """GeminiGenerator가 SDK에 보낸 요청을 담고, 정해 둔 응답을 돌려주게 한다."""
    sent: dict = {}
    reply = SimpleNamespace(response=response_with(types.Part(text="")))

    def generate_content(**request):
        sent.update(request)
        return reply.response

    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    monkeypatch.setattr(gemini_service, "get_client", lambda: client)
    return SimpleNamespace(sent=sent, reply=reply)


CONVERSATION = [
    ChatMessage(role="user", text="첫 질문"),
    ChatMessage(role="assistant", text="첫 답변"),
    ChatMessage(role="user", text="그거 다시"),
]


def test_the_assistant_speaks_as_model(gemini):
    """Gemini는 assistant 발화를 model 역할로만 받는다."""
    gemini.reply.response = response_with(types.Part(text="답"))

    GeminiGenerator("test-model").generate_text("지시", CONVERSATION)

    assert [(content.role, content.parts[0].text) for content in gemini.sent["contents"]] == [
        ("user", "첫 질문"),
        ("model", "첫 답변"),
        ("user", "그거 다시"),
    ]


def test_text_generation_sends_the_model_and_the_instruction(gemini):
    gemini.reply.response = response_with(types.Part(text="  안녕하세요  \n"))

    reply = GeminiGenerator("test-model").generate_text("지시", CONVERSATION)

    assert reply == "안녕하세요"
    assert gemini.sent["model"] == "test-model"
    assert gemini.sent["config"].system_instruction == "지시"


def test_choosing_a_tool_forces_a_call_and_returns_it(gemini):
    gemini.reply.response = response_with(
        types.Part(function_call=types.FunctionCall(name="search_history", args={"query": "김치찌개"}))
    )
    tools = [
        Tool("search_history", "기록을 찾는다.", {"type": "object", "properties": {"query": {"type": "string"}}}),
        Tool("chat", "잡담."),
    ]

    calls = GeminiGenerator("test-model").choose_tool("지시", CONVERSATION, tools)

    config = gemini.sent["config"]
    assert config.tool_config.function_calling_config.mode is types.FunctionCallingConfigMode.ANY
    declarations = config.tools[0].function_declarations
    assert [d.name for d in declarations] == ["search_history", "chat"]
    assert declarations[1].parameters_json_schema is None
    assert calls == [ToolCall(name="search_history", args={"query": "김치찌개"})]


def test_answering_in_words_instead_of_a_tool_gives_no_calls(gemini):
    gemini.reply.response = response_with(types.Part(text="무엇을 도와드릴까요?"))

    assert GeminiGenerator("test-model").choose_tool("지시", CONVERSATION, [Tool("chat", "잡담.")]) == []


def test_a_structured_answer_comes_back_as_the_schema(gemini):
    gemini.reply.response = SimpleNamespace(parsed=Plan(title="이번 달"), text='{"title": "이번 달"}')

    plan = GeminiGenerator("test-model").generate_structured("지시", CONVERSATION, Plan)

    assert plan == Plan(title="이번 달")
    assert gemini.sent["config"].response_schema is Plan
    assert gemini.sent["config"].response_mime_type == "application/json"


def test_an_unreadable_structured_answer_gives_none(gemini):
    gemini.reply.response = SimpleNamespace(parsed=None, text="모르겠어요")

    assert GeminiGenerator("test-model").generate_structured("지시", CONVERSATION, Plan) is None
