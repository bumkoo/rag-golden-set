"""픽스처 파일은 테스트가 직접 만든다. 저장소에 바이너리 샘플을 넣지 않는다."""

from pathlib import Path
from types import SimpleNamespace

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
_CHAPTERS = [
    ("문파의 창건", "첫 장문인 청운은 황하 기슭의 폐사에서 문파를 열었다. 그는 제자들에게 검보다 먼저 신의를 가르쳤고, 문규의 첫 조항을 '빚은 갚고 은혜는 잊지 않는다'로 정했다. 창건 첫해 겨울, 문파는 양식이 모자라 산 아래 마을에 쌀을 빌렸다."),
    ("사제의 갈등", "둘째 장문인 백리는 스승의 뜻을 따라 검을 뽑지 않았으나, 수제자 소천은 그것을 비겁이라 여겼다. 두 사람의 다툼은 무공이 아니라 마을에 갚지 못한 쌀 빚을 어떻게 처리할지에서 비롯되었다. 소천은 결국 문파를 떠났다."),
    ("은거와 귀환", "셋째 장문인 운하는 십 년 동안 산문을 닫았다. 그 사이 떠난 소천은 강호에서 이름을 얻었고, 돌아와 문파의 빚을 대신 갚았다. 운하는 그를 받아들였으나 장문인 자리는 넘기지 않았다."),
    ("강호의 변화", "넷째 장문인 소천은 문규를 고쳐 '검은 지키기 위해서만 뽑는다'는 조항을 더했다. 관가와의 관계가 달라져 문파는 처음으로 세금을 냈고, 제자 수는 서른에서 백으로 늘었다."),
    ("다섯째 장문인의 선택", "다섯째 장문인 설매는 문파의 재산을 마을에 나누고 산문을 다시 열었다. 그는 창건 때의 쌀 빚 이야기를 모든 제자에게 들려주며, 문파가 지켜야 할 것은 검법이 아니라 약속이라고 가르쳤다."),
]
HEADER_PAGES = [
    "문파 연대기  국가법령정보센터\n"
    + f"제{n}장 {title}\n{body}\n"
    + f"In chapter {n}, the sect's leader faced a choice between the sword and the promise, and the chronicle records that the promise prevailed.\n"
    + f"- {n} -"
    for n, (title, body) in enumerate(_CHAPTERS, start=1)
]  # 쪽마다 같은 머리글과 쪽 번호 바닥글. prepare의 머리글 제거 예시와 생성기 실제 호출 테스트용


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
            page.insert_textbox(pymupdf.Rect(50, 50, 550, 750), text, fontname="korea", fontsize=10)
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


# ---- 가짜 OpenAI 클라이언트 (LLM 서버 없이 ChatClient를 검사한다) ----


class FakeOpenAI:
    """chat.completions.create / embeddings.create 호출마다 미리 준 응답(또는 예외)을 차례로 돌려준다.

    동기와 비동기 양쪽 인터페이스를 모두 제공하므로 ChatClient의 client, aclient 어디에나 넣을 수 있다.
    응답이 다 떨어지면 마지막 응답을 반복한다. 받은 kwargs는 calls에 쌓인다.
    """

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.embeddings = SimpleNamespace(create=self._embed)

    def _next(self, kwargs):
        self.calls.append(kwargs)
        r = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(r, Exception):
            raise r
        return r

    def _create(self, **kwargs):
        return self._next(kwargs)

    def _embed(self, **kwargs):
        return self._next(kwargs)

    @property
    def as_async(self) -> "FakeAsyncOpenAI":
        """같은 응답 큐와 기록을 쓰는 비동기 인터페이스."""
        return FakeAsyncOpenAI(self)


class FakeAsyncOpenAI:
    def __init__(self, inner: FakeOpenAI):
        self.inner = inner
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.embeddings = SimpleNamespace(create=self._embed)

    async def _create(self, **kwargs):
        return self.inner._next(kwargs)

    async def _embed(self, **kwargs):
        return self.inner._next(kwargs)


def choice(content: str | None, finish: str = "stop", reasoning: str | None = None) -> SimpleNamespace:
    message = SimpleNamespace(content=content, model_extra={"reasoning_content": reasoning} if reasoning else {})
    return SimpleNamespace(message=message, finish_reason=finish)


def completion(*choices) -> SimpleNamespace:
    return SimpleNamespace(choices=list(choices))


def embedding_response(*vectors) -> SimpleNamespace:
    return SimpleNamespace(data=[SimpleNamespace(index=i, embedding=list(v)) for i, v in reversed(list(enumerate(vectors)))])


def fake_chat(*texts, **settings):
    """정해진 본문을 차례로 돌려주는 ChatClient. 동기·비동기 요청 모두 같은 큐를 쓴다."""
    from golden_set.llm import ChatClient, Endpoint, LLMSettings

    responses = [t if isinstance(t, Exception) else completion(choice(t)) for t in texts]
    fake = FakeOpenAI(*responses)
    ep = Endpoint("http://llm.test/v1", "qwen-test")
    return ChatClient(ep, LLMSettings(llm=ep, **settings), client=fake, aclient=fake.as_async), fake


def fake_embed(dim: int = 4):
    from golden_set.llm import EmbedClient, Endpoint

    class AnyEmbed(FakeOpenAI):
        def _next(self, kwargs):
            self.calls.append(kwargs)
            n = len(kwargs["input"])
            return embedding_response(*([[1.0] + [0.0] * (dim - 1)] * n))

    fake = AnyEmbed()
    return EmbedClient(Endpoint("http://emb.test/v1", "bge-test"), client=fake, aclient=fake.as_async), fake


def build_fixture_dir(root: Path) -> Path:
    """형식별 샘플과 실패 사례를 한 폴더에 깐다. cli 테스트와 README 출력 예시에 쓴다."""
    (root / "sub").mkdir(parents=True, exist_ok=True)
    (root / "ko_utf8.txt").write_text(KO_TEXT, encoding="utf-8")
    (root / "ko_cp949.txt").write_text(KO_TEXT, encoding="cp949")
    make_docx(root / "two_paragraphs.docx")
    make_pdf(root / "three_pages.pdf")
    make_pdf(root / "sub" / "with_blank.pdf", [PDF_PAGES[0], "", PDF_PAGES[2], ""])
    make_pdf(root / "with_header.pdf", HEADER_PAGES)
    make_pptx(root / "sub" / "two_slides.pptx")
    (root / "broken.pdf").touch()
    (root / "old.doc").touch()
    (root / "sheet.xlsx").touch()
    return root
