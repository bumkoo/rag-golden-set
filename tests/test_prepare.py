"""전처리(clean, chunk)와 chunks.jsonl을 손으로 만든 Document로 검사한다."""

from pathlib import Path

import pytest
from langchain_core.documents import Document

from golden_set.prepare import ChunkSettings, CleanSettings, chunk_docs, clean_docs, read_chunks, write_chunks
from golden_set.prepare.chunk import chunk_text, make_chunk_id
from golden_set.prepare.clean import line_key

HEADER = "법제처  국가법령정보센터"
FOOTER = "형법 - 3 -"
BODY = ["제1조(목적) 이 법은 범죄와 형벌을 정한다.", "제2조(국내범) 본법은 대한민국영역내에서 죄를 범한 내국인과 외국인에게 적용한다."]


def page(text: str, n: int, source: str = "a.pdf") -> Document:
    return Document(page_content=text, metadata={"source": source, "file_type": "pdf", "loader": "t", "page": n})


def five_pages(header: str = HEADER, footer_pages: int = 5) -> list[Document]:
    docs = []
    for n in range(1, 6):
        footer = f"형법 - {n} -" if n <= footer_pages else f"끝 줄은 본문 {'가나다라마'[n - 1]}"  # 쪽마다 다른 글자
        docs.append(page(f"{header}\n{BODY[0]}\n{BODY[1]} 쪽 {n}\n{footer}", n))
    return docs


# ---- clean ----


def test_line_key_ignores_digits_and_whitespace() -> None:
    assert line_key(" 형법 -  3 - ") == line_key("형법 - 12 -") == "형법 - # -"
    assert line_key("가") != line_key("나")


def test_header_and_numbered_footer_removed_body_kept() -> None:
    cleaned, reports = clean_docs(five_pages())
    assert len(cleaned) == 5
    for n, doc in enumerate(cleaned, start=1):
        assert doc.page_content == f"{BODY[0]}\n{BODY[1]} 쪽 {n}"
        assert doc.metadata["page"] == n and doc.metadata["source"] == "a.pdf"
    (r,) = reports
    assert r.source == "a.pdf" and r.page_count == 5
    assert {(x.position, x.pattern, x.count) for x in r.removed} == {("head", line_key(HEADER), 5), ("tail", "형법 - # -", 5)}
    assert any(x.example == "형법 - 1 -" for x in r.removed)


def test_below_ratio_is_kept() -> None:
    docs = five_pages(footer_pages=2)  # 바닥글이 5쪽 중 2쪽에만 (40%)
    cleaned, (r,) = clean_docs(docs)
    assert [x.position for x in r.removed] == ["head"]
    assert cleaned[0].page_content.endswith("형법 - 1 -")
    assert cleaned[4].page_content.endswith("끝 줄은 본문 마")


def test_ratio_boundary_is_configurable() -> None:
    docs = five_pages(footer_pages=3)  # 60%
    _, (r,) = clean_docs(docs)
    assert {x.position for x in r.removed} == {"head", "tail"}
    _, (r,) = clean_docs(docs, CleanSettings(min_ratio=0.61))
    assert {x.position for x in r.removed} == {"head"}


def test_blank_lines_before_header_are_skipped() -> None:
    docs = [page(f"\n\n{HEADER}\n{BODY[0]} {n}\n{BODY[1]} {'가나다'[n - 1]}\n\n", n) for n in range(1, 4)]
    cleaned, _ = clean_docs(docs)
    assert cleaned[0].page_content == f"{BODY[0]} 1\n{BODY[1]} 가"


def test_single_line_pages_count_once() -> None:
    docs = [page(HEADER, n) for n in range(1, 4)]
    cleaned, (r,) = clean_docs(docs)
    assert [(x.position, x.count) for x in r.removed] == [("head", 3)]
    assert all(d.page_content == "" for d in cleaned)


def test_files_are_cleaned_separately_and_unpaged_docs_untouched() -> None:
    a = five_pages()
    b = [page(f"다른 머리글\n{BODY[1]}\n꼬리 {n}", n, "b.pptx") for n in range(1, 4)]
    txt = Document(page_content=f"{HEADER}\n{BODY[0]}", metadata={"source": "c.txt", "file_type": "txt", "loader": "t"})
    cleaned, reports = clean_docs(a + [txt] + b)
    assert len(cleaned) == 9 and cleaned[5] is txt
    assert {r.source: r.page_count for r in reports} == {"a.pdf": 5, "b.pptx": 3}
    assert cleaned[6].page_content == BODY[1]


def test_too_few_pages_are_left_alone() -> None:
    docs = five_pages()[:2]
    cleaned, (r,) = clean_docs(docs)
    assert cleaned == docs and r.removed == []
    _, (r,) = clean_docs(docs, CleanSettings(min_pages=2))
    assert r.removed


# ---- chunk ----

KO_SENTENCES = [f"제{n}조 강호의 규율은 무공이 아니라 신의에서 나온다고 장문인은 말했다." for n in range(1, 200)]
EN_SENTENCES = [f"Section {n}. The master never drew the sword, and the pupil never understood why." for n in range(1, 200)]


def test_chunks_respect_size_and_overlap() -> None:
    text = " ".join(KO_SENTENCES)
    st = ChunkSettings(size=300, overlap=60, min_chars=10)
    chunks = chunk_text(text, st)
    assert len(chunks) > 5
    assert all(len(c) <= 300 for c in chunks)
    for prev, nxt in zip(chunks, chunks[1:]):
        head = nxt.split(" 제")[0]  # 다음 청크의 첫 문장
        assert head in prev  # 겹침: 앞 청크 끝부분이 다음 청크 앞에 다시 나온다
        assert len(head) <= 60 + len(head)  # 겹침 상한은 문장 단위로 60자를 넘지 않는다
    joined = "".join(chunks)
    assert KO_SENTENCES[0] in chunks[0] and KO_SENTENCES[-1] in chunks[-1]
    assert all(s in joined for s in KO_SENTENCES)  # 문장이 빠지지 않는다


def test_cuts_at_sentence_boundary_not_mid_sentence() -> None:
    text = " ".join(EN_SENTENCES[:40])
    chunks = chunk_text(text, ChunkSettings(size=400, overlap=50, min_chars=10))
    assert len(chunks) > 5
    for c in chunks:
        assert c.startswith("Section") and c.endswith("why.")  # "Section 11." 의 마침표에서는 자르지 않는다


def test_fullwidth_sentence_end_and_newline_are_boundaries() -> None:
    text = "첫 문장이다。둘째 문장이다！\n셋째 문장이다？ " + "가" * 50
    from golden_set.prepare.chunk import split_units

    assert [body for _, body in split_units(text, ChunkSettings(size=30, overlap=0, min_chars=1))] == [
        "첫 문장이다。",
        "둘째 문장이다！",
        "셋째 문장이다？",
        "가" * 30,
        "가" * 20,
    ]


def test_paragraph_boundary_preferred() -> None:
    paras = ["가" * 500 + ".", "나" * 500 + ".", "다" * 500 + "."]
    chunks = chunk_text("\n\n".join(paras), ChunkSettings(size=1200, overlap=150, min_chars=10))
    assert chunks == ["\n\n".join(paras[:2]), paras[2]]  # 둘째 문단은 겹침 상한(150)보다 길어 다시 들어가지 않는다


def test_overlap_zero_means_no_repeat() -> None:
    text = " ".join(EN_SENTENCES[:40])
    chunks = chunk_text(text, ChunkSettings(size=400, overlap=0, min_chars=10))
    assert "".join(chunks).count("Section 1.") == 1


def test_long_sentence_is_hard_split() -> None:
    text = "가" * 2500
    chunks = chunk_text(text, ChunkSettings(size=1200, overlap=150))
    assert [len(c) for c in chunks] == [1200, 1200, 400]
    assert chunks[1].startswith(chunks[0][-150:])


def test_short_and_empty_chunks_are_dropped() -> None:
    assert chunk_text("") == []
    assert chunk_text("제목만 있는 슬라이드") == []
    assert chunk_text(" ".join("가" * 99)) == []  # 공백을 빼면 99자
    assert len(chunk_text(" ".join("가" * 100))) == 1


def test_bad_settings_rejected() -> None:
    with pytest.raises(ValueError):
        ChunkSettings(size=100, overlap=100)
    with pytest.raises(ValueError):
        ChunkSettings(size=0)


def test_chunk_docs_inherit_metadata_and_stable_ids() -> None:
    docs = [page(" ".join(KO_SENTENCES[:60]), 1, "dir/a.pdf"), page(" ".join(EN_SENTENCES[:60]), 2, "dir/a.pdf")]
    chunks = chunk_docs(docs)
    assert len(chunks) >= 4
    for c in chunks:
        assert c.metadata["source"] == "dir/a.pdf" and c.metadata["loader"] == "t"
        assert c.metadata["page"] in (1, 2)
        assert c.metadata["chunk_id"].startswith(f"a.pdf:p{c.metadata['page']}:{c.metadata['chunk_index']}:")
    ids = [c.metadata["chunk_id"] for c in chunks]
    assert len(set(ids)) == len(ids)
    assert ids == [c.metadata["chunk_id"] for c in chunk_docs(docs)]  # 다시 돌려도 같다
    assert make_chunk_id("dir/a.pdf", 1, 0) != make_chunk_id("other/a.pdf", 1, 0)  # 같은 이름, 다른 경로
    assert make_chunk_id("a.txt", None, 0).startswith("a.txt:p0:0:")


def test_chunk_boundaries_do_not_cross_pages() -> None:
    docs = [page("가" * 150 + ".", 1), page("나" * 150 + ".", 2)]
    chunks = chunk_docs(docs)
    assert [c.page_content for c in chunks] == ["가" * 150 + ".", "나" * 150 + "."]


# ---- chunks.jsonl ----


def test_chunks_jsonl_roundtrip(tmp_path: Path) -> None:
    docs = [page(" ".join(KO_SENTENCES[:40]), 1), page(" ".join(EN_SENTENCES[:40]), 2)]
    chunks = chunk_docs(docs)
    out = tmp_path / "chunks.jsonl"
    write_chunks(chunks, str(out))
    raw = out.read_text(encoding="utf-8")
    assert "강호의" in raw and "\\u" not in raw  # 한글 그대로
    back = read_chunks(str(out))
    assert [(c.page_content, c.metadata) for c in back] == [(c.page_content, c.metadata) for c in chunks]


def test_read_chunks_rejects_bad_row(tmp_path: Path) -> None:
    p = tmp_path / "chunks.jsonl"
    p.write_text('{"chunk_id": "x", "text": "본문"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="chunks.jsonl:1"):
        read_chunks(str(p))
