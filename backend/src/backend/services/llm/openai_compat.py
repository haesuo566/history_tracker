"""OpenAI 호환 `/v1/chat/completions`로 생성한다.

Ollama·vLLM·LM Studio·llama.cpp server가 모두 이 규약을 내놓으므로, 로컬 LLM은 이 파일 하나로
붙는다. OpenAI·OpenRouter 같은 원격 서비스도 같다.

도구 고르기와 구조화 응답은 둘 다 `response_format: json_schema`로 받는다. 도구 호출을 강제하는
`tool_choice: required`는 서버마다 지원이 들쭉날쭉한 반면, json_schema는 대부분의 서버가 문법 제약
생성으로 구현해 작은 모델에서도 형식이 깨지지 않는다.

다만 서버는 schema를 디코딩 제약으로만 쓸 뿐 모델에게 보여주지 않는다(Ollama가 그렇다). 필드
description에 적어 둔 규칙이 모델에 닿으려면 schema를 지시에도 함께 실어야 한다.
"""

import json
import re
from typing import Any

import httpx
from loguru import logger
from pydantic import ValidationError

from backend.services.llm.generation import (
    ChatMessage,
    LlmError,
    T,
    Tool,
    ToolCall,
    json_schema_of,
)

# 로컬 CPU·작은 GPU에서는 응답 하나에 수십 초가 걸린다. 무한정 기다리지는 않되 넉넉히 잡는다.
TIMEOUT_SECONDS = 180.0

# 추론 모델이 생각을 본문에 섞어 내는 서버가 있다. 답변이나 JSON 앞에 붙으면 그대로 쓸 수 없다.
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


def _root(base_url: str) -> str:
    """설정에 담긴 주소에서 서버 루트를 골라낸다.

    `http://host:11434`, `.../v1`, `.../v1/chat/completions` 중 무엇을 넣어도 같은 서버를 가리키게
    한다 — 어느 쪽으로 적어야 하는지는 화면만 보고 알 수 없다.
    """
    trimmed = base_url.rstrip("/")
    for suffix in ("/v1/chat/completions", "/chat/completions", "/v1"):
        if trimmed.endswith(suffix):
            return trimmed[: -len(suffix)]
    return trimmed


def _endpoint(base_url: str) -> str:
    return f"{_root(base_url)}/v1/chat/completions"


# 목록 조회는 설정 화면이 기다린다. 생성과 달리 서버가 살아 있으면 바로 답한다.
LIST_TIMEOUT_SECONDS = 10.0


def list_models(base_url: str, api_key: str | None = None) -> list[str]:
    """서버에 올라가 있는 모델 이름들(`GET /v1/models`). 설정 화면의 선택지와 연결 확인에 쓴다."""
    url = f"{_root(base_url)}/v1/models"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        with httpx.Client(timeout=LIST_TIMEOUT_SECONDS) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as error:
        raise LlmError(f"모델 목록 조회에 {error.response.status_code}가 돌아왔습니다: {url}") from error
    except httpx.HTTPError as error:
        raise LlmError(f"생성 모델 서버({url})에 연결할 수 없습니다: {error}") from error
    except ValueError as error:
        raise LlmError("모델 목록 응답을 JSON으로 해석할 수 없습니다.") from error

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise LlmError("모델 목록 응답에 data 배열이 없습니다.")
    return sorted({item["id"] for item in data if isinstance(item, dict) and isinstance(item.get("id"), str)})


def _dump(schema: dict[str, Any]) -> str:
    return json.dumps(schema, ensure_ascii=False)


def _tools_instruction(tools: list[Tool]) -> str:
    """도구 목록과 답하는 형식을 지시로 풀어 쓴다. 도구 호출 규약을 쓰지 않으므로 모델이 볼 곳이 여기뿐이다."""
    described = "\n".join(
        f"- {tool.name}: {tool.description}\n  arguments 스키마: {_dump(tool.parameters) if tool.parameters else '{}'}"
        for tool in tools
    )
    return (
        "\n\n사용할 수 있는 도구:\n"
        f"{described}\n\n"
        '반드시 {"tool": "<도구 이름>", "arguments": {...}} 모양의 JSON 하나로만 답하라. '
        "arguments는 고른 도구의 스키마를 따르고, 스키마의 description에 적힌 규칙을 지켜라."
    )


def _call_schema(tools: list[Tool]) -> dict[str, Any]:
    """도구 하나를 고른 결과의 schema. 도구마다 갈래를 두어, 이름과 인자가 서로 맞게 묶이게 한다."""
    return {
        "anyOf": [
            {
                "type": "object",
                "properties": {
                    "tool": {"type": "string", "enum": [tool.name]},
                    "arguments": tool.parameters or {"type": "object", "properties": {}},
                },
                "required": ["tool", "arguments"],
            }
            for tool in tools
        ]
    }


class OpenAICompatGenerator:
    """OpenAI 호환 서버로 생성한다.

    reasoning_effort는 추론 모델의 생각 분량이다. Ollama에서 "none"을 주면 생각을 건너뛰어 응답이
    열 배 넘게 빨라진다. 이 필드를 모르는 서버가 있어 값이 있을 때만 보낸다.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        if not base_url:
            raise LlmError("생성 모델 서버 주소가 설정되지 않았습니다. 설정 화면에서 입력해 주세요.")
        self._url = _endpoint(base_url)
        self._model = model
        self._api_key = api_key
        self._reasoning_effort = reasoning_effort

    @property
    def model(self) -> str:
        return self._model

    def generate_text(self, system: str, messages: list[ChatMessage]) -> str:
        return self._complete(system, messages)

    def choose_tool(self, system: str, messages: list[ChatMessage], tools: list[Tool]) -> list[ToolCall]:
        content = self._complete(
            system + _tools_instruction(tools),
            messages,
            response_format={"type": "json_schema", "json_schema": {"name": "tool_call", "schema": _call_schema(tools)}},
        )
        try:
            payload = json.loads(content)
        except ValueError:
            logger.warning("model answered without a tool call: {!r}", content)
            return []
        if not isinstance(payload, dict) or not isinstance(payload.get("tool"), str):
            logger.warning("tool call has no tool name: {!r}", content)
            return []
        arguments = payload.get("arguments")
        return [ToolCall(name=payload["tool"], args=arguments if isinstance(arguments, dict) else {})]

    def generate_structured(self, system: str, messages: list[ChatMessage], schema: type[T]) -> T | None:
        json_schema = json_schema_of(schema)
        content = self._complete(
            f"{system}\n\n반드시 다음 JSON Schema를 따르는 JSON 하나로만 답하라. 스키마의 description에 "
            f"적힌 규칙을 지켜라.\n{_dump(json_schema)}",
            messages,
            response_format={"type": "json_schema", "json_schema": {"name": schema.__name__, "schema": json_schema}},
        )
        try:
            return schema.model_validate_json(content)
        except ValidationError as error:
            logger.warning("structured response unparsable as {}: {} ({!r})", schema.__name__, error, content)
            return None

    def _complete(self, system: str, messages: list[ChatMessage], **extra: Any) -> str:
        body: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                *({"role": message.role, "content": message.text} for message in messages),
            ],
            "stream": False,
            **extra,
        }
        if self._reasoning_effort:
            body["reasoning_effort"] = self._reasoning_effort
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}

        try:
            with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
                response = client.post(self._url, json=body, headers=headers)
                response.raise_for_status()
                payload = response.json()
        except httpx.TimeoutException as error:
            raise LlmError(f"생성 모델 서버가 {TIMEOUT_SECONDS:.0f}초 안에 답하지 않았습니다.") from error
        except httpx.HTTPStatusError as error:
            # 본문에 모델 이름 오타, 지원하지 않는 필드 같은 사유가 담겨 온다.
            detail = error.response.text[:200]
            raise LlmError(f"생성 모델 서버가 {error.response.status_code}를 반환했습니다: {detail}") from error
        except httpx.HTTPError as error:
            raise LlmError(f"생성 모델 서버({self._url})에 연결할 수 없습니다: {error}") from error
        except ValueError as error:
            raise LlmError("생성 모델 서버의 응답을 JSON으로 해석할 수 없습니다.") from error

        return _content_of(payload)


def _content_of(payload: object) -> str:
    """응답에서 답변 본문을 꺼낸다. 본문에 섞여 온 생각 구간은 걷어낸다."""
    try:
        content = payload["choices"][0]["message"]["content"]  # type: ignore[index]
    except (KeyError, IndexError, TypeError) as error:
        raise LlmError("생성 모델 서버의 응답에 choices[0].message.content가 없습니다.") from error
    if not isinstance(content, str):
        raise LlmError("생성 모델 서버가 빈 답변을 돌려줬습니다.")
    return _THINK.sub("", content).strip()
