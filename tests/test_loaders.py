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


# ---- 4단계: 비교용 대안 로더 ----

from golden_set.loaders import PdfplumberLoader, PythonDocxLoader, UnstructuredPptxLoader


@pytest.mark.parametrize("loader", [PythonDocxLoader(), PdfplumberLoader(), UnstructuredPptxLoader()])
def test_alt_loaders_satisfy_protocol(loader) -> None:
    assert isinstance(loader, Loader)


def test_python_docx_contains_both_paragraphs_and_table(tmp_path: Path) -> None:
    import docx

    d = docx.Document()
    d.add_paragraph(DOCX_PARAGRAPHS[0])
    table = d.add_table(rows=1, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "문파", "화산파"
    d.add_paragraph(DOCX_PARAGRAPHS[1])
    p = tmp_path / "t.docx"
    d.save(str(p))

    docs = load_path(str(p), "python-docx")
    assert len(docs) == 1
    text = docs[0].page_content
    assert text.index(DOCX_PARAGRAPHS[0]) < text.index("문파\t화산파") < text.index(DOCX_PARAGRAPHS[1])
    assert_common_meta(docs[0], p, "docx", "python-docx")


def test_pdfplumber_pages_and_blank_pages(pdf_file: Path, pdf_with_blank: Path) -> None:
    docs = load_path(str(pdf_file), "pdfplumber")
    assert [d.metadata["page"] for d in docs] == [1, 2, 3]
    for doc, expected in zip(docs, PDF_PAGES):
        assert squash(doc.page_content) == squash(expected)
        assert_common_meta(doc, pdf_file, "pdf", "pdfplumber")
    blank = load_path(str(pdf_with_blank), "pdfplumber")
    assert [d.page_content for d in blank][1::2] == ["", ""] and len(blank) == 4


def test_unstructured_pptx_slides_notes_and_blank_slides(tmp_path: Path) -> None:
    pytest.importorskip("unstructured.partition.pptx")
    p = make_pptx(tmp_path / "u.pptx", blank_slides=2)
    docs = load_path(str(p), "unstructured")
    assert [d.metadata["page"] for d in docs] == [1, 2, 3, 4]
    for doc, (title, body) in zip(docs, SLIDES):
        assert title in doc.page_content and body in doc.page_content
        assert_common_meta(doc, p, "pptx", "unstructured")
    assert NOTE in docs[1].page_content and NOTE not in docs[0].page_content
    assert [d.page_content for d in docs[2:]] == ["", ""]


@pytest.mark.parametrize("name,loader", [("e.pdf", "pdfplumber"), ("e.docx", "python-docx"), ("e.pptx", "unstructured")])
def test_alt_loaders_wrap_errors(tmp_path: Path, name: str, loader: str) -> None:
    p = tmp_path / name
    p.touch()
    with pytest.raises(LoadError):
        load_path(str(p), loader)


# ---- .doc (내용이 RTF인 파일) ----

from golden_set.loaders import RtfDocLoader, UnsupportedError
from golden_set.loaders.doc import rtf_to_text


def rtf_escape(text: str) -> str:
    """한글을 법제처 파일과 같은 \\uN? 표기로 바꾼다."""
    return "".join(c if ord(c) < 128 else f"\\u{ord(c)}?" for c in text)


def make_rtf_doc(path: Path) -> Path:
    blob = b"\xff\xd8{\\par}Exif\x00}"  # 중괄호와 제어어처럼 보이는 바이트가 든 이진 그림 데이터
    body = (
        "{\\rtf1\\ansi\\ansicpg1252\\deff0{\\fonttbl{\\f0\\froman Times New Roman;}}"
        "{\\colortbl\\red0\\green0\\blue0;}"
        "{\\footer \\pard " + rtf_escape("바닥글 국가법령정보센터") + "{\\*\\shppict{\\pict\\jpegblip\n"
    ).encode("ascii") + b"\\bin" + str(len(blob)).encode() + b" " + blob + (
        "}}\\par}"
        "\\pard\\plain\\f0 " + rtf_escape("제1조(목적) 이 법은 A\\{B\\} 를 정한다.") + "\\par\r\n"
        "{\\b " + rtf_escape("제2조(정의)") + "}\\tab " + rtf_escape("①항 내용") + "\\par}"
    ).encode("ascii")
    path.write_bytes(body)
    return path


def test_rtf_doc_body_only(tmp_path: Path) -> None:
    p = make_rtf_doc(tmp_path / "law.doc")
    docs = load_path(str(p))
    assert len(docs) == 1
    assert docs[0].page_content == "제1조(목적) 이 법은 A{B} 를 정한다.\n제2조(정의)\t①항 내용\n"
    assert_common_meta(docs[0], p, "doc", "rtf")
    assert isinstance(RtfDocLoader(), Loader)


def test_rtf_codepage_bytes_are_decoded_as_pairs() -> None:
    encoded = "".join(f"\\'{b:02x}" for b in "한글".encode("cp949"))
    assert rtf_to_text(("{\\rtf1\\ansi\\ansicpg949 " + encoded + " ok}").encode("ascii")) == "한글 ok"


def test_rtf_unicode_fallback_chars_are_skipped() -> None:
    assert rtf_to_text(b"{\\rtf1\\uc1 \\u44032?\\u45208\\'3f\\uc2 \\u45796??x}") == "가나다x"
    assert rtf_to_text(b"{\\rtf1 \\u-21504?}") == "가"  # 음수는 16비트로 되돌린다 (U+AC00)


# ---- 검토 2: 서로게이트 쌍 ----


def test_rtf_surrogate_pair_becomes_one_character() -> None:
    text = rtf_to_text(rb"{\rtf1\ansi\ansicpg949\uc1 A\u-10179?\u-8704?B}")
    assert text == "A\U0001F600B"
    assert text.encode("utf-8") == "A\U0001F600B".encode("utf-8")


@pytest.mark.parametrize(
    "rtf,expected",
    [
        (rb"{\rtf1 A\u-10179?B}", "A\ufffdB"),  # 상위만
        (rb"{\rtf1 A\u-8704?B}", "A\ufffdB"),  # 하위만
        (rb"{\rtf1 A\u-8704?\u-10179?B}", "A\ufffd\ufffdB"),  # 순서가 뒤집힘
        (rb"{\rtf1 \u-10179? \u-8704?}", "\ufffd \ufffd"),  # 사이에 다른 글자
    ],
)
def test_rtf_lone_surrogate_becomes_replacement_char(rtf: bytes, expected: str) -> None:
    text = rtf_to_text(rtf)
    assert text == expected
    text.encode("utf-8")


@pytest.mark.parametrize("content", [b"", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1 binary word", b"plain text"])
def test_doc_that_is_not_rtf_is_unsupported(tmp_path: Path, content: bytes) -> None:
    p = tmp_path / "old.doc"
    p.write_bytes(content)
    with pytest.raises(UnsupportedError, match="^unsupported$"):
        load_path(str(p))


# ---- 검토 3, 4: txt의 BOM ----


def test_txt_utf8_bom_is_removed(tmp_path: Path) -> None:
    p = tmp_path / "bom.txt"
    p.write_bytes(b"\xef\xbb\xbf" + KO_TEXT.encode("utf-8"))
    docs = load_path(str(p))
    assert docs[0].page_content == KO_TEXT
    assert not docs[0].page_content.startswith("﻿")


@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-le", "utf-16-be"])
def test_txt_utf16_with_bom(tmp_path: Path, encoding: str) -> None:
    import codecs

    bom = {"utf-16-le": codecs.BOM_UTF16_LE, "utf-16-be": codecs.BOM_UTF16_BE}.get(encoding, b"")
    p = tmp_path / "utf16.txt"
    p.write_bytes(bom + KO_TEXT.encode(encoding))  # "utf-16"은 인코더가 BOM을 직접 붙인다
    docs = load_path(str(p))
    assert docs[0].page_content == KO_TEXT


def test_txt_utf16_without_bom_is_not_guessed(tmp_path: Path) -> None:
    p = tmp_path / "nobom.txt"
    p.write_bytes(KO_TEXT.encode("utf-16-le"))
    try:
        text = load_path(str(p))[0].page_content
    except LoadError:
        return
    assert text != KO_TEXT  # 읽히더라도 utf-16으로 추측해서 읽은 것은 아니다


def test_txt_broken_utf16_raises_load_error(tmp_path: Path) -> None:
    p = tmp_path / "odd.txt"
    p.write_bytes(b"\xff\xfe" + "가나다".encode("utf-16-le") + b"\x00")  # 홀수 바이트
    with pytest.raises(LoadError):
        load_path(str(p))


# ---- 검토 5: RTF 각주 ----


def test_rtf_footnote_is_kept_but_separated_by_newlines() -> None:
    text = rtf_to_text(rb"{\rtf1\ansi body{\footnote note text} end}")
    assert text == "body\nnote text\n end"
    assert "note text" in text.split("\n")
