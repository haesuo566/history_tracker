from dataclasses import dataclass

# 청크 하나의 최대 문자 수를 알려주지 않았을 때 쓰는 값. 임베딩이 한 번에 받는 분량은 모델이
# 정하므로(core.model_catalog.chunk_chars_for) 정상 경로에서는 항상 계산된 값이 넘어온다.
DEFAULT_MAX_CHARS = 2048


@dataclass
class TextChunk:
    text: str
    char_start: int
    char_end: int


def chunk_text(full_text: str, max_chars: int = DEFAULT_MAX_CHARS) -> list[TextChunk]:
    """full_text를 max_chars 기준으로 나눠 TextChunk 목록을 반환한다.

    각 조각은 최대 길이 안에서 가장 가까운 개행(\\n) 위치까지 자르고,
    남은 길이가 최대 길이 이하면 그대로 마지막 조각으로 넣는다.

    자르는 기준이 토큰이 아니라 문자인 것은 임베딩 모델의 토크나이저를 로컬에서 돌릴 수 없기
    때문이다. 대신 문자 수 한계를 토큰 한계에서 보수적으로 환산해 받는다 — 넘치면 오류가 나는
    대신 뒷부분이 조용히 버려지므로(Gemini도 TEI도 그렇다) 넉넉하게 잡아선 안 된다.
    """
    n = len(full_text)
    chunks: list[TextChunk] = []
    start = 0
    while start < n:
        end = start + max_chars
        if end >= n:
            chunks.append(TextChunk(text=full_text[start:n], char_start=start, char_end=n))
            break
        split_at = full_text.rfind("\n", start, end)
        end = split_at + 1 if split_at != -1 else end
        chunks.append(TextChunk(text=full_text[start:end], char_start=start, char_end=end))
        start = end
    return chunks
