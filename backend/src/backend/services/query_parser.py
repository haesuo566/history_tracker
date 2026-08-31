from collections.abc import Mapping, Sequence
from datetime import datetime

from google.genai import types
from loguru import logger
from pydantic import BaseModel

from backend.models.conversation import Message
from backend.models.document import Document
from backend.services.gemini import get_client
from backend.services.intent import Intent
from backend.services.prompt import format_listing, render_history
from backend.services.runtime_settings import get_settings
from backend.services.timerange import TimeRange, local_now


class ParsedQuery(BaseModel):
    """rewrite_query의 구조화 출력 스키마."""

    # 이 docstring과 필드 순서는 그대로 Gemini에 스키마로 전달된다(description, propertyOrdering).
    # 설명은 모델에게 도움이 될 만큼만 적고, 설계 근거는 주석으로 남긴다. intent를 앞에 두는 것은
    # 의도를 먼저 정하고 그에 맞는 검색어를 쓰게 하려는 의도다 — 지시 표현이 무엇을 가리키는지
    # 찾는 일과 이 턴이 recall인지 판단하는 일이 같은 추론이라 한 호출로 함께 받는다.
    # target_index가 query보다 앞인 것도 같은 이유다. 지목한 대상을 먼저 정해야 그 제목을 검색어로
    # 쓸 수 있다.
    # time_range도 query보다 앞이다. 시간 표현을 먼저 떼어내야 그것을 뺀 검색어를 쓰게 된다 —
    # "어제"가 검색어에 남으면 그 낱말로 본문을 뒤져 엉뚱한 문서가 걸린다.
    intent: Intent
    target_index: int | None = None
    time_range: TimeRange = TimeRange()
    query: str
    desired_count: int | None = None


SYSTEM_INSTRUCTION = (
    "사용자의 입력을 다음 JSON 형식으로 변환하라. "
    "앞선 대화가 함께 주어지면 맥락 파악에만 쓰고, 판단과 재작성의 대상은 항상 마지막 사용자 메시지다. "
    "intent 필드에는 마지막 사용자 메시지의 의도를 담아라. "
    "recall: 과거에 방문했거나 열람한 웹 페이지/사이트/글을 기록에서 새로 찾으려는 의도. "
    "detail: 앞선 대화에서 이미 찾아준 결과 중 하나를 지목해 그 페이지의 내용을 더 알려달라는 의도. "
    "'두 번째 것 자세히', '첫 번째 링크 내용이 뭐였지', '거기 가격 얼마였어'처럼 지목한 대상이 앞선 "
    "대화의 결과 목록 안에 있어야 detail이다. 앞선 대화에 결과가 없거나 기록을 새로 뒤져야 하면 "
    "detail이 아니라 recall이다. "
    "etc: 그 외 잡담이나 무관한 질문. "
    "번호가 붙은 결과 목록이 함께 주어지면 detail 판단의 근거는 그 목록이다. intent가 detail이면 "
    "사용자가 지목한 항목의 번호를 target_index에 담아라. 순서('두 번째'), 제목의 일부, 사이트 "
    "이름이나 주소 등 무엇으로 가리켰든 목록에서 그 항목을 찾아 번호로 바꿔라. 목록에서 하나로 "
    "좁힐 수 없으면 target_index는 null이고, 그때는 detail이 아니라 recall이다. "
    "목록이 주어지지 않았거나 intent가 detail이 아니면 target_index는 null이다. "
    "time_range 필드에는 마지막 사용자 메시지가 가리키는 기간을 담아라. kind는 다음 중 하나다. "
    "none: 기간을 말하지 않았다. today: 오늘. yesterday: 어제. this_week: 이번 주. "
    "last_week: 지난주. this_month: 이번 달. last_month: 지난달. "
    "recent_days: '최근 사흘', '요 며칠', '일주일 사이'처럼 오늘로부터 며칠간을 말한 경우이며, "
    "days에 그 일수를 정수로 담아라. "
    "absolute: '8월 20일', '3월 초에', '20일부터 22일까지'처럼 특정 날짜나 날짜 구간을 말한 경우이며, "
    "since와 until에 YYYY-MM-DD 형식으로 담아라. 하루만 말했으면 since와 until을 같은 날로 하고, "
    "연도를 말하지 않았으면 오늘 날짜를 기준으로 가장 가까운 과거의 그 날짜로 정하라. "
    "kind가 recent_days가 아니면 days는 null, absolute가 아니면 since와 until은 null이다. "
    "'최근에', '요즘', '얼마 전에'처럼 기간이 분명하지 않은 말은 none으로 두어라 — 임의로 며칠을 "
    "정하면 사용자가 말하지 않은 기간으로 기록을 잘라내게 된다. "
    "query 필드에는 검색 엔진에 넣기 좋은 간결한 한국어 검색어 문장을 담아라. "
    "대화체, 잡담, 존댓말 표현은 제거하고 핵심 주제와 키워드만 남겨라. "
    "시간 표현은 query에서 빼라 — 그것은 time_range가 담는다. '어제 본 리액트 상태관리 글'의 "
    "query는 '리액트 상태관리'다. 시간 표현을 빼면 검색어가 비는 질의('어제 본 거 다 보여줘')는 "
    "query를 빈 문자열로 두어라. "
    "'그거', '아까 그 사이트', '두 번째 것'처럼 앞선 대화를 가리키는 표현은 대화에서 그 대상을 찾아 "
    "구체적인 명사나 제목으로 바꿔라. 가리키는 대상을 찾을 수 없으면 그 표현은 버려라. "
    "intent가 detail이면 query에는 지목된 그 결과 하나를 특정할 수 있는 제목이나 키워드만 담아라. "
    "intent가 etc이면 query는 쓰이지 않으므로 마지막 사용자 메시지를 그대로 담아도 된다. "
    "desired_count 필드에는 사용자가 '3개만', '다섯 개 찾아줘'처럼 결과 개수를 명시적으로 요청한 경우 "
    "그 숫자를 정수로, 그렇지 않으면 null을 담아라."
)

_WEEKDAYS = ("월", "화", "수", "목", "금", "토", "일")


def _system_instruction(client_now: datetime | None) -> str:
    """지시에 오늘 날짜를 붙인다.

    '8월 20일에 본 거'가 몇 년의 8월 20일인지, '지난달'이 몇 월인지는 오늘을 알아야 정해진다.
    모델은 자기가 언제 불렸는지 모르므로 여기서 알려준다. 라벨(yesterday 등)의 실제 구간 계산은
    services/timerange.py가 하지만, absolute로 말한 날짜만은 모델이 적어야 해서 필요하다.

    날짜는 사용자의 로컬 기준이다. UTC로 알려주면 밤늦은 질의에서 하루가 어긋난다.
    """
    now = local_now(client_now)
    return f"{SYSTEM_INSTRUCTION} 오늘은 {now:%Y-%m-%d}({_WEEKDAYS[now.weekday()]}요일)이다."


def _build_contents(
    message: str,
    history: Sequence[Message],
    candidates: Sequence[Document] = (),
    shown: Mapping[int, Sequence[Document]] = {},
) -> list[types.Content]:
    """앞선 대화를 옮기고(services/prompt.py) 후보 목록과 이번 입력을 뒤에 붙인다.

    후보 목록은 이번 입력 바로 앞에 번호를 붙여 끼운다. 목록을 따로 보여줘야 판단과 번호 지목이
    같은 것을 보고 이뤄진다. 별개의 발화로 두는 것은 '판단 대상은 마지막 사용자 메시지'라는 지시를
    흐리지 않기 위해서다. 이 목록과 겹치는 직전 턴은 shown에서 미리 빠져 있다(results.past_shown).
    """
    contents = render_history(history, shown)
    if candidates:
        contents.append(
            types.Content(
                role="user",
                parts=[types.Part(text=f"직전에 보여준 결과 목록:\n{format_listing(candidates)}")],
            )
        )
    contents.append(types.Content(role="user", parts=[types.Part(text=message)]))
    return contents


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
    model = get_settings().query_rewrite_model
    logger.debug(
        "rewriting query via {}: {!r} (history={} message(s), candidates={}, listed turns={})",
        model,
        message,
        len(history),
        len(candidates),
        len(shown),
    )
    response = get_client().models.generate_content(
        model=model,
        contents=_build_contents(message, history, candidates, shown),
        config=types.GenerateContentConfig(
            system_instruction=_system_instruction(client_now),
            response_mime_type="application/json",
            response_schema=ParsedQuery,
        ),
    )
    if not isinstance(response.parsed, ParsedQuery):
        # 의도까지 못 받은 상황이라 검색으로 밀어봐야 원문 그대로 찾는 헛질의가 된다. etc로 두어
        # 일반 대화로 답하게 한다(분류 실패 시의 기존 동작과 같다).
        logger.warning("query rewrite unparsable, falling back to raw message: {!r}", response.text)
        return ParsedQuery(intent=Intent.ETC, query=message)
    return response.parsed
