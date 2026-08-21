import json

import httpx
import pytest

from backend.services import tei
from backend.services.tei import (
    MAX_BATCH_SIZE,
    TeiError,
    _endpoint,
    _info_endpoint,
    embed,
    fetch_max_input_tokens,
)

BASE_URL = "http://tei.internal:8080"


def echo_handler(request: httpx.Request) -> httpx.Response:
    """입력 개수만큼, 배치 안의 index 를 첫 성분으로 담은 벡터를 돌려주는 정상 서버."""
    inputs = json.loads(request.content)["input"]
    return httpx.Response(
        200,
        json={
            "object": "list",
            "data": [
                {"object": "embedding", "index": index, "embedding": [float(index), 0.5]}
                for index in range(len(inputs))
            ],
            "model": "BAAI/bge-m3",
            "usage": {"prompt_tokens": 1, "total_tokens": 1},
        },
    )


class FakeTei:
    """가짜 TEI. 요청을 기록하고, 테스트가 원하면 응답 handler 를 바꿔 끼운다."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.handler = echo_handler

    def serve(self, handler) -> None:
        self.handler = handler

    def dispatch(self, request: httpx.Request) -> httpx.Response:
        # /info 는 GET 이라 본문이 없다.
        body = json.loads(request.content) if request.content else None
        self.calls.append((str(request.url), body))
        return self.handler(request)

    def bodies(self) -> list[dict]:
        return [body for _url, body in self.calls if body is not None]


@pytest.fixture
def fake_tei(monkeypatch):
    """httpx.Client 를 MockTransport 를 물린 것으로 바꿔치운다.

    요청 조립과 응답 파싱은 실제 코드를 그대로 거치므로, 우리가 보내는 본문과 읽는 방식을 함께
    확인할 수 있다. 원본 Client 를 미리 잡아 두는 것은 monkeypatch 가 httpx.Client 자체를 바꿔서,
    대체 함수 안에서 httpx.Client 를 부르면 자기를 다시 부르기 때문이다.
    """
    real_client = httpx.Client
    server = FakeTei()

    monkeypatch.setattr(
        tei.httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(server.dispatch), **kwargs),
    )
    return server


def test_a_bare_host_gets_the_openai_path():
    assert _endpoint("http://tei:8080") == "http://tei:8080/v1/embeddings"


def test_a_trailing_slash_does_not_double_up():
    assert _endpoint("http://tei:8080/") == "http://tei:8080/v1/embeddings"


def test_a_v1_suffix_is_not_repeated():
    """설정 화면만 보고는 /v1 을 붙여야 하는지 알 수 없다. 어느 쪽으로 적어도 같은 곳이어야 한다."""
    assert _endpoint("http://tei:8080/v1") == "http://tei:8080/v1/embeddings"


def test_a_full_path_is_left_alone():
    assert _endpoint("http://tei:8080/v1/embeddings") == "http://tei:8080/v1/embeddings"


def test_the_info_path_sits_next_to_the_root():
    """/info 는 OpenAI 호환 경로가 아니라 TEI 고유라 /v1 아래에 없다."""
    assert _info_endpoint("http://tei:8080") == "http://tei:8080/info"
    assert _info_endpoint("http://tei:8080/v1") == "http://tei:8080/info"
    assert _info_endpoint("http://tei:8080/v1/embeddings") == "http://tei:8080/info"


def test_the_input_limit_is_read_from_info(fake_tei):
    fake_tei.serve(lambda request: httpx.Response(200, json={"max_input_length": 8192}))

    assert fetch_max_input_tokens(BASE_URL) == 8192


def test_a_compatible_server_key_is_also_accepted(fake_tei):
    """vLLM 등은 이름이 다르다. 못 읽으면 보수적 기본값으로 내려가 청크가 불필요하게 짧아진다."""
    fake_tei.serve(lambda request: httpx.Response(200, json={"max_model_len": 4096}))

    assert fetch_max_input_tokens(BASE_URL) == 4096


def test_info_without_a_limit_returns_none(fake_tei):
    fake_tei.serve(lambda request: httpx.Response(200, json={"model_id": "BAAI/bge-m3"}))

    assert fetch_max_input_tokens(BASE_URL) is None


def test_an_unreachable_info_does_not_raise(fake_tei):
    """/info 를 안 내놓는 호환 서버도 있다. 여기서 던지면 색인을 아예 시작할 수 없다."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    fake_tei.serve(refuse)

    assert fetch_max_input_tokens(BASE_URL) is None


def test_a_missing_base_url_skips_the_info_call(fake_tei):
    assert fetch_max_input_tokens("") is None
    assert fake_tei.calls == []


def test_embedding_returns_one_vector_per_input(fake_tei):
    vectors = embed(["첫째", "둘째"], base_url=BASE_URL)

    assert vectors == [[0.0, 0.5], [1.0, 0.5]]
    assert len(fake_tei.calls) == 1


def test_the_request_goes_to_the_openai_path(fake_tei):
    embed(["하나"], base_url=BASE_URL)

    assert fake_tei.calls[0][0] == f"{BASE_URL}/v1/embeddings"


def test_an_empty_input_does_not_call_the_server(fake_tei):
    assert embed([], base_url=BASE_URL) == []
    assert fake_tei.calls == []


def test_the_model_is_omitted_when_not_set(fake_tei):
    """TEI 는 model 을 검증하지 않는다. 비워 둔 설정을 빈 문자열로 실어 보내면 호환 서버가 거부한다."""
    embed(["하나"], base_url=BASE_URL)

    assert "model" not in fake_tei.bodies()[0]


def test_the_model_is_sent_when_set(fake_tei):
    embed(["하나"], base_url=BASE_URL, model="BAAI/bge-m3")

    assert fake_tei.bodies()[0]["model"] == "BAAI/bge-m3"


def test_a_long_input_list_is_split_into_batches(fake_tei):
    """TEI 의 max-client-batch-size 기본값이 32다. 통째로 보내면 긴 문서에서 413이 된다."""
    count = MAX_BATCH_SIZE + 5

    vectors = embed([f"청크 {index}" for index in range(count)], base_url=BASE_URL)

    assert len(vectors) == count
    assert [len(body["input"]) for body in fake_tei.bodies()] == [MAX_BATCH_SIZE, 5]


def test_batches_keep_the_original_order(fake_tei):
    """두 번째 배치의 벡터가 앞으로 오면 다른 청크의 좌표가 조용히 붙는다."""
    count = MAX_BATCH_SIZE + 2

    vectors = embed([f"청크 {index}" for index in range(count)], base_url=BASE_URL)

    # 각 배치는 배치 안에서의 index 를 첫 성분으로 돌려준다. 순서가 유지되면 0..31 다음에 0..1 이다.
    assert [vector[0] for vector in vectors[:MAX_BATCH_SIZE]] == [float(i) for i in range(MAX_BATCH_SIZE)]
    assert [vector[0] for vector in vectors[MAX_BATCH_SIZE:]] == [0.0, 1.0]


def test_a_shuffled_response_is_put_back_in_order(fake_tei):
    """응답 순서를 그대로 믿으면 벡터가 어긋난 채 오류 없이 색인된다."""
    fake_tei.serve(
        lambda request: httpx.Response(
            200, json={"data": [{"index": 1, "embedding": [1.0]}, {"index": 0, "embedding": [0.0]}]}
        )
    )

    assert embed(["첫째", "둘째"], base_url=BASE_URL) == [[0.0], [1.0]]


def test_a_missing_base_url_is_rejected_before_calling():
    with pytest.raises(TeiError, match="TEI 주소"):
        embed(["하나"], base_url="")


def test_a_short_response_is_an_error(fake_tei):
    """입력보다 적게 돌아오면 어느 청크가 빠졌는지 알 수 없다. 짝을 맞춰 색인할 수 없다."""
    fake_tei.serve(lambda request: httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1]}]}))

    with pytest.raises(TeiError, match="2건에 대해 1건"):
        embed(["첫째", "둘째"], base_url=BASE_URL)


def test_a_duplicated_index_is_an_error(fake_tei):
    fake_tei.serve(
        lambda request: httpx.Response(
            200, json={"data": [{"index": 0, "embedding": [0.1]}, {"index": 0, "embedding": [0.2]}]}
        )
    )

    with pytest.raises(TeiError, match="중복된 index"):
        embed(["첫째", "둘째"], base_url=BASE_URL)


def test_a_base64_embedding_is_rejected(fake_tei):
    """encoding_format 을 지정하지 않아도 서버 설정에 따라 문자열이 올 수 있다."""
    fake_tei.serve(lambda request: httpx.Response(200, json={"data": [{"index": 0, "embedding": "AAAA"}]}))

    with pytest.raises(TeiError, match="실수 배열"):
        embed(["하나"], base_url=BASE_URL)


def test_a_response_without_data_is_rejected(fake_tei):
    fake_tei.serve(lambda request: httpx.Response(200, json={"object": "list"}))

    with pytest.raises(TeiError, match="data 배열"):
        embed(["하나"], base_url=BASE_URL)


def test_an_error_status_carries_the_server_message(fake_tei):
    """입력 길이나 배치 크기 위반은 본문에 이유가 담겨 온다. 그것이 없으면 원인을 못 찾는다."""
    fake_tei.serve(
        lambda request: httpx.Response(413, text="batch size 40 > maximum allowed batch size 32")
    )

    with pytest.raises(TeiError, match="413.*maximum allowed batch size"):
        embed(["하나"], base_url=BASE_URL)


def test_a_connection_failure_names_the_address(fake_tei):
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    fake_tei.serve(refuse)

    with pytest.raises(TeiError, match="연결할 수 없습니다"):
        embed(["하나"], base_url=BASE_URL)
