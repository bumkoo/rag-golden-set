"""픽스처 파일은 테스트가 직접 만든다. 저장소에 바이너리 샘플을 넣지 않는다."""

from pathlib import Path

import pytest

KO_TEXT = "강호에 떠도는 소문은 언제나 사실보다 빠르다. 객잔의 등불 아래에서 두 사람은 말없이 차를 마셨다.\nThe rumor travels faster than the truth."


@pytest.fixture
def txt_utf8(tmp_path: Path) -> Path:
    p = tmp_path / "ko_utf8.txt"
    p.write_text(KO_TEXT, encoding="utf-8")
    return p


@pytest.fixture
def txt_cp949(tmp_path: Path) -> Path:
    p = tmp_path / "ko_cp949.txt"
    p.write_text(KO_TEXT, encoding="cp949")
    return p


DOCX_PARAGRAPHS = ["첫째 문단입니다. 사부는 끝내 검을 뽑지 않았다.", "Second paragraph in English, mixed with 한국어."]
PDF_PAGES = [
    "첫째 쪽 본문입니다. 산문 밖에는 눈이 내리고 있었다. Page one body text for extraction.",
    "둘째 쪽 본문입니다. 제자는 스승의 뜻을 헤아리지 못했다. Page two body text for extraction.",
    "셋째 쪽 본문입니다. 봄이 오자 그는 다시 길을 떠났다. Page three body text for extraction.",
]
SLIDES = [
    ("첫 슬라이드: 문파의 내력", "창건 이래 삼대에 걸쳐 장문인이 바뀌었고, 그때마다 문규도 조금씩 달라졌다. History of the sect."),
    ("둘째 슬라이드: 사제 관계", "스승과 제자의 갈등은 무공이 아니라 신의의 문제에서 시작되었다. Conflict between master and pupil."),
]
NOTE = "발표자 노트: 여기서 질문을 받는다."


def make_docx(path: Path, paragraphs: list[str] = DOCX_PARAGRAPHS) -> Path:
    import docx

    d = docx.Document()
    for text in paragraphs:
        d.add_paragraph(text)
    d.save(str(path))
    return path


def make_pdf(path: Path, pages: list[str] = PDF_PAGES) -> Path:
    """쪽마다 한 줄을 넣은 pdf를 만든다. 빈 문자열은 빈 쪽이 된다."""
    import pymupdf

    pdf = pymupdf.open()
    for text in pages:
        page = pdf.new_page()
        if text:
            page.insert_textbox(pymupdf.Rect(50, 50, 550, 300), text, fontname="korea", fontsize=10)
    pdf.save(str(path))
    pdf.close()
    return path


def make_pptx(path: Path, slides: list[tuple[str, str]] = SLIDES, note_on_last: str = NOTE, blank_slides: int = 0) -> Path:
    from pptx import Presentation

    prs = Presentation()
    slide = None
    for title, body in slides:
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = title
        slide.placeholders[1].text = body
    if slide is not None and note_on_last:
        slide.notes_slide.notes_text_frame.text = note_on_last
    for _ in range(blank_slides):
        prs.slides.add_slide(prs.slide_layouts[6])
    prs.save(str(path))
    return path


@pytest.fixture
def docx_file(tmp_path: Path) -> Path:
    return make_docx(tmp_path / "two_paragraphs.docx")


@pytest.fixture
def pdf_file(tmp_path: Path) -> Path:
    return make_pdf(tmp_path / "three_pages.pdf")


@pytest.fixture
def pdf_with_blank(tmp_path: Path) -> Path:
    return make_pdf(tmp_path / "with_blank.pdf", [PDF_PAGES[0], "", PDF_PAGES[2], ""])


@pytest.fixture
def pptx_file(tmp_path: Path) -> Path:
    return make_pptx(tmp_path / "two_slides.pptx")


def build_fixture_dir(root: Path) -> Path:
    """형식별 샘플과 실패 사례를 한 폴더에 깐다. cli 테스트와 README 출력 예시에 쓴다."""
    (root / "sub").mkdir(parents=True, exist_ok=True)
    (root / "ko_utf8.txt").write_text(KO_TEXT, encoding="utf-8")
    (root / "ko_cp949.txt").write_text(KO_TEXT, encoding="cp949")
    make_docx(root / "two_paragraphs.docx")
    make_pdf(root / "three_pages.pdf")
    make_pdf(root / "sub" / "with_blank.pdf", [PDF_PAGES[0], "", PDF_PAGES[2], ""])
    make_pptx(root / "sub" / "two_slides.pptx")
    (root / "broken.pdf").touch()
    (root / "old.doc").touch()
    (root / "sheet.xlsx").touch()
    return root
