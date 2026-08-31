"""질의에 담긴 시간 표현("어제", "이번 주")을 실제 검색 구간으로 바꾼다.

모델은 라벨만 고르고 날짜 산술은 여기서 한다. '지난주 월요일'이 며칠인지를 모델에게 계산시키면
틀려도 티가 나지 않은 채 엉뚱한 기간을 뒤지게 되는데, 이 계산은 규칙이 정해져 있어 서버가 하면
항상 같은 답이 나온다. 모델이 직접 날짜를 말한 경우(ABSOLUTE)만 그 값을 받는다.

기준 시각은 사용자의 로컬 시각이다(chat 요청의 client_now). "어제"의 경계는 브라우저 앞에 앉은
사람의 자정이지 서버나 UTC 의 자정이 아니다. 반대로 비교 대상인 documents.timestamp 는 확장이
보낸 UTC 를 tzinfo 없이 저장한 값이라(services/document.py), 여기서 돌려주는 구간도 naive UTC 로
맞춰 둔다. 한쪽만 aware 면 SQLAlchemy 비교에서 조용히 어긋난다.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from enum import StrEnum

from loguru import logger
from pydantic import BaseModel

# 모델이 "최근 300일" 같은 값을 내놓아도 사실상 전체 검색이라 뜻이 없다. 상한을 두어 터무니없는
# 값이 그대로 구간이 되지 않게 한다.
MAX_RECENT_DAYS = 365

# until 만 말한 질의("8월 20일 이전에 본 거")의 시작점. 수집 기록이 이보다 앞설 수 없다.
_EPOCH = datetime(1970, 1, 1)


class TimeRangeKind(StrEnum):
    """사용자가 말한 기간의 종류."""

    NONE = "none"
    TODAY = "today"
    YESTERDAY = "yesterday"
    THIS_WEEK = "this_week"
    LAST_WEEK = "last_week"
    THIS_MONTH = "this_month"
    LAST_MONTH = "last_month"
    RECENT_DAYS = "recent_days"
    ABSOLUTE = "absolute"


class TimeRange(BaseModel):
    """rewrite_query가 질의에서 뽑아내는 기간. 그대로 Gemini 스키마가 된다.

    날짜를 문자열로 받는 것은 Gemini 스키마가 date 형식을 그대로 받아주지 않기 때문이다. 파싱은
    resolve가 맡고, 형식이 어긋난 값은 기간 없음으로 흘린다.
    """

    kind: TimeRangeKind = TimeRangeKind.NONE
    days: int | None = None
    since: str | None = None
    until: str | None = None


@dataclass(frozen=True)
class TimeWindow:
    """검색에 쓸 구간. since 이상 until 미만(naive UTC)이다.

    경계를 한쪽만 포함하는 것은 자정이 두 구간에 겹쳐 드는 것을 막기 위해서다 — "어제"와 "오늘"이
    30일 자정을 함께 가지면 같은 문서가 양쪽에 걸린다.

    label은 답변과 로그에 쓸 사람 말이다("어제(8월 30일)"). 결과가 0건일 때 어느 기간을 뒤졌는지
    밝히려면 구간을 사용자의 말로 되돌려 줄 무언가가 필요하다.
    """

    since: datetime
    until: datetime
    label: str


_KIND_NAMES = {
    TimeRangeKind.TODAY: "오늘",
    TimeRangeKind.YESTERDAY: "어제",
    TimeRangeKind.THIS_WEEK: "이번 주",
    TimeRangeKind.LAST_WEEK: "지난주",
    TimeRangeKind.THIS_MONTH: "이번 달",
    TimeRangeKind.LAST_MONTH: "지난달",
}


def local_now(client_now: datetime | None) -> datetime:
    """기준이 될 사용자 현재 시각. 없거나 tzinfo가 없으면 UTC로 본다.

    클라이언트가 시각을 싣지 못한 요청에서도 기간 검색이 완전히 멈추지는 않게 하려는 폴백이다.
    한국에서 쓰면 자정 전후 아홉 시간이 어긋나므로, 부르는 쪽(services/preprocess.py)이 경고를
    남긴다.

    재작성 호출도 이 값을 쓴다. "8월 20일에 본 거"의 연도를 정하려면 모델이 오늘이 며칠인지
    알아야 한다(services/query_parser.py).
    """
    if client_now is None:
        return datetime.now(UTC)
    return client_now if client_now.tzinfo is not None else client_now.replace(tzinfo=UTC)


def _midnight(day: date, zone: tzinfo) -> datetime:
    """그 지역 그 날짜의 자정을 naive UTC로 옮긴다."""
    return datetime.combine(day, time.min, tzinfo=zone).astimezone(UTC).replace(tzinfo=None)


def _month_start(day: date) -> date:
    return day.replace(day=1)


def _previous_month_start(day: date) -> date:
    """전달 1일. 1월이면 작년 12월로 넘어간다."""
    first = _month_start(day)
    return _month_start(first - timedelta(days=1))


def _parse_day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        logger.warning("ignoring unparsable date in time range: {!r}", value)
        return None


def _describe(kind: TimeRangeKind, since: datetime, until: datetime, zone: tzinfo) -> str:
    """구간을 사용자가 말한 기간에 가깝게 되돌린다.

    구간은 UTC라 그대로 적으면 사용자가 보는 날짜와 어긋난다. 로컬로 되돌린 뒤, 끝 경계는 배타
    이므로 1초를 빼서 마지막으로 포함되는 날을 구한다.
    """
    start_day = since.replace(tzinfo=UTC).astimezone(zone).date()
    end_day = (until - timedelta(seconds=1)).replace(tzinfo=UTC).astimezone(zone).date()

    span = (
        f"{start_day.month}월 {start_day.day}일"
        if start_day == end_day
        else f"{start_day.month}월 {start_day.day}일~{end_day.month}월 {end_day.day}일"
    )
    name = _KIND_NAMES.get(kind)
    if kind is TimeRangeKind.RECENT_DAYS:
        name = f"최근 {(end_day - start_day).days + 1}일"
    return f"{name}({span})" if name else span


def _bounds(spec: TimeRange, today: date, zone: tzinfo) -> tuple[datetime, datetime] | None:
    """kind별 구간. 끝 경계는 항상 '포함되는 마지막 날의 다음 자정'이다."""
    tomorrow = today + timedelta(days=1)

    match spec.kind:
        case TimeRangeKind.TODAY:
            return _midnight(today, zone), _midnight(tomorrow, zone)
        case TimeRangeKind.YESTERDAY:
            return _midnight(today - timedelta(days=1), zone), _midnight(today, zone)
        case TimeRangeKind.THIS_WEEK:
            # 주의 시작은 월요일이다(ISO). 일요일 시작으로 보는 달력도 있지만, 한쪽으로 정해두지
            # 않으면 "이번 주"가 일요일마다 뜻이 바뀐다.
            monday = today - timedelta(days=today.weekday())
            return _midnight(monday, zone), _midnight(monday + timedelta(days=7), zone)
        case TimeRangeKind.LAST_WEEK:
            monday = today - timedelta(days=today.weekday() + 7)
            return _midnight(monday, zone), _midnight(monday + timedelta(days=7), zone)
        case TimeRangeKind.THIS_MONTH:
            first = _month_start(today)
            return _midnight(first, zone), _midnight(tomorrow, zone)
        case TimeRangeKind.LAST_MONTH:
            first = _previous_month_start(today)
            return _midnight(first, zone), _midnight(_month_start(today), zone)
        case TimeRangeKind.RECENT_DAYS:
            if spec.days is None or spec.days <= 0:
                logger.warning("recent_days without a usable day count: {!r}", spec.days)
                return None
            # "최근 3일"은 오늘을 포함해 사흘이다. 오늘을 빼면 사용자가 방금 본 페이지가 빠진다.
            days = min(spec.days, MAX_RECENT_DAYS)
            return _midnight(today - timedelta(days=days - 1), zone), _midnight(tomorrow, zone)
        case TimeRangeKind.ABSOLUTE:
            start, end = _parse_day(spec.since), _parse_day(spec.until)
            if start is None and end is None:
                return None
            if start is not None and end is not None and start > end:
                start, end = end, start
            since = _midnight(start, zone) if start else _EPOCH
            # 사용자가 말한 마지막 날도 포함해야 하므로 그 다음 자정까지다.
            until = _midnight(end + timedelta(days=1), zone) if end else _midnight(tomorrow, zone)
            return since, until
        case _:
            return None


def resolve(spec: TimeRange | None, client_now: datetime | None) -> TimeWindow | None:
    """기간 표현을 검색 구간으로 바꾼다. 기간이 없거나 쓸 수 없으면 None.

    None은 "기간 제한 없음"이지 "결과 없음"이 아니다. 부르는 쪽은 이 값이 없으면 기간 조건 없이
    검색한다.
    """
    if spec is None or spec.kind is TimeRangeKind.NONE:
        return None

    now = local_now(client_now)
    zone = now.tzinfo
    bounds = _bounds(spec, now.date(), zone)
    if bounds is None:
        return None

    since, until = bounds
    # 아직 오지 않은 시간에는 기록이 없다. 끝을 오늘까지로 당겨 두면 "이번 주"의 라벨이 남은
    # 날짜까지 부르지 않는다. 다만 구간이 통째로 미래면 당길 곳이 없어 원래 구간을 그대로 둔다
    # (그 경우 결과 0건이 맞는 답이다).
    today_end = _midnight(now.date() + timedelta(days=1), zone)
    if since < today_end < until:
        until = today_end

    window = TimeWindow(since=since, until=until, label=_describe(spec.kind, since, until, zone))
    logger.debug("time range resolved: {} -> {} .. {} ({})", spec.kind, since, until, window.label)
    return window
