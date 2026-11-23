"""domain.Chunk: metadata dict와 오가는 변환. chunks.jsonl의 한 줄이 바뀌지 않는지 본다."""

import json
from pathlib import Path

import pytest

from golden_set.domain.chunk import Chunk
from golden_set.domain.store import read_chunks, write_chunks

META = {"source": "dir/a.pdf", "file_type": "pdf", "loader": "pymupdf", "page": 3, "chunk_id": "a.pdf:p3:0:abcd1234", "chunk_index": 0}


def test_from_metadata_fills_fields_and_keeps_the_rest() -> None:
    c = Chunk.from_metadata("본문", META)
    assert (c.chunk_id, c.text, c.source, c.page, c.file_type, c.loader) == ("a.pdf:p3:0:abcd1234", "본문", "dir/a.pdf", 3, "pdf", "pymupdf")
    assert c.extra == {"chunk_index": 0}
    assert c.metadata == META and list(c.metadata) == list(META)  # 키 순서도 chunks.jsonl과 같다


def test_metadata_omits_what_the_source_did_not_have() -> None:
    c = Chunk.from_metadata("본문", {"source": "a.txt", "file_type": "txt", "loader": "stdlib", "chunk_id": "a.txt:p0:1:ffff", "chunk_index": 1})
    assert c.page is None and "page" not in c.metadata
    bare = Chunk(chunk_id="x", text="t")
    assert bare.metadata == {"chunk_id": "x"}


def test_page_that_is_not_a_number_is_kept_as_is() -> None:
    c = Chunk.from_metadata("본문", {**META, "page": "iv"})
    assert c.page is None and c.metadata["page"] == "iv"


def test_chunk_id_is_required() -> None:
    with pytest.raises(KeyError):
        Chunk.from_metadata("본문", {"source": "a.pdf"})


def test_chunks_jsonl_row_is_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "chunks.jsonl"
    write_chunks([Chunk.from_metadata("강호의 규율", META)], str(path))
    line = path.read_text(encoding="utf-8")
    assert line == '{"chunk_id": "a.pdf:p3:0:abcd1234", "text": "강호의 규율", "metadata": ' + json.dumps(META, ensure_ascii=False) + "}\n"
    (back,) = read_chunks(str(path))
    assert back == Chunk.from_metadata("강호의 규율", META)
    write_chunks([back], str(path))
    assert path.read_text(encoding="utf-8") == line  # 읽어서 다시 써도 같은 바이트다


def test_read_chunks_takes_chunk_id_from_the_row_when_metadata_lacks_it(tmp_path: Path) -> None:
    path = tmp_path / "chunks.jsonl"
    path.write_text('{"chunk_id": "c1", "text": "t", "metadata": {"source": "a.txt"}}\n\n', encoding="utf-8")
    (c,) = read_chunks(str(path))
    assert (c.chunk_id, c.source) == ("c1", "a.txt")
    path.write_text('{"text": "t"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="bad chunk row"):
        read_chunks(str(path))
