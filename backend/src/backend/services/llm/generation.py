"""생성 모델을 부르는 쪽이 보는 모양. 어느 제공자인지는 여기서 드러나지 않는다.

질의 재작성·대시보드 구성·답변 생성이 Gemini SDK의 types.Content 같은 것을 직접 만들고 있으면
제공자를 하나 더할 때 세 곳을 모두 고쳐야 한다. 대화는 ChatMessage로, 도구는 Tool로 넘기고
제공자별 모양으로 옮기는 일은 각 구현(services.llm.gemini 등)이 맡는다.
"""

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel

Role = Literal["user", "assistant"]

T = TypeVar("T", bound=BaseModel)


class LlmError(RuntimeError):
    """생성 모델 호출이 실패했다(연결·HTTP 오류·응답 형식). 메시지는 사용자에게 그대로 보여줄 수 있다."""


@dataclass(frozen=True)
class ChatMessage:
    """대화 한 마디. 제공자마다 assistant를 부르는 이름이 다르므로(Gemini는 model) 옮기는 쪽이 바꾼다."""

    role: Role
    text: str


@dataclass(frozen=True)
class Tool:
    """모델이 고를 수 있는 도구 하나.

    parameters는 $ref를 풀어 둔 JSON Schema다. 제공자마다 받아주는 범위가 달라 $defs를 넘기면
    거절하는 곳이 있다. 인자가 없는 도구는 None이다.
    """

    name: str
    description: str
    parameters: dict[str, Any] | None = None


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict[str, Any] = field(default_factory=dict)


class Generator(Protocol):
    """생성 모델 하나. 어떤 모델을 쓰는지는 만들 때 정해져 있다."""

    @property
    def model(self) -> str:
        """로그에 남길 모델 이름."""
        ...

    def generate_text(self, system: str, messages: list[ChatMessage]) -> str:
        """지시와 대화를 주고 답변 문장을 받는다."""
        ...

    def choose_tool(self, system: str, messages: list[ChatMessage], tools: list[Tool]) -> list[ToolCall]:
        """주어진 도구 중 하나를 반드시 고르게 한다. 고르지 않고 말로 답했으면 빈 목록이다."""
        ...

    def generate_structured(self, system: str, messages: list[ChatMessage], schema: type[T]) -> T | None:
        """schema 모양의 JSON으로 답하게 한다. 그 모양으로 읽을 수 없으면 None."""
        ...


def json_schema_of(model: type[BaseModel]) -> dict[str, Any]:
    """pydantic 모델의 JSON Schema를 $defs 없이 만든다.

    pydantic은 하위 모델을 $defs로 빼 두고 $ref로 가리키는데, 제공자마다 받아주는 JSON Schema의
    범위가 달라 $ref를 거절하는 곳이 있다. 제자리에 풀어 두면 어느 쪽에도 그대로 건넬 수 있다.
    """
    schema = model.model_json_schema()
    definitions = schema.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                target = definitions[node["$ref"].rsplit("/", 1)[-1]]
                # $ref 옆에 붙은 description 같은 키가 정의 쪽 값보다 이 자리에 맞는 설명이다.
                return resolve({**target, **{key: value for key, value in node.items() if key != "$ref"}})
            return {key: resolve(value) for key, value in node.items()}
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    return resolve(schema)
