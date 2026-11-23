"""손으로 만든 Document 리스트로 지표마다 경계값을 검사한다."""

from dataclasses import fields

import pytest
from langchain_core.documents import Document

from golden_set.loading.validation import FileReport, Thresholds, validate_docs

GOOD = "가" * 60  # 기준을 모두 넘는 본문


def doc(text: str, file_type: str = "txt", page: int | None = None, **override) -> Document:
    meta: dict = {"source": f"a.{file_type}", "file_type": file_type, "loader": "t"}
    if page is not None:
        meta["page"] = page
    meta.update(override)
    return Document(page_content=text, metadata=meta)


def pages(texts: list[str], file_type: str = "pdf") -> list[Document]:
    return [doc(t, file_type, page=i) for i, t in enumerate(texts, start=1)]


def test_good_file_passes() -> None:
    r = validate_docs("a.txt", "t", [doc(GOOD)], elapsed_sec=0.25)
    assert isinstance(r, FileReport)
    assert r.passed and r.reasons == []
    assert (r.path, r.loader, r.file_type, r.doc_count, r.elapsed_sec) == ("a.txt", "t", "txt", 1, 0.25)


def test_doc_count_zero_fails() -> None:
    r = validate_docs("a.pdf", "t", [])
    assert r.doc_count == 0 and not r.passed
    assert any("doc_count" in x for x in r.reasons)
    assert (r.empty_ratio, r.avg_chars, r.broken_ratio, r.hangul_ratio) == (0, 0, 0, 0)


def test_empty_doc_boundary_is_20_chars_after_removing_whitespace() -> None:
    nineteen = " ".join("가" * 19) + "\n\n"  # 공백을 빼면 19자
    twenty = " ".join("가" * 20)
    assert validate_docs("a.pdf", "t", pages([nineteen, GOOD])).empty_ratio == 0.5
    assert validate_docs("a.pdf", "t", pages([twenty, GOOD])).empty_ratio == 0.0


@pytest.mark.parametrize("file_type", ["pdf", "pptx"])
def test_empty_ratio_boundary_paged(file_type: str) -> None:
    long = "가" * 200
    at_limit = validate_docs(f"a.{file_type}", "t", pages([""] * 3 + [long] * 7, file_type))
    assert at_limit.empty_ratio == pytest.approx(0.30) and at_limit.passed
    over = validate_docs(f"a.{file_type}", "t", pages([""] * 4 + [long] * 6, file_type))
    assert over.empty_ratio == pytest.approx(0.40) and not over.passed
    assert any("empty_ratio" in x for x in over.reasons)


@pytest.mark.parametrize("file_type", ["txt", "docx"])
def test_empty_ratio_must_be_zero_for_unpaged(file_type: str) -> None:
    long = "가" * 2000
    r = validate_docs(f"a.{file_type}", "t", [doc(long, file_type)] * 9 + [doc("", file_type)])
    assert r.empty_ratio == pytest.approx(0.1) and not r.passed
    assert r.reasons == ["empty_ratio 10.0% > 0.0%"]


def test_avg_chars_boundary() -> None:
    assert validate_docs("a.txt", "t", [doc("가" * 50)]).passed
    r = validate_docs("a.txt", "t", [doc("가" * 49)])
    assert r.avg_chars == 49 and not r.passed
    assert any("avg_chars" in x for x in r.reasons)
    assert validate_docs("a.pdf", "t", pages(["가" * 30, "가" * 70])).avg_chars == 50


def test_broken_ratio_boundary() -> None:
    at_limit = validate_docs("a.txt", "t", [doc("�" + "가" * 199)])
    assert at_limit.broken_ratio == pytest.approx(0.005) and at_limit.passed
    over = validate_docs("a.txt", "t", [doc("�" + "가" * 198)])
    assert over.broken_ratio > 0.005 and not over.passed
    assert any("broken_ratio" in x for x in over.reasons)


def test_broken_counts_control_chars_but_not_newline_or_tab() -> None:
    clean = validate_docs("a.txt", "t", [doc("가\n나\t다\r\n" * 20)])
    assert clean.broken_ratio == 0
    dirty = validate_docs("a.txt", "t", [doc("\x00\x07\x1b" + "가" * 97)])
    assert dirty.broken_ratio == pytest.approx(0.03)


def test_hangul_ratio_is_reported_not_judged() -> None:
    english = validate_docs("a.txt", "t", [doc("a" * 100)])
    assert english.hangul_ratio == 0 and english.passed
    mixed = validate_docs("a.txt", "t", [doc("가나다라마 abcde\n" * 10)])
    assert mixed.hangul_ratio == pytest.approx(0.5)  # 공백은 분모에서 뺀다
    jamo = validate_docs("a.txt", "t", [doc("ㄱㄴㄷ" * 30)])
    assert jamo.hangul_ratio == 0  # 낱자모는 음절이 아니다


@pytest.mark.parametrize("key", ["source", "file_type", "loader"])
def test_meta_missing_required_key_fails(key: str) -> None:
    d = doc(GOOD)
    del d.metadata[key]
    r = validate_docs("a.txt", "t", [doc(GOOD), d])
    assert not r.meta_ok and r.reasons == ["meta_ok false"]


def test_meta_page_required_only_for_pdf_and_pptx() -> None:
    assert validate_docs("a.txt", "t", [doc(GOOD)]).meta_ok
    assert validate_docs("a.docx", "t", [doc(GOOD, "docx")]).meta_ok
    assert not validate_docs("a.pdf", "t", [doc(GOOD, "pdf")]).meta_ok
    assert not validate_docs("a.pptx", "t", [doc(GOOD, "pptx")]).meta_ok
    assert not validate_docs("a.pdf", "t", [doc(GOOD, "pdf", page=0)]).meta_ok  # 1부터
    assert validate_docs("a.pdf", "t", [doc(GOOD, "pdf", page=1)]).meta_ok


def test_thresholds_can_be_overridden() -> None:
    docs = [doc("가" * 30)]
    assert not validate_docs("a.txt", "t", docs).passed
    assert validate_docs("a.txt", "t", docs, Thresholds(min_avg_chars=30)).passed
    strict = Thresholds(max_empty_ratio_paged=0.0)
    assert not validate_docs("a.pdf", "t", pages(["", GOOD * 3, GOOD * 3, GOOD * 3]), strict).passed


def test_multiple_reasons_are_all_listed() -> None:
    r = validate_docs("a.txt", "t", [Document(page_content="�")])
    assert len(r.reasons) == 4  # empty_ratio, avg_chars, broken_ratio, meta_ok


def test_thresholds_defaults_match_plan() -> None:
    th = Thresholds()
    assert (th.min_doc_count, th.empty_doc_chars, th.min_avg_chars) == (1, 20, 50)
    assert (th.max_empty_ratio_paged, th.max_empty_ratio_other, th.max_broken_ratio) == (0.30, 0.0, 0.005)
    assert {f.name for f in fields(th)} >= {"paged_types", "required_meta"}
