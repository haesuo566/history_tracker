from backend.core.model_catalog import GenerationProvider
from backend.services.llm import provider
from backend.services.llm.gemini import GeminiGenerator
from backend.services.llm.openai_compat import OpenAICompatGenerator
from tests.test_runtime_settings import runtime_settings


def test_gemini_is_used_unless_another_provider_is_chosen(monkeypatch):
    monkeypatch.setattr(provider, "get_settings", lambda: runtime_settings(generation_model="gemini-2.5-pro"))

    generator = provider.get_generator()

    assert isinstance(generator, GeminiGenerator)
    assert generator.model == "gemini-2.5-pro"


def test_a_local_server_gets_its_address_model_and_options(monkeypatch):
    monkeypatch.setattr(
        provider,
        "get_settings",
        lambda: runtime_settings(
            generation_provider=GenerationProvider.OPENAI_COMPAT,
            llm_base_url="http://localhost:11434",
            llm_model="qwen3.5:4b",
            llm_api_key="",
            llm_disable_thinking=True,
        ),
    )

    generator = provider.get_generator()

    assert isinstance(generator, OpenAICompatGenerator)
    assert generator.model == "qwen3.5:4b"
    assert generator._url == "http://localhost:11434/v1/chat/completions"
    # 빈 키는 보내지 않고, 생각 끄기는 reasoning_effort로 나간다.
    assert generator._api_key is None
    assert generator._reasoning_effort == "none"
