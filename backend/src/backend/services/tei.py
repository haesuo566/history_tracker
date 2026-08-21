"""TEI(Text Embeddings Inference)에서 임베딩을 받아온다.

OpenAI 호환 경로(`POST /v1/embeddings`)를 쓴다. TEI 고유 경로인 `/embed`가 더 단순하지만, 호환
경로를 쓰면 vLLM·Infinity 처럼 같은 규약을 내놓는 서버로 바꿔도 이 파일을 다시 쓰지 않는다.

Gemini의 task_type(RETRIEVAL_DOCUMENT / RETRIEVAL_QUERY)에 해당하는 개념이 TEI에는 없다.
e5 계열이라면 `query: ` / `passage: ` 프리픽스가 그 역할을 하지만, 지금 쓰기로 한 bge-m3는
프리픽스를 요구하지 않으므로 문서와 질의를 같은 방식으로 보낸다. 프리픽스가 필요한 모델로
바꾸려면 그때 설정 항목을 늘려야 한다.
"""

import httpx
from loguru import logger

# TEI의 --max-client-batch-size 기본값이 32다. 한 문서의 청크를 통째로 보내면 긴 문서에서
# 413(batch size error)이 되므로 이 크기로 잘라 보낸다.
MAX_BATCH_SIZE = 32

# 임베딩은 모델과 배치 크기에 따라 초 단위로 걸린다. 색인 배치는 이 호출을 문서마다 반복하므로
# 무한정 기다리게 두면 어디서 멈췄는지 알 수 없다.
TIMEOUT_SECONDS = 60.0


class TeiError(RuntimeError):
    """TEI 호출이 실패했다. 색인 배치가 문서 단위로 이 예외를 잡아 실패로 센다."""


def _root(base_url: str) -> str:
    """설정에 담긴 주소에서 서버 루트를 골라낸다.

    사용자가 `http://host:8080`, `http://host:8080/`, `http://host:8080/v1`,
    `http://host:8080/v1/embeddings` 중 무엇을 넣어도 같은 서버를 가리키게 한다 — 어느 쪽으로
    적어야 하는지는 화면만 보고 알 수 없다.
    """
    trimmed = base_url.rstrip("/")
    for suffix in ("/v1/embeddings", "/embeddings", "/v1"):
        if trimmed.endswith(suffix):
            return trimmed[: -len(suffix)]
    return trimmed


def _endpoint(base_url: str) -> str:
    """임베딩 경로."""
    return f"{_root(base_url)}/v1/embeddings"


def _info_endpoint(base_url: str) -> str:
    """서버가 스스로를 설명하는 경로. OpenAI 호환이 아니라 TEI 고유다."""
    return f"{_root(base_url)}/info"


# /info 가 입력 한계를 담는 키. TEI 는 max_input_length 를 쓰지만, 호환 서버는 이름이 다를 수 있다.
_MAX_INPUT_KEYS = ("max_input_length", "max_model_len", "max_input_tokens")


def fetch_max_input_tokens(base_url: str) -> int | None:
    """서버가 한 번에 받는 입력 토큰 수. 알아내지 못하면 None.

    이 값이 필요한 것은 넘치는 입력이 오류가 아니라 조용한 절삭으로 처리되기 때문이다. TEI 는
    auto_truncate 가 기본으로 켜져 있어, 한계를 넘겨 보내면 뒷부분을 버리고 200 을 돌려준다.

    실패를 예외로 올리지 않는다. 한계를 모르는 것은 보수적인 기본값으로 대신할 수 있는 반면,
    여기서 예외를 내면 /info 를 제공하지 않는 호환 서버에서는 색인을 아예 시작할 수 없다.
    """
    if not base_url:
        return None

    url = _info_endpoint(base_url)
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
            response = client.get(url)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        logger.warning("could not read TEI info from {}: {}", url, error)
        return None

    if not isinstance(payload, dict):
        logger.warning("unexpected TEI info payload from {}", url)
        return None

    for key in _MAX_INPUT_KEYS:
        value = payload.get(key)
        if isinstance(value, int) and value > 0:
            logger.info("TEI reports {}={} at {}", key, value, url)
            return value

    logger.warning("TEI info at {} has no input length field", url)
    return None


def _parse(payload: object, expected: int) -> list[list[float]]:
    """OpenAI 호환 응답에서 벡터를 꺼낸다. index 순으로 되돌린다.

    응답에 담긴 순서를 그대로 믿지 않는다. 순서가 어긋나면 다른 청크의 벡터가 붙어도 오류 없이
    색인되고, 검색 결과가 조용히 엉뚱해진다.
    """
    if not isinstance(payload, dict):
        raise TeiError("TEI 응답이 JSON 객체가 아닙니다.")

    data = payload.get("data")
    if not isinstance(data, list):
        raise TeiError("TEI 응답에 data 배열이 없습니다.")
    if len(data) != expected:
        raise TeiError(f"TEI가 입력 {expected}건에 대해 {len(data)}건을 돌려줬습니다.")

    indexed: dict[int, list[float]] = {}
    for item in data:
        if not isinstance(item, dict):
            raise TeiError("TEI 응답의 data 원소가 객체가 아닙니다.")
        index = item.get("index")
        embedding = item.get("embedding")
        if not isinstance(index, int) or not 0 <= index < expected:
            raise TeiError("TEI 응답의 index가 올바르지 않습니다.")
        # encoding_format을 지정하지 않으면 float 배열로 온다. base64 문자열이 오면 설정이
        # 어긋난 것이므로 그대로 통과시키지 않는다.
        if not isinstance(embedding, list) or not all(isinstance(value, (int, float)) for value in embedding):
            raise TeiError("TEI 응답의 embedding이 실수 배열이 아닙니다.")
        indexed[index] = [float(value) for value in embedding]

    if len(indexed) != expected:
        raise TeiError("TEI 응답에 중복된 index가 있습니다.")
    return [indexed[index] for index in range(expected)]


def embed(texts: list[str], base_url: str, model: str | None = None) -> list[list[float]]:
    """텍스트 목록을 TEI로 임베딩한다. 입력과 같은 순서로 돌려준다."""
    if not texts:
        return []
    if not base_url:
        raise TeiError("TEI 주소가 설정되지 않았습니다. 설정 화면에서 입력해 주세요.")

    url = _endpoint(base_url)
    batches = [texts[start : start + MAX_BATCH_SIZE] for start in range(0, len(texts), MAX_BATCH_SIZE)]
    logger.debug(
        "embedding {} text(s) via TEI {} ({} batch(es), model={})", len(texts), url, len(batches), model or "-"
    )

    embeddings: list[list[float]] = []
    with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
        for batch in batches:
            body: dict[str, object] = {"input": batch}
            # TEI는 model을 검증하지 않고 경고만 남기지만, 호환 서버 중에는 필수인 것이 있다.
            if model:
                body["model"] = model
            try:
                response = client.post(url, json=body)
                response.raise_for_status()
                payload = response.json()
            except httpx.HTTPStatusError as error:
                # 본문에 어떤 검증에 걸렸는지가 담겨 온다(입력 길이, 배치 크기 등).
                detail = error.response.text[:200]
                raise TeiError(f"TEI가 {error.response.status_code}를 반환했습니다: {detail}") from error
            except httpx.HTTPError as error:
                raise TeiError(f"TEI({url})에 연결할 수 없습니다: {error}") from error
            except ValueError as error:
                raise TeiError("TEI 응답을 JSON으로 해석할 수 없습니다.") from error

            embeddings.extend(_parse(payload, len(batch)))

    return embeddings
