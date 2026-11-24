"""대시보드 구성(DashboardPlan)을 SQL 로 옮겨 실행하고, 화면이 그릴 Dashboard 를 만든다.

모델이 고른 것은 레이어의 이름뿐이다(services/dashboard/planner.py). 여기서 그 이름을
semantic_layer 의 식으로 바꾸고, 사용자가 건 조건(기간·사이트·키워드)을 바인딩 파라미터로 붙인다.
SQL 문자열을 이어 붙이는 자리가 없으므로 모델의 출력이 무엇이든 정해진 모양의 집계만 나간다.

거절은 두 갈래다. 만들 수 없는 조건이 있으면(unsupported) 그 조건을 밝혀 거절하고, 무엇을 만들지
모르면(구성 해석 실패, 쓸 패널이 없음) 다시 물어 달라고 한다. 사용자는 두 경우에 할 일이 다르다 —
앞쪽은 질문을 바꿔야 하고 뒤쪽은 더 분명히 말하면 된다.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from loguru import logger
from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import Session

from backend.models.conversation import Message
from backend.models.document import Document
from backend.schemas.dashboard import (
    ChartType,
    Dashboard,
    DashboardPanel,
    DashboardPlan,
    DashboardPoint,
    PanelPlan,
)
from backend.services.chat.timerange import TimeWindow, local_now, to_local
from backend.services.dashboard.planner import plan_dashboard, unsupported_by_rule
from backend.services.dashboard.semantic_layer import (
    DIMENSIONS,
    MEASURES,
    SQL_URL_HOST,
    DimensionKind,
    DimensionName,
    MeasureName,
    capabilities_summary,
    url_host,
)

MAX_PANELS = 4
DEFAULT_CATEGORY_LIMIT = 10
MAX_CATEGORY_LIMIT = 20
# 날짜 기준 패널의 점 수 상한. 기간 없이 '일별 추이'를 물으면 기록 전체가 하루 단위로 펼쳐지는데,
# 몇 년치를 한 줄에 그리면 읽을 수 없다.
MAX_TIMELINE_POINTS = 366

OTHERS_KEY = "__others__"
OTHERS_LABEL = "기타"
UNKNOWN_SITE_LABEL = "(알 수 없음)"
WEEKDAY_LABELS = ("월", "화", "수", "목", "금", "토", "일")
WHOLE_PERIOD_LABEL = "전체 기간"

UNPLANNED_ANSWER = (
    "어떤 대시보드를 만들지 정하지 못했습니다. 무엇을 어떤 기준으로 볼지 말씀해 주세요. "
    "예: '이번 달 사이트별로 본 페이지 수', '지난주 요일별 추이'"
)


@dataclass(frozen=True)
class DashboardOutcome:
    """대시보드 턴의 결과. 거절한 턴은 dashboard 가 없고 answer 에 그 이유가 담긴다."""

    answer: str
    dashboard: Dashboard | None = None


def build_dashboard(
    message: str,
    db: Session,
    history: Sequence[Message] = (),
    shown: Mapping[int, Sequence[Document]] = {},
    window: TimeWindow | None = None,
    client_now: datetime | None = None,
) -> DashboardOutcome:
    """질의 하나를 대시보드로 만든다. 만들 수 없으면 그 이유를 답한다."""
    by_rule = unsupported_by_rule(message)
    if by_rule:
        # 모델을 부르기 전에 끊는다. 모델이 이것을 비슷한 측정값으로 바꿔 채워 오면 그럴듯한 엉뚱한
        # 차트가 나가는데, 이 말들은 무엇으로 바꿔도 맞을 수 없다.
        logger.info("dashboard refused by rule: {!r} -> {}", message, by_rule)
        return refusal(by_rule)

    plan = plan_dashboard(message, history, shown, window)
    if plan is None:
        return DashboardOutcome(answer=UNPLANNED_ANSWER)
    if plan.unsupported:
        logger.info("dashboard refused by plan: {!r} -> {}", message, plan.unsupported)
        return refusal(plan.unsupported)

    panels = normalize_panels(plan.panels)
    if not panels:
        logger.info("dashboard plan has no usable panel: {!r} -> {}", message, plan.panels)
        return DashboardOutcome(answer=UNPLANNED_ANSWER)

    dashboard, matched = execute_plan(plan, panels, db, window, client_now)
    return DashboardOutcome(answer=_summary(dashboard, matched), dashboard=dashboard)


def refusal(unsupported: Sequence[str]) -> DashboardOutcome:
    """만들 수 없는 조건을 밝혀 거절한다. 무엇이라면 되는지도 함께 알린다.

    대체해서 만들지 않는다. '체류 시간'을 물었는데 본문 길이를 그려 주면, 사용자는 그것이 체류
    시간인 줄 알고 읽는다.
    """
    named = ", ".join(f"'{item}'" for item in dict.fromkeys(unsupported))
    return DashboardOutcome(
        answer=(
            f"요청하신 대시보드는 만들 수 없습니다. {named}은(는) 지금 모으는 기록에 없는 정보라 "
            f"셀 수 없습니다.\n\n대시보드로 만들 수 있는 것은 다음과 같습니다.\n{capabilities_summary()}"
        )
    )


def normalize_panels(panels: Sequence[PanelPlan]) -> list[PanelPlan]:
    """모델이 고른 패널을 그릴 수 있는 모양으로 바로잡는다. 바로잡을 수 없는 패널은 버린다.

    차트 종류가 기준과 안 맞는 것(사이트별 꺾은선 등)은 막대로 바꾼다. 무엇을 보려는지는 맞게
    골랐는데 그리는 방식만 어긋난 것이라, 거절하기보다 고쳐 그리는 쪽이 사용자에게 낫다.
    """
    normalized: list[PanelPlan] = []
    seen: set[tuple[MeasureName, DimensionName | None]] = set()
    for panel in panels:
        fixed = _normalize_panel(panel)
        if fixed is None:
            continue
        signature = (fixed.measure, fixed.dimension)
        if signature in seen:
            continue
        seen.add(signature)
        normalized.append(fixed)
    return normalized[:MAX_PANELS]


def _normalize_panel(panel: PanelPlan) -> PanelPlan | None:
    measure = MEASURES[panel.measure]
    dimension = DIMENSIONS[panel.dimension] if panel.dimension else None

    if dimension is None:
        return panel.model_copy(
            update={"chart": ChartType.KPI, "limit": None, "title": panel.title.strip() or measure.label}
        )

    if panel.measure is MeasureName.SITE_COUNT and dimension.name is DimensionName.SITE:
        # 사이트별 사이트 수는 모든 칸이 1이다. 그릴 것이 없다.
        logger.debug("dropping panel {!r}: site_count by site is always 1", panel.title)
        return None

    chart = panel.chart
    if chart is ChartType.KPI:
        chart = ChartType.BAR
    if chart is ChartType.LINE and dimension.kind is not DimensionKind.TIMELINE:
        # 선은 이어지는 시간을 뜻한다. 요일·시간대는 여러 날을 겹쳐 센 칸이라 선으로 이으면 한 시점의
        # 오르내림처럼 읽힌다.
        chart = ChartType.BAR
    if chart is ChartType.PIE and (not measure.additive or dimension.kind is DimensionKind.TIMELINE):
        # 비중은 나눠 센 값을 더해 전체가 될 때만 뜻이 있다. 날짜별 비중은 추이를 조각낸 것일 뿐이다.
        chart = ChartType.BAR

    limit = None
    if dimension.kind is DimensionKind.CATEGORY:
        requested = panel.limit if panel.limit and panel.limit > 0 else DEFAULT_CATEGORY_LIMIT
        limit = min(requested, MAX_CATEGORY_LIMIT)

    title = panel.title.strip() or f"{dimension.label}별 {measure.label}"
    return panel.model_copy(update={"chart": chart, "limit": limit, "title": title})


def execute_plan(
    plan: DashboardPlan,
    panels: Sequence[PanelPlan],
    db: Session,
    window: TimeWindow | None,
    client_now: datetime | None,
) -> tuple[Dashboard, int]:
    """패널마다 집계를 하나씩 돌려 Dashboard 를 만든다. 조건에 맞는 페이지 수를 함께 돌려준다.

    조건에 맞는 페이지 수는 답변 문장에 쓴다. 0건이면 0으로 채운 차트만 덩그러니 나가지 않게
    '그 기간에는 기록이 없다'고 밝혀야 하는데, 패널만으로는 그것을 알 수 없다(평균 패널만 있을 수 있다).
    """
    _register_functions(db)
    offset = _sqlite_offset(client_now)
    sites = _clean_sites(plan.sites)
    keywords = list(dict.fromkeys(keyword.strip() for keyword in plan.keywords if keyword.strip()))
    conditions = _conditions(window, sites, keywords)

    matched = db.scalar(select(func.count(Document.id)).where(*conditions)) or 0
    notes: list[str] = []
    rendered = [
        _run_panel(panel, db, conditions, offset, window, client_now, notes) for panel in panels
    ]

    if any(panel.measure is MeasureName.PAGE_COUNT for panel in panels):
        notes.insert(0, "같은 페이지를 다시 본 것은 처음 본 날 한 번으로 셉니다.")
    if keywords:
        notes.append("키워드 조건은 제목이나 본문에 그 낱말이 하나라도 들어간 페이지를 셉니다.")

    filters = []
    if sites:
        filters.append(f"사이트: {', '.join(sites)}")
    if keywords:
        filters.append(f"키워드: {', '.join(keywords)}")

    dashboard = Dashboard(
        title=plan.title.strip() or rendered[0].title,
        period=window.label if window else WHOLE_PERIOD_LABEL,
        filters=filters,
        panels=rendered,
        notes=list(dict.fromkeys(notes)),
    )
    logger.info(
        "dashboard built: {!r} period={} filters={} panels={} matched={}",
        dashboard.title,
        dashboard.period,
        filters,
        [(panel.measure, panel.dimension, panel.chart) for panel in panels],
        matched,
    )
    return dashboard, matched


def _register_functions(db: Session) -> None:
    """레이어가 SQL 안에서 부르는 파이썬 함수를 이 커넥션에 등록한다.

    엔진의 connect 이벤트가 아니라 여기서 하는 것은 이 함수가 대시보드에서만 쓰여서다. 같은 이름으로
    다시 등록하면 덮어쓸 뿐이라 매번 불러도 된다.
    """
    raw = db.connection().connection.dbapi_connection
    raw.create_function(SQL_URL_HOST, 1, url_host, deterministic=True)


def _sqlite_offset(client_now: datetime | None) -> str:
    """사용자의 UTC 오프셋을 SQLite 날짜 수식어로. 한국이면 '+540 minutes'.

    요청 시각의 오프셋 하나로 모든 기록을 옮긴다. 서머타임이 있는 지역에서는 경계를 넘은 기록이
    한 시간 어긋나지만, 브라우저가 알려 주는 것이 지금의 오프셋뿐이라 더 나은 값이 없다.
    """
    delta = local_now(client_now).utcoffset() or timedelta(0)
    return f"{int(delta.total_seconds() // 60):+d} minutes"


def _clean_sites(raw_sites: Sequence[str]) -> list[str]:
    """모델이 적어 온 사이트를 비교할 수 있는 호스트로. 'https://www.github.com/x' -> 'github.com'."""
    cleaned = []
    for raw in raw_sites:
        value = raw.strip().lower()
        if not value:
            continue
        host = url_host(value) if "://" in value else value.split("/", 1)[0].removeprefix("www.")
        if host:
            cleaned.append(host)
    return list(dict.fromkeys(cleaned))


def _conditions(
    window: TimeWindow | None, sites: Sequence[str], keywords: Sequence[str]
) -> list[ColumnElement]:
    """모든 패널이 함께 쓰는 WHERE 조건. 값은 전부 바인딩 파라미터로 들어간다."""
    conditions: list[ColumnElement] = []
    if window is not None:
        conditions += [Document.timestamp >= window.since, Document.timestamp < window.until]
    if sites:
        host = getattr(func, SQL_URL_HOST)(Document.url)
        # 하위 도메인도 그 사이트다. 'github.com'에는 'gist.github.com'도 든다.
        conditions.append(
            or_(*(or_(host == site, host.endswith(f".{site}", autoescape=True)) for site in sites))
        )
    if keywords:
        conditions.append(
            or_(
                *(
                    or_(
                        Document.title.contains(keyword, autoescape=True),
                        Document.full_text.contains(keyword, autoescape=True),
                    )
                    for keyword in keywords
                )
            )
        )
    return conditions


def _run_panel(
    panel: PanelPlan,
    db: Session,
    conditions: Sequence[ColumnElement],
    offset: str,
    window: TimeWindow | None,
    client_now: datetime | None,
    notes: list[str],
) -> DashboardPanel:
    measure = MEASURES[panel.measure]
    dimension = DIMENSIONS[panel.dimension] if panel.dimension else None
    rendered = DashboardPanel(
        title=panel.title,
        chart=panel.chart,
        measure=measure.name,
        measure_label=measure.label,
        unit=measure.unit,
        dimension=dimension.name if dimension else None,
        dimension_label=dimension.label if dimension else None,
    )

    if dimension is None:
        value = _as_value(panel.measure, db.scalar(select(measure.expression()).where(*conditions)))
        if value is None and measure.zero_when_empty:
            value = 0.0
        points = [] if value is None else [DashboardPoint(key="total", label=measure.label, value=value)]
        return rendered.model_copy(update={"points": points})

    bucket = dimension.expression(offset).label("bucket")
    rows = db.execute(
        select(bucket, measure.expression().label("value")).where(*conditions).group_by(bucket)
    ).all()
    values: dict[str, float] = {}
    for key, raw in rows:
        value = _as_value(panel.measure, raw)
        if key is not None and value is not None:
            values[str(key)] = value

    match dimension.kind:
        case DimensionKind.TIMELINE:
            points = _timeline_points(dimension.name, values, measure.zero_when_empty, window, client_now, notes)
        case DimensionKind.CYCLE:
            points = _cycle_points(dimension.name, values, measure.zero_when_empty)
        case _:
            points = _category_points(values, panel.limit or DEFAULT_CATEGORY_LIMIT, measure.additive)
    return rendered.model_copy(update={"points": points})


def _as_value(measure: MeasureName, raw) -> float | None:
    """집계값을 화면에 내보낼 숫자로. 평균은 소수점이 뜻이 없어 반올림한다."""
    if raw is None:
        return None
    return float(round(raw)) if measure is MeasureName.AVG_TEXT_LENGTH else float(raw)


def _timeline_points(
    name: DimensionName,
    values: Mapping[str, float],
    zero_when_empty: bool,
    window: TimeWindow | None,
    client_now: datetime | None,
    notes: list[str],
) -> list[DashboardPoint]:
    """날짜·주·월 기준. 기록이 없는 칸도 채워 넣는다 — 빠진 날을 건너뛰면 추이가 왜곡된다.

    칸의 범위는 기간이 있으면 그 기간 전체다. 그래야 '이번 달 일별'에서 아직 아무것도 안 본 초순도
    0으로 보인다. 기간이 없거나 그 기간이 너무 넓으면 기록이 있는 범위로 좁힌다.
    """
    recorded = sorted(_parse_bucket(name, key) for key in values)
    if not recorded:
        return []

    first, last = recorded[0], recorded[-1]
    if window is not None:
        first = _bucket_start(name, to_local(window.since, client_now).date())
        last = _bucket_start(name, to_local(window.until - timedelta(microseconds=1), client_now).date())
        if len(_bucket_range(name, first, last)) > MAX_TIMELINE_POINTS:
            first, last = recorded[0], recorded[-1]

    buckets = _bucket_range(name, first, last)
    if len(buckets) > MAX_TIMELINE_POINTS:
        buckets = buckets[-MAX_TIMELINE_POINTS:]
        notes.append(f"칸이 너무 많아 최근 {MAX_TIMELINE_POINTS}개만 보여줍니다.")

    multi_year = buckets[0].year != buckets[-1].year
    points = []
    for start in buckets:
        key = _bucket_key(name, start)
        value = values.get(key)
        if value is None:
            if not zero_when_empty:
                continue
            value = 0.0
        points.append(DashboardPoint(key=key, label=_bucket_label(name, start, multi_year), value=value))
    return points


def _parse_bucket(name: DimensionName, key: str) -> date:
    if name is DimensionName.MONTH:
        year, month = key.split("-")
        return date(int(year), int(month), 1)
    return date.fromisoformat(key)


def _bucket_start(name: DimensionName, day: date) -> date:
    """그 날짜가 속한 칸의 첫날. SQL 쪽 식(semantic_layer)과 같은 경계여야 키가 맞는다."""
    if name is DimensionName.WEEK:
        return day - timedelta(days=day.weekday())
    if name is DimensionName.MONTH:
        return day.replace(day=1)
    return day


def _bucket_range(name: DimensionName, first: date, last: date) -> list[date]:
    buckets = []
    current = first
    while current <= last:
        buckets.append(current)
        if name is DimensionName.WEEK:
            current += timedelta(days=7)
        elif name is DimensionName.MONTH:
            current = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
        else:
            current += timedelta(days=1)
    return buckets


def _bucket_key(name: DimensionName, start: date) -> str:
    return f"{start:%Y-%m}" if name is DimensionName.MONTH else start.isoformat()


def _bucket_label(name: DimensionName, start: date, multi_year: bool) -> str:
    year = f"{start.year}년 " if multi_year else ""
    match name:
        case DimensionName.MONTH:
            return f"{year}{start.month}월"
        case DimensionName.WEEK:
            # 주는 시작하는 월요일로 부른다. 물결표가 '이날부터 한 주'를 뜻한다.
            return f"{year}{start.month}/{start.day}~"
        case _:
            return f"{year}{start.month}/{start.day}"


def _cycle_points(
    name: DimensionName, values: Mapping[str, float], zero_when_empty: bool
) -> list[DashboardPoint]:
    """요일·시간대 기준. 칸이 정해져 있으므로 모두 순서대로 내보낸다."""
    if name is DimensionName.WEEKDAY:
        slots = [(str(index), label) for index, label in enumerate(WEEKDAY_LABELS)]
    else:
        slots = [(str(hour), f"{hour}시") for hour in range(24)]

    points = []
    for key, label in slots:
        value = values.get(key)
        if value is None:
            if not zero_when_empty:
                continue
            value = 0.0
        points.append(DashboardPoint(key=key, label=label, value=value))
    return points


def _category_points(values: Mapping[str, float], limit: int, additive: bool) -> list[DashboardPoint]:
    """사이트 기준. 값이 큰 순서로 limit 개, 나머지는 더할 수 있는 값이면 '기타'로 묶는다.

    같은 값끼리는 이름순이다. 순서가 실행마다 흔들리면 다시 연 대화의 차트가 처음과 달라 보인다.
    """
    ranked = sorted(values.items(), key=lambda item: (-item[1], item[0]))
    points = [
        DashboardPoint(key=key, label=key or UNKNOWN_SITE_LABEL, value=value)
        for key, value in ranked[:limit]
    ]
    rest = ranked[limit:]
    if additive and rest:
        points.append(
            DashboardPoint(key=OTHERS_KEY, label=OTHERS_LABEL, value=sum(value for _key, value in rest))
        )
    return points


def _summary(dashboard: Dashboard, matched: int) -> str:
    """대시보드와 함께 나갈 한 줄. 대화 기록에는 이 문장이 남아 다음 턴의 맥락이 된다."""
    if matched == 0:
        return (
            f"{dashboard.period}에는 조건에 맞는 기록이 없습니다. '{dashboard.title}' 대시보드를 "
            "만들었지만 모든 값이 비어 있습니다."
        )
    return f"{dashboard.period} 동안 본 페이지 {matched}개로 '{dashboard.title}' 대시보드를 만들었습니다."
