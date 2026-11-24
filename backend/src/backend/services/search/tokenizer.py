from kiwipiepy import Kiwi

NOUN_TAGS = {"NNG", "NNP", "NNB"}

_kiwi: Kiwi | None = None


def _get_kiwi() -> Kiwi:
    global _kiwi
    if _kiwi is None:
        _kiwi = Kiwi()
    return _kiwi


def extract_nouns(text: str) -> list[str]:
    """kiwi로 형태소 분석해 명사만 추출한다."""
    return [token.form for token in _get_kiwi().tokenize(text) if token.tag in NOUN_TAGS]
