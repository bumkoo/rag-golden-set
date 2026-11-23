"""pptx 로더: 기본 python-pptx."""

from typing import Any, Iterable

from langchain_core.documents import Document

from golden_set.loading.loaders.base import LoadError, make_doc


def _shape_texts(shapes: Iterable[Any]) -> list[str]:
    """도형 목록에서 텍스트를 순서대로 모은다. 그룹은 안으로 들어가고 표는 행마다 한 줄로 만든다."""
    texts: list[str] = []
    for shape in shapes:
        if hasattr(shape, "shapes"):  # 그룹 도형
            texts.extend(_shape_texts(shape.shapes))
        elif getattr(shape, "has_table", False):
            for row in shape.table.rows:
                texts.append("\t".join(cell.text for cell in row.cells))
        elif getattr(shape, "has_text_frame", False):
            texts.append(shape.text_frame.text)
    return [t for t in texts if t.strip()]


class PythonPptxLoader:
    """python-pptx로 슬라이드마다 Document 하나를 만들고 발표자 노트를 본문 뒤에 붙인다."""

    name = "python-pptx"
    extensions = (".pptx",)

    def load(self, path: str) -> list[Document]:
        """pptx 파일을 슬라이드별 Document 리스트로 읽는다."""
        try:
            from pptx import Presentation

            docs: list[Document] = []
            for i, slide in enumerate(Presentation(path).slides, start=1):
                parts = _shape_texts(slide.shapes)
                if slide.has_notes_slide:
                    frame = slide.notes_slide.notes_text_frame
                    if frame is not None and frame.text.strip():
                        parts.append(frame.text)
                docs.append(make_doc("\n\n".join(parts), path, self.name, page=i))
            return docs
        except Exception as e:
            raise LoadError(f"{self.name}: {type(e).__name__}: {e}") from e


class UnstructuredPptxLoader:
    """비교용 대안. unstructured의 partition_pptx 요소를 슬라이드별로 묶는다.

    unstructured는 노트를 그 슬라이드 본문보다 먼저 내보내고 본문과 구분해 주지 않으므로,
    이 로더에서는 노트가 본문 앞에 온다.
    """

    name = "unstructured"
    extensions = (".pptx",)

    def load(self, path: str) -> list[Document]:
        """pptx 파일을 슬라이드별 Document 리스트로 읽는다."""
        try:
            import os

            # unstructured는 import할 때 사용 통계를 외부로 보낸다. 문서 작업 중에는 끈다.
            os.environ.setdefault("DO_NOT_TRACK", "1")
            os.environ.setdefault("UNSTRUCTURED_DISABLE_NOTICE", "1")
            from unstructured.partition.pptx import partition_pptx

            elements = partition_pptx(filename=path, include_slide_notes=True, include_page_breaks=True)
            # 슬라이드 사이마다 PageBreak가 하나씩 나오므로 슬라이드 수는 PageBreak 수 + 1이다.
            # 텍스트가 없는 슬라이드는 요소가 없어서, 이렇게 세어야 빈 슬라이드를 남길 수 있다.
            slides: list[list[str]] = [[]]
            for element in elements:
                if type(element).__name__ == "PageBreak":
                    slides.append([])
                elif element.text and element.text.strip():
                    slides[-1].append(element.text)
            return [
                make_doc("\n\n".join(parts), path, self.name, page=i)
                for i, parts in enumerate(slides, start=1)
            ]
        except Exception as e:
            raise LoadError(f"{self.name}: {type(e).__name__}: {e}") from e
