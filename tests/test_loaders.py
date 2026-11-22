from pathlib import Path

import pytest

from conftest import KO_TEXT
from golden_set.loaders import LoadError, Loader, TxtLoader
from golden_set.registry import load_path


def assert_common_meta(doc, path: Path, file_type: str, loader: str) -> None:
    assert doc.metadata["source"] == str(path)
    assert doc.metadata["file_type"] == file_type
    assert doc.metadata["loader"] == loader


def test_txt_utf8(txt_utf8: Path) -> None:
    docs = load_path(str(txt_utf8))
    assert len(docs) == 1
    assert docs[0].page_content == KO_TEXT
    assert_common_meta(docs[0], txt_utf8, "txt", "stdlib")
    assert "page" not in docs[0].metadata


def test_txt_cp949_is_read_by_retry(txt_cp949: Path) -> None:
    with pytest.raises(UnicodeDecodeError):
        txt_cp949.read_text(encoding="utf-8")  # utf-8로는 정말 안 읽히는 픽스처인지 확인
    docs = load_path(str(txt_cp949))
    assert docs[0].page_content == KO_TEXT


def test_txt_undecodable_raises_load_error(tmp_path: Path) -> None:
    p = tmp_path / "bad.txt"
    p.write_bytes(b"\xff\xff\xff\xff")
    with pytest.raises(LoadError):
        load_path(str(p))


def test_txt_missing_file_raises_load_error(tmp_path: Path) -> None:
    with pytest.raises(LoadError):
        load_path(str(tmp_path / "none.txt"))


def test_txt_loader_satisfies_protocol() -> None:
    assert isinstance(TxtLoader(), Loader)


# ---- 2단계: docx, pdf, pptx 기본 로더 ----

from conftest import DOCX_PARAGRAPHS, NOTE, PDF_PAGES, SLIDES, make_pptx
from golden_set.loaders import Docx2txtLoader, PyMuPDFLoader, PythonPptxLoader


def squash(text: str) -> str:
    """줄바꿈 위치는 도구마다 다르므로 공백을 모두 빼고 비교한다."""
    return "".join(text.split())


@pytest.mark.parametrize("loader", [Docx2txtLoader(), PyMuPDFLoader(), PythonPptxLoader()])
def test_default_loaders_satisfy_protocol(loader) -> None:
    assert isinstance(loader, Loader)
    assert loader.name and all(e.startswith(".") for e in loader.extensions)


def test_docx_contains_both_paragraphs(docx_file: Path) -> None:
    docs = load_path(str(docx_file))
    assert len(docs) == 1
    for paragraph in DOCX_PARAGRAPHS:
        assert paragraph in docs[0].page_content
    assert_common_meta(docs[0], docx_file, "docx", "docx2txt")
    assert "page" not in docs[0].metadata


def test_pdf_three_pages(pdf_file: Path) -> None:
    docs = load_path(str(pdf_file))
    assert len(docs) == 3
    assert [d.metadata["page"] for d in docs] == [1, 2, 3]
    for doc, expected in zip(docs, PDF_PAGES):
        assert squash(doc.page_content) == squash(expected)
        assert_common_meta(doc, pdf_file, "pdf", "pymupdf")


def test_pdf_blank_pages_are_kept(pdf_with_blank: Path) -> None:
    docs = load_path(str(pdf_with_blank))
    assert len(docs) == 4
    assert [bool(d.page_content.strip()) for d in docs] == [True, False, True, False]
    assert [d.metadata["page"] for d in docs] == [1, 2, 3, 4]


def test_pptx_two_slides_with_notes(pptx_file: Path) -> None:
    docs = load_path(str(pptx_file))
    assert len(docs) == 2
    assert [d.metadata["page"] for d in docs] == [1, 2]
    for doc, (title, body) in zip(docs, SLIDES):
        assert title in doc.page_content and body in doc.page_content
        assert_common_meta(doc, pptx_file, "pptx", "python-pptx")
    assert NOTE not in docs[0].page_content
    assert docs[1].page_content.endswith(NOTE)  # 노트는 본문 뒤에 붙는다


def test_pptx_blank_slide_is_kept(tmp_path: Path) -> None:
    docs = load_path(str(make_pptx(tmp_path / "blank.pptx", blank_slides=1)))
    assert len(docs) == 3
    assert docs[2].page_content == ""
    assert docs[2].metadata["page"] == 3


@pytest.mark.parametrize("name", ["empty.pdf", "empty.docx", "empty.pptx"])
def test_zero_byte_file_raises_load_error(tmp_path: Path, name: str) -> None:
    p = tmp_path / name
    p.touch()
    with pytest.raises(LoadError):
        load_path(str(p))
