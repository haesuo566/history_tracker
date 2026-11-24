import pytest

from backend.services.chat.intent import Intent, classify_by_regex


@pytest.mark.parametrize(
    "message",
    [
        "지난주에 봤던 요리 블로그 찾아줘",
        "어제 본 뉴스 기사 링크 좀 찾아줘",
        "그 사이트 다시 검색해줘",
        "북마크 해놨던 페이지 있었는데",
    ],
)
def test_classify_by_regex_recall(message):
    assert classify_by_regex(message) == Intent.RECALL


@pytest.mark.parametrize("message", ["안녕", "고마워ㅎㅎ"])
def test_classify_by_regex_etc(message):
    assert classify_by_regex(message) == Intent.ETC


@pytest.mark.parametrize(
    "message",
    [
        "오늘 날씨 어때",
        "너 이름이 뭐야",
        "ㅇㅇ",
        "그거 요약해줘",
        "가격 얼마였어",
        "저거 내용이 뭐였지",
    ],
)
def test_classify_by_regex_ambiguous_falls_through(message):
    assert classify_by_regex(message) is None


def test_classify_by_regex_empty_message():
    assert classify_by_regex("") == Intent.ETC
    assert classify_by_regex("   ") == Intent.ETC


@pytest.mark.parametrize(
    "message",
    [
        "이번 달 사이트별로 본 페이지 그래프",
        "요일별 추이 보여줘",
        "지난주에 몇 개 봤어",
        "대쉬보드 만들어줘",
        "시간대별 통계",
    ],
)
def test_classify_by_regex_dashboard(message):
    assert classify_by_regex(message) == Intent.DASHBOARD


@pytest.mark.parametrize(
    "message",
    [
        # 차트를 다룬 글을 찾는 것인지, 기록을 차트로 그려 달라는 것인지는 문장을 읽어야 갈린다.
        "어제 본 차트 라이브러리 글 찾아줘",
        "방문 기록 통계 보여줘",
    ],
)
def test_classify_by_regex_dashboard_and_recall_words_together_fall_through(message):
    assert classify_by_regex(message) is None


def test_pointing_at_the_nth_result_is_not_a_count():
    """'몇 번째'는 지목이지 개수를 묻는 말이 아니다."""
    assert classify_by_regex("몇 번째 거였지") is None
