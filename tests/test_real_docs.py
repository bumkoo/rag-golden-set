"""실제 문서로 하는 파싱 검증. 문서는 저장소에 넣지 않으므로 폴더를 환경 변수로 준다.

    GOLDEN_SET_REAL_DOCS=<폴더> pytest tests/test_real_docs.py -v

환경 변수가 없으면 전부 건너뛴다. 검사 방법은 "같은 내용을 다른 경로로 읽어 대조"다.
  pdf  : 로더 2종 대조, 조문 번호 연속성, 같은 법령의 doc과 대조
  doc  : 독립 구현(striprtf)과 대조, RTF 찌꺼기 없음, 조문 번호 연속성
  pptx : 파일 안 원본 XML과 슬라이드별 대조, 로더 2종 대조
"""

import os
import re
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree

import pytest

from golden_set import load_path
from lawtext import law_body, law_title, missing_articles, squash

ROOT = os.environ.get("GOLDEN_SET_REAL_DOCS", "")
pytestmark = pytest.mark.skipif(not ROOT, reason="GOLDEN_SET_REAL_DOCS 폴더가 지정되지 않음")


def files(ext: str) -> list[Path]:
    return sorted(Path(ROOT).rglob(f"*{ext}")) if ROOT else []


def ids(paths: list[Path]) -> list[str]:
    return [p.name[-24:] for p in paths]


PDFS, DOCS, PPTXS = files(".pdf"), files(".doc"), files(".pptx")


def test_real_docs_folder_has_files() -> None:
    assert PDFS or DOCS or PPTXS, f"{ROOT}에 pdf, doc, pptx가 하나도 없음"


# ---------------------------------------------------------------- pdf


@pytest.mark.parametrize("path", PDFS, ids=ids(PDFS))
def test_pdf_pages_are_numbered_and_not_empty(path: Path) -> None:
    import pymupdf

    docs = load_path(str(path))
    with pymupdf.open(str(path)) as pdf:
        assert len(docs) == pdf.page_count
    assert [d.metadata["page"] for d in docs] == list(range(1, len(docs) + 1))
    assert all(len(squash(d.page_content)) >= 20 for d in docs)
    assert "\ufffd" not in "".join(d.page_content for d in docs)


@pytest.mark.parametrize("path", PDFS, ids=ids(PDFS))
def test_pdf_two_loaders_extract_the_same_characters_on_every_page(path: Path) -> None:
    a, b = load_path(str(path), "pymupdf"), load_path(str(path), "pdfplumber")
    assert len(a) == len(b)
    different = [
        x.metadata["page"]
        for x, y in zip(a, b)
        if Counter(squash(x.page_content)) != Counter(squash(y.page_content))
    ]
    assert different == []


@pytest.mark.parametrize("path", PDFS, ids=ids(PDFS))
def test_pdf_two_loaders_agree_on_reading_order(path: Path) -> None:
    """머리글을 지우고 이어 붙인 본문 전체가 글자 순서까지 같아야 한다."""
    a, b = load_path(str(path), "pymupdf"), load_path(str(path), "pdfplumber")
    assert squash(law_body(a)) == squash(law_body(b))


@pytest.mark.parametrize("path", PDFS, ids=ids(PDFS))
def test_pdf_article_numbers_have_no_gap(path: Path) -> None:
    last, missing = missing_articles(law_body(load_path(str(path))))
    assert last > 0 and missing == []


def _doc_of_same_law(pdf: Path) -> Path | None:
    title = law_title(load_path(str(pdf)))
    for doc in DOCS:
        if law_title(load_path(str(doc))) == title:
            return doc
    return None


@pytest.mark.parametrize("path", PDFS, ids=ids(PDFS))
def test_pdf_matches_doc_of_the_same_law(path: Path) -> None:
    """형식도 파서도 다른 두 파일의 본문이 글자 단위로 같아야 한다."""
    doc = _doc_of_same_law(path)
    if doc is None:
        pytest.skip("같은 법령의 doc 파일이 폴더에 없음")
    assert squash(law_body(load_path(str(path)))) == squash(law_body(load_path(str(doc))))


# ---------------------------------------------------------------- doc (RTF)


@pytest.mark.parametrize("path", DOCS, ids=ids(DOCS))
def test_doc_has_no_rtf_residue(path: Path) -> None:
    docs = load_path(str(path))
    assert len(docs) == 1 and docs[0].metadata["file_type"] == "doc"
    text = docs[0].page_content
    assert re.findall(r"[\\{}]", text) == []  # 제어어나 중괄호가 본문에 새지 않았는지
    assert "\ufffd" not in text
    assert "Exif" not in text and "JFIF" not in text  # 그림의 이진 데이터가 섞이지 않았는지


@pytest.mark.parametrize("path", DOCS, ids=ids(DOCS))
def test_doc_matches_independent_rtf_parser(path: Path) -> None:
    """우리 파서와 striprtf의 결과가 같아야 한다. striprtf는 \\bin 블록을 못 넘겨서 먼저 떼어 준다."""
    striprtf = pytest.importorskip("striprtf.striprtf")
    raw = path.read_bytes()
    out, pos = bytearray(), 0
    for m in re.finditer(rb"\\bin(\d+) ?", raw):
        if m.start() < pos:
            continue
        out += raw[pos : m.start()]
        pos = m.end() + int(m.group(1))
    out += raw[pos:]
    reference = striprtf.rtf_to_text(out.decode("latin-1"), errors="ignore")
    assert squash(load_path(str(path))[0].page_content) == squash(reference)


@pytest.mark.parametrize("path", DOCS, ids=ids(DOCS))
def test_doc_article_numbers_have_no_gap(path: Path) -> None:
    last, missing = missing_articles(law_body(load_path(str(path))))
    assert last > 0 and missing == []


# ---------------------------------------------------------------- pptx

_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def slide_xml_texts(path: Path) -> list[str]:
    """python-pptx를 거치지 않고 zip 안의 슬라이드 XML에서 글자(<a:t>)를 발표 순서대로 꺼낸다."""
    with zipfile.ZipFile(path) as z:
        rels = {
            r.get("Id"): r.get("Target")
            for r in ElementTree.fromstring(z.read("ppt/_rels/presentation.xml.rels"))
        }
        presentation = ElementTree.fromstring(z.read("ppt/presentation.xml"))
        parts = ["ppt/" + rels[s.get(_R + "id")] for s in presentation.iter(_P + "sldId")]
        return [
            "".join(t.text or "" for t in ElementTree.fromstring(z.read(part)).iter(_A + "t"))
            for part in parts
        ]


@pytest.mark.parametrize("path", PPTXS, ids=ids(PPTXS))
@pytest.mark.parametrize("loader", ["python-pptx", "unstructured"])
def test_pptx_every_slide_has_exactly_the_characters_in_its_xml(path: Path, loader: str) -> None:
    if loader == "unstructured":
        pytest.importorskip("unstructured.partition.pptx")
    docs = load_path(str(path), loader)
    xml = slide_xml_texts(path)
    assert len(docs) == len(xml)
    assert [d.metadata["page"] for d in docs] == list(range(1, len(xml) + 1))
    different = [
        d.metadata["page"]
        for d, x in zip(docs, xml)
        if Counter(squash(d.page_content)) != Counter(squash(x))
    ]
    assert different == []


@pytest.mark.parametrize("path", PPTXS, ids=ids(PPTXS))
def test_pptx_every_text_box_survives_as_one_piece(path: Path) -> None:
    """텍스트 상자 하나의 글이 중간에 다른 상자의 글과 섞이지 않고 통째로 남아 있어야 한다."""
    from pptx import Presentation

    def boxes(shapes):
        for shape in shapes:
            if hasattr(shape, "shapes"):
                yield from boxes(shape.shapes)
            elif getattr(shape, "has_text_frame", False) and shape.text_frame.text.strip():
                yield shape.text_frame.text

    docs = load_path(str(path))
    broken = [
        (i, text[:30])
        for i, slide in enumerate(Presentation(str(path)).slides, start=1)
        for text in boxes(slide.shapes)
        if squash(text) not in squash(docs[i - 1].page_content)
    ]
    assert broken == []
