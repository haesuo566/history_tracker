"""사용자 질의를 대시보드 구성(DashboardPlan)으로 옮긴다 — 모델이 하는 일은 여기까지다.

모델은 시멘틱 레이어(services/dashboard/semantic_layer.py)의 이름을 고르기만 하고, 그 이름을 SQL 로
옮기고 실행하는 것은 services/dashboard/builder.py 다. 모델에게 SQL 을 쓰게 하면 없는 컬럼을 만들어
내거나 조용히 틀린 집계를 하는데, 그 결과가 숫자라 틀렸다는 것이 드러나지 않는다.

기간은 여기서 받지 않는다. 재작성 호출(services/chat/query_parser.py)이 이미 time_range 로 받아
구간으로 풀어 두었으므로, 같은 판단을 두 번 시켜 서로 다른 답을 얻을 이유가 없다.
"""

import re
from collections.abc import Mapping, Sequence

from google.genai import types
from loguru import logger

from backend.models.conversation import Message, MessageRole
from backend.models.document import Document
from backend.schemas.dashboard import Dashboard, DashboardPlan
from backend.services.chat.timerange import TimeWindow
from backend.services.conversation.prompt import render_history
from backend.services.dashboard.semantic_layer import catalog
from backend.services.llm.gemini import get_client
from backend.services.runtime_settings import get_settings

SYSTEM_INSTRUCTION = (
    "너는 사용자의 웹 브라우징 기록으로 대시보드를 구성한다. 마지막 사용자 메시지를 아래 시멘틱 "
    "레이어의 측정값·기준·조건만으로 표현한 구성(JSON)으로 바꿔라. "
    "앞선 대화는 '그거 주별로 바꿔줘'처럼 앞서 만든 대시보드를 고치는 요청을 알아듣는 데에만 써라. "
    "unsupported 필드부터 정하라. 질의가 요구하는 조건 중 레이어로 표현할 수 없는 것을 사용자가 쓴 "
    "말 그대로 모두 담아라. 비슷한 측정값으로 바꿔 채우지 마라 — '체류 시간'을 본문 길이로, "
    "'재방문 횟수'를 본 페이지 수로, '주제별'을 사이트별로 바꾸는 것은 틀린 답이다. "
    "unsupported에 하나라도 담았으면 panels는 빈 목록으로 두어라. "
    "기간('이번 달', '지난주' 등)은 따로 처리되므로 unsupported에 넣지 마라. "
    "'방문 수', '몇 개 봤는지', '얼마나 봤는지'는 본 페이지 수(page_count)로 표현한다. 다만 같은 "
    "페이지를 몇 번 다시 봤는지는 셀 수 없다. "
    "title에는 대시보드의 짧은 한국어 제목을 담아라. "
    "sites에는 특정 사이트만 보라고 했을 때 그 도메인을 담아라(예: github.com). 사이트 이름으로 "
    "말했으면 대표 도메인으로 바꿔라(깃허브 -> github.com, 벨로그 -> velog.io). "
    "keywords에는 특정 주제의 페이지만 보라고 했을 때 제목·본문에서 찾을 낱말을 담아라. 낱말 중 "
    "하나라도 들어간 페이지를 센다. 같은 낱말의 한글·영문 표기를 함께 넣어라(리액트, React). "
    "'리액트 관련 글이 늘었는지'처럼 주제를 말한 질의는 주제 분류가 아니라 키워드 조건으로 표현한다. "
    "panels에는 패널을 1~4개 담아라. 질의가 직접 물은 것을 첫 패널로 두고, 그것을 읽는 데 도움이 "
    "되는 패널(예: 전체 본 페이지 수 KPI)을 덧붙여도 된다. 질의와 무관한 패널은 넣지 마라. "
    "chart는 kpi(기준 없이 숫자 하나), line(날짜·주·월의 추이. 요일·시간대에는 쓰지 않는다), "
    "bar(항목끼리 비교, 요일·시간대 분포), "
    "pie(사이트·요일 등의 비중), table(항목이 많은 목록) 중에서 골라라. kpi면 dimension은 null이다. "
    "limit은 사이트 기준 패널에서 상위 몇 개를 보일지다. 사용자가 말하지 않았으면 null로 두어라."
)

_WINDOW_FALLBACK = "전체 기간"


def _system_instruction(window: TimeWindow | None) -> str:
    """지시에 레이어 설명과 이미 정해진 기간을 붙인다.

    기간을 알려주는 것은 '이번 달 추이'에서 이번 달을 만들 수 없는 조건으로 오해하지 않게 하고,
    기간에 맞는 기준(하루짜리면 시간대, 몇 달이면 월)을 고르게 하려는 것이다.
    """
    period = window.label if window else _WINDOW_FALLBACK
    return f"{SYSTEM_INSTRUCTION}\n\n기간: {period}\n\n{catalog()}"


def latest_dashboard(history: Sequence[Message]) -> Dashboard | None:
    """앞선 대화에서 가장 최근에 만든 대시보드. 없으면 None.

    '그거 주별로 바꿔줘'는 무엇을 바꾸라는지 알아야 풀린다. 답변 문장에는 제목만 남으므로 저장해 둔
    구성을 함께 보여준다. 저장된 값을 읽지 못하면(형식이 바뀐 옛 행) 없는 것으로 친다.
    """
    for message in reversed(history):
        if message.role != MessageRole.ASSISTANT or not message.dashboard:
            continue
        try:
            return Dashboard.model_validate(message.dashboard)
        except ValueError:
            logger.warning("stored dashboard unreadable, ignoring: message_id={}", message.id)
            return None
    return None


def describe(dashboard: Dashboard) -> str:
    """저장된 대시보드를 모델이 읽을 한 덩이로. 데이터는 빼고 구성만 싣는다."""
    panels = "\n".join(
        f"- {panel.title}: measure={panel.measure}, dimension={panel.dimension}, chart={panel.chart}"
        for panel in dashboard.panels
    )
    filters = f"\n조건: {', '.join(dashboard.filters)}" if dashboard.filters else ""
    return f"제목: {dashboard.title}\n기간: {dashboard.period}{filters}\n패널:\n{panels}"


def _build_contents(
    message: str,
    history: Sequence[Message],
    shown: Mapping[int, Sequence[Document]],
    previous: Dashboard | None,
) -> list[types.Content]:
    contents = render_history(history, shown)
    if previous is not None:
        contents.append(
            types.Content(
                role="user", parts=[types.Part(text=f"직전에 만든 대시보드:\n{describe(previous)}")]
            )
        )
    contents.append(types.Content(role="user", parts=[types.Part(text=message)]))
    return contents


def plan_dashboard(
    message: str,
    history: Sequence[Message] = (),
    shown: Mapping[int, Sequence[Document]] = {},
    window: TimeWindow | None = None,
) -> DashboardPlan | None:
    """질의를 대시보드 구성으로 바꾼다. 응답을 해석하지 못하면 None.

    None 은 '만들 수 없다'가 아니라 '무엇을 만들지 모른다'다. 부르는 쪽은 둘을 다르게 답한다.
    """
    model = get_settings().query_rewrite_model
    previous = latest_dashboard(history)
    logger.debug(
        "planning dashboard via {}: {!r} (period={}, history={}, previous={!r})",
        model,
        message,
        window.label if window else None,
        len(history),
        previous.title if previous else None,
    )
    response = get_client().models.generate_content(
        model=model,
        contents=_build_contents(message, history, shown, previous),
        config=types.GenerateContentConfig(
            system_instruction=_system_instruction(window),
            response_mime_type="application/json",
            response_schema=DashboardPlan,
        ),
    )
    if not isinstance(response.parsed, DashboardPlan):
        logger.warning("dashboard plan unparsable: {!r}", response.text)
        return None
    return response.parsed


# 모델이 지시를 어기고 비슷한 측정값으로 바꿔 채우는 경우를 막는 마지막 그물이다. 수집하지 않는다는
# 것이 분명한 개념만 둔다 — 넓게 잡으면 '체류 비자 관련 글 수'처럼 멀쩡한 키워드 질의까지 막는다.
_UNSUPPORTED_PATTERNS = (
    ("체류 시간", re.compile(r"체류\s?시간")),
    ("머문 시간", re.compile(r"머(문|무른|물렀던)\s?시간")),
    ("재방문", re.compile(r"재방문")),
    ("다시 본 횟수", re.compile(r"(다시|또)\s?(본|방문한|들어간)\s?(횟수|빈도)")),
)


def unsupported_by_rule(message: str) -> list[str]:
    """질의에서 수집하지 않는 개념을 찾는다. 모델의 판단과 상관없이 이것이 걸리면 거절한다."""
    return [name for name, pattern in _UNSUPPORTED_PATTERNS if pattern.search(message)]
