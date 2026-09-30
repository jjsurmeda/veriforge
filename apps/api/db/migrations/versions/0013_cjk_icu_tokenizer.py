"""Segment CJK with the ICU tokenizer so the BM25 leg works (KI-19).

Implements: TRD §9.1 (hybrid retrieval), TRD §7 (ingress lexical_weight).

The default tokenizer treats a whole CJK question as one unsegmented token
run, so `孫悟空的兵器是什麼？` matched nothing and the BM25 leg of hybrid
search contributed zero candidates for every natural Chinese or Japanese
question. Retrieval was silently pure-vector for those languages while
fusion still weighted the dead leg at `lexical_weight`.

`icu` segments both corpus languages by word and leaves Latin script
byte-identical to the previous tokenizer, so English retrieval does not
change. Measured with `paradedb.tokenize` on pg_search 0.25.9:

    '孫悟空的兵器是什麼？'  default → 孫悟空的兵器是什麼   (1 token)
                             icu     → 孫悟空 的 兵器 是 什麼
    '羅生門で老婆は何をしていましたか？' icu → 羅生門 で 老婆 は 何 を し てい まし たか
    'the AW-2000-XE blade ships with a 12 month warranty'
                             default → identical to icu

`chinese_lindera` also segments CJK correctly but emits an *empty* token
between Latin words, which matches every document and destroys English
precision, so it was rejected. `jieba` and `japanese_lindera` were
measured and rejected for the same reason: `japanese_lindera` splits the
Chinese title 西遊記 into 西遊 | 記, and jieba splits 孫悟空 into 孫 | 悟空.

Only the BM25 index is rebuilt. The embedding index and every stored
embedding are untouched — this is a re-tokenisation, not a re-embed.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

INDEX_NAME = "ix_chunks_text_bm25"

CREATE_INDEX = (
    f"CREATE INDEX {INDEX_NAME} ON chunks"
    " USING bm25 (id, text)"
    " WITH (key_field='id',"
    ' text_fields=\'{"text": {"tokenizer": {"type": "icu"}}}\')'
)

DROP_INDEX = f"DROP INDEX IF EXISTS {INDEX_NAME}"

CREATE_INDEX_DEFAULT = (
    f"CREATE INDEX {INDEX_NAME} ON chunks"
    " USING bm25 (id, text)"
    " WITH (key_field='id')"
)


def upgrade() -> None:
    op.execute(DROP_INDEX)
    op.execute(CREATE_INDEX)


def downgrade() -> None:
    op.execute(DROP_INDEX)
    op.execute(CREATE_INDEX_DEFAULT)
