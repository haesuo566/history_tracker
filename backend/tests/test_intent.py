import pytest

from backend.services.intent import Intent, classify_by_regex


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
