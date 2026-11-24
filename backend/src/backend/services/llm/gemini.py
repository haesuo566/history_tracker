"""Gemini 클라이언트를 한 곳에서 만들어 준다.

answer·embedding·query_parser가 각자 클라이언트를 캐시하고 있었는데, API key를 화면에서 바꿀 수
있게 되면서 세 캐시를 동시에 버려야 하는 문제가 생겼다. 캐시를 여기 하나로 모으고 key가 바뀌면
새로 만든다.
"""

from google import genai

from backend.services.runtime_settings import get_settings

_client: genai.Client | None = None
_client_api_key: str | None = None


def get_client() -> genai.Client:
    """지금 설정된 API key로 만든 클라이언트. key가 바뀌었으면 새로 만든다."""
    global _client, _client_api_key

    api_key = get_settings().gemini_api_key
    if not api_key:
        # 여기서 막지 않으면 클라이언트 생성이나 첫 호출에서 맥락 없는 오류가 난다.
        raise RuntimeError("Gemini API key가 설정되지 않았습니다. 설정 화면에서 입력해 주세요.")

    if _client is None or _client_api_key != api_key:
        _client = genai.Client(api_key=api_key)
        _client_api_key = api_key
    return _client
