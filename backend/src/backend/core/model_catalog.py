"""설정 화면에서 고를 수 있는 임베딩·생성 모델 목록.

Gemini의 models.list로 실시간 조회하는 대신 상수로 둔다. API key가 아직 없거나 잘못된 상태에서도
설정 화면이 떠야 하는데, 그 목록을 API로 받아오면 정작 key를 입력하려는 순간에 목록이 비어버린다.

목록에 없는 모델을 쓰고 싶으면 .env로 지정할 수 있다(services.runtime_settings). 여기 상수는
화면에서 고를 수 있는 후보일 뿐이고, DB에 저장할 때만 이 목록 안인지 검증한다.

임베딩은 목록 대신 제공자(EmbeddingProvider)를 고른다. TEI는 서버에 올려둔 모델 하나를 그대로
쓰므로 이쪽에서 후보를 늘어놓을 수 없다 — 무엇이 올라가 있는지는 그 서버만 안다.
"""

from enum import StrEnum
from typing import NamedTuple


class ModelOption(NamedTuple):
    id: str
    label: str


class EmbeddingModelOption(NamedTuple):
    id: str
    label: str
    # 이 모델이 낼 수 있는 최대 임베딩 차원. Settings.embedding_dim이 이 값을 넘으면 임베딩
    # 호출이 실패하므로 저장 시점에 걸러낸다. 두 모델 모두 MRL이라 이 값 이하는 자유롭게 낸다.
    max_dim: int
    # 한 번에 받는 입력 토큰 수. 이걸 넘기면 오류가 나는 대신 뒷부분이 조용히 버려진다.
    max_input_tokens: int


class EmbeddingProvider(StrEnum):
    """임베딩을 어디서 받아올지."""

    GEMINI = "gemini"
    TEI = "tei"


PROVIDER_LABELS = {
    EmbeddingProvider.GEMINI: "Gemini API",
    EmbeddingProvider.TEI: "TEI (자체 호스팅)",
}

# provider를 한 번도 고른 적 없는 환경은 예전처럼 Gemini를 쓴다.
DEFAULT_EMBEDDING_PROVIDER = EmbeddingProvider.GEMINI

# 답변 생성(answer_model)과 질의 재작성(query_rewrite_model)에 함께 쓰는 목록이다. 질의 재작성은
# 구조화 출력(response_schema)을 쓰므로 그것을 지원하는 텍스트 모델만 담는다 — 이미지·음성·live
# 전용 모델은 제외했다.
GENERATION_MODELS: tuple[ModelOption, ...] = (
    ModelOption("gemini-3.7-flash", "Gemini 3.7 Flash"),
    ModelOption("gemini-3.6-flash", "Gemini 3.6 Flash"),
    ModelOption("gemini-3.5-flash", "Gemini 3.5 Flash"),
    ModelOption("gemini-3.5-flash-lite", "Gemini 3.5 Flash Lite"),
    ModelOption("gemini-3.1-pro-preview", "Gemini 3.1 Pro (preview)"),
    ModelOption("gemini-3.1-flash-lite", "Gemini 3.1 Flash Lite"),
    ModelOption("gemini-2.5-pro", "Gemini 2.5 Pro"),
    ModelOption("gemini-2.5-flash", "Gemini 2.5 Flash"),
)

EMBEDDING_MODELS: tuple[EmbeddingModelOption, ...] = (
    EmbeddingModelOption("gemini-embedding-2", "Gemini Embedding 2", max_dim=3072, max_input_tokens=8192),
    EmbeddingModelOption("gemini-embedding-001", "Gemini Embedding 001", max_dim=3072, max_input_tokens=2048),
)

# 한 토큰이 몇 글자인지. 청크를 자를 때 토큰 한계를 문자 수로 바꾸는 데 쓴다.
#
# 실제 수집된 한국어 문서로 재보면 1.11~2.61 자/토큰이다(영어·코드는 3~4자). 최악에 맞추지 않으면
# 어떤 문서는 한계를 넘고, 넘친 뒷부분은 오류 없이 버려져 벡터 검색에서 통째로 빠진다. 조용히
# 나빠지는 쪽이 청크가 좀 짧아지는 쪽보다 나쁘므로 가장 촘촘한 경우를 기준으로 잡는다.
CHARS_PER_TOKEN = 1.1

# 모델을 목록에서 못 찾거나 TEI가 한계를 알려주지 않을 때 쓰는 값. TEI의 기본 max_input_length다.
FALLBACK_MAX_INPUT_TOKENS = 512


def chunk_chars_for(max_input_tokens: int) -> int:
    """토큰 한계를 청크 문자 수로 환산한다."""
    return max(1, int(max_input_tokens * CHARS_PER_TOKEN))


def find_generation_model(model_id: str) -> ModelOption | None:
    return next((option for option in GENERATION_MODELS if option.id == model_id), None)


def find_embedding_model(model_id: str) -> EmbeddingModelOption | None:
    return next((option for option in EMBEDDING_MODELS if option.id == model_id), None)
