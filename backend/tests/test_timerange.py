from datetime import datetime, timedelta, timezone

import pytest

from backend.services.timerange import (
    MAX_RECENT_DAYS,
    TimeRange,
    TimeRangeKind,
    resolve,
)

KST = timezone(timedelta(hours=9))

# 2026-08-31은 월요일이다. 주 경계를 보는 테스트가 이 사실에 기대고 있다.
MONDAY_NOON = datetime(2026, 8, 31, 12, 0, tzinfo=KST)


def window(kind: TimeRangeKind, now: datetime = MONDAY_NOON, **fields):
    return resolve(TimeRange(kind=kind, **fields), now)


def test_no_time_expression_means_no_window():
    """기간이 없으면 None이다. '결과 없음'이 아니라 '기간 제한 없음'을 뜻한다."""
    assert resolve(TimeRange(), MONDAY_NOON) is None
    assert resolve(None, MONDAY_NOON) is None


def test_yesterday_is_cut_at_the_local_midnight():
    """어제의 경계는 사용자의 자정이다. UTC로는 아홉 시간 앞이라 날짜가 하루 밀린다."""
    result = window(TimeRangeKind.YESTERDAY)

    assert result.since == datetime(2026, 8, 29, 15, 0)
    assert result.until == datetime(2026, 8, 30, 15, 0)


def test_late_night_today_still_means_the_local_day():
    """밤 11시에 '오늘'을 물으면 UTC로는 이미 다음 날이다. UTC 자정으로 자르면 온종일이 빠진다."""
    result = window(TimeRangeKind.TODAY, now=datetime(2026, 8, 31, 23, 30, tzinfo=KST))

    assert result.since == datetime(2026, 8, 30, 15, 0)  # 8/31 00:00 KST
    assert result.until == datetime(2026, 8, 31, 15, 0)  # 9/1 00:00 KST


def test_the_boundary_belongs_to_one_side_only():
    """같은 자정이 두 구간에 겹쳐 들면 한 문서가 어제와 오늘 양쪽에 걸린다."""
    yesterday = window(TimeRangeKind.YESTERDAY)
    today = window(TimeRangeKind.TODAY)

    assert yesterday.until == today.since


def test_this_week_starts_on_monday():
    result = window(TimeRangeKind.THIS_WEEK, now=datetime(2026, 9, 2, 12, 0, tzinfo=KST))  # 수요일

    assert result.since == datetime(2026, 8, 30, 15, 0)  # 8/31(월) 00:00 KST


def test_last_week_is_the_seven_days_before_this_one():
    result = window(TimeRangeKind.LAST_WEEK)

    assert result.since == datetime(2026, 8, 23, 15, 0)  # 8/24(월) 00:00 KST
    assert result.until == datetime(2026, 8, 30, 15, 0)  # 8/31(월) 00:00 KST


def test_this_month_starts_on_the_first():
    result = window(TimeRangeKind.THIS_MONTH)

    assert result.since == datetime(2026, 7, 31, 15, 0)  # 8/1 00:00 KST


def test_last_month_ends_where_this_month_starts():
    result = window(TimeRangeKind.LAST_MONTH)

    assert result.since == datetime(2026, 6, 30, 15, 0)  # 7/1 00:00 KST
    assert result.until == window(TimeRangeKind.THIS_MONTH).since


def test_last_month_crosses_the_year():
    result = window(TimeRangeKind.LAST_MONTH, now=datetime(2026, 1, 15, 12, 0, tzinfo=KST))

    assert result.since == datetime(2025, 11, 30, 15, 0)  # 2025-12-01 00:00 KST
    assert result.until == datetime(2025, 12, 31, 15, 0)  # 2026-01-01 00:00 KST


def test_recent_days_includes_today():
    """'최근 3일'에서 오늘을 빼면 방금 본 페이지가 빠진다."""
    result = window(TimeRangeKind.RECENT_DAYS, days=3)

    assert result.since == datetime(2026, 8, 28, 15, 0)  # 8/29 00:00 KST
    assert result.until == datetime(2026, 8, 31, 15, 0)  # 9/1 00:00 KST


def test_recent_days_is_capped():
    result = window(TimeRangeKind.RECENT_DAYS, days=100_000)
    capped = window(TimeRangeKind.RECENT_DAYS, days=MAX_RECENT_DAYS)

    assert result.since == capped.since


@pytest.mark.parametrize("days", [None, 0, -3])
def test_recent_days_without_a_usable_count_gives_no_window(days):
    assert window(TimeRangeKind.RECENT_DAYS, days=days) is None


def test_absolute_range_includes_the_last_day():
    """'20일부터 22일까지'의 22일은 통째로 들어가야 한다."""
    result = window(TimeRangeKind.ABSOLUTE, since="2026-08-20", until="2026-08-22")

    assert result.since == datetime(2026, 8, 19, 15, 0)  # 8/20 00:00 KST
    assert result.until == datetime(2026, 8, 22, 15, 0)  # 8/23 00:00 KST


def test_absolute_range_is_ordered():
    swapped = window(TimeRangeKind.ABSOLUTE, since="2026-08-22", until="2026-08-20")
    ordered = window(TimeRangeKind.ABSOLUTE, since="2026-08-20", until="2026-08-22")

    assert (swapped.since, swapped.until) == (ordered.since, ordered.until)


def test_absolute_since_alone_runs_up_to_today():
    result = window(TimeRangeKind.ABSOLUTE, since="2026-08-20")

    assert result.until == datetime(2026, 8, 31, 15, 0)  # 9/1 00:00 KST


def test_absolute_until_alone_runs_from_the_beginning():
    result = window(TimeRangeKind.ABSOLUTE, until="2026-08-20")

    assert result.since == datetime(1970, 1, 1)
    assert result.until == datetime(2026, 8, 20, 15, 0)  # 8/21 00:00 KST


def test_unparsable_dates_are_dropped():
    assert window(TimeRangeKind.ABSOLUTE, since="어제", until=None) is None


def test_the_window_never_runs_past_today():
    """이번 주는 일요일까지지만, 아직 오지 않은 날을 뒤질 이유가 없다."""
    result = window(TimeRangeKind.THIS_WEEK)  # 월요일에 물었다

    assert result.until == datetime(2026, 8, 31, 15, 0)  # 9/1 00:00 KST


def test_a_fully_future_window_is_left_alone():
    """구간이 통째로 미래면 당길 곳이 없다. 그대로 두면 0건이 나오고, 그것이 맞는 답이다."""
    result = window(TimeRangeKind.ABSOLUTE, since="2027-01-01", until="2027-01-02")

    assert result.since < result.until


def test_the_label_speaks_the_users_dates():
    """0건일 때 어느 기간을 뒤졌는지 밝히려면 구간을 사용자의 날짜로 되돌려야 한다."""
    assert window(TimeRangeKind.YESTERDAY).label == "어제(8월 30일)"
    assert window(TimeRangeKind.LAST_WEEK).label == "지난주(8월 24일~8월 30일)"
    assert window(TimeRangeKind.ABSOLUTE, since="2026-08-20").label == "8월 20일~8월 31일"


def test_a_naive_client_now_is_read_as_utc():
    """시각을 싣지 못한 요청에서도 기간 검색이 멈추지는 않는다(경계는 UTC로 어긋난다)."""
    result = window(TimeRangeKind.TODAY, now=datetime(2026, 8, 31, 12, 0))

    assert result.since == datetime(2026, 8, 31, 0, 0)
