"""Gemini 클라이언트를 한 곳에서 만들고, 생성 호출을 Generator 모양으로 감싼다.

answer·embedding·query_parser가 각자 클라이언트를 캐시하고 있었는데, API key를 화면에서 바꿀 수
있게 되면서 세 캐시를 동시에 버려야 하는 문제가 생겼다. 캐시를 여기 하나로 모으고 key가 바뀌면
새로 만든다.
"""

from google import genai
from google.genai import types
from loguru import logger

from backend.services.llm.generation import ChatMessage, T, Tool, ToolCall
from backend.services.runtime_settings import get_settings

_client: genai.Client | None = None
_client_api_key: str | None = None

# Gemini의 contents는 assistant 발화를 "model" 역할로 받는다.
_ROLES = {"user": "user", "assistant": "model"}


def get_client() -> genai.Client:
    """지금 설정된 API key로 만든 클라이언트. key가 바뀌었으면 새로 만든다."""
    global _client, _client_api_key

    api_key = get_settings().gemini_api_key
    if not api_key:
        # 여기서 막지 않으면 클라이언트 생성이나 첫 호출에서 맥락 없는 오류가 난다.
        raise RuntimeError("Gemini API key가 설정되지 않았습니다. 설정 화면에서 입력해 주세요.")

    if _client is None or _client_api_key != api_key:
        _client = genai.Client(api_key=api_key)
        _client_api_key = api_key
    return _client


def to_contents(messages: list[ChatMessage]) -> list[types.Content]:
    return [types.Content(role=_ROLES[message.role], parts=[types.Part(text=message.text)]) for message in messages]


def to_declaration(tool: Tool) -> types.FunctionDeclaration:
    return types.FunctionDeclaration(
        name=tool.name,
        description=tool.description,
        parameters_json_schema=tool.parameters,
    )


class GeminiGenerator:
    """Gemini로 생성한다. 클라이언트는 호출할 때마다 get_client로 받아 key 변경을 따라간다."""

    def __init__(self, model: str) -> None:
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    def generate_text(self, system: str, messages: list[ChatMessage]) -> str:
        response = get_client().models.generate_content(
            model=self._model,
            contents=to_contents(messages),
            config=types.GenerateContentConfig(system_instruction=system),
        )
        return response.text.strip()

    def choose_tool(self, system: str, messages: list[ChatMessage], tools: list[Tool]) -> list[ToolCall]:
        response = get_client().models.generate_content(
            model=self._model,
            contents=to_contents(messages),
            config=types.GenerateContentConfig(
                system_instruction=system,
                tools=[types.Tool(function_declarations=[to_declaration(tool) for tool in tools])],
                # 도구를 부르지 않고 말로 답해버리는 응답을 막는다.
                tool_config=types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(mode=types.FunctionCallingConfigMode.ANY)
                ),
            ),
        )
        calls = response.function_calls or []
        if not calls:
            logger.warning("gemini answered without calling a tool: {!r}", response.text)
        return [ToolCall(name=call.name or "", args=call.args or {}) for call in calls]

    def generate_structured(self, system: str, messages: list[ChatMessage], schema: type[T]) -> T | None:
        response = get_client().models.generate_content(
            model=self._model,
            contents=to_contents(messages),
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_schema=schema,
            ),
        )
        if not isinstance(response.parsed, schema):
            logger.warning("gemini structured response unparsable as {}: {!r}", schema.__name__, response.text)
            return None
        return response.parsed
