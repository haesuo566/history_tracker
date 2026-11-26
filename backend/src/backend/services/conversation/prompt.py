"""저장된 대화를 생성 모델에 실을 수 있는 모양(ChatMessage)으로 옮긴다.

재작성 호출(query_parser)과 답변 호출(answer)이 같은 맥락을 봐야 하므로 옮기는 규칙을 한곳에 둔다.
규칙이 갈리면 재작성은 '아까 그 두 번째'가 무엇인지 아는데 답변은 모르는 상태가 된다.
"""

from collections.abc import Mapping, Sequence
from itertools import dropwhile

from backend.models.conversation import Message, MessageRole
from backend.models.document import Document
from backend.services.llm.generation import ChatMessage


def format_listing(documents: Sequence[Document]) -> str:
    """결과 목록을 번호가 붙은 여러 줄로 만든다. 번호는 사용자가 본 순서 그대로다."""
    return "\n".join(
        f"{index}. {document.title} ({document.url})"
        for index, document in enumerate(documents, start=1)
    )


def render_history(
    history: Sequence[Message],
    shown: Mapping[int, Sequence[Document]] = {},
) -> list[ChatMessage]:
    """이전 메시지를 멀티턴 대화로 옮긴다. 이번 입력은 부르는 쪽이 뒤에 붙인다.

    생성 모델은 대화가 user 발화로 시작하길 기대한다(Gemini는 아니면 호출이 깨진다). 정상
    경로에서는 user/assistant가 짝을 이루지만 답변 생성이 실패해 user 메시지만 저장된 턴이 있으면
    최근 N건을 자른 결과가 assistant부터 시작할 수 있어, 앞쪽 assistant 발화는 버린다.

    shown(메시지 id -> 그 턴이 보여준 문서)이 주어지면 해당 발화 뒤에 그 목록을 덧붙인다.
    messages.content에는 답변 문장만 남아 어떤 URL을 보여줬는지가 대화 기록만으로는 되살아나지
    않기 때문이다(services/conversation/results.py). 별개의 발화로 끼우지 않고 발화 안에 붙이는 것은 user/assistant
    교대를 깨지 않기 위해서다 — 사이에 user 발화를 넣으면 그 턴 구조가 무너진다.
    """
    spoken = (past for past in history if past.content)
    turns = dropwhile(lambda past: past.role != MessageRole.USER, spoken)

    messages = []
    for past in turns:
        listed = shown.get(past.id) if past.id is not None else None
        text = (
            f"{past.content}\n\n[이 턴에 보여준 목록]\n{format_listing(listed)}"
            if listed
            else past.content
        )
        role = "assistant" if past.role == MessageRole.ASSISTANT else "user"
        messages.append(ChatMessage(role=role, text=text))
    return messages
