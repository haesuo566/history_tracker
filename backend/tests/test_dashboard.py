from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.db.base import Base
from backend.models.conversation import Message, MessageRole
from backend.models.document import Document
from backend.schemas.dashboard import ChartType, Dashboard, DashboardPlan, PanelPlan
from backend.services.chat.timerange import TimeRange, TimeRangeKind, resolve
from backend.services.dashboard import builder as dashboard_service
from backend.services.dashboard.builder import (
    OTHERS_LABEL,
    UNPLANNED_ANSWER,
    build_dashboard,
    execute_plan,
    normalize_panels,
)
from backend.services.dashboard.planner import latest_dashboard, unsupported_by_rule
from backend.services.dashboard.semantic_layer import DimensionName, MeasureName, url_host

KST = timezone(timedelta(hours=9))
# 2026-08-31 은 월요일이다.
NOW = datetime(2026, 8, 31, 12, 0, tzinfo=KST)

# (url, title, 본문, 수집 시각 naive UTC). 주석은 한국 시각이다.
DOCUMENTS = [
    # UTC 로는 8/30 이지만 한국에서는 8/31(월) 새벽이다. 날짜를 UTC 로 자르면 하루 어긋난다.
    ("https://github.com/a", "깃허브 a", "가" * 100, datetime(2026, 8, 30, 20, 0)),
    # www. 가 붙어도 같은 사이트다. 8/29(토) 12시.
    ("https://www.github.com/b", "깃허브 b", "나" * 300, datetime(2026, 8, 29, 3, 0)),
    # 하위 도메인은 사이트 기준에서는 따로, 사이트 조건에서는 github.com 에 든다. 8/27(목) 10시.
    ("https://gist.github.com/c", "gist c", "다" * 200, datetime(2026, 8, 27, 1, 0)),
    # 8/27(목) 11시.
    ("https://velog.io/@me/react", "리액트 상태관리", "React 상태관리 정리!", datetime(2026, 8, 27, 2, 0)),
    # 기간(최근 7일) 밖. 7/15(수).
    ("https://news.example.com/e", "뉴스", "라" * 50, datetime(2026, 7, 15, 0, 0)),
]

LAST_7_DAYS = resolve(TimeRange(kind=TimeRangeKind.RECENT_DAYS, days=7), NOW)


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(bind=engine, tables=[Document.__table__])
    with Session(engine) as session:
        session.add_all(
            Document(document_id=f"doc-{index}", url=url, title=title, full_text=body, hash=f"h{index}", timestamp=at)
            for index, (url, title, body, at) in enumerate(DOCUMENTS)
        )
        session.commit()
        yield session


def panel(measure: MeasureName, dimension: DimensionName | None = None, chart=ChartType.BAR, limit=None) -> PanelPlan:
    return PanelPlan(title="", measure=measure, dimension=dimension, chart=chart, limit=limit)


def run(db, *panels: PanelPlan, window=LAST_7_DAYS, sites=(), keywords=()) -> tuple[Dashboard, int]:
    plan = DashboardPlan(title="테스트", sites=list(sites), keywords=list(keywords), panels=list(panels))
    return execute_plan(plan, normalize_panels(plan.panels), db, window, NOW)


def values(dashboard: Dashboard, index: int = 0) -> dict[str, float]:
    return {point.key: point.value for point in dashboard.panels[index].points}


def test_kpi_counts_pages_in_the_period(db):
    dashboard, matched = run(db, panel(MeasureName.PAGE_COUNT))

    assert matched == 4
    assert dashboard.panels[0].chart is ChartType.KPI
    assert values(dashboard) == {"total": 4.0}
    assert dashboard.period == LAST_7_DAYS.label


def test_days_are_cut_at_the_users_midnight_and_gaps_are_filled(db):
    """빈 날도 0으로 나와야 추이가 맞다. 8/30 UTC 기록은 한국 날짜로 8/31 에 세어져야 한다."""
    dashboard, _ = run(db, panel(MeasureName.PAGE_COUNT, DimensionName.DAY, ChartType.LINE))

    assert values(dashboard) == {
        "2026-08-25": 0.0,
        "2026-08-26": 0.0,
        "2026-08-27": 2.0,
        "2026-08-28": 0.0,
        "2026-08-29": 1.0,
        "2026-08-30": 0.0,
        "2026-08-31": 1.0,
    }
    assert dashboard.panels[0].points[-1].label == "8/31"


def test_weekdays_always_show_all_seven_slots_starting_monday(db):
    dashboard, _ = run(db, panel(MeasureName.PAGE_COUNT, DimensionName.WEEKDAY))

    points = dashboard.panels[0].points
    assert [point.label for point in points] == ["월", "화", "수", "목", "금", "토", "일"]
    assert [point.value for point in points] == [1.0, 0.0, 0.0, 2.0, 0.0, 1.0, 0.0]


def test_hours_use_local_time(db):
    dashboard, _ = run(db, panel(MeasureName.PAGE_COUNT, DimensionName.HOUR))

    counted = {point.label: point.value for point in dashboard.panels[0].points if point.value}
    assert len(dashboard.panels[0].points) == 24
    assert counted == {"5시": 1.0, "10시": 1.0, "11시": 1.0, "12시": 1.0}


def test_sites_keep_the_top_ones_and_fold_the_rest_into_others(db):
    dashboard, _ = run(db, panel(MeasureName.PAGE_COUNT, DimensionName.SITE, limit=1))

    points = dashboard.panels[0].points
    assert [(point.label, point.value) for point in points] == [("github.com", 2.0), (OTHERS_LABEL, 2.0)]


def test_non_additive_measures_are_not_folded_into_others(db):
    """평균을 더한 '기타'는 뜻이 없다."""
    dashboard, _ = run(db, panel(MeasureName.AVG_TEXT_LENGTH, DimensionName.SITE, limit=1))

    points = dashboard.panels[0].points
    assert len(points) == 1
    assert points[0].label != OTHERS_LABEL


def test_site_condition_includes_subdomains(db):
    dashboard, matched = run(db, panel(MeasureName.PAGE_COUNT), sites=["https://www.GitHub.com/"])

    assert matched == 3
    assert dashboard.filters == ["사이트: github.com"]


def test_keyword_condition_matches_title_or_body(db):
    dashboard, matched = run(db, panel(MeasureName.PAGE_COUNT), keywords=["리액트", "React"])

    assert matched == 1
    assert dashboard.filters == ["키워드: 리액트, React"]


def test_keyword_wildcards_are_taken_literally(db):
    """모델이 적어 온 '%'가 LIKE 와일드카드로 먹히면 모든 페이지가 걸린다."""
    _, matched = run(db, panel(MeasureName.PAGE_COUNT), keywords=["%"])

    assert matched == 0


def test_averages_leave_empty_days_out_instead_of_zero(db):
    dashboard, _ = run(db, panel(MeasureName.AVG_TEXT_LENGTH, DimensionName.DAY, ChartType.LINE))

    assert values(dashboard) == {"2026-08-27": 107.0, "2026-08-29": 300.0, "2026-08-31": 100.0}


def test_months_without_a_period_span_the_recorded_range(db):
    dashboard, matched = run(db, panel(MeasureName.PAGE_COUNT, DimensionName.MONTH, ChartType.LINE), window=None)

    assert matched == 5
    assert dashboard.period == "전체 기간"
    assert [(point.label, point.value) for point in dashboard.panels[0].points] == [("7월", 1.0), ("8월", 4.0)]


def test_weeks_start_on_monday(db):
    dashboard, _ = run(db, panel(MeasureName.PAGE_COUNT, DimensionName.WEEK), window=None)

    assert values(dashboard) == {
        "2026-07-13": 1.0,
        "2026-07-20": 0.0,
        "2026-07-27": 0.0,
        "2026-08-03": 0.0,
        "2026-08-10": 0.0,
        "2026-08-17": 0.0,
        "2026-08-24": 3.0,
        "2026-08-31": 1.0,
    }


def test_an_empty_period_still_builds_but_says_so(db, monkeypatch):
    yesterday = resolve(TimeRange(kind=TimeRangeKind.YESTERDAY), NOW)
    monkeypatch.setattr(
        dashboard_service,
        "plan_dashboard",
        lambda *args, **kwargs: DashboardPlan(title="어제", panels=[panel(MeasureName.PAGE_COUNT)]),
    )

    outcome = build_dashboard("어제 몇 개 봤어", db, window=yesterday, client_now=NOW)

    assert outcome.dashboard.panels[0].points[0].value == 0.0
    assert "기록이 없습니다" in outcome.answer


def test_page_counts_carry_the_revisit_caveat(db):
    dashboard, _ = run(db, panel(MeasureName.PAGE_COUNT))

    assert any("다시 본 것" in note for note in dashboard.notes)


# --- 패널 바로잡기 ---


def test_a_panel_without_a_dimension_becomes_a_kpi():
    [fixed] = normalize_panels([panel(MeasureName.PAGE_COUNT, chart=ChartType.LINE)])

    assert fixed.chart is ChartType.KPI
    assert fixed.title == "본 페이지 수"


def test_a_line_over_sites_becomes_bars():
    [fixed] = normalize_panels([panel(MeasureName.PAGE_COUNT, DimensionName.SITE, ChartType.LINE)])

    assert fixed.chart is ChartType.BAR
    assert fixed.limit == 10


def test_a_line_over_hours_becomes_bars():
    """시간대는 여러 날을 겹쳐 센 칸이다. 선으로 이으면 하루 동안의 추이처럼 읽힌다."""
    [fixed] = normalize_panels([panel(MeasureName.PAGE_COUNT, DimensionName.HOUR, ChartType.LINE)])

    assert fixed.chart is ChartType.BAR


def test_a_line_over_days_stays_a_line():
    [fixed] = normalize_panels([panel(MeasureName.PAGE_COUNT, DimensionName.DAY, ChartType.LINE)])

    assert fixed.chart is ChartType.LINE


def test_a_pie_of_a_non_additive_measure_becomes_bars():
    [fixed] = normalize_panels([panel(MeasureName.AVG_TEXT_LENGTH, DimensionName.WEEKDAY, ChartType.PIE)])

    assert fixed.chart is ChartType.BAR


def test_site_count_by_site_is_dropped():
    assert normalize_panels([panel(MeasureName.SITE_COUNT, DimensionName.SITE)]) == []


def test_duplicate_and_excess_panels_are_trimmed():
    panels = [
        panel(MeasureName.PAGE_COUNT, DimensionName.DAY),
        panel(MeasureName.PAGE_COUNT, DimensionName.DAY, ChartType.LINE),
        panel(MeasureName.PAGE_COUNT),
        panel(MeasureName.SITE_COUNT),
        panel(MeasureName.AVG_TEXT_LENGTH),
        panel(MeasureName.PAGE_COUNT, DimensionName.HOUR),
    ]

    assert len(normalize_panels(panels)) == 4


def test_category_limit_is_capped():
    [fixed] = normalize_panels([panel(MeasureName.PAGE_COUNT, DimensionName.SITE, limit=500)])

    assert fixed.limit == 20


# --- 거절 ---


def test_unsupported_concepts_in_the_plan_are_refused(db, monkeypatch):
    monkeypatch.setattr(
        dashboard_service,
        "plan_dashboard",
        lambda *args, **kwargs: DashboardPlan(unsupported=["주제별"], panels=[panel(MeasureName.PAGE_COUNT)]),
    )

    outcome = build_dashboard("이번 달 주제별 그래프", db, client_now=NOW)

    assert outcome.dashboard is None
    assert "'주제별'" in outcome.answer
    assert "만들 수 없습니다" in outcome.answer
    # 무엇이라면 되는지도 알려야 질문을 고칠 수 있다.
    assert "사이트" in outcome.answer


def test_untracked_concepts_are_refused_without_asking_the_model(db, monkeypatch):
    """모델이 '체류 시간'을 본문 길이로 바꿔치기해 오기 전에 끊는다."""

    def must_not_be_called(*args, **kwargs):
        raise AssertionError("planner must not be called")

    monkeypatch.setattr(dashboard_service, "plan_dashboard", must_not_be_called)

    outcome = build_dashboard("사이트별 평균 체류시간 그래프", db, client_now=NOW)

    assert outcome.dashboard is None
    assert "'체류 시간'" in outcome.answer


def test_an_unreadable_plan_asks_again(db, monkeypatch):
    monkeypatch.setattr(dashboard_service, "plan_dashboard", lambda *args, **kwargs: None)

    assert build_dashboard("뭔가 보여줘", db).answer == UNPLANNED_ANSWER


def test_a_plan_with_nothing_drawable_asks_again(db, monkeypatch):
    monkeypatch.setattr(
        dashboard_service,
        "plan_dashboard",
        lambda *args, **kwargs: DashboardPlan(panels=[panel(MeasureName.SITE_COUNT, DimensionName.SITE)]),
    )

    outcome = build_dashboard("사이트별 사이트 수", db)

    assert outcome.dashboard is None
    assert outcome.answer == UNPLANNED_ANSWER


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("페이지별 체류 시간", ["체류 시간"]),
        ("오래 머문 시간 순으로", ["머문 시간"]),
        ("재방문 많은 사이트", ["재방문"]),
        ("다시 본 횟수 그래프", ["다시 본 횟수"]),
        ("체류 비자 관련 글 몇 개 봤어", []),
        ("이번 달 사이트별 그래프", []),
    ],
)
def test_unsupported_by_rule(message, expected):
    assert unsupported_by_rule(message) == expected


# --- 앞선 대시보드 ---


def test_latest_dashboard_is_the_most_recent_one():
    older = Dashboard(title="옛것", period="전체 기간", panels=[])
    newer = Dashboard(title="새것", period="전체 기간", panels=[])
    history = [
        Message(id=1, role=MessageRole.ASSISTANT, content="a", dashboard=older.model_dump(mode="json")),
        Message(id=2, role=MessageRole.USER, content="b"),
        Message(id=3, role=MessageRole.ASSISTANT, content="c", dashboard=newer.model_dump(mode="json")),
        Message(id=4, role=MessageRole.ASSISTANT, content="d"),
    ]

    assert latest_dashboard(history).title == "새것"


def test_an_unreadable_stored_dashboard_is_ignored():
    history = [Message(id=1, role=MessageRole.ASSISTANT, content="a", dashboard={"panels": "broken"})]

    assert latest_dashboard(history) is None


@pytest.mark.parametrize(
    ("url", "host"),
    [
        ("https://www.github.com/x", "github.com"),
        ("https://gist.github.com/y", "gist.github.com"),
        ("not a url", ""),
        ("", ""),
        ("http://[::1", ""),
    ],
)
def test_url_host(url, host):
    assert url_host(url) == host
