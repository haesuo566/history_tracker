import re
from enum import StrEnum


class Intent(StrEnum):
    """chat 메시지를 분류하는 3가지 의도."""

    # DETAIL은 RECALL을 더 나눈 것이다. 기록에서 새로 찾는 것(RECALL)과 이미 찾아준 결과 중
    # 하나를 지목해 더 캐묻는 것(DETAIL)은 앞선 대화를 봐야 갈리므로, 정규식은 이 둘을 구분하지
    # 못하고 재작성 호출(services/chat/query_parser.py)이 가린다.
    RECALL = "recall"
    DETAIL = "detail"
    # 기록을 하나하나 찾는 대신 모아서 센다(services/dashboard/builder.py). 같은 기록을 보지만 답이 목록이
    # 아니라 집계라서 갈래가 다르다.
    DASHBOARD = "dashboard"
    ETC = "etc"


_RECALL_KEYWORDS = re.compile(
    r"찾아|검색|서치|북마크|즐겨찾기|방문\s?기록|열람\s?기록|기록에|히스토리에|"
    r"url|링크\s?(줘|알려|보내)",
    re.IGNORECASE,
)
_RECALL_RECOLLECTION = re.compile(
    r"(봤|봤었|봤던|본\s?적|읽었|읽었던|들어갔|열었|방문했|접속했)"
    r".{0,15}?(사이트|페이지|글|블로그|기사|영상|뉴스|링크|주소|탭|자료|문서)"
)
_ETC_GREETING = re.compile(r"^(안녕|반가워|고마워|고마웠|감사|잘\s?가|수고)?[ㅋㅎ.!?\s]*$")
# '몇 번'은 '몇 번째 것'(detail)과 겹치므로 '째'가 붙지 않은 것만 센다.
_DASHBOARD_KEYWORDS = re.compile(
    r"그래프|차트|대시보드|대쉬보드|시각화|통계|추이|분포|비중|"
    r"몇\s?(개|곳|번(?!\s?째))|"
    r"(날짜|일|주|월|요일|시간대|사이트|도메인)\s?별"
)


def classify_by_regex(message: str) -> Intent | None:
    """정규식/키워드로 의도를 분류한다. 확신할 수 없으면 None을 반환한다.

    판정 불가(None)는 전처리에서 질의 재작성 호출이 맡는다. '그거 뭐였지'처럼 앞선 대화를
    가리키는 후속 질문은 원문만으로는 갈릴 수 없고 history가 있어야 판단되기 때문이다.

    여기서 나오는 RECALL은 '기록 관련'까지만 뜻한다. DETAIL은 절대 나오지 않는다 — '찾아줘'
    같은 키워드는 새로 찾는 질문과 이미 찾아준 결과를 캐묻는 질문에 똑같이 붙는다.

    대시보드 낱말과 찾기 낱말이 함께 있으면 판정하지 않는다. '어제 본 차트 라이브러리 글 찾아줘'는
    차트를 그려 달라는 말이 아니다. 어느 쪽이 주어인지는 문장을 읽어야 갈린다.
    """
    stripped = message.strip()
    if not stripped:
        return Intent.ETC
    wants_recall = bool(_RECALL_KEYWORDS.search(stripped) or _RECALL_RECOLLECTION.search(stripped))
    wants_dashboard = bool(_DASHBOARD_KEYWORDS.search(stripped))
    if wants_recall and wants_dashboard:
        return None
    if wants_dashboard:
        return Intent.DASHBOARD
    if wants_recall:
        return Intent.RECALL
    if _ETC_GREETING.match(stripped):
        return Intent.ETC
    return None
