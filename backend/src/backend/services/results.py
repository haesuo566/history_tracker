"""그 턴이 사용자에게 보여준 결과 목록을 문서로 되살린다.

messages.result_document_ids에는 보여준 document_id만 순서대로 남는다 — 제목도 URL도 남기지
않는다. 그래서 저장된 대화만으로는 무엇을 보여줬는지 되짚을 수 없고, 화면 복원도 프롬프트의
과거 맥락도 이 조인을 거쳐야 한다.

결과를 메시지에 복제해 두지 않고 매번 되살리는 쪽을 택한 근거는 문서가 불변이라는 점이다.
같은 URL을 다시 수집해도 무시하므로(services/document.py의 on_conflict_do_nothing) title도 url도
처음 값 그대로다. 즉 지금 조인해도 그때 보여준 것과 같은 값이 나온다 — 스냅샷으로 복제해서
지킬 것이 없다.
"""

from collections.abc import Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.conversation import Message, MessageRole
from backend.models.document import Document

# 재작성 프롬프트에 과거 목록을 실을 최대 턴 수.
MAX_LISTED_TURNS = 3


def load_shown_documents(messages: Sequence[Message], db: Session) -> dict[int, list[Document]]:
    """메시지 id -> 그 턴이 보여준 문서 목록(보여준 순서 그대로). 조회는 IN 한 번으로 끝낸다.

    사라진 문서는 조용히 빠진다. 해시 방식을 URL 단위로 바꾸며 중복 문서를 지웠기 때문에
    (db/init_db.py) 그때 지워진 문서를 가리키는 id가 옛 메시지에 남아 있을 수 있다.

    남은 문서가 하나도 없는 턴은 키 자체를 만들지 않는다. 부르는 쪽이 '결과가 있던 턴'을 키의
    존재만으로 가릴 수 있게 하려는 것이다.
    """
    listed = [
        message
        for message in messages
        if message.role == MessageRole.ASSISTANT and message.result_document_ids
    ]
    wanted = {document_id for message in listed for document_id in message.result_document_ids}
    if not wanted:
        return {}

    documents = {
        document.document_id: document
        for document in db.scalars(select(Document).where(Document.document_id.in_(wanted)))
    }

    shown: dict[int, list[Document]] = {}
    for message in listed:
        found = [
            documents[document_id]
            for document_id in message.result_document_ids
            if document_id in documents
        ]
        if found:
            shown[message.id] = found
    return shown


def latest_shown(shown: Mapping[int, Sequence[Document]]) -> list[Document]:
    """가장 최근 결과 턴이 보여준 목록. 결과가 있던 턴이 없으면 빈 목록.

    메시지 id는 단조 증가하므로 가장 큰 키가 가장 최근 턴이다.
    """
    return list(shown[max(shown)]) if shown else []


def past_shown(
    shown: Mapping[int, Sequence[Document]], limit: int = MAX_LISTED_TURNS
) -> dict[int, list[Document]]:
    """가장 최근 결과 턴을 뺀 나머지 중 최근 limit개.

    최근 턴을 빼는 것은 그 목록이 후보 목록으로 이미 따로 실리기 때문이다(query_parser의
    candidates). 같은 목록을 두 번 실으면 토큰만 쓰고, 번호를 두 군데서 세게 만든다.

    limit을 두는 것은 프롬프트 크기 때문이다. 글자 예산(conversation._fit_char_budget)은 메시지
    content의 길이만 세므로 여기서 덧붙는 목록은 그 예산 밖이다. 상한이 없으면 history에 실린
    결과 턴 수만큼 프롬프트가 늘어난다.
    """
    if limit <= 0:
        return {}
    older = sorted(shown)[:-1]
    return {message_id: list(shown[message_id]) for message_id in older[-limit:]}
