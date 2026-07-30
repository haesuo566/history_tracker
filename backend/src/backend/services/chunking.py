from dataclasses import dataclass

MAX_TOKENS = 2048
CHARS_PER_TOKEN = 4


@dataclass
class TextChunk:
    text: str
    char_start: int
    char_end: int


def chunk_text(
    full_text: str,
    max_tokens: int = MAX_TOKENS,
    chars_per_token: int = CHARS_PER_TOKEN,
) -> list[TextChunk]:
    """full_text를 max_tokens(문자 수 근사치) 기준으로 나눠 TextChunk 목록을 반환한다.

    각 조각은 근사 최대 길이 안에서 가장 가까운 개행(\\n) 위치까지 자르고,
    남은 길이가 근사 최대 길이 이하면 그대로 마지막 조각으로 넣는다.
    """
    max_chars = max_tokens * chars_per_token
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
