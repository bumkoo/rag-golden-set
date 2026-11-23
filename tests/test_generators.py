"""생성기 공통 도우미: 언어 판별, 근거 본문 ↔ 청크 대조, 리포트, 생성기 조회."""

import pytest
from langchain_core.documents import Document

from golden_set.domain.candidate import Source
from golden_set.domain.language import detect_language
from golden_set.generators import GenerateError, GenerateReport, Generator, get_generator
from golden_set.generators.base import ChunkIndex, sources_for
from golden_set.llm import Endpoint, LLMSettings


def chunk(text: str, cid: str, source: str = "a.pdf", page: int | None = 1) -> Document:
    meta: dict = {"source": source, "file_type": "pdf", "loader": "t", "chunk_id": cid, "chunk_index": 0}
    if page is not None:
        meta["page"] = page
    return Document(page_content=text, metadata=meta)


@pytest.mark.parametrize(
    "text, lang",
    [
        ("장문인이 말한 규율의 근원은 무엇인가?", "ko"),
        ("What did the master say about the sword?", "en"),
        ("RAG 파이프라인에서 chunk size는 왜 중요한가?", "ko"),  # 영어 용어가 섞여도 한글이 30% 이상
        ("Explain 청킹 in RAG pipelines with overlap and size", "en"),
        ("1234 ...", "en"),  # 글자가 없으면 en
    ],
)
def test_detect_language(text: str, lang: str) -> None:
    assert detect_language(text) == lang


def test_chunk_index_exact_then_normalized_then_none() -> None:
    chunks = [chunk("첫 청크 본문.\n둘째 줄.", "c1"), chunk("second chunk body", "c2", "b.txt", None)]
    idx = ChunkIndex(chunks)
    assert idx.source_of("첫 청크 본문.\n둘째 줄.") == Source("c1", "a.pdf", 1)
    assert idx.source_of("  첫 청크 본문. 둘째 줄.  ") == Source("c1", "a.pdf", 1)  # 공백만 다르다
    assert idx.source_of("second   chunk body") == Source("c2", "b.txt", None)
    assert idx.source_of("없는 본문") is None
    assert idx.by_id["c2"] is chunks[1]


def test_sources_for_dedups_and_counts_missing() -> None:
    idx = ChunkIndex([chunk("가나다", "c1"), chunk("라마바", "c2")])
    sources, missing = sources_for(["가나다", "가나다", "없음", "라마바"], idx)
    assert [s.chunk_id for s in sources] == ["c1", "c2"] and missing == 1


def test_report_summary_lists_reasons() -> None:
    r = GenerateReport("ragas", requested=5, produced=3)
    r.skip("sample: ValueError: bad json")
    r.skip("sample: ValueError: bad json")
    r.skip("transform NERExtractor: LLMError: empty")
    r.notes.append("language=ko")
    text = r.summary()
    assert "requested=5  produced=3  skipped=3" in text
    assert "skipped x2: sample" in text and "skipped x1: transform NERExtractor" in text and "note: language=ko" in text


def test_get_generator_unknown_and_ragas_needs_embedding() -> None:
    settings = LLMSettings(llm=Endpoint("http://llm.test/v1", "qwen"))
    with pytest.raises(GenerateError, match="unknown generator"):
        get_generator("nope", settings)
    with pytest.raises(GenerateError, match="GOLDEN_EMBED"):
        get_generator("ragas", settings)


def test_generators_satisfy_protocol() -> None:
    from golden_set.generators.ragas_gen import RagasGenerator

    settings = LLMSettings(llm=Endpoint("http://llm.test/v1", "qwen"), embed=Endpoint("http://emb.test/v1", "bge"))
    g = get_generator("ragas", settings)
    assert isinstance(g, RagasGenerator) and isinstance(g, Generator) and g.name == "ragas"
