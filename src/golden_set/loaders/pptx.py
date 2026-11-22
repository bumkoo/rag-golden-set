"""pptx 로더: 기본 python-pptx."""

from typing import Any, Iterable

from langchain_core.documents import Document

from golden_set.loaders.base import LoadError, make_doc


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
