"""대시보드가 물을 수 있는 것의 목록 — 측정값, 기준(차원), 거를 수 있는 조건.

모델은 SQL 을 쓰지 않는다. 이 목록에서 이름을 고를 뿐이고, 그 이름을 SQL 로 옮기는 것은
services/dashboard/builder.py 다. 모델이 고를 수 있는 이름은 여기 enum 이 전부라(Gemini 스키마의 enum
으로 그대로 실린다) 없는 컬럼이나 임의의 식이 끼어들 자리가 없다.

이 목록이 곧 "만들 수 있는 것"의 경계다. 사용자가 여기 없는 개념(체류 시간, 재방문 횟수 등)을
물으면 비슷한 측정값으로 바꿔치지 않고 만들 수 없다고 답한다 — 다른 것을 그린 차트는 그럴듯해
보여서 틀렸다는 것을 알아채기 어렵다.

바탕이 되는 데이터는 documents 한 테이블이다. URL 하나가 문서 하나이고 timestamp 는 그 URL 을
**처음** 수집한 시각이다(services/collection/document.py). 그래서 "본 페이지 수"는 처음 본 페이지의 수이며,
같은 페이지를 다시 본 것은 세지 않는다.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit

from sqlalchemy import ColumnElement, Integer, cast, func

from backend.models.document import Document


class MeasureName(StrEnum):
    PAGE_COUNT = "page_count"
    SITE_COUNT = "site_count"
    AVG_TEXT_LENGTH = "avg_text_length"


class DimensionName(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    WEEKDAY = "weekday"
    HOUR = "hour"
    SITE = "site"


class DimensionKind(StrEnum):
    """기준의 성격. 차트 종류를 고르고 빈 구간을 채우는 방식이 여기서 갈린다."""

    # 이어지는 시간축. 빈 날짜를 0으로 채워야 추이가 왜곡되지 않는다.
    TIMELINE = "timeline"
    # 되풀이되는 고정된 칸(요일 7칸, 시간대 24칸). 칸이 정해져 있어 모두 채워 보여준다.
    CYCLE = "cycle"
    # 값으로 정렬되는 범주. 상위 몇 개만 남기고 나머지는 '기타'로 묶는다.
    CATEGORY = "category"


@dataclass(frozen=True)
class Measure:
    name: MeasureName
    label: str
    unit: str
    description: str
    expression: Callable[[], ColumnElement]
    # 나눠 센 값을 더하면 전체가 되는가. 사이트 수나 평균은 그렇지 않아, 상위 몇 개 밖의 범주를
    # '기타' 한 칸으로 합칠 수 없고 파이 차트로 나눠 그릴 수도 없다.
    additive: bool
    # 기록이 없는 칸의 값이 0인가. 개수는 0이 맞지만 평균은 값이 없는 것이라, 0으로 채우면 그날
    # 아주 짧은 글만 읽은 것처럼 그려진다.
    zero_when_empty: bool


@dataclass(frozen=True)
class Dimension:
    name: DimensionName
    label: str
    kind: DimensionKind
    description: str
    # 인자는 사용자의 UTC 오프셋을 SQLite 날짜 수식어로 적은 것이다("+540 minutes").
    expression: Callable[[str], ColumnElement]


def url_host(url: str | None) -> str:
    """URL 의 호스트에서 www. 를 뗀 것. 결과 카드가 사이트를 보여주는 방식(MessageBubble)과 같다.

    SQLite 에는 URL 을 쪼개는 함수가 없어 이 함수를 커넥션에 등록해 SQL 안에서 부른다
    (services/dashboard/builder.py). 파싱할 수 없는 값은 빈 문자열이라 한 범주로 모인다.
    """
    if not url:
        return ""
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        return ""
    return host.removeprefix("www.")


SQL_URL_HOST = "url_host"


def _site() -> ColumnElement:
    return getattr(func, SQL_URL_HOST)(Document.url)


def _local(offset: str) -> ColumnElement:
    """수집 시각(naive UTC)을 사용자 지역 시각으로. 날짜·요일·시간대는 모두 이 값으로 가른다.

    UTC 그대로 자르면 한국에서는 아침 아홉 시 이전에 본 것이 전날로 세어진다.
    """
    return func.datetime(Document.timestamp, offset)


MEASURES: dict[MeasureName, Measure] = {
    measure.name: measure
    for measure in (
        Measure(
            name=MeasureName.PAGE_COUNT,
            label="본 페이지 수",
            unit="개",
            description="처음 본 페이지의 수. 같은 페이지를 다시 본 것은 세지 않는다.",
            expression=lambda: func.count(Document.id),
            additive=True,
            zero_when_empty=True,
        ),
        Measure(
            name=MeasureName.SITE_COUNT,
            label="사이트 수",
            unit="곳",
            description="서로 다른 사이트(도메인)의 수.",
            expression=lambda: func.count(func.distinct(_site())),
            additive=False,
            zero_when_empty=True,
        ),
        Measure(
            name=MeasureName.AVG_TEXT_LENGTH,
            label="평균 본문 길이",
            unit="자",
            description="본 페이지 본문의 평균 글자 수. 얼마나 긴 글을 읽었는지의 대략적인 지표.",
            expression=lambda: func.avg(func.length(Document.full_text)),
            additive=False,
            zero_when_empty=False,
        ),
    )
}

DIMENSIONS: dict[DimensionName, Dimension] = {
    dimension.name: dimension
    for dimension in (
        Dimension(
            name=DimensionName.DAY,
            label="날짜",
            kind=DimensionKind.TIMELINE,
            description="날짜별(YYYY-MM-DD).",
            expression=lambda offset: func.date(_local(offset)),
        ),
        Dimension(
            name=DimensionName.WEEK,
            label="주",
            kind=DimensionKind.TIMELINE,
            description="주별. 주는 월요일에 시작한다.",
            # 'weekday 1' 은 그날이 월요일이 아니면 다음 월요일로 간다. 엿새를 먼저 빼 두면 그 주의
            # 월요일(또는 그날 자신)에 떨어진다. timerange 의 "이번 주"와 같은 주 경계다.
            expression=lambda offset: func.date(_local(offset), "-6 days", "weekday 1"),
        ),
        Dimension(
            name=DimensionName.MONTH,
            label="월",
            kind=DimensionKind.TIMELINE,
            description="월별(YYYY-MM).",
            expression=lambda offset: func.strftime("%Y-%m", _local(offset)),
        ),
        Dimension(
            name=DimensionName.WEEKDAY,
            label="요일",
            kind=DimensionKind.CYCLE,
            description="요일별(월~일). 여러 주의 같은 요일을 합친다.",
            # %w 는 일요일이 0이다. 월요일을 0으로 돌려 월~일 순서로 정렬되게 한다.
            expression=lambda offset: (cast(func.strftime("%w", _local(offset)), Integer) + 6) % 7,
        ),
        Dimension(
            name=DimensionName.HOUR,
            label="시간대",
            kind=DimensionKind.CYCLE,
            description="하루 중 시간대별(0~23시). 여러 날의 같은 시간대를 합친다.",
            expression=lambda offset: cast(func.strftime("%H", _local(offset)), Integer),
        ),
        Dimension(
            name=DimensionName.SITE,
            label="사이트",
            kind=DimensionKind.CATEGORY,
            description="사이트(도메인)별. 값이 큰 순서로 상위 몇 개만 보여준다.",
            expression=lambda _offset: _site(),
        ),
    )
}

# 걸 수 있는 조건. 측정값·기준과 달리 SQL 식이 아니라 대시보드 구성의 필드로 받는다
# (DashboardPlan.sites·keywords, 기간은 재작성의 time_range). 모델에게 보여줄 설명만 여기 둔다.
FILTER_DESCRIPTIONS = {
    "기간": "질의에서 말한 기간('이번 달', '지난주', '8월 20일부터' 등). 말하지 않으면 전체 기간.",
    "사이트": "특정 사이트(도메인)만. 예: github.com, velog.io",
    "키워드": "제목이나 본문에 그 낱말이 들어간 페이지만. 예: 리액트, 도커",
}

# 사람들이 흔히 묻지만 수집하지 않아 만들 수 없는 것들. 모델이 비슷한 측정값으로 바꿔치지 않도록
# 지시에 그대로 싣는다. 목록이 전부는 아니다 — 여기 없어도 위 목록에 없으면 만들 수 없다.
KNOWN_UNSUPPORTED = (
    "체류 시간·머문 시간·읽은 시간(수집하지 않는다)",
    "재방문 횟수·같은 페이지를 몇 번 봤는지(URL 하나를 처음 본 한 번만 남긴다)",
    "클릭·스크롤·입력 같은 페이지 안에서의 행동",
    "주제·카테고리 분류(분류해 둔 것이 없다. 특정 낱말이 들어간 페이지 수는 키워드 조건으로 셀 수 있다)",
    "검색 엔진에 입력한 검색어",
    "브라우저·기기·위치",
)


def catalog() -> str:
    """모델에게 보여줄 레이어 설명. 지시문에 그대로 붙는다.

    이름과 설명을 여기서 한꺼번에 만들어야 정의와 지시가 갈라지지 않는다 — 측정값을 하나 더하면
    지시문도 저절로 따라온다.
    """
    measures = "\n".join(f"- {m.name}: {m.label}({m.unit}). {m.description}" for m in MEASURES.values())
    dimensions = "\n".join(f"- {d.name}: {d.label}. {d.description}" for d in DIMENSIONS.values())
    filters = "\n".join(f"- {name}: {description}" for name, description in FILTER_DESCRIPTIONS.items())
    unsupported = "\n".join(f"- {item}" for item in KNOWN_UNSUPPORTED)
    return (
        f"[측정값]\n{measures}\n\n[기준]\n{dimensions}\n\n[조건]\n{filters}\n\n"
        f"[만들 수 없는 것의 예]\n{unsupported}"
    )


def capabilities_summary() -> str:
    """거절할 때 사용자에게 무엇이라면 되는지 알려줄 한 덩이."""
    measures = ", ".join(m.label for m in MEASURES.values())
    dimensions = ", ".join(d.label for d in DIMENSIONS.values())
    filters = ", ".join(FILTER_DESCRIPTIONS)
    return f"측정값: {measures}\n기준: {dimensions}\n조건: {filters}"
