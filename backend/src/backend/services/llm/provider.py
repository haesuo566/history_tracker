"""지금 설정에 맞는 생성 모델을 골라 준다.

부르는 쪽(services.chat.answer 등)은 이 함수만 알고, 어느 제공자의 어떤 모델인지는 모른다.
"""

from backend.core.model_catalog import GenerationProvider
from backend.services.llm.gemini import GeminiGenerator
from backend.services.llm.generation import Generator
from backend.services.llm.openai_compat import OpenAICompatGenerator
from backend.services.runtime_settings import get_settings


def get_generator() -> Generator:
    """매번 설정을 읽어 만든다. 설정 화면에서 제공자나 모델을 바꾸면 다음 호출부터 따라간다."""
    current = get_settings()
    if current.generation_provider is GenerationProvider.OPENAI_COMPAT:
        return OpenAICompatGenerator(
            current.llm_base_url,
            current.llm_model,
            api_key=current.llm_api_key or None,
            reasoning_effort="none" if current.llm_disable_thinking else None,
        )
    return GeminiGenerator(current.generation_model)
