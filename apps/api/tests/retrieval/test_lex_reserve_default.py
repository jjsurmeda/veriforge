"""The BM25 reserve has one value, whichever way it is read.

`retrieval/hybrid.py` reads `retrieval.lex_reserve` from the runtime settings and
falls back to `LEX_RESERVE`. The runtime defaults won whenever settings were
loaded, so the product ran a reserve of 24 while the code, the recall
measurement and the docs said 8 (found while writing R2c, 2026-10-19)."""

from retrieval.hybrid import LEX_RESERVE
from runtime import DEFAULT_DATA, RuntimeSettings


def test_the_runtime_default_equals_the_module_constant() -> None:
    assert DEFAULT_DATA["retrieval"]["lex_reserve"] == LEX_RESERVE


def test_loaded_settings_read_the_same_value() -> None:
    assert RuntimeSettings.from_data(1, {}).get("retrieval.lex_reserve") == LEX_RESERVE
