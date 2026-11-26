"""사용자 입력을 의도와 검색어, 메타데이터로 해석한다.

의도마다 도구를 하나씩 두고, 모델이 그중 하나를 골라 호출하게 한다(function calling). 어떤 도구를
골랐는지가 곧 의도이고, 그 도구의 인자가 그 의도에 필요한 값이다. 의도 하나에 모든 필드를 담는
단일 스키마로 받으면 'detail이 아니면 target_index는 null' 같은 조건부 규칙을 지시문으로 부탁해야
하는데, 도구로 나누면 그런 필드가 애초에 다른 도구에 없다. 각 필드의 뜻도 지시문 대신 그 필드의
description에 적어 두어, 모델이 인자를 채우는 바로 그 자리에서 보게 한다.

모델 쪽 표현(도구 인자)은 여기서 ParsedQuery로 바꿔 내보낸다. 호출하는 쪽은 도구가 무엇인지 모른다.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from loguru import logger
from pydantic import BaseModel, Field, ValidationError

from backend.models.conversation import Message
from backend.models.document import Document
from backend.services.chat.intent import Intent
from backend.services.chat.timerange import TimeRange, local_now
from backend.services.conversation.prompt import format_listing, render_history
from backend.services.llm.generation import ChatMessage, Tool, ToolCall, json_schema_of
from backend.services.llm.provider import get_generator


class ParsedQuery(BaseModel):
    """rewrite_query의 결과. 어느 도구가 불렸든 이 모양으로 맞춰 내보낸다."""

    intent: Intent
    target_index: int | None = None
    time_range: TimeRange = TimeRange()
    query: str
    desired_count: int | None = None


# 아래 도구 인자 모델의 docstring은 도구 설명으로, 필드 description은 인자 설명으로 그대로 모델에
# 전달된다. 설명은 모델에게 도움이 될 만큼만 적고, 설계 근거는 주석으로 남긴다.


class SearchHistory(BaseModel):
    """과거에 방문했거나 열람한 웹 페이지·사이트·글을 기록에서 새로 찾는다. 차트나 그래프를 다룬 글을
    찾는 것('d3 차트 글 찾아줘')도 여기다. 앞선 대화의 결과 목록에서 하나를 지목할 수 없거나 기록을
    새로 뒤져야 하면 이 도구를 쓴다."""

    # time_range가 query보다 앞이다. 시간 표현을 먼저 떼어내야 그것을 뺀 검색어를 쓰게 된다 —
    # "어제"가 검색어에 남으면 그 낱말로 본문을 뒤져 엉뚱한 문서가 걸린다.
    time_range: TimeRange = Field(default_factory=TimeRange, description="찾을 기록의 기간.")
    query: str = Field(
        description=(
            "검색 엔진에 넣기 좋은 간결한 한국어 검색어. 대화체·잡담·존댓말은 빼고 핵심 주제와 키워드만 "
            "남긴다. 시간 표현은 빼고 time_range에 담는다 — '어제 본 리액트 상태관리 글'이면 "
            "'리액트 상태관리'다. 시간 표현을 빼면 남는 것이 없는 질의('어제 본 거 다 보여줘')는 빈 문자열."
        )
    )
    desired_count: int | None = Field(
        None, description="'3개만', '다섯 개 찾아줘'처럼 결과 개수를 명시했을 때만 그 숫자. 아니면 null."
    )


class ShowDetail(BaseModel):
    """앞선 대화에서 이미 보여준 번호 붙은 결과 목록 중 하나를 지목해 그 페이지의 내용을 더 묻는다.
    '두 번째 것 자세히', '첫 번째 링크 내용이 뭐였지', '거기 가격 얼마였어'처럼 지목한 대상이 목록 안에
    있어야 한다. 목록이 없거나 하나로 좁힐 수 없으면 이 도구가 아니라 search_history다."""

    # target_index가 title_hint보다 앞이다. 지목한 대상을 먼저 정해야 그 제목을 적을 수 있다.
    target_index: int = Field(
        description=(
            "지목한 항목의 목록 번호. 순서('두 번째'), 제목의 일부, 사이트 이름이나 주소 등 무엇으로 "
            "가리켰든 목록에서 그 항목을 찾아 번호로 바꾼다."
        )
    )
    # 번호가 목록 범위를 벗어났을 때 제목으로 다시 찾는 근거다(services/chat/detail.py).
    title_hint: str = Field(description="지목한 항목을 특정할 수 있는 제목이나 키워드.")


class BuildDashboard(BaseModel):
    """기록을 하나하나 찾는 대신 모아서 세거나 그래프·차트·대시보드·통계로 보여준다. '이번 달 사이트별로
    몇 개 봤어', '요일별 추이 그래프', '지난주에 리액트 글 몇 개 읽었지'처럼 답이 페이지 목록이 아니라
    숫자나 그래프인 질의다. 앞서 만든 대시보드를 '주별로 바꿔줘'처럼 고치라는 요청도 여기다."""

    # 무엇을 셀지는 여기서 받지 않는다. 그것은 대시보드 계획 호출(services/dashboard/planner.py)이
    # 카탈로그를 보고 정한다. 기간만은 검색과 같은 규칙으로 풀어야 해서 여기서 받는다.
    time_range: TimeRange = Field(
        default_factory=TimeRange,
        description=(
            "대시보드가 볼 기간. 앞서 만든 대시보드를 고치는 요청이 기간을 새로 말하지 않았으면 그 "
            "대시보드의 기간을 그대로 담는다."
        ),
    )


class Chat(BaseModel):
    """기록을 찾거나 세는 것과 무관한 잡담이나 일반 질문."""


@dataclass(frozen=True)
class _Tool:
    name: str
    arguments: type[BaseModel]


_TOOLS = (
    _Tool("search_history", SearchHistory),
    _Tool("show_detail", ShowDetail),
    _Tool("build_dashboard", BuildDashboard),
    _Tool("chat", Chat),
)
_TOOLS_BY_NAME = {tool.name: tool for tool in _TOOLS}


SYSTEM_INSTRUCTION = (
    "너는 사용자의 웹 방문 기록을 다루는 도우미의 질의 해석기다. 마지막 사용자 메시지를 읽고 주어진 "
    "도구 중 정확히 하나를 골라 호출하라. "
    "앞선 대화와 결과 목록은 맥락 파악에만 쓰고, 판단의 대상은 항상 마지막 사용자 메시지다. "
    "'그거', '아까 그 사이트', '두 번째 것'처럼 앞선 대화를 가리키는 표현은 대화에서 그 대상을 찾아 "
    "구체적인 명사나 제목으로 바꿔 인자에 담아라. 가리키는 대상을 찾을 수 없으면 그 표현은 버려라."
)


def _declare(tool: _Tool) -> Tool:
    schema = json_schema_of(tool.arguments)
    description = schema.pop("description")
    schema.pop("title", None)
    return Tool(
        name=tool.name,
        description=description,
        # 인자가 없는 도구에 빈 object 스키마를 붙이지 않는다.
        parameters=schema if schema.get("properties") else None,
    )


_WEEKDAYS = ("월", "화", "수", "목", "금", "토", "일")


def _system_instruction(client_now: datetime | None) -> str:
    """지시에 오늘 날짜를 붙인다.

    '8월 20일에 본 거'가 몇 년의 8월 20일인지, '지난달'이 몇 월인지는 오늘을 알아야 정해진다.
    모델은 자기가 언제 불렸는지 모르므로 여기서 알려준다. 라벨(yesterday 등)의 실제 구간 계산은
    services/chat/timerange.py가 하지만, absolute로 말한 날짜만은 모델이 적어야 해서 필요하다.

    날짜는 사용자의 로컬 기준이다. UTC로 알려주면 밤늦은 질의에서 하루가 어긋난다.
    """
    now = local_now(client_now)
    return f"{SYSTEM_INSTRUCTION} 오늘은 {now:%Y-%m-%d}({_WEEKDAYS[now.weekday()]}요일)이다."


def _build_contents(
    message: str,
    history: Sequence[Message],
    candidates: Sequence[Document] = (),
    shown: Mapping[int, Sequence[Document]] = {},
) -> list[ChatMessage]:
    """앞선 대화를 옮기고(services/conversation/prompt.py) 후보 목록과 이번 입력을 뒤에 붙인다.

    후보 목록은 이번 입력 바로 앞에 번호를 붙여 끼운다. 목록을 따로 보여줘야 판단과 번호 지목이
    같은 것을 보고 이뤄진다. 별개의 발화로 두는 것은 '판단 대상은 마지막 사용자 메시지'라는 지시를
    흐리지 않기 위해서다. 이 목록과 겹치는 직전 턴은 shown에서 미리 빠져 있다(results.past_shown).
    """
    messages = render_history(history, shown)
    if candidates:
        messages.append(ChatMessage(role="user", text=f"직전에 보여준 결과 목록:\n{format_listing(candidates)}"))
    messages.append(ChatMessage(role="user", text=message))
    return messages


def rewrite_query(
    message: str,
    history: Sequence[Message] = (),
    candidates: Sequence[Document] = (),
    shown: Mapping[int, Sequence[Document]] = {},
    client_now: datetime | None = None,
) -> ParsedQuery:
    """사용자 입력을 의도와 검색어, 메타데이터(기간·원하는 결과 개수)로 한 번에 해석한다.

    history를 넘기면 그 대화를 맥락으로 삼아 '그거', '아까 그 사이트' 같은 지시 표현을 풀어낸다.
    candidates는 직전에 보여준 결과 목록으로, 지목된 항목의 번호를 target_index로 받는 근거가 된다.
    shown은 그보다 앞선 턴들이 보여준 목록이라, '아까 두 번째로 찾아준 그거'처럼 직전 턴을 넘어
    거슬러 가리키는 표현을 풀어낼 근거가 된다.
    client_now는 사용자의 현재 시각으로, 날짜를 직접 말한 질의의 연도·월을 정하는 데 쓰인다.
    """
    generator = get_generator()
    logger.debug(
        "rewriting query via {}: {!r} (history={} message(s), candidates={}, listed turns={})",
        generator.model,
        message,
        len(history),
        len(candidates),
        len(shown),
    )
    # 잡담도 chat 도구로 받으므로 어떤 입력이든 도구 하나가 골라져야 한다.
    calls = generator.choose_tool(
        _system_instruction(client_now),
        _build_contents(message, history, candidates, shown),
        [_declare(tool) for tool in _TOOLS],
    )
    parsed = _parse_call(calls, message)
    if parsed is None:
        # 의도까지 못 받은 상황이라 검색으로 밀어봐야 원문 그대로 찾는 헛질의가 된다. etc로 두어
        # 일반 대화로 답하게 한다(분류 실패 시의 기존 동작과 같다).
        logger.warning("query rewrite unparsable, falling back to raw message: {!r}", message)
        return ParsedQuery(intent=Intent.ETC, query=message)
    return parsed


def _parse_call(calls: Sequence[ToolCall], message: str) -> ParsedQuery | None:
    """모델이 부른 도구를 ParsedQuery로 바꾼다. 알아볼 수 없는 호출이면 None."""
    if not calls:
        return None
    if len(calls) > 1:
        # 도구는 하나만 고르라고 했다. 여러 개가 오면 먼저 고른 것을 따른다.
        logger.warning("query rewrite called {} tools, using the first: {}", len(calls), [c.name for c in calls])
    call = calls[0]
    tool = _TOOLS_BY_NAME.get(call.name)
    if tool is None:
        logger.warning("query rewrite called an unknown tool: {!r}", call.name)
        return None
    try:
        arguments = tool.arguments.model_validate(call.args)
    except ValidationError as error:
        logger.warning("query rewrite gave invalid arguments for {}: {}", call.name, error)
        return None

    match arguments:
        case SearchHistory():
            return ParsedQuery(
                intent=Intent.RECALL,
                time_range=arguments.time_range,
                query=arguments.query,
                desired_count=arguments.desired_count,
            )
        case ShowDetail():
            return ParsedQuery(intent=Intent.DETAIL, target_index=arguments.target_index, query=arguments.title_hint)
        # dashboard와 etc에는 검색어가 쓰이지 않는다. 원문을 그대로 실어 둔다.
        case BuildDashboard():
            return ParsedQuery(intent=Intent.DASHBOARD, time_range=arguments.time_range, query=message)
        case _:
            return ParsedQuery(intent=Intent.ETC, query=message)
