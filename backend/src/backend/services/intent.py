import re
from enum import StrEnum


class Intent(StrEnum):
    """chat 메시지를 분류하는 2가지 의도."""

    RECALL = "recall"
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


def classify_by_regex(message: str) -> Intent | None:
    """정규식/키워드로 의도를 분류한다. 확신할 수 없으면 None을 반환한다.

    판정 불가(None)는 전처리에서 질의 재작성 호출이 맡는다. '그거 뭐였지'처럼 앞선 대화를
    가리키는 후속 질문은 원문만으로는 갈릴 수 없고 history가 있어야 판단되기 때문이다.
    """
    stripped = message.strip()
    if not stripped:
        return Intent.ETC
    if _RECALL_KEYWORDS.search(stripped) or _RECALL_RECOLLECTION.search(stripped):
        return Intent.RECALL
    if _ETC_GREETING.match(stripped):
        return Intent.ETC
    return None
